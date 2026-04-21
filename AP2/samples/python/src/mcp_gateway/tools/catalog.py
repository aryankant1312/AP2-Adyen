"""Catalog tools — pure SQLite reads against ``pharmacy_data``.

Tools that the LLM is most likely to render visually
(``search_products`` and ``get_store_inventory``) wrap their payloads
with the ``ui://product_grid`` widget envelope so ChatGPT
developer-mode renders an inline product grid; Claude falls back to
the JSON content block. ``get_product`` and ``list_stores`` stay as
plain JSON returns — they're typically narrated by the model in prose.
"""

from __future__ import annotations

from pharmacy_data import queries

from ..schemas import ProductDetail, ProductSummary, StoreInventoryRow
from ..ui import PRODUCT_GRID_URI, widget_meta, widget_result


def _row_to_summary(r: dict) -> dict:
    qty = r.get("qty_in_stock")
    return ProductSummary(
        product_ref=r["product_ref"],
        title=r["title"],
        brand=r.get("brand"),
        category=r.get("category"),
        price_gbp=float(r.get("price_gbp") or r.get("base_price_gbp") or 0.0),
        in_stock=bool(qty and qty > 0) if qty is not None else True,
        qty_in_stock=qty,
        shelf=r.get("shelf_location") or None,
    ).model_dump()


def register(mcp) -> None:

    @mcp.tool(
        meta=widget_meta(
            PRODUCT_GRID_URI,
            invoking="Searching the pharmacy catalog…",
            invoked="Showing matching products",
        ),
    )
    async def search_products(query: str,
                               store_location: str | None = None,
                               limit: int = 5):
        """Search the pharmacy catalog by keyword.

        Args:
          query: free-text search against title/description/category/brand.
          store_location: if given, results are ranked by stock at that
                          store and ``price_gbp`` reflects the store's
                          local price.
          limit: max rows (default 5).
        """
        rows = queries.search_products(query=query,
                                       store_location=store_location,
                                       limit=limit)
        products = [_row_to_summary(r) for r in rows]
        return widget_result(
            {"products": products, "store": store_location, "query": query},
            ui_uri=PRODUCT_GRID_URI,
        )

    @mcp.tool()
    async def get_product(product_ref: str,
                           store_location: str | None = None) -> dict | None:
        """Fetch full product detail; if ``store_location`` given, also
        include stock + local price at that store."""
        base = queries.get_product(product_ref)
        if not base:
            return None
        merged = dict(base)
        if store_location:
            inv = queries.price_at_store(product_ref, store_location) or {}
            merged.setdefault("price_gbp",
                              inv.get("local_price_gbp")
                              or base.get("base_price_gbp"))
            merged["qty_in_stock"]   = inv.get("qty_in_stock")
            merged["shelf_location"] = inv.get("shelf_location")
        else:
            merged["price_gbp"]    = base.get("base_price_gbp")
            merged["qty_in_stock"] = None
            merged["shelf_location"] = None

        merged["in_stock"] = bool((merged.get("qty_in_stock") or 0) > 0) \
            if merged.get("qty_in_stock") is not None else True
        merged["shelf"] = merged.pop("shelf_location", None)
        return ProductDetail(**{k: merged.get(k) for k in
                                ProductDetail.model_fields}).model_dump()

    @mcp.tool(
        meta=widget_meta(
            PRODUCT_GRID_URI,
            invoking="Loading store inventory…",
            invoked="Showing store inventory",
        ),
    )
    async def get_store_inventory(store_location: str):
        """List in-stock + out-of-stock items at a single pharmacy store."""
        rows = queries.get_store_inventory(store_location)
        # Map StoreInventoryRow into the same ProductSummary shape the
        # widget expects, so we reuse the product_grid template.
        products = []
        for r in rows:
            inv = StoreInventoryRow(**{k: r.get(k)
                                       for k in StoreInventoryRow.model_fields}
                                    ).model_dump()
            qty = inv.get("qty_in_stock")
            products.append({
                "product_ref":  inv["product_ref"],
                "title":        inv["title"],
                "brand":        inv.get("brand"),
                "category":     inv.get("category"),
                "price_gbp":    float(inv.get("local_price_gbp") or 0.0),
                "in_stock":     bool(qty and qty > 0),
                "qty_in_stock": qty,
                "shelf":        inv.get("shelf_location"),
            })
        return widget_result(
            {"products": products, "store": store_location},
            ui_uri=PRODUCT_GRID_URI,
        )

    @mcp.tool()
    async def list_stores() -> list[dict]:
        """Return all known pharmacy locations + region codes."""
        return queries.list_stores()
