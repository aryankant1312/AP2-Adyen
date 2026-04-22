"""Register every ``ui://`` HTML template as an MCP resource."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from . import TEMPLATE_INDEX

_LOG = logging.getLogger("ap2.mcp_gateway.ui")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _boots_logo_data_url() -> str:
    p = _TEMPLATES_DIR / "_boots_logo.png"
    if not p.exists():
        return ""
    return ("data:image/png;base64,"
            + base64.b64encode(p.read_bytes()).decode("ascii"))


_BOOTS_LOGO_DATA_URL = _boots_logo_data_url()


# Short human descriptions ChatGPT exposes in the connector inspector.
_WIDGET_DESCRIPTIONS: dict[str, str] = {
    "ui://product_grid":       "Inline grid of pharmacy products with add-to-cart buttons.",
    "ui://cart":               "Cart sidebar with line items, totals and a checkout button.",
    "ui://mof_picker":         "Saved-card picker with brand art and last-4 labels.",
    "ui://receipt":            "Order receipt with totals, line items and PSP reference.",
    "ui://new_card":           "Inline Adyen Web Drop-in for new card, PayPal, Klarna and 3DS2.",
    "ui://payment_processing": "Processing / 3DS-challenge spinner that polls the payment session.",
}


# Default CSP — most widgets render fully from the structuredContent
# payload and make no outbound network calls.
_DEFAULT_CSP: dict[str, list[str]] = {
    "connect_domains":  [],
    "resource_domains": [],
}

# Adyen Web Drop-in needs to load its JS + CSS bundle from Adyen's
# checkout-shopper CDN and POST back to the Sessions endpoint. The host
# pattern is the same for test and live; we whitelist both subdomains so
# the same widget works in both environments without a rebuild.
_ADYEN_DROPIN_CSP: dict[str, list[str]] = {
    "connect_domains": [
        "https://checkoutshopper-test.adyen.com",
        "https://checkoutshopper-live.adyen.com",
        "https://checkout-test.adyen.com",
        "https://checkout-live.adyen.com",
        # Drop-in occasionally issues analytics beacons through these
        # regional subdomains; listing them keeps the iframe quiet.
        "https://checkoutshopper-live-us.adyen.com",
        "https://checkoutshopper-live-au.adyen.com",
    ],
    "resource_domains": [
        "https://checkoutshopper-test.adyen.com",
        "https://checkoutshopper-live.adyen.com",
        # PayPal / Google Pay / Apple Pay / Klarna hosted scripts that
        # Drop-in can pull in when those APMs are enabled on the merchant
        # account. Safe to list even if the APMs are not configured —
        # Drop-in simply won't reference them.
        "https://www.paypalobjects.com",
        "https://pay.google.com",
        "https://appleid.cdn-apple.com",
        "https://x.klarnacdn.net",
    ],
}


_WIDGET_CSP_OVERRIDES: dict[str, dict[str, list[str]]] = {
    "ui://new_card": _ADYEN_DROPIN_CSP,
    # The processing spinner only re-renders via toolOutput — it does NOT
    # need network access. Keep it on the default CSP.
}


def _load(name: str) -> str:
    p = _TEMPLATES_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"missing widget template: {p}")
    return p.read_text(encoding="utf-8")


def register_resources(mcp) -> None:
    """Bind each template under its ``ui://`` URI on the given FastMCP.

    FastMCP's ``@mcp.resource(uri, mime_type=..., meta=...)`` decorator
    wires a function to a static MCP resource read AND attaches the
    given ``_meta`` to the resource descriptor returned in
    ``resources/list`` — that's the slot ChatGPT inspects when deciding
    how to render the widget (CSP, description, border preference).
    """
    # Snapshot once so the closures don't all reference the loop var.
    items = list(TEMPLATE_INDEX.items())

    for uri, (filename, mime) in items:
        html = _load(filename).replace(
            "{{BOOTS_LOGO_DATA_URL}}", _BOOTS_LOGO_DATA_URL)

        meta = {
            # Self-reference — Apps SDK uses this to bind a resource to
            # its own outputTemplate slot.
            "openai/outputTemplate":      uri,
            "openai/widgetDescription":   _WIDGET_DESCRIPTIONS.get(uri, ""),
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP":           _WIDGET_CSP_OVERRIDES.get(
                uri, _DEFAULT_CSP),
        }

        # Need a unique function per registration → build via closure factory.
        def _make_handler(_html: str):
            def _handler() -> str:
                return _html
            return _handler

        handler = _make_handler(html)
        handler.__name__ = (
            "widget_" + uri.replace("ui://", "").replace("/", "_")
        )
        mcp.resource(uri, mime_type=mime, meta=meta)(handler)
        _LOG.info("registered widget resource %s (%s, %d bytes, meta=%s)",
                  uri, mime, len(html), sorted(meta.keys()))
