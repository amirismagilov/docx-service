import io
import json
import shutil
import time
import zipfile

from fastapi.testclient import TestClient

from app.docx_ops import build_docx_from_plain_text
from app.main import PROD_DB_PATH, PROD_RESULTS_DIR, app, jobs, template_versions, templates


AUTH_HEADERS = {"Authorization": "Bearer dev-v1-token"}


def _reset_state() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()
    if PROD_DB_PATH.exists():
        PROD_DB_PATH.unlink()
    if PROD_RESULTS_DIR.exists():
        shutil.rmtree(PROD_RESULTS_DIR)


def test_v1_sync_generation_returns_docx_and_supports_idempotency() -> None:
    _reset_state()
    with TestClient(app) as client:
        boot = client.post("/api/templates/bootstrap-empty", json={"name": "Doc"})
        tid = boot.json()["templateId"]
        vid = boot.json()["versionId"]

        raw = build_docx_from_plain_text("Hello {{name}}")
        up = client.post(
            f"/api/templates/{tid}/versions/{vid}/upload-docx",
            files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert up.status_code == 200

        headers = {"Idempotency-Key": "idem-12345678", "X-Request-Id": "req-sync-1", **AUTH_HEADERS}
        first = client.post(
            "/api/v1/generations/sync",
            headers=headers,
            json={"documentId": tid, "versionId": vid, "payload": {"name": "World"}},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/generations/sync",
            headers=headers,
            json={"documentId": tid, "versionId": vid, "payload": {"name": "World"}},
        )
        assert second.status_code == 200

        z = zipfile.ZipFile(io.BytesIO(second.content))
        xml = z.read("word/document.xml").decode("utf-8")
        assert "World" in xml


def test_v1_async_generation_status_and_result() -> None:
    _reset_state()
    with TestClient(app) as client:
        boot = client.post("/api/templates/bootstrap-empty", json={"name": "Doc"})
        tid = boot.json()["templateId"]
        vid = boot.json()["versionId"]

        raw = build_docx_from_plain_text("Invoice {{number}}")
        client.post(
            f"/api/templates/{tid}/versions/{vid}/upload-docx",
            files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        queued = client.post(
            "/api/v1/generations/async",
            headers=AUTH_HEADERS,
            json={"documentId": tid, "versionId": vid, "payload": {"number": "A-42"}},
        )
        assert queued.status_code == 202
        job_id = queued.json()["jobId"]

        status = None
        for _ in range(20):
            status_r = client.get(f"/api/v1/generations/{job_id}", headers=AUTH_HEADERS)
            assert status_r.status_code == 200
            status = status_r.json()["status"]
            if status == "succeeded":
                break
            time.sleep(0.05)
        assert status == "succeeded"

        result_r = client.get(f"/api/v1/generations/{job_id}/result", headers=AUTH_HEADERS)
        assert result_r.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(result_r.content))
        xml = z.read("word/document.xml").decode("utf-8")
        assert "A-42" in xml


def test_v1_document_statistics_reflect_calls() -> None:
    _reset_state()
    with TestClient(app) as client:
        boot = client.post("/api/templates/bootstrap-empty", json={"name": "Doc"})
        tid = boot.json()["templateId"]
        vid = boot.json()["versionId"]
        raw = build_docx_from_plain_text("Hello {{name}}")
        client.post(
            f"/api/templates/{tid}/versions/{vid}/upload-docx",
            files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        for i in range(3):
            r = client.post(
                "/api/v1/generations/sync",
                headers=AUTH_HEADERS,
                json={"documentId": tid, "versionId": vid, "payload": {"name": f"U{i}"}},
            )
            assert r.status_code == 200

        stats = client.get(f"/api/v1/documents/{tid}/statistics", headers=AUTH_HEADERS)
        assert stats.status_code == 200
        body = stats.json()
        assert body["totals"]["calls"] >= 3
        assert body["totals"]["success"] >= 3


def test_v1_requires_bearer_auth() -> None:
    _reset_state()
    with TestClient(app) as client:
        boot = client.post("/api/templates/bootstrap-empty", json={"name": "Doc"})
        tid = boot.json()["templateId"]
        vid = boot.json()["versionId"]
        raw = build_docx_from_plain_text("Hello {{name}}")
        client.post(
            f"/api/templates/{tid}/versions/{vid}/upload-docx",
            files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        denied = client.post(
            "/api/v1/generations/sync",
            json={"documentId": tid, "versionId": vid, "payload": {"name": "X"}},
        )
        assert denied.status_code == 401


def test_v1_payload_validation_rejects_invalid_json_schema_payload() -> None:
    _reset_state()
    with TestClient(app) as client:
        boot = client.post("/api/templates/bootstrap-empty", json={"name": "Doc"})
        tid = boot.json()["templateId"]
        vid = boot.json()["versionId"]
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        }
        patch = client.patch(f"/api/templates/{tid}", json={"schemaJson": json.dumps(schema)})
        assert patch.status_code == 200
        publish = client.post(f"/api/templates/{tid}/versions/{vid}/publish")
        assert publish.status_code == 200
        raw = build_docx_from_plain_text("Hello {{name}}")
        client.post(
            f"/api/templates/{tid}/versions/{vid}/upload-docx",
            files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        invalid = client.post(
            "/api/v1/generations/sync",
            headers=AUTH_HEADERS,
            json={"documentId": tid, "versionId": vid, "payload": {"name": "X", "age": "not-int"}},
        )
        assert invalid.status_code == 422
