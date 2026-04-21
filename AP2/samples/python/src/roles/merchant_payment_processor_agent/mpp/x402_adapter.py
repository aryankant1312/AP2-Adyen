"""x402 adapter — wraps the legacy x402 path from the original sample.

The x402 protocol is settled directly via the signed payload carried in
``payment_mandate.payment_response.details.value``. This adapter does
not raise a step-up challenge and does not require a credentials provider.
"""

from __future__ import annotations

import secrets

from ap2.types.mandate import PaymentMandate

from .base import (
    AuthorizeResult,
    AuthorizeStatus,
    Challenge,
    PaymentAdapter,
)


class X402Adapter(PaymentAdapter):
    name = "x402"

    async def raise_challenge(self, payment_mandate: PaymentMandate) -> Challenge:
        # x402 settlement is non-interactive.
        return Challenge(type="none", payload={})

    async def authorize(self, payment_mandate: PaymentMandate,
                        risk_data: str) -> AuthorizeResult:
        details = payment_mandate.payment_mandate_contents.payment_response.details
        signed_payload = (details or {}).get("value")
        if not signed_payload:
            return AuthorizeResult(
                status=AuthorizeStatus.REFUSED,
                error_message="x402: missing signed payload in payment_response.details.value",
            )
        # We do not actually broadcast on-chain in the POC; we synthesize
        # a transaction id that the receipt carries forward.
        return AuthorizeResult(
            status=AuthorizeStatus.AUTHORISED,
            psp_reference=f"x402_{secrets.token_hex(10)}",
            raw_result_code="Authorised",
        )
