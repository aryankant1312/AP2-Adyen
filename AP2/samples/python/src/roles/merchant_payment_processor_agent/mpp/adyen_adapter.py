"""Adyen Checkout adapter (real PSP path).

Talks to Adyen's Checkout API v71 via plain ``httpx``. Uses the
``shopperReference + storedPaymentMethodId`` recurring primitives so the
POC mirrors a real merchant-on-file flow. The stored ID is carried
forward in ``payment_response.details.token.value`` (with the ``mof:``
prefix the rest of the system uses).

Required env (per the plan §"Prerequisite: getting Adyen sandbox keys"):

    ADYEN_API_KEY         X-API-Key from your test API credential
    ADYEN_MERCHANT_ACCOUNT  e.g. YourCompanyECOM
    ADYEN_ENV             "TEST" (default) or "LIVE"
    ADYEN_API_BASE        optional override (defaults to standard checkout-test URL)

The adapter never reads or writes the customer's PAN — the
``storedPaymentMethodId`` is everything Adyen needs.

Step-up: when Adyen returns ``ChallengeShopper``, we surface the
``action`` blob (for 3DS2 redirect) as a Challenge. Finalisation lands
via the Adyen webhook on the merchant agent (separate code path —
``payments/details`` is wired in the merchant agent's webhook handler,
not here).
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from typing import Any

import httpx

from ap2.types.mandate import PaymentMandate

from .base import (
    AuthorizeResult,
    AuthorizeStatus,
    Challenge,
    PaymentAdapter,
)

_DEFAULT_TEST_BASE = "https://checkout-test.adyen.com/v71"
_DEFAULT_LIVE_BASE_HINT = (
    # Real live URL is per-account; set ADYEN_API_BASE explicitly when LIVE.
    "https://checkout-live.adyen.com/v71"
)


def _api_base() -> str:
    if os.environ.get("ADYEN_API_BASE"):
        return os.environ["ADYEN_API_BASE"].rstrip("/")
    if os.environ.get("ADYEN_ENV", "TEST").upper() == "LIVE":
        return _DEFAULT_LIVE_BASE_HINT
    return _DEFAULT_TEST_BASE


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"AdyenAdapter requires env var {name}. See the plan's "
            "'Prerequisite: getting Adyen sandbox keys' section."
        )
    return val


def _strip_mof_prefix(token: str) -> str:
    return token[len("mof:"):] if token.startswith("mof:") else token


class AdyenAdapter(PaymentAdapter):
    name = "adyen"

    def __init__(self,
                 http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client  # injected in tests; otherwise lazily built

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=_api_base(),
                headers={
                    "X-API-Key":   _required_env("ADYEN_API_KEY"),
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._http

    async def raise_challenge(self, payment_mandate: PaymentMandate) -> Challenge:
        # Adyen decides whether 3DS2 is needed during ``/payments``; we
        # don't pre-raise.
        return Challenge(type="none", payload={})

    async def authorize(self, payment_mandate: PaymentMandate,
                        risk_data: str) -> AuthorizeResult:
        contents = payment_mandate.payment_mandate_contents
        details = contents.payment_response.details or {}
        token_obj = details.get("token") or {}
        raw_token = token_obj.get("value") if isinstance(token_obj, dict) else None
        if not raw_token:
            return AuthorizeResult(
                status=AuthorizeStatus.ERROR,
                error_message="adyen: missing token in payment_response.details.token.value",
            )
        stored_payment_method_id = _strip_mof_prefix(raw_token)
        shopper_reference = (
            contents.payment_response.payer_email
            or contents.payment_response.payer_name
            or "anonymous_shopper"
        )

        amount = contents.payment_details_total.amount
        currency = amount.currency or "GBP"
        # Adyen uses minor units; GBP minor units are pence (×100).
        minor_units = int(round(float(amount.value) * 100))

        body = {
            "merchantAccount":           _required_env("ADYEN_MERCHANT_ACCOUNT"),
            "amount": {
                "currency": currency,
                "value":    minor_units,
            },
            "reference":                 contents.payment_mandate_id,
            "shopperReference":          shopper_reference,
            "shopperInteraction":        "ContAuth",
            "recurringProcessingModel":  "UnscheduledCardOnFile",
            "paymentMethod": {
                "type":                     "scheme",
                "storedPaymentMethodId":    stored_payment_method_id,
            },
            "returnUrl": os.environ.get(
                "ADYEN_RETURN_URL",
                "https://example.com/ap2-poc/return",
            ),
            "channel":                   "Web",
            "metadata": {
                "ap2_payment_mandate_id": contents.payment_mandate_id,
                "adapter":                "ap2-pharmacy-poc",
            },
        }

        client = await self._client()
        try:
            r = await client.post("/payments", json=body)
        except httpx.HTTPError as e:
            logging.exception("Adyen /payments transport error")
            return AuthorizeResult(
                status=AuthorizeStatus.ERROR,
                error_message=f"adyen transport error: {e}",
            )

        if r.status_code >= 500:
            return AuthorizeResult(
                status=AuthorizeStatus.ERROR,
                error_message=f"adyen 5xx: {r.status_code} {r.text[:300]}",
            )

        try:
            data: dict[str, Any] = r.json()
        except Exception:
            return AuthorizeResult(
                status=AuthorizeStatus.ERROR,
                error_message=f"adyen non-json response: {r.text[:300]}",
            )

        return self._from_adyen_response(data, contents.payment_mandate_id)

    def _from_adyen_response(self, data: dict[str, Any],
                              payment_mandate_id: str) -> AuthorizeResult:
        result_code = data.get("resultCode")
        psp_ref     = data.get("pspReference")

        if result_code == "Authorised":
            return AuthorizeResult(
                status=AuthorizeStatus.AUTHORISED,
                psp_reference=psp_ref,
                raw_result_code=result_code,
            )

        if result_code in ("ChallengeShopper", "IdentifyShopper",
                           "RedirectShopper"):
            action = data.get("action") or {}
            challenge_id = f"ch_{uuid.uuid4().hex[:12]}"
            payload = {
                "url":              action.get("url"),
                "method":           action.get("method"),
                "data":             action.get("data"),
                "paymentData":      action.get("paymentData"),
                "type":             action.get("type"),
                "psp_reference":    psp_ref,
                "payment_mandate_id": payment_mandate_id,
            }
            return AuthorizeResult(
                status=AuthorizeStatus.CHALLENGE_SHOPPER,
                psp_reference=psp_ref,
                raw_result_code=result_code,
                challenge=Challenge(
                    type=("3ds2_redirect" if action.get("type") == "redirect"
                          else "3ds2_fingerprint"),
                    payload=payload,
                    challenge_id=challenge_id,
                ),
            )

        if result_code in ("Refused", "Cancelled"):
            return AuthorizeResult(
                status=AuthorizeStatus.REFUSED,
                psp_reference=psp_ref,
                raw_result_code=result_code,
                error_message=data.get("refusalReason") or "refused",
            )

        return AuthorizeResult(
            status=AuthorizeStatus.ERROR,
            psp_reference=psp_ref,
            raw_result_code=result_code,
            error_message=f"unexpected resultCode: {result_code}",
        )
