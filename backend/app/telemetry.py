from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_initialized = False


def init_tracing() -> bool:
    """
    Initialize OpenTelemetry tracing once.
    Controlled by env vars:
    - DOCX_SERVICE_OTEL_ENABLED=1|0
    - DOCX_SERVICE_OTEL_EXPORTER=otlp|console
    - DOCX_SERVICE_OTEL_SERVICE_NAME
    - OTEL_EXPORTER_OTLP_ENDPOINT (for otlp exporter)
    """
    global _initialized
    if _initialized:
        return True
    # Test sessions create/teardown many app lifecycles; disable tracing there to avoid exporter shutdown noise.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False

    enabled = os.environ.get("DOCX_SERVICE_OTEL_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return False

    service_name = os.environ.get("DOCX_SERVICE_OTEL_SERVICE_NAME", "docx-service")
    exporter_kind = os.environ.get("DOCX_SERVICE_OTEL_EXPORTER", "console").strip().lower()
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if exporter_kind == "console":
        span_exporter = ConsoleSpanExporter()
    else:
        span_exporter = OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    _initialized = True
    return True


def get_tracer(name: str = "docx-service"):
    return trace.get_tracer(name)
