from __future__ import annotations

import re


CANONICAL_SKUS: dict[str, str] = {
    "widgeta": "WidgetA",
    "widgetb": "WidgetB",
    "gadgetx": "GadgetX",
    "fakeitem": "FakeItem",
}


def strip_parenthetical(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()


def sku_key(name: str) -> str:
    cleaned = strip_parenthetical(name)
    return re.sub(r"[^a-z0-9]", "", cleaned.lower())


def normalize_sku(name: str) -> str:
    """Map OCR/spacing variants onto catalog names. Unknown items keep a cleaned form."""
    key = sku_key(name)
    if key in CANONICAL_SKUS:
        return CANONICAL_SKUS[key]
    cleaned = strip_parenthetical(name)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned or name.strip()


def normalize_invoice_id(raw: str | None) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits:
        return f"INV-{digits}"
    return raw.strip()


def ocr_fix_text(text: str) -> str:
    """Repair common OCR digit/letter swaps in dates and money without touching SKUs."""

    def fix_year(match: re.Match[str]) -> str:
        token = match.group(0).replace("O", "0").replace("o", "0")
        return token

    def fix_money(match: re.Match[str]) -> str:
        return match.group(0).replace("O", "0").replace("o", "0")

    text = re.sub(r"\b\d{1,2}-[A-Za-z]{3}-[\dO]{4}\b", fix_year, text)
    text = re.sub(r"\$[\d,]*[O0]\d*(?:\.[O0\d]+)?", fix_money, text)
    text = re.sub(r"\b(\d)[Oo](\d{2})\b", r"\g<1>0\g<2>", text)
    return text


def parse_money(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace(",", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_quantity(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {"-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None
