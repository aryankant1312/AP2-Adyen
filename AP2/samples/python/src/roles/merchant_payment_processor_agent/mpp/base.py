"""PaymentAdapter ABC + result types.

Every PSP integration (mock, x402, Adyen) implements this contract. The
MPP's ``tools.py`` is now a thin dispatch layer that picks an adapter
and forwards.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ap2.types.mandate import PaymentMandate


class AuthorizeStatus(str, enum.Enum):
    AUTHORISED       = "Authorised"
    CHALLENGE_SHOPPER = "ChallengeShopper"
    REFUSED          = "Refused"
    ERROR            = "Error"


@dataclass
class Challenge:
    """A step-up challenge handed back to the shopper.

    ``type`` is one of: ``otp``, ``3ds2_redirect``, ``3ds2_fingerprint``.
    ``payload`` is adapter-specific (e.g. Adyen's ``action`` blob, or the
    OTP display text).
    """
    type:    str
    payload: dict[str, Any] = field(default_factory=dict)
    challenge_id: str | None = None


@dataclass
class AuthorizeResult:
    status:           AuthorizeStatus
    psp_reference:    str | None = None
    auth_code:        str | None = None
    raw_result_code:  str | None = None
    challenge:        Challenge | None = None
    error_message:    str | None = None


class PaymentAdapter(ABC):
    """All payment adapters implement this contract.

    ``authorize`` is called *after* the OTP / step-up has been resolved
    (or as the first call when no challenge is needed). ``raise_challenge``
    is called when the caller wants a step-up before authorize — it is a
    legacy entry point for the OTP-only adapters; Adyen returns the
    challenge inside ``authorize`` directly.
    """

    name: str = "abstract"

    @abstractmethod
    async def authorize(self, payment_mandate: PaymentMandate,
                        risk_data: str) -> AuthorizeResult:
        ...

    async def raise_challenge(self, payment_mandate: PaymentMandate) -> Challenge:
        """Default: no challenge needed — adapter authorizes immediately."""
        return Challenge(type="none", payload={})

    async def validate_challenge_response(self, response: str) -> bool:
        """Default: accept anything — only mock adapter overrides."""
        return True
