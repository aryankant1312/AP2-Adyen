"""Cart tools — local cart in SQLite, finalized via the Merchant Agent.

Why we keep a local cart row at all instead of just round-tripping every
add to MA: the MA's CartMandate is a per-snapshot signed object — minting
one for every add_cart_item would be wasteful. We accumulate adds in
SQLite, then call the merchant once for the final signed CartMandate.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from common import a2a_helpers
from pharmacy_data import queries

from .. import session as _session
from ..schemas import CartFinalised, CartLine, CartView
from ..ui import CART_URI, widget_meta, widget_result


_CART_TTL_MIN = 30


def _compute_totals(items: list[dict]) -> tuple[float, float, float, float]:
    subtotal = round(sum(it["qty"] * it["unit_price_gbp"] for it in items), 2)
    shipping = 2.00 if subtotal > 0 else 0.0
    tax      = 0.0   # UK OTC medicines: 0% VAT
    total    = round(subtotal + shipping + tax, 2)
    return subtotal, shipping, tax, total


def _format_cart(cart_id: str, cart_row: dict) -> CartView:
    items = [CartLine(product_ref=it["product_ref"],
                      qty=it["qty"],
                      unit_price_gbp=it["unit_price_gbp"],
                      title=it.get("title"))
             for it in cart_row.get("items", [])]
    subtotal, shipping, tax, total = _compute_totals(
        [it.model_dump() for it in items])
    return CartView(
        cart_id=cart_id,
        user_email=cart_row.get("email"),
        store_location=cart_row.get("store_location"),
        items=items,
        subtotal_gbp=subtotal,
        shipping_gbp=shipping,
        tax_gbp=tax,
        total_gbp=total,
        expires_at=cart_row.get("expires_at"),
    )


def register(mcp) -> None:

    @mcp.tool()
    async def start_cart(user_email: str,
                          store_location: str | None = None,
                          mcp_session_id: str | None = None) -> dict:
        """Start a fresh cart for a user. Returns ``{cart_id, expires_at}``."""
        cart_id = f"cart_{uuid.uuid4().hex[:10]}"
        now     = datetime.now(timezone.utc)
        exp     = now + timedelta(minutes=_CART_TTL_MIN)
        queries.insert_cart(cart_id=cart_id, email=user_email,
                            store_location=store_location,
                            created_at=now, expires_at=exp)
        sess = _session.get_or_create(token_hash=None,
                                      user_email=user_email,
                                      session_id=mcp_session_id)
        _session.update(sess["session_id"], cart_id=cart_id,
                        user_email=user_email)
        return {"cart_id": cart_id,
                "expires_at": exp.isoformat(),
                "session_id": sess["session_id"]}

    @mcp.tool(
        meta=widget_meta(
            CART_URI,
            invoking="Adding to cart…",
            invoked="Cart updated",
        ),
    )
    async def add_cart_item(cart_id: str, product_ref: str,
                             qty: int = 1):
        """Add (or accumulate) a line item to an open cart."""
        cart = queries.get_cart(cart_id)
        if not cart:
            return {"error": f"unknown cart_id {cart_id!r}"}
        store_loc = cart.get("store_location")
        price_row = (queries.price_at_store(product_ref, store_loc)
                     if store_loc else None) \
            or queries.get_product(product_ref)
        if not price_row:
            return {"error": f"unknown product_ref {product_ref!r}"}
        unit_price = float(price_row.get("local_price_gbp")
                           or price_row.get("base_price_gbp"))
        queries.add_cart_item(cart_id=cart_id, product_ref=product_ref,
                              qty=qty, unit_price_gbp=unit_price)
        view = _format_cart(cart_id, queries.get_cart(cart_id)).model_dump()
        return widget_result(view, ui_uri=CART_URI)

    @mcp.tool(
        meta=widget_meta(
            CART_URI,
            invoking="Removing from cart…",
            invoked="Cart updated",
        ),
    )
    async def remove_cart_item(cart_id: str, product_ref: str):
        """Remove a line item entirely."""
        if not queries.get_cart(cart_id):
            return {"error": f"unknown cart_id {cart_id!r}"}
        queries.remove_cart_item(cart_id=cart_id, product_ref=product_ref)
        view = _format_cart(cart_id, queries.get_cart(cart_id)).model_dump()
        return widget_result(view, ui_uri=CART_URI)

    @mcp.tool(
        meta=widget_meta(
            CART_URI,
            invoking="Loading cart…",
            invoked="Showing cart",
        ),
    )
    async def view_cart(cart_id: str):
        """Show the current cart contents and computed totals."""
        cart = queries.get_cart(cart_id)
        if not cart:
            return {"error": f"unknown cart_id {cart_id!r}"}
        view = _format_cart(cart_id, cart).model_dump()
        return widget_result(view, ui_uri=CART_URI)

    @mcp.tool(
        meta=widget_meta(
            CART_URI,
            invoking="Quoting cart…",
            invoked="Showing quote",
        ),
    )
    async def quote_cart(cart_id: str,
                          shipping_address: dict[str, Any] | None = None):
        """Return computed totals (a quick local quote — does not call MA)."""
        cart = queries.get_cart(cart_id)
        if not cart:
            return {"error": f"unknown cart_id {cart_id!r}"}
        view = _format_cart(cart_id, cart).model_dump()
        view["shipping_address"] = shipping_address
        return widget_result(view, ui_uri=CART_URI)

    @mcp.tool()
    async def finalize_cart(cart_id: str,
                             shipping_address: dict[str, Any] | None = None,
                             mcp_session_id: str | None = None) -> dict:
        """Ask the Merchant Agent to mint a signed CartMandate for this cart.

        Returns ``CartFinalised`` — the signed CartMandate (with
        ``merchant_authorization`` JWT) plus the final total.
        """
        cart = queries.get_cart(cart_id)
        if not cart:
            return {"error": f"unknown cart_id {cart_id!r}"}

        # Build an IntentMandate from the cart contents so MA's catalog
        # agent can re-emit a per-cart CartMandate carrying all lines.
        from ap2.types.mandate import IntentMandate

        descr = "Cart with " + ", ".join(
            f"{it['qty']}× {it.get('title') or it['product_ref']}"
            for it in cart.get("items", [])
        )
        intent = IntentMandate(
            user_cart_confirmation_required=False,
            natural_language_description=descr,
            merchants=None,
            skus=[it["product_ref"] for it in cart.get("items", [])],
            requires_refundability=False,
            intent_expiry=(datetime.now(timezone.utc) + timedelta(hours=1))
            .isoformat(),
        )

        result = await a2a_helpers.merchant_find_products(
            intent_mandate=intent,
            user_email=cart.get("email"),
            store_location=cart.get("store_location"),
        )
        if not result["cart_mandates"]:
            return {"error": "merchant returned no cart mandates",
                    "raw":   result}

        # In this sample, MA emits one CartMandate per matched product;
        # we adopt the first one + record it locally.
        cart_mandate = result["cart_mandates"][0]
        merchant_auth = (cart_mandate.get("merchant_authorization")
                         or "")
        total = (cart_mandate.get("contents", {})
                 .get("payment_request", {})
                 .get("details", {})
                 .get("total", {})
                 .get("amount", {})
                 .get("value")
                 or sum(it["qty"] * it["unit_price_gbp"]
                        for it in cart.get("items", [])))

        queries.set_cart_mandate(cart_id, cart_mandate)
        if mcp_session_id:
            _session.set_cart_mandate(mcp_session_id, cart_id, cart_mandate)

        return CartFinalised(
            cart_id=cart_id,
            cart_mandate=cart_mandate,
            merchant_authorization=merchant_auth,
            total_gbp=float(total),
        ).model_dump()
