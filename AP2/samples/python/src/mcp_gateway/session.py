"""SQLite-backed session store for the MCP gateway.

A "session" binds a (bearer-token-hash, user-email) pair to the in-flight
shopping state — active cart, finalized cart-mandate, chosen payment
source, charge token, latest payment-mandate, pending challenge, last
order id. TTL defaults to 2 h.

Why SQLite-backed: the gateway is restartable independent of Claude /
ChatGPT, and the same session may be resumed from a new TCP connection.
The ``mcp_sessions`` table is created in ``pharmacy_data/schema.sql``
(and is also bootstrapped here defensively for fresh dev DBs).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from pharmacy_data import db as _db


_SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 h


# (column_name, sqlite_type) — declared in dependency-free order so we can
# ALTER TABLE ADD COLUMN them onto an older table that pre-dates a column.
# NOTE: SQLite ALTER TABLE ADD COLUMN cannot add a NOT NULL column without
# a default, so we model the columns here as nullable and rely on the
# INSERT path to provide values. The fresh-DB CREATE below tightens
# `token_hash` and the timestamp columns to NOT NULL.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_id", "TEXT PRIMARY KEY"),
    ("token_hash", "TEXT"),
    ("user_email", "TEXT"),
    ("created_at", "REAL"),
    ("expires_at", "REAL"),
    ("cart_id", "TEXT"),
    ("cart_mandate_json", "TEXT"),
    ("chosen_token", "TEXT"),
    ("chosen_source", "TEXT"),
    ("payment_mandate_id", "TEXT"),
    ("payment_mandate_json", "TEXT"),
    ("pending_challenge_json", "TEXT"),
    ("last_order_id", "TEXT"),
    ("extras_json", "TEXT"),
)


def _ensure_table(conn: sqlite3.Connection) -> None:
    # Fresh-DB path: full CREATE with NOT NULL constraints baked in.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_sessions (
            session_id        TEXT PRIMARY KEY,
            token_hash        TEXT NOT NULL,
            user_email        TEXT,
            created_at        REAL NOT NULL,
            expires_at        REAL NOT NULL,
            cart_id           TEXT,
            cart_mandate_json TEXT,
            chosen_token      TEXT,
            chosen_source     TEXT,
            payment_mandate_id TEXT,
            payment_mandate_json TEXT,
            pending_challenge_json TEXT,
            last_order_id     TEXT,
            extras_json       TEXT
        )
        """
    )

    # Migration path: if an older version of this table is already present
    # (e.g. seeded by `pharmacy_data/schema.sql` before we added some
    # columns), reconcile by ALTER TABLE ADD COLUMN-ing the missing ones.
    # `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table and
    # silently leaves stale schemas in place, which is what was biting us.
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(mcp_sessions)").fetchall()
    }
    for col, decl in _COLUMNS:
        if col in existing:
            continue
        # Strip "PRIMARY KEY" — only valid at table-create time.
        ddl_type = decl.replace("PRIMARY KEY", "").strip() or "TEXT"
        conn.execute(
            f"ALTER TABLE mcp_sessions ADD COLUMN {col} {ddl_type}"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_token_user "
        "ON mcp_sessions(token_hash, user_email)"
    )


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = _db.connect()
    try:
        _ensure_table(c)
        yield c
        c.commit()
    finally:
        c.close()


def _now() -> float:
    return time.time()


def get_or_create(*, token_hash: str | None, user_email: str | None,
                  session_id: str | None = None) -> dict[str, Any]:
    """Find or create a session row.

    Lookup priority:
      1. by ``session_id`` if provided.
      2. by (token_hash, user_email) — newest non-expired.
      3. otherwise create a new row.
    """
    now = _now()
    with _conn() as c:
        # 1. explicit id
        if session_id:
            row = c.execute(
                "SELECT * FROM mcp_sessions WHERE session_id = ? AND expires_at > ?",
                (session_id, now),
            ).fetchone()
            if row:
                return dict(row)

        # 2. token+email
        if token_hash:
            row = c.execute(
                "SELECT * FROM mcp_sessions WHERE token_hash = ? "
                "AND IFNULL(user_email, '') = ? AND expires_at > ? "
                "ORDER BY created_at DESC LIMIT 1",
                (token_hash, user_email or "", now),
            ).fetchone()
            if row:
                return dict(row)

        # 3. fresh
        new_id = f"sess_{uuid.uuid4().hex[:16]}"
        c.execute(
            "INSERT INTO mcp_sessions(session_id, token_hash, user_email, "
            "created_at, expires_at) VALUES(?, ?, ?, ?, ?)",
            (new_id, token_hash or "anon", user_email,
             now, now + _SESSION_TTL_SECONDS),
        )
        row = c.execute(
            "SELECT * FROM mcp_sessions WHERE session_id = ?", (new_id,)
        ).fetchone()
        return dict(row)


def update(session_id: str, **fields) -> None:
    """Patch a session row. Unknown fields are stored under ``extras_json``."""
    if not fields:
        return
    known = {
        "user_email", "cart_id", "cart_mandate_json", "chosen_token",
        "chosen_source", "payment_mandate_id", "payment_mandate_json",
        "pending_challenge_json", "last_order_id",
    }
    known_updates = {k: v for k, v in fields.items() if k in known}
    extras_updates = {k: v for k, v in fields.items() if k not in known}

    with _conn() as c:
        if known_updates:
            cols = ", ".join(f"{k}=?" for k in known_updates)
            c.execute(
                f"UPDATE mcp_sessions SET {cols} WHERE session_id=?",
                (*known_updates.values(), session_id),
            )
        if extras_updates:
            row = c.execute(
                "SELECT extras_json FROM mcp_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            existing = json.loads(row["extras_json"]) if row and row["extras_json"] else {}
            existing.update(extras_updates)
            c.execute(
                "UPDATE mcp_sessions SET extras_json=? WHERE session_id=?",
                (json.dumps(existing), session_id),
            )


def set_cart_mandate(session_id: str, cart_id: str,
                     cart_mandate: dict) -> None:
    update(session_id, cart_id=cart_id,
           cart_mandate_json=json.dumps(cart_mandate))


def set_chosen_payment(session_id: str, *, token: str, source: str) -> None:
    update(session_id, chosen_token=token, chosen_source=source)


def set_payment_mandate(session_id: str, payment_mandate_id: str,
                        payment_mandate: dict) -> None:
    update(session_id, payment_mandate_id=payment_mandate_id,
           payment_mandate_json=json.dumps(payment_mandate))


def set_pending_challenge(session_id: str, challenge: dict) -> None:
    update(session_id, pending_challenge_json=json.dumps(challenge))


def clear_pending_challenge(session_id: str) -> None:
    update(session_id, pending_challenge_json=None)


def set_last_order(session_id: str, order_id: str) -> None:
    update(session_id, last_order_id=order_id)


def load_cart_mandate(session_id: str) -> dict | None:
    s = get_or_create(token_hash=None, user_email=None, session_id=session_id)
    raw = s.get("cart_mandate_json")
    return json.loads(raw) if raw else None


def load_payment_mandate(session_id: str) -> dict | None:
    s = get_or_create(token_hash=None, user_email=None, session_id=session_id)
    raw = s.get("payment_mandate_json")
    return json.loads(raw) if raw else None


def load_pending_challenge(session_id: str) -> dict | None:
    s = get_or_create(token_hash=None, user_email=None, session_id=session_id)
    raw = s.get("pending_challenge_json")
    return json.loads(raw) if raw else None
