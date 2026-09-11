from pathlib import Path

from fastapi.testclient import TestClient

from app.api.server import app
from app.config import settings


def test_health_and_index(monkeypatch, db_path):
    monkeypatch.setattr(settings, "database_path", db_path)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        page = client.get("/")
        assert page.status_code == 200
        assert "Accounts Payable" in page.text


def test_process_and_override(monkeypatch, db_path):
    monkeypatch.setattr(settings, "database_path", db_path)
    with TestClient(app) as client:
        res = client.post("/api/process", json={"path": "data/invoices/invoice_1016.json"})
        assert res.status_code == 200
        run = res.json()["runs"][0]
        assert run["status"] == "held"
        paid = client.post(f"/api/runs/{run['run_id']}/pay")
        assert paid.status_code == 200
        assert paid.json()["status"] == "paid"
        metrics = client.get("/api/metrics").json()
        assert metrics["processed"] >= 1


def test_demo_walk(monkeypatch, db_path):
    monkeypatch.setattr(settings, "database_path", db_path)
    with TestClient(app) as client:
        res = client.post("/api/demo")
        assert res.status_code == 200
        statuses = [run["status"] for run in res.json()["runs"]]
        assert statuses == ["paid", "held", "held", "paid", "held"]
        assert [run["invoice_id"] for run in res.json()["runs"]] == [
            "INV-1001",
            "INV-1002",
            "INV-1003",
            "INV-1004",
            "INV-1004",
        ]


def test_upload_invoice(monkeypatch, db_path, tmp_path):
    monkeypatch.setattr(settings, "database_path", db_path)
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    raw = Path("data/invoices/invoice_1016.json").read_bytes()
    with TestClient(app) as client:
        res = client.post(
            "/api/upload",
            files={"file": ("invoice_1016.json", raw, "application/json")},
        )
        assert res.status_code == 200
        run = res.json()["runs"][0]
        assert run["invoice_id"] == "INV-1016"
        assert run["status"] == "held"


def test_upload_rejects_bad_type(monkeypatch, db_path):
    monkeypatch.setattr(settings, "database_path", db_path)
    with TestClient(app) as client:
        res = client.post(
            "/api/upload",
            files={"file": ("notes.exe", b"nope", "application/octet-stream")},
        )
        assert res.status_code == 400
