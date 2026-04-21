# Running the AP2 pharmacy POC

Four services — Merchant Agent, Credentials Provider, Merchant Payment
Processor, MCP Gateway — run side-by-side. Only the MCP Gateway is exposed
to the host (port 8080). Claude Desktop / claude.ai / ChatGPT connect to
the gateway as a custom MCP connector.

## Prerequisites

- Python 3.11+ with `uv` (or use the docker-compose path)
- (Optional) Docker + docker-compose
- (Optional) cloudflared **or** ngrok for public HTTPS tunnels
- (Optional, for real Adyen) Adyen sandbox account — see "Adyen setup"

## Setup (≤10 commands)

```bash
# 1. Configure
cp ops/envs/.env.example ops/envs/.env
# edit ops/envs/.env: set MCP_TOKENS, plus ADYEN_* if PSP_ADAPTER=adyen
#
# Or rotate fresh tokens automatically:
python ops/gen_token.py --write-env

# 2. Build + start everything (docker path)
docker compose -f ops/docker-compose.yml up --build -d
# OR run the four services directly with uv (see scripts/run_local.sh)

# 3. Seed the SQLite database (first run only)
docker compose -f ops/docker-compose.yml run --rm \
    -e ROLE=seed mcp_gateway --seed 42

# 4. (Adyen only) Provision a real stored payment method for one customer
docker compose -f ops/docker-compose.yml run --rm \
    -e ROLE=zero_auth mcp_gateway \
    --email aarav.sharma@example.com \
    --test-card 4111111111111111 --alias-prefix "Visa"

# 5. Open a public HTTPS tunnel (in another terminal)
./ops/tunnel.sh
# → prints a banner with the exact MCP URL + bearer line + connector recipes
```

## Connector setup (Claude + ChatGPT)

After `./ops/tunnel.sh` runs, it prints the public URL and an
`Authorization: Bearer <token>` line. Use those in either client below.

### Claude — custom connector (remote)

1. claude.ai → **Settings → Connectors → Add custom connector**.
2. Name: `AP2 Pharmacy`
3. URL: `<tunnel>/mcp` (e.g. `https://random-words-1234.trycloudflare.com/mcp`)
4. Auth: `Bearer`, Token: paste from the banner.
5. New chat → enable the connector → ask:

   > Shop as `aarav.sharma@example.com` at the **London Oxford St** store.
   > Get me ibuprofen for headaches and pay with my saved Visa.

6. The connector inspector shows the tool sequence:
   `search_products → start_cart → add_cart_item → finalize_cart →
   get_merchant_on_file_payment_methods → create_merchant_on_file_token →
   build_payment_mandate → sign_payment_mandate → submit_payment →
   complete_challenge` (mock OTP `123`).

Claude does not currently render Apps-SDK widgets — every tool result
also carries a JSON `text` block so the chat reads cleanly anyway.

### Claude Desktop — local (stdio, no tunnel)

```bash
claude mcp add ap2-local -- python -m mcp_gateway
```

This bypasses HTTP entirely; auth is implicit (same trust boundary as
your laptop).

### ChatGPT — developer mode (remote)

1. ChatGPT → **Settings → Connectors → Developer mode → Add MCP server**
   (developer mode must be enabled in *Settings → Beta features*).
2. Server URL: `<tunnel>/mcp`
3. Auth: `Bearer <token>` (same token as Claude can use a different
   one — the tunnel banner prints two by default).
4. ChatGPT enumerates the ~21 tools; approve them.
5. Same shopping prompt as above. Four moments render as inline widgets:
   - `search_products` → product grid with **[Add to cart]** buttons.
   - `quote_cart` / `view_cart` → cart with totals + expiry countdown.
   - `get_merchant_on_file_payment_methods` → MOF picker tiles.
   - `submit_payment` / `complete_challenge` (Authorised) → receipt with
     PSP reference + **[Print]** / **[Reorder]**.
6. Step-up appears as a normal text bubble that hints `OTP=123` for the
   mock adapter so the demo presenter doesn't have to remember it.

## Adyen setup

1. Sign up: <https://www.adyen.com/signup> → Test account.
2. Customer Area → Merchant accounts → New (record the name).
3. Developers → API credentials → Create new credential → Web service
   user. Copy the `X-API-Key`. Scope it to Checkout API + Recurring API
   (read).
4. Account → Recurring → enable "Store details for future payments".
5. Developers → Webhooks → Standard webhook → URL
   `<tunnel>/webhooks/adyen/notifications`. Generate HMAC key, store it.
6. Set in `ops/envs/.env`:
   - `PSP_ADAPTER=adyen`
   - `ADYEN_API_KEY=...`
   - `ADYEN_MERCHANT_ACCOUNT=YourCompanyECOM`
   - `ADYEN_HMAC_KEY=<hex>`
   - `ADYEN_RETURN_URL=<tunnel>/webhooks/adyen/3ds-return`
7. Test card numbers: `4111 1111 1111 1111` (Visa),
   `5555 4444 3333 1111` (MC), CVV `737`, any future expiry.

## Verifying

```bash
# 1. Auth gate (with the four agents up)
curl -i http://localhost:8080/healthz                  # → 200 {"status":"ok"}
curl -i http://localhost:8080/mcp                      # → 401 unauthorized
curl -i -H "Authorization: Bearer wrong" \
    http://localhost:8080/mcp                          # → 401
# Real handshake requires a Streamable-HTTP MCP client (see smoke below).

# 2. Full happy-path smoke (10 steps, mock PSP)
python ops/smoke_gateway.py \
    --base-url http://127.0.0.1:8080/mcp \
    --token "$(grep ^MCP_TOKENS ops/envs/.env | cut -d= -f2 | cut -d, -f1)"

# 3. Same smoke against the public tunnel
python ops/smoke_gateway.py \
    --base-url https://<tunnel>/mcp \
    --token <token-from-banner>
```

## Troubleshooting

- **`401 unauthorized` from `/mcp`** — your `Authorization: Bearer ...`
  header doesn't match any value in `MCP_TOKENS`. Re-read the tunnel
  banner or `cat ops/envs/.env`.
- **ChatGPT shows the JSON instead of a widget** — your tool result is
  missing `_meta["openai/outputTemplate"]` or the `ui://...` resource
  isn't registered. Verify with
  `mcp resources http://localhost:8080/mcp -H "Authorization: Bearer ..."`.
- **Widget loads but the button does nothing** — the widget triggers
  `window.openai.sendFollowUpMessage(...)`. In Claude this returns
  `undefined` (graceful fallback); in ChatGPT it injects a chat message.
  Check the Apps SDK panel in ChatGPT dev tools.
- **"missing token in payment_response.details.token.value"** — you
  built a PaymentMandate against a CP token but the MPP's adapter routing
  selected `adyen-mof`. Either re-run `create_merchant_on_file_token`
  or switch `source` to `credentials_provider`.
- **3DS challenge never completes** — make sure `ADYEN_RETURN_URL`
  points at `<tunnel>/webhooks/adyen/3ds-return` so the gateway can
  finalise on behalf of the shopper.
- **Webhook HMAC mismatch** — `ADYEN_HMAC_KEY` must be the *hex* value
  Adyen showed you when you created the webhook, not base64.
