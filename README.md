# DOCX Generation Service MVP

Сервис генерации печатных форм в формате DOCX на стеке **React + Python (FastAPI)**.

## Что реализовано

- No-code управление шаблонами и версиями через API и UI.
- Визуальный редактор шаблона (schema + template body + mapping + DSL rules).
- Асинхронная генерация через очередь `asyncio` и фоновый worker.
- API-ключи для интеграций внешних систем.
- Webhook test endpoint и webhook уведомление после успешной генерации.
- Базовая модель сложных правил (условные блоки `if`) для крупных документов.

## Структура

- `backend/app` — FastAPI приложение (`main.py`, `generator.py`).
- `frontend` — React + Vite UI.
- `docker-compose.yml` — локальный запуск API/UI/Redis/MinIO.

## Запуск

### Вариант 1: Docker

```bash
cd docx-service
docker compose up --build
```

- API (OpenAPI / Swagger UI): [http://localhost:8080/docs](http://localhost:8080/docs)
- Web: [http://localhost:5175](http://localhost:5175)

### Вариант 2: Локально

Backend (Python 3.11+):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Тесты:

```bash
cd backend
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## API поток для интеграции

1. `POST /api/clients` — получить `apiKey`.
2. `POST /api/templates` — создать шаблон.
3. `POST /api/templates/{id}/versions` — добавить версию.
4. `POST /api/templates/{id}/versions/{versionId}/publish` — опубликовать.
5. `POST /api/jobs` с заголовком `X-Api-Key` — запустить генерацию.
6. `GET /api/jobs/{id}` — отслеживать статус.
7. `GET /api/jobs/{id}/result` — скачать файл.

## Ограничения текущего MVP

- Данные хранятся в памяти процесса (для production заменить на PostgreSQL).
- Генератор выдаёт файл с расширением `.docx` из текстового шаблона; для валидного OOXML-пакета можно подключить библиотеку работы с Open XML.
- Rate limiting и OAuth2 — отдельный этап hardening.
