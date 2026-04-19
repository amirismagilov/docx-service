"""FastAPI port of the DOCX generation service (replaces the previous ASP.NET Core backend)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from app.dkp_fields import DKP_FIELDS, dkp_schema_json, dkp_starter_template_text
from app.docx_ops import (
    apply_docx_single_text_replacement,
    apply_docx_text_replacements,
    build_docx_from_plain_text,
    expand_replacement_escapes,
    extract_plain_text_from_docx,
    norm_tag_fragment,
    remove_docx_fragment,
    render_version_to_docx,
)
from app.generation_store import GenerationStore
from app.observability import (
    ASYNC_QUEUE_DEPTH,
    GENERATION_DURATION_SECONDS,
    GENERATION_TOTAL,
    HTTP_V1_REQUEST_DURATION_SECONDS,
    HTTP_V1_REQUESTS_TOTAL,
    metrics_content_type,
    metrics_payload,
)
from app.store_factory import create_generation_store
from app.store_persistence import default_store_path, persist_templates, try_load_templates


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


class CreateClientRequest(BaseModel):
    name: str
    webhook_url: str | None = Field(None, alias="webhookUrl")
    rate_limit_per_minute: int = Field(0, alias="rateLimitPerMinute")

    model_config = {"populate_by_name": True}


class CreateTemplateRequest(BaseModel):
    name: str
    schema_json_payload: str = Field(..., alias="schemaJson")
    created_by: str = Field("system", alias="createdBy")

    model_config = {"populate_by_name": True}


class CreateTemplateVersionRequest(BaseModel):
    docx_template_body: str = Field(..., alias="docxTemplateBody")
    bindings_json: str = Field(..., alias="bindingsJson")
    rules_json: str = Field(..., alias="rulesJson")

    model_config = {"populate_by_name": True}


class CreateGenerationJobRequest(BaseModel):
    template_version_id: uuid.UUID = Field(..., alias="templateVersionId")
    payload_json: str = Field(..., alias="payloadJson")

    model_config = {"populate_by_name": True}


class TestWebhookRequest(BaseModel):
    webhook_url: str = Field(..., alias="webhookUrl")

    model_config = {"populate_by_name": True}


class EditorTextBody(BaseModel):
    text: str


class ApplyTagBody(BaseModel):
    findText: str
    tagId: str = ""
    replacementTemplate: str | None = None
    replaceAll: bool = True
    occurrenceIndex: int | None = None
    tagSlotId: uuid.UUID | None = None


class RevertTagBody(BaseModel):
    tagSlotId: uuid.UUID
    findText: str
    occurrenceIndex: int


class CreateConditionalBlockBody(BaseModel):
    findTemplate: str
    occurrenceIndex: int
    conditionField: str
    equalsValue: str = ""
    branch: str = "if"
    elseGroupId: uuid.UUID | None = None


class PatchConditionalBlockBody(BaseModel):
    findTemplate: str | None = None
    occurrenceIndex: int | None = None
    conditionField: str | None = None
    equalsValue: str | None = None
    branch: str | None = None
    elseGroupId: uuid.UUID | None = None


class PatchTemplateRequest(BaseModel):
    name: str | None = None
    schema_json_payload: str | None = Field(None, alias="schemaJson")

    model_config = {"populate_by_name": True}


class BootstrapEmptyTemplateRequest(BaseModel):
    name: str = "Новый документ"


class GenerateSyncV1Request(BaseModel):
    documentId: uuid.UUID
    versionId: uuid.UUID | None = None
    payload: dict[str, Any]
    options: dict[str, Any] | None = None


class GenerateAsyncV1Request(BaseModel):
    documentId: uuid.UUID
    versionId: uuid.UUID | None = None
    payload: dict[str, Any]
    callback: dict[str, Any] | None = None
    ttlSeconds: int | None = None


# --- In-memory store (same role as EF InMemory DB) ---

TEMPLATE_STATUS_DRAFT = 0
TEMPLATE_STATUS_PUBLISHED = 1
TEMPLATE_STATUS_ARCHIVED = 2

VERSION_STATUS_DRAFT = 0
VERSION_STATUS_PUBLISHED = 1
VERSION_STATUS_ARCHIVED = 2

JOB_QUEUED = 0
JOB_RUNNING = 1
JOB_SUCCEEDED = 2
JOB_FAILED = 3
JOB_CANCELLED = 4

clients: dict[uuid.UUID, dict[str, Any]] = {}
clients_by_key_hash: dict[str, uuid.UUID] = {}

templates: dict[uuid.UUID, dict[str, Any]] = {}
template_versions: dict[uuid.UUID, dict[str, Any]] = {}
jobs: dict[uuid.UUID, dict[str, Any]] = {}

job_queue: asyncio.Queue[uuid.UUID] | None = None
worker_task: asyncio.Task | None = None
v1_job_queue: asyncio.Queue[uuid.UUID] | None = None
v1_worker_task: asyncio.Task | None = None
production_store: GenerationStore | None = None

STORE_PATH = default_store_path()
PROD_DB_PATH = Path(os.environ.get("DOCX_SERVICE_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "production.db")))
PROD_RESULTS_DIR = Path(
    os.environ.get("DOCX_SERVICE_RESULTS_DIR", str(Path(__file__).resolve().parent.parent / "data" / "generated"))
)
GENERATION_STORE_BACKEND = os.environ.get("DOCX_SERVICE_GENERATION_STORE", "sqlite")
POSTGRES_DSN = os.environ.get("DOCX_SERVICE_PG_DSN")
V1_AUTH_REQUIRED = os.environ.get("DOCX_SERVICE_V1_AUTH_REQUIRED", "1").strip().lower() not in {"0", "false", "no"}
V1_AUTH_TOKEN = os.environ.get("DOCX_SERVICE_V1_BEARER_TOKEN", "dev-v1-token")
STRICT_LEGACY_SCHEMA = os.environ.get("DOCX_SERVICE_STRICT_LEGACY_SCHEMA", "0").strip().lower() in {"1", "true", "yes"}
V1_MAX_REQUEST_BYTES = int(os.environ.get("DOCX_SERVICE_V1_MAX_REQUEST_BYTES", str(1024 * 1024)))
V1_RATE_LIMIT_PER_MINUTE = int(os.environ.get("DOCX_SERVICE_V1_RATE_LIMIT_PER_MINUTE", "120"))

_v1_rate_limit_lock = threading.Lock()
_v1_rate_limit_counters: dict[str, tuple[datetime, int]] = {}


def _persist_templates() -> None:
    persist_templates(STORE_PATH, templates, template_versions)


def _content_disposition(filename: str, disposition: str = "inline") -> str:
    """
    Формирует безопасный Content-Disposition для ASCII и Unicode имён.
    filename=... (ASCII fallback) + filename*=UTF-8''... (RFC5987).
    """
    safe_ascii = "".join(ch if ord(ch) < 128 and ch not in {'"', "\\"} else "_" for ch in filename) or "file.docx"
    encoded = quote(filename, safe="")
    return f'{disposition}; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded}'


def _invalidate_publication_for_version(template_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Снимает публикацию с версии после правок шаблона (текст / файл .docx)."""
    t = templates.get(template_id)
    v = template_versions.get(version_id)
    if not t or not v or v["template_id"] != template_id:
        return
    if v["status"] != VERSION_STATUS_PUBLISHED:
        return
    v["status"] = VERSION_STATUS_DRAFT
    v["published_at_utc"] = None
    if t.get("current_version_id") == version_id and t.get("status") == TEMPLATE_STATUS_PUBLISHED:
        t["status"] = TEMPLATE_STATUS_DRAFT


