from __future__ import annotations

from app.domain.models import Invoice, LineItem
from app.domain.sku import normalize_invoice_id, normalize_sku


def invoice_1001() -> Invoice:
    return Invoice(
        invoice_id="INV-1001",
        vendor="Widgets Inc.",
        invoice_date="2026-01-15",
        due_date="2026-02-01",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=10, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=5, unit_price=500.0),
        ],
        subtotal=5000.0,
        tax=0.0,
        total=5000.0,
        currency="USD",
        payment_terms="Net 15",
        source_format="txt",
    )


def invoice_1002() -> Invoice:
    return Invoice(
        invoice_id=normalize_invoice_id("1002"),
        vendor="Gadgets Co.",
        invoice_date="2026-01-30",
        due_date="2026-01-30",
        line_items=[
            LineItem(description="GadgetX", sku="GadgetX", quantity=20, unit_price=750.0),
        ],
        total=15000.0,
        currency="USD",
        payment_terms="Net 30",
        source_format="txt",
    )


def invoice_1003() -> Invoice:
    return Invoice(
        invoice_id="INV-1003",
        vendor="Fraudster LLC",
        invoice_date="2026-01-20",
        due_date="yesterday",
        line_items=[
            LineItem(description="FakeItem", sku="FakeItem", quantity=100, unit_price=1000.0),
        ],
        total=100000.0,
        currency="USD",
        payment_terms="Immediate",
        notes="URGENT - Pay immediately to avoid penalties!!! Wire transfer preferred.",
        source_format="txt",
    )


def invoice_1004() -> Invoice:
    return Invoice(
        invoice_id="INV-1004",
        vendor="Precision Parts Ltd.",
        invoice_date="2026-01-22",
        due_date="2026-02-22",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=3, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=2, unit_price=500.0),
        ],
        subtotal=1750.0,
        tax=140.0,
        total=1890.0,
        currency="USD",
        source_format="json",
    )


def invoice_1004_revised() -> Invoice:
    inv = invoice_1004()
    inv.revision = "R1"
    inv.line_items.append(
        LineItem(description="GadgetX", sku="GadgetX", quantity=5, unit_price=750.0)
    )
    inv.subtotal = 5500.0
    inv.tax = 440.0
    inv.total = 5940.0
    inv.notes = "Revised invoice - additional items added per PO amendment"
    return inv


def invoice_1005() -> Invoice:
    return Invoice(
        invoice_id="INV-1005",
        vendor="Global Supply Chain Partners",
        invoice_date="2026-01-18",
        due_date="2026-03-18",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=14, unit_price=250.0),
            LineItem(description="GadgetX", sku="GadgetX", quantity=8, unit_price=750.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=10, unit_price=500.0),
        ],
        subtotal=14500.0,
        tax=725.0,
        total=15225.0,
        currency="USD",
        source_format="json",
    )


def invoice_1006() -> Invoice:
    return Invoice(
        invoice_id="INV-1006",
        vendor="Acme Industrial Supplies",
        invoice_date="2026-01-25",
        due_date="2026-02-10",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=5, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=2750.0,
        tax=0.0,
        total=2750.0,
        currency="USD",
        source_format="csv",
    )


def invoice_1007() -> Invoice:
    return Invoice(
        invoice_id="INV-1007",
        vendor="MegaWidgets Corp",
        invoice_date="01/28/2026",
        due_date="02/28/2026",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=20, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=15, unit_price=500.0),
            LineItem(description="GadgetX", sku="GadgetX", quantity=3, unit_price=750.0),
        ],
        subtotal=14750.0,
        tax=885.0,
        total=15525.0,
        currency="USD",
        source_format="csv",
    )


def invoice_1008() -> Invoice:
    return Invoice(
        invoice_id="INV-1008",
        vendor="NoProd Industries",
        invoice_date="2026-01-10",
        due_date="2026-01-20",
        line_items=[
            LineItem(
                description="SuperGizmo",
                sku=normalize_sku("SuperGizmo"),
                quantity=12,
                unit_price=400.0,
            ),
            LineItem(
                description="MegaSprocket",
                sku=normalize_sku("MegaSprocket"),
                quantity=6,
                unit_price=850.0,
            ),
        ],
        total=9900.0,
        currency="USD",
        source_format="email",
    )


def invoice_1009() -> Invoice:
    return Invoice(
        invoice_id="INV-1009",
        vendor="",
        invoice_date="2026-01-15",
        due_date=None,
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=-5, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=2, unit_price=500.0),
        ],
        subtotal=1000.0,
        tax=0.0,
        total=-250.0,
        currency="USD",
        source_format="json",
    )


