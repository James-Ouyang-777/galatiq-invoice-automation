from __future__ import annotations

import uuid

from app.db import record_payment
from app.domain.models import PaymentResult


def mock_payment(vendor: str, amount: float) -> dict:
    """Banking API stand-in — the brief's contract, plus a payment id."""
    print(f"Paid {amount} to {vendor}")
    return {"status": "success", "vendor": vendor, "amount": amount}


def execute_payment(
    conn,
    *,
    invoice_id: str,
    vendor: str,
    amount: float,
    paid_ids: set[str],
) -> PaymentResult:
    if invoice_id in paid_ids:
        return PaymentResult(
            status="already_paid",
            payment_id=None,
            vendor=vendor,
            amount=amount,
            message=f"{invoice_id} was already paid — idempotent skip",
            idempotent=True,
        )
    raw = mock_payment(vendor, amount)
    payment_id = f"pay_{uuid.uuid4().hex[:10]}"
    record_payment(conn, payment_id, invoice_id, vendor, amount)
    return PaymentResult(
        status=raw.get("status", "success"),
        payment_id=payment_id,
        vendor=vendor,
        amount=amount,
        message=f"Paid {amount:,.2f} to {vendor}",
        idempotent=False,
    )
