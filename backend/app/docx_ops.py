"""Работа с бинарным .docx: извлечение текста, сборка из текста, подстановка {{полей}} в OOXML."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from docx import Document

from app.generator import generate_docx


def xml_escape_for_word(text: str) -> str:
    return escape(text, entities={'"': "&quot;", "'": "&apos;"})


def extract_plain_text_from_docx(docx_bytes: bytes) -> str:
    doc = Document(io.BytesIO(docx_bytes))
    lines: list[str] = []
    for p in doc.paragraphs:
        lines.append(p.text)
    return "\n".join(lines)


def build_docx_from_plain_text(text: str) -> bytes:
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
ET.register_namespace("w", W_NS)
PARA_BREAK_MARKER = "[[PARA_BREAK]]"


def _w_tag(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def _paragraph_text(p: ET.Element) -> str:
    texts = list(p.findall(".//w:t", NS))
    return "".join(t.text or "" for t in texts)


def _make_run_with_text(text: str, template_run: ET.Element | None, break_before: bool = False) -> ET.Element:
    run = ET.Element(_w_tag("r"))
    if template_run is not None:
        rpr = template_run.find("w:rPr", NS)
        if rpr is not None:
            run.append(ET.fromstring(ET.tostring(rpr, encoding="unicode")))
    if break_before:
        run.append(ET.Element(_w_tag("br")))
    text_el = ET.Element(_w_tag("t"))
    if text.startswith(" ") or text.endswith(" "):
        text_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_el.text = text
    run.append(text_el)
    return run


def _set_paragraph_text_with_breaks(p: ET.Element, text: str) -> None:
    template_run = p.find(".//w:r", NS)
    keep: list[ET.Element] = []
    for child in list(p):
        if child.tag == _w_tag("pPr"):
            keep.append(child)
        p.remove(child)
    for child in keep:
        p.append(child)
    lines = text.split("\n")
    if not lines:
        p.append(_make_run_with_text("", template_run))
        return
    p.append(_make_run_with_text(lines[0], template_run))
    for line in lines[1:]:
        p.append(_make_run_with_text(line, template_run, break_before=True))


def _replace_tokens_in_paragraph_runs(p: ET.Element, values: dict[str, str]) -> bool:
    texts = list(p.findall(".//w:t", NS))
    if not texts:
        return False
    original = "".join(t.text or "" for t in texts)
    updated = original
    for src, val in values.items():
        updated = updated.replace(src, val)
    if updated == original:
        return False

    cursor = 0
    for idx, node in enumerate(texts):
        node_len = len(node.text or "")
        if idx == len(texts) - 1:
            node.text = updated[cursor:]
        else:
            node.text = updated[cursor : cursor + node_len]
        cursor += node_len

    return True


def _replace_template_in_paragraph_runs(p: ET.Element, find_text: str, replace_template: str, replace_all: bool) -> tuple[bool, bool]:
    original = _paragraph_text(p)
    if not original:
        return False, False
    updated = original.replace(find_text, replace_template) if replace_all else original.replace(find_text, replace_template, 1)
    if updated == original:
        return False, False
    if "\n" in replace_template and PARA_BREAK_MARKER not in replace_template:
        _set_paragraph_text_with_breaks(p, updated)
        return True, False
    return _replace_tokens_in_paragraph_runs(p, {find_text: replace_template}), False


def _replace_exact_paragraph_with_parts(parent: ET.Element, p: ET.Element, replacement: str) -> bool:
    parts = replacement.split(PARA_BREAK_MARKER)
    if len(parts) <= 1:
        return False
    idx = list(parent).index(p)
    template_xml = ET.tostring(p, encoding="unicode")
    parent.remove(p)
    for offset, part in enumerate(parts):
        clone = ET.fromstring(template_xml)
        _set_paragraph_text_with_breaks(clone, part)
        parent.insert(idx + offset, clone)
    return True


def _replace_tokens_in_word_xml(xml_bytes: bytes, values: dict[str, str]) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        s = xml_bytes.decode("utf-8", errors="ignore")
        for key, val in values.items():
            token = "{{" + key + "}}"
            s = s.replace(token, xml_escape_for_word(val))
        return s.encode("utf-8")

    changed = False
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for p in root.findall(".//w:p", NS):
        for src, val in values.items():
            if PARA_BREAK_MARKER in val:
                original = _paragraph_text(p)
                if original != src:
                    continue
                parent = parent_map.get(p)
                if parent is None:
                    continue
                changed = _replace_exact_paragraph_with_parts(parent, p, val) or changed
            else:
                did, _unsupported = _replace_template_in_paragraph_runs(p, src, val, True)
                changed = did or changed
    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def apply_docx_text_replacements(docx_bytes: bytes, replacements: dict[str, str]) -> bytes:
    """Заменяет произвольные текстовые фрагменты в word/*.xml с сохранением OOXML-структуры."""
    buf_in = io.BytesIO(docx_bytes)
    buf_out = io.BytesIO()
    with (
        zipfile.ZipFile(buf_in, "r") as zin,
        zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for zinfo in zin.infolist():
            raw = zin.read(zinfo.filename)
            fn = zinfo.filename.replace("\\", "/")
            if fn.endswith(".xml") and fn.startswith("word/"):
                raw = _replace_tokens_in_word_xml(raw, replacements)
            zout.writestr(fn, raw, compress_type=zipfile.ZIP_DEFLATED)
    return buf_out.getvalue()


def _replace_nth_in_paragraph_runs(p: ET.Element, src: str, dst: str, target_index: int, seen: int) -> tuple[bool, int]:
    texts = list(p.findall(".//w:t", NS))
    if not texts:
        return False, seen
    original = "".join(t.text or "" for t in texts)
    pos = 0
    local_occurs: list[int] = []
    while True:
        i = original.find(src, pos)
        if i < 0:
            break
        local_occurs.append(i)
        pos = i + len(src)
    if not local_occurs:
        return False, seen

    if target_index < seen or target_index >= seen + len(local_occurs):
        return False, seen + len(local_occurs)

    idx_in_local = target_index - seen
    start = local_occurs[idx_in_local]
    updated = original[:start] + dst + original[start + len(src) :]

    cursor = 0
    for idx, node in enumerate(texts):
        node_len = len(node.text or "")
        if idx == len(texts) - 1:
            node.text = updated[cursor:]
        else:
            node.text = updated[cursor : cursor + node_len]
        cursor += node_len
    return True, seen + len(local_occurs)


def apply_docx_single_text_replacement(docx_bytes: bytes, find_text: str, replace_with: str, occurrence_index: int) -> tuple[bytes, bool]:
    """
    Заменяет только одно (N-е) вхождение текста в word/*.xml, сохраняя OOXML-структуру.
    occurrence_index — 0-based.
    """
    buf_in = io.BytesIO(docx_bytes)
    buf_out = io.BytesIO()
    replaced_any = False
    with (
        zipfile.ZipFile(buf_in, "r") as zin,
        zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for zinfo in zin.infolist():
            raw = zin.read(zinfo.filename)
            fn = zinfo.filename.replace("\\", "/")
            if fn.endswith(".xml") and fn.startswith("word/"):
                try:
                    root = ET.fromstring(raw)
                except ET.ParseError:
                    zout.writestr(fn, raw, compress_type=zipfile.ZIP_DEFLATED)
                    continue
                seen = 0
                changed = False
                parent_map = {child: parent for parent in root.iter() for child in parent}
                for p in root.findall(".//w:p", NS):
                    original = _paragraph_text(p)
                    local_count = original.count(find_text)
                    if local_count == 0:
                        continue
                    if occurrence_index < seen or occurrence_index >= seen + local_count:
                        seen += local_count
                        continue
                    local_target = occurrence_index - seen
                    if PARA_BREAK_MARKER in replace_with:
                        if local_count != 1 or local_target != 0 or original != find_text:
                            break
                        parent = parent_map.get(p)
                        if parent is None:
                            break
                        changed = _replace_exact_paragraph_with_parts(parent, p, replace_with)
                        replaced_any = changed
                        break
                    if "\n" in replace_with:
                        updated = original.replace(find_text, replace_with, 1)
                        _set_paragraph_text_with_breaks(p, updated)
                        changed = True
                        replaced_any = True
                        break
                    did, seen_after = _replace_nth_in_paragraph_runs(p, find_text, replace_with, occurrence_index, seen)
                    seen = seen_after
                    if did:
                        changed = True
                        replaced_any = True
                        break
                if changed:
                    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            zout.writestr(fn, raw, compress_type=zipfile.ZIP_DEFLATED)
    return buf_out.getvalue(), replaced_any


def merge_docx_placeholders(docx_bytes: bytes, values: dict[str, str]) -> tuple[str, bytes]:
    """
    Подставляет значения в плейсхолдеры вида {{field_id}} во всех word/*.xml.
    Ограничение MVP: плейсхолдер должен целиком попадать в один XML-текстовый фрагмент Word
    (при разбиении Word на «раны» подстановка может не сработать — тогда вставьте поле заново одним фрагментом).
    """
    buf_in = io.BytesIO(docx_bytes)
    buf_out = io.BytesIO()
    token_replacements = {"{{" + key + "}}": val for key, val in values.items()}
    merged = apply_docx_text_replacements(docx_bytes, token_replacements)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"dkp-{ts}.docx", merged


def render_version_to_docx(
    *,
    docx_bytes: bytes | None,
    docx_template_body: str,
    bindings_json: str,
    rules_json: str,
    payload_json: str,
) -> tuple[str, bytes]:
    """Объединяет логику: бинарный шаблон или текстовый legacy."""
    if docx_bytes:
        import json

        payload = json.loads(payload_json) if payload_json else {}
        if not isinstance(payload, dict):
            payload = {}
        flat = {str(k): "" if v is None else str(v) for k, v in payload.items()}
        return merge_docx_placeholders(docx_bytes, flat)
    result = generate_docx(docx_template_body, bindings_json, rules_json, payload_json)
    return result.file_name, result.bytes_
