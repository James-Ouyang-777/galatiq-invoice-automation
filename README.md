# Acme AP — Invoice Processing Automation

Acme Corp is losing **$2M/year** on a five-day, 30%-error invoice process. This prototype automates the happy path and parks everything else in a clerk exception queue.

Clean invoices **auto-pay**. Stock mismatches, unknown SKUs, fraud signals, FX, math errors, and revisions **hold** for a human. Negative quantities and missing vendors **reject**. High-value invoices (>$10k) get a VP draft + critic pass before anyone pays.

The graph is the supervisor. There is no fifth chatty agent.

## Two-minute demo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional — works without an LLM key

python main.py --rebuild-db
python main.py --invoice_path=data/invoices/invoice1.txt
python main.py --serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Click **Run 2-min demo**, or drop any txt / json / csv / xml / pdf into the left pane.

The brief’s `invoice1.txt` path is accepted; the real file is `invoice_1001.txt`.

Walk this path in the UI (**Run 2-min demo** or the sidebar chips):

1. **INV-1001** — clean $5,000. Auto-pays in seconds, not five days.
2. **INV-1002** — 20× GadgetX against 5 in stock, $15k. Held. VP recommendation is advisory.
3. **INV-1003** — Fraudster LLC, FakeItem, due “yesterday”, wire-urgency language. Held.
4. **INV-1004** then **INV-1004 R1** — original pays; revision holds as a duplicate amendment.

A clerk can **Override & Pay** or **Reject** from the detail pane. Re-runs of the same file are allowed; a second *file* with the same invoice id is not.

## What auto-pays vs what holds

| Outcome | Rule |
|---|---|
| **Auto-pay** | Known SKUs, qty ≤ stock, totals reconcile within $1, USD, not a duplicate, vendor not on the watchlist, amount < $10k |
| **Hold** | Stock mismatch, unknown SKU, zero-stock / FakeItem, watchlist vendor, fraud language, invalid dates, revision / already-paid duplicate, non-USD, math mismatch |
| **Reject** | Negative quantity, empty vendor, unparseable total |
| **VP review** | Amount ≥ $10k. Binding if the invoice is otherwise clean; advisory when already held |

Hidden cases the sample pack is designed to catch: INV-1005/1007 multi-item stock, INV-1008 unknown catalog, INV-1009 integrity reject, INV-1010 rush-line aggregation, INV-1012 OCR (`Widget A` → WidgetA), INV-1013 $50 total error, INV-1014 EUR (no silent FX), INV-1016 partial unknown WidgetC.

## Architecture

```
ingest → extract (+ LLM repair if needed) → inventory validate → policy
   ├─ clean < $10k  → mock payment (idempotent)
   ├─ clean ≥ $10k  → VP draft → critic → pay or reject
   ├─ hold (+ ≥ $10k) → VP advisory → exception queue
   └─ reject → rejected (still overridable in the UI)
```

- **Deterministic first.** JSON / XML / CSV parse without an LLM. TXT / email / PDF use heuristics plus PDF table extract; arithmetic and bill-to checks treat regex as a proposal. An LLM retries on extract issues (max 2). Remaining doubt HOLDs `extract_uncertain` instead of auto-paying.
- **Policy is Python.** Prompts do not invent payment rules.
- **Tools are real.** SQLite inventory lookups, mock bank `mock_payment(vendor, amount)`, audit log.
- **LLM is optional.** No key → heuristic VP + deterministic extract. With a key, structured extraction and the VP critique loop run.

xAI/Grok is preferred (OpenAI-compatible at `https://api.x.ai/v1`). The brief’s `from xai import Grok` is not a real SDK. Provider order: `XAI_API_KEY` → OpenAI → Anthropic → Google.

## How to run

```bash
# one invoice (file or directory)
python main.py --invoice_path=data/invoices/invoice_1002.txt
python main.py --invoice_path=data/invoices/

# dashboard
python main.py --serve --host 127.0.0.1 --port 8000

# wipe and reseed inventory.db
python main.py --rebuild-db
```

```bash
pytest
```

Tests do not need network or API keys. They cover parsers, golden field snapshots for every sample file, SKU/OCR normalization, the golden policy table, the LangGraph path, novel fixtures, and the dashboard API.

## Assumptions we cut

Shipped: every sample format, explicit controls, HITL override, traces, batch inbox, file upload, two-minute demo path, configurable LLM.

Not shipped (on purpose):

- Real bank, real email inbox, cloud deploy
- React / SPA framework
- Silent FX conversion
- Expanding inventory so failing invoices pass (WidgetC, SuperGizmo stay unknown)
- Extra agents for theater

If I had another day: email watcher, vendor master with three-way match, live FX with treasury approval, replay of a run from the audit log.

## Repository

| Path | Role |
|---|---|
| [`main.py`](main.py) | CLI |
| [`app/graph.py`](app/graph.py) | LangGraph workflow |
| [`app/domain/policy.py`](app/domain/policy.py) | Payment controls |
| [`app/ingestion/`](app/ingestion/) | Format detection + parsers |
| [`app/api/server.py`](app/api/server.py) | FastAPI + ops UI |
| [`tests/golden_extracts.py`](tests/golden_extracts.py) | Expected fields for every sample invoice |
| [`instructions/README.md`](instructions/README.md) | Original brief |
