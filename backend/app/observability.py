from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

HTTP_V1_REQUESTS_TOTAL = Counter(
    "docx_v1_http_requests_total",
    "Total number of HTTP requests to /api/v1 endpoints.",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)

HTTP_V1_REQUEST_DURATION_SECONDS = Histogram(
    "docx_v1_http_request_duration_seconds",
    "Duration of /api/v1 endpoint processing.",
    ["method", "path"],
    registry=REGISTRY,
)

GENERATION_TOTAL = Counter(
    "docx_generation_total",
    "Generation outcomes by mode and status.",
    ["mode", "status"],
    registry=REGISTRY,
)

GENERATION_DURATION_SECONDS = Histogram(
    "docx_generation_duration_seconds",
    "Generation duration in seconds.",
    ["mode"],
    registry=REGISTRY,
)

ASYNC_QUEUE_DEPTH = Gauge(
    "docx_async_queue_depth",
    "Current async generation queue depth.",
    registry=REGISTRY,
)


def metrics_payload() -> bytes:
    return generate_latest(REGISTRY)


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST
