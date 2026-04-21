"""Mock card adapter — preserves the legacy OTP=123 demo path.

This is the default when ``PSP_ADAPTER`` is not set or is ``mock``. It
does NOT call any external service. Useful for end-to-end CI without
Adyen credentials.
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

_DEMO_OTP = "123"


class MockCardAdapter(PaymentAdapter):
    name = "mock_card"

    async def raise_challenge(self, payment_mandate: PaymentMandate) -> Challenge:
        return Challenge(
            type="otp",
            payload={
                "display_text": (
                    "The payment method issuer sent a verification code to the "
                    "phone number on file. Enter it below. (Demo only — code is 123)"
                ),
            },
            challenge_id=f"otp_{secrets.token_urlsafe(8)}",
        )

    async def validate_challenge_response(self, response: str) -> bool:
        return response.strip() == _DEMO_OTP

    async def authorize(self, payment_mandate: PaymentMandate,
                        risk_data: str) -> AuthorizeResult:
        # Synthetic success once the OTP has been validated.
        return AuthorizeResult(
            status=AuthorizeStatus.AUTHORISED,
            psp_reference=f"mock_psp_{secrets.token_hex(8)}",
            auth_code=secrets.token_hex(3).upper(),
            raw_result_code="Authorised",
        )
