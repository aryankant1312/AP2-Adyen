"""Key management + JWT signing utilities shared across roles.

Two primary helpers:

  * :func:`merchant_authorization_jwt` — RS256-signs a CartMandate's
    contents and returns the JWT to be stamped into
    ``cart_mandate.merchant_authorization``. Replaces the legacy
    ``_FAKE_JWT`` placeholder.
  * :func:`verify_merchant_jwt` — counterpart for downstream agents
    (MPP, gateway tests).

Keys are auto-generated under ``keys/`` on first use if not present —
that's a dev convenience; production deployments must supply real keys
via the ``MERCHANT_PRIVATE_KEY_PATH`` env var.
"""

from .keys import (
    ensure_ec_key,
    ensure_rsa_key,
    load_private_key,
    load_public_key,
)
from .merchant_jwt import (
    merchant_authorization_jwt,
    serve_public_key_pem,
    verify_merchant_jwt,
)

__all__ = [
    "ensure_ec_key",
    "ensure_rsa_key",
    "load_private_key",
    "load_public_key",
    "merchant_authorization_jwt",
    "serve_public_key_pem",
    "verify_merchant_jwt",
]
