from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageEnhance


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


def process_video(input_path: str | Path, output_path: str | Path | None = None) -> Path:
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

    def run_ffmpeg(audio_args: list[str]) -> subprocess.CompletedProcess[str]:
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
            str(output_path),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    # Prefer copying audio (much faster); fall back to AAC if remux fails.
    result = run_ffmpeg(["-c:a", "copy"])
    if result.returncode != 0:
        result = run_ffmpeg(["-c:a", "aac", "-b:a", "128k"])

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "ffmpeg завершился с ошибкой")

    if not output_path.exists():
        raise RuntimeError("Выходной файл не был создан")

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
