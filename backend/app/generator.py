"""DOCX placeholder generation (same semantics as the previous C# implementation)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GenerationResult:
    file_name: str
    bytes_: bytes


def generate_docx(
    docx_template_body: str,
    bindings_json: str,
    rules_json: str,
    payload_json: str,
) -> GenerationResult:
    payload = json.loads(payload_json) if payload_json else {}
    if not isinstance(payload, dict):
        payload = {}

    content = docx_template_body
    bindings = json.loads(bindings_json) if bindings_json else {}
    if not isinstance(bindings, dict):
        bindings = {}
    rules = json.loads(rules_json) if rules_json else []
    if not isinstance(rules, list):
        rules = []

    for placeholder, data_key in bindings.items():
        if not isinstance(placeholder, str) or not isinstance(data_key, str):
            continue
        raw = payload.get(data_key)
        value = "" if raw is None else str(raw)
        content = content.replace(f"{{{{{placeholder}}}}}", value)

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("type", "")).lower() != "if":
            continue
        field = str(rule.get("field", ""))
        equals = str(rule.get("equals", ""))
        block = str(rule.get("block", ""))
        raw = payload.get(field)
        matched = raw is not None and str(raw).lower() == equals.lower()
        if not matched:
            content = content.replace(block, "")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    file_name = f"document-{ts}.docx"
    return GenerationResult(file_name=file_name, bytes_=content.encode("utf-8"))
