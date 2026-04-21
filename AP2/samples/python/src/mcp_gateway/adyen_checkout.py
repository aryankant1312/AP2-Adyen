"""Adyen Sessions-flow + Web Drop-in for the Boots pharmacy MCP.

The MCP widgets inside ChatGPT run in a locked-down iframe that cannot load
Adyen's client bundle. So the shopper path is:

  1. LLM calls the ``start_adyen_checkout`` MCP tool.
  2. Gateway creates an Adyen ``/sessions`` object, persists it in SQLite,
     and returns a ``pay_url`` of the form
     ``https://<ngrok>/pay/<session_id>``.
  3. Shopper opens that URL in a new tab. The gateway serves a
     Boots-branded HTML page that mounts Adyen Web Drop-in v6 (Sessions
     flow). Drop-in handles payment method selection, 3DS2, and redirects.
  4. On redirect-based challenges Adyen returns to
     ``/pay/return?sessionId=…&sessionResult=…``. We finalise by calling
     ``GET /v71/sessions/{id}?sessionResult=…`` server-side, stash the
     outcome in SQLite and show the shopper a Boots confirmation page.
  5. Back in ChatGPT the LLM calls ``poll_adyen_checkout`` which reads
     our SQLite row; once it's ``completed`` the tool emits the receipt
     widget.

Webhook validation for out-of-band notifications is handled in
``_adyen_webhook`` using ``ADYEN_HMAC_KEY``.
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import os
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from pharmacy_data import db as _db


_LOG = logging.getLogger("ap2.mcp_gateway.adyen")

# ---------------------------------------------------------------- env / config

_ADYEN_ENV = (os.environ.get("ADYEN_ENVIRONMENT") or "test").lower()
# Server-to-server API host (per region). For test both EU and US use
# ``checkout-test``; for live you'd use the region-specific subdomain.
_API_HOST = {
    "test": "https://checkout-test.adyen.com",
    "live": os.environ.get("ADYEN_LIVE_PREFIX",
                           "https://checkout-live.adyenpayments.com"),
}.get(_ADYEN_ENV, "https://checkout-test.adyen.com")
_API_VERSION = "v71"

# Client-side Drop-in CDN bundle.
_DROPIN_VERSION = os.environ.get("ADYEN_DROPIN_VERSION", "6.31.1")


def _api_key() -> str:
    return os.environ.get("ADYEN_API_KEY") or ""


def _merchant_account() -> str:
    return os.environ.get("ADYEN_MERCHANT_ACCOUNT") or ""


def _client_key() -> str:
    return os.environ.get("ADYEN_CLIENT_KEY") or ""


def _hmac_key_hex() -> str:
    return os.environ.get("ADYEN_HMAC_KEY") or ""


# ---------------------------------------------------------------- public base URL

def _public_base_url() -> str:
    """Best-effort auto-detect the public HTTPS URL the gateway is reachable at.

    Priority:
      1. ``PUBLIC_BASE_URL`` env var (explicit override — used by tests or
         when hosting behind a custom domain).
      2. The live ngrok tunnel reported at http://127.0.0.1:4040 (what
         ``start_stack.sh`` spawns).
      3. Fall back to ``http://localhost:<MCP_HTTP_PORT|5000>`` so local
         development still works (3DS redirects will obviously fail then,
         but the user sees a clear URL).
    """
    override = os.environ.get("PUBLIC_BASE_URL")
    if override:
        return override.rstrip("/")
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:4040/api/tunnels", timeout=0.8
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for tun in data.get("tunnels", []):
                url = tun.get("public_url", "")
                if url.startswith("https://"):
                    return url.rstrip("/")
    except Exception:
        pass
    port = os.environ.get("MCP_HTTP_PORT") or "5000"
    return f"http://localhost:{port}"


# ---------------------------------------------------------------- SQLite

_SESSIONS_DDL = (
    ("session_id",              "TEXT PRIMARY KEY"),
    ("cart_id",                 "TEXT"),
    ("user_email",              "TEXT"),
    ("shopper_reference",       "TEXT"),
    ("amount_minor",            "INTEGER"),
    ("currency",                "TEXT DEFAULT 'GBP'"),
    ("status",                  "TEXT DEFAULT 'pending'"),
    ("psp_reference",           "TEXT"),
    ("result_code",             "TEXT"),
    ("refusal_reason",          "TEXT"),
    ("stored_payment_method_id","TEXT"),
    ("session_data",            "TEXT"),
    ("return_url",              "TEXT"),
    ("created_at",              "TEXT DEFAULT CURRENT_TIMESTAMP"),
    ("updated_at",              "TEXT"),
)


def _ensure_table(conn: sqlite3.Connection) -> None:
    cols_decl = ", ".join(f"{c} {d}" for c, d in _SESSIONS_DDL)
    conn.execute(f"CREATE TABLE IF NOT EXISTS adyen_checkout_sessions ({cols_decl})")
    existing = {row["name"] for row
                in conn.execute("PRAGMA table_info(adyen_checkout_sessions)").fetchall()}
    for col, decl in _SESSIONS_DDL:
        if col in existing:
            continue
        ddl = decl.replace("PRIMARY KEY", "").strip() or "TEXT"
        conn.execute(f"ALTER TABLE adyen_checkout_sessions ADD COLUMN {col} {ddl}")


def _save_session(row: dict) -> None:
    cols = [c for c, _ in _SESSIONS_DDL]
    vals = [row.get(c) for c in cols]
    conn = _db.connect()
    try:
        _ensure_table(conn)
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT OR REPLACE INTO adyen_checkout_sessions({','.join(cols)}) "
            f"VALUES({placeholders})", vals,
        )
        conn.commit()
    finally:
        conn.close()


def _update_session(session_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime()))
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = _db.connect()
    try:
        _ensure_table(conn)
        conn.execute(
            f"UPDATE adyen_checkout_sessions SET {sets} WHERE session_id = ?",
            list(fields.values()) + [session_id],
        )
        conn.commit()
    finally:
        conn.close()


def load_session_row(session_id: str) -> dict | None:
    conn = _db.connect()
    try:
        _ensure_table(conn)
        r = conn.execute(
            "SELECT * FROM adyen_checkout_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def session_for_cart(cart_id: str) -> dict | None:
    conn = _db.connect()
    try:
        _ensure_table(conn)
        r = conn.execute(
            "SELECT * FROM adyen_checkout_sessions WHERE cart_id = ? "
            "ORDER BY created_at DESC LIMIT 1", (cart_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


# ---------------------------------------------------------------- Adyen HTTP client

class AdyenError(RuntimeError):
    pass


def _api_call(method: str, path: str,
              body: dict | None = None) -> dict:
    url = f"{_API_HOST}/{_API_VERSION}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-API-key", _api_key())
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        _LOG.error("Adyen %s %s -> HTTP %d: %s",
                   method, path, exc.code, raw[:400])
        try:
            err = json.loads(raw)
        except Exception:
            err = {"message": raw}
        raise AdyenError(
            f"adyen {method} {path} failed (HTTP {exc.code}): "
            f"{err.get('message') or err}") from None


# ---------------------------------------------------------------- create_checkout_session

def _minor_units(amount_gbp: float, currency: str = "GBP") -> int:
    # GBP is 2-decimal, so multiply by 100 and round.
    return int(round(float(amount_gbp) * 100))


def _shopper_reference(user_email: str) -> str:
    # Stable, non-PII shopper ref derived from the email. Adyen requires
    # alphanumeric + ``_-``; keep it under 256 chars.
    digest = hashlib.sha256((user_email or "anon").encode("utf-8")).hexdigest()
    return f"boots_{digest[:24]}"


def create_checkout_session(*,
                             cart_id: str,
                             user_email: str,
                             amount_gbp: float,
                             currency: str = "GBP",
                             public_base: str | None = None,
                             shopper_reference: str | None = None,
                             ) -> dict:
    """Create a Sessions-flow session and persist our ledger row.

    Returns a dict with ``pay_url``, ``session_id``, ``expires_at``,
    ``amount_gbp``, ``currency`` — safe to hand to the LLM.
    """
    if not _api_key() or not _merchant_account():
        raise AdyenError("ADYEN_API_KEY and ADYEN_MERCHANT_ACCOUNT must be set")
    if amount_gbp <= 0:
        raise AdyenError("amount_gbp must be > 0")

    base = (public_base or _public_base_url()).rstrip("/")
    shopper_ref = shopper_reference or _shopper_reference(user_email)

    # NB: returnUrl carries session_id so /pay/return can find our row even
    # before Adyen's query params arrive.
    return_url = f"{base}/pay/return"

    body: dict[str, Any] = {
        "amount":                   {"currency": currency,
                                     "value":    _minor_units(amount_gbp,
                                                              currency)},
        "reference":                cart_id,
        "merchantAccount":          _merchant_account(),
        "returnUrl":                return_url,
        "countryCode":              "GB",
        "shopperLocale":            "en-GB",
        "channel":                  "Web",
        "shopperReference":         shopper_ref,
        "shopperEmail":             user_email,
        # Show saved cards for this shopper and allow storing new ones.
        "storePaymentMethodMode":   "askForConsent",
        "recurringProcessingModel": "CardOnFile",
        # Non-sensitive trace metadata.
        "metadata": {
            "cart_id":    cart_id,
            "storefront": "boots-pharmacy-mcp",
        },
    }

    result = _api_call("POST", "/sessions", body)
    session_id = result.get("id")
    if not session_id:
        raise AdyenError(f"adyen /sessions did not return id: {result}")

    pay_url = f"{base}/pay/{session_id}"
    row = {
        "session_id":               session_id,
        "cart_id":                  cart_id,
        "user_email":               user_email,
        "shopper_reference":        shopper_ref,
        "amount_minor":             body["amount"]["value"],
        "currency":                 currency,
        "status":                   "pending",
        "session_data":             json.dumps(result),
        "return_url":               return_url,
    }
    _save_session(row)
    _LOG.info("adyen session created id=%s cart=%s amount=%d %s pay_url=%s",
              session_id, cart_id, body["amount"]["value"], currency, pay_url)

    return {
        "session_id":  session_id,
        "pay_url":     pay_url,
        "expires_at":  result.get("expiresAt"),
        "amount_gbp":  amount_gbp,
        "currency":    currency,
    }


# ---------------------------------------------------------------- session status polling

_FINAL_CODES = {"Authorised", "Refused", "Cancelled", "Error"}


def _map_result_code(code: str) -> str:
    if not code:
        return "pending"
    if code == "Authorised":
        return "completed"
    if code in {"Refused", "Cancelled", "Error"}:
        return "failed"
    return "pending"


def refresh_session_status(session_id: str,
                           session_result: str | None = None) -> dict:
    """Poll Adyen for the latest outcome of a session and update SQLite.

    ``session_result`` (opaque signed blob) is the value Adyen appends to
    the return URL after a redirect-based challenge; passing it lets the
    sessions API return the final result.
    """
    path = f"/sessions/{urllib.parse.quote(session_id)}"
    if session_result:
        path += f"?sessionResult={urllib.parse.quote(session_result)}"
    try:
        data = _api_call("GET", path)
    except AdyenError as exc:
        _LOG.warning("refresh_session_status failed for %s: %s", session_id, exc)
        return load_session_row(session_id) or {}

    status_text = data.get("status") or ""       # "completed" / "paymentPending"
    result_code = data.get("resultCode") or ""   # "Authorised" etc. (may be blank
                                                 # if still pending)
    psp_ref = data.get("pspReference") or ""

    fields: dict[str, Any] = {}
    if result_code:
        fields["result_code"] = result_code
        fields["status"] = _map_result_code(result_code)
    elif status_text == "completed":
        fields["status"] = "completed"
    if psp_ref:
        fields["psp_reference"] = psp_ref

    if fields:
        _update_session(session_id, **fields)

    return load_session_row(session_id) or {}


# ---------------------------------------------------------------- webhook HMAC

def _verify_webhook_hmac(item: dict) -> bool:
    """Verify the HMAC of a single notification item (test + live rules).

    The signing string is a pipe-joined list of specific NotificationRequestItem
    fields; see https://docs.adyen.com/development-resources/webhooks/verify-hmac-signatures.
    """
    key_hex = _hmac_key_hex()
    if not key_hex:
        _LOG.warning("ADYEN_HMAC_KEY not set — skipping webhook verification")
        return True

    sig = ((item.get("additionalData") or {}).get("hmacSignature") or "")
    if not sig:
        return False

    amount = item.get("amount") or {}
    fields = [
        item.get("pspReference") or "",
        item.get("originalReference") or "",
        item.get("merchantAccountCode") or "",
        item.get("merchantReference") or "",
        str(amount.get("value", "")),
        amount.get("currency", ""),
        item.get("eventCode") or "",
        "true" if item.get("success") in (True, "true") else "false",
    ]
    signing_input = ":".join(f.replace("\\", "\\\\").replace(":", "\\:")
                              for f in fields).encode("utf-8")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        _LOG.error("ADYEN_HMAC_KEY is not valid hex")
        return False
    digest = hmac.new(key, signing_input, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, sig)


# ---------------------------------------------------------------- HTML templates

_DROPIN_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Boots — Secure checkout</title>
<link rel="stylesheet"
      href="https://checkoutshopper-{env_host}.adyen.com/checkoutshopper/sdk/{dropin_version}/adyen.css"
      integrity="" crossorigin="anonymous">
<style>
  :root {{
    --boots-navy:#05054B; --boots-blue:#004990; --boots-red:#CC0033;
    --boots-yellow:#FFE600; --boots-grey-bg:#F4F5F7; --boots-border:#E1E3E8;
    --boots-text:#05054B; --boots-muted:#6B7280;
  }}
  body {{ margin:0; font-family:Arial,Helvetica,sans-serif;
         background:var(--boots-grey-bg); color:var(--boots-text); }}
  header {{ background:var(--boots-navy); padding:16px 20px; }}
  header img {{ height:38px; filter:brightness(0) invert(1); }}
  .wrap {{ max-width:560px; margin:24px auto; padding:0 16px; }}
  .card {{ background:#fff; border:1px solid var(--boots-border);
           border-radius:8px; padding:20px; }}
  .summary {{ display:flex; justify-content:space-between; align-items:center;
              border-bottom:1px solid var(--boots-border);
              padding-bottom:12px; margin-bottom:16px; font-size:14px; }}
  .summary .label {{ color:var(--boots-muted); }}
  .summary .total {{ font-weight:700; font-size:18px; }}
  .banner {{ background:var(--boots-yellow); color:var(--boots-navy);
             padding:9px 12px; border-radius:6px; text-align:center;
             font-weight:700; font-size:13px; margin-bottom:14px; }}
  #dropin-container {{ min-height:220px; }}
  .footnote {{ font-size:12px; color:var(--boots-muted);
               text-align:center; margin-top:18px; }}
  .err {{ background:#FBE8E8; color:var(--boots-red); padding:10px 12px;
          border-radius:6px; font-size:13px; margin-top:10px; }}
</style>
</head>
<body>
<header><img src="{logo_data_url}" alt="Boots"></header>
<div class="wrap">
  <div class="banner">🔒 Secure payment powered by Adyen</div>
  <div class="card">
    <div class="summary">
      <div>
        <div class="label">Basket</div>
        <div style="font-weight:600;">{cart_id}</div>
      </div>
      <div style="text-align:right;">
        <div class="label">Total</div>
        <div class="total">{currency_symbol}{amount_major}</div>
      </div>
    </div>
    <div id="dropin-container"></div>
    <div id="err" class="err" style="display:none"></div>
  </div>
  <div class="footnote">
    Your card details are encrypted and sent directly to Adyen —
    they never touch the Boots MCP server.
  </div>
</div>

<script type="module">
  import {{ AdyenCheckout, Dropin, Card }}
      from "https://checkoutshopper-{env_host}.adyen.com/checkoutshopper/sdk/{dropin_version}/adyen.js";

  const errEl = document.getElementById("err");
  function showError(msg) {{ errEl.textContent = msg; errEl.style.display="block"; }}

  try {{
    const checkout = await AdyenCheckout({{
      environment: "{env_short}",
      clientKey: "{client_key}",
      session: {{
        id: "{session_id}",
        sessionData: {session_data_json}
      }},
      countryCode: "GB",
      locale: "en-GB",
      onPaymentCompleted: (result, component) => {{
        // Result handled server-side on /pay/return. For non-redirect
        // completions (card without 3DS), navigate there ourselves.
        window.location.href = "/pay/return?sessionId={session_id}" +
            "&resultCode=" + encodeURIComponent(result.resultCode || "");
      }},
      onPaymentFailed: (result, component) => {{
        window.location.href = "/pay/return?sessionId={session_id}" +
            "&resultCode=" + encodeURIComponent(
                (result && result.resultCode) || "Refused");
      }},
      onError: (err, component) => {{
        console.error("Drop-in error:", err);
        showError(err && err.message ? err.message
                  : "Something went wrong. Please try again.");
      }},
    }});
    new Dropin(checkout, {{
      paymentMethodComponents: [Card],
    }}).mount("#dropin-container");
  }} catch (err) {{
    console.error(err);
    showError("Could not load the payment form: " +
              (err && err.message ? err.message : err));
  }}
</script>
</body>
</html>
"""


