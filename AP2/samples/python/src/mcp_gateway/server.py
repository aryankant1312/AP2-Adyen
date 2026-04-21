"""FastMCP server wiring — registers every tool group on a single MCP.

Two HTTP entry shapes:
  * ``build_mcp()``      — the bare FastMCP instance (used by stdio).
  * ``build_http_app()`` — wraps ``mcp.streamable_http_app()`` in a
    Starlette app that adds:
      - bearer-token auth gate (``/mcp`` and any non-public path)
      - per-identity sliding-window rate limiter (``/mcp`` only)
      - security response headers on every reply (CSP, X-Frame-Options …)
      - ``/healthz`` (unauth, plain JSON)
      - ``/.well-known/oauth-protected-resource`` (unauth, OAuth discovery
        stub used by ChatGPT developer-mode connectors).

Middleware execution order (outermost → innermost, i.e. first for requests):
  SecurityHeadersMiddleware  — always stamps headers onto the response
  RateLimitMiddleware        — enforces per-identity request budgets
  BearerAuthMiddleware       — rejects missing/invalid bearer tokens
  Routes                     — tool handlers, health, OAuth discovery
"""

from __future__ import annotations

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import auth as _auth
from . import adyen_checkout as _adyen
from .rate_limit import RateLimitMiddleware
from .tools import (
    cart as cart_tools,
    catalog as catalog_tools,
    history as history_tools,
    payment as payment_tools,
    payment_methods as payment_method_tools,
)
from .ui import register_resources as _register_ui_resources


_LOG = logging.getLogger("ap2.mcp_gateway.server")


# --------------------------------------------------------------------- MCP

