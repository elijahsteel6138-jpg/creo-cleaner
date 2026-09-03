from __future__ import annotations

import random
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageEnhance

ProgressCallback = Callable[[int], None]


def process_image(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    if output_path is None:
        output_path = input_path.with_stem(f"{input_path.stem}_clean")
    else:
        output_path = Path(output_path)

    with Image.open(input_path) as img:
        orig_format = img.format if img.format else "JPEG"
        mode = "RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB"
        img_clean = Image.new(mode, img.size)
        img_clean.paste(img)

        w, h = img_clean.size
        crop_pixels = random.randint(1, 3)
        img_clean = img_clean.crop(
            (crop_pixels, crop_pixels, w - crop_pixels, h - crop_pixels)
        )

        angle = random.uniform(-0.5, 0.5)
        img_clean = img_clean.rotate(angle, resample=Image.BICUBIC, expand=False)

        brightness_factor = random.uniform(0.98, 1.02)
        contrast_factor = random.uniform(0.98, 1.02)
        img_clean = ImageEnhance.Brightness(img_clean).enhance(brightness_factor)
        img_clean = ImageEnhance.Contrast(img_clean).enhance(contrast_factor)

        if orig_format.upper() in ["JPEG", "JPG"]:
            if img_clean.mode != "RGB":
                img_clean = img_clean.convert("RGB")
            img_clean.save(output_path, "JPEG", quality=random.randint(92, 96), exif=b"")
        elif orig_format.upper() == "PNG":
            img_clean.save(output_path, "PNG", optimize=True)
        else:
            img_clean.save(output_path)

    return output_path


def probe_duration_seconds(input_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((result.stdout or "").strip()))
    except ValueError:
        return 0.0


def process_video(
    input_path: str | Path,
    output_path: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    if output_path is None:
        output_path = input_path.with_name(f"{input_path.stem}_clean.mp4")
    else:
        output_path = Path(output_path)

    crop_pixels = random.randint(1, 3)
    brightness = random.uniform(-0.02, 0.02)
    crf = random.randint(22, 24)

    vf = f"crop=iw-{crop_pixels * 2}:ih-{crop_pixels * 2}:{crop_pixels}:{crop_pixels}"
    if abs(brightness) > 0.001:
        vf += f",eq=brightness={brightness:.4f}"

    duration = probe_duration_seconds(input_path)
    if on_progress:
        on_progress(1)

    def run_ffmpeg(audio_args: list[str]) -> tuple[int, str]:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-map_metadata",
            "-1",
            "-metadata",
            "title=",
            "-metadata",
            "comment=",
            "-metadata",
            "description=",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            "ultrafast",
            "-threads",
            "0",
            *audio_args,
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        last_reported = -1
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("out_time_ms=") or not on_progress or duration <= 0:
                continue
            raw = line.split("=", 1)[1]
            if not raw.isdigit():
                continue
            out_ms = int(raw)
            percent = int(min(99, max(1, (out_ms / 1_000_000) / duration * 100)))
            if percent != last_reported:
                last_reported = percent
                on_progress(percent)

        stderr = ""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
        code = proc.wait()
        return code, stderr

    # Prefer copying audio (much faster); fall back to AAC if remux fails.
    code, stderr = run_ffmpeg(["-c:a", "copy"])
    if code != 0:
        code, stderr = run_ffmpeg(["-c:a", "aac", "-b:a", "128k"])

    if code != 0:
        raise RuntimeError((stderr or "").strip() or "ffmpeg завершился с ошибкой")

    if not output_path.exists():
        raise RuntimeError("Выходной файл не был создан")

    if on_progress:
        on_progress(100)

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python processor.py <файл>")
        sys.exit(1)

    path = Path(sys.argv[1])
    ext = path.suffix.lower()
    if ext in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
        out = process_video(path)
    else:
        out = process_image(path)
    print(f"[+] Готово: {out}")
