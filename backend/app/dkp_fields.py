"""Поля формы ДКП между юридическими лицами (демо-набор из 10 полей)."""

from __future__ import annotations

import json
from typing import Any

DKP_FIELDS: list[dict[str, Any]] = [
    {"id": "seller_company_name", "label": "Продавец — полное наименование"},
    {"id": "seller_inn", "label": "Продавец — ИНН"},
    {"id": "seller_ogrn", "label": "Продавец — ОГРН"},
    {"id": "seller_address", "label": "Продавец — юридический адрес"},
    {"id": "buyer_company_name", "label": "Покупатель — полное наименование"},
    {"id": "buyer_inn", "label": "Покупатель — ИНН"},
    {"id": "buyer_ogrn", "label": "Покупатель — ОГРН"},
    {"id": "buyer_address", "label": "Покупатель — юридический адрес"},
    {"id": "subject_matter", "label": "Предмет договора (краткое описание)"},
    {"id": "price_amount", "label": "Цена договора (руб., цифрами)"},
]


def dkp_schema_json() -> str:
    return json.dumps({f["id"]: {"label": f["label"]} for f in DKP_FIELDS}, ensure_ascii=False)


def dkp_starter_template_text() -> str:
    return (
        "ДОГОВОР КУПЛИ-ПРОДАЖИ № _____\n"
        "\n"
        "г. _______________ «___» __________20__ г.\n"
        "\n"
        "{{seller_company_name}}, именуемое в дальнейшем «Продавец», ИНН {{seller_inn}}, ОГРН {{seller_ogrn}}, "
        "адрес: {{seller_address}}, с одной стороны, и\n"
        "\n"
        "{{buyer_company_name}}, именуемое в дальнейшем «Покупатель», ИНН {{buyer_inn}}, ОГРН {{buyer_ogrn}}, "
        "адрес: {{buyer_address}}, с другой стороны,\n"
        "\n"
        "заключили настоящий договор о нижеследующем:\n"
        "\n"
        "1. Предмет договора\n"
        "{{subject_matter}}\n"
        "\n"
        "2. Цена и порядок расчётов\n"
        "Цена договора составляет {{price_amount}} (_____) рублей 00 копеек.\n"
        "\n"
        "3. Заключительные положения\n"
        "(дополните договор в редакторе или загрузьте свой .docx)\n"
    )