def _invalidate_publication_after_schema_change(template_id: uuid.UUID) -> None:
    """Схема полей общая для шаблона — снимаем публикацию со всех опубликованных версий этого шаблона."""
    t = templates.get(template_id)
    if not t:
        return
    changed = False
    for v in template_versions.values():
        if v["template_id"] != template_id:
            continue
        if v["status"] == VERSION_STATUS_PUBLISHED:
            v["status"] = VERSION_STATUS_DRAFT
            v["published_at_utc"] = None
            changed = True
    if changed and t.get("status") == TEMPLATE_STATUS_PUBLISHED:
        t["status"] = TEMPLATE_STATUS_DRAFT


def _template_to_summary(t: dict[str, Any]) -> dict[str, Any]:
    tid = t["id"]
    vers = [v for v in template_versions.values() if v["template_id"] == tid]
    vers.sort(key=lambda x: x["version"], reverse=True)
    return {
        "id": str(tid),
        "name": t["name"],
        "status": t["status"],
        "createdAtUtc": t["created_at_utc"].isoformat().replace("+00:00", "Z"),
        "currentVersionId": str(t["current_version_id"]) if t.get("current_version_id") else None,
        "versions": [
            {
                "id": str(v["id"]),
                "version": v["version"],
                "status": v["status"],
                "publishedAtUtc": v["published_at_utc"].isoformat().replace("+00:00", "Z")
                if v.get("published_at_utc")
                else None,
            }
            for v in vers
        ],
    }


async def _process_job(job_id: uuid.UUID, http_client: httpx.AsyncClient) -> None:
    job = jobs.get(job_id)
    if not job:
        return
    try:
        job["status"] = JOB_RUNNING
        ver = template_versions[job["template_version_id"]]
        fn, data = render_version_to_docx(
            docx_bytes=ver.get("docx_bytes"),
            docx_template_body=ver["docx_template_body"],
            bindings_json=ver["bindings_json"],
            rules_json=ver["rules_json"],
            payload_json=job["payload_json"],
            conditional_blocks=ver.get("conditional_blocks") or [],
        )
        job["result_bytes"] = data
        job["result_file_name"] = fn
        job["status"] = JOB_SUCCEEDED
        job["finished_at_utc"] = datetime.now(timezone.utc)

        cid = job["client_id"]
        cl = clients.get(cid)
        if cl and cl.get("webhook_url"):
            try:
                await http_client.post(
                    cl["webhook_url"],
                    json={
                        "eventType": "job.succeeded",
                        "jobId": str(job_id),
                        "at": job["finished_at_utc"].isoformat().replace("+00:00", "Z"),
                    },
                    timeout=30.0,
                )
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        job["status"] = JOB_FAILED
        job["error"] = str(exc)
        job["finished_at_utc"] = datetime.now(timezone.utc)


async def _worker_loop() -> None:
    assert job_queue is not None
    async with httpx.AsyncClient() as http_client:
        while True:
            job_id = await job_queue.get()
            try:
                await _process_job(job_id, http_client)
            finally:
                job_queue.task_done()


def _resolve_published_version_for_v1(document_id: uuid.UUID, version_id: uuid.UUID | None) -> dict[str, Any]:
    t = templates.get(document_id)
    if not t:
        raise HTTPException(status_code=404, detail="Document not found.")
    effective_version_id = version_id or t.get("current_version_id")
    if not effective_version_id:
        raise HTTPException(status_code=400, detail="Document has no active version.")
    v = template_versions.get(effective_version_id)
    if not v or v["template_id"] != document_id:
        raise HTTPException(status_code=404, detail="Version not found.")
    if v["status"] != VERSION_STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail="Publish document version before generation.")
    return v


def _enforce_v1_rate_limit(principal: str) -> None:
    now = datetime.now(timezone.utc)
    with _v1_rate_limit_lock:
        start, count = _v1_rate_limit_counters.get(principal, (now, 0))
        if now - start >= timedelta(minutes=1):
            _v1_rate_limit_counters[principal] = (now, 1)
            return
        if count >= V1_RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")
        _v1_rate_limit_counters[principal] = (start, count + 1)


