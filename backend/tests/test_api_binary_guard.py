import io
import zipfile

from fastapi.testclient import TestClient

from app.docx_ops import build_docx_from_plain_text
from app.main import app, templates, template_versions, jobs


def test_upload_docx_auto_publishes_and_allows_render_sync_without_publish() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    assert r.status_code == 200
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Hello {{x}}')
    up = client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )
    assert up.status_code == 200

    detail = client.get(f'/api/templates/{tid}')
    assert detail.status_code == 200
    vers = {v['id']: v for v in detail.json()['versions']}
    assert vers[vid]['status'] == 1

    render_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/render-sync',
        json={'x': 'world'},
    )
    assert render_r.status_code == 200
    assert render_r.headers.get('content-type', '').startswith(
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


def test_put_editor_text_rejected_for_uploaded_docx() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)

    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    assert r.status_code == 200
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Hello {{x}}')
    up = client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )
    assert up.status_code == 200

    put = client.put(
        f'/api/templates/{tid}/versions/{vid}/editor-text',
        json={'text': 'new text'},
    )
    assert put.status_code == 409
    assert 'загруженного DOCX' in put.text



def test_download_template_docx_allows_unicode_filename() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    assert r.status_code == 200
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Hello')
    up = client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('ТЗ_документ.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )
    assert up.status_code == 200

    got = client.get(f'/api/templates/{tid}/versions/{vid}/docx-file')
    assert got.status_code == 200
    cd = got.headers.get('content-disposition', '')
    assert 'filename*=' in cd


def test_apply_tag_endpoint_replaces_text_in_binary_docx() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    assert r.status_code == 200
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Контрагент: ООО Ромашка')
    up = client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )
    assert up.status_code == 200

    apply_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/apply-tag',
        json={'findText': 'ООО Ромашка', 'tagId': 'buyer_name', 'replaceAll': False, 'occurrenceIndex': 0},
    )
    assert apply_r.status_code == 200

    got = client.get(f'/api/templates/{tid}/versions/{vid}/docx-file')
    assert got.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(got.content))
    xml = z.read('word/document.xml').decode('utf-8')
    assert '{{buyer_name}}' in xml


def test_apply_tag_endpoint_supports_composite_template_and_symbols() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Контрагент: ООО Ромашка')
    client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )

    apply_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/apply-tag',
        json={
            'findText': 'ООО Ромашка',
            'replacementTemplate': '{{buyer_name}} / {{buyer_inn}}',
            'replaceAll': False,
            'occurrenceIndex': 0,
        },
    )
    assert apply_r.status_code == 200
    got = client.get(f'/api/templates/{tid}/versions/{vid}/docx-file')
    z = zipfile.ZipFile(io.BytesIO(got.content))
    xml = z.read('word/document.xml').decode('utf-8')
    assert '{{buyer_name}} / {{buyer_inn}}' in xml


def test_apply_tag_endpoint_supports_line_breaks() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('ООО Ромашка')
    client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )

    apply_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/apply-tag',
        json={
            'findText': 'ООО Ромашка',
            'replacementTemplate': '{{buyer_name}}\n{{buyer_inn}}',
            'replaceAll': False,
            'occurrenceIndex': 0,
        },
    )
    assert apply_r.status_code == 200
    got = client.get(f'/api/templates/{tid}/versions/{vid}/docx-file')
    z = zipfile.ZipFile(io.BytesIO(got.content))
    xml = z.read('word/document.xml').decode('utf-8')
    assert '<w:br' in xml
    assert '{{buyer_name}}' in xml
    assert '{{buyer_inn}}' in xml


def test_apply_tag_endpoint_supports_paragraph_break_for_whole_paragraph() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('ООО Ромашка')
    client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )

    apply_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/apply-tag',
        json={
            'findText': 'ООО Ромашка',
            'replacementTemplate': '{{buyer_name}}[[PARA_BREAK]]{{buyer_inn}}',
            'replaceAll': False,
            'occurrenceIndex': 0,
        },
    )
    assert apply_r.status_code == 200
    got = client.get(f'/api/templates/{tid}/versions/{vid}/docx-file')
    z = zipfile.ZipFile(io.BytesIO(got.content))
    xml = z.read('word/document.xml').decode('utf-8')
    assert xml.count('<w:p') >= 2
    assert '{{buyer_name}}' in xml
    assert '{{buyer_inn}}' in xml


def test_apply_tag_endpoint_rejects_paragraph_break_for_partial_paragraph() -> None:
    templates.clear()
    template_versions.clear()
    jobs.clear()

    client = TestClient(app)
    r = client.post('/api/templates/bootstrap-empty', json={'name': 'T'})
    data = r.json()
    tid = data['templateId']
    vid = data['versionId']

    raw = build_docx_from_plain_text('Контрагент: ООО Ромашка')
    client.post(
        f'/api/templates/{tid}/versions/{vid}/upload-docx',
        files={'file': ('template.docx', raw, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )

    apply_r = client.post(
        f'/api/templates/{tid}/versions/{vid}/apply-tag',
        json={
            'findText': 'ООО Ромашка',
            'replacementTemplate': '{{buyer_name}}[[PARA_BREAK]]{{buyer_inn}}',
            'replaceAll': False,
            'occurrenceIndex': 0,
        },
    )
    assert apply_r.status_code == 404
