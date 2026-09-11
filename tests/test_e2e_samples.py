from pathlib import Path

from app.domain.models import InvoiceStatus
from app.pipeline import process_invoice


EXPECTED = {
    "invoice_1001.txt": InvoiceStatus.PAID,
    "invoice_1002.txt": InvoiceStatus.HELD,
    "invoice_1003.txt": InvoiceStatus.HELD,
    "invoice_1004.json": InvoiceStatus.PAID,
    "invoice_1004_revised.json": InvoiceStatus.HELD,
    "invoice_1005.json": InvoiceStatus.HELD,
    "invoice_1006.csv": InvoiceStatus.PAID,
    "invoice_1007.csv": InvoiceStatus.HELD,
    "invoice_1008.txt": InvoiceStatus.HELD,
    "invoice_1009.json": InvoiceStatus.REJECTED,
    "invoice_1010.txt": InvoiceStatus.PAID,
    "invoice_1011.pdf": InvoiceStatus.PAID,
    "invoice_1012.txt": InvoiceStatus.PAID,
    "invoice_1012.pdf": InvoiceStatus.PAID,
    "invoice_1013.json": InvoiceStatus.HELD,
    "invoice_1013.pdf": InvoiceStatus.HELD,
    "invoice_1014.xml": InvoiceStatus.HELD,
    "invoice_1015.csv": InvoiceStatus.PAID,
    "invoice_1016.json": InvoiceStatus.HELD,
}


NOVEL = {
    Path("tests/data/invoice_acme_billto.txt"): InvoiceStatus.PAID,
    Path("tests/data/invoice_alt_keys.json"): InvoiceStatus.PAID,
}


def test_each_sample_in_isolation(tmp_path: Path):
    from app.db import init_db

    invoices = Path("data/invoices")
    for name, expected in EXPECTED.items():
        path = invoices / name
        if not path.exists():
            continue
        db = tmp_path / name.replace(".", "_") / "inventory.db"
        db.parent.mkdir()
        init_db(db)
        run = process_invoice(path, db_path=db)
        assert run.status == expected, f"{name}: {run.status} ({run.policy.summary if run.policy else run.error})"


def test_novel_inputs_do_not_auto_pay_acme_or_drop_fields(db_path: Path):
    for path, expected in NOVEL.items():
        run = process_invoice(path, db_path=db_path)
        assert run.invoice is not None
        assert run.invoice.vendor != "Acme Corp"
        assert run.status == expected, f"{path}: {run.status} ({run.policy.summary if run.policy else run.error})"
