"""Payment-method discovery + token-minting tools.

These wrap two distinct A2A surfaces:
  * Merchant Agent → ``get_merchant_on_file_payment_methods`` /
    ``create_merchant_on_file_token`` (the MOF / Adyen path).
  * Credentials Provider → ``cp_search_payment_methods`` /
    ``cp_create_payment_credential_token`` (the legacy CARD/CP path).

Returned shapes are uniform so Claude / ChatGPT can treat both sources
identically when picking a method.
"""

from __future__ import annotations

from typing import Any

from common import a2a_helpers

from .. import adyen_checkout as _adyen
from .. import session as _session
from ..schemas import PaymentMethodSummary, PaymentMethodToken
from ..ui import MOF_PICKER_URI, RECEIPT_URI, widget_meta, widget_result
from .payment import _build_receipt_widget_payload


def _normalise_mof(row: dict) -> dict:
    return PaymentMethodSummary(
        alias=row.get("alias") or row.get("display_name") or "saved card",
        source="merchant_on_file",
        brand=row.get("brand"),
        last4=row.get("last4"),
        display_name=(f"{row.get('brand', '')} ending in {row.get('last4', '')}"
                      .strip() or None),
        raw=row,
    ).model_dump()


def _normalise_cp(row: dict) -> dict:
    # CP shape varies by sample; pull common fields, preserve the rest.
    return PaymentMethodSummary(
        alias=row.get("alias") or row.get("nickname") or row.get("id") or "card",
        source="credentials_provider",
        brand=row.get("brand"),
        last4=row.get("last4"),
        display_name=row.get("display_name") or row.get("nickname"),
        raw=row,
    ).model_dump()


