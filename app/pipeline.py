from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings
from app.db import audit, db_session, init_db, save_run
from app.domain.models import (
    Flag,
    Invoice,
    InvoiceRun,
    InvoiceStatus,
    PaymentResult,
    PolicyResult,
    TraceEvent,
    ValidationResult,
    VPDecision,
    utc_now,
)
from app.graph import get_graph
from app.logging import get_logger
from app.tools.payment import execute_payment

log = get_logger("acme.ap.pipeline")


def process_invoice(path: Path | str, *, db_path: Path | None = None) -> InvoiceRun:
    path = Path(path).resolve()
    db_path = Path(db_path or settings.database_path)
    init_db(db_path)

    run_id = uuid.uuid4().hex[:12]
    now = utc_now()
    log.info("processing invoice", extra={"run_id": run_id})

    graph = get_graph()
    try:
        raw = graph.invoke(
            {
                "run_id": run_id,
                "db_path": str(db_path),
                "source_path": str(path),
                "trace": [],
            }
        )
    except Exception as exc:  # noqa: BLE001 — persist failures for the ops UI
        log.exception("pipeline failed")
        run = InvoiceRun(
            run_id=run_id,
            invoice_id=None,
            source_path=str(path),
            status=InvoiceStatus.FAILED,
            flags=[],
            error=str(exc),
            created_at=now,
            updated_at=utc_now(),
        )
        with db_session(db_path) as conn:
            save_run(conn, run)
        return run

    invoice = Invoice.model_validate(raw["invoice"]) if raw.get("invoice") else None
    flags = [Flag.model_validate(f) for f in raw.get("flags") or []]
    status = InvoiceStatus(raw.get("status") or InvoiceStatus.FAILED.value)
    run = InvoiceRun(
        run_id=run_id,
        invoice_id=invoice.invoice_id if invoice else None,
        source_path=str(path),
        status=status,
        vendor=invoice.vendor if invoice else None,
        amount=invoice.total if invoice else None,
        currency=invoice.currency if invoice else None,
        flags=flags,
        invoice=invoice,
        validation=ValidationResult.model_validate(raw["validation"]) if raw.get("validation") else None,
        policy=PolicyResult.model_validate(raw["policy"]) if raw.get("policy") else None,
        vp=VPDecision.model_validate(raw["vp"]) if raw.get("vp") else None,
        payment=PaymentResult.model_validate(raw["payment"]) if raw.get("payment") else None,
        trace=[TraceEvent.model_validate(t) for t in (raw.get("trace") or [])],
        error=raw.get("error"),
        created_at=now,
        updated_at=utc_now(),
    )

    with db_session(db_path) as conn:
        save_run(conn, run)
        audit(
            conn,
            "processed",
            run_id=run.run_id,
            invoice_id=run.invoice_id,
            payload={"status": run.status.value, "source": str(path)},
        )
    return run


def override_pay(run_id: str, *, db_path: Path | None = None) -> InvoiceRun:
    from app.db import get_run

    db_path = Path(db_path or settings.database_path)
    with db_session(db_path) as conn:
        existing = get_run(conn, run_id)
        if not existing:
            raise KeyError(run_id)
        invoice = Invoice.model_validate(existing["invoice"])
        from app.db import paid_invoice_ids

        paid = paid_invoice_ids(conn)
        payment = execute_payment(
            conn,
            invoice_id=invoice.invoice_id,
            vendor=invoice.vendor or "UNKNOWN",
            amount=invoice.total or 0.0,
            paid_ids=paid,
        )
        run = _run_from_row(existing)
        run.status = InvoiceStatus.PAID
        run.payment = payment
        run.updated_at = utc_now()
        run.trace = list(run.trace) + [
            TraceEvent(
                at=utc_now(),
                node="human_override",
                message=f"Clerk overrode hold/reject and paid {invoice.invoice_id}",
                data=payment.model_dump(mode="json"),
            )
        ]
        save_run(conn, run)
        audit(
            conn,
            "override_pay",
            run_id=run_id,
            invoice_id=invoice.invoice_id,
            payload=payment.model_dump(),
        )
        return run


def override_reject(run_id: str, *, db_path: Path | None = None) -> InvoiceRun:
    from app.db import get_run

    db_path = Path(db_path or settings.database_path)
    with db_session(db_path) as conn:
        existing = get_run(conn, run_id)
        if not existing:
            raise KeyError(run_id)
        run = _run_from_row(existing)
        run.status = InvoiceStatus.REJECTED
        run.updated_at = utc_now()
        run.trace = list(run.trace) + [
            TraceEvent(
                at=utc_now(),
                node="human_override",
                message="Clerk confirmed rejection",
                data={},
            )
        ]
        save_run(conn, run)
        audit(conn, "override_reject", run_id=run_id, invoice_id=run.invoice_id)
        return run


def _run_from_row(row: dict) -> InvoiceRun:
    from app.domain.models import TraceEvent

    traces = []
    for event in row.get("trace") or []:
        traces.append(TraceEvent.model_validate(event) if isinstance(event, dict) else event)
    return InvoiceRun(
        run_id=row["run_id"],
        invoice_id=row.get("invoice_id"),
        source_path=row["source_path"],
        status=InvoiceStatus(row["status"]),
        vendor=row.get("vendor"),
        amount=row.get("amount"),
        currency=row.get("currency"),
        flags=[Flag.model_validate(f) for f in row.get("flags") or []],
        invoice=Invoice.model_validate(row["invoice"]) if row.get("invoice") else None,
        validation=ValidationResult.model_validate(row["validation"]) if row.get("validation") else None,
        policy=PolicyResult.model_validate(row["policy"]) if row.get("policy") else None,
        vp=VPDecision.model_validate(row["vp"]) if row.get("vp") else None,
        payment=PaymentResult.model_validate(row["payment"]) if row.get("payment") else None,
        trace=traces,
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
