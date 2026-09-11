from app.domain.models import InvoiceStatus, Route, Severity
from app.domain.policy import evaluate_policy
from tests.fixtures import FIXTURES


def _codes(policy) -> set[str]:
    return {f.code for f in policy.flags}


def test_1001_auto_pays(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1001"](), catalog)
    assert policy.route == Route.PAY
    assert policy.recommended_status == InvoiceStatus.PAID


def test_1002_stock_and_high_value(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1002"](), catalog)
    assert policy.route == Route.HOLD_WITH_VP
    assert "stock_mismatch" in _codes(policy)
    assert "high_value" in _codes(policy)


def test_1003_fraud_hold(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1003"](), catalog)
    assert policy.recommended_status == InvoiceStatus.HELD
    codes = _codes(policy)
    assert "watchlist_vendor" in codes
    assert "zero_stock_item" in codes
    assert "invalid_date" in codes
    assert "fraud_signals" in codes
    assert "high_value" in codes


def test_1004_auto_pays(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1004"](), catalog)
    assert policy.route == Route.PAY


def test_1004_revised_holds(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1004-R1"](), catalog)
    assert policy.recommended_status == InvoiceStatus.HELD
    assert "revision" in _codes(policy)


def test_1004_duplicate_after_payment(catalog):
    invoice = FIXTURES["INV-1004"]()
    _, policy = evaluate_policy(invoice, catalog, paid_ids={"INV-1004"})
    assert "duplicate_invoice" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_1005_partial_stock(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1005"](), catalog)
    assert "stock_mismatch" in _codes(policy)
    assert policy.route == Route.HOLD_WITH_VP


def test_1006_auto_pays(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1006"](), catalog)
    assert policy.route == Route.PAY


def test_1007_multi_stock(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1007"](), catalog)
    assert "stock_mismatch" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_1008_unknown_items(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1008"](), catalog)
    assert "unknown_sku" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_1009_rejects_integrity(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1009"](), catalog)
    assert policy.route == Route.REJECT
    assert policy.recommended_status == InvoiceStatus.REJECTED
    codes = _codes(policy)
    assert "negative_quantity" in codes
    assert "empty_vendor" in codes
    assert any(f.severity == Severity.REJECT for f in policy.flags)


def test_1010_aggregates_rush_line(catalog):
    invoice = FIXTURES["INV-1010"]()
    assert invoice.aggregated_quantities()["WidgetA"] == 12
    _, policy = evaluate_policy(invoice, catalog)
    assert policy.route == Route.PAY


def test_1011_auto_pays(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1011"](), catalog)
    assert policy.route == Route.PAY


def test_1012_ocr_normalizes_and_pays(catalog):
    invoice = FIXTURES["INV-1012"]()
    assert {i.sku for i in invoice.line_items} == {"WidgetA", "WidgetB", "GadgetX"}
    _, policy = evaluate_policy(invoice, catalog)
    assert policy.route == Route.PAY
    assert "ocr_uncertain" not in _codes(policy)


def test_1013_math_and_stock(catalog):
    validation, policy = evaluate_policy(FIXTURES["INV-1013"](), catalog)
    assert validation.math_delta == 50.0
    codes = _codes(policy)
    assert "math_mismatch" in codes
    assert "stock_mismatch" in codes
    assert policy.route == Route.HOLD_WITH_VP


def test_1014_holds_eur(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1014"](), catalog)
    assert "non_usd" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_1015_auto_pays(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1015"](), catalog)
    assert policy.route == Route.PAY


def test_1016_partial_unknown(catalog):
    _, policy = evaluate_policy(FIXTURES["INV-1016"](), catalog)
    assert "unknown_sku" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_extract_uncertain_holds_unstructured(catalog):
    invoice = FIXTURES["INV-1001"]()
    invoice.extraction_confidence = 0.4
    invoice.source_format = "txt"
    _, policy = evaluate_policy(invoice, catalog)
    assert "extract_uncertain" in _codes(policy)
    assert policy.recommended_status == InvoiceStatus.HELD


def test_extract_uncertain_ignores_structured_json(catalog):
    invoice = FIXTURES["INV-1004"]()
    invoice.extraction_confidence = 0.4
    invoice.source_format = "json"
    _, policy = evaluate_policy(invoice, catalog)
    assert "extract_uncertain" not in _codes(policy)
    assert policy.route == Route.PAY


GOLDEN_STATUS = {
    "INV-1001": InvoiceStatus.PAID,
    "INV-1002": InvoiceStatus.HELD,
    "INV-1003": InvoiceStatus.HELD,
    "INV-1004": InvoiceStatus.PAID,
    "INV-1004-R1": InvoiceStatus.HELD,
    "INV-1005": InvoiceStatus.HELD,
    "INV-1006": InvoiceStatus.PAID,
    "INV-1007": InvoiceStatus.HELD,
    "INV-1008": InvoiceStatus.HELD,
    "INV-1009": InvoiceStatus.REJECTED,
    "INV-1010": InvoiceStatus.PAID,
    "INV-1011": InvoiceStatus.PAID,
    "INV-1012": InvoiceStatus.PAID,
    "INV-1013": InvoiceStatus.HELD,
    "INV-1014": InvoiceStatus.HELD,
    "INV-1015": InvoiceStatus.PAID,
    "INV-1016": InvoiceStatus.HELD,
}


def test_golden_table(catalog):
    for key, expected in GOLDEN_STATUS.items():
        _, policy = evaluate_policy(FIXTURES[key](), catalog)
        assert policy.recommended_status == expected, f"{key}: {policy.summary}"
