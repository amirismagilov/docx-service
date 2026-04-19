# Performance Harness (k6)

## Purpose
Operational smoke and burst checks for `/api/v1` generation endpoints.

## Prerequisites
- Running backend (`http://127.0.0.1:8080` by default).
- Published document version for test execution.
- `k6` installed locally.

## Required env vars
- `DOC_ID` — document UUID.
- `VERSION_ID` — published version UUID.
- `BEARER_TOKEN` — v1 bearer token (default in scripts: `dev-v1-token`).
- Optional: `BASE_URL`.

## Scenarios

### 1) Sync latency smoke
```bash
DOC_ID=<uuid> VERSION_ID=<uuid> BEARER_TOKEN=<token> \
k6 run perf/k6/generation-smoke.js
```

Checks:
- `p95 < 1000ms`
- failure rate `<1%`

### 2) Async burst and queue stability
```bash
DOC_ID=<uuid> VERSION_ID=<uuid> BEARER_TOKEN=<token> \
k6 run perf/k6/generation-async-burst.js
```

Checks:
- accepted async submit flow
- bounded failure rate during burst
- jobs complete via polling

## Notes
- Keep test templates synthetic and non-sensitive.
- Run in staging before release, not only locally.
