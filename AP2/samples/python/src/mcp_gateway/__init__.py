"""AP2 MCP gateway — fine-grained MCP tools that drive the AP2 agents.

This package is the *only* inbound surface for Claude / ChatGPT in the
pharmacy POC. Each tool is a thin wrapper over either a SQLite query
(catalog, history) or an A2A round-trip (cart, payment) — no LLM runs
inside the gateway.
"""
