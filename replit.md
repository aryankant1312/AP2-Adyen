# AP2 (Agent Payments Protocol) — Replit Setup

This repository contains Google's **Agent Payments Protocol (AP2)** samples and the **AP2 MCP Gateway** (a Model Context Protocol server exposing pharmacy/commerce tools to LLM clients like Claude/ChatGPT).

## What's running

- **Workflow `Start application`** runs the MCP gateway (`ops/run_gateway.py`) on `0.0.0.0:5000`.
  - Health check: `GET /healthz` → `{"status":"ok","service":"ap2-mcp-gateway"}`
  - MCP endpoint: `POST /mcp` (streamable HTTP MCP transport)
  - Default auth mode is **open** (`MCP_REQUIRE_AUTH=false`); set `MCP_REQUIRE_AUTH=true` and `MCP_TOKENS=...` to require bearer tokens.

## Project layout

- `AP2/samples/python/src/mcp_gateway/` — the MCP gateway (FastMCP + Starlette).
- `AP2/samples/python/src/roles/` — the three backend agents (merchant `:8001`, credentials provider `:8002`, merchant payment processor `:8003`). They are **not** auto-started; launch them with `python ops/run_agents.py {merchant|cp|mpp}` if you want the full stack.
- `AP2/samples/python/scenarios/` — end-to-end scenarios (cards, x402, merchant-on-file). Each has a `run.sh` that starts the agents and an ADK web UI; these require a `GOOGLE_API_KEY`.
- `AP2/ops/` — launchers and ops scripts (`run_gateway.py`, `run_agents.py`, `gen_token.py`, `start_stack.sh`, ...).
- `AP2/data/pharmacy.sqlite` — sample pharmacy catalog DB used by the gateway tools.
- `AP2/keys/` — sample dev keypairs used to sign mandates.

## Tooling

- Python 3.12, dependency manager **uv** (workspace defined in `AP2/pyproject.toml`).
- Install / sync deps: `cd AP2 && uv sync --package ap2-samples`.
- The gateway requires `mcp >= 1.15` (the lockfile pinned an older version that lacks `FastMCP.tool(meta=...)`); we install `mcp>=1.15` on top of `uv sync`.

## Notes

- The gateway is bound to `0.0.0.0:5000` and serves through Replit's iframe proxy. DNS-rebinding host validation is disabled in code; bearer auth is the real gate.
- Running the full agent stack or any scenario requires `GOOGLE_API_KEY` (Gemini) — request it via the secrets UI before running them.