def _require_v1_authorization(authorization: str | None = Header(None, alias="Authorization")) -> str:
    if not V1_AUTH_REQUIRED:
        principal = "auth-disabled"
        _enforce_v1_rate_limit(principal)
        return principal
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token.")
    token = parts[1].strip()
    if not token or not secrets.compare_digest(token, V1_AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token.")
    principal = "service-token"
    _enforce_v1_rate_limit(principal)
    return principal


def _validate_payload_for_version(version: dict[str, Any], payload: dict[str, Any]) -> None:
    t = templates.get(version["template_id"])
    schema_raw = (t or {}).get("schema_json")
    if not schema_raw:
        return
    try:
        parsed = json.loads(schema_raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Payload must be a JSON object.")

    # JSON Schema mode (industrial target).
    if isinstance(parsed, dict) and parsed.get("type") == "object":
        validator = Draft202012Validator(parsed)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            msg = "; ".join(e.message for e in errors[:3])
            raise HTTPException(status_code=422, detail=f"Payload schema validation failed: {msg}")
        return

    # Legacy schema mode (MVP map: {fieldId: {...}}).
    if isinstance(parsed, dict):
        allowed_keys = {str(k) for k in parsed.keys()}
        if STRICT_LEGACY_SCHEMA:
            unknown = sorted(set(payload.keys()) - allowed_keys)
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=f"Payload contains fields not declared in schema: {', '.join(unknown[:10])}",
                )


def _ensure_production_store() -> GenerationStore:
    global production_store
    if production_store is None:
        production_store = create_generation_store(
            backend=GENERATION_STORE_BACKEND,
            sqlite_db_path=PROD_DB_PATH,
            result_dir=PROD_RESULTS_DIR,
            pg_dsn=POSTGRES_DSN,
        )
    return production_store


async def _process_v1_generation_job(job_id: uuid.UUID) -> None:
    store = _ensure_production_store()
    rec = store.get_generation(job_id)
    started = perf_counter()
    try:
        store.mark_running(job_id)
        version = _resolve_published_version_for_v1(rec.document_id, rec.version_id)
        fn, data = render_version_to_docx(
            docx_bytes=version.get("docx_bytes"),
            docx_template_body=version["docx_template_body"],
            bindings_json=version["bindings_json"],
            rules_json=version["rules_json"],
            payload_json=rec.payload_json,
            conditional_blocks=version.get("conditional_blocks") or [],
        )
        store.mark_succeeded(job_id, fn, data)
        GENERATION_TOTAL.labels(mode="async", status="succeeded").inc()
        GENERATION_DURATION_SECONDS.labels(mode="async").observe(perf_counter() - started)
    except Exception as exc:  # noqa: BLE001
        store.mark_failed(job_id, "generation_error", str(exc))
        GENERATION_TOTAL.labels(mode="async", status="failed").inc()
        GENERATION_DURATION_SECONDS.labels(mode="async").observe(perf_counter() - started)


async def _v1_worker_loop() -> None:
    assert v1_job_queue is not None
    while True:
        job_id = await v1_job_queue.get()
        try:
            await _process_v1_generation_job(job_id)
        finally:
            v1_job_queue.task_done()
            ASYNC_QUEUE_DEPTH.set(v1_job_queue.qsize())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global templates, template_versions, worker_task, v1_worker_task, production_store, job_queue, v1_job_queue
    loaded = try_load_templates(STORE_PATH)
    if loaded:
        templates, template_versions = loaded
    job_queue = asyncio.Queue()
    v1_job_queue = asyncio.Queue()
    ASYNC_QUEUE_DEPTH.set(0)
    worker_task = asyncio.create_task(_worker_loop())
    production_store = create_generation_store(
        backend=GENERATION_STORE_BACKEND,
        sqlite_db_path=PROD_DB_PATH,
        result_dir=PROD_RESULTS_DIR,
        pg_dsn=POSTGRES_DSN,
    )
    for queued_id in production_store.list_queued_generation_ids():
        await v1_job_queue.put(queued_id)
    ASYNC_QUEUE_DEPTH.set(v1_job_queue.qsize())
    v1_worker_task = asyncio.create_task(_v1_worker_loop())
    yield
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    if v1_worker_task:
        v1_worker_task.cancel()
        try:
            await v1_worker_task
        except asyncio.CancelledError:
            pass
    if production_store:
        production_store.close()
        production_store = None
    job_queue = None
    v1_job_queue = None


app = FastAPI(title="DOCX Forms Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def v1_request_size_guard(request: Request, call_next):
    started = perf_counter()
    if request.url.path.startswith("/api/v1/") and request.method.upper() in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > V1_MAX_REQUEST_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "request_too_large",
                            "message": "Request payload exceeds maximum allowed size.",
                            "requestId": request.headers.get("x-request-id"),
                        },
                    )
            except ValueError:
                pass
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        elapsed = perf_counter() - started
        HTTP_V1_REQUESTS_TOTAL.labels(
            method=request.method.upper(),
            path=request.url.path,
            status_code=str(response.status_code),
        ).inc()
        HTTP_V1_REQUEST_DURATION_SECONDS.labels(
            method=request.method.upper(),
            path=request.url.path,
        ).observe(elapsed)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/v1/"):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": f"http_{exc.status_code}",
                "message": detail,
                "requestId": request.headers.get("x-request-id"),
            },
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Internal server error.",
                "requestId": request.headers.get("x-request-id"),
            },
        )
    raise exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/field-definitions/dkp")
def get_dkp_field_definitions() -> list[dict[str, Any]]:
    return DKP_FIELDS


@app.post("/api/templates/dkp-bootstrap")
def bootstrap_dkp_template() -> dict[str, Any]:
    """Создаёт шаблон ДКП с 10 полями и черновой версией с текстом и .docx."""
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    starter = dkp_starter_template_text()
    docx_bytes = build_docx_from_plain_text(starter)
    templates[tid] = {
        "id": tid,
        "name": "Договор купли-продажи (юрлица)",
        "status": TEMPLATE_STATUS_DRAFT,
        "schema_json": dkp_schema_json(),
        "created_by": "dkp-bootstrap",
        "created_at_utc": now,
        "current_version_id": None,
    }
    vid = uuid.uuid4()
    template_versions[vid] = {
        "id": vid,
        "template_id": tid,
        "version": 1,
        "status": VERSION_STATUS_DRAFT,
        "docx_template_body": starter,
        "bindings_json": "{}",
        "rules_json": "[]",
        "created_at_utc": now,
        "published_at_utc": None,
        "docx_bytes": docx_bytes,
        "source_file_name": None,
        "tag_slots": [],
        "conditional_blocks": [],
    }
    _persist_templates()
    return {
        "templateId": str(tid),
        "versionId": str(vid),
        "fields": DKP_FIELDS,
    }


@app.post("/api/clients")
def create_client(body: CreateClientRequest) -> dict[str, Any]:
    raw_key = "dks_" + secrets.token_hex(12)
    cid = uuid.uuid4()
    entry = {
        "id": cid,
        "name": body.name.strip(),
        "api_key_hash": _hash_key(raw_key),
        "rate_limit_per_minute": body.rate_limit_per_minute if body.rate_limit_per_minute > 0 else 120,
        "webhook_url": body.webhook_url,
    }
    clients[cid] = entry
    clients_by_key_hash[entry["api_key_hash"]] = cid
    return {
        "id": str(cid),
        "name": entry["name"],
        "rateLimitPerMinute": entry["rate_limit_per_minute"],
        "webhookUrl": entry["webhook_url"],
        "apiKey": raw_key,
    }


@app.get("/api/templates")
def list_templates() -> list[dict[str, Any]]:
    items = sorted(templates.values(), key=lambda t: t["created_at_utc"], reverse=True)
    return [_template_to_summary(t) for t in items]


@app.post("/api/templates")
def create_template(body: CreateTemplateRequest) -> JSONResponse:
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    t = {
        "id": tid,
        "name": body.name.strip(),
        "status": TEMPLATE_STATUS_DRAFT,
        "schema_json": body.schema_json_payload,
        "created_by": body.created_by,
        "created_at_utc": now,
        "current_version_id": None,
    }
    templates[tid] = t
    _persist_templates()
    payload = {
        "id": str(tid),
        "name": t["name"],
        "status": t["status"],
        "schemaJson": t["schema_json"],
        "createdBy": t["created_by"],
        "createdAtUtc": t["created_at_utc"].isoformat().replace("+00:00", "Z"),
        "currentVersionId": None,
    }
    return JSONResponse(status_code=201, content=payload, headers={"Location": f"/api/templates/{tid}"})


