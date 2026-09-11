from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    HOLD = "hold"
    REJECT = "reject"


class Route(str, Enum):
    PAY = "pay"
    VP = "vp"
    HOLD = "hold"
    HOLD_WITH_VP = "hold_with_vp"
    REJECT = "reject"


class InvoiceStatus(str, Enum):
    EXTRACTED = "extracted"
    HELD = "held"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    FAILED = "failed"


class Flag(BaseModel):
    code: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class LineItem(BaseModel):
    description: str
    sku: str
    quantity: float
    unit_price: float | None = None
    line_total: float | None = None
    note: str | None = None

    def extended(self) -> float | None:
        if self.quantity is None or self.unit_price is None:
            return self.line_total
        return round(self.quantity * self.unit_price, 2)


class Invoice(BaseModel):
    invoice_id: str
    vendor: str
    invoice_date: str | None = None
    due_date: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    shipping: float | None = None
    total: float | None = None
    currency: str = "USD"
    payment_terms: str | None = None
    notes: str | None = None
    revision: str | None = None
    source_path: str | None = None
    source_format: str | None = None
    raw_text: str | None = None
    extraction_confidence: float = 1.0
    ocr_artifacts: bool = False

    def aggregated_quantities(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for item in self.line_items:
            totals[item.sku] = totals.get(item.sku, 0.0) + item.quantity
        return totals


class InventoryRow(BaseModel):
    item: str
    stock: int
    unit_price_usd: float | None = None


class ItemValidation(BaseModel):
    sku: str
    quantity: float
    in_catalog: bool
    stock: int | None = None
    status: Literal["ok", "unknown", "out_of_stock", "exceeds_stock"]
    message: str


class ValidationResult(BaseModel):
    items: list[ItemValidation] = Field(default_factory=list)
    already_paid: bool = False
    prior_run: bool = False
    claimed_total: float | None = None
    computed_total: float | None = None
    math_delta: float | None = None


class PolicyResult(BaseModel):
    flags: list[Flag]
    route: Route
    recommended_status: InvoiceStatus
    summary: str


class VPDecision(BaseModel):
    draft_decision: Literal["approve", "reject"]
    draft_rationale: str
    critic_agrees: bool
    critic_issues: list[str] = Field(default_factory=list)
    final_decision: Literal["approve", "reject"]
    final_rationale: str
    confidence: float = 0.5
    used_llm: bool = False


class PaymentResult(BaseModel):
    status: str
    payment_id: str | None = None
    vendor: str
    amount: float
    message: str
    idempotent: bool = False


class TraceEvent(BaseModel):
    at: str
    node: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class InvoiceRun(BaseModel):
    run_id: str
    invoice_id: str | None = None
    source_path: str
    status: InvoiceStatus
    vendor: str | None = None
    amount: float | None = None
    currency: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    invoice: Invoice | None = None
    validation: ValidationResult | None = None
    policy: PolicyResult | None = None
    vp: VPDecision | None = None
    payment: PaymentResult | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