_RETURN_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Boots — Payment {headline}</title>
<style>
  :root {{
    --boots-navy:#05054B; --boots-blue:#004990; --boots-red:#CC0033;
    --boots-yellow:#FFE600; --boots-grey-bg:#F4F5F7; --boots-border:#E1E3E8;
    --boots-text:#05054B; --boots-green:#1E7C3A; --boots-muted:#6B7280;
  }}
  body {{ margin:0; font-family:Arial,Helvetica,sans-serif;
         background:var(--boots-grey-bg); color:var(--boots-text); }}
  header {{ background:var(--boots-navy); padding:16px 20px; }}
  header img {{ height:38px; filter:brightness(0) invert(1); }}
  .wrap {{ max-width:520px; margin:40px auto; padding:0 16px; }}
  .card {{ background:#fff; border:1px solid var(--boots-border);
           border-radius:8px; padding:28px; text-align:center; }}
  .icon {{ width:64px; height:64px; border-radius:50%;
          display:inline-flex; align-items:center; justify-content:center;
          font-size:32px; color:#fff; margin-bottom:14px;
          background:{icon_bg}; }}
  h1 {{ margin:8px 0 6px; font-size:22px; }}
  p  {{ color:var(--boots-muted); margin:4px 0; font-size:14px; }}
  .meta {{ border-top:1px solid var(--boots-border);
           margin-top:18px; padding-top:14px; text-align:left;
           font-size:13px; color:var(--boots-muted); }}
  .meta strong {{ color:var(--boots-text); }}
  .callout {{ margin-top:18px; background:var(--boots-yellow);
              color:var(--boots-navy); border-radius:6px;
              padding:10px 12px; font-weight:700; font-size:13px; }}
