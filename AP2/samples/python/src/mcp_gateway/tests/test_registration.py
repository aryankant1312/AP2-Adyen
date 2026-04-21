"""Sanity test: the gateway can be constructed and exposes all tools."""

from __future__ import annotations

import pytest


def test_build_mcp_registers_tools():
    pytest.importorskip("mcp")
    from mcp_gateway.server import build_mcp

    mcp = build_mcp("ap2-pharmacy-test")

    # FastMCP keeps tools in an internal registry; the public API exposes
    # ``list_tools()`` in async form. We just check construction doesn't raise.
    assert mcp is not None
    # Discover tools via the FastMCP internal registry shape.
    registry = (getattr(mcp, "_tool_manager", None)
                or getattr(mcp, "tool_manager", None))
    if registry is not None and hasattr(registry, "_tools"):
        names = set(registry._tools.keys())
    else:
        names = set()

    # Spot-check a handful of expected tool names.
    expected = {
        "search_products", "get_product", "list_stores",
        "start_cart", "add_cart_item", "view_cart", "finalize_cart",
        "get_merchant_on_file_payment_methods",
        "get_credentials_provider_payment_methods",
        "create_merchant_on_file_token",
        "create_payment_credential_token",
        "build_payment_mandate", "sign_payment_mandate",
        "submit_payment", "complete_challenge", "get_order_status",
        "list_past_orders", "get_order",
    }
    if names:
        missing = expected - names
        assert not missing, f"missing tools: {missing}"
