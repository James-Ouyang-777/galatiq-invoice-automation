from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings
from app.domain.models import Flag, InventoryRow, InvoiceRun, utc_now


SEED_INVENTORY = [
    ("WidgetA", 15, 250.0),
    ("WidgetB", 10, 500.0),
    ("GadgetX", 5, 750.0),
    ("FakeItem", 0, None),
]

SEED_VENDORS = [
    ("Fraudster LLC", "watchlist"),
    ("Widgets Inc.", "normal"),
    ("Gadgets Co.", "normal"),
    ("Precision Parts Ltd.", "normal"),
    ("Global Supply Chain Partners", "normal"),
    ("Acme Industrial Supplies", "normal"),
    ("MegaWidgets Corp", "normal"),
    ("NoProd Industries", "normal"),
    ("Consolidated Materials Group", "normal"),
    ("Summit Manufacturing Co.", "normal"),
    ("QuickShip Distributers", "normal"),
    ("Atlas Industrial Supply", "normal"),
    ("TechParts International", "normal"),
    ("Reliable Components Inc.", "normal"),
]


SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    item TEXT PRIMARY KEY,
    stock INTEGER NOT NULL,
    unit_price_usd REAL
);

CREATE TABLE IF NOT EXISTS vendors (
    name TEXT PRIMARY KEY,
    risk TEXT NOT NULL DEFAULT 'normal'
);

CREATE TABLE IF NOT EXISTS invoice_runs (
    run_id TEXT PRIMARY KEY,
    invoice_id TEXT,
    source_path TEXT NOT NULL,
    status TEXT NOT NULL,
    vendor TEXT,
    amount REAL,
    currency TEXT,
    flags_json TEXT NOT NULL DEFAULT '[]',
    invoice_json TEXT,
    validation_json TEXT,
    policy_json TEXT,
    vp_json TEXT,
    payment_json TEXT,
    trace_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    vendor TEXT,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    invoice_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None, *, rebuild: bool = False) -> Path:
    db_path = path or settings.database_path
    if rebuild and db_path.exists():
        db_path.unlink()
    with db_session(db_path) as conn:
        conn.executescript(SCHEMA)
        count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO inventory (item, stock, unit_price_usd) VALUES (?, ?, ?)",
                SEED_INVENTORY,
            )
            conn.executemany(
                "INSERT INTO vendors (name, risk) VALUES (?, ?)",
                SEED_VENDORS,
            )
    return db_path


def load_catalog(conn: sqlite3.Connection) -> dict[str, InventoryRow]:
    rows = conn.execute("SELECT item, stock, unit_price_usd FROM inventory").fetchall()
    return {
        row["item"]: InventoryRow(
            item=row["item"],
            stock=row["stock"],
            unit_price_usd=row["unit_price_usd"],
        )
        for row in rows
    }


def paid_invoice_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT DISTINCT invoice_id FROM payments").fetchall()
    return {row["invoice_id"] for row in rows if row["invoice_id"]}


def prior_sources_for(
    conn: sqlite3.Connection, invoice_id: str, current_path: str
) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT source_path FROM invoice_runs
        WHERE invoice_id = ? AND source_path != ?
        """,
        (invoice_id, current_path),
    ).fetchall()
    return [row["source_path"] for row in rows]


def save_run(conn: sqlite3.Connection, run: InvoiceRun) -> None:
    payload = (
        run.run_id,
        run.invoice_id,
        run.source_path,
        run.status.value,
        run.vendor,
        run.amount,
        run.currency,
        json.dumps([f.model_dump(mode="json") for f in run.flags]),
        run.invoice.model_dump_json() if run.invoice else None,
        run.validation.model_dump_json() if run.validation else None,
        run.policy.model_dump_json() if run.policy else None,
        run.vp.model_dump_json() if run.vp else None,
        run.payment.model_dump_json() if run.payment else None,
        json.dumps([t.model_dump(mode="json") for t in run.trace]),
        run.error,
        run.created_at,
        run.updated_at,
    )
    conn.execute(
        """
        INSERT INTO invoice_runs (
            run_id, invoice_id, source_path, status, vendor, amount, currency,
            flags_json, invoice_json, validation_json, policy_json, vp_json,
            payment_json, trace_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            invoice_id=excluded.invoice_id,
            source_path=excluded.source_path,
            status=excluded.status,
            vendor=excluded.vendor,
            amount=excluded.amount,
            currency=excluded.currency,
            flags_json=excluded.flags_json,
            invoice_json=excluded.invoice_json,
            validation_json=excluded.validation_json,
            policy_json=excluded.policy_json,
            vp_json=excluded.vp_json,
            payment_json=excluded.payment_json,
            trace_json=excluded.trace_json,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        payload,
    )


def record_payment(
    conn: sqlite3.Connection,
    payment_id: str,
    invoice_id: str,
    vendor: str,
    amount: float,
) -> None:
    conn.execute(
        "INSERT INTO payments (payment_id, invoice_id, vendor, amount, created_at) VALUES (?, ?, ?, ?, ?)",
        (payment_id, invoice_id, vendor, amount, utc_now()),
    )


def audit(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    run_id: str | None = None,
    invoice_id: str | None = None,
    payload: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_events (run_id, invoice_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, invoice_id, event_type, json.dumps(payload or {}), utc_now()),
    )


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT run_id, invoice_id, source_path, status, vendor, amount, currency,
               flags_json, created_at, updated_at, error
        FROM invoice_runs
        ORDER BY created_at DESC
        """
    ).fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "run_id": row["run_id"],
                "invoice_id": row["invoice_id"],
                "source_path": row["source_path"],
                "status": row["status"],
                "vendor": row["vendor"],
                "amount": row["amount"],
                "currency": row["currency"],
                "flags": json.loads(row["flags_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "error": row["error"],
            }
        )
    return results


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM invoice_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "invoice_id": row["invoice_id"],
        "source_path": row["source_path"],
        "status": row["status"],
        "vendor": row["vendor"],
        "amount": row["amount"],
        "currency": row["currency"],
        "flags": json.loads(row["flags_json"] or "[]"),
        "invoice": json.loads(row["invoice_json"]) if row["invoice_json"] else None,
        "validation": json.loads(row["validation_json"]) if row["validation_json"] else None,
        "policy": json.loads(row["policy_json"]) if row["policy_json"] else None,
        "vp": json.loads(row["vp_json"]) if row["vp_json"] else None,
        "payment": json.loads(row["payment_json"]) if row["payment_json"] else None,
        "trace": json.loads(row["trace_json"] or "[]"),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def metrics(conn: sqlite3.Connection) -> dict:
    rows = list_runs(conn)
    total = len(rows)
    by_status: dict[str, int] = {}
    paid_amount = 0.0
    held_amount = 0.0
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        amt = row["amount"] or 0.0
        if row["status"] == "paid":
            paid_amount += amt
        elif row["status"] == "held":
            held_amount += amt
    auto_pay_rate = (by_status.get("paid", 0) / total) if total else 0.0
    return {
        "processed": total,
        "by_status": by_status,
        "auto_pay_rate": auto_pay_rate,
        "paid_amount": paid_amount,
        "held_amount": held_amount,
    }


def flags_from_run(run: InvoiceRun) -> list[Flag]:
    return run.flags
