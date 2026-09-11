from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import Invoice, LineItem
from app.domain.sku import normalize_invoice_id, normalize_sku, parse_money, parse_quantity
from app.ingestion.parsers import extraction_issues, parse_invoice
from app.llm import get_chat_model


class ExtractedLine(BaseModel):
    description: str
    quantity: float
    unit_price: float | None = None
    note: str | None = None


class ExtractedInvoice(BaseModel):
    invoice_id: str
    vendor: str
    invoice_date: str | None = None
    due_date: str | None = None
    line_items: list[ExtractedLine] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    shipping: float | None = None
    total: float | None = None
    currency: str = "USD"
    payment_terms: str | None = None
    notes: str | None = None
    revision: str | None = None


UNSTRUCTURED = {"txt", "pdf", "email"}

EXTRACT_SYSTEM = """You extract accounts-payable invoice fields from messy documents.
Return structured data only. Preserve bad data (negative quantities, empty vendor, nonsense dates)
rather than inventing fixes — downstream policy must see the real invoice.
Do not replace a supplier with the bill-to party (Acme Corp).
Normalize obvious OCR digit errors in money and dates (O vs 0).
Keep item names; a later step maps SKUs.
If the document is an email, ignore headers and extract the invoice body.
Currency defaults to USD unless explicitly EUR/GBP/etc.
If line totals and the claimed grand total disagree, keep both as printed — do not silently "fix" math.
"""


def deterministic_extract(path, text: str, fmt: str) -> Invoice:
    return parse_invoice(path, text, fmt)


def llm_extract(text: str, errors: list[str] | None = None) -> ExtractedInvoice | None:
    model, _provider = get_chat_model()
    if model is None:
        return None
    structured = model.with_structured_output(ExtractedInvoice)
    human = "Extract the invoice.\n\n" + text[:12000]
    if errors:
        human += "\n\nPrevious extraction had these problems — correct them if the source supports it:\n"
        human += "\n".join(f"- {e}" for e in errors)
        human += "\nDo not invent a vendor or total that is not in the source."
    return structured.invoke(
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": human},
        ]
    )


def to_invoice(extracted: ExtractedInvoice, base: Invoice) -> Invoice:
    items = [
        LineItem(
            description=line.description,
            sku=normalize_sku(line.description),
            quantity=parse_quantity(line.quantity) or 0.0,
            unit_price=parse_money(line.unit_price),
            note=line.note,
        )
        for line in extracted.line_items
    ]
    return base.model_copy(
        update={
            "invoice_id": normalize_invoice_id(extracted.invoice_id) or base.invoice_id,
            "vendor": extracted.vendor if extracted.vendor is not None else base.vendor,
            "invoice_date": extracted.invoice_date or base.invoice_date,
            "due_date": extracted.due_date or base.due_date,
            "line_items": items or base.line_items,
            "subtotal": extracted.subtotal if extracted.subtotal is not None else base.subtotal,
            "tax": extracted.tax if extracted.tax is not None else base.tax,
            "shipping": extracted.shipping if extracted.shipping is not None else base.shipping,
            "total": extracted.total if extracted.total is not None else base.total,
            "currency": (extracted.currency or base.currency or "USD").upper(),
            "payment_terms": extracted.payment_terms or base.payment_terms,
            "notes": extracted.notes or base.notes,
            "revision": extracted.revision or base.revision,
            "extraction_confidence": 0.85,
        }
    )


def extract_with_repair(path, text: str, fmt: str, max_attempts: int = 2) -> tuple[Invoice, list[str], int]:
    """Deterministic parse first. Unstructured text is a proposal: check, then LLM-repair."""
    invoice = deterministic_extract(path, text, fmt)
    attempts = 0
    notes: list[str] = []
    unstructured = fmt in UNSTRUCTURED
    if not unstructured:
        return invoice, notes, attempts

    issues = extraction_issues(invoice)
    need_llm = bool(issues) or invoice.extraction_confidence < 0.8
    if not need_llm:
        return invoice, notes, attempts

    while attempts < max_attempts:
        attempts += 1
        extracted = llm_extract(text, issues)
        if extracted is None:
            notes.append("No LLM configured; kept deterministic extract")
            break
        invoice = to_invoice(extracted, invoice)
        issues = extraction_issues(invoice)
        notes.append(f"LLM extract attempt {attempts}: {issues or 'checks ok'}")
        if not issues:
            invoice.extraction_confidence = max(invoice.extraction_confidence, 0.85)
            break

    if issues:
        invoice.extraction_confidence = min(invoice.extraction_confidence, 0.4)
    return invoice, notes, attempts
