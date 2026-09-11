from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.approve import vp_review
from app.agents.extract import extract_with_repair
from app.db import db_session, load_catalog, paid_invoice_ids, prior_sources_for
from app.domain.models import (
    Invoice,
    InvoiceStatus,
    Route,
    TraceEvent,
    utc_now,
)
from app.domain.policy import evaluate_policy
from app.ingestion.detect import detect_format
from app.ingestion.parsers import read_source
from app.logging import get_logger
from app.tools.payment import execute_payment

log = get_logger("acme.ap.graph")


class GraphState(TypedDict, total=False):
    run_id: str
    db_path: str
    source_path: str
    raw_text: str
    fmt: str
    invoice: dict[str, Any]
    extract_notes: list[str]
    extract_attempts: int
    validation: dict[str, Any]
    policy: dict[str, Any]
    flags: list[dict[str, Any]]
    route: str
    vp: dict[str, Any]
    payment: dict[str, Any]
    status: str
    trace: list[dict[str, Any]]
    error: str


def _append_trace(state: GraphState, node: str, message: str, **data: Any) -> list[dict[str, Any]]:
    events = list(state.get("trace") or [])
    events.append(
        TraceEvent(at=utc_now(), node=node, message=message, data=data).model_dump()
    )
    return events


def ingest_node(state: GraphState) -> dict[str, Any]:
    path = Path(state["source_path"])
    text, fmt = read_source(path)
    fmt = detect_format(path, text)
    return {
        "raw_text": text,
        "fmt": fmt,
        "trace": _append_trace(
            state, "ingest", f"Read {path.name} as {fmt}", bytes=len(text.encode())
        ),
    }


def extract_node(state: GraphState) -> dict[str, Any]:
    path = Path(state["source_path"])
    invoice, notes, attempts = extract_with_repair(path, state["raw_text"], state["fmt"])
    return {
        "invoice": invoice.model_dump(),
        "extract_notes": notes,
        "extract_attempts": attempts,
        "trace": _append_trace(
            state,
            "extract",
            f"Extracted {invoice.invoice_id or '(unknown)'} from {invoice.vendor or '(no vendor)'}",
            attempts=attempts,
            notes=notes,
            items=len(invoice.line_items),
            total=invoice.total,
            confidence=invoice.extraction_confidence,
        ),
    }


def validate_node(state: GraphState) -> dict[str, Any]:
    invoice = Invoice.model_validate(state["invoice"])
    db_path = Path(state["db_path"])
    with db_session(db_path) as conn:
        catalog = load_catalog(conn)
        paid = paid_invoice_ids(conn)
        priors = prior_sources_for(conn, invoice.invoice_id, state["source_path"])
        item_lookups = {
            sku: {
                "in_catalog": sku in catalog,
                "stock": catalog[sku].stock if sku in catalog else None,
            }
            for sku in invoice.aggregated_quantities()
        }
        validation, policy = evaluate_policy(
            invoice,
            catalog,
            paid_ids=paid,
            prior_sources=priors,
        )
    return {
        "validation": validation.model_dump(),
        "policy": policy.model_dump(),
        "flags": [f.model_dump() for f in policy.flags],
        "route": policy.route.value,
        "trace": _append_trace(
            state,
            "validate",
            policy.summary,
            route=policy.route.value,
            flags=[f.code for f in policy.flags],
            inventory_lookups=item_lookups,
        ),
    }


def policy_node(state: GraphState) -> dict[str, Any]:
    # Policy already computed in validate; this node exists so the graph matches the four-stage story.
    route = state.get("route")
    return {
        "trace": _append_trace(
            state, "policy", f"Routing to {route}", route=route
        )
    }


def vp_node(state: GraphState) -> dict[str, Any]:
    from app.domain.models import PolicyResult

    invoice = Invoice.model_validate(state["invoice"])
    policy = PolicyResult.model_validate(state["policy"])
    decision = vp_review(invoice, policy)
    return {
        "vp": decision.model_dump(),
        "trace": _append_trace(
            state,
            "vp_review",
            f"VP {decision.final_decision} (critic {'agrees' if decision.critic_agrees else 'revises'})",
            draft=decision.draft_decision,
            final=decision.final_decision,
            used_llm=decision.used_llm,
            rationale=decision.final_rationale,
        ),
    }


def pay_node(state: GraphState) -> dict[str, Any]:
    invoice = Invoice.model_validate(state["invoice"])
    amount = invoice.total or 0.0
    db_path = Path(state["db_path"])
    with db_session(db_path) as conn:
        paid = paid_invoice_ids(conn)
        result = execute_payment(
            conn,
            invoice_id=invoice.invoice_id,
            vendor=invoice.vendor or "UNKNOWN",
            amount=amount,
            paid_ids=paid,
        )
    status = InvoiceStatus.PAID.value
    if result.idempotent:
        status = InvoiceStatus.HELD.value
    return {
        "payment": result.model_dump(),
        "status": status,
        "trace": _append_trace(state, "pay", result.message, payment=result.model_dump()),
    }


def hold_node(state: GraphState) -> dict[str, Any]:
    return {
        "status": InvoiceStatus.HELD.value,
        "trace": _append_trace(state, "hold", "Parked in the exception queue for a clerk"),
    }


def reject_node(state: GraphState) -> dict[str, Any]:
    return {
        "status": InvoiceStatus.REJECTED.value,
        "trace": _append_trace(state, "reject", "Rejected — unsafe to pay"),
    }


def route_after_policy(state: GraphState) -> str:
    route = state.get("route")
    if route == Route.REJECT.value:
        return "reject"
    if route == Route.PAY.value:
        return "pay"
    if route in {Route.VP.value, Route.HOLD_WITH_VP.value}:
        return "vp"
    return "hold"


def route_after_vp(state: GraphState) -> str:
    route = state.get("route")
    vp = state.get("vp") or {}
    # Holds stay holds; VP is advisory so clerks see a recommendation.
    if route == Route.HOLD_WITH_VP.value:
        return "hold"
    if vp.get("final_decision") == "approve":
        return "pay"
    return "reject"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("policy", policy_node)
    graph.add_node("vp_review", vp_node)
    graph.add_node("pay", pay_node)
    graph.add_node("hold", hold_node)
    graph.add_node("reject", reject_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "policy")
    graph.add_conditional_edges(
        "policy",
        route_after_policy,
        {"pay": "pay", "vp": "vp_review", "hold": "hold", "reject": "reject"},
    )
    graph.add_conditional_edges(
        "vp_review",
        route_after_vp,
        {"pay": "pay", "hold": "hold", "reject": "reject"},
    )
    graph.add_edge("pay", END)
    graph.add_edge("hold", END)
    graph.add_edge("reject", END)
    return graph.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