def _template_detail(template_id: uuid.UUID) -> dict[str, Any]:
    t = templates.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not Found")
    vers = [v for v in template_versions.values() if v["template_id"] == template_id]
    vers.sort(key=lambda x: x["version"], reverse=True)
    return {
        "id": str(t["id"]),
        "name": t["name"],
        "status": t["status"],
        "schemaJson": t["schema_json"],
        "createdBy": t["created_by"],
        "createdAtUtc": t["created_at_utc"].isoformat().replace("+00:00", "Z"),
        "currentVersionId": str(t["current_version_id"]) if t.get("current_version_id") else None,
        "versions": [
            {
                "id": str(v["id"]),
                "version": v["version"],
                "status": v["status"],
                "createdAtUtc": v["created_at_utc"].isoformat().replace("+00:00", "Z"),
                "publishedAtUtc": v["published_at_utc"].isoformat().replace("+00:00", "Z")
                if v.get("published_at_utc")
                else None,
                "sourceFileName": v.get("source_file_name"),
            }
            for v in vers
        ],
    }


@app.get("/api/templates/{template_id}")
def get_template(template_id: uuid.UUID) -> dict[str, Any]:
    return _template_detail(template_id)


@app.patch("/api/templates/{template_id}")
def patch_template(template_id: uuid.UUID, body: PatchTemplateRequest) -> dict[str, Any]:
    t = templates.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not Found")
    if body.name is not None:
        t["name"] = body.name.strip()
    if body.schema_json_payload is not None:
        t["schema_json"] = body.schema_json_payload
        _invalidate_publication_after_schema_change(template_id)
    _persist_templates()
    return _template_detail(template_id)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: uuid.UUID) -> Response:
    t = templates.pop(template_id, None)
    if not t:
        raise HTTPException(status_code=404, detail="Not Found")
    vids = [vid for vid, v in list(template_versions.items()) if v["template_id"] == template_id]
    for vid in vids:
        template_versions.pop(vid, None)
    for jid, job in list(jobs.items()):
        if job["template_version_id"] in vids:
            jobs.pop(jid, None)
    _persist_templates()
    return Response(status_code=204)


@app.post("/api/templates/bootstrap-empty")
def bootstrap_empty_template(body: BootstrapEmptyTemplateRequest) -> dict[str, Any]:
    """Минимальный шаблон без полей (пустая schema)."""
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    starter = ""
    templates[tid] = {
        "id": tid,
        "name": body.name.strip() or "Новый документ",
        "status": TEMPLATE_STATUS_DRAFT,
        "schema_json": "{}",
        "created_by": "bootstrap-empty",
        "created_at_utc": now,
        "current_version_id": None,
    }
    vid = uuid.uuid4()
    template_versions[vid] = {
        "id": vid,
        "template_id": tid,
        "version": 1,
        "status": VERSION_STATUS_DRAFT,
        "docx_template_body": starter,
        "bindings_json": "{}",
        "rules_json": "[]",
        "created_at_utc": now,
        "published_at_utc": None,
        "docx_bytes": None,
        "source_file_name": None,
        "tag_slots": [],
        "conditional_blocks": [],
    }
    _persist_templates()
    return {
        "templateId": str(tid),
        "versionId": str(vid),
        "fields": [],
    }


@app.post("/api/templates/{template_id}/versions")
def create_version(template_id: uuid.UUID, body: CreateTemplateVersionRequest) -> JSONResponse:
    t = templates.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not Found")
    vers = [v for v in template_versions.values() if v["template_id"] == template_id]
    next_v = 1 if not vers else max(x["version"] for x in vers) + 1
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    v = {
        "id": vid,
        "template_id": template_id,
        "version": next_v,
        "status": VERSION_STATUS_DRAFT,
        "docx_template_body": body.docx_template_body,
        "bindings_json": body.bindings_json,
        "rules_json": body.rules_json,
        "created_at_utc": now,
        "published_at_utc": None,
        "docx_bytes": None,
        "source_file_name": None,
        "tag_slots": [],
        "conditional_blocks": [],
    }
    template_versions[vid] = v
    _persist_templates()
    out = {
        "id": str(vid),
        "templateId": str(template_id),
        "version": next_v,
        "status": v["status"],
        "docxTemplateBody": v["docx_template_body"],
        "bindingsJson": v["bindings_json"],
        "rulesJson": v["rules_json"],
        "createdAtUtc": v["created_at_utc"].isoformat().replace("+00:00", "Z"),
        "publishedAtUtc": None,
    }
    return JSONResponse(
        status_code=201,
        content=out,
        headers={"Location": f"/api/templates/{template_id}/versions/{vid}"},
    )


def _set_version_published(template_id: uuid.UUID, version_id: uuid.UUID) -> datetime:
    """Помечает версию опубликованной и текущей для шаблона (без persist)."""
    t = templates.get(template_id)
    v = template_versions.get(version_id)
    if not t or not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    now = datetime.now(timezone.utc)
    v["status"] = VERSION_STATUS_PUBLISHED
    v["published_at_utc"] = now
    t["status"] = TEMPLATE_STATUS_PUBLISHED
    t["current_version_id"] = version_id
    return now


@app.post("/api/templates/{template_id}/versions/{version_id}/publish")
def publish_version(template_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, Any]:
    now = _set_version_published(template_id, version_id)
    t = templates[template_id]
    _persist_templates()
    return {
        "id": str(t["id"]),
        "currentVersionId": str(version_id),
        "publishedAtUtc": now.isoformat().replace("+00:00", "Z"),
    }


