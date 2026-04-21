"""End-to-end query tests after a real seed."""

from __future__ import annotations

import pytest

from pharmacy_data import db as _db
from pharmacy_data import queries, seed


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("pharmacy") / "p.sqlite"
    seed.main(["--db", str(path), "--seed", "42",
               "--target-products", "100",
               "--customers-total", "25", "--customers-returning", "20",
               "--orders-per-customer", "5"])
    return _db.connect(path)


def test_search_finds_seed_product(seeded_db):
    results = queries.search_products("ibuprofen", conn=seeded_db)
    assert any("Ibuprofen" in r["title"] for r in results)


def test_search_with_store_returns_stock(seeded_db):
    stores = queries.list_stores(conn=seeded_db)
    assert stores
    store = stores[0]["store_location"]
    rows = queries.search_products("paracetamol", store_location=store, conn=seeded_db)
    for r in rows:
        assert "qty_in_stock" in r
        assert "shelf_location" in r


def test_list_stores_has_four(seeded_db):
    stores = queries.list_stores(conn=seeded_db)
    assert len(stores) == 4


def test_mof_methods_filters_expired(seeded_db):
    # Pull a customer who has at least one MOF.
    rows = seeded_db.execute(
        "SELECT email FROM merchant_on_file_methods LIMIT 1").fetchall()
    if not rows:
        pytest.skip("synth produced 0 MOF methods (rare)")
    email = rows[0]["email"]
    visible = queries.list_mof_methods(email, conn=seeded_db)
    all_ = queries.list_mof_methods(email, include_expired=True, conn=seeded_db)
    assert len(visible) <= len(all_)
    for m in visible:
        assert m["is_expired"] == 0
