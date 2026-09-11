from __future__ import annotations

import csv
import json
import re
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree as ET

from app.domain.models import Invoice, LineItem
from app.domain.sku import (
    normalize_invoice_id,
    normalize_sku,
    ocr_fix_text,
    parse_money,
    parse_quantity,
)
from app.ingestion.detect import detect_format


SKIP_ITEM_NAMES = {
    "item",
    "description",
    "subtotal",
    "total",
    "tax",
    "shipping",
    "grand total",
    "sales tax",
    "amount",
}

BILL_TO_NAMES = {"acme corp", "acme"}


def read_source(path: Path) -> tuple[str, str]:
    """Return (text, format). PDF uses pdfplumber; everything else is utf-8."""
    if path.suffix.lower() == ".pdf":
        text = _read_pdf(path)
        return text, "pdf"
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, detect_format(path, text)


def _read_pdf(path: Path) -> str:
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def _header_index(header: list[str], *names: str) -> int | None:
    for i, cell in enumerate(header):
        if cell in names:
            return i
    return None


def _pdf_table_items(path: Path) -> list[LineItem]:
    """Prefer real table cells over whitespace-collapsed PDF text."""
    import pdfplumber

    items: list[LineItem] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                header = [(c or "").strip().lower() for c in table[0]]
                item_i = _header_index(header, "item", "description", "name", "sku")
                qty_i = _header_index(header, "qty", "quantity", "qty.")
                price_i = _header_index(header, "unit price", "price", "rate")
                amount_i = _header_index(header, "amount", "total", "line total")
                if item_i is None or qty_i is None:
                    continue
                for row in table[1:]:
                    cells = [(c or "").strip() for c in row]
                    if item_i >= len(cells):
                        continue
                    name = cells[item_i]
                    if not name or name.lower() in SKIP_ITEM_NAMES:
                        continue
                    if name.lower().startswith(("subtotal", "total", "tax", "grand")):
                        continue
                    qty = parse_quantity(cells[qty_i] if qty_i < len(cells) else None)
                    if qty is None:
                        continue
                    price = (
                        parse_money(cells[price_i])
                        if price_i is not None and price_i < len(cells)
                        else None
                    )
                    amount = (
                        parse_money(cells[amount_i])
                        if amount_i is not None and amount_i < len(cells)
                        else None
                    )
                    items.append(_item(name, qty, price, amount))
    return items


def parse_invoice(path: Path, text: str | None = None, fmt: str | None = None) -> Invoice:
    if text is None or fmt is None:
        text, fmt = read_source(path)
    fmt = fmt or detect_format(path, text)

    if fmt == "json":
        invoice = _parse_json(text)
    elif fmt == "xml":
        invoice = _parse_xml(text)
    elif fmt == "csv":
        invoice = _parse_csv(text)
    elif fmt == "pdf":
        invoice = _parse_text(text, fmt=fmt)
        table_items = _pdf_table_items(path)
        if table_items and len(table_items) >= max(len(invoice.line_items), 1):
            invoice.line_items = table_items
    else:
        invoice = _parse_text(text, fmt=fmt)

    invoice.source_path = str(path)
    invoice.source_format = fmt
    invoice.raw_text = text
    invoice.ocr_artifacts = invoice.ocr_artifacts or _looks_like_ocr(text)
    if invoice.invoice_id:
        invoice.invoice_id = normalize_invoice_id(invoice.invoice_id)
    return invoice


def _looks_like_ocr(text: str) -> bool:
    return bool(
        re.search(
            r"\d[Oo]\d|\.[Oo]\d|I N V O I C E|Payble|Distributers|2O26",
            text,
        )
    )


def _item(name: str, qty: float, price: float | None = None, total: float | None = None, note: str | None = None) -> LineItem:
    return LineItem(
        description=name.strip(),
        sku=normalize_sku(name),
        quantity=qty,
        unit_price=price,
        line_total=total,
        note=note,
    )