@app.post("/api/templates/{template_id}/versions/{version_id}/validate")
def validate_version(template_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    errors: list[str] = []
    has_body = bool((v.get("docx_template_body") or "").strip())
    has_bin = bool(v.get("docx_bytes"))
    if not has_body and not has_bin:
        errors.append("Template body is empty.")
    if v.get("docx_bytes"):
        patched = False
        if not (v.get("bindings_json") or "").strip():
            v["bindings_json"] = "{}"
            patched = True
        if not (v.get("rules_json") or "").strip():
            v["rules_json"] = "[]"
            patched = True
        if patched:
            _persist_templates()
    else:
        if not (v.get("bindings_json") or "").strip():
            errors.append("Bindings are required.")
        if not (v.get("rules_json") or "").strip():
            errors.append("Rules DSL is required.")
    return {"isValid": len(errors) == 0, "errors": errors}


@app.get("/api/templates/{template_id}/versions/{version_id}/editor-text")
def get_editor_text(template_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, str]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    if v.get("docx_bytes"):
        try:
            text = extract_plain_text_from_docx(v["docx_bytes"])
        except Exception:  # noqa: BLE001
            text = v.get("docx_template_body") or ""
    else:
        text = v.get("docx_template_body") or ""
    return {"text": text}


@app.put("/api/templates/{template_id}/versions/{version_id}/editor-text")
def put_editor_text(template_id: uuid.UUID, version_id: uuid.UUID, body: EditorTextBody) -> dict[str, bool]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    # Для бинарного DOCX-шаблона запрещаем plain-text overwrite:
    # иначе теряется исходная верстка (таблицы, стили, run-форматирование).
    if v.get("docx_bytes") and v.get("source_file_name"):
        raise HTTPException(
            status_code=409,
            detail="Нельзя сохранять текстовый шаблон поверх загруженного DOCX. Используйте редактирование тегов и повторную публикацию.",
        )
    v["docx_template_body"] = body.text
    v["docx_bytes"] = build_docx_from_plain_text(body.text)
    v["source_file_name"] = None
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    return {"ok": True}


@app.post("/api/templates/{template_id}/versions/{version_id}/upload-docx")
async def upload_docx_template(
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    v["docx_bytes"] = raw
    v["source_file_name"] = file.filename or "template.docx"
    v["tag_slots"] = []
    try:
        v["docx_template_body"] = extract_plain_text_from_docx(raw)
    except Exception:  # noqa: BLE001
        pass
    _set_version_published(template_id, version_id)
    _persist_templates()
    return {"ok": True, "fileName": v["source_file_name"]}


def _try_single_replace_with_fallbacks(
    docx_bytes: bytes,
    find_text: str,
    token: str,
    preferred_occurrence: int | None,
    max_scan_occurrences: int = 256,
) -> tuple[bytes, bool, int | None]:
    """
    Пытается заменить фрагмент сначала по preferred_occurrence, затем линейным сканом.
    Возвращает (updated_bytes, ok, used_occurrence).
    """
    tried: set[int] = set()
    if preferred_occurrence is not None and preferred_occurrence >= 0:
        tried.add(preferred_occurrence)
        updated, ok = apply_docx_single_text_replacement(docx_bytes, find_text, token, preferred_occurrence)
        if ok:
            return updated, True, preferred_occurrence

    for occ in range(max_scan_occurrences):
        if occ in tried:
            continue
        updated, ok = apply_docx_single_text_replacement(docx_bytes, find_text, token, occ)
        if ok:
            return updated, True, occ

    return docx_bytes, False, None


def _list_occurrence_indices_for_text(docx_bytes: bytes, find_text: str, max_scan_occurrences: int = 512) -> list[int]:
    """Возвращает список существующих occurrenceIndex для find_text в текущем DOCX."""
    if not find_text:
        return []
    probe_token = "__CURSOR_PROBE__"
    out: list[int] = []
    for occ in range(max_scan_occurrences):
        _updated, ok = apply_docx_single_text_replacement(docx_bytes, find_text, probe_token, occ)
        if not ok:
            break
        out.append(occ)
    return out


def _resync_tag_slots(v: dict[str, Any]) -> None:
    """
    Синхронизирует current_occurrence_index для всех слотов с фактическим DOCX
    и удаляет «висячие» слоты, для которых текущий шаблон больше не найден.
    """
    docx_bytes = v.get("docx_bytes")
    if not docx_bytes:
        return
    slots: list[dict[str, Any]] = v.setdefault("tag_slots", [])
    if not slots:
        return

    slots_by_template: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in slots:
        slots_by_template[s["current_template"]].append(s)

    kept: list[dict[str, Any]] = []
    for template, group in slots_by_template.items():
        group_sorted = sorted(group, key=lambda s: (s.get("created_at_utc") or datetime.min.replace(tzinfo=timezone.utc)))
        occs = _list_occurrence_indices_for_text(docx_bytes, template)
        assign_count = min(len(group_sorted), len(occs))
        for idx in range(assign_count):
            slot = group_sorted[idx]
            slot["current_occurrence_index"] = occs[idx]
            kept.append(slot)
        # Лишние слоты (без фактического вхождения) отбрасываем как устаревшие.

    slots[:] = kept


def _conditional_find_candidates(find_template: str) -> list[str]:
    base = find_template.replace("\r\n", "\n").replace("\r", "\n")
    candidates: list[str] = []
    variants = [
        base,
        norm_tag_fragment(base),
        re.sub(r"[^\S\r\n]*\n[^\S\r\n]*", "\n", norm_tag_fragment(base)).strip(),
        re.sub(r"\n{2,}", "\n", re.sub(r"[^\S\r\n]*\n[^\S\r\n]*", "\n", norm_tag_fragment(base))).strip(),
    ]
    for v in variants:
        if v and v not in candidates:
            candidates.append(v)
    return candidates


def _resolve_conditional_block_target(docx_bytes: bytes, find_template: str, occurrence_index: int) -> tuple[str, int]:
    if not find_template:
        raise HTTPException(status_code=400, detail="findTemplate не должен быть пустым.")
    if occurrence_index < 0:
        raise HTTPException(status_code=400, detail="occurrenceIndex должен быть >= 0.")

    def _is_large_fragment(s: str) -> bool:
        normalized = norm_tag_fragment(s).strip()
        non_empty_lines = [x for x in (ln.strip() for ln in normalized.split("\n")) if x]
        return len(normalized) > 600 or len(non_empty_lines) > 8

    for candidate in _conditional_find_candidates(find_template):
        is_large = _is_large_fragment(candidate)
        if not is_large:
            probe_token = "__CURSOR_CONDITIONAL_PROBE__"
            _updated, ok, used_occ = _try_single_replace_with_fallbacks(
                docx_bytes,
                candidate,
                probe_token,
                preferred_occurrence=occurrence_index,
                max_scan_occurrences=256,
            )
            if ok and used_occ is not None:
                return candidate, used_occ

        _updated_large, ok_large = remove_docx_fragment(docx_bytes, candidate, occurrence_index)
        if ok_large:
            return candidate, occurrence_index

        # Для больших фрагментов ограничиваем fallback-скан, иначе создание блока слишком медленное.
        max_scan = 48 if is_large else 256
        for occ in range(max_scan):
            if occ == occurrence_index:
                continue
            _updated_large, ok_large = remove_docx_fragment(docx_bytes, candidate, occ)
            if ok_large:
                return candidate, occ
    raise HTTPException(
        status_code=404,
        detail="Фрагмент условного блока не найден в DOCX по findTemplate/occurrenceIndex.",
    )


def _conditional_block_to_api(b: dict[str, Any]) -> dict[str, Any]:
    created = b.get("created_at_utc")
    group = b.get("else_group_id")
    return {
        "id": str(b["id"]),
        "findTemplate": b["find_template"],
        "occurrenceIndex": b["occurrence_index"],
        "conditionField": b["condition_field"],
        "equalsValue": b.get("equals_value", ""),
        "branch": b.get("branch", "if"),
        "elseGroupId": str(group) if group else None,
        "createdAtUtc": created.isoformat().replace("+00:00", "Z") if created else None,
    }


def _validate_conditional_branch(value: str) -> str:
    v = (value or "if").strip().lower()
    if v not in {"if", "else"}:
        raise HTTPException(status_code=400, detail="branch должен быть 'if' или 'else'.")
    return v


@app.post("/api/templates/{template_id}/versions/{version_id}/apply-tag")
def apply_tag_in_docx(template_id: uuid.UUID, version_id: uuid.UUID, body: ApplyTagBody) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    docx_bytes = v.get("docx_bytes")
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="Для этой версии нет загруженного DOCX.")
    tag_id = body.tagId.strip()
    replacement_template = (body.replacementTemplate or "").strip()
    if replacement_template:
        token = replacement_template
    else:
        if not tag_id:
            raise HTTPException(status_code=400, detail="Укажите id тега или replacementTemplate.")
        token = "{{" + tag_id + "}}"

    slots: list[dict[str, Any]] = v.setdefault("tag_slots", [])
    returned_slot_id: uuid.UUID | None = None
    stored_template = expand_replacement_escapes(token)

    if body.replaceAll:
        if body.tagSlotId is not None:
            raise HTTPException(status_code=400, detail="tagSlotId не используется при replaceAll.")
        find_text = body.findText.strip()
        if not find_text:
            raise HTTPException(status_code=400, detail="Укажите текст для поиска.")
        replacements = {find_text: token}
        updated = apply_docx_text_replacements(docx_bytes, replacements)
        if updated == docx_bytes:
            raise HTTPException(status_code=404, detail="Текст для замены не найден в документе или операция не поддержана в текущем контексте.")
    else:
        find_for_replace: str
        occ_eff: int
        if body.tagSlotId is not None:
            slot = next((s for s in slots if s["id"] == body.tagSlotId), None)
            if slot is None:
                raise HTTPException(status_code=404, detail="Слот тега не найден.")
            find_for_replace = slot["current_template"]
            oix = slot.get("current_occurrence_index")
            if oix is not None:
                occ_eff = int(oix)
            elif body.occurrenceIndex is not None and body.occurrenceIndex >= 0:
                occ_eff = body.occurrenceIndex
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Для слота не задан индекс вхождения. Обновите страницу.",
                )
        else:
            find_text = body.findText.strip()
            if not find_text:
                raise HTTPException(status_code=400, detail="Укажите текст для поиска.")
            if body.occurrenceIndex is None or body.occurrenceIndex < 0:
                raise HTTPException(status_code=400, detail="Укажите корректный occurrenceIndex (0-based) для точечной замены.")
            find_for_replace = find_text
            occ_eff = body.occurrenceIndex

        updated, ok = apply_docx_single_text_replacement(docx_bytes, find_for_replace, token, occ_eff)
        used_occ = occ_eff
        if not ok and body.tagSlotId is not None:
            # При редактировании по слоту допускаем рассинхрон индекса/форматирования:
            # пробуем найти то же значение слота по другим вхождениям.
            updated, ok, used_alt = _try_single_replace_with_fallbacks(docx_bytes, find_for_replace, token, occ_eff)
            if ok and used_alt is not None:
                used_occ = used_alt
        if not ok and body.tagSlotId is not None:
            # Финальный fallback: пробуем клиентский findText (если он был передан).
            client_find = body.findText.strip()
            if client_find:
                preferred = body.occurrenceIndex if body.occurrenceIndex is not None and body.occurrenceIndex >= 0 else None
                updated, ok, used_alt = _try_single_replace_with_fallbacks(docx_bytes, client_find, token, preferred)
                if ok and used_alt is not None:
                    used_occ = used_alt
        if not ok:
            raise HTTPException(status_code=404, detail="Выделенный фрагмент не найден в документе для точечной замены или операция не поддержана в текущем контексте.")
        if body.tagSlotId is not None:
            slot = next((s for s in slots if s["id"] == body.tagSlotId), None)
            assert slot is not None
            slot["current_template"] = stored_template
            slot["current_occurrence_index"] = used_occ
            returned_slot_id = slot["id"]
        else:
            new_id = uuid.uuid4()
            find_plain = body.findText.strip()
            slots.append(
                {
                    "id": new_id,
                    "original_plain_text": find_plain,
                    "current_template": stored_template,
                    "current_occurrence_index": occ_eff,
                    "created_at_utc": datetime.now(timezone.utc),
                }
            )
            returned_slot_id = new_id

    v["docx_bytes"] = updated
    _resync_tag_slots(v)
    try:
        v["docx_template_body"] = extract_plain_text_from_docx(updated)
    except Exception:  # noqa: BLE001
        pass
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    out: dict[str, Any] = {"ok": True, "tag": stored_template}
    if returned_slot_id is not None:
        out["tagSlotId"] = str(returned_slot_id)
    return out


