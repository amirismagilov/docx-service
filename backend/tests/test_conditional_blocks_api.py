import io
import zipfile

from fastapi.testclient import TestClient

from app.docx_ops import build_docx_from_plain_text
from app.main import app, jobs, template_versions, templates


def _docx_text(docx_bytes: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(docx_bytes))
    xml = z.read("word/document.xml").decode("utf-8")
    # Достаточно для проверок наличия/отсутствия строк в тестах.
    return xml


def test_conditional_blocks_crud_and_selection_validation() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    boot = client.post("/api/templates/bootstrap-empty", json={"name": "T"})
    tid = boot.json()["templateId"]
    vid = boot.json()["versionId"]

    raw = build_docx_from_plain_text("Для физ лица\nДля юр лица")
    up = client.post(
        f"/api/templates/{tid}/versions/{vid}/upload-docx",
        files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert up.status_code == 200

    bad = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Не существую",
            "occurrenceIndex": 0,
            "conditionField": "customer_type",
            "equalsValue": "phys",
            "branch": "if",
        },
    )
    assert bad.status_code == 404

    preview_style = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Для физ лица\n\nДля юр лица",
            "occurrenceIndex": 0,
            "conditionField": "customer_type",
            "equalsValue": "phys",
            "branch": "if",
        },
    )
    assert preview_style.status_code == 200

    created = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Для физ лица",
            "occurrenceIndex": 0,
            "conditionField": "customer_type",
            "equalsValue": "phys",
            "branch": "if",
        },
    )
    assert created.status_code == 200
    block_id = created.json()["id"]

    listed = client.get(f"/api/templates/{tid}/versions/{vid}/conditional-blocks")
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert any(x["id"] == block_id for x in listed.json())

    patched = client.patch(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks/{block_id}",
        json={"equalsValue": "individual"},
    )
    assert patched.status_code == 200
    assert patched.json()["equalsValue"] == "individual"

    deleted = client.delete(f"/api/templates/{tid}/versions/{vid}/conditional-blocks/{block_id}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    listed_after = client.get(f"/api/templates/{tid}/versions/{vid}/conditional-blocks")
    assert listed_after.status_code == 200
    assert len(listed_after.json()) == 1


def test_render_sync_applies_if_else_conditional_blocks() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    boot = client.post("/api/templates/bootstrap-empty", json={"name": "T"})
    tid = boot.json()["templateId"]
    vid = boot.json()["versionId"]

    raw = build_docx_from_plain_text("Для физ лица\nДля юр лица\nИмя: {{name}}")
    up = client.post(
        f"/api/templates/{tid}/versions/{vid}/upload-docx",
        files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert up.status_code == 200

    b_if = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Для физ лица",
            "occurrenceIndex": 0,
            "conditionField": "customer_type",
            "equalsValue": "phys",
            "branch": "if",
        },
    )
    assert b_if.status_code == 200
    group_id = b_if.json()["id"]
    b_else = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Для юр лица",
            "occurrenceIndex": 0,
            "conditionField": "customer_type",
            "equalsValue": "phys",
            "branch": "else",
            "elseGroupId": group_id,
        },
    )
    assert b_else.status_code == 200
    republish = client.post(f"/api/templates/{tid}/versions/{vid}/publish")
    assert republish.status_code == 200

    phys_render = client.post(
        f"/api/templates/{tid}/versions/{vid}/render-sync",
        json={"customer_type": "PHYS", "name": "Алиса"},
    )
    assert phys_render.status_code == 200
    phys_text = _docx_text(phys_render.content)
    assert "Для физ лица" in phys_text
    assert "Для юр лица" not in phys_text
    assert "Алиса" in phys_text

    jur_render = client.post(
        f"/api/templates/{tid}/versions/{vid}/render-sync",
        json={"customer_type": "jur", "name": "ООО Ландыш"},
    )
    assert jur_render.status_code == 200
    jur_text = _docx_text(jur_render.content)
    assert "Для физ лица" not in jur_text
    assert "Для юр лица" in jur_text
    assert "ООО Ландыш" in jur_text


def test_stale_conditional_block_does_not_break_render() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    boot = client.post("/api/templates/bootstrap-empty", json={"name": "T"})
    tid = boot.json()["templateId"]
    vid = boot.json()["versionId"]

    first = build_docx_from_plain_text("Только этот блок")
    up1 = client.post(
        f"/api/templates/{tid}/versions/{vid}/upload-docx",
        files={"file": ("template.docx", first, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert up1.status_code == 200

    created = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": "Только этот блок",
            "occurrenceIndex": 0,
            "conditionField": "mode",
            "equalsValue": "show",
            "branch": "if",
        },
    )
    assert created.status_code == 200

    second = build_docx_from_plain_text("Новый текст без старого блока")
    up2 = client.post(
        f"/api/templates/{tid}/versions/{vid}/upload-docx",
        files={"file": ("template_v2.docx", second, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert up2.status_code == 200

    rendered = client.post(
        f"/api/templates/{tid}/versions/{vid}/render-sync",
        json={"mode": "hide"},
    )
    assert rendered.status_code == 200
    text = _docx_text(rendered.content)
    assert "Новый текст без старого блока" in text


def test_conditional_block_supports_large_multipage_fragment() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    boot = client.post("/api/templates/bootstrap-empty", json={"name": "T"})
    tid = boot.json()["templateId"]
    vid = boot.json()["versionId"]

    lines = [f"Оглавление строка {i}" for i in range(1, 121)]
    # Большой диапазон (много абзацев), имитируем выделение «страницы+».
    large_fragment = "\n\n".join(lines[15:95])
    raw = build_docx_from_plain_text("\n".join(lines))
    up = client.post(
        f"/api/templates/{tid}/versions/{vid}/upload-docx",
        files={"file": ("template.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert up.status_code == 200

    created = client.post(
        f"/api/templates/{tid}/versions/{vid}/conditional-blocks",
        json={
            "findTemplate": large_fragment,
            "occurrenceIndex": 0,
            "conditionField": "show_toc_chunk",
            "equalsValue": "yes",
            "branch": "if",
        },
    )
    assert created.status_code == 200
    republish = client.post(f"/api/templates/{tid}/versions/{vid}/publish")
    assert republish.status_code == 200

    hidden = client.post(
        f"/api/templates/{tid}/versions/{vid}/render-sync",
        json={"show_toc_chunk": "no"},
    )
    assert hidden.status_code == 200
    hidden_text = _docx_text(hidden.content)
    assert "Оглавление строка 40" not in hidden_text
    assert "Оглавление строка 5" in hidden_text
    assert "Оглавление строка 110" in hidden_text
