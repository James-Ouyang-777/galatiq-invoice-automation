from __future__ import annotations

import re

from app.config import settings
from app.domain.models import (
    Flag,
    InventoryRow,
    Invoice,
    InvoiceStatus,
    ItemValidation,
    PolicyResult,
    Route,
    Severity,
    ValidationResult,
)


WATCHLIST_VENDORS = {"fraudster llc"}
FRAUD_NOTE_PATTERNS = re.compile(
    r"urgent|wire transfer|pay immediately|immediate payment|avoid penalties",
    re.IGNORECASE,
)
NONSENSICAL_DATES = {"yesterday", "tomorrow", "asap", "immediately", "n/a", "tbd"}


def _flag(code: str, severity: Severity, message: str, **details: object) -> Flag:
    return Flag(code=code, severity=severity, message=message, details=details)


def compute_line_sum(invoice: Invoice) -> float | None:
    total = 0.0
    any_priced = False
    for item in invoice.line_items:
        extended = item.extended()
        if extended is None:
            continue
        any_priced = True
        total += extended
    return round(total, 2) if any_priced else None


def compute_expected_total(invoice: Invoice) -> float | None:
    line_sum = compute_line_sum(invoice)
    base = invoice.subtotal if invoice.subtotal is not None else line_sum
    if base is None:
        return invoice.total
    tax = invoice.tax or 0.0
    shipping = invoice.shipping or 0.0
    return round(base + tax + shipping, 2)


def validate_inventory(
    invoice: Invoice,
    catalog: dict[str, InventoryRow],
) -> list[ItemValidation]:
    results: list[ItemValidation] = []
    for sku, qty in invoice.aggregated_quantities().items():
        row = catalog.get(sku)
        if row is None:
            results.append(
                ItemValidation(
                    sku=sku,
                    quantity=qty,
                    in_catalog=False,
                    stock=None,
                    status="unknown",
                    message=f"{sku} is not in the inventory catalog",
                )
            )
            continue
        if row.stock <= 0:
            results.append(
                ItemValidation(
                    sku=sku,
                    quantity=qty,
                    in_catalog=True,
                    stock=row.stock,
                    status="out_of_stock",
                    message=f"{sku} has zero stock (requested {qty:g})",
                )
            )
        elif qty > row.stock:
            results.append(
                ItemValidation(
                    sku=sku,
                    quantity=qty,
                    in_catalog=True,
                    stock=row.stock,
                    status="exceeds_stock",
                    message=f"{sku}: requested {qty:g}, only {row.stock} in stock",
                )
            )
        else:
            results.append(
                ItemValidation(
                    sku=sku,
                    quantity=qty,
                    in_catalog=True,
                    stock=row.stock,
                    status="ok",
                    message=f"{sku}: {qty:g} within stock of {row.stock}",
                )
            )
    return results


