"""Простое сохранение шаблонов и версий в JSON (переживает перезапуск uvicorn)."""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_FORMAT_VERSION = 1


def default_store_path() -> Path:
    override = os.environ.get("DOCX_SERVICE_STORE")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data" / "store.json"


def _dt_serialize(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _dt_parse(s: str | None) -> datetime | None:
    if not s:
        return None
    normalized = s[:-1] + "+00:00" if s.endswith("Z") else s
    return datetime.fromisoformat(normalized)


def _serialize_template(t: dict[str, Any]) -> dict[str, Any]:
    cv = t.get("current_version_id")
    return {
        "id": str(t["id"]),
        "name": t["name"],
        "status": t["status"],
        "schema_json": t["schema_json"],
        "created_by": t["created_by"],
        "created_at_utc": _dt_serialize(t["created_at_utc"]),
        "current_version_id": str(cv) if cv else None,
    }


def _deserialize_template(d: dict[str, Any]) -> dict[str, Any]:
    tid = uuid.UUID(d["id"])
    cv_raw = d.get("current_version_id")
    return {
        "id": tid,
        "name": d["name"],
        "status": d["status"],
        "schema_json": d["schema_json"],
        "created_by": d["created_by"],
        "created_at_utc": _dt_parse(d["created_at_utc"]) or datetime.now(timezone.utc),
        "current_version_id": uuid.UUID(cv_raw) if cv_raw else None,
    }


def _serialize_version(v: dict[str, Any]) -> dict[str, Any]:
    b = v.get("docx_bytes")
    return {
        "id": str(v["id"]),
        "template_id": str(v["template_id"]),
        "version": v["version"],
        "status": v["status"],
        "docx_template_body": v["docx_template_body"],
        "bindings_json": v["bindings_json"],
        "rules_json": v["rules_json"],
        "created_at_utc": _dt_serialize(v["created_at_utc"]),
        "published_at_utc": _dt_serialize(v.get("published_at_utc")),
        "docx_bytes_b64": base64.standard_b64encode(b).decode("ascii") if b else None,
        "source_file_name": v.get("source_file_name"),
    }


def _deserialize_version(d: dict[str, Any]) -> dict[str, Any]:
    b64 = d.get("docx_bytes_b64")
    raw: bytes | None = base64.standard_b64decode(b64) if b64 else None
    pub = d.get("published_at_utc")
    return {
        "id": uuid.UUID(d["id"]),
        "template_id": uuid.UUID(str(d["template_id"])),
        "version": d["version"],
        "status": d["status"],
        "docx_template_body": d["docx_template_body"],
        "bindings_json": d["bindings_json"],
        "rules_json": d["rules_json"],
        "created_at_utc": _dt_parse(d["created_at_utc"]) or datetime.now(timezone.utc),
        "published_at_utc": _dt_parse(pub) if pub else None,
        "docx_bytes": raw,
        "source_file_name": d.get("source_file_name"),
    }


def persist_templates(
    path: Path,
    templates: dict[uuid.UUID, dict[str, Any]],
    template_versions: dict[uuid.UUID, dict[str, Any]],
) -> None:
    payload = {
        "format": STORE_FORMAT_VERSION,
        "templates": [_serialize_template(t) for t in templates.values()],
        "template_versions": [_serialize_version(v) for v in template_versions.values()],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def try_load_templates(
    path: Path,
) -> tuple[dict[uuid.UUID, dict[str, Any]], dict[uuid.UUID, dict[str, Any]]] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("format") != STORE_FORMAT_VERSION:
        return None
    t_list = raw.get("templates") or []
    v_list = raw.get("template_versions") or []
    out_t: dict[uuid.UUID, dict[str, Any]] = {}
    out_v: dict[uuid.UUID, dict[str, Any]] = {}
    for item in t_list:
        t = _deserialize_template(item)
        out_t[t["id"]] = t
    for item in v_list:
        v = _deserialize_version(item)
        out_v[v["id"]] = v
    return out_t, out_v
