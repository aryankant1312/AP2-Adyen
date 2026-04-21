"""did:key encoding for a P-256 ECDSA public key.

Implements the W3C did:key method for the `p256` (secp256r1) curve:

    did:key:z<base58btc( 0x80 0x24 || compressed_public_key )>

where `0x80 0x24` is the varint-encoded multicodec identifier for p256-pub
(code 0x1200).

Reference: https://w3c-ccg.github.io/did-method-key/
"""

from __future__ import annotations

import base58
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

# Multicodec varint for p256-pub (0x1200 -> varint 0x80, 0x24).
_P256_MULTICODEC_PREFIX = b"\x80\x24"


def public_key_to_did_key(public_key: ec.EllipticCurvePublicKey) -> str:
    """Return the did:key string for a P-256 public key.

    The public key is serialized in compressed SEC1 form (33 bytes), prefixed
    with the p256-pub multicodec header, and base58btc encoded with a leading
    "z" multibase prefix.
    """
    if not isinstance(public_key.curve, ec.SECP256R1):
        raise ValueError(
            f"public_key must use SECP256R1 curve, got {public_key.curve.name!r}"
        )
    compressed = public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.CompressedPoint,
    )
    multicodec_bytes = _P256_MULTICODEC_PREFIX + compressed
    return "did:key:z" + base58.b58encode(multicodec_bytes).decode("ascii")
