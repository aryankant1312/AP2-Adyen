-- Pharmacy POC SQLite schema.
-- All monetary values are GBP. Booleans use INTEGER 0/1.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS products (
    product_ref     TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    brand           TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT NOT NULL,
    policy          TEXT NOT NULL,
    ingredients     TEXT NOT NULL,
    base_price_gbp  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_brand    ON products(brand);

CREATE TABLE IF NOT EXISTS stock_map (
    product_ref TEXT PRIMARY KEY REFERENCES products(product_ref),
    stock_ref   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS inventory (
    inv_id            TEXT PRIMARY KEY,
    stock_ref         TEXT NOT NULL REFERENCES stock_map(stock_ref),
    store_location    TEXT NOT NULL,
    store_region      TEXT NOT NULL,
    qty_in_stock      INTEGER NOT NULL,
    local_price_gbp   REAL NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'GBP',
    last_restock_date TEXT NOT NULL,
    shelf_location    TEXT NOT NULL,
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_inv_store ON inventory(store_location);
CREATE INDEX IF NOT EXISTS idx_inv_stock ON inventory(stock_ref);

CREATE TABLE IF NOT EXISTS customers (
    email           TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    phone           TEXT NOT NULL,
    preferred_store TEXT NOT NULL,
    joined_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_on_file_methods (
    id                              TEXT PRIMARY KEY,
    email                           TEXT NOT NULL REFERENCES customers(email),
    adyen_stored_payment_method_id  TEXT NOT NULL,
    brand                           TEXT NOT NULL,
    last4                           TEXT NOT NULL,
    alias                           TEXT NOT NULL,
    expiry_month                    INTEGER NOT NULL,
    expiry_year                     INTEGER NOT NULL,
    is_expired                      INTEGER NOT NULL DEFAULT 0,
    created_at                      TEXT NOT NULL,
    last_used_at                    TEXT
);

CREATE INDEX IF NOT EXISTS idx_mof_email ON merchant_on_file_methods(email);

CREATE TABLE IF NOT EXISTS past_orders (
    order_id         TEXT PRIMARY KEY,
    email            TEXT NOT NULL REFERENCES customers(email),
    placed_at        TEXT NOT NULL,
    total_gbp        REAL NOT NULL,
    store_location   TEXT NOT NULL,
    stored_method_id TEXT REFERENCES merchant_on_file_methods(id)
);

CREATE INDEX IF NOT EXISTS idx_orders_email ON past_orders(email);

CREATE TABLE IF NOT EXISTS past_order_lines (
    order_id        TEXT NOT NULL REFERENCES past_orders(order_id),
    product_ref     TEXT NOT NULL REFERENCES products(product_ref),
    qty             INTEGER NOT NULL,
    unit_price_gbp  REAL NOT NULL,
    PRIMARY KEY (order_id, product_ref)
);

-- Runtime tables (cart + payment state used by MA / MCP gateway).
CREATE TABLE IF NOT EXISTS carts (
    cart_id          TEXT PRIMARY KEY,
    email            TEXT NOT NULL,
    store_location   TEXT,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',  -- open | finalized | cancelled
    cart_mandate_json TEXT,
    chosen_token     TEXT,
    chosen_source    TEXT
);

CREATE TABLE IF NOT EXISTS cart_items (
    cart_id      TEXT NOT NULL REFERENCES carts(cart_id),
    product_ref  TEXT NOT NULL REFERENCES products(product_ref),
    qty          INTEGER NOT NULL,
    unit_price_gbp REAL NOT NULL,
    PRIMARY KEY (cart_id, product_ref)
);

-- ``challenges`` and ``mcp_sessions`` are both owned by the MCP gateway
-- and created on first boot with the columns the gateway code actually
-- uses (psp_reference, raw_result_code, refusal_reason, ...). We
-- deliberately do NOT define them here to avoid two divergent schemas
-- silently rotting (we already had to debug exactly that).
-- See:
--   * mcp_gateway/tools/payment.py::_ensure_challenges_table
--   * mcp_gateway/session.py::_ensure_table
