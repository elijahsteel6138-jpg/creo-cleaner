from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from processor import process_video

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/creo-cleaner/uploads"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

app = FastAPI(title="Creo Cleaner")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _cleanup(*paths: Path) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


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
async def process_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> FileResponse:
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

        process_video(input_path, output_path)
    except HTTPException:
        _cleanup(job_dir)
        raise
    except FileNotFoundError as exc:
        _cleanup(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        _cleanup(job_dir)
        raise HTTPException(422, f"Ошибка обработки: {exc}") from exc
    except Exception as exc:
        _cleanup(job_dir)
        raise HTTPException(500, f"Не удалось обработать файл: {exc}") from exc

    background_tasks.add_task(_cleanup, job_dir)
    download_name = f"{Path(file.filename).stem}_clean.mp4"
    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=download_name,
        background=background_tasks,
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
