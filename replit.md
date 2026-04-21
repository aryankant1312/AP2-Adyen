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

## Boots Pharmacy MCP — current customisations

- **Branding**: all four Apps-SDK widgets (`product_grid`, `cart`, `mof_picker`, `receipt`) under `AP2/samples/python/src/mcp_gateway/ui/templates/` are styled in Boots UK identity (navy `#05054B`, blue `#004990`, red `#CC0033`, yellow info banner `#FFE600`, Arial). The Boots logo PNG lives at `templates/_boots_logo.png` and is inlined as a base-64 data URL by `ui/loader.py` so widgets render without any external network fetch.
- **Flow**: cart and mof_picker show a `BASKET → PAYMENT → RECEIPT` step indicator; product_grid supports multi-select (Add / ✓ Added) and a sticky footer with `MORE OPTIONS` + `CHECKOUT`; receipt shows order ID, idempotency key, gateway, PSP reference, addresses, and a thank-you footer. The receipt payload is enriched server-side by `_build_receipt_widget_payload` in `tools/payment.py`, which joins the cart items, totals, and payment-mandate metadata into a single flat dict for the widget.
- **Payment picker**: `mof_picker.html` always renders six tiles — saved Adyen cards, "Pay with a new card", Apple Pay, Google Pay, PayPal, Klarna. The first three are wired (cards via `pay_with_merchant_on_file_token` / new card via the CP flow); the rest carry a `Coming soon` badge and are non-selectable.
- **Currency**: GBP throughout; cart math is `subtotal + £2 delivery + 0% UK-OTC VAT`.
- **ngrok tunnel**: `scripts/start_stack.sh` is the launcher. By default it brings up the merchant/CP/MPP agents on `:8001/:8002/:8003`, reuses the gateway on `:5000` (or starts one if absent), and **always** opens an `ngrok https` tunnel using the `NGROK_AUTHTOKEN` Replit secret. It then prints a Boots-branded banner with the public `/mcp` URL and ChatGPT/Claude connector instructions. Pass `--no-tunnel` to skip ngrok. Logs land in `AP2/.logs/ap2-*.log`. Tear down with `scripts/stop_stack.sh`.
- **Adyen**: required env vars are `ADYEN_API_KEY`, `ADYEN_MERCHANT_ACCOUNT`, `ADYEN_HMAC_KEY` (hex), plus the optional `ADYEN_CLIENT_KEY` / `ADYEN_RETURN_URL` (point the latter at `<ngrok>/webhooks/adyen/3ds-return`). Webhook receiver lives at `samples/python/src/roles/merchant_agent/webhooks/adyen.py`. Mint a first stored-payment-method id with `cd AP2 && uv run --no-sync python -m ops.adyen_zero_auth` once the credentials are set.
