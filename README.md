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

## Деплой на Render

1. Запушьте этот репозиторий на GitHub.
2. Зайдите на [render.com](https://render.com) → **New** → **Blueprint**.
3. Выберите репозиторий `creo-cleaner` (подхватит `render.yaml`).
4. Дождитесь сборки Docker-образа — URL будет вида `https://creo-cleaner.onrender.com`.

На free-плане сервис может «засыпать» после простоя (~15 мин): первый запрос после сна занимает 30–60 сек.

## API

- `GET /` — веб-форма
- `GET /health` — проверка живости
- `POST /process` — загрузка видео (multipart `file`), ответ — `{ "job_id": "..." }`
- `GET /jobs/{id}/status` — прогресс `{ "state", "percent", "error" }`
- `GET /jobs/{id}/download` — готовый MP4

## CLI (processor.py)

```bash
python processor.py video.mp4
python processor.py image.jpg
```