def evaluate_policy(
    invoice: Invoice,
    catalog: dict[str, InventoryRow],
    *,
    paid_ids: set[str] | None = None,
    prior_sources: list[str] | None = None,
    math_tolerance: float | None = None,
    high_value_threshold: float | None = None,
) -> tuple[ValidationResult, PolicyResult]:
    paid_ids = paid_ids or set()
    prior_sources = prior_sources or []
    tol = settings.math_tolerance if math_tolerance is None else math_tolerance
    threshold = (
        settings.high_value_threshold if high_value_threshold is None else high_value_threshold
    )

    item_validations = validate_inventory(invoice, catalog)
    line_sum = compute_line_sum(invoice)
    expected = compute_expected_total(invoice)
    claimed = invoice.total
    delta = None
    if claimed is not None and expected is not None:
        delta = round(claimed - expected, 2)

    validation = ValidationResult(
        items=item_validations,
        already_paid=invoice.invoice_id in paid_ids,
        prior_run=bool(prior_sources),
        claimed_total=claimed,
        computed_total=expected,
        math_delta=delta,
    )

    flags: list[Flag] = []

    vendor = (invoice.vendor or "").strip()
    if not vendor:
        flags.append(
            _flag(
                "empty_vendor",
                Severity.REJECT,
                "Vendor name is missing — cannot pay an unknown counterparty",
            )
        )
    elif vendor.lower() in WATCHLIST_VENDORS:
        flags.append(
            _flag(
                "watchlist_vendor",
                Severity.HOLD,
                f"{vendor} is on the fraud watchlist",
                vendor=vendor,
            )
        )

    if claimed is None:
        flags.append(
            _flag(
                "unparseable_amount",
                Severity.REJECT,
                "Invoice total could not be parsed",
            )
        )

    for item in invoice.line_items:
        if item.quantity < 0:
            flags.append(
                _flag(
                    "negative_quantity",
                    Severity.REJECT,
                    f"{item.sku} has a negative quantity ({item.quantity:g})",
                    sku=item.sku,
                    quantity=item.quantity,
                )
            )

    if not invoice.line_items:
        flags.append(
            _flag(
                "missing_line_items",
                Severity.HOLD,
                "No line items were extracted",
            )
        )

    for row in item_validations:
        if row.status == "unknown":
            flags.append(
                _flag(
                    "unknown_sku",
                    Severity.HOLD,
                    row.message,
                    sku=row.sku,
                    quantity=row.quantity,
                )
            )
        elif row.status == "out_of_stock":
            flags.append(
                _flag(
                    "zero_stock_item",
                    Severity.HOLD,
                    row.message,
                    sku=row.sku,
                    quantity=row.quantity,
                    stock=row.stock,
                )
            )
        elif row.status == "exceeds_stock":
            flags.append(
                _flag(
                    "stock_mismatch",
                    Severity.HOLD,
                    row.message,
                    sku=row.sku,
                    quantity=row.quantity,
                    stock=row.stock,
                )
            )

    currency = (invoice.currency or "USD").upper()
    if currency != "USD":
        flags.append(
            _flag(
                "non_usd",
                Severity.HOLD,
                f"Currency is {currency} — do not silently convert or pay",
                currency=currency,
            )
        )

    if invoice.subtotal is not None and line_sum is not None and abs(invoice.subtotal - line_sum) > tol:
        flags.append(
            _flag(
                "math_mismatch",
                Severity.HOLD,
                f"Line items sum to {line_sum:.2f} but subtotal is {invoice.subtotal:.2f}",
                line_sum=line_sum,
                subtotal=invoice.subtotal,
            )
        )

    if delta is not None and abs(delta) > tol:
        flags.append(
            _flag(
                "math_mismatch",
                Severity.HOLD,
                f"Claimed total {claimed:.2f} vs computed {expected:.2f} (delta {delta:.2f})",
                claimed=claimed,
                computed=expected,
                delta=delta,
            )
        )

    if invoice.revision:
        flags.append(
            _flag(
                "revision",
                Severity.HOLD,
                f"Invoice {invoice.invoice_id} is revision {invoice.revision} — needs AP review",
                revision=invoice.revision,
            )
        )

    if validation.already_paid:
        flags.append(
            _flag(
                "duplicate_invoice",
                Severity.HOLD,
                f"{invoice.invoice_id} was already paid — refusing a second disbursement",
            )
        )
    elif validation.prior_run:
        flags.append(
            _flag(
                "duplicate_invoice",
                Severity.HOLD,
                f"{invoice.invoice_id} was already processed from another file",
                prior_sources=prior_sources,
            )
        )

    due = (invoice.due_date or "").strip().lower()
    if due in NONSENSICAL_DATES:
        flags.append(
            _flag(
                "invalid_date",
                Severity.HOLD,
                f"Due date '{invoice.due_date}' is not a calendar date",
                due_date=invoice.due_date,
            )
        )

    notes = invoice.notes or ""
    terms = invoice.payment_terms or ""
    if FRAUD_NOTE_PATTERNS.search(f"{notes} {terms}"):
        flags.append(
            _flag(
                "fraud_signals",
                Severity.HOLD,
                "Urgency / wire-transfer language on the invoice",
            )
        )

    if invoice.ocr_artifacts and invoice.extraction_confidence < 0.7:
        flags.append(
            _flag(
                "ocr_uncertain",
                Severity.HOLD,
                "OCR artifacts remain after extraction — clerk should confirm fields",
                confidence=invoice.extraction_confidence,
            )
        )

    unstructured = (invoice.source_format or "") in {"txt", "pdf", "email"}
    if unstructured and invoice.extraction_confidence < 0.8:
        flags.append(
            _flag(
                "extract_uncertain",
                Severity.HOLD,
                "Extraction confidence is too low to auto-pay — clerk should confirm fields",
                confidence=invoice.extraction_confidence,
                source_format=invoice.source_format,
            )
        )

    amount = claimed if claimed is not None else expected
    if amount is not None and amount >= threshold:
        flags.append(
            _flag(
                "high_value",
                Severity.INFO,
                f"Amount {amount:,.2f} exceeds the ${threshold:,.0f} VP threshold",
                amount=amount,
                threshold=threshold,
            )
        )

    has_reject = any(f.severity == Severity.REJECT for f in flags)
    has_hold = any(f.severity == Severity.HOLD for f in flags)
    high_value = amount is not None and amount >= threshold

    if has_reject:
        route = Route.REJECT
        status = InvoiceStatus.REJECTED
    elif has_hold:
        route = Route.HOLD_WITH_VP if high_value else Route.HOLD
        status = InvoiceStatus.HELD
    elif high_value:
        route = Route.VP
        status = InvoiceStatus.APPROVED
    else:
        route = Route.PAY
        status = InvoiceStatus.PAID

    summary = _summarize(route, flags)
    policy = PolicyResult(flags=flags, route=route, recommended_status=status, summary=summary)
    return validation, policy


def _summarize(route: Route, flags: list[Flag]) -> str:
    material = [f for f in flags if f.severity != Severity.INFO]
    if route == Route.PAY:
        return "Clean invoice under the VP threshold — auto-pay."
    if route == Route.VP:
        return "Clean high-value invoice — VP agent must approve before payment."
    if route == Route.REJECT:
        reasons = "; ".join(f.message for f in material)
        return f"Rejected: {reasons}"
    if not material:
        return "Held for review."
    reasons = "; ".join(f.message for f in material)
    return f"Held: {reasons}"
