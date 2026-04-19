# OpenTelemetry Setup (v1)

## Overview
The backend now emits tracing spans for:
- incoming HTTP requests (including `/api/v1/*`),
- sync generation execution,
- async worker generation execution.

Prometheus metrics are available at `GET /metrics`.

## Environment Variables

- `DOCX_SERVICE_OTEL_ENABLED=1|0`  
  Enable/disable tracing initialization (default: `1`).

- `DOCX_SERVICE_OTEL_SERVICE_NAME=docx-service`  
  Service name for traces.

- `DOCX_SERVICE_OTEL_EXPORTER=otlp|console`  
  Exporter kind (default: `console`).

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`  
  OTLP HTTP endpoint used by exporter.

## Local smoke

1. Start backend.
2. Trigger a sync or async generation request.
3. For `console` exporter, check span output in backend logs.
4. For `otlp`, confirm traces in your collector backend.

## Operational notes

- Tracing is optional and can be disabled quickly with `DOCX_SERVICE_OTEL_ENABLED=0`.
- `/metrics` should be scraped by Prometheus and visualized in Grafana.
- Keep `X-Request-Id` in caller requests for easier trace correlation.
