"""CSV → row-dict loaders for the three seed CSVs.

The CSV paths default to the user-provided downloads folder but can be
overridden via env vars (used by the Docker image where the CSVs are
copied into ``/app/seed/``).
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Iterable

# Match exactly the three CSVs the user supplied.
_DEFAULT_PRODUCTS_CSV = os.environ.get(
    "PHARMACY_PRODUCTS_CSV",
    "C:/Users/Acer/Downloads/walgreens_dataset_20.csv",
)
_DEFAULT_INVENTORY_CSV = os.environ.get(
    "PHARMACY_INVENTORY_CSV",
    "C:/Users/Acer/Downloads/store_inventory 1.csv",
)
_DEFAULT_STOCK_MAP_CSV = os.environ.get(
    "PHARMACY_STOCK_MAP_CSV",
    "C:/Users/Acer/Downloads/product_stock_map.csv",
)

_PRICE_RE = re.compile(r"[^0-9.]")


def _strip_price(raw: str) -> float:
    """Convert '$8.49' / '£8.49' / '8.49' into 8.49."""
    cleaned = _PRICE_RE.sub("", raw)
    return float(cleaned) if cleaned else 0.0


def load_products(path: str | Path = _DEFAULT_PRODUCTS_CSV) -> list[dict]:
    """Load the walgreens product CSV.

    Returns dicts shaped like rows of the ``products`` table, *except*
    ``product_ref`` which is assigned by the stock-map join (P001..P021).
    """
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "title":          r["Title"].strip(),
                "brand":          r["Brand"].strip(),
                "category":       r["Category"].strip(),
                "description":    r["Description"].strip(),
                "policy":         r["Policy"].strip(),
                "ingredients":    r["Ingredients"].strip(),
                "base_price_gbp": _strip_price(r["Price"]),
            })
    return rows


def load_stock_map(path: str | Path = _DEFAULT_STOCK_MAP_CSV) -> list[dict]:
    """Returns [{product_ref, stock_ref}, ...]."""
    out: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out.append({
                "product_ref": r["product_ref"].strip(),
                "stock_ref":   r["stock_ref"].strip(),
            })
    return out


def load_inventory(path: str | Path = _DEFAULT_INVENTORY_CSV) -> list[dict]:
    """Returns rows shaped for the ``inventory`` table."""
    out: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out.append({
                "inv_id":            r["inv_id"].strip(),
                "stock_ref":         r["stock_ref"].strip(),
                "store_location":    r["store_location"].strip(),
                "store_region":      r["store_region"].strip(),
                "qty_in_stock":      int(r["qty_in_stock"]),
                "local_price_gbp":   float(r["local_price"]),
                "currency":          r.get("currency", "GBP").strip() or "GBP",
                "last_restock_date": r["last_restock_date"].strip(),
                "shelf_location":    r["shelf_location"].strip(),
                "notes":             (r.get("notes") or "").strip() or None,
            })
    return out


def stores_from_inventory(rows: Iterable[dict]) -> list[tuple[str, str]]:
    """Distinct ``(store_location, store_region)`` pairs in stable order."""
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["store_location"], r["store_region"])
    return sorted(seen.items())
