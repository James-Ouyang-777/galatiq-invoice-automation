from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.config import settings
from app.db import db_session, get_run, init_db, list_runs, metrics
from app.ingestion.detect import collect_invoice_paths
from app.pipeline import override_pay, override_reject, process_invoice

ALLOWED_UPLOAD_SUFFIXES = {".txt", ".json", ".csv", ".xml", ".pdf"}
DEMO_PATHS = [
    "invoice_1001.txt",
    "invoice_1002.txt",
    "invoice_1003.txt",
    "invoice_1004.json",
    "invoice_1004_revised.json",
]

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Acme AP", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(UI_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/api/health")
def health():
    from app.llm import provider_name

    return {"ok": True, "llm": provider_name() or "heuristic"}


@app.get("/api/metrics")
def api_metrics():
    with db_session() as conn:
        return metrics(conn)


@app.get("/api/runs")
def api_runs():
    with db_session() as conn:
        return {"runs": list_runs(conn)}


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    with db_session() as conn:
        row = get_run(conn, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return row


class ProcessBody(BaseModel):
    path: str | None = None


@app.post("/api/process")
def api_process(body: ProcessBody):
    if not body.path:
        raise HTTPException(400, "path required")
    try:
        paths = collect_invoice_paths(body.path, settings.invoices_dir)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    runs = [process_invoice(path).model_dump(mode="json") for path in paths]
    return {"runs": runs}


@app.post("/api/process-all")
def api_process_all():
    paths = collect_invoice_paths(str(settings.invoices_dir), settings.invoices_dir)
    runs = [process_invoice(path).model_dump(mode="json") for path in paths]
    return {"runs": runs}


@app.post("/api/demo")
def api_demo():
    """Two-minute walk: clean pay → stock hold → fraud hold → pay → revision hold."""
    runs = []
    for name in DEMO_PATHS:
        path = settings.invoices_dir / name
        if not path.exists():
            raise HTTPException(404, f"Demo file missing: {name}")
        runs.append(process_invoice(path).model_dump(mode="json"))
    return {"runs": runs}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(400, f"Unsupported type {suffix or '(none)'}. Use txt, json, csv, xml, or pdf.")
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "invoice").name.replace(" ", "_")
    dest = settings.uploads_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    dest.write_bytes(await file.read())
    run = process_invoice(dest)
    return {"runs": [run.model_dump(mode="json")]}


@app.post("/api/runs/{run_id}/pay")
def api_pay(run_id: str):
    try:
        run = override_pay(run_id)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/reject")
def api_reject(run_id: str):
    try:
        run = override_reject(run_id)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/rerun")
def api_rerun(run_id: str):
    with db_session() as conn:
        row = get_run(conn, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    run = process_invoice(row["source_path"])
    return run.model_dump(mode="json")
