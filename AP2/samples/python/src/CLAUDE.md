# MCP Gateway — Boots Pharmacy on AP2

Interactive **ChatGPT Apps-SDK** storefront + checkout for the AP2 (Agent Payments Protocol 2) sample. Users shop and pay inside ChatGPT via inline HTML widgets; payments are charged through **Adyen Web Drop-in** (Sessions flow).

Reference implementation for comparison: `C:/Users/Acer/Downloads/A2A/sid_flipkart/` (outside this worktree).

## Runtime shape

FastMCP server (`mcp_gateway/server.py`, entrypoint `mcp_gateway/__main__.py`) exposes MCP tools + widget resources over stdio/HTTP. Each user-facing tool is decorated with `widget_meta(URI, ...)` and returns `widget_result(payload, ui_uri=URI)`; ChatGPT renders the matching `text/html+skybridge` resource and passes `payload` as `window.openai.toolOutput`.

## End-to-end flow

```
search_products        → ui://product_grid
view_cart / add_cart_item → ui://cart
get_merchant_on_file_payment_methods → ui://mof_picker
start_adyen_checkout   → ui://new_card          (Adyen Drop-in inline)
poll_adyen_checkout    → ui://payment_processing (pending) / ui://receipt (done)
```

Widgets are **interactive** — buttons call `window.openai.callTool(name, args)`. `sendFollowUpMessage` is only a fallback for hosts without `callTool`. Cross-widget identity (`cart_id`, `user_email`) is propagated via `window.openai.setWidgetState` / `widgetState`, not via LLM narration.

## File map (where to look, by concern)

| Concern | File |
| --- | --- |
| Tool registration, FastMCP setup | `mcp_gateway/server.py`, `mcp_gateway/tools/__init__.py` |
| Catalog / search | `mcp_gateway/tools/catalog.py` |
| Cart CRUD | `mcp_gateway/tools/cart.py` |
| Payment-method discovery + Adyen tools | `mcp_gateway/tools/payment_methods.py` |
| AP2 PaymentMandate / receipt assembly | `mcp_gateway/tools/payment.py` |
| Order history | `mcp_gateway/tools/history.py` |
| Adyen Sessions API + ledger | `mcp_gateway/adyen_checkout.py` |
| In-memory per-session state (CartMandate, chosen payment, last order) | `mcp_gateway/session.py` |
| Pydantic DTOs | `mcp_gateway/schemas.py` |
| Widget URI → template map | `mcp_gateway/ui/__init__.py` (`TEMPLATE_INDEX`) |
| Resource registration, CSP overrides, `widget_meta`/`widget_result` helpers | `mcp_gateway/ui/loader.py`, `mcp_gateway/ui/__init__.py` |
| Skybridge widget HTML | `mcp_gateway/ui/templates/*.html` |
| A2A calls to merchant-agent / credentials-provider | `common/a2a_helpers.py` |
| SQLite (products, carts, orders) | `pharmacy_data/db.py` |

## Widget contract (every template uses the same pattern)

- Read input: `window.openai.toolOutput`
- Invoke a tool: `window.openai.callTool(name, args)` → returns `{ structuredContent, ... }`
- Persist state for sibling widgets: `window.openai.setWidgetState({...})`
- Fallback when `callTool` unavailable: `window.openai.sendFollowUpMessage({ prompt })`
- Template placeholder `{{BOOTS_LOGO_DATA_URL}}` is substituted by `ui/loader.py`
- Per-widget CSP overrides live in `_WIDGET_CSP_OVERRIDES` in `ui/loader.py` (Adyen CDN domains are whitelisted only for `ui://new_card`)

## Adyen integration

- **Flow**: Sessions API (`/v71/sessions`) → Web Drop-in v6 mounted inline in the iframe.
- **Secrets**: `ADYEN_API_KEY`, `ADYEN_MERCHANT_ACCOUNT`, `ADYEN_CLIENT_KEY`, `ADYEN_HMAC_KEY` (test env).
- `adyen_checkout.create_checkout_session` returns `{session_id, session_data, client_key, env_host, env_short, dropin_version, pay_url}` — Drop-in needs `session_data` + `client_key`.
- `adyen_checkout.refresh_session_status` polls Adyen and updates the SQLite ledger row; `poll_adyen_checkout` tool dispatches the processing vs. receipt widget based on the row's status.
- `mount_data_for(session_id)` re-hydrates Drop-in payload for the hosted fallback page (`/pay/<session_id>`).
- PayPal / Klarna tiles in `mof_picker.html` route through the same `start_adyen_checkout` call — Drop-in surfaces them natively if enabled on the merchant account.

## Gotchas

- **Don't regress to `sendFollowUp`-only buttons.** Every interactive control must attempt `callTool` first; the fallback is for hosts that don't implement it.
- **Empty `toolOutput` on early boot** — templates poll up to 20× at 150 ms until `_has_data` flips. Preserve this when editing render loops.
- **CSP**: adding a new external CDN requires editing `_WIDGET_CSP_OVERRIDES` (not the default CSP) and scoping it to the specific `ui://...` URI.
- **`text/html+skybridge`** is mandatory for Apps-SDK to render widgets — do not switch to `text/html`.
- **3DS2 challenges** happen inside the Drop-in iframe; the `payment_processing` widget polls `poll_adyen_checkout` every 2.5 s (max 40 attempts) and swaps itself for the receipt widget when `order_id` appears.
- **Session state is in-memory** (`session.py`) — restarting the gateway loses CartMandates. The SQLite ledger (`pharmacy_data/db.py`, `adyen_checkout.py`) persists orders and Adyen sessions.