</style>
</head>
<body>
<header><img src="{logo_data_url}" alt="Boots"></header>
<div class="wrap">
  <div class="card">
    <div class="icon">{icon_char}</div>
    <h1>{headline}</h1>
    <p>{subline}</p>
    <div class="meta">
      <div><strong>Session</strong>: {session_id}</div>
      <div><strong>Basket</strong>: {cart_id}</div>
      <div><strong>Amount</strong>: £{amount_major}</div>
      <div><strong>Result</strong>: {result_code}</div>
      {psp_line}
    </div>
    <div class="callout">{callout}</div>
  </div>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- route handlers

def _load_logo_data_url() -> str:
    """Re-use the same base-64 PNG the widgets use."""
    try:
        from .ui.loader import _BOOTS_LOGO_DATA_URL  # type: ignore
        return _BOOTS_LOGO_DATA_URL
    except Exception:
        return ""


def _env_host() -> str:
    return "test" if _ADYEN_ENV == "test" else "live"


def _env_short() -> str:
    return "test" if _ADYEN_ENV == "test" else "live"


async def _pay_page(request: Request) -> HTMLResponse:
    session_id = request.path_params["session_id"]
    row = load_session_row(session_id)
    if not row:
        return HTMLResponse(
            "<h1>Unknown payment session</h1>"
            "<p>Please return to ChatGPT and restart checkout.</p>",
            status_code=404)

    session_data_json = "null"
    try:
        sd = json.loads(row.get("session_data") or "{}")
        session_data_json = json.dumps(sd.get("sessionData") or "")
    except Exception:
        pass

    amount_major = f"{(row.get('amount_minor') or 0) / 100:.2f}"
    html = _DROPIN_PAGE_HTML.format(
        session_id=session_id,
        cart_id=row.get("cart_id") or "",
        amount_major=amount_major,
        currency_symbol="£" if (row.get("currency") or "GBP") == "GBP" else "",
        client_key=_client_key(),
        env_host=_env_host(),
        env_short=_env_short(),
        dropin_version=_DROPIN_VERSION,
        session_data_json=session_data_json,
        logo_data_url=_load_logo_data_url(),
    )
    return HTMLResponse(html)


