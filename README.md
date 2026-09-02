# Creo Cleaner

Веб-сервис для очистки видео: удаляет метаданные и слегка перекодирует файл.

## Локальный запуск

```bash
cd ~/Projects/creo-cleaner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Нужен ffmpeg в системе:
# brew install ffmpeg   (macOS)

uvicorn app:app --reload --port 8000
```

Откройте http://127.0.0.1:8000/

## Docker

```bash
docker build -t creo-cleaner .
docker run --rm -p 8000:8000 creo-cleaner
```

## Деплой на Railway

1. Создайте репозиторий на GitHub и запушьте этот проект.
2. Зайдите на [railway.app](https://railway.app) → New Project → Deploy from GitHub.
3. Выберите репозиторий `creo-cleaner`.
4. Railway соберёт Dockerfile и выдаст публичный URL.
5. (Опционально) В Variables задайте `MAX_UPLOAD_MB=200`.

## API

- `GET /` — веб-форма
- `GET /health` — проверка живости
- `POST /process` — загрузка видео (multipart `file`), ответ — очищенный MP4

## CLI (processor.py)

```bash
python processor.py video.mp4
python processor.py image.jpg
```
