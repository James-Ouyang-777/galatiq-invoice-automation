from pathlib import Path

from app.db import db_session, paid_invoice_ids
from app.domain.models import InvoiceStatus
from app.pipeline import override_pay, process_invoice


def test_graph_pays_clean_json(db_path: Path):
    run = process_invoice(Path("data/invoices/invoice_1004.json"), db_path=db_path)
    assert run.status == InvoiceStatus.PAID
    assert run.invoice and run.invoice.invoice_id == "INV-1004"
    assert run.payment and run.payment.status == "success"
    with db_session(db_path) as conn:
        assert "INV-1004" in paid_invoice_ids(conn)


def test_graph_rejects_1009(db_path: Path):
    run = process_invoice(Path("data/invoices/invoice_1009.json"), db_path=db_path)
    assert run.status == InvoiceStatus.REJECTED
    codes = {f.code for f in run.flags}
    assert "negative_quantity" in codes
    assert "empty_vendor" in codes


def test_graph_holds_unknown_and_fx(db_path: Path):
    unknown = process_invoice(Path("data/invoices/invoice_1016.json"), db_path=db_path)
    assert unknown.status == InvoiceStatus.HELD
    assert any(f.code == "unknown_sku" for f in unknown.flags)

    fx = process_invoice(Path("data/invoices/invoice_1014.xml"), db_path=db_path)
    assert fx.status == InvoiceStatus.HELD
    assert any(f.code == "non_usd" for f in fx.flags)


def test_revision_after_original(db_path: Path):
    first = process_invoice(Path("data/invoices/invoice_1004.json"), db_path=db_path)
    assert first.status == InvoiceStatus.PAID
    revised = process_invoice(Path("data/invoices/invoice_1004_revised.json"), db_path=db_path)
    assert revised.status == InvoiceStatus.HELD
    codes = {f.code for f in revised.flags}
    assert "revision" in codes
    assert "duplicate_invoice" in codes


def test_override_pay(db_path: Path):
    held = process_invoice(Path("data/invoices/invoice_1016.json"), db_path=db_path)
    assert held.status == InvoiceStatus.HELD
    paid = override_pay(held.run_id, db_path=db_path)
    assert paid.status == InvoiceStatus.PAID
    assert paid.payment is not None
