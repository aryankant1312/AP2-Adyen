"""Typed read helpers built on top of ``db.connect()``.

Centralises the SQL so the agents never construct queries directly.
Every function accepts an optional ``conn`` for test injection; when
omitted, a fresh connection is opened (cheap; SQLite shared file).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from . import db as _db


def _conn(conn: sqlite3.Connection | None) -> sqlite3.Connection:
    return conn or _db.connect()


def _resolve_store(loc: str, conn: sqlite3.Connection) -> str:
    """Resolve a partial store name to the canonical DB value.

    Tries exact match first, then case-insensitive LIKE so callers can
    pass "London" and get back "London - Oxford St".
    """
    r = conn.execute(
        "SELECT store_location FROM inventory WHERE store_location = ? LIMIT 1",
        (loc,),
    ).fetchone()
    if r:
        return r[0]
    r = conn.execute(
        "SELECT store_location FROM inventory "
        "WHERE LOWER(store_location) LIKE LOWER(?) LIMIT 1",
        (f"%{loc}%",),
    ).fetchone()
    return r[0] if r else loc


# ---------------------------- Catalog --------------------------------

# Words that contribute no signal in shopping queries. The model often
# pads its query with these ("medicine for skin allergy"), and matching
# a single LIKE against the whole string returned zero rows.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "do",
    "for", "from", "have", "i", "in", "is", "it", "me", "my", "of",
    "on", "or", "that", "the", "this", "to", "with", "you", "your",
    # Domain-noise words that match nothing but "medicine" everywhere.
    "med", "meds", "medicine", "medicines", "medication", "medications",
    "drug", "drugs", "pill", "pills", "tablet", "tablets",
    "treatment", "treatments", "remedy", "remedies", "relief",
    "buy", "want", "need", "looking", "please", "give", "show",
    "good", "best", "some", "something", "things", "stuff",
})

# Light stemming so "allergy"/"allergies", "cream"/"creams" both hit.
def _expand_token(tok: str) -> list[str]:
    out = {tok}
    if tok.endswith("ies") and len(tok) > 4:
        out.add(tok[:-3] + "y")
    if tok.endswith("es") and len(tok) > 3:
        out.add(tok[:-2])
    if tok.endswith("s") and len(tok) > 3:
        out.add(tok[:-1])
    return sorted(out)


def _tokenize_query(query: str) -> list[str]:
    """Split a free-text query into useful search tokens.

    Lowercase, drop punctuation, drop stopwords, drop tokens shorter
    than 3 chars (single letters / typos), de-dupe while preserving
    order. Stem trivially via :func:`_expand_token`.
    """
    cleaned = "".join(ch.lower() if (ch.isalnum() or ch == "-") else " "
                      for ch in query)
    seen: set[str] = set()
    out: list[str] = []
    for raw in cleaned.split():
        if len(raw) < 3 or raw in _STOPWORDS:
            continue
        for variant in _expand_token(raw):
            if variant in seen:
                continue
            seen.add(variant)
            out.append(variant)
    return out


def search_products(query: str, store_location: str | None = None,
                    limit: int = 5, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Keyword search over title/description/category/brand.

    The query is tokenized: any product matching at least one
    meaningful token across title/description/category/brand is
    returned. Ranking favours (a) more tokens matched, then (b) stock
    at the requested store, then (c) raw stock quantity. Falls back to
    a single LIKE against the whole query if tokenization yields
    nothing useful (e.g. searches like a brand sku ``"P007"``).
    """
    c = _conn(conn)
    tokens = _tokenize_query(query)

    if not tokens:
        # Single-token / SKU-like query — keep the old behaviour.
        tokens = [query.lower().strip()]

    # Build OR predicate per token across the four searchable fields.
    # ``score`` counts how many tokens hit at least one field.
    where_parts: list[str] = []
    score_parts: list[str] = []
    params: list[str] = []
    for tok in tokens:
        like = f"%{tok}%"
        per_token = ("(LOWER(p.title) LIKE ? OR LOWER(p.description) LIKE ? "
                     "OR LOWER(p.category) LIKE ? OR LOWER(p.brand) LIKE ?)")
        where_parts.append(per_token)
        score_parts.append("(CASE WHEN " + per_token + " THEN 1 ELSE 0 END)")
        params.extend([like, like, like, like])

    where_sql = " OR ".join(where_parts)
    # Each per-token CASE expects four params, so we duplicate the
    # token-params for the score-side as well.
    score_params = [p for tok in tokens
                    for p in (f"%{tok}%",) * 4]
    score_sql = " + ".join(score_parts) if score_parts else "0"

    if store_location:
        store_location = _resolve_store(store_location, c)
        sql = f"""
            SELECT p.product_ref, p.title, p.brand, p.category, p.description,
                   p.policy, p.ingredients, p.base_price_gbp,
                   IFNULL(i.local_price_gbp, p.base_price_gbp) AS price_gbp,
                   IFNULL(i.qty_in_stock, 0)               AS qty_in_stock,
                   IFNULL(i.shelf_location, '')            AS shelf_location,
                   ({score_sql})                           AS match_score
              FROM products p
              JOIN stock_map sm ON sm.product_ref = p.product_ref
              LEFT JOIN inventory i
                ON i.stock_ref = sm.stock_ref AND i.store_location = ?
             WHERE {where_sql}
             ORDER BY match_score DESC,
                      (IFNULL(i.qty_in_stock, 0) > 0) DESC,
                      i.qty_in_stock DESC
             LIMIT ?
        """
        rows = c.execute(
            sql,
            [*score_params, store_location, *params, limit],
        ).fetchall()
    else:
        sql = f"""
            SELECT p.product_ref, p.title, p.brand, p.category, p.description,
                   p.policy, p.ingredients, p.base_price_gbp,
                   p.base_price_gbp                          AS price_gbp,
                   NULL                                       AS qty_in_stock,
                   ''                                         AS shelf_location,
                   ({score_sql})                              AS match_score
              FROM products p
             WHERE {where_sql}
             ORDER BY match_score DESC
             LIMIT ?
        """
        rows = c.execute(
            sql,
            [*score_params, *params, limit],
        ).fetchall()
    return [dict(r) for r in rows]