def build_mcp(name: str = "ap2-pharmacy") -> FastMCP:
    """Construct a configured FastMCP instance.

    DNS-rebinding host validation is disabled because the gateway is
    designed to be reached through varying hostnames (localhost, LAN IP,
    cloudflared/ngrok subdomains, custom domains). Bearer-token auth in
    ``BearerAuthMiddleware`` is the real security gate; rejecting on
    Host header alone would block every public-tunnel demo.
    """
    mcp = FastMCP(
        name,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    catalog_tools.register(mcp)
    cart_tools.register(mcp)
    payment_method_tools.register(mcp)
    payment_tools.register(mcp)
    history_tools.register(mcp)
    _register_ui_resources(mcp)
    _LOG.info("registered MCP tool groups: catalog, cart, payment_methods, "
              "payment, history; ui resources mounted")
    return mcp


# --------------------------------------------------------------------- HTTP

# Paths that bypass bearer-auth. The OAuth discovery doc lets ChatGPT's
# developer-mode connector probe us before the user has typed a token.
_PUBLIC_PATHS: tuple[str, ...] = (
    "/healthz",
    "/.well-known/oauth-protected-resource",
    # Adyen Drop-in + webhook routes: the shopper's browser and Adyen's
    # servers have no bearer token — the session_id itself is the capability.
    *_adyen.PUBLIC_PATH_PREFIXES,
)


def _auth_required() -> bool:
    """Honour ``MCP_REQUIRE_AUTH=true|1|yes`` to enable the bearer gate.

    Default is OFF so ChatGPT developer-mode connectors (whose UI only
    offers ``OAuth / Mixed / No auth`` — no plain bearer field) work
    out-of-the-box. Flip it on in .env for deployments where the URL is
    the only shared secret and you want belt-and-braces bearer auth.
    """
    val = (os.environ.get("MCP_REQUIRE_AUTH") or "false").strip().lower()
    return val in ("1", "true", "yes", "on")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid ``Authorization: Bearer …`` header.

    Lets ``OPTIONS`` (CORS preflight) and the public paths above through
    untouched. On success, stashes the token-hash on ``request.state`` so
    downstream code (e.g. ``session.py``) can bind sessions to a bearer
    without ever holding the token itself.

    Globally disabled by ``MCP_REQUIRE_AUTH=false`` — used for connector
    UIs (notably ChatGPT developer mode) that don't expose a bearer
    field. The trycloudflare URL acts as the (weak) shared secret in
    that case; do not flip auth off for production traffic.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if any(request.url.path == p or request.url.path.startswith(p + "/")
               for p in _PUBLIC_PATHS):
            return await call_next(request)
        if not _auth_required():
            request.state.token_hash = "anonymous"
            return await call_next(request)
        try:
            # Run in a thread-pool executor: in JWT mode check_bearer calls
            # PyJWKClient.get_signing_key_from_jwt() which uses blocking I/O
            # (urllib) to fetch the JWKS on first use. After the key is
            # cached the call is effectively instant, but we always offload
            # to avoid ever blocking the event loop.
            loop = asyncio.get_running_loop()
            th   = await loop.run_in_executor(
                None, _auth.check_bearer,
                request.headers.get("authorization"),
            )
        except PermissionError as exc:
            _LOG.warning("auth rejected %s %s: %s",
                         request.method, request.url.path, exc)
            return JSONResponse(
                {"error": "unauthorized", "detail": str(exc)},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="ap2-pharmacy"'},
            )
        request.state.token_hash = th
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp security-relevant HTTP headers onto every response.

    Content-Security-Policy: frame-ancestors 'none'
        Prevents any third-party page from embedding this server inside an
        <iframe>.  The /mcp JSON-RPC surface must never be iframeable —
        that is the primary clickjacking / phishing vector the header guards
        against.  Widget HTML is returned *inside* MCP responses and is
        sandboxed by the client host (e.g. ChatGPT), not via a raw
        <iframe src=URL>, so 'none' is the correct value here.

    X-Frame-Options: DENY
        Legacy complement to frame-ancestors for older browsers that do not
        honour the CSP directive.

    X-Content-Type-Options: nosniff
        Stops browsers from MIME-sniffing a response away from the declared
        Content-Type — prevents a crafted payload from being executed as
        script.

    Referrer-Policy: strict-origin-when-cross-origin
        Limits the Referer header to the origin (no path) on cross-origin
        requests so internal paths / session IDs are not leaked.
    """

    _HEADERS: dict[str, str] = {
        "Content-Security-Policy":   "frame-ancestors 'none'",
        "X-Frame-Options":           "DENY",
        "X-Content-Type-Options":    "nosniff",
        "Referrer-Policy":           "strict-origin-when-cross-origin",
    }

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.update(self._HEADERS)
        return response


async def _healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok",
                         "service": "ap2-mcp-gateway"})


async def _oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 OAuth Protected Resource Metadata.

    When ``OAUTH_ISSUER`` is set the document advertises the real Auth0
    authorization server so that MCP clients (Claude Desktop, ChatGPT
    connector) can auto-discover the token endpoint and perform the
    OAuth 2.1 flow without manual configuration.

    When ``OAUTH_ISSUER`` is not set the document is a minimal stub
    (``authorization_servers: []``) that is sufficient for clients that
    only check for the existence of the endpoint.
    """
    base   = str(request.base_url).rstrip("/")
    issuer = (os.environ.get("OAUTH_ISSUER") or "").rstrip("/")

    # Auth0 publishes its authorization-server metadata at the issuer URL.
    # MCP clients follow the chain:
    #   /.well-known/oauth-protected-resource
    #       → authorization_servers[0]
    #           → /.well-known/oauth-authorization-server  (RFC 8414)
    #               → token_endpoint, jwks_uri, …
    auth_servers = [issuer + "/"] if issuer else []

    return JSONResponse({
        "resource":                   base,
        "authorization_servers":      auth_servers,
        "bearer_methods_supported":   ["header"],
        "scopes_supported":           ["mcp:tools"],
    })


def build_http_app(mcp: FastMCP) -> Starlette:
    """Return a Starlette ASGI app exposing ``/mcp`` (gated) +
    ``/healthz`` + ``/.well-known/oauth-protected-resource``.
    """
    # FastMCP already returns a Starlette app rooted at ``/mcp``; we
    # piggy-back on it so we don't have to re-mount the streamable
    # transport ourselves.
    app: Starlette = mcp.streamable_http_app()

    # Add public routes alongside the MCP route.
    app.router.routes.extend([
        Route("/healthz", _healthz, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource",
              _oauth_protected_resource, methods=["GET"]),
        *_adyen.routes(),
    ])

    # Middleware is added via add_middleware() which *prepends* each entry,
    # so the last call here becomes the outermost wrapper (first to handle
    # a request, last to touch the response).
    #
    # Desired request-processing order:
    #   SecurityHeaders → RateLimit → BearerAuth → Routes
    #
    # Therefore add_middleware call order is innermost first:

    # 1. BearerAuth — validates the token and gates unauthorised requests.
    app.add_middleware(BearerAuthMiddleware)

    # 2. RateLimit — throttles per authenticated identity.
    #    Runs before BearerAuth for requests (so bad tokens also burn
    #    rate-limit budget, preventing token brute-force) but derives the
    #    identity key directly from the Authorization header — it does not
    #    depend on BearerAuth having run first.
    app.add_middleware(RateLimitMiddleware)

    # 3. SecurityHeaders — stamps CSP / X-Frame-Options / nosniff headers
    #    onto every response regardless of path or auth outcome.
    app.add_middleware(SecurityHeadersMiddleware)

    # Startup log.
    mode     = _auth.auth_mode()
    n_static = len({t for t in (os.environ.get("MCP_TOKENS") or "")
                    .split(",") if t.strip()})
    issuer   = (os.environ.get("OAUTH_ISSUER") or "").rstrip("/") or None

    if _auth_required():
        if mode == "jwt":
            _LOG.info(
                "HTTP transport ready: /mcp BEARER-GATED [JWT/OAuth2.1], "
                "issuer=%s, rate-limit 120/20 rpm, CSP frame-ancestors none",
                issuer,
            )
        else:
            _LOG.info(
                "HTTP transport ready: /mcp BEARER-GATED [static, %d token(s)], "
                "rate-limit 120/20 rpm, CSP frame-ancestors none",
                n_static,
            )
    else:
        _LOG.warning(
            "HTTP transport ready: /mcp OPEN (MCP_REQUIRE_AUTH=false) [%s mode], "
            "rate-limit 120/20 rpm, CSP frame-ancestors none — "
            "anyone with the URL can call tools.",
            mode,
        )
    return app
