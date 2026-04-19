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
- `docs/api/integration-guide-v1.md` — практический гайд подключения к API v1.
- `docs/security/security-contours.md` — baseline/enhanced security контуры и go-live критерии.
- `docs/security/threat-model-v1.md` — threat model v1 с маппингом угроз и контролей.
- `docs/security/security-test-pack-v1.md` — минимальный security test pack и критерии выхода.
- `docs/engineering/render-engine-hardening.md` — план усиления рендер-движка и бенчмарки.
- `docs/observability/analytics-audit-model.md` — модель статистики и аудита.
- `docs/observability/otel-setup.md` — настройка OpenTelemetry tracing.
- `docs/observability/grafana/docx-v1-overview.dashboard.json` — готовый Grafana dashboard.
- `docs/data-model/schema-v1.sql` — черновой SQL-дизайн схемы данных v1.
- `docs/testing/test-strategy-v1.md` — полная тест-стратегия.
- `docs/e2e-test-cases.md` — каталог E2E кейсов.
- `docs/roadmap/industrial-v1-delivery-roadmap.md` — поэтапный delivery roadmap.
- `docs/ops/runbook-v1.md` — эксплуатационный runbook для v1.
- `docs/ops/canary-rollout-checklist-v1.md` — чеклист канареечного выката.
- `docs/ops/release-evidence-pack-v1.md` — шаблон release evidence pack для go-live sign-off.
- `perf/README.md` — нагрузочные smoke/burst сценарии на k6.
- `scripts/canary_smoke.sh` — автоматизированный canary smoke script.
- `scripts/backup_generation_store.sh` — создание backup bundle generation store + artifacts.
- `scripts/dr_restore_smoke.sh` — DR restore smoke для backup bundle.
- `scripts/security_smoke.sh` — security smoke для auth/size/rate-limit проверок.
- `scripts/generate_release_evidence.py` — генерация markdown evidence record по workflow run ссылкам.

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
- `DOCX_SERVICE_V1_AUTH_REQUIRED=1|0` (по умолчанию `1`)
- `DOCX_SERVICE_V1_BEARER_TOKEN=<token>` (Bearer-токен для `/api/v1/*`)
- `DOCX_SERVICE_STRICT_LEGACY_SCHEMA=1|0` (жёсткая проверка legacy schema по ключам)

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

## CI/CD заметки

- `CI` workflow проверяет backend/frontend, OpenAPI и dependency audits.
- `Deploy` workflow теперь делает повторную попытку деплоя при transient-сбоях.
- `SLO Smoke` workflow (`workflow_dispatch` + nightly schedule) поднимает backend и прогоняет k6 сценарии из `perf/k6`.
- `DR Smoke` workflow (`workflow_dispatch` + nightly schedule) проверяет backup/restore smoke сценарий и сохраняет backup bundle как artifact.
- `DAST Smoke` workflow (`workflow_dispatch` + nightly schedule) выполняет OWASP ZAP baseline и сохраняет security reports.
- `Security Smoke` workflow (`workflow_dispatch` + nightly schedule) проверяет базовые security anti-regressions (`401/413/429`).
- `Release Evidence` workflow (`workflow_dispatch`) генерирует release evidence markdown и сохраняет как artifact.

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