@app.get("/api/templates/{template_id}/versions/{version_id}/tag-slots")
def list_tag_slots(template_id: uuid.UUID, version_id: uuid.UUID) -> list[dict[str, Any]]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    slots = v.get("tag_slots") or []
    out: list[dict[str, Any]] = []
    for s in slots:
        created = s.get("created_at_utc")
        out.append(
            {
                "id": str(s["id"]),
                "originalPlainText": s["original_plain_text"],
                "currentTemplate": s["current_template"],
                "currentOccurrenceIndex": s.get("current_occurrence_index"),
                "createdAtUtc": created.isoformat().replace("+00:00", "Z") if created else None,
            }
        )
    return out


@app.get("/api/templates/{template_id}/versions/{version_id}/conditional-blocks")
def list_conditional_blocks(template_id: uuid.UUID, version_id: uuid.UUID) -> list[dict[str, Any]]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Template/version not found.")
    blocks = v.get("conditional_blocks") or []
    return [_conditional_block_to_api(b) for b in blocks]


@app.post("/api/templates/{template_id}/versions/{version_id}/conditional-blocks")
def create_conditional_block(template_id: uuid.UUID, version_id: uuid.UUID, body: CreateConditionalBlockBody) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Template/version not found.")
    docx_bytes = v.get("docx_bytes")
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="Для этой версии нет загруженного DOCX.")
    cond_field = body.conditionField.strip()
    if not cond_field:
        raise HTTPException(status_code=400, detail="conditionField обязателен.")
    find_template, occurrence_index = _resolve_conditional_block_target(
        docx_bytes,
        body.findTemplate,
        body.occurrenceIndex,
    )
    branch = _validate_conditional_branch(body.branch)
    new_id = uuid.uuid4()
    block = {
        "id": new_id,
        "find_template": find_template,
        "occurrence_index": occurrence_index,
        "condition_field": cond_field,
        "equals_value": body.equalsValue,
        "branch": branch,
        "else_group_id": body.elseGroupId,
        "created_at_utc": datetime.now(timezone.utc),
    }
    blocks: list[dict[str, Any]] = v.setdefault("conditional_blocks", [])
    blocks.append(block)
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    return _conditional_block_to_api(block)