def register(mcp) -> None:

    @mcp.tool(
        meta=widget_meta(
            MOF_PICKER_URI,
            invoking="Looking up your saved cards…",
            invoked="Choose a saved card",
        ),
    )
    async def get_merchant_on_file_payment_methods(user_email: str):
        """List the customer's saved (merchant-on-file) payment methods.

        Empty list ⇒ the LLM should call
        ``get_credentials_provider_payment_methods`` next.
        """
        rows = await a2a_helpers.merchant_get_on_file_methods(
            user_email=user_email)
        methods = [_normalise_mof(r) for r in rows]
        return widget_result(
            {"methods": methods, "user_email": user_email},
            ui_uri=MOF_PICKER_URI,
        )

    @mcp.tool()
    async def get_credentials_provider_payment_methods(user_email: str
                                                       ) -> list[dict]:
        """List payment methods the user has at the Credentials Provider."""
        rows = await a2a_helpers.cp_search_payment_methods(
            user_email=user_email)
        return [_normalise_cp(r) for r in rows]

    @mcp.tool()
    async def create_merchant_on_file_token(user_email: str,
                                             alias: str,
                                             cart_id: str | None = None,
                                             mcp_session_id: str | None = None
                                             ) -> dict:
        """Mint a charge token for a chosen MOF method.

        If ``cart_id`` (and the session has a CartMandate for it) is
        provided, the token is bound to the cart on the merchant.
        """
        cart_mandate = None
        if mcp_session_id:
            cart_mandate = _session.load_cart_mandate(mcp_session_id)

        token = await a2a_helpers.merchant_create_on_file_token(
            user_email=user_email, alias=alias,
            cart_mandate=cart_mandate,
        )
        out = PaymentMethodToken(
            token=token.get("token") or token.get("value") or "",
            source="merchant_on_file",
            alias=alias,
            brand=token.get("brand"),
            last4=token.get("last4"),
        )
        if mcp_session_id:
            _session.set_chosen_payment(mcp_session_id,
                                        token=out.token,
                                        source="merchant_on_file")
        return out.model_dump()

    @mcp.tool()
    async def create_payment_credential_token(user_email: str,
                                                payment_method_id: str,
                                                cart_id: str | None = None,
                                                mcp_session_id: str | None = None
                                                ) -> dict:
        """Mint a payment credential token via the Credentials Provider."""
        cart_mandate = None
        if mcp_session_id:
            cart_mandate = _session.load_cart_mandate(mcp_session_id)

        token = await a2a_helpers.cp_create_payment_credential_token(
            user_email=user_email,
            payment_method_id=payment_method_id,
            cart_mandate=cart_mandate,
        )
        out = PaymentMethodToken(
            token=token.get("token") or token.get("value") or "",
            source="credentials_provider",
            alias=token.get("alias"),
            brand=token.get("brand"),
            last4=token.get("last4"),
        )
        if mcp_session_id:
            _session.set_chosen_payment(mcp_session_id,
                                        token=out.token,
                                        source="credentials_provider")
        return out.model_dump()

    # ------------------------------------------------------------------
    # Adyen Web Drop-in (Sessions flow)
    #
    # Two tools: one to start a hosted-payment session, and one to poll
    # the result so the LLM can emit the receipt widget once the shopper
    # completes the 3DS2 challenge in the browser tab.
    # ------------------------------------------------------------------

    @mcp.tool()
    async def start_adyen_checkout(cart_id: str,
                                    user_email: str,
                                    mcp_session_id: str | None = None
                                    ) -> dict:
        """Start an Adyen Web Drop-in checkout for a cart.

        Returns ``{pay_url, session_id, amount_gbp}``. Give the user the
        ``pay_url`` and ask them to open it in a new tab — they will see a
        Boots-branded page that handles card / Apple Pay / Google Pay and
        3DS2. When they return, call ``poll_adyen_checkout`` with the
        ``session_id`` to fetch the outcome and render the receipt.
        """
        # Resolve cart total from SQLite.
        from pharmacy_data import db as _pdb
        conn = _pdb.connect()
        try:
            rows = conn.execute(
                "SELECT qty, unit_price_gbp FROM cart_items WHERE cart_id = ?",
                (cart_id,),
            ).fetchall()
        finally:
            conn.close()
        subtotal = round(sum((r["qty"] or 0) * (r["unit_price_gbp"] or 0)
                             for r in rows), 2)
        if subtotal <= 0:
            return {"error": "empty_cart",
                    "message": f"Cart {cart_id} has no items or zero total."}
        shipping = 2.00
        total = round(subtotal + shipping, 2)

        try:
            info = _adyen.create_checkout_session(
                cart_id=cart_id,
                user_email=user_email,
                amount_gbp=total,
                currency="GBP",
            )
        except _adyen.AdyenError as exc:
            return {"error": "adyen_error", "message": str(exc)}

        if mcp_session_id:
            _session.set_chosen_payment(
                mcp_session_id,
                token=f"adyen-session:{info['session_id']}",
                source="adyen_dropin",
            )
        return {
            **info,
            "instructions": (
                "Open the pay_url in a new tab to complete payment securely "
                "with Adyen. After you see the 'Payment authorised' screen, "
                "return here and I'll pull up your receipt."
            ),
        }

    @mcp.tool(
        meta=widget_meta(
            RECEIPT_URI,
            invoking="Checking your Adyen payment…",
            invoked="Payment result",
        ),
    )
    async def poll_adyen_checkout(session_id: str,
                                   mcp_session_id: str | None = None
                                   ) -> dict:
        """Fetch the outcome of an Adyen Drop-in session.

        Returns the receipt widget once Adyen reports the payment
        ``Authorised``. While the shopper is still on the Drop-in page this
        returns ``{"status":"pending"}`` — poll again in a few seconds.
        """
        row = _adyen.refresh_session_status(session_id)
        if not row:
            return {"status": "unknown", "error": "session_not_found"}
        status = row.get("status") or "pending"
        if status != "completed":
            return {"status": status,
                    "result_code":    row.get("result_code") or "",
                    "refusal_reason": row.get("refusal_reason") or ""}

        # Build receipt payload from our ledger row so the receipt widget
        # can render without a full AP2 PaymentMandate round-trip.
        import uuid
        order_id = f"ord_{uuid.uuid4().hex[:10]}"
        total_gbp = (row.get("amount_minor") or 0) / 100.0
        fake_receipt = {
            "status":           "Authorised",
            "payment_id":       order_id,
            "psp_reference":    row.get("psp_reference") or "",
            "merchant_reference": row.get("cart_id") or "",
            "idempotency_key":  row.get("cart_id") or order_id,
            "amount":           {"value": total_gbp,
                                 "currency": row.get("currency") or "GBP"},
            "gateway":          "Adyen",
        }
        # Attach cart_id to the session so the receipt builder can load items.
        if mcp_session_id and row.get("cart_id"):
            _session.set_cart_mandate(mcp_session_id,
                                       cart_id=row["cart_id"],
                                       cart_mandate={})
            _session.set_last_order(mcp_session_id, order_id)

        payload = _build_receipt_widget_payload(
            order_id=order_id,
            receipt=fake_receipt,
            payment_mandate={
                "payment_mandate_contents": {
                    "payment_response": {
                        "method_name":   "adyen/web-dropin",
                        "payer_email":   row.get("user_email"),
                        "details":       {"token": {"source": "Adyen Drop-in"}},
                    }
                }
            },
            mcp_session_id=mcp_session_id,
        )
        return widget_result(payload, ui_uri=RECEIPT_URI)
