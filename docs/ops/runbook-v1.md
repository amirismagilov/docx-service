# Runbook: DOCX Service v1

## Environment Variables

Core:
- `DOCX_SERVICE_GENERATION_STORE=sqlite|postgres`
- `DOCX_SERVICE_DB_PATH` (sqlite)
- `DOCX_SERVICE_PG_DSN` (postgres)
- `DOCX_SERVICE_RESULTS_DIR`

Security:
- `DOCX_SERVICE_V1_AUTH_REQUIRED=1|0`
- `DOCX_SERVICE_V1_BEARER_TOKEN`
- `DOCX_SERVICE_V1_MAX_REQUEST_BYTES`
- `DOCX_SERVICE_V1_RATE_LIMIT_PER_MINUTE`
- `DOCX_SERVICE_STRICT_LEGACY_SCHEMA`

## Health Checks
- Service: `GET /health`
- API docs: `GET /docs`
- v1 smoke: run one sync generation with known published document.

## Startup Checklist
1. Verify secrets and env variables.
2. Start dependencies (`postgres`, `redis`, `minio` as needed).
3. Start API process.
4. Confirm migration for generation store is applied (auto for postgres store).
5. Execute sync and async smoke requests.

## Incident: Elevated 5xx on generation
1. Check backend logs for `generation_error`.
2. Check storage path write permissions (`DOCX_SERVICE_RESULTS_DIR`).
3. Verify template version is published and payload schema valid.
4. Check queue processing (async jobs stuck in queued/running).

## Incident: 429 spikes
1. Validate caller behavior (retry storms).
2. Tune `DOCX_SERVICE_V1_RATE_LIMIT_PER_MINUTE`.
3. Ensure caller uses idempotency on retries.

## Incident: 413 spikes
1. Inspect payload size from client.
2. Move large submissions to async flow.
3. Tune `DOCX_SERVICE_V1_MAX_REQUEST_BYTES` if justified by policy.

## Recovery
- Async queued jobs are restored on service restart via durable generation store.
- If artifact files missing, status remains succeeded but result endpoint returns `410`.

## Backup and Restore (DR)

Backup bundle:
```bash
DOCX_SERVICE_GENERATION_STORE=sqlite \
DOCX_SERVICE_DB_PATH=./backend/data/production.db \
DOCX_SERVICE_RESULTS_DIR=./backend/data/results \
./scripts/backup_generation_store.sh
```

Restore smoke (SQLite):
```bash
BACKUP_DIR=/tmp/docx-service-backups/<timestamp> \
./scripts/dr_restore_smoke.sh
```

Restore smoke (Postgres):
```bash
BACKUP_DIR=/tmp/docx-service-backups/<timestamp> \
RESTORE_PG_DSN=postgresql://user:pass@localhost:5432/docx_restore \
./scripts/dr_restore_smoke.sh
```

Operational notes:
- Keep backup bundles encrypted-at-rest in target storage.
- Run backup daily and DR restore smoke at least weekly.
- Store the latest successful DR smoke evidence in release artifacts.

## Release Verification
1. Run backend tests (`pytest`).
2. Validate OpenAPI (`python scripts/validate_openapi.py`).
3. Run perf smoke (`k6` sync scenario).
4. Run security smoke (`scripts/security_smoke.sh`) on staging-like config.
5. Ensure latest DAST report (`dast-smoke.yml`) is available and reviewed.
6. Run DR restore smoke (`scripts/dr_restore_smoke.sh`).
7. Confirm CI pipeline green.
