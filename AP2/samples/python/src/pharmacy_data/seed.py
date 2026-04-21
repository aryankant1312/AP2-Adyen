"""CLI entrypoint to seed the SQLite DB from CSVs + synthesizers.

Usage:
    python -m pharmacy_data.seed \
        --db data/pharmacy.sqlite \
        --seed 42 \
        --target-products 100

Idempotent: drops + recreates seed tables every run. Runtime tables
(``carts``, ``challenges``, ``mcp_sessions``) are preserved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db as _db
from . import loader, synthesize


_SEED_TABLES = (
    "past_order_lines", "past_orders",
    "merchant_on_file_methods", "customers",
    "inventory", "stock_map", "products",
)


def _truncate_seed_tables(conn) -> None:
    for tbl in _SEED_TABLES:
        conn.execute(f"DELETE FROM {tbl}")


def _insert_products(conn, products: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO products(product_ref, title, brand, category, "
        "description, policy, ingredients, base_price_gbp) "
        "VALUES(:product_ref, :title, :brand, :category, "
        ":description, :policy, :ingredients, :base_price_gbp)",
        products,
    )


def _insert_stock_map(conn, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO stock_map(product_ref, stock_ref) "
        "VALUES(:product_ref, :stock_ref)",
        rows,
    )


def _insert_inventory(conn, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO inventory(inv_id, stock_ref, store_location, store_region, "
        "qty_in_stock, local_price_gbp, currency, last_restock_date, "
        "shelf_location, notes) "
        "VALUES(:inv_id, :stock_ref, :store_location, :store_region, "
        ":qty_in_stock, :local_price_gbp, :currency, :last_restock_date, "
        ":shelf_location, :notes)",
        rows,
    )


def _insert_customers(conn, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO customers(email, full_name, phone, preferred_store, joined_at) "
        "VALUES(:email, :full_name, :phone, :preferred_store, :joined_at)",
        rows,
    )


def _insert_mof(conn, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO merchant_on_file_methods(id, email, "
        "adyen_stored_payment_method_id, brand, last4, alias, "
        "expiry_month, expiry_year, is_expired, created_at, last_used_at) "
        "VALUES(:id, :email, :adyen_stored_payment_method_id, :brand, "
        ":last4, :alias, :expiry_month, :expiry_year, :is_expired, "
        ":created_at, :last_used_at)",
        rows,
    )


def _insert_orders(conn, orders: list[dict], lines: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO past_orders(order_id, email, placed_at, total_gbp, "
        "store_location, stored_method_id) "
        "VALUES(:order_id, :email, :placed_at, :total_gbp, "
        ":store_location, :stored_method_id)",
        orders,
    )
    conn.executemany(
        "INSERT INTO past_order_lines(order_id, product_ref, qty, unit_price_gbp) "
        "VALUES(:order_id, :product_ref, :qty, :unit_price_gbp)",
        lines,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed pharmacy POC SQLite DB")
    parser.add_argument("--db", type=Path, default=None,
                        help="Path to SQLite DB (default: $PHARMACY_DB or data/pharmacy.sqlite)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for deterministic synthesis")
    parser.add_argument("--target-products", type=int, default=100)
    parser.add_argument("--customers-total", type=int, default=25)
    parser.add_argument("--customers-returning", type=int, default=20)
    parser.add_argument("--orders-per-customer", type=int, default=5)
    parser.add_argument("--products-csv", type=str, default=None)
    parser.add_argument("--inventory-csv", type=str, default=None)
    parser.add_argument("--stock-map-csv", type=str, default=None)
    args = parser.parse_args(argv)

    seed_products  = loader.load_products(args.products_csv) if args.products_csv else loader.load_products()
    seed_stock     = loader.load_stock_map(args.stock_map_csv) if args.stock_map_csv else loader.load_stock_map()
    seed_inventory = loader.load_inventory(args.inventory_csv) if args.inventory_csv else loader.load_inventory()

    bundle = synthesize.build(
        seed_products=seed_products,
        seed_stock=seed_stock,
        seed_inventory=seed_inventory,
        rng_seed=args.seed,
        target_products=args.target_products,
        customers_total=args.customers_total,
        customers_returning=args.customers_returning,
        orders_per_customer=args.orders_per_customer,
    )

    conn = _db.connect(args.db)
    with _db.transaction(conn):
        _truncate_seed_tables(conn)
        _insert_products(conn, bundle.products)
        _insert_stock_map(conn, bundle.stock_map)
        _insert_inventory(conn, bundle.inventory)
        _insert_customers(conn, bundle.customers)
        _insert_mof(conn, bundle.merchant_on_file_methods)
        _insert_orders(conn, bundle.past_orders, bundle.past_order_lines)

    print("seeded:")
    print(f"  products:                 {len(bundle.products)}")
    print(f"  stock_map:                {len(bundle.stock_map)}")
    print(f"  inventory:                {len(bundle.inventory)}")
    print(f"  customers:                {len(bundle.customers)}")
    print(f"  merchant_on_file_methods: {len(bundle.merchant_on_file_methods)}")
    print(f"  past_orders:              {len(bundle.past_orders)}")
    print(f"  past_order_lines:         {len(bundle.past_order_lines)}")
    print(f"db: {_db.DB_PATH if args.db is None else args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
