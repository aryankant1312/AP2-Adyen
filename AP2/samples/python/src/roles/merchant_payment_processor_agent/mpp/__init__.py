"""Payment-processor adapter strategy.

Selects an adapter at request time based on either the inbound
``payment_method_type`` (preferred) or the legacy ``PAYMENT_METHOD``
env var (fallback for back-compat with the original sample). Each
adapter implements ``PaymentAdapter`` from ``base.py``.

Adapter mapping:
    "adyen-mof" / "adyen"    -> AdyenAdapter
    "x402" / "https://www.x402.org/" -> X402Adapter
    everything else (incl. "CARD") -> MockCardAdapter
"""

from __future__ import annotations

import os

from .base import (
    AuthorizeResult,
    AuthorizeStatus,
    Challenge,
    PaymentAdapter,
)
from .mock_card_adapter import MockCardAdapter
from .x402_adapter import X402Adapter


def get_adapter(payment_method_type: str | None = None) -> PaymentAdapter:
    """Return the adapter for the given payment_method_type.

    Resolution order:
      0. ``$PSP_ADAPTER=mock`` short-circuits everything → MockCardAdapter.
         This is the dev/demo kill switch that lets the whole stack run
         with no Adyen credentials regardless of what ``method_name`` the
         gateway stamped on the PaymentMandate.
      1. Explicit ``payment_method_type`` argument (case-insensitive prefix)
      2. ``$PAYMENT_METHOD`` env var
      3. ``MockCardAdapter`` default
    """
    psp_override = (os.environ.get("PSP_ADAPTER") or "").lower().strip()
    if psp_override in {"mock", "mock_card", "mock-card"}:
        return MockCardAdapter()

    candidate = (payment_method_type or os.environ.get("PAYMENT_METHOD") or "card").lower()

    if candidate.startswith("adyen") or psp_override == "adyen":
        from .adyen_adapter import AdyenAdapter
        return AdyenAdapter()
    if "x402" in candidate:
        return X402Adapter()
    return MockCardAdapter()


__all__ = [
    "AuthorizeResult",
    "AuthorizeStatus",
    "Challenge",
    "PaymentAdapter",
    "MockCardAdapter",
    "X402Adapter",
    "get_adapter",
]
