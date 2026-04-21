"""Tiny launcher: set the env vars our local-dev gateway expects, then
re-enter ``python -m mcp_gateway --http 0.0.0.0:8080 -v``.

Used by the smoke harness on Windows where chained ``set VAR=...``
commands in cmd-/-bash don't always survive the call boundary. Safe to
re-run; environment values default to the canonical local-dev ports.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_SRC  = _REPO / "samples" / "python" / "src"

# Make the gateway + helper packages importable.
sys.path.insert(0, str(_SRC))


def _load_dotenv(path: Path) -> None:
    """Tiny KEY=VALUE loader (no python-dotenv dep). Existing env wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


# Source ops/envs/.env first so its MCP_TOKENS / PSP_ADAPTER values become
# the defaults; anything already in os.environ still wins.
_load_dotenv(_HERE / "envs" / ".env")

# Sensible local-dev defaults; explicit overrides win.
# OAuth 2.1 / Auth0 — empty by default so the gateway starts in static mode.
# Populate OAUTH_ISSUER + OAUTH_AUDIENCE in ops/envs/.env to switch to JWT mode.
os.environ.setdefault("OAUTH_ISSUER",   "")
os.environ.setdefault("OAUTH_AUDIENCE", "")
os.environ.setdefault("MCP_TOKENS",
                      "dev-token-please-change")
os.environ.setdefault("MERCHANT_AGENT_URL",
                      "http://127.0.0.1:8001")
os.environ.setdefault("CREDENTIALS_PROVIDER_URL",
                      "http://127.0.0.1:8002")
os.environ.setdefault("MERCHANT_PAYMENT_PROCESSOR_URL",
                      "http://127.0.0.1:8003")
os.environ.setdefault("PSP_ADAPTER", "mock")
os.environ.setdefault(
    "PHARMACY_DB", str(_REPO / "data" / "pharmacy.sqlite"))
os.environ.setdefault(
    "MERCHANT_PRIVATE_KEY_PATH",
    str(_REPO / "keys" / "merchant_private.pem"))
os.environ.setdefault(
    "SHOPPER_KEY_PATH",
    str(_REPO / "keys" / "shopper_key.pem"))


def main() -> int:
    from mcp_gateway.__main__ import main as _gateway_main
    argv = sys.argv[1:] or ["--http", "0.0.0.0:8080", "-v"]
    return _gateway_main(argv) or 0


if __name__ == "__main__":
    sys.exit(main())
