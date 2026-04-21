"""Per-identity sliding-window rate limiter for the MCP gateway.

Two tiers
---------
default   120 req / min  — catalog search, cart ops, order history
payment    20 req / min  — mandate build/sign, token mint, submit, challenge

Design notes
------------
* Pure in-process: one ``deque[float]`` of timestamps per (identity, tier).
  No external dependency needed for a single-process PoC.  For a
  multi-process / multi-instance deployment, swap ``_Window`` for a Redis
  ``ZADD`` + ``ZREMRANGEBYSCORE`` store.

* Identity is derived from the bearer token (SHA-256 hash, first 16 hex
  chars) so that each authenticated MCP client has its own budget.  Falls
  back to the client IP when no bearer is present — rate-limits anonymous
  probes by source address.

* The payment tool set is defined here (not in ``payment.py``) so the
  middleware can apply the tighter limit *before* the request reaches the
  tool handler — even a rejected payment call burns a payment-tier slot.

* ``BaseHTTPMiddleware`` buffers the request body before calling
  ``dispatch``, so ``await request.body()`` is safe here and the body is
  still available to downstream handlers unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


_LOG = logging.getLogger("ap2.mcp_gateway.rate_limit")

# ------------------------------------------------------------------ tiers

# Tools that touch money — get the tighter 20 req/min limit.
_PAYMENT_TOOLS: frozenset[str] = frozenset(
    {
        "submit_payment",
        "complete_challenge",
        "build_payment_mandate",
        "sign_payment_mandate",
        "create_merchant_on_file_token",
        "create_payment_credential_token",
        "finalize_cart",
    }
)


# ----------------------------------------------------------- sliding window

class _Window:
    """Thread-safe sliding-window counter for a single (identity, tier) pair."""

    __slots__ = ("limit", "window", "_ts", "_lock")

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._ts: Deque[float] = deque()
        self._lock = threading.Lock()

    def is_allowed(self) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after`` is the number of seconds until the *oldest* slot in
        the current window expires, giving the caller the earliest moment
        they can retry.
        """
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            # Evict timestamps that have scrolled out of the window.
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
            if len(self._ts) >= self.limit:
                retry_after = max(1, int(self._ts[0] - cutoff) + 1)
                return False, retry_after
            self._ts.append(now)
            return True, 0


# ------------------------------------------------------------- rate limiter

class RateLimiter:
    """Two-tier limiter — one ``_Window`` per ``(identity, tier)`` key.

    Instantiated once at module load (``_limiter`` below) and shared across
    all requests in the process.
    """

    def __init__(
        self,
        default_rpm: int = 120,
        payment_rpm: int = 20,
    ) -> None:
        self._default_rpm = default_rpm
        self._payment_rpm = payment_rpm
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def _get_window(self, key: str, rpm: int) -> _Window:
        with self._lock:
            if key not in self._windows:
                self._windows[key] = _Window(rpm)
            return self._windows[key]

    def check(
        self,
        identity: str,
        tool_name: str | None = None,
    ) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        Parameters
        ----------
        identity:
            A stable opaque key for the calling client (token hash, IP …).
        tool_name:
            The MCP tool being invoked.  ``None`` (e.g. ``initialize`` or
            ``tools/list``) falls through to the default tier.
        """
        if tool_name in _PAYMENT_TOOLS:
            rpm  = self._payment_rpm
            tier = "pay"
        else:
            rpm  = self._default_rpm
            tier = "def"
        return self._get_window(f"{identity}:{tier}", rpm).is_allowed()


# Module-level singleton — one shared limiter for the whole process.
_limiter = RateLimiter()


# ------------------------------------------------------ request helpers

def _identity_from_request(request: Request) -> str:
    """Derive a stable identity key without waiting for BearerAuthMiddleware.

    Uses the raw bearer token's SHA-256 hash so the key matches the one
    stored in sessions.  Falls back to the client IP for unauthenticated
    requests (rate-limits brute-force token guessing by source address).
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1].strip()
        return "tok:" + hashlib.sha256(token.encode()).hexdigest()[:16]
    client = request.client
    return "ip:" + (client.host if client else "unknown")


async def _extract_tool_name(request: Request) -> str | None:
    """Best-effort MCP JSON-RPC body parse to find the tool name.

    ``BaseHTTPMiddleware`` buffers the body before calling ``dispatch``, so
    this call is safe and the body remains available to downstream handlers.
    Returns ``None`` for any non-``tools/call`` or unparseable request.
    """
    try:
        body = await request.body()
        if not body:
            return None
        data = json.loads(body)
        if data.get("method") == "tools/call":
            return (data.get("params") or {}).get("name")
    except Exception:  # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------ middleware

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter — applies only to ``POST /mcp``.

    All other paths (``/healthz``, ``/.well-known/…``) are passed through
    without consuming any quota.

    On rejection the middleware returns HTTP 429 with a ``Retry-After``
    header so well-behaved clients can back off automatically.
    """

    async def dispatch(self, request: Request, call_next):
        # Only gate the MCP JSON-RPC endpoint; leave health / OAuth paths free.
        if not (request.url.path == "/mcp" and request.method == "POST"):
            return await call_next(request)

        identity  = _identity_from_request(request)
        tool_name = await _extract_tool_name(request)

        allowed, retry_after = _limiter.check(identity, tool_name)

        if not allowed:
            is_payment = tool_name in _PAYMENT_TOOLS
            _LOG.warning(
                "rate-limit exceeded  identity=%.20s  tool=%s  "
                "tier=%s  retry_after=%ds",
                identity,
                tool_name,
                "payment" if is_payment else "default",
                retry_after,
            )
            return JSONResponse(
                {
                    "error": "rate_limit_exceeded",
                    "detail": (
                        f"Too many {'payment ' if is_payment else ''}"
                        f"requests. Retry after {retry_after}s."
                    ),
                    "retry_after": retry_after,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
