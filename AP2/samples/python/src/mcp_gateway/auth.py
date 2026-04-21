"""Bearer-token auth for the streamable-HTTP transport.

Two modes, selected at runtime
-------------------------------
JWT mode  (set ``OAUTH_ISSUER``)
    Validates incoming bearer tokens as RS256-signed JWTs issued by Auth0
    (or any RFC 8414-compliant OAuth 2.1 server).

    ``PyJWKClient`` fetches the public JWKS once from
    ``{OAUTH_ISSUER}/.well-known/jwks.json`` and caches the key set for
    five minutes — so only the very first request (and occasional re-checks)
    hit the network.

    Validated claims:
      - ``exp``  token has not expired
      - ``iss``  matches ``OAUTH_ISSUER``
      - ``aud``  matches ``OAUTH_AUDIENCE``  (checked only when that env
                 var is set — allows omitting it for issuers that leave it
                 out, e.g. Auth0 M2M tokens for a single-audience tenant)

    The stable session key is derived from the ``sub`` claim (Auth0 sets
    this to ``<client_id>@clients`` for M2M tokens) so every distinct M2M
    application gets its own independent rate-limit and session bucket.

Static mode  (no ``OAUTH_ISSUER``)
    Falls back to the comma-separated ``MCP_TOKENS`` env var.  Useful for
    local dev without an Auth0 account.  Tokens never expire — rotate by
    redeploying.

Caller interface
----------------
Only ``check_bearer()`` and ``token_hash()`` are public.  Everything else
is an implementation detail.  The function is synchronous; the async
Starlette middleware in ``server.py`` calls it via
``asyncio.get_running_loop().run_in_executor(None, check_bearer, header)``
so the blocking JWKS HTTP fetch never stalls the event loop.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Iterable

_LOG = logging.getLogger("ap2.mcp_gateway.auth")


# ================================================================ JWKS client
# PyJWT[crypto] is already in pyproject.toml so this import should never fail
# in practice; the guard keeps unit-test environments happy.
try:
    import jwt
    from jwt import InvalidTokenError, PyJWKClient
    _JWT_OK = True
except ImportError:  # pragma: no cover
    _JWT_OK = False
    _LOG.warning("pyjwt[crypto] not importable — JWT mode unavailable")

# One PyJWKClient per issuer URL, shared across all requests in the process.
_JWKS_CLIENTS: dict[str, "PyJWKClient"] = {}


def _jwks_client(issuer: str) -> "PyJWKClient":
    """Return (or create) a cached PyJWKClient for *issuer*."""
    key = issuer.rstrip("/")
    if key not in _JWKS_CLIENTS:
        jwks_uri = key + "/.well-known/jwks.json"
        _LOG.info("initialising JWKS client for %s", jwks_uri)
        _JWKS_CLIENTS[key] = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,          # re-fetch JWKS at most every 5 minutes
            timeout=10,
        )
    return _JWKS_CLIENTS[key]


# ============================================================= public helpers

def token_hash(token: str) -> str:
    """Stable 32-hex-char hash for binding sessions without storing the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _identity_hash(subject: str) -> str:
    """Map an OAuth ``sub`` (or raw token) to a 32-char session key."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]


# ============================================================ JWT validation

def _validate_jwt(token: str) -> str:
    """Validate *token* as a signed JWT; return the stable identity hash.

    Raises ``PermissionError`` on any validation failure so the caller can
    return HTTP 401 without leaking internal exception details.
    """
    if not _JWT_OK:
        raise PermissionError("pyjwt[crypto] not installed; JWT mode unavailable")

    issuer = (os.environ.get("OAUTH_ISSUER") or "").rstrip("/")
    if not issuer:
        raise PermissionError("OAUTH_ISSUER not configured")

    audience = (os.environ.get("OAUTH_AUDIENCE") or "").strip() or None

    try:
        client      = _jwks_client(issuer)
        signing_key = client.get_signing_key_from_jwt(token)
        payload     = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            # Auth0 appends a trailing slash to the issuer in the iss claim.
            issuer=issuer + "/",
            audience=audience,
            options={
                "require":    ["exp", "iat", "iss"],
                "verify_exp": True,
                "verify_aud": audience is not None,
            },
        )
    except Exception as exc:  # noqa: BLE001  — map all jwt errors to 401
        _LOG.warning("JWT validation failed: %s", exc)
        raise PermissionError(f"JWT validation failed: {exc}") from exc

    # Use the subject claim as the session identity (Auth0 M2M → "<cid>@clients").
    subject = payload.get("sub") or token
    _LOG.debug("JWT accepted: sub=%s exp=%s", subject, payload.get("exp"))
    return _identity_hash(subject)


# =========================================================== static fallback

def _load_static_tokens() -> set[str]:
    raw = os.environ.get("MCP_TOKENS", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


# ================================================================ public API

def auth_mode() -> str:
    """Return ``'jwt'`` when OAUTH_ISSUER is set, else ``'static'``."""
    return "jwt" if os.environ.get("OAUTH_ISSUER") else "static"


def check_bearer(
    authorization_header: str | None,
    *,
    allow_anonymous: bool = False,
    valid_tokens: Iterable[str] | None = None,
) -> str | None:
    """Validate a bearer token; return the stable identity hash on success.

    Parameters
    ----------
    authorization_header:
        Raw ``Authorization`` header value from the HTTP request.
    allow_anonymous:
        When ``True``, missing / invalid tokens return ``None`` instead of
        raising — used by the stdio transport which runs in a trusted
        process context.
    valid_tokens:
        Override the env-loaded static token set.  Only consulted in static
        mode; ignored when ``OAUTH_ISSUER`` is set.  Primarily for tests.

    Returns
    -------
    str or None
        A 32-hex-char identity hash, or ``None`` if ``allow_anonymous`` and
        no credentials were provided.

    Raises
    ------
    PermissionError
        On any authentication failure (missing token, invalid signature,
        expired JWT, unknown static token, …).
    """
    # --- extract the raw token string ---
    if not authorization_header or not authorization_header.lower().startswith("bearer "):
        if allow_anonymous:
            return None
        raise PermissionError("missing bearer token")

    presented = authorization_header.split(None, 1)[1].strip()

    # --- JWT mode ---
    if os.environ.get("OAUTH_ISSUER"):
        return _validate_jwt(presented)

    # --- static mode ---
    tokens = set(valid_tokens) if valid_tokens is not None else _load_static_tokens()
    if not tokens:
        if allow_anonymous:
            return None
        raise PermissionError(
            "no tokens configured — set MCP_TOKENS (static mode) or "
            "OAUTH_ISSUER (JWT mode)"
        )
    if presented not in tokens:
        _LOG.warning("rejected unknown static bearer (hash=%s)", token_hash(presented))
        raise PermissionError("invalid bearer token")
    return token_hash(presented)
