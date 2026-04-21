"""Integration test for sign_mandates_on_user_device.

Verifies that the tool reads cart + payment mandates from ToolContext state,
produces a real ECDSA authorization, and writes it back to
PaymentMandate.user_authorization.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ap2.types.mandate import PaymentMandate
from roles.shopping_agent import tools
from roles.shopping_agent.crypto import MandateSigner


class _FakeToolContext:
    """Minimal stand-in for google.adk.tools.ToolContext.

    The real ToolContext exposes a .state dict-like; that's the only surface
    sign_mandates_on_user_device uses.
    """

    def __init__(self, state: dict) -> None:
        self.state = state


@pytest.fixture(autouse=True)
def _isolate_signer(tmp_signer):
    """Force the module-level signer to the tmp_path-backed test signer."""
    tools.set_mandate_signer(tmp_signer)
    yield
    tools.set_mandate_signer(None)


def test_tool_writes_real_signature(
    tmp_signer, cart_mandate, payment_mandate_contents
):
    payment_mandate = PaymentMandate(
        payment_mandate_contents=payment_mandate_contents,
    )
    ctx = _FakeToolContext(
        {"cart_mandate": cart_mandate, "payment_mandate": payment_mandate}
    )

    token = tools.sign_mandates_on_user_device(ctx)

    assert token, "sign_mandates_on_user_device must return a non-empty token"
    assert payment_mandate.user_authorization == token
    assert ctx.state["signed_payment_mandate"] is payment_mandate
    assert ctx.state["signer_did"] == tmp_signer.did

    # The token verifies under the test signer's public key.
    parsed = MandateSigner.verify_authorization(token, tmp_signer.public_key)
    assert parsed.cart_hash == MandateSigner.hash_object(cart_mandate)
    assert parsed.payment_contents_hash == MandateSigner.hash_object(
        payment_mandate_contents
    )


def test_tool_hash_helpers_are_real_sha256(cart_mandate, payment_mandate_contents):
    """_generate_*_hash no longer produce 'fake_' placeholder strings."""
    cart_hash = tools._generate_cart_mandate_hash(cart_mandate)
    pm_hash = tools._generate_payment_mandate_hash(payment_mandate_contents)
    assert len(cart_hash) == 64 and all(c in "0123456789abcdef" for c in cart_hash)
    assert len(pm_hash) == 64 and all(c in "0123456789abcdef" for c in pm_hash)
    assert not cart_hash.startswith("fake_")
    assert not pm_hash.startswith("fake_")