async def _pay_return(request: Request) -> HTMLResponse:
    qp = request.query_params
    session_id = qp.get("sessionId") or qp.get("session_id") or ""
    session_result = qp.get("sessionResult")
    result_code_q = qp.get("resultCode") or ""

    row = load_session_row(session_id) if session_id else None
    if not row:
        return HTMLResponse(
            "<h1>Unknown payment session</h1>"
            "<p>Please return to ChatGPT to try again.</p>",
            status_code=404)

    # Always refresh the authoritative status from Adyen.
    row = refresh_session_status(session_id, session_result) or row

    # If the redirect dropped us here without a sessionResult but Drop-in
    # did tell us a resultCode client-side, record it too.
    if result_code_q and not row.get("result_code"):
        _update_session(session_id,
                        result_code=result_code_q,
                        status=_map_result_code(result_code_q))
        row = load_session_row(session_id) or row

    code = row.get("result_code") or result_code_q or "Pending"
    status = row.get("status") or "pending"
    amount_major = f"{(row.get('amount_minor') or 0) / 100:.2f}"
    psp_ref = row.get("psp_reference") or ""
    psp_line = (f"<div><strong>Gateway ref</strong>: {psp_ref}</div>"
                if psp_ref else "")

    if status == "completed":
        icon_bg = "var(--boots-green)"
        icon_char = "✓"
        headline = "Payment authorised"
        subline = "Thank you — your Boots order has been confirmed."
        callout = "You can close this tab and return to ChatGPT."
    elif status == "failed":
        icon_bg = "var(--boots-red)"
        icon_char = "✕"
        headline = "Payment not completed"
        subline = "No funds were taken. Please return to ChatGPT to try again."
        callout = "Close this tab and ask ChatGPT to retry checkout."
    else:
        icon_bg = "var(--boots-blue)"
        icon_char = "⋯"
        headline = "Finalising your payment"
        subline = "This usually takes only a moment."
        callout = "Return to ChatGPT in a few seconds."

    html = _RETURN_PAGE_HTML.format(
        icon_bg=icon_bg,
        icon_char=icon_char,
        headline=headline,
        subline=subline,
        session_id=session_id,
        cart_id=row.get("cart_id") or "",
        amount_major=amount_major,
        result_code=code,
        psp_line=psp_line,
        callout=callout,
        logo_data_url=_load_logo_data_url(),
    )
    return HTMLResponse(html)


