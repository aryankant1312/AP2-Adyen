"""Shared pytest fixtures for shopping_agent tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from roles.shopping_agent.crypto import MandateSigner


@pytest.fixture
def tmp_signer(tmp_path: Path) -> MandateSigner:
    """A MandateSigner backed by a throw-away PEM under tmp_path."""
    return MandateSigner.load_or_create(tmp_path / "shopper_key.pem")


@pytest.fixture
def cart_mandate():
    """A minimal but spec-valid CartMandate fixture."""
    from ap2.types.mandate import CartContents, CartMandate
    from ap2.types.payment_request import (
        PaymentCurrencyAmount,
        PaymentDetailsInit,
        PaymentItem,
        PaymentMethodData,
        PaymentRequest,
    )

    total = PaymentItem(
        label="Total",
        amount=PaymentCurrencyAmount(currency="USD", value=129.99),
    )
    payment_request = PaymentRequest(
        method_data=[PaymentMethodData(supported_methods="CARD", data={})],
        details=PaymentDetailsInit(
            id="req-001",
            display_items=[total],
            total=total,
        ),
    )
    contents = CartContents(
        id="cart-001",
        user_cart_confirmation_required=True,
        payment_request=payment_request,
        cart_expiry="2099-01-01T00:00:00Z",
        merchant_name="Test Merchant",
    )
    return CartMandate(
        contents=contents,
        merchant_authorization="eyJhbGciOiJFUzI1NiJ9.merchant_signed",
    )


@pytest.fixture
def payment_mandate_contents(cart_mandate):
    """A PaymentMandateContents fixture bound to the cart fixture."""
    from ap2.types.contact_picker import ContactAddress
    from ap2.types.mandate import PaymentMandateContents
    from ap2.types.payment_request import PaymentResponse

    payment_request = cart_mandate.contents.payment_request
    return PaymentMandateContents(
        payment_mandate_id="pm-001",
        payment_details_id=payment_request.details.id,
        payment_details_total=payment_request.details.display_items[0],
        payment_response=PaymentResponse(
            request_id=payment_request.details.id,
            method_name="CARD",
            details={"token": "tok_abc"},
            shipping_address=ContactAddress(
                city="San Francisco",
                country="US",
                postal_code="94103",
                recipient="Test User",
                address_line=["1 Market St"],
                region="CA",
            ),
            payer_email="user@example.com",
        ),
        merchant_agent="Test Merchant",
    )
