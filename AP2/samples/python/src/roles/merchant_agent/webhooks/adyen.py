"""Adyen webhook receiver — finalises 3DS2 step-up and records notifications.

Mount this sub-app from the merchant agent's ASGI server. Two endpoints:

  POST /webhooks/adyen/notifications
       Standard webhook batch (notification items wrapped in
       ``notificationItems[].NotificationRequestItem``). HMAC-validated
       per item. Each item updates the ``challenges`` table by
       ``pspReference`` and records the merchant_reference for audit.

  POST /webhooks/adyen/3ds-return
       Browser landing endpoint after the shopper completes the 3DS2
       challenge on Adyen's hosted page. The ``redirectResult`` /
       ``payload`` query string is forwarded to Adyen
       ``/payments/details``; the result is stored in the ``challenges``
       table and the user is redirected to ``ADYEN_RETURN_URL``.

To wire from ``agent_executor.py`` (one-line change you make manually)::

    from roles.merchant_agent.webhooks.adyen import build_app as build_adyen_webhook
    asgi_app.mount("/webhooks/adyen", build_adyen_webhook())

Required env (in addition to the runtime adapter's vars):

  ADYEN_HMAC_KEY    hex-encoded HMAC key from the Adyen webhook config
  ADYEN_API_KEY     reused from the runtime adapter (for /payments/details)
  ADYEN_API_BASE    optional override
  ADYEN_RETURN_URL  optional, default https://example.com/ap2-poc/return
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sqlite3
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from pharmacy_data import db as _db


_LOG = logging.getLogger("ap2.merchant_agent.webhooks.adyen")

_DEFAULT_TEST_BASE = "https://checkout-test.adyen.com/v71"

# Field order Adyen specifies for HMAC signing of notification items.
# https://docs.adyen.com/development-resources/webhooks/verify-hmac-signatures
_HMAC_FIELDS = (
    "pspReference",
    "originalReference",
    "merchantAccountCode",
    "merchantReference",
    "amount.value",
    "amount.currency",
    "eventCode",
    "success",
)


# --------------------------------------------------------------------- DB

def _ensure_challenges_table(conn: sqlite3.Connection) -> None:
    """Create the ``challenges`` table if the seed schema didn't already.

    Defensive — the canonical schema lives in ``pharmacy_data/schema.sql``;
    this is only here so the webhook is self-bootstrapping for fresh dev DBs.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS challenges (
            challenge_id        TEXT PRIMARY KEY,
            payment_mandate_id  TEXT,
            psp_reference       TEXT,
            status              TEXT,           -- pending / Authorised / Refused / Error
            raw_result_code     TEXT,
            refusal_reason      TEXT,
            event_code          TEXT,
            merchant_reference  TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT,
            raw_json            TEXT
        )
        """
    )
    # Helpful lookup index for the webhook's UPDATE-by-pspReference path.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_challenges_psp "
        "ON challenges(psp_reference)"
    )


def _record_notification(item: dict[str, Any]) -> None:
    psp_ref     = item.get("pspReference")
    event_code  = item.get("eventCode")
    success_str = (item.get("success") or "").lower()
    success     = success_str == "true"
    merch_ref   = item.get("merchantReference")
    refusal     = item.get("reason") if not success else None

    conn = _db.connect()
    try:
        _ensure_challenges_table(conn)
        # Upsert by psp_reference (a 3DS challenge row was inserted at
        # submit time; if not, the webhook still records the audit row).
        existing = conn.execute(
            "SELECT challenge_id FROM challenges WHERE psp_reference = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (psp_ref,),
        ).fetchone()
        status = "Authorised" if success else "Refused"
        if existing:
            conn.execute(
                "UPDATE challenges SET status=?, event_code=?, "
                "merchant_reference=?, refusal_reason=?, "
                "raw_json=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE challenge_id=?",
                (status, event_code, merch_ref, refusal,
                 json.dumps(item), existing["challenge_id"]),
            )
        else:
            conn.execute(
                "INSERT INTO challenges(challenge_id, psp_reference, status, "
                "event_code, merchant_reference, refusal_reason, raw_json, "
                "updated_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (f"webhook_{psp_ref}", psp_ref, status, event_code,
                 merch_ref, refusal, json.dumps(item)),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------- HMAC

def _hmac_payload(item: dict[str, Any]) -> str:
    """Build the colon-separated HMAC payload Adyen expects."""
    amount = item.get("amount") or {}
    values = {
        "pspReference":         item.get("pspReference") or "",
        "originalReference":    item.get("originalReference") or "",
        "merchantAccountCode":  item.get("merchantAccountCode") or "",
        "merchantReference":    item.get("merchantReference") or "",
        "amount.value":         str(amount.get("value", "")),
        "amount.currency":      amount.get("currency") or "",
        "eventCode":            item.get("eventCode") or "",
        "success":              item.get("success") or "",
    }
    # Adyen escapes ":" and "\\" in field values prior to joining.
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(":", "\\:")
    return ":".join(esc(values[f]) for f in _HMAC_FIELDS)


def _verify_hmac(item: dict[str, Any], hmac_key_hex: str) -> bool:
    additional = item.get("additionalData") or {}
    received_b64 = additional.get("hmacSignature")
    if not received_b64:
        return False
    try:
        key = bytes.fromhex(hmac_key_hex)
    except ValueError:
        _LOG.error("ADYEN_HMAC_KEY is not valid hex")
        return False
    payload = _hmac_payload(item).encode("utf-8")
    digest = hmac.new(key, payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, received_b64)


# --------------------------------------------------------------------- handlers

async def _notifications_handler(request: Request) -> JSONResponse:
    """Adyen Standard Webhook — must respond ``[accepted]`` quickly."""
    hmac_key = os.environ.get("ADYEN_HMAC_KEY")
    if not hmac_key:
        # Dev mode: accept without HMAC but log loudly.
        _LOG.warning("ADYEN_HMAC_KEY not set; accepting webhook unverified")

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)

    items = body.get("notificationItems") or []
    bad = 0
    for wrapped in items:
        item = wrapped.get("NotificationRequestItem") or {}
        if hmac_key and not _verify_hmac(item, hmac_key):
            bad += 1
            _LOG.error("HMAC mismatch on item pspReference=%s",
                       item.get("pspReference"))
            continue
        try:
            _record_notification(item)
        except Exception:
            _LOG.exception("failed to record notification %s",
                           item.get("pspReference"))

    if bad:
        # Per Adyen: returning anything other than "[accepted]" causes retry.
        # We still return 200 [accepted] so good items aren't re-sent;
        # bad items have already been logged for follow-up.
        _LOG.warning("accepted batch with %d HMAC failures", bad)
    return JSONResponse(content="[accepted]")


async def _three_ds_return_handler(request: Request) -> RedirectResponse:
    """Browser lands here after the 3DS2 challenge.

    We POST to Adyen ``/payments/details`` with the ``redirectResult`` /
    ``payload`` parameter, persist the outcome, then redirect the shopper
    to ``ADYEN_RETURN_URL`` so the browser tab can be closed safely.
    """
    qs = dict(request.query_params)
    payload = qs.get("redirectResult") or qs.get("payload")
    psp_ref = qs.get("pspReference")
    return_url = os.environ.get(
        "ADYEN_RETURN_URL",
        "https://example.com/ap2-poc/return",
    )

    if not payload:
        return RedirectResponse(url=f"{return_url}?status=missing_payload")

    api_key = os.environ.get("ADYEN_API_KEY")
    base    = (os.environ.get("ADYEN_API_BASE")
               or _DEFAULT_TEST_BASE).rstrip("/")
    if not api_key:
        _LOG.error("ADYEN_API_KEY not set; cannot finalise 3DS")
        return RedirectResponse(url=f"{return_url}?status=server_misconfigured")

    body = {"details": {"redirectResult": payload}}
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{base}/payments/details",
                headers={"X-API-Key": api_key,
                         "Content-Type": "application/json"},
                json=body,
            )
        data = r.json() if r.headers.get("content-type", "").startswith(
            "application/json") else {}
    except Exception:
        _LOG.exception("payments/details transport error")
        return RedirectResponse(url=f"{return_url}?status=transport_error")

    rc = data.get("resultCode")
    psp_from_resp = data.get("pspReference") or psp_ref

    # Persist on the challenge row.
    try:
        conn = _db.connect()
        _ensure_challenges_table(conn)
        existing = conn.execute(
            "SELECT challenge_id FROM challenges WHERE psp_reference = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (psp_from_resp,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE challenges SET status=?, raw_result_code=?, "
                "refusal_reason=?, raw_json=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE challenge_id=?",
                (rc or "Error", rc, data.get("refusalReason"),
                 json.dumps(data), existing["challenge_id"]),
            )
        else:
            conn.execute(
                "INSERT INTO challenges(challenge_id, psp_reference, status, "
                "raw_result_code, refusal_reason, raw_json, updated_at) "
                "VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (f"3ds_{psp_from_resp}", psp_from_resp, rc or "Error",
                 rc, data.get("refusalReason"), json.dumps(data)),
            )
        conn.commit()
        conn.close()
    except Exception:
        _LOG.exception("failed to persist /payments/details outcome")

    return RedirectResponse(
        url=f"{return_url}?status={rc or 'unknown'}&psp={psp_from_resp or ''}"
    )


def build_app() -> Starlette:
    """Return a Starlette sub-app to mount under ``/webhooks/adyen``."""
    return Starlette(routes=[
        Route("/notifications", _notifications_handler, methods=["POST"]),
        Route("/3ds-return",    _three_ds_return_handler, methods=["GET", "POST"]),
    ])