def _is_bill_to(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered in BILL_TO_NAMES or lowered.startswith("acme corp")


def _vendor_name(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(
            value.get("name") or value.get("vendor") or value.get("supplier") or ""
        ).strip()
    return str(value).strip()


def _parse_json(text: str) -> Invoice:
    data = json.loads(text)
    raw_items = data.get("line_items") or data.get("items") or data.get("lines") or []
    items = []
    for raw in raw_items:
        name = raw.get("item") or raw.get("name") or raw.get("description") or ""
        qty = parse_quantity(raw.get("quantity") if "quantity" in raw else raw.get("qty")) or 0.0
        price = parse_money(raw.get("unit_price") if "unit_price" in raw else raw.get("price"))
        amount = parse_money(raw.get("amount") if "amount" in raw else raw.get("line_total"))
        items.append(_item(name, qty, price, amount, raw.get("note")))
    vendor = _vendor_name(data.get("vendor") if "vendor" in data else data.get("supplier"))
    invoice_id = (
        data.get("invoice_number")
        or data.get("invoice_id")
        or data.get("invoiceNo")
        or data.get("invoice_no")
        or ""
    )
    return Invoice(
        invoice_id=normalize_invoice_id(str(invoice_id)),
        vendor=vendor,
        invoice_date=_as_str(data.get("date") or data.get("invoice_date")),
        due_date=_as_str(data.get("due_date")),
        line_items=items,
        subtotal=parse_money(data.get("subtotal")),
        tax=parse_money(data.get("tax_amount") if data.get("tax_amount") is not None else data.get("tax")),
        shipping=parse_money(data.get("shipping")),
        total=parse_money(data.get("total") if data.get("total") is not None else data.get("total_amount")),
        currency=(data.get("currency") or "USD").upper(),
        payment_terms=_as_str(data.get("payment_terms")),
        notes=_as_str(data.get("notes")),
        revision=_as_str(data.get("revision")),
    )


def _as_str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _parse_xml(text: str) -> Invoice:
    root = ET.fromstring(text)
    header = root.find("header") if root.find("header") is not None else root

    def text_of(*paths: str) -> str | None:
        for path in paths:
            node = root.find(path)
            if node is not None and node.text:
                return node.text.strip()
            node = header.find(path.split("/")[-1]) if header is not None else None
            if node is not None and node.text:
                return node.text.strip()
        return None

    items: list[LineItem] = []
    for node in root.findall(".//line_items/item") or root.findall(".//item"):
        name = (node.findtext("name") or node.findtext("item") or "").strip()
        if not name:
            continue
        qty = parse_quantity(node.findtext("quantity")) or 0.0
        price = parse_money(node.findtext("unit_price"))
        items.append(_item(name, qty, price))

    currency = (text_of("header/currency", "currency") or "USD").upper()
    return Invoice(
        invoice_id=normalize_invoice_id(text_of("header/invoice_number", "invoice_number") or ""),
        vendor=text_of("header/vendor", "vendor") or "",
        invoice_date=text_of("header/date", "date"),
        due_date=text_of("header/due_date", "due_date"),
        line_items=items,
        subtotal=parse_money(text_of("totals/subtotal", "subtotal")),
        tax=parse_money(text_of("totals/tax_amount", "tax_amount")),
        total=parse_money(text_of("totals/total", "total")),
        currency=currency,
        payment_terms=text_of("payment_terms"),
    )


def _parse_csv(text: str) -> Invoice:
    sample = text.lstrip()
    first = sample.splitlines()[0] if sample else ""
    if first.lower().startswith("field,value"):
        return _parse_vertical_csv(text)
    return _parse_tabular_csv(text)


def _parse_vertical_csv(text: str) -> Invoice:
    reader = csv.reader(StringIO(text))
    header = next(reader, None)
    if not header:
        raise ValueError("Empty CSV")
    fields: dict[str, str] = {}
    items: list[LineItem] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current.get("item"):
            items.append(
                _item(
                    current["item"],
                    parse_quantity(current.get("quantity")) or 0.0,
                    parse_money(current.get("unit_price")),
                )
            )
        current = {}

    for row in reader:
        if len(row) < 2:
            continue
        key, value = row[0].strip(), row[1].strip()
        if key == "item":
            flush()
            current["item"] = value
        elif key in {"quantity", "unit_price"} and (current.get("item") or key in current):
            current[key] = value
        else:
            if current:
                flush()
            fields[key] = value
    flush()

    return Invoice(
        invoice_id=normalize_invoice_id(fields.get("invoice_number", "")),
        vendor=fields.get("vendor", ""),
        invoice_date=fields.get("date"),
        due_date=fields.get("due_date"),
        line_items=items,
        subtotal=parse_money(fields.get("subtotal")),
        tax=parse_money(fields.get("tax")),
        total=parse_money(fields.get("total")),
        payment_terms=fields.get("payment_terms"),
        currency="USD",
    )


def _parse_tabular_csv(text: str) -> Invoice:
    reader = csv.DictReader(StringIO(text))
    items: list[LineItem] = []
    invoice_id = ""
    vendor = ""
    date = None
    due = None
    subtotal = None
    tax = None
    total = None

    for row in reader:
        # DictReader keys from first header
        values = { (k or "").strip(): (v or "").strip() for k, v in row.items() }
        inv = values.get("Invoice Number") or values.get("invoice_number") or ""
        item_name = values.get("Item") or values.get("item") or ""
        qty_raw = values.get("Qty") or values.get("quantity") or ""
        last_label = ""
        last_value = ""
        # Trailing total rows put the label in the unit-price column and amount in Line Total
        nonempty = [(k, v) for k, v in values.items() if v]
        if len(nonempty) <= 2:
            for _, v in nonempty:
                lowered = v.lower().rstrip(":")
                if "subtotal" in lowered:
                    last_label = "subtotal"
                elif lowered.startswith("tax"):
                    last_label = "tax"
                elif "total" in lowered:
                    last_label = "total"
                else:
                    last_value = v
            amount = parse_money(last_value)
            if last_label == "subtotal":
                subtotal = amount
            elif last_label == "tax":
                tax = amount
            elif last_label == "total":
                total = amount
            continue

        if inv:
            invoice_id = inv
        if values.get("Vendor") or values.get("vendor"):
            vendor = values.get("Vendor") or values.get("vendor") or vendor
        if values.get("Date") or values.get("date"):
            date = values.get("Date") or values.get("date")
        if values.get("Due Date") or values.get("due_date"):
            due = values.get("Due Date") or values.get("due_date")

        if item_name and item_name.lower() not in SKIP_ITEM_NAMES:
            items.append(
                _item(
                    item_name,
                    parse_quantity(qty_raw) or 0.0,
                    parse_money(values.get("Unit Price") or values.get("unit_price")),
                    parse_money(values.get("Line Total") or values.get("line_total")),
                )
            )

    return Invoice(
        invoice_id=normalize_invoice_id(invoice_id),
        vendor=vendor,
        invoice_date=date,
        due_date=due,
        line_items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        currency="USD",
    )


def _parse_text(text: str, fmt: str = "txt") -> Invoice:
    raw = text
    text = ocr_fix_text(text)
    vendor = _pick_vendor(text)

    invoice_id = _search(
        text,
        r"(?:Invoice Number|Invoice #|Inv #|INV NO|Invoice)\s*:?\s*(INV[-\s]?\d+|\d+)",
    )
    if not invoice_id:
        invoice_id = _search(text, r"\b(INV[-\s]?\d+)\b")

    date = _search(text, r"(?:Invoice Date|Date|Dt)\s*:?\s*(.+)")
    due = _search(text, r"(?:Due Date|Due Dt|Due)\s*:?\s*(.+)")
    if due:
        due = due.split("\n")[0].strip()
        if due.lower() in {"yesterday", "tomorrow"}:
            pass
        else:
            due = due.split("  ")[0].strip()

    notes = _search(text, r"(?:Notes|NOTES)\s*:?\s*(.+)")
    terms = _search(text, r"(?:Payment Terms|Pymnt Terms|Terms)\s*:?\s*(.+)")

    currency = "EUR" if "€" in raw or re.search(r"\bEUR\b", raw) else "USD"

    items = _parse_text_items(text)
    totals = _parse_text_totals(text)

    confidence = 0.95 if invoice_id and vendor and items and totals.get("total") is not None else 0.6
    if fmt == "email":
        confidence = min(confidence, 0.9)

    return Invoice(
        invoice_id=normalize_invoice_id(invoice_id or ""),
        vendor=(vendor or "").strip(),
        invoice_date=_clean_field(date),
        due_date=_clean_field(due),
        line_items=items,
        subtotal=totals.get("subtotal"),
        tax=totals.get("tax"),
        shipping=totals.get("shipping"),
        total=totals.get("total"),
        currency=currency,
        payment_terms=_clean_field(terms),
        notes=_clean_field(notes),
        extraction_confidence=confidence,
        ocr_artifacts=_looks_like_ocr(raw),
    )


def _pick_vendor(text: str) -> str:
    """Skip bill-to / Acme Corp FROM lines when a real Vendor: exists."""
    matches = re.findall(r"(?:Vendor|Vndr|FROM)\s*:\s*(.+)", text, re.IGNORECASE)
    cleaned: list[str] = []
    for raw in matches:
        value = raw.split("(")[0].strip()
        value = re.split(r"\s{2,}|\n|\s+Due:", value, maxsplit=1)[0].strip()
        if not value or value.lower().startswith("formerly"):
            continue
        if "@" in value:
            continue
        cleaned.append(value)
    for value in cleaned:
        if not _is_bill_to(value):
            return value
    return cleaned[0] if cleaned else ""


def _clean_field(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    value = re.split(r"\s{2,}|\n", value)[0].strip()
    if value.lower() in {"acme corp", "attn:"}:
        return None
    return value


def _search(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() if match.lastindex else match.group(0).strip()


def _parse_text_items(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    patterns = [
        re.compile(
            r"^\s*-\s*(?P<name>[A-Za-z][\w\s()-]*?)\s+x\s*(?P<qty>-?\d+)\s+\$?(?P<price>[\d,]+(?:\.\d+)?)",
            re.I,
        ),
        re.compile(
            r"^\s*(?P<name>[A-Za-z][\w\s()-]*?)\s+qty:?\s*(?P<qty>-?\d+)\s+(?:unit price:|@)\s*\$?(?P<price>[\d,]+(?:\.\d+)?)",
            re.I,
        ),
        re.compile(
            r"^\s*(?P<name>[A-Za-z][\w\s()-]*?)\s+qty\s+(?P<qty>-?\d+)\s+@\s*\$?(?P<price>[\d,]+)",
            re.I,
        ),
        re.compile(
            r"^\s*(?P<name>[A-Za-z][\w\s()-]+?)\s{2,}(?P<qty>-?\d+)\s+\$?(?P<price>[\d,]+(?:\.[O0\d]+)?)\s+\$?(?P<total>[\d,]+(?:\.[O0\d]+)?)",
            re.I,
        ),
        re.compile(
            r"^\s*(?P<name>[A-Za-z][\w\s()-]+?)\s{2,}(?P<qty>-?\d+)\s+\$?(?P<price>[\d,]+(?:\.\d+)?)\s+\$?(?P<total>[\d,]+(?:\.\d+)?)",
            re.I,
        ),
        re.compile(
            r"^\s*(?P<name>[A-Za-z][\w()-]*(?:\s+[A-Za-z][\w()-]*)*(?:\s+\([^)]+\))?)\s+(?P<qty>-?\d+)\s+\$(?P<price>[\d,]+(?:\.[O0\d]+)?)\s+\$(?P<total>[\d,]+(?:\.[O0\d]+)?)\s*$",
            re.I,
        ),
    ]

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-" * 5):
            continue
        lower = stripped.lower()
        if lower.startswith(("subtotal", "total", "tax", "sales tax", "shipping", "grand")):
            continue
        if lower.startswith(("item ", "description", "from:", "to:", "vendor", "invoice")):
            continue
        matched = None
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                matched = match
                break
        if not matched:
            continue
        name = matched.group("name").strip()
        if name.lower() in SKIP_ITEM_NAMES or len(name) < 3:
            continue
        qty = parse_quantity(matched.group("qty")) or 0.0
        price = parse_money(matched.group("price")) if "price" in matched.groupdict() else None
        total = parse_money(matched.group("total")) if "total" in matched.groupdict() and matched.groupdict().get("total") else None
        items.append(_item(name, qty, price, total))
    return items


def _parse_text_totals(text: str) -> dict[str, float | None]:
    totals: dict[str, float | None] = {"subtotal": None, "tax": None, "shipping": None, "total": None}
    for line in text.splitlines():
        stripped = line.strip()
        amount_match = re.search(r"\$?\s*([\d,]+(?:\.[O0\d]+)?)\s*$", stripped)
        if not amount_match:
            # Amt: $15,000.00 on same line as label
            labeled = re.search(
                r"(Total Amount|Grand Total|TOTAL|Amt)\s*:?\s*\$?\s*([\d,]+(?:\.[O0\d]+)?)",
                stripped,
                re.I,
            )
            if labeled:
                totals["total"] = parse_money(labeled.group(2))
            continue
        amount = parse_money(amount_match.group(1))
        lower = stripped.lower()
        if lower.startswith("subtotal") or "subtotal:" in lower:
            totals["subtotal"] = amount
        elif "shipping" in lower:
            totals["shipping"] = amount
        elif lower.startswith("tax") or "sales tax" in lower or re.search(r"tax\s*\(", lower):
            totals["tax"] = amount
        elif re.search(r"\b(total amount|grand total|total|amt)\b", lower):
            if "subtotal" not in lower:
                totals["total"] = amount
    return totals


def extraction_gaps(invoice: Invoice) -> list[str]:
    gaps: list[str] = []
    if not invoice.invoice_id:
        gaps.append("Missing invoice number")
    if not (invoice.vendor or "").strip():
        gaps.append("Missing vendor")
    if not invoice.line_items:
        gaps.append("Missing line items")
    if invoice.total is None:
        gaps.append("Missing total")
    return gaps


def extraction_issues(invoice: Invoice) -> list[str]:
    """Problems that mean the parse is incomplete or the wrong party/amount.

    Math mismatches are included: they may be a dropped line (parse) or a bad
    invoice (integrity). Either way the extract should not be trusted blindly.
    """
    from app.config import settings
    from app.domain.policy import compute_expected_total

    issues = extraction_gaps(invoice)
    vendor = (invoice.vendor or "").strip()
    if vendor and _is_bill_to(vendor):
        issues.append(f"Vendor '{vendor}' looks like a bill-to party, not the supplier")

    tol = settings.math_tolerance
    for item in invoice.line_items:
        if item.unit_price is None or item.line_total is None:
            continue
        expected_line = round(item.quantity * item.unit_price, 2)
        if abs(expected_line - item.line_total) > tol:
            issues.append(
                f"Line {item.sku}: qty*price={expected_line:.2f} vs line_total={item.line_total:.2f}"
            )

    expected_total = compute_expected_total(invoice)
    if invoice.total is not None and expected_total is not None:
        if abs(invoice.total - expected_total) > tol:
            issues.append(
                f"Claimed total {invoice.total:.2f} vs computed {expected_total:.2f}"
            )
    return issues