def invoice_1010() -> Invoice:
    return Invoice(
        invoice_id="INV-1010",
        vendor="Consolidated Materials Group",
        invoice_date="January 27, 2026",
        due_date="February 26, 2026",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=8, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=4, unit_price=500.0),
            LineItem(description="GadgetX", sku="GadgetX", quantity=2, unit_price=750.0),
            LineItem(
                description="WidgetA (rush order)",
                sku=normalize_sku("WidgetA (rush order)"),
                quantity=4,
                unit_price=300.0,
            ),
        ],
        subtotal=6700.0,
        tax=335.0,
        shipping=150.0,
        total=7185.0,
        currency="USD",
        source_format="txt",
    )


def invoice_1011() -> Invoice:
    return Invoice(
        invoice_id="INV-1011",
        vendor="Summit Manufacturing Co.",
        invoice_date="2026-01-20",
        due_date="2026-02-20",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=6, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=3000.0,
        tax=0.0,
        total=3000.0,
        currency="USD",
        source_format="txt",
    )


def invoice_1012() -> Invoice:
    return Invoice(
        invoice_id=normalize_invoice_id("INV 1012"),
        vendor="QuickShip Distributers",
        invoice_date="26-Jan-2026",
        due_date="25-Feb-2026",
        line_items=[
            LineItem(
                description="Widget A",
                sku=normalize_sku("Widget A"),
                quantity=12,
                unit_price=250.0,
            ),
            LineItem(description="WidgetB", sku="WidgetB", quantity=7, unit_price=500.0),
            LineItem(
                description="Gadget X",
                sku=normalize_sku("Gadget X"),
                quantity=4,
                unit_price=750.0,
            ),
        ],
        subtotal=9500.0,
        tax=475.0,
        total=9975.0,
        currency="USD",
        ocr_artifacts=True,
        extraction_confidence=0.9,
        source_format="txt",
    )


def invoice_1013() -> Invoice:
    return Invoice(
        invoice_id="INV-1013",
        vendor="Atlas Industrial Supply",
        invoice_date="2026-01-24",
        due_date="2026-03-24",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=15, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=10, unit_price=500.0),
            LineItem(description="GadgetX", sku="GadgetX", quantity=5, unit_price=750.0),
            LineItem(description="WidgetA", sku="WidgetA", quantity=5, unit_price=240.0, note="Volume discount"),
            LineItem(description="WidgetB", sku="WidgetB", quantity=8, unit_price=480.0, note="Volume discount"),
            LineItem(description="GadgetX", sku="GadgetX", quantity=3, unit_price=750.0, note="Expedited"),
            LineItem(description="WidgetA", sku="WidgetA", quantity=2, unit_price=250.0, note="Replacement"),
            LineItem(description="GadgetX", sku="GadgetX", quantity=1, unit_price=750.0, note="Sample"),
        ],
        subtotal=21040.0,
        tax=1472.80,
        total=22562.80,
        currency="USD",
        source_format="json",
    )


def invoice_1014() -> Invoice:
    return Invoice(
        invoice_id="INV-1014",
        vendor="TechParts International",
        invoice_date="2026-01-26",
        due_date="2026-02-26",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=4, unit_price=225.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=6, unit_price=475.0),
        ],
        subtotal=3750.0,
        tax=375.0,
        total=4125.0,
        currency="EUR",
        source_format="xml",
    )


def invoice_1015() -> Invoice:
    return Invoice(
        invoice_id="INV-1015",
        vendor="Reliable Components Inc.",
        invoice_date="2026-01-29",
        due_date="2026-02-28",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=10, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=5, unit_price=500.0),
            LineItem(description="GadgetX", sku="GadgetX", quantity=2, unit_price=750.0),
        ],
        subtotal=6500.0,
        tax=0.0,
        total=6500.0,
        currency="USD",
        source_format="csv",
    )


def invoice_1016() -> Invoice:
    return Invoice(
        invoice_id="INV-1016",
        vendor="Widgets Inc.",
        invoice_date="2026-01-27",
        due_date="2026-02-27",
        line_items=[
            LineItem(description="WidgetA", sku="WidgetA", quantity=4, unit_price=250.0),
            LineItem(description="WidgetB", sku="WidgetB", quantity=2, unit_price=500.0),
            LineItem(
                description="WidgetC",
                sku=normalize_sku("WidgetC"),
                quantity=3,
                unit_price=350.0,
            ),
        ],
        subtotal=3050.0,
        tax=183.0,
        total=3233.0,
        currency="USD",
        source_format="json",
    )


FIXTURES = {
    "INV-1001": invoice_1001,
    "INV-1002": invoice_1002,
    "INV-1003": invoice_1003,
    "INV-1004": invoice_1004,
    "INV-1004-R1": invoice_1004_revised,
    "INV-1005": invoice_1005,
    "INV-1006": invoice_1006,
    "INV-1007": invoice_1007,
    "INV-1008": invoice_1008,
    "INV-1009": invoice_1009,
    "INV-1010": invoice_1010,
    "INV-1011": invoice_1011,
    "INV-1012": invoice_1012,
    "INV-1013": invoice_1013,
    "INV-1014": invoice_1014,
    "INV-1015": invoice_1015,
    "INV-1016": invoice_1016,
}
