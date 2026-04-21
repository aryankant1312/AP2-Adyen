"""Tiny launcher for the three AP2 backend agents.

Usage:
    python ops/run_agents.py merchant   # MA on :8001
    python ops/run_agents.py cp         # CP on :8002
    python ops/run_agents.py mpp        # MPP on :8003

Each role has its own ``__main__.py``; this just sets the env vars they
expect, fixes up sys.path, and re-enters that module's ``main`` via
``absl.app.run``. Sensible defaults — explicit env wins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_SRC  = _REPO / "samples" / "python" / "src"

sys.path.insert(0, str(_SRC))

# Shared env. The Gemini key is required by base_server_executor's
# `genai.Client()`; defaulting to the dev key the user provided so the
# stack boots without manual env work.
os.environ.setdefault("GOOGLE_API_KEY",
                      "AIzaSyAVwlH7aOeZf0355_z_K0JdeGfgqsEOark")
os.environ.setdefault("GEMINI_API_KEY",
                      os.environ["GOOGLE_API_KEY"])
os.environ.setdefault("PSP_ADAPTER", "mock")
os.environ.setdefault(
    "PHARMACY_DB", str(_REPO / "data" / "pharmacy.sqlite"))
os.environ.setdefault(
    "MERCHANT_PRIVATE_KEY_PATH",
    str(_REPO / "keys" / "merchant_private.pem"))
os.environ.setdefault(
    "SHOPPER_KEY_PATH",
    str(_REPO / "keys" / "shopper_key.pem"))
os.environ.setdefault("KNOWN_SHOPPING_AGENTS", "ap2_mcp_gateway")

# Also let the MPP find the CP for AP2 dynamic credential exchange.
os.environ.setdefault(
    "CREDENTIALS_PROVIDER_AGENT_URL",
    "http://127.0.0.1:8002/a2a/credentials_provider")


_ROLES: dict[str, tuple[str, int]] = {
    "merchant": ("roles.merchant_agent.__main__", 8001),
    "cp":       ("roles.credentials_provider_agent.__main__", 8002),
    "mpp":      ("roles.merchant_payment_processor_agent.__main__", 8003),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in _ROLES:
        print(f"usage: {sys.argv[0]} {{{'|'.join(_ROLES)}}}",
              file=sys.stderr)
        return 2
    role = sys.argv[1]
    module, port = _ROLES[role]
    os.environ["PORT"] = str(port)

    # absl.app.run reads sys.argv; replace with a single program-name slot
    # so it doesn't try to consume our own positional argument.
    sys.argv = [sys.argv[0]]

    import importlib
    mod = importlib.import_module(module)
    from absl import app
    app.run(mod.main)
    return 0


if __name__ == "__main__":
    sys.exit(main())
