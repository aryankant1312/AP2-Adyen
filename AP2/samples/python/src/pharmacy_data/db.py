"""SQLite connection helper + schema bootstrap."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[3]   # .../AP2
_DEFAULT_DB = _REPO_ROOT / "data" / "pharmacy.sqlite"

DB_PATH = Path(os.environ.get("PHARMACY_DB", str(_DEFAULT_DB)))
SCHEMA_PATH = _HERE / "schema.sql"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql idempotently. Safe to call repeatedly."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with row_factory + foreign keys + schema."""
    target = Path(db_path) if db_path else DB_PATH
    _ensure_parent(target)
    conn = sqlite3.connect(str(target), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context-managed transaction (BEGIN/COMMIT/ROLLBACK)."""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
