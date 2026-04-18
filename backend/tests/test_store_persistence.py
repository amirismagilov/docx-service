"""Round-trip тест сериализации шаблонов на диск."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.store_persistence import persist_templates, try_load_templates


def test_persist_and_load_roundtrip(tmp_path: Path) -> None:
    tid = uuid.uuid4()
    vid = uuid.uuid4()
    now = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
    templates = {
        tid: {
            "id": tid,
            "name": "Test",
            "status": 0,
            "schema_json": "{}",
            "created_by": "test",
            "created_at_utc": now,
            "current_version_id": vid,
        }
    }
    slot_id = uuid.uuid4()
    template_versions = {
        vid: {
            "id": vid,
            "template_id": tid,
            "version": 1,
            "status": 0,
            "docx_template_body": "Hello",
            "bindings_json": "{}",
            "rules_json": "[]",
            "created_at_utc": now,
            "published_at_utc": None,
            "docx_bytes": b"PK\x03\x04fake",
            "source_file_name": "a.docx",
            "tag_slots": [
                {
                    "id": slot_id,
                    "original_plain_text": "Old",
                    "current_template": "{{x}}",
                    "created_at_utc": now,
                }
            ],
        }
    }
    path = tmp_path / "store.json"
    persist_templates(path, templates, template_versions)
    loaded = try_load_templates(path)
    assert loaded is not None
    t2, v2 = loaded
    assert len(t2) == 1 and len(v2) == 1
    assert t2[tid]["name"] == "Test"
    assert t2[tid]["current_version_id"] == vid
    ver = v2[vid]
    assert ver["docx_template_body"] == "Hello"
    assert ver["docx_bytes"] == b"PK\x03\x04fake"
    slots = ver.get("tag_slots") or []
    assert len(slots) == 1
    assert slots[0]["id"] == slot_id
    assert slots[0]["original_plain_text"] == "Old"
    assert slots[0]["current_template"] == "{{x}}"