async def _pay_status(request: Request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    row = load_session_row(session_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    row = refresh_session_status(session_id) or row
    # Never leak the raw sessionData blob.
    safe = {k: v for k, v in row.items() if k != "session_data"}
    return JSONResponse(safe)


async def _adyen_webhook(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"notificationResponse": "[accepted]"})

    for item_wrap in body.get("notificationItems", []):
        item = item_wrap.get("NotificationRequestItem") or {}
        if not _verify_webhook_hmac(item):
            _LOG.warning("webhook HMAC failed for pspRef=%s",
                         item.get("pspReference"))
            continue
        merchant_ref = item.get("merchantReference") or ""
        event_code = item.get("eventCode") or ""
        success = item.get("success") in (True, "true")

        # Match by our cart_id (merchantReference) OR pspReference.
        row = None
        conn = _db.connect()
        try:
            _ensure_table(conn)
            r = conn.execute(
                "SELECT * FROM adyen_checkout_sessions "
                "WHERE cart_id = ? OR psp_reference = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (merchant_ref, item.get("pspReference") or ""),
            ).fetchone()
            row = dict(r) if r else None
        finally:
            conn.close()
        if not row:
            continue

        fields: dict[str, Any] = {
            "psp_reference": item.get("pspReference") or row.get("psp_reference"),
        }
        if event_code == "AUTHORISATION":
            if success:
                fields["status"] = "completed"
                fields["result_code"] = "Authorised"
            else:
                fields["status"] = "failed"
                fields["result_code"] = "Refused"
                fields["refusal_reason"] = item.get("reason") or ""
        _update_session(row["session_id"], **fields)

    # Adyen needs this exact response body within 10s.
    return JSONResponse({"notificationResponse": "[accepted]"})


# ---------------------------------------------------------------- public routes

# Paths that the gateway must let through unauthenticated — Drop-in runs
# in the shopper's browser with no bearer token.
PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/pay", "/webhooks/adyen")


def routes() -> list[Route]:
    return [
        Route("/pay/{session_id}",         _pay_page,    methods=["GET"]),
        Route("/pay/return",               _pay_return,  methods=["GET"]),
        Route("/pay/status/{session_id}",  _pay_status,  methods=["GET"]),
        Route("/webhooks/adyen",           _adyen_webhook, methods=["POST"]),
    ]