@app.patch("/api/templates/{template_id}/versions/{version_id}/conditional-blocks/{block_id}")
def patch_conditional_block(
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    block_id: uuid.UUID,
    body: PatchConditionalBlockBody,
) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Template/version not found.")
    blocks: list[dict[str, Any]] = v.setdefault("conditional_blocks", [])
    block = next((b for b in blocks if b["id"] == block_id), None)
    if block is None:
        raise HTTPException(status_code=404, detail="Conditional block not found.")
    docx_bytes = v.get("docx_bytes")
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="Для этой версии нет загруженного DOCX.")
    requested_find_template = block["find_template"] if body.findTemplate is None else body.findTemplate
    requested_occurrence_index = block["occurrence_index"] if body.occurrenceIndex is None else body.occurrenceIndex
    find_template, occurrence_index = _resolve_conditional_block_target(
        docx_bytes,
        requested_find_template,
        requested_occurrence_index,
    )
    if body.conditionField is not None:
        cond_field = body.conditionField.strip()
        if not cond_field:
            raise HTTPException(status_code=400, detail="conditionField обязателен.")
        block["condition_field"] = cond_field
    if body.equalsValue is not None:
        block["equals_value"] = body.equalsValue
    if body.branch is not None:
        block["branch"] = _validate_conditional_branch(body.branch)
    if "elseGroupId" in body.model_fields_set:
        block["else_group_id"] = body.elseGroupId
    block["find_template"] = find_template
    block["occurrence_index"] = occurrence_index
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    return _conditional_block_to_api(block)


@app.delete("/api/templates/{template_id}/versions/{version_id}/conditional-blocks/{block_id}")
def delete_conditional_block(template_id: uuid.UUID, version_id: uuid.UUID, block_id: uuid.UUID) -> dict[str, bool]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Template/version not found.")
    blocks: list[dict[str, Any]] = v.setdefault("conditional_blocks", [])
    before = len(blocks)
    blocks[:] = [b for b in blocks if b["id"] != block_id]
    if len(blocks) == before:
        raise HTTPException(status_code=404, detail="Conditional block not found.")
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    return {"ok": True}


@app.post("/api/templates/{template_id}/versions/{version_id}/revert-tag")
def revert_tag_in_docx(template_id: uuid.UUID, version_id: uuid.UUID, body: RevertTagBody) -> dict[str, Any]:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    docx_bytes = v.get("docx_bytes")
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="Для этой версии нет загруженного DOCX.")
    find_text = body.findText.strip()
    slots: list[dict[str, Any]] = v.setdefault("tag_slots", [])
    slot = next((s for s in slots if s["id"] == body.tagSlotId), None)
    if slot is None:
        raise HTTPException(status_code=404, detail="Слот тега не найден.")
    occ = slot.get("current_occurrence_index", body.occurrenceIndex)
    if occ < 0:
        raise HTTPException(status_code=400, detail="Укажите корректный occurrenceIndex (0-based).")
    original = slot["original_plain_text"]
    find_in_docx = slot["current_template"]
    updated, ok = apply_docx_single_text_replacement(docx_bytes, find_in_docx, original, occ)
    if not ok:
        raise HTTPException(status_code=404, detail="Не удалось восстановить исходный текст в документе.")
    slots[:] = [s for s in slots if s["id"] != body.tagSlotId]
    v["docx_bytes"] = updated
    _resync_tag_slots(v)
    try:
        v["docx_template_body"] = extract_plain_text_from_docx(updated)
    except Exception:  # noqa: BLE001
        pass
    _invalidate_publication_for_version(template_id, version_id)
    _persist_templates()
    return {"ok": True}


@app.get("/api/templates/{template_id}/versions/{version_id}/docx-file")
def download_template_docx(template_id: uuid.UUID, version_id: uuid.UUID) -> Response:
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    b = v.get("docx_bytes")
    if not b:
        b = build_docx_from_plain_text(v.get("docx_template_body") or "")
    name = v.get("source_file_name") or "template.docx"
    return Response(
        content=b,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": _content_disposition(name, disposition="inline"),
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/templates/{template_id}/versions/{version_id}/render-sync")
def render_sync(
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    body: dict[str, Any] = Body(...),
) -> Response:
    """Синхронная генерация: плоский JSON полей → готовый .docx (для вкладки «Документ»)."""
    v = template_versions.get(version_id)
    if not v or v["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Not Found")
    if v["status"] != VERSION_STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail="Опубликуйте версию шаблона перед генерацией.")
    payload_json = json.dumps(body, ensure_ascii=False)
    fn, data = render_version_to_docx(
        docx_bytes=v.get("docx_bytes"),
        docx_template_body=v["docx_template_body"],
        bindings_json=v["bindings_json"],
        rules_json=v["rules_json"],
        payload_json=payload_json,
        conditional_blocks=v.get("conditional_blocks") or [],
    )
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(fn, disposition="attachment")},
    )


def _get_client_from_api_key(x_api_key: str | None) -> dict[str, Any] | None:
    if not x_api_key:
        return None
    h = _hash_key(x_api_key)
    cid = clients_by_key_hash.get(h)
    if not cid:
        return None
    return clients.get(cid)


@app.post("/api/jobs")
async def create_job(
    body: CreateGenerationJobRequest,
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
) -> JSONResponse:
    client = _get_client_from_api_key(x_api_key)
    if not client:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ver = template_versions.get(body.template_version_id)
    if not ver or ver["status"] != VERSION_STATUS_PUBLISHED:
        return JSONResponse(
            status_code=400,
            content={"error": "Template version not found or not published."},
        )

    jid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    job = {
        "id": jid,
        "template_version_id": body.template_version_id,
        "client_id": client["id"],
        "payload_json": body.payload_json,
        "status": JOB_QUEUED,
        "error": None,
        "result_bytes": None,
        "result_file_name": None,
        "created_at_utc": now,
        "finished_at_utc": None,
    }
    jobs[jid] = job
    if job_queue is None:
        raise HTTPException(status_code=503, detail="Job queue is unavailable.")
    await job_queue.put(jid)
    return JSONResponse(
        status_code=202,
        content={"id": str(jid), "status": job["status"]},
        headers={"Location": f"/api/jobs/{jid}"},
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: uuid.UUID) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Not Found")
    return {
        "id": str(job["id"]),
        "status": job["status"],
        "error": job.get("error"),
        "resultFileName": job.get("result_file_name"),
        "createdAtUtc": job["created_at_utc"].isoformat().replace("+00:00", "Z"),
        "finishedAtUtc": job["finished_at_utc"].isoformat().replace("+00:00", "Z")
        if job.get("finished_at_utc")
        else None,
    }


