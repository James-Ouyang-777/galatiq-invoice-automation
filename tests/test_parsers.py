from pathlib import Path

from app.config import settings
from app.ingestion.detect import collect_invoice_paths, detect_format, resolve_invoice_path
from app.ingestion.parsers import parse_invoice, read_source


INVOICES = settings.invoices_dir


def test_resolve_brief_alias():
    path = resolve_invoice_path("invoice1.txt", INVOICES)
    assert path.name == "invoice_1001.txt"


def test_json_1004():
    invoice = parse_invoice(INVOICES / "invoice_1004.json")
    assert invoice.invoice_id == "INV-1004"
    assert invoice.vendor == "Precision Parts Ltd."
    assert invoice.total == 1890.0
    assert len(invoice.line_items) == 2


def test_json_1004_revised():
    invoice = parse_invoice(INVOICES / "invoice_1004_revised.json")
    assert invoice.invoice_id == "INV-1004"
    assert invoice.revision == "R1"
    assert len(invoice.line_items) == 3


def test_json_1009_preserves_bad_data():
    invoice = parse_invoice(INVOICES / "invoice_1009.json")
    assert invoice.vendor == ""
    assert invoice.line_items[0].quantity == -5
    assert invoice.total == -250.0


def test_json_1016_unknown_sku():
    invoice = parse_invoice(INVOICES / "invoice_1016.json")
    skus = {i.sku for i in invoice.line_items}
    assert "WidgetC" in skus


def test_xml_1014_eur():
    invoice = parse_invoice(INVOICES / "invoice_1014.xml")
    assert invoice.invoice_id == "INV-1014"
    assert invoice.currency == "EUR"
    assert invoice.total == 4125.0
    assert [i.sku for i in invoice.line_items] == ["WidgetA", "WidgetB"]


def test_vertical_csv_1006():
    invoice = parse_invoice(INVOICES / "invoice_1006.csv")
    assert invoice.invoice_id == "INV-1006"
    assert invoice.vendor == "Acme Industrial Supplies"
    assert [i.sku for i in invoice.line_items] == ["WidgetA", "WidgetB"]
    assert invoice.total == 2750.0


def test_tabular_csv_1007():
    invoice = parse_invoice(INVOICES / "invoice_1007.csv")
    assert invoice.invoice_id == "INV-1007"
    assert invoice.total == 15525.0
    assert invoice.tax == 885.0
    assert len(invoice.line_items) == 3


def test_tabular_csv_1015():
    invoice = parse_invoice(INVOICES / "invoice_1015.csv")
    assert invoice.invoice_id == "INV-1015"
    assert invoice.total == 6500.0
    assert len(invoice.line_items) == 3


def test_txt_1001():
    invoice = parse_invoice(INVOICES / "invoice_1001.txt")
    assert invoice.invoice_id == "INV-1001"
    assert invoice.vendor == "Widgets Inc."
    assert invoice.total == 5000.0
    assert [i.quantity for i in invoice.line_items] == [10, 5]


def test_txt_1002_messy():
    invoice = parse_invoice(INVOICES / "invoice_1002.txt")
    assert invoice.invoice_id == "INV-1002"
    assert invoice.vendor == "Gadgets Co."
    assert invoice.line_items[0].sku == "GadgetX"
    assert invoice.line_items[0].quantity == 20
    assert invoice.total == 15000.0


def test_txt_1003_fraud():
    invoice = parse_invoice(INVOICES / "invoice_1003.txt")
    assert invoice.vendor == "Fraudster LLC"
    assert invoice.due_date == "yesterday"
    assert invoice.line_items[0].sku == "FakeItem"


def test_email_1008():
    text, fmt = read_source(INVOICES / "invoice_1008.txt")
    assert detect_format(INVOICES / "invoice_1008.txt", text) == "email"
    invoice = parse_invoice(INVOICES / "invoice_1008.txt", text, fmt)
    assert invoice.invoice_id == "INV-1008"
    skus = {i.sku for i in invoice.line_items}
    assert "SuperGizmo" in skus
    assert "MegaSprocket" in skus
    assert invoice.total == 9900.0


def test_txt_1010_rush_aggregation():
    invoice = parse_invoice(INVOICES / "invoice_1010.txt")
    assert invoice.invoice_id == "INV-1010"
    assert invoice.aggregated_quantities()["WidgetA"] == 12
    assert invoice.shipping == 150.0
    assert invoice.total == 7185.0


def test_txt_1012_ocr():
    invoice = parse_invoice(INVOICES / "invoice_1012.txt")
    assert invoice.invoice_id == "INV-1012"
    assert invoice.ocr_artifacts is True
    skus = [i.sku for i in invoice.line_items]
    assert skus == ["WidgetA", "WidgetB", "GadgetX"]
    assert invoice.total == 9975.0


def test_pdf_1011():
    invoice = parse_invoice(INVOICES / "invoice_1011.pdf")
    assert invoice.invoice_id == "INV-1011"
    assert invoice.vendor.startswith("Summit")
    assert invoice.total == 3000.0
    assert [i.sku for i in invoice.line_items] == ["WidgetA", "WidgetB"]
    assert invoice.ocr_artifacts is False


def test_collect_directory():
    paths = collect_invoice_paths(str(INVOICES), INVOICES)
    assert len(paths) >= 16


def test_golden_extracts():
    from tests.golden_extracts import GOLDEN

    invoices = settings.invoices_dir
    for name, expected in GOLDEN.items():
        path = invoices / name
        if not path.exists():
            continue
        invoice = parse_invoice(path)
        skus = [(item.sku, item.quantity) for item in invoice.line_items]
        assert invoice.invoice_id == expected["invoice_id"], name
        assert invoice.vendor == expected["vendor"], name
        assert skus == expected["skus"], name
        assert invoice.total == expected["total"], name
        assert invoice.currency == expected["currency"], name
        assert invoice.revision == expected["revision"], name


def test_novel_bill_to_does_not_become_vendor():
    invoice = parse_invoice(Path("tests/data/invoice_acme_billto.txt"))
    assert invoice.vendor == "Northern Widgets LLC"
    assert invoice.invoice_id == "INV-9001"
    assert invoice.total == 500.0
    assert [i.sku for i in invoice.line_items] == ["WidgetA"]


def test_novel_alt_key_json():
    invoice = parse_invoice(Path("tests/data/invoice_alt_keys.json"))
    assert invoice.invoice_id == "INV-9002"
    assert invoice.vendor == "Alt Key Supply"
    assert invoice.total == 250.0
    assert invoice.line_items[0].sku == "WidgetA"
    assert invoice.line_items[0].quantity == 1


def test_extraction_issues_on_math_error():
    from app.ingestion.parsers import extraction_issues

    invoice = parse_invoice(INVOICES / "invoice_1013.json")
    issues = extraction_issues(invoice)
    assert any("Claimed total" in i for i in issues)


def test_extraction_issues_bill_to():
    from app.domain.models import Invoice, LineItem
    from app.ingestion.parsers import extraction_issues

    invoice = Invoice(
        invoice_id="INV-9",
        vendor="Acme Corp",
        line_items=[LineItem(description="WidgetA", sku="WidgetA", quantity=1, unit_price=250)],
        total=250.0,
        source_format="txt",
    )
    issues = extraction_issues(invoice)
    assert any("bill-to" in i.lower() for i in issues)
