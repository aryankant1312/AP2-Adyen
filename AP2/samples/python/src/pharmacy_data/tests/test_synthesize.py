"""Determinism + shape tests for the synthesizer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pharmacy_data import db as _db
from pharmacy_data import loader, seed, synthesize


@pytest.fixture
def csv_inputs():
    return loader.load_products(), loader.load_stock_map(), loader.load_inventory()


def test_seed_csvs_load(csv_inputs):
    products, stock, inv = csv_inputs
    assert len(products) == 21  # walgreens_dataset_20.csv (21 rows despite name)
    assert len(stock) == 21
    assert len(inv) == 69
    assert all(p["base_price_gbp"] > 0 for p in products)
    assert all("category" in p for p in products)


def test_synth_is_deterministic(csv_inputs):
    a = synthesize.build(*csv_inputs, rng_seed=42, target_products=100)
    b = synthesize.build(*csv_inputs, rng_seed=42, target_products=100)
    assert [p["title"] for p in a.products] == [p["title"] for p in b.products]
    assert [m["adyen_stored_payment_method_id"] for m in a.merchant_on_file_methods] \
        == [m["adyen_stored_payment_method_id"] for m in b.merchant_on_file_methods]
    assert [o["order_id"] for o in a.past_orders] \
        == [o["order_id"] for o in b.past_orders]


def test_synth_target_counts(csv_inputs):
    bundle = synthesize.build(*csv_inputs, rng_seed=42, target_products=100,
                              customers_total=25, customers_returning=20,
                              orders_per_customer=5)
    assert len(bundle.products) == 100
    assert len(bundle.stock_map) == 100
    # 4 stores × 100 SKUs = 400 max; some seed rows < 4 stores existed.
    assert 350 <= len(bundle.inventory) <= 400
    assert len(bundle.customers) == 25
    # 20 returning × 5 orders == 100.
    assert len(bundle.past_orders) == 100


def test_seed_writes_to_sqlite(csv_inputs, tmp_path):
    db_path = tmp_path / "p.sqlite"
    rc = seed.main(["--db", str(db_path), "--seed", "42", "--target-products", "50",
                    "--customers-total", "10", "--customers-returning", "8",
                    "--orders-per-customer", "3"])
    assert rc == 0
    conn = _db.connect(db_path)
    n_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    n_inv      = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    n_cust     = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert n_products == 50
    assert n_inv > 0
    assert n_cust == 10


def test_only_adyen_test_last4_used(csv_inputs):
    bundle = synthesize.build(*csv_inputs, rng_seed=42)
    allowed = {"1111", "4444", "5100", "8888", "9995"}
    assert {m["last4"] for m in bundle.merchant_on_file_methods} <= allowed


def test_emails_are_reserved_domain(csv_inputs):
    bundle = synthesize.build(*csv_inputs, rng_seed=42)
    assert all(c["email"].endswith("@example.com") for c in bundle.customers)


def test_returning_customers_have_orders(csv_inputs):
    bundle = synthesize.build(*csv_inputs, rng_seed=42)
    emails_with_orders = {o["email"] for o in bundle.past_orders}
    # Every returning customer is in the orders set; new customers (5) are not.
    assert len(emails_with_orders) == 20
