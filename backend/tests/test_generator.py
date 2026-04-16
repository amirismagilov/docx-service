from app.generator import generate_docx


def test_generate_replaces_placeholders_and_applies_if_rule() -> None:
    result = generate_docx(
        "Hello {{customerName}} [VIP]",
        '{"customerName":"name"}',
        '[{"type":"if","field":"tier","equals":"vip","block":"[VIP]"}]',
        '{"name":"Alice","tier":"regular"}',
    )
    text = result.bytes_.decode("utf-8")
    assert "Hello Alice" in text
    assert "[VIP]" not in text
