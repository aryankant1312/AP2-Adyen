"""ChatGPT Apps SDK / MCP-UI widget templates.

Each ``ui://<name>`` resource is a self-contained HTML document the
ChatGPT developer-mode connector loads into a sandboxed iframe. The
iframe reads its data from ``window.openai.toolOutput`` (the
``structuredContent`` payload our tool returned) and fires
``window.openai.callTool(name, args)`` for in-widget actions.

Claude Desktop / claude.ai do not currently render these widgets; the
plain ``content`` part on the same tool result (a JSON dump) is the
visual fallback there. We keep both populated so we don't fork the
server.
"""

from __future__ import annotations

import json
from typing import Any

# Stable URIs the tool layer references via ``_meta["openai/outputTemplate"]``.
PRODUCT_GRID_URI = "ui://product_grid"
CART_URI         = "ui://cart"
MOF_PICKER_URI   = "ui://mof_picker"
RECEIPT_URI      = "ui://receipt"


def widget_meta(ui_uri: str,
                *,
                widget_accessible: bool = True,
                invoking: str | None = None,
                invoked: str | None = None,
                ) -> dict[str, Any]:
    """The ``_meta`` block that pins a tool (or response) to a widget.

    ChatGPT's Apps SDK inspects ``_meta`` on the **tool descriptor**
    returned from ``tools/list`` when deciding whether to render an
    iframe — not on the per-call response. Anything we want ChatGPT to
    notice at connector-discovery time has to flow through ``meta=`` on
    ``@mcp.tool(...)``.

    We also embed the same dict on every response (defensive — keeps
    the wire payload self-describing for clients that look at either
    place).
    """
    meta: dict[str, Any] = {"openai/outputTemplate": ui_uri}
    if widget_accessible:
        meta["openai/widgetAccessible"] = True
    if invoking:
        meta["openai/toolInvocation/invoking"] = invoking
    if invoked:
        meta["openai/toolInvocation/invoked"] = invoked
    return meta


def widget_result(payload: Any,
                  *,
                  ui_uri: str,
                  widget_accessible: bool = True,
                  ) -> Any:
    """Build a ``CallToolResult`` carrying both the widget envelope
    (for ChatGPT developer-mode iframes) and a plain-text JSON content
    block (for Claude / debug clients that don't render widgets).

    ``payload`` is the JSON-serialisable shape the iframe will read off
    ``window.openai.toolOutput``. We deliberately do NOT wrap it under
    a ``{"result": ...}`` key — both the iframe scripts AND the smoke
    test assume the full payload is at the root.

    NOTE: ChatGPT primarily honours the matching ``_meta`` on the **tool
    descriptor** (see ``widget_meta`` + each tool's ``@mcp.tool(meta=)``
    registration). We still emit ``_meta`` on the response itself as a
    belt-and-braces signal — clients that inspect either location will
    pick it up.
    """
    # Lazy import so ``mcp_gateway.ui`` itself stays import-cheap.
    from mcp.types import CallToolResult, TextContent

    text = json.dumps(payload, separators=(",", ":"), default=str)

    meta = widget_meta(ui_uri, widget_accessible=widget_accessible)

    structured: dict[str, Any]
    if isinstance(payload, dict):
        structured = payload
    else:
        # MCP requires structuredContent to be an object (dict). When
        # the natural payload is a list we wrap it under a stable key
        # the widget JS already understands.
        structured = {"items": payload}

    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=structured,
        _meta=meta,
    )

# Mapping: URI → (template-filename, mime-type). The MIME is what
# ChatGPT looks for when deciding to render the iframe; Claude treats
# unknown subtypes as ``text/html`` and ignores the template — harmless.
TEMPLATE_INDEX: dict[str, tuple[str, str]] = {
    PRODUCT_GRID_URI: ("product_grid.html", "text/html+skybridge"),
    CART_URI:         ("cart.html",         "text/html+skybridge"),
    MOF_PICKER_URI:   ("mof_picker.html",   "text/html+skybridge"),
    RECEIPT_URI:      ("receipt.html",      "text/html+skybridge"),
}

from .loader import register_resources  # noqa: E402  (after constants)

__all__ = [
    "PRODUCT_GRID_URI",
    "CART_URI",
    "MOF_PICKER_URI",
    "RECEIPT_URI",
    "TEMPLATE_INDEX",
    "register_resources",
    "widget_meta",
    "widget_result",
]
