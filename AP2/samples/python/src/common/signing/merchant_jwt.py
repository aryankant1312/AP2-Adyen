"""RS256-signed merchant_authorization JWT for CartMandate.

Replaces the legacy ``_FAKE_JWT`` placeholder. The catalog agent should
call :func:`merchant_authorization_jwt(cart_mandate_contents)` and stamp
the returned JWT into ``cart_mandate.merchant_authorization`` before
emitting the artifact.

The MA exposes the matching public key at ``/.well-known/merchant-key.pem``
via :func:`serve_public_key_pem` (a Starlette route factory) — every
downstream consumer (MPP, gateway tests) verifies signatures against it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization

from .keys import ensure_rsa_key, load_private_key


_LOG = logging.getLogger("ap2.common.signing.merchant_jwt")

_DEFAULT_KEY_PATH = "keys/merchant_private.pem"
_DEFAULT_KID      = "merchant-poc-key-1"


def _key_path() -> Path:
    return Path(os.environ.get("MERCHANT_PRIVATE_KEY_PATH",
                                _DEFAULT_KEY_PATH))


def _kid() -> str:
    return os.environ.get("MERCHANT_JWT_KID", _DEFAULT_KID)


def _issuer() -> str:
    return os.environ.get("MERCHANT_JWT_ISS", "merchant_agent")


def merchant_authorization_jwt(cart_mandate_contents: dict[str, Any],
                                *,
                                ttl_seconds: int = 1800,
                                audience: str = "ap2-payment-mandate") -> str:
    """Sign the canonical hash of CartMandate contents with RS256.

    The JWT carries a hash, not the whole contents, so the resulting
    token stays small while still binding the mandate end-to-end.
    """
    canonical = json.dumps(cart_mandate_contents, sort_keys=True,
                            separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()

    now = int(time.time())
    claims = {
        "iss":  _issuer(),
        "aud":  audience,
        "iat":  now,
        "exp":  now + ttl_seconds,
        "jti":  uuid.uuid4().hex,
        "cart_mandate_sha256": digest,
        "cart_id": cart_mandate_contents.get("payment_request", {})
                                          .get("details", {})
                                          .get("id"),
    }
    ensure_rsa_key(_key_path())
    priv = load_private_key(_key_path())
    return jwt.encode(claims, priv, algorithm="RS256",
                       headers={"kid": _kid(), "typ": "JWT"})


def verify_merchant_jwt(token: str,
                         *,
                         public_key_pem: bytes | None = None,
                         expected_audience: str = "ap2-payment-mandate"
                         ) -> dict[str, Any]:
    """Verify an RS256 JWT and return its claims."""
    if public_key_pem is None:
        ensure_rsa_key(_key_path())
        priv = load_private_key(_key_path())
        public_key_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    return jwt.decode(token, public_key_pem, algorithms=["RS256"],
                       audience=expected_audience,
                       issuer=_issuer())


def serve_public_key_pem():
    """Return a Starlette route handler for ``/.well-known/merchant-key.pem``.

    Mount from the merchant agent's ASGI app::

        from common.signing import serve_public_key_pem
        from starlette.routing import Route
        asgi.routes.append(
            Route("/.well-known/merchant-key.pem",
                  serve_public_key_pem(), methods=["GET"]),
        )
    """
    from starlette.responses import Response

    async def handler(request):
        ensure_rsa_key(_key_path())
        priv = load_private_key(_key_path())
        pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return Response(content=pem, media_type="application/x-pem-file")

    return handler
