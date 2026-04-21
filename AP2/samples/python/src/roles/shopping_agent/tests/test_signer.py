"""Tests for the ECDSA MandateSigner and did:key identity."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidSignature

from roles.shopping_agent.crypto import MandateSigner


def test_did_key_format(tmp_signer):
    """did:key strings start with 'did:key:z' and decode to 35 bytes."""
    import base58

    did = tmp_signer.did
    assert did.startswith("did:key:z")
    raw = base58.b58decode(did[len("did:key:z"):])
    # 2-byte p256-pub multicodec prefix + 33-byte compressed point.
    assert len(raw) == 35
    assert raw[:2] == b"\x80\x24"


def test_keypair_is_persistent(tmp_path):
    """A signer loads the same key from disk on a second construction."""
    key_path = tmp_path / "key.pem"
    first = MandateSigner.load_or_create(key_path)
    second = MandateSigner.load_or_create(key_path)
    assert first.did == second.did
    assert first.public_key_pem() == second.public_key_pem()


def test_sign_and_verify_roundtrip(tmp_signer, cart_mandate, payment_mandate_contents):
    """A signed authorization verifies against the signer's public key."""
    auth = tmp_signer.sign_mandate(cart_mandate, payment_mandate_contents)
    compact = auth.to_compact()

    parsed = MandateSigner.verify_authorization(compact, tmp_signer.public_key)
    assert parsed.signer_did == tmp_signer.did
    assert parsed.cart_hash == MandateSigner.hash_object(cart_mandate)
    assert parsed.payment_contents_hash == MandateSigner.hash_object(
        payment_mandate_contents
    )


def test_tampered_signature_rejected(
    tmp_signer, cart_mandate, payment_mandate_contents
):
    """Flipping a bit in the signature causes verification to fail."""
    auth = tmp_signer.sign_mandate(cart_mandate, payment_mandate_contents).to_compact()
    header, sig = auth.split(".", 1)
    # Flip a character in the signature; base64url alphabet is large, so any
    # swap with a different legal character corrupts the signature.
    tampered_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = f"{header}.{tampered_sig}"

    with pytest.raises(InvalidSignature):
        MandateSigner.verify_authorization(tampered, tmp_signer.public_key)


def test_tampered_header_rejected(
    tmp_signer, cart_mandate, payment_mandate_contents
):
    """Substituting a different header (e.g. different cart hash) fails."""
    import base64
    import json

    auth = tmp_signer.sign_mandate(cart_mandate, payment_mandate_contents)
    _, sig = auth.to_compact().split(".", 1)

    forged_header = {
        "cart_hash": "0" * 64,
        "payment_contents_hash": auth.payment_contents_hash,
        "nonce": auth.nonce,
        "signer_did": auth.signer_did,
    }
    forged_header_b64 = (
        base64.urlsafe_b64encode(json.dumps(forged_header, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(InvalidSignature):
        MandateSigner.verify_authorization(
            f"{forged_header_b64}.{sig}", tmp_signer.public_key
        )


def test_nonce_changes_each_call(tmp_signer, cart_mandate, payment_mandate_contents):
    """Signing the same inputs twice yields different nonces + signatures."""
    a = tmp_signer.sign_mandate(cart_mandate, payment_mandate_contents)
    b = tmp_signer.sign_mandate(cart_mandate, payment_mandate_contents)
    assert a.nonce != b.nonce
    assert a.signature_b64url != b.signature_b64url


def test_hash_object_accepts_pydantic_and_dict(cart_mandate):
    """hash_object yields identical digests for a model and its JSON dict."""
    direct = MandateSigner.hash_object(cart_mandate)
    via_dict = MandateSigner.hash_object(cart_mandate.model_dump(mode="json"))
    assert direct == via_dict
