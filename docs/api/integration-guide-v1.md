# Integration Guide: DOCX Service API v1

## Base Concepts
- All `/api/v1/*` endpoints require `Authorization: Bearer <token>`.
- Recommended headers:
  - `X-Request-Id`: caller correlation ID.
  - `Idempotency-Key`: dedupe key for repeated generation calls.

OpenAPI reference: `docs/api/openapi-v1.yaml`.

## 1) Sync generation

Request:
```bash
curl -X POST "http://localhost:8080/api/v1/generations/sync" \
  -H "Authorization: Bearer dev-v1-token" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: req-123" \
  -H "Idempotency-Key: idem-123" \
  -d '{
    "documentId": "11111111-1111-1111-1111-111111111111",
    "versionId": "22222222-2222-2222-2222-222222222222",
    "payload": { "field_1": "value" }
  }' --output result.docx
```

Response:
- `200` with DOCX binary.

## 2) Async generation

Submit:
```bash
curl -X POST "http://localhost:8080/api/v1/generations/async" \
  -H "Authorization: Bearer dev-v1-token" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: req-async-1" \
  -d '{
    "documentId": "11111111-1111-1111-1111-111111111111",
    "versionId": "22222222-2222-2222-2222-222222222222",
    "payload": { "field_1": "value" }
  }'
```

Accepted response (`202`):
```json
{
  "jobId": "33333333-3333-3333-3333-333333333333",
  "status": "queued",
  "statusUrl": "/api/v1/generations/33333333-3333-3333-3333-333333333333"
}
```

Poll status:
```bash
curl -H "Authorization: Bearer dev-v1-token" \
  "http://localhost:8080/api/v1/generations/33333333-3333-3333-3333-333333333333"
```

Fetch result after `succeeded`:
```bash
curl -H "Authorization: Bearer dev-v1-token" \
  "http://localhost:8080/api/v1/generations/33333333-3333-3333-3333-333333333333/result" \
  --output result.docx
```

## 3) Statistics endpoint

```bash
curl -H "Authorization: Bearer dev-v1-token" \
  "http://localhost:8080/api/v1/documents/11111111-1111-1111-1111-111111111111/statistics"
```

## 4) Error model

`/api/v1/*` uses standard error envelope:
```json
{
  "code": "http_422",
  "message": "Payload schema validation failed: ...",
  "requestId": "req-123"
}
```

Common codes:
- `http_401`: auth missing/invalid.
- `http_413`: request too large.
- `http_422`: validation failure.
- `http_429`: rate limit exceeded.
- `http_409`: async result not ready.

## 5) Operational recommendations
- Always send `X-Request-Id`.
- Use `Idempotency-Key` on retries.
- Prefer async for large templates/documents.
- Monitor status latency and failure rates.
