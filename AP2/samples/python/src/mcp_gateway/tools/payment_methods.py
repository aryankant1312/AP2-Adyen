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

from .. import session as _session
from ..schemas import PaymentMethodSummary, PaymentMethodToken
from ..ui import MOF_PICKER_URI, widget_meta, widget_result


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