def get_product(product_ref: str,
                conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    r = c.execute("SELECT * FROM products WHERE product_ref = ?",
                  (product_ref,)).fetchone()
    return dict(r) if r else None


def get_store_inventory(store_location: str,
                        conn: sqlite3.Connection | None = None) -> list[dict]:
    c = _conn(conn)
    store_location = _resolve_store(store_location, c)
    rows = c.execute(
        """
        SELECT p.product_ref, p.title, p.brand, p.category,
               i.qty_in_stock, i.local_price_gbp, i.shelf_location
          FROM inventory i
          JOIN stock_map sm ON sm.stock_ref = i.stock_ref
          JOIN products p   ON p.product_ref = sm.product_ref
         WHERE i.store_location = ?
         ORDER BY p.category, p.title
        """,
        (store_location,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_stores(conn: sqlite3.Connection | None = None) -> list[dict]:
    c = _conn(conn)
    rows = c.execute(
        "SELECT DISTINCT store_location, store_region "
        "FROM inventory ORDER BY store_location"
    ).fetchall()
    return [dict(r) for r in rows]


def price_at_store(product_ref: str, store_location: str,
                   conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    store_location = _resolve_store(store_location, c)
    r = c.execute(
        """
        SELECT p.product_ref, p.title, p.base_price_gbp,
               i.local_price_gbp, i.qty_in_stock, i.shelf_location
          FROM products p
          JOIN stock_map sm ON sm.product_ref = p.product_ref
          LEFT JOIN inventory i
            ON i.stock_ref = sm.stock_ref AND i.store_location = ?
         WHERE p.product_ref = ?
        """,
        (store_location, product_ref),
    ).fetchone()
    return dict(r) if r else None


# ---------------------------- Customers ------------------------------

def get_customer(email: str,
                 conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    r = c.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone()
    return dict(r) if r else None


def list_mof_methods(email: str, include_expired: bool = False,
                     conn: sqlite3.Connection | None = None) -> list[dict]:
    c = _conn(conn)
    if include_expired:
        rows = c.execute(
            "SELECT * FROM merchant_on_file_methods WHERE email = ? "
            "ORDER BY created_at DESC", (email,)).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM merchant_on_file_methods "
            "WHERE email = ? AND is_expired = 0 "
            "ORDER BY created_at DESC", (email,)).fetchall()
    return [dict(r) for r in rows]


def get_mof_by_alias(email: str, alias: str,
                     conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    r = c.execute(
        "SELECT * FROM merchant_on_file_methods "
        "WHERE email = ? AND alias = ? AND is_expired = 0 LIMIT 1",
        (email, alias)).fetchone()
    return dict(r) if r else None


def upsert_mof_stored_id(mof_id: str, real_stored_id: str,
                         conn: sqlite3.Connection | None = None) -> None:
    """Used by the Adyen zero-auth CLI to swap mock IDs for real ones."""
    c = _conn(conn)
    c.execute(
        "UPDATE merchant_on_file_methods "
        "SET adyen_stored_payment_method_id = ? "
        "WHERE id = ?", (real_stored_id, mof_id))


# ---------------------------- Orders ---------------------------------

def list_past_orders(email: str, limit: int = 20,
                     conn: sqlite3.Connection | None = None) -> list[dict]:
    c = _conn(conn)
    rows = c.execute(
        """
        SELECT o.order_id, o.placed_at, o.total_gbp, o.store_location,
               o.stored_method_id
          FROM past_orders o
         WHERE o.email = ?
         ORDER BY o.placed_at DESC
         LIMIT ?
        """,
        (email, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_order(order_id: str,
              conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    head = c.execute("SELECT * FROM past_orders WHERE order_id = ?",
                     (order_id,)).fetchone()
    if not head:
        return None
    lines = c.execute(
        "SELECT l.product_ref, l.qty, l.unit_price_gbp, p.title, p.brand "
        "FROM past_order_lines l JOIN products p USING(product_ref) "
        "WHERE l.order_id = ?", (order_id,)).fetchall()
    return {**dict(head), "lines": [dict(r) for r in lines]}


# ---------------------------- Carts ----------------------------------

def insert_cart(cart_id: str, email: str, store_location: str | None,
                created_at: datetime, expires_at: datetime,
                conn: sqlite3.Connection | None = None) -> None:
    c = _conn(conn)
    c.execute(
        "INSERT INTO carts(cart_id, email, store_location, created_at, expires_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (cart_id, email, store_location,
         created_at.astimezone(timezone.utc).isoformat(),
         expires_at.astimezone(timezone.utc).isoformat()),
    )


def add_cart_item(cart_id: str, product_ref: str, qty: int, unit_price_gbp: float,
                  conn: sqlite3.Connection | None = None) -> None:
    c = _conn(conn)
    c.execute(
        """
        INSERT INTO cart_items(cart_id, product_ref, qty, unit_price_gbp)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(cart_id, product_ref) DO UPDATE SET
            qty = qty + excluded.qty
        """,
        (cart_id, product_ref, qty, unit_price_gbp),
    )


def remove_cart_item(cart_id: str, product_ref: str,
                     conn: sqlite3.Connection | None = None) -> None:
    c = _conn(conn)
    c.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_ref = ?",
              (cart_id, product_ref))


def get_cart(cart_id: str,
             conn: sqlite3.Connection | None = None) -> dict | None:
    c = _conn(conn)
    head = c.execute("SELECT * FROM carts WHERE cart_id = ?",
                     (cart_id,)).fetchone()
    if not head:
        return None
    items = c.execute(
        "SELECT ci.product_ref, ci.qty, ci.unit_price_gbp, p.title, p.brand, p.category "
        "FROM cart_items ci JOIN products p USING(product_ref) "
        "WHERE ci.cart_id = ?", (cart_id,)).fetchall()
    return {**dict(head), "items": [dict(r) for r in items]}


def set_cart_mandate(cart_id: str, cart_mandate: dict,
                     conn: sqlite3.Connection | None = None) -> None:
    c = _conn(conn)
    c.execute(
        "UPDATE carts SET status='finalized', cart_mandate_json=? WHERE cart_id=?",
        (json.dumps(cart_mandate), cart_id))


def set_cart_chosen_payment(cart_id: str, token: str, source: str,
                            conn: sqlite3.Connection | None = None) -> None:
    c = _conn(conn)
    c.execute(
        "UPDATE carts SET chosen_token=?, chosen_source=? WHERE cart_id=?",
        (token, source, cart_id))


def record_order(order_id: str, email: str, placed_at: str,
                 total_gbp: float, store_location: str,
                 cart_id: str,
                 conn: sqlite3.Connection | None = None) -> None:
    """Insert a completed order into past_orders + past_order_lines.

    Copies line items from ``cart_items`` for ``cart_id``.  Safe to call
    multiple times (INSERT OR IGNORE); a duplicate order_id is silently
    skipped so retries don't double-insert.
    """
    owned = conn is None
    c = _conn(conn)
    try:
        c.execute(
            "INSERT OR IGNORE INTO past_orders"
            "(order_id, email, placed_at, total_gbp, store_location) "
            "VALUES(?, ?, ?, ?, ?)",
            (order_id, email, placed_at, total_gbp, store_location),
        )
        rows = c.execute(
            "SELECT product_ref, qty, unit_price_gbp FROM cart_items "
            "WHERE cart_id = ?", (cart_id,)
        ).fetchall()
        for row in rows:
            c.execute(
                "INSERT OR IGNORE INTO past_order_lines"
                "(order_id, product_ref, qty, unit_price_gbp) "
                "VALUES(?, ?, ?, ?)",
                (order_id, row["product_ref"], row["qty"],
                 row["unit_price_gbp"]),
            )
        if owned:
            c.commit()
    except Exception:
        if owned:
            c.rollback()
        raise


def decrement_stock_from_cart(cart_id: str, store_location: str,
                              conn: sqlite3.Connection | None = None) -> None:
    """Decrement ``inventory.qty_in_stock`` for each item in ``cart_id``.

    Decrements are clamped at 0 so stock never goes negative.  Uses the
    store-specific inventory row; if no store match is found the global
    minimum is used as a fallback.  Silent no-op if the product is not in
    the inventory table at all.
    """
    owned = conn is None
    c = _conn(conn)
    try:
        items = c.execute(
            "SELECT product_ref, qty FROM cart_items WHERE cart_id = ?",
            (cart_id,)
        ).fetchall()
        for item in items:
            product_ref = item["product_ref"]
            qty = item["qty"]
            # Find stock_ref via stock_map
            sm = c.execute(
                "SELECT stock_ref FROM stock_map WHERE product_ref = ?",
                (product_ref,)
            ).fetchone()
            if not sm:
                continue
            stock_ref = sm["stock_ref"]
            # Prefer store-specific row; fall back to any row for this stock_ref
            inv = c.execute(
                "SELECT inv_id, qty_in_stock FROM inventory "
                "WHERE stock_ref = ? AND store_location = ? "
                "ORDER BY qty_in_stock DESC LIMIT 1",
                (stock_ref, store_location)
            ).fetchone()
            if not inv:
                inv = c.execute(
                    "SELECT inv_id, qty_in_stock FROM inventory "
                    "WHERE stock_ref = ? "
                    "ORDER BY qty_in_stock DESC LIMIT 1",
                    (stock_ref,)
                ).fetchone()
            if not inv:
                continue
            new_qty = max(0, inv["qty_in_stock"] - qty)
            c.execute(
                "UPDATE inventory SET qty_in_stock = ? WHERE inv_id = ?",
                (new_qty, inv["inv_id"])
            )
        if owned:
            c.commit()
    except Exception:
        if owned:
            c.rollback()
        raise
