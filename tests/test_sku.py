from app.domain.sku import normalize_invoice_id, normalize_sku, ocr_fix_text, parse_money


def test_sku_spacing_and_notes():
    assert normalize_sku("Widget A") == "WidgetA"
    assert normalize_sku("Gadget X") == "GadgetX"
    assert normalize_sku("WidgetA (rush order)") == "WidgetA"
    assert normalize_sku("widget-b") == "WidgetB"


def test_unknown_skus_are_not_invented():
    assert normalize_sku("SuperGizmo") == "SuperGizmo"
    assert normalize_sku("WidgetC") == "WidgetC"
    assert normalize_sku("MegaSprocket") == "MegaSprocket"


def test_invoice_id_normalization():
    assert normalize_invoice_id("1002") == "INV-1002"
    assert normalize_invoice_id("INV 1012") == "INV-1012"
    assert normalize_invoice_id("INV-1001") == "INV-1001"


def test_ocr_money_and_year():
    fixed = ocr_fix_text("DATE: 26-Jan-2O26  TOTAL: $3,500.O0")
    assert "2O26" not in fixed
    assert "2026" in fixed
    assert parse_money("$3,500.O0") == 3500.0
    assert parse_money("15,000.00") == 15000.0
