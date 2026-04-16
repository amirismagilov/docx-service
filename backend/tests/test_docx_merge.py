import io
import re
import zipfile

from docx import Document

from app.docx_ops import apply_docx_single_text_replacement, build_docx_from_plain_text, merge_docx_placeholders


def _joined_w_text(xml: str) -> str:
    parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
    return "".join(parts)


def test_merge_docx_replaces_placeholder_in_xml() -> None:
    body = "Hello {{seller_inn}} end."
    raw = build_docx_from_plain_text(body)
    name, out = merge_docx_placeholders(raw, {"seller_inn": "7701234567"})
    assert name.endswith(".docx")
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode("utf-8")
    assert "7701234567" in xml
    assert "{{seller_inn}}" not in xml


def test_merge_docx_replaces_split_run_placeholder() -> None:
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Продавец ИНН: ")
    p.add_run("{{seller")
    p.add_run("_inn}}")
    buf = io.BytesIO()
    doc.save(buf)

    _, out = merge_docx_placeholders(buf.getvalue(), {"seller_inn": "7701234567"})
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode("utf-8")
    assert "7701234567" in _joined_w_text(xml)
    assert "{{seller" not in xml
    assert "_inn}}" not in xml


def test_merge_docx_keeps_table_and_run_formatting_tags() -> None:
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    p = table.cell(0, 0).paragraphs[0]
    p.add_run("ИНН: ")
    bold_run = p.add_run("{{seller")
    bold_run.bold = True
    p.add_run("_inn}}")
    buf = io.BytesIO()
    doc.save(buf)

    _, out = merge_docx_placeholders(buf.getvalue(), {"seller_inn": "7701234567"})
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode("utf-8")
    assert "<w:tbl" in xml
    assert "<w:b" in xml
    assert "7701234567" in _joined_w_text(xml)


def test_single_replacement_supports_line_breaks() -> None:
    raw = build_docx_from_plain_text("ООО Ромашка")
    out, ok = apply_docx_single_text_replacement(raw, "ООО Ромашка", "{{buyer_name}}\n{{buyer_inn}}", 0)
    assert ok is True
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode("utf-8")
    assert "<w:br" in xml
    assert "{{buyer_name}}" in xml
    assert "{{buyer_inn}}" in xml


def test_single_replacement_supports_paragraph_break_only_for_whole_paragraph() -> None:
    raw = build_docx_from_plain_text("ООО Ромашка")
    out, ok = apply_docx_single_text_replacement(raw, "ООО Ромашка", "{{buyer_name}}[[PARA_BREAK]]{{buyer_inn}}", 0)
    assert ok is True
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:p") >= 2

    raw2 = build_docx_from_plain_text("Контрагент: ООО Ромашка")
    _out2, ok2 = apply_docx_single_text_replacement(raw2, "ООО Ромашка", "{{buyer_name}}[[PARA_BREAK]]{{buyer_inn}}", 0)
    assert ok2 is False


