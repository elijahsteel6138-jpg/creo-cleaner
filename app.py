from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from processor import process_video

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/creo-cleaner/uploads"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "3600"))
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

app = FastAPI(title="Creo Cleaner")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@dataclass
class Job:
    id: str
    job_dir: Path
    input_path: Path
    output_path: Path
    download_name: str
    state: str = "queued"  # queued | running | done | error
    percent: int = 0
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def status_path(self) -> Path:
        return self.job_dir / "status.json"

    def persist(self) -> None:
        payload = {
            "job_id": self.id,
            "state": self.state,
            "percent": self.percent,
            "error": self.error,
            "download_name": self.download_name,
            "created_at": self.created_at,
        }
        try:
            self.status_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _cleanup(*paths: Path) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _purge_old_jobs() -> None:
    now = time.time()
    with _jobs_lock:
        stale = [
            job_id
            for job_id, job in _jobs.items()
            if now - job.created_at > JOB_TTL_SECONDS
        ]
        for job_id in stale:
            job = _jobs.pop(job_id, None)
            if job:
                _cleanup(job.job_dir)


def _set_progress(job: Job, percent: int) -> None:
    with _jobs_lock:
        if job.state in {"done", "error"}:
            return
        job.state = "running"
        job.percent = max(job.percent, min(100, int(percent)))
        job.persist()


def _run_job(job: Job) -> None:
    try:
        with _jobs_lock:
            job.state = "running"
            job.percent = max(job.percent, 1)
            job.persist()

        process_video(
            job.input_path,
            job.output_path,
            on_progress=lambda p: _set_progress(job, p),
        )

        with _jobs_lock:
            job.state = "done"
            job.percent = 100
            job.persist()
    except Exception as exc:  # noqa: BLE001
        with _jobs_lock:
            job.state = "error"
            job.error = str(exc)
            job.percent = 0
            job.persist()


def _load_job_from_disk(job_id: str) -> Job | None:
    job_dir = UPLOAD_DIR / job_id
    status_path = job_dir / "status.json"
    if not status_path.exists():
        return None
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    inputs = list(job_dir.glob("input.*"))
    if not inputs:
        return None
    job = Job(
        id=job_id,
        job_dir=job_dir,
        input_path=inputs[0],
        output_path=job_dir / "output.mp4",
        download_name=str(data.get("download_name") or f"{job_id}_clean.mp4"),
        state=str(data.get("state") or "error"),
        percent=int(data.get("percent") or 0),
        error=data.get("error"),
        created_at=float(data.get("created_at") or time.time()),
    )
    # Jobs left mid-flight after a crash are not recoverable on free hosts.
    if job.state in {"queued", "running"}:
        job.state = "error"
        job.error = (
            "Обработка прервалась (мало памяти на сервере). "
            "Сожмите видео или уменьшите разрешение и попробуйте снова."
        )
        job.persist()
    return job


def _get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            return job
    restored = _load_job_from_disk(job_id)
    if restored:
        with _jobs_lock:
            _jobs[job_id] = restored
        return restored
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(500, "index.html не найден")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/process")
async def process_upload(file: UploadFile = File(...)) -> dict[str, str]:
    _purge_old_jobs()

    if not file.filename:
        raise HTTPException(400, "Имя файла не указано")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Неподдерживаемый формат. Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / f"input{ext}"
    output_path = job_dir / "output.mp4"

    try:
        size = 0
        max_bytes = MAX_UPLOAD_MB * 1024 * 1024
        with input_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        413,
                        f"Файл слишком большой. Лимит: {MAX_UPLOAD_MB} MB",
                    )
                out.write(chunk)

        if size == 0:
            raise HTTPException(400, "Пустой файл")
    except HTTPException:
        _cleanup(job_dir)
        raise
    except Exception as exc:
        _cleanup(job_dir)
        raise HTTPException(500, f"Не удалось сохранить файл: {exc}") from exc

    job = Job(
        id=job_id,
        job_dir=job_dir,
        input_path=input_path,
        output_path=output_path,
        download_name=f"{Path(file.filename).stem}_clean.mp4",
        state="queued",
        percent=0,
    )
    job.persist()
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(target=_run_job, args=(job,), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/status")
def job_status(job_id: str) -> dict[str, object]:
    job = _get_job(job_id)
    if not job:
        raise HTTPException(
            404,
            "Задача не найдена. Сервер мог перезапуститься во время обработки — "
            "попробуйте файл поменьше.",
        )
    return {
        "job_id": job.id,
        "state": job.state,
        "percent": job.percent,
        "error": job.error,
    }


@app.get("/jobs/{job_id}/download")
def job_download(job_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    job = _get_job(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    with _jobs_lock:
        if job.state == "error":
            raise HTTPException(422, job.error or "Ошибка обработки")
        if job.state != "done" or not job.output_path.exists():
            raise HTTPException(409, "Файл ещё не готов")
        download_name = job.download_name
        output_path = job.output_path
        job_dir = job.job_dir
        _jobs.pop(job_id, None)

    background_tasks.add_task(_cleanup, job_dir)
    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=download_name,
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
