#!/usr/bin/env python3
"""CLI for Acme AP invoice processing.

Examples:
  python main.py --invoice_path=data/invoices/invoice1.txt
  python main.py --invoice_path=data/invoices/
  python main.py --serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import settings
from app.db import init_db
from app.ingestion.detect import collect_invoice_paths
from app.logging import configure_logging, get_logger
from app.pipeline import process_invoice

log = get_logger("acme.ap.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acme AP — invoice processing automation")
    parser.add_argument(
        "--invoice_path",
        help="Invoice file or directory. The brief's invoice1.txt alias maps to invoice_1001.txt.",
    )
    parser.add_argument("--serve", action="store_true", help="Start the AP ops dashboard")
    parser.add_argument("--rebuild-db", action="store_true", help="Wipe and reseed inventory.db")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    return parser


def print_run(run) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"{run.invoice_id or run.source_path} → {run.status.value}")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("run_id", run.run_id)
        table.add_row("vendor", run.vendor or "")
        table.add_row("amount", f"{run.amount:,.2f} {run.currency}" if run.amount is not None else "")
        table.add_row("status", run.status.value)
        table.add_row("summary", run.policy.summary if run.policy else run.error or "")
        flags = ", ".join(f.code for f in run.flags) or "—"
        table.add_row("flags", flags)
        console.print(table)
    except Exception:
        print(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "invoice_id": run.invoice_id,
                    "status": run.status.value,
                    "vendor": run.vendor,
                    "amount": run.amount,
                    "flags": [f.code for f in run.flags],
                    "summary": run.policy.summary if run.policy else run.error,
                }
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging()

    if args.rebuild_db:
        init_db(rebuild=True)
        print(f"Reseeded {settings.database_path}")
        if not args.serve and not args.invoice_path:
            return 0

    if args.serve:
        init_db()
        import uvicorn

        uvicorn.run("app.api.server:app", host=args.host, port=args.port, reload=False)
        return 0

    if not args.invoice_path:
        parser.print_help()
        print("\nProvide --invoice_path and/or --serve.", file=sys.stderr)
        return 2

    init_db()
    paths = collect_invoice_paths(args.invoice_path, settings.invoices_dir)
    failures = 0
    for path in paths:
        run = process_invoice(path)
        print_run(run)
        if run.status.value == "failed":
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