@app.get("/api/jobs/{job_id}/result")
def get_job_result(job_id: uuid.UUID) -> Response:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Not Found")
    if job["status"] != JOB_SUCCEEDED or not job.get("result_bytes"):
        return JSONResponse(status_code=400, content={"error": "Result is not ready."})
    name = job.get("result_file_name") or "generated.docx"
    return Response(
        content=job["result_bytes"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(name, disposition="attachment")},
    )


def _generation_record_to_api(rec: Any) -> dict[str, Any]:
    return {
        "jobId": str(rec.id),
        "status": rec.status,
        "documentId": str(rec.document_id),
        "versionId": str(rec.version_id),
        "createdAtUtc": rec.created_at_utc,
        "startedAtUtc": rec.started_at_utc,
        "finishedAtUtc": rec.finished_at_utc,
        "latencyMs": rec.latency_ms,
        "errorCode": rec.error_code,
        "errorMessage": rec.error_message,
    }


@app.post("/api/v1/generations/sync")
def generate_sync_v1(
    body: GenerateSyncV1Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    request_id: str | None = Header(None, alias="X-Request-Id"),
    _actor: str = Depends(_require_v1_authorization),
) -> Response:
    req_id = request_id or str(uuid.uuid4())
    version = _resolve_published_version_for_v1(body.documentId, body.versionId)
    _validate_payload_for_version(version, body.payload)
    store = _ensure_production_store()
    if idempotency_key:
        existing = store.find_by_idempotency_key(
            document_id=body.documentId,
            version_id=version["id"],
            idempotency_key=idempotency_key,
        )
        if existing and existing.status == "succeeded" and existing.storage_path:
            path = Path(existing.storage_path)
            if path.is_file():
                return Response(
                    content=path.read_bytes(),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": _content_disposition(existing.file_name or "generated.docx", "attachment")},
                )
    rec = store.create_generation(
        document_id=body.documentId,
        version_id=version["id"],
        mode="sync",
        request_id=req_id,
        idempotency_key=idempotency_key,
        payload=body.payload,
        status="running",
    )
    started = perf_counter()
    try:
        fn, data = render_version_to_docx(
            docx_bytes=version.get("docx_bytes"),
            docx_template_body=version["docx_template_body"],
            bindings_json=version["bindings_json"],
            rules_json=version["rules_json"],
            payload_json=json.dumps(body.payload, ensure_ascii=False),
            conditional_blocks=version.get("conditional_blocks") or [],
        )
        store.mark_succeeded(rec.id, fn, data)
        GENERATION_TOTAL.labels(mode="sync", status="succeeded").inc()
        GENERATION_DURATION_SECONDS.labels(mode="sync").observe(perf_counter() - started)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": _content_disposition(fn, "attachment"),
                "X-Request-Id": req_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        store.mark_failed(rec.id, "generation_error", str(exc))
        GENERATION_TOTAL.labels(mode="sync", status="failed").inc()
        GENERATION_DURATION_SECONDS.labels(mode="sync").observe(perf_counter() - started)
        raise HTTPException(status_code=500, detail="Generation failed.") from exc


@app.post("/api/v1/generations/async")
async def generate_async_v1(
    body: GenerateAsyncV1Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    request_id: str | None = Header(None, alias="X-Request-Id"),
    _actor: str = Depends(_require_v1_authorization),
) -> JSONResponse:
    req_id = request_id or str(uuid.uuid4())
    version = _resolve_published_version_for_v1(body.documentId, body.versionId)
    _validate_payload_for_version(version, body.payload)
    store = _ensure_production_store()
    if idempotency_key:
        existing = store.find_by_idempotency_key(
            document_id=body.documentId,
            version_id=version["id"],
            idempotency_key=idempotency_key,
        )
        if existing:
            return JSONResponse(
                status_code=202,
                content={"jobId": str(existing.id), "status": existing.status, "statusUrl": f"/api/v1/generations/{existing.id}"},
            )
    rec = store.create_generation(
        document_id=body.documentId,
        version_id=version["id"],
        mode="async",
        request_id=req_id,
        idempotency_key=idempotency_key,
        payload=body.payload,
        status="queued",
    )
    if v1_job_queue is None:
        raise HTTPException(status_code=503, detail="Generation queue is unavailable.")
    await v1_job_queue.put(rec.id)
    ASYNC_QUEUE_DEPTH.set(v1_job_queue.qsize())
    store.add_audit_event(
        generation_request_id=rec.id,
        event_type="generation.queued",
        severity="info",
        actor_id="system",
        request_id=req_id,
        metadata={},
    )
    return JSONResponse(
        status_code=202,
        content={"jobId": str(rec.id), "status": "queued", "statusUrl": f"/api/v1/generations/{rec.id}"},
        headers={"Location": f"/api/v1/generations/{rec.id}"},
    )


@app.get("/api/v1/generations/{job_id}")
def get_generation_v1(job_id: uuid.UUID, _actor: str = Depends(_require_v1_authorization)) -> dict[str, Any]:
    store = _ensure_production_store()
    try:
        rec = store.get_generation(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation not found.") from exc
    return _generation_record_to_api(rec)


@app.get("/api/v1/generations/{job_id}/result")
def get_generation_result_v1(job_id: uuid.UUID, _actor: str = Depends(_require_v1_authorization)) -> Response:
    store = _ensure_production_store()
    try:
        rec = store.get_generation(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation not found.") from exc
    if rec.status != "succeeded" or not rec.storage_path:
        raise HTTPException(status_code=409, detail="Result is not ready.")
    path = Path(rec.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Result artifact expired.")
    return Response(
        content=path.read_bytes(),
        media_type=rec.mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(rec.file_name or "generated.docx", "attachment")},
    )


@app.get("/api/v1/documents/{document_id}/statistics")
def get_document_statistics_v1(
    document_id: uuid.UUID,
    fromUtc: datetime | None = None,
    toUtc: datetime | None = None,
    _actor: str = Depends(_require_v1_authorization),
) -> dict[str, Any]:
    store = _ensure_production_store()
    return store.get_document_statistics(document_id, from_utc=fromUtc, to_utc=toUtc)


@app.get("/metrics")
def get_metrics() -> Response:
    return Response(content=metrics_payload(), media_type=metrics_content_type())


@app.post("/api/webhooks/test")
async def test_webhook(body: TestWebhookRequest) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                body.webhook_url,
                json={"eventType": "webhook.test", "at": datetime.now(timezone.utc).isoformat()},
                timeout=15.0,
            )
        return {"statusCode": r.status_code}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(exc)})


# OpenAPI at /docs (FastAPI default)
