# DOCX Service

Сервис для управления DOCX-шаблонами и генерации документов на стеке **React + FastAPI**.

## Что умеет сейчас

- Создавать, переименовывать и удалять шаблоны документов.
- Работать с версиями шаблонов и публиковать актуальную версию.
- Загружать исходный `.docx` и показывать его предпросмотр в браузере.
- Вставлять теги вида `{{field_id}}` прямо в DOCX по выделенному тексту.
- Поддерживать составные вставки: несколько тегов, произвольный текст, `\n` и `[[PARA_BREAK]]`.
- Заполнять шаблон данными формы и скачивать готовый DOCX.
- Сохранять шаблоны между перезапусками через `backend/data/store.json`.
- Предоставлять HTTP API для UI и внешних интеграций.

## Структура проекта

- `backend` — FastAPI API, DOCX-операции, тесты.
- `frontend` — React + Vite UI для списка документов, редактирования и предпросмотра.
- `docs` — рабочая документация по развитию продукта.
- `docker-compose.yml` — локальный запуск проекта в контейнерах.

### Документы для промышленной версии (v1)

- `docs/adr/0001-industrial-architecture.md` — целевая архитектура и ключевые решения.
- `docs/api/openapi-v1.yaml` — контракт API v1 для интеграции.
- `docs/security/security-contours.md` — baseline/enhanced security контуры и go-live критерии.
- `docs/engineering/render-engine-hardening.md` — план усиления рендер-движка и бенчмарки.
- `docs/observability/analytics-audit-model.md` — модель статистики и аудита.
- `docs/data-model/schema-v1.sql` — черновой SQL-дизайн схемы данных v1.
- `docs/testing/test-strategy-v1.md` — полная тест-стратегия.
- `docs/e2e-test-cases.md` — каталог E2E кейсов.
- `docs/roadmap/industrial-v1-delivery-roadmap.md` — поэтапный delivery roadmap.

## Быстрый старт

### Локально

Требования:

- Python 3.11+
- Node.js 20+

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Дополнительно для `v1` generation store:

- `DOCX_SERVICE_GENERATION_STORE=sqlite|postgres` (по умолчанию `sqlite`)
- `DOCX_SERVICE_DB_PATH=/path/to/production.db` (для sqlite)
- `DOCX_SERVICE_RESULTS_DIR=/path/to/generated` (каталог артефактов)
- `DOCX_SERVICE_PG_DSN=postgresql://...` (обязательно при `postgres`)

Frontend:

```bash
cd frontend
npm install
npm run dev
```

После запуска:

- API: [http://localhost:8080/docs](http://localhost:8080/docs)
- UI: [http://localhost:5175](http://localhost:5175)

### Docker Compose

```bash
docker compose up --build
```

## Полезные команды

Backend tests:

```bash
cd backend
pytest
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Основные сценарии API

### Управление шаблонами

- `GET /api/templates`
- `POST /api/templates/bootstrap-empty`
- `POST /api/templates/dkp-bootstrap`
- `GET /api/templates/{id}`
- `PATCH /api/templates/{id}`
- `DELETE /api/templates/{id}`

### Работа с версиями и DOCX

- `POST /api/templates/{id}/versions/{versionId}/upload-docx`
- `POST /api/templates/{id}/versions/{versionId}/publish`
- `GET /api/templates/{id}/versions/{versionId}/docx-file`
- `POST /api/templates/{id}/versions/{versionId}/render-sync`
- `POST /api/templates/{id}/versions/{versionId}/apply-tag`

## Замечания

- `[[PARA_BREAK]]` работает только когда замена применяется ко всему абзацу целиком.
- При изменении схемы полей или DOCX публикация версии снимается автоматически.
- Текущее хранилище файлов и метаданных подходит для локальной разработки и MVP, но не для production без отдельной БД и объектного хранилища.
