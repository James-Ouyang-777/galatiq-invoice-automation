from __future__ import annotations

from pathlib import Path

import pytest

from app.db import init_db, load_catalog
from app.domain.models import InventoryRow


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "inventory.db"
    init_db(path)
    return path


@pytest.fixture()
def catalog(db_path: Path) -> dict[str, InventoryRow]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return load_catalog(conn)
    finally:
        conn.close()
