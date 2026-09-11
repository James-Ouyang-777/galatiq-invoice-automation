from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import Invoice, PolicyResult, VPDecision
from app.llm import get_chat_model


class VPDraft(BaseModel):
    decision: str = Field(description="approve or reject")
    rationale: str
    risk_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class VPCritique(BaseModel):
    agrees: bool
    issues: list[str] = Field(default_factory=list)
    revised_decision: str = Field(description="approve or reject")
    revised_rationale: str


DRAFT_SYSTEM = """You are the VP of Finance at Acme Corp, a PE-backed manufacturer.
You review invoices before payment. Controls matter more than speed.
Never approve: empty vendor, negative quantities, watchlist vendors, unknown SKUs,
stock shortages, non-USD without treasury FX, math mismatches, or duplicate payments.
High value (>$10k) that is otherwise clean may be approved with a written rationale.
Be concise. Decision must be exactly 'approve' or 'reject'.
"""

CRITIC_SYSTEM = """You are an internal audit critic reviewing a VP payment decision.
Check the decision against policy flags. If the VP approved something with hold/reject flags, disagree.
If the VP rejected a clean invoice, disagree.
Return a revised decision of 'approve' or 'reject'.
"""


def _coerce_decision(value: str) -> str:
    value = (value or "").strip().lower()
    return "approve" if value.startswith("approve") else "reject"


def heuristic_vp(invoice: Invoice, policy: PolicyResult) -> VPDecision:
    material = [f for f in policy.flags if f.severity.value in {"hold", "reject"}]
    if material:
        reasons = "; ".join(f.message for f in material)
        rationale = f"Controls block payment: {reasons}"
        return VPDecision(
            draft_decision="reject",
            draft_rationale=rationale,
            critic_agrees=True,
            critic_issues=[],
            final_decision="reject",
            final_rationale=rationale + " Auditor agrees.",
            confidence=0.9,
            used_llm=False,
        )
    rationale = (
        f"{invoice.invoice_id} from {invoice.vendor} for {invoice.total:,.2f} "
        f"{invoice.currency} is clean against inventory and math. Approve with standard terms."
    )
    return VPDecision(
        draft_decision="approve",
        draft_rationale=rationale,
        critic_agrees=True,
        critic_issues=[],
        final_decision="approve",
        final_rationale=rationale + " Auditor agrees.",
        confidence=0.8,
        used_llm=False,
    )


def vp_review(invoice: Invoice, policy: PolicyResult) -> VPDecision:
    model, _provider = get_chat_model()
    if model is None:
        return heuristic_vp(invoice, policy)

    flags = [{"code": f.code, "severity": f.severity.value, "message": f.message} for f in policy.flags]
    payload = {
        "invoice_id": invoice.invoice_id,
        "vendor": invoice.vendor,
        "total": invoice.total,
        "currency": invoice.currency,
        "due_date": invoice.due_date,
        "items": [i.model_dump() for i in invoice.line_items],
        "notes": invoice.notes,
        "policy_summary": policy.summary,
        "flags": flags,
    }
    draft = model.with_structured_output(VPDraft).invoke(
        [
            {"role": "system", "content": DRAFT_SYSTEM},
            {"role": "user", "content": f"Review this invoice:\n{payload}"},
        ]
    )
    critic = model.with_structured_output(VPCritique).invoke(
        [
            {"role": "system", "content": CRITIC_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Invoice flags: {flags}\n"
                    f"VP draft: {draft.model_dump()}\n"
                    "Audit the decision."
                ),
            },
        ]
    )
    final = _coerce_decision(critic.revised_decision)
    return VPDecision(
        draft_decision=_coerce_decision(draft.decision),
        draft_rationale=draft.rationale,
        critic_agrees=bool(critic.agrees),
        critic_issues=critic.issues,
        final_decision=final,
        final_rationale=critic.revised_rationale,
        confidence=float(draft.confidence or 0.5),
        used_llm=True,
    )
