"""Pharmacy POC data layer.

SQLite-backed catalog, inventory, customers, on-file payment methods, and
synthetic order history. Used by the merchant agent (catalog + customer
vault), the credentials provider (account fixtures), and the MCP gateway
(history queries).

Public entry points:
    pharmacy_data.db.connect()       — open a connection (creates schema if missing)
    pharmacy_data.seed.main()        — CLI seed-from-CSV + synth generator
    pharmacy_data.queries.*          — typed read helpers consumed by agents

The on-disk path defaults to ``$PHARMACY_DB`` (env) or
``data/pharmacy.sqlite`` relative to the repo root.
"""

from .db import DB_PATH, connect, ensure_schema  # noqa: F401
