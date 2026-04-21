"""Payment-mandate construction, signing, and submission tools."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import a2a_helpers
from pharmacy_data import db as _db
from pharmacy_data import queries as _queries

from .. import session as _session
from ..schemas import (
    PaymentMandateBuilt,
    SubmitResultAuthorized,
    SubmitResultChallenge,
    SubmitResultRefused,
)
from ..ui import RECEIPT_URI, widget_meta, widget_result


# --------------------------------------------------------------------- receipt enrichment

def _build_receipt_widget_payload(*, order_id: str,
                                   receipt: dict,
                                   payment_mandate: dict | None,
                                   mcp_session_id: str | None) -> dict:
    """Flatten receipt + cart + mandate metadata into a single payload the
    receipt widget can render directly without further tool calls.
    """
    sess = (_session.get_or_create(token_hash=None, user_email=None,
                                   session_id=mcp_session_id)
            if mcp_session_id else {})
    cart_id = sess.get("cart_id") or ""

    items: list[dict] = []
    subtotal = shipping = tax = total = 0.0
    if cart_id:
        try:
            conn = _db.connect()
            try:
                rows = conn.execute(
                    "SELECT product_ref, qty, unit_price_gbp, title "
                    "FROM cart_items WHERE cart_id = ?", (cart_id,)
                ).fetchall()
                items = [dict(r) for r in rows]
            finally:
                conn.close()
            subtotal = round(sum((it["qty"] or 0) * (it["unit_price_gbp"] or 0)
                                 for it in items), 2)
            shipping = 2.00 if subtotal > 0 else 0.0
            tax      = 0.0
            total    = round(subtotal + shipping + tax, 2)
        except Exception:
            _LOG.exception("could not fetch cart items for receipt widget")

    amount = (receipt.get("amount") or {})
    if total == 0.0 and amount.get("value"):
        try:
            total = float(amount["value"])
        except Exception:
            pass

    pmc = (payment_mandate or {}).get("payment_mandate_contents") or {}
    payresp = pmc.get("payment_response") or {}
    method_name = payresp.get("method_name") or ""
    token_meta  = (payresp.get("details") or {}).get("token") or {}
    payer_email = payresp.get("payer_email") or sess.get("user_email")

    if method_name.startswith("adyen"):
        gateway = "Adyen"
        payment_mode = "Saved card"
    elif "/cp" in method_name:
        gateway = "Credentials Provider"
        payment_mode = "New card"
    else:
        gateway = receipt.get("gateway") or "Adyen"
        payment_mode = "Card"

    payment_alias = token_meta.get("source") or ""

    store_location = sess.get("store_location") or "Boots online"
    ship_addr = (f"Click & Collect — {store_location}"
                 if store_location and store_location != "Boots online"
                 else "Default delivery address on file")

    return {
        "order_id":         order_id,
        "status":           receipt.get("status") or "Authorised",
        "created_at":       receipt.get("timestamp")
                            or datetime.now(timezone.utc).isoformat(),
        "currency":         amount.get("currency") or "GBP",
        "subtotal_gbp":     subtotal,
        "shipping_gbp":     shipping,
        "tax_gbp":          tax,
        "total_gbp":        total,
        "amount_gbp":       total,
        "items":            items,
        "payment_method":   payment_mode,
        "payment_mode":     payment_mode,
        "payment_alias":    payment_alias,
        "gateway":          gateway,
        "psp_reference":    receipt.get("psp_reference")
                            or receipt.get("payment_id") or "",
        "payment_id":       receipt.get("payment_id") or "",
        "idempotency_key":  receipt.get("idempotency_key")
                            or receipt.get("merchant_reference")
                            or order_id,
        "user_email":       payer_email,
        "shipping_address": ship_addr,
        "billing_address":  ship_addr,
        "raw_receipt":      receipt,
    }

_LOG = logging.getLogger("ap2.mcp_gateway.tools.payment")


# --------------------------------------------------------------------- signing

def _shopper_key_path() -> Path:
    p = Path(os.environ.get("SHOPPER_KEY_PATH", "keys/shopper_key.pem"))
    return p


def _ensure_shopper_key() -> None:
    """Generate a P-256 EC private key if one isn't present (dev)."""
    p = _shopper_key_path()
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = ec.generate_private_key(ec.SECP256R1())
        p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        _LOG.info("generated new shopper key at %s", p)
    except Exception:
        _LOG.exception("could not auto-generate shopper key at %s", p)


def _sign_p256(data: bytes) -> str:
    """ECDSA P-256 sign with the shopper key. Returns base64url DER."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    _ensure_shopper_key()
    key = serialization.load_pem_private_key(
        _shopper_key_path().read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise RuntimeError("shopper key is not an EC private key")
    sig = key.sign(data, ec.ECDSA(hashes.SHA256()))
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------- risk JWT

def _risk_jwt(*, user_email: str | None,
              session_id: str | None,
              token_hash: str | None) -> str:
    """Synthetic but schema-valid risk JWT, signed with the shopper key.

    Real systems would replace this with a Forter / Sardine / Signifyd
    signed payload. Schema deliberately mirrors a real risk-vendor token
    so downstream integrators can swap implementations without changing
    the payment mandate shape.
    """
    header = {"alg": "ES256", "typ": "RISK+JWT"}
    body = {
        "iat":           int(time.time()),
        "user_email":    user_email,
        "session_id":    session_id,
        "token_hash":    token_hash,
        "tool_call_count": 1,        # placeholder — real impl tracks per-session
        "schema":        "ap2-poc-risk-v1",
    }
    h_b64 = base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":"))
                                     .encode()).rstrip(b"=").decode()
    b_b64 = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":"))
                                     .encode()).rstrip(b"=").decode()
    signing_input = f"{h_b64}.{b_b64}".encode()
    try:
        sig = _sign_p256(signing_input)
    except Exception:
        # If the key is missing in a constrained env, emit an unsigned
        # marker so the wire shape is still schema-valid. Marked clearly.
        sig = "UNSIGNED-DEMO"
    return f"{h_b64}.{b_b64}.{sig}"


# --------------------------------------------------------------------- challenges DB

# Authoritative column list for the gateway-owned `challenges` table.
# (col_name, sqlite-decl). PRIMARY KEY only on the first column.
_CHALLENGE_COLS: tuple[tuple[str, str], ...] = (
    ("challenge_id",       "TEXT PRIMARY KEY"),
    ("payment_mandate_id", "TEXT"),
    ("psp_reference",      "TEXT"),
    ("status",             "TEXT"),
    ("raw_result_code",    "TEXT"),
    ("refusal_reason",     "TEXT"),
    ("event_code",         "TEXT"),
    ("merchant_reference", "TEXT"),
    ("created_at",         "TEXT DEFAULT CURRENT_TIMESTAMP"),
    ("updated_at",         "TEXT"),
    ("raw_json",           "TEXT"),
)


def _ensure_challenges_table(conn: sqlite3.Connection) -> None:
    """Create the table if missing; ALTER-add any columns the gateway
    expects but the live DB lacks.

    Mirrors the migration pattern in ``mcp_gateway/session.py``: an
    older schema (e.g. one shipped by ``pharmacy_data/schema.sql``)
    might have been created before we added a column — we fold those
    in idempotently rather than crashing on the next INSERT.
    """
    cols_decl = ", ".join(f"{c} {d}" for c, d in _CHALLENGE_COLS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS challenges ({cols_decl})")
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(challenges)").fetchall()
    }
    for col, decl in _CHALLENGE_COLS:
        if col in existing:
            continue
        # Strip PRIMARY KEY from ALTER-added cols (SQLite doesn't allow
        # adding a PK column after table creation).
        ddl_type = decl.replace("PRIMARY KEY", "").strip() or "TEXT"
        conn.execute(f"ALTER TABLE challenges ADD COLUMN {col} {ddl_type}")


def _record_pending_challenge(challenge: dict, payment_mandate_id: str) -> str:
    cid = challenge.get("challenge_id") or f"ch_{uuid.uuid4().hex[:12]}"
    psp = challenge.get("psp_reference")
    conn = _db.connect()
    try:
        _ensure_challenges_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO challenges("
            "challenge_id, payment_mandate_id, psp_reference, status, raw_json) "
            "VALUES(?,?,?,?,?)",
            (cid, payment_mandate_id, psp, "pending", json.dumps(challenge)),
        )
        conn.commit()
    finally:
        conn.close()
    return cid


def _read_challenge_status(challenge_id: str) -> dict | None:
    conn = _db.connect()
    try:
        _ensure_challenges_table(conn)
        row = conn.execute(
            "SELECT * FROM challenges WHERE challenge_id = ? "
            "OR psp_reference = ? ORDER BY updated_at DESC LIMIT 1",
            (challenge_id, challenge_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --------------------------------------------------------------------- registrations

def register(mcp) -> None:

    @mcp.tool()
    async def build_payment_mandate(cart_id: str,
                                     token: str,
                                     source: str,
                                     user_email: str,
                                     payer_name: str | None = None,
                                     mcp_session_id: str | None = None
                                     ) -> dict:
        """Build a PaymentMandate from a finalised cart + chosen token.

        ``source`` is one of ``merchant_on_file`` / ``credentials_provider``
        and informs the resulting ``method_name`` so the MPP can dispatch
        to the right adapter (mock_card / adyen / x402 / cp).
        """
        from ap2.types.mandate import (
            PaymentMandate,
            PaymentMandateContents,
        )
        from ap2.types.payment_request import (
            PaymentCurrencyAmount,
            PaymentItem,
            PaymentResponse,
        )

        cart_mandate = (_session.load_cart_mandate(mcp_session_id)
                        if mcp_session_id else None)
        if not cart_mandate:
            return {"error": "no finalised cart in session; call finalize_cart first"}

        # Pull total + currency from the embedded cart_mandate.
        total = (cart_mandate.get("contents", {})
                 .get("payment_request", {})
                 .get("details", {})
                 .get("total", {})
                 .get("amount", {})) or {}
        currency = total.get("currency") or "GBP"
        amount_value = str(total.get("value") or "0")

        method_name = ("adyen-mof" if source == "merchant_on_file"
                       else "https://payments.example/cp")
        pm_id = f"pm_{uuid.uuid4().hex[:14]}"
        payment_response = PaymentResponse(
            request_id=cart_id,
            method_name=method_name,
            details={"token": {"value": token, "source": source}},
            payer_name=payer_name,
            payer_email=user_email,
        )
        contents = PaymentMandateContents(
            payment_mandate_id=pm_id,
            payment_details_id=cart_id,
            payment_details_total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency=currency,
                                              value=amount_value),
                refund_period=0,
                pending=False,
            ),
            payment_response=payment_response,
            merchant_agent="merchant_agent",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        mandate = PaymentMandate(payment_mandate_contents=contents,
                                  user_authorization=None)

        out = PaymentMandateBuilt(
            payment_mandate_id=pm_id,
            contents=mandate.model_dump(),
            signed=False,
        )
        if mcp_session_id:
            _session.set_payment_mandate(mcp_session_id, pm_id,
                                         mandate.model_dump())
        return out.model_dump()

    @mcp.tool()
    async def sign_payment_mandate(mandate_id: str,
                                    mcp_session_id: str | None = None) -> dict:
        """ECDSA-P256-sign the PaymentMandate contents with the shopper key.

        Stamps the signature into ``user_authorization``.
        """
        if not mcp_session_id:
            return {"error": "mcp_session_id required to retrieve the mandate"}
        pm = _session.load_payment_mandate(mcp_session_id)
        if not pm or pm.get("payment_mandate_contents", {}) \
                .get("payment_mandate_id") != mandate_id:
            return {"error": f"mandate {mandate_id!r} not found in session"}

        canonical = json.dumps(pm["payment_mandate_contents"],
                                sort_keys=True, separators=(",", ":")).encode()
        signature = _sign_p256(canonical)
        pm["user_authorization"] = signature
        _session.set_payment_mandate(mcp_session_id, mandate_id, pm)
        return {"signed": True,
                "signature": signature,
                "alg": "ES256",
                "digest_sha256":
                    hashlib.sha256(canonical).hexdigest()}

    @mcp.tool(
        meta=widget_meta(
            RECEIPT_URI,
            invoking="Authorising payment…",
            invoked="Payment result",
        ),
    )
    async def submit_payment(mandate_id: str,
                              mcp_session_id: str | None = None,
                              user_email: str | None = None):
        """Forward the signed PaymentMandate to the MPP for authorisation."""
        if not mcp_session_id:
            return {"error": "mcp_session_id required"}
        pm = _session.load_payment_mandate(mcp_session_id)
        if not pm or pm.get("payment_mandate_contents", {}) \
                .get("payment_mandate_id") != mandate_id:
            return {"error": f"mandate {mandate_id!r} not found in session"}

        risk_jwt = _risk_jwt(
            user_email=user_email,
            session_id=mcp_session_id,
            token_hash=None,
        )
        result = await a2a_helpers.mpp_initiate_payment(
            payment_mandate=pm,
            risk_data=risk_jwt,
            context_id=mcp_session_id,
        )

        if result["status"] == "input_required":
            cid = _record_pending_challenge(result["challenge"], mandate_id)
            _session.set_pending_challenge(mcp_session_id,
                                           {**result["challenge"],
                                            "challenge_id": cid,
                                            "task_id": result.get("task_id"),
                                            "context_id": result.get("context_id")})
            # Step-up — no receipt yet; surface the demo OTP hint inside
            # the challenge payload so the LLM (and any future widget)
            # can show it.
            ch = dict(result["challenge"])
            ch.setdefault("demo_hint",
                          "For the mock PSP adapter, reply with OTP `123`.")
            return SubmitResultChallenge(
                challenge=ch,
                challenge_id=cid,
            ).model_dump()

        if result["status"] == "completed" and result.get("receipt"):
            receipt = result["receipt"]
            order_id = receipt.get("payment_id") or f"ord_{uuid.uuid4().hex[:10]}"
            _session.set_last_order(mcp_session_id, order_id)
            _session.clear_pending_challenge(mcp_session_id)
            payload = _build_receipt_widget_payload(
                order_id=order_id, receipt=receipt,
                payment_mandate=pm, mcp_session_id=mcp_session_id)
            return widget_result(payload, ui_uri=RECEIPT_URI)

        return SubmitResultRefused(
            status="Refused" if result["status"] == "failed" else "Error",
            error=result.get("error"),
        ).model_dump()

    @mcp.tool(
        meta=widget_meta(
            RECEIPT_URI,
            invoking="Verifying step-up…",
            invoked="Payment result",
        ),
    )
    async def complete_challenge(challenge_id: str,
                                  challenge_response: str | None = None,
                                  mcp_session_id: str | None = None
                                  ) -> dict:
        """Resolve a pending step-up challenge.

        For mock OTP: pass ``challenge_response="123"``.
        For Adyen 3DS2: leave ``challenge_response`` unset and call this
        after the shopper completes the redirect — the webhook handler
        will have written the result to the ``challenges`` table.
        """
        # 1. If the webhook already wrote a terminal status, return it.
        row = _read_challenge_status(challenge_id)
        if row and row.get("status") in ("Authorised", "Refused", "Error"):
            return {
                "status":        row["status"],
                "raw_result_code": row.get("raw_result_code"),
                "psp_reference": row.get("psp_reference"),
                "refusal_reason": row.get("refusal_reason"),
            }

        # 2. Otherwise re-call the MPP with the challenge response (mock OTP path).
        if not mcp_session_id:
            return {"status": "pending",
                    "error": "mcp_session_id required for mock-OTP completion"}
        pm = _session.load_payment_mandate(mcp_session_id)
        if not pm:
            return {"status": "pending",
                    "error": "no payment mandate in session"}

        # Pull the original task_id / context_id off the pending challenge
        # we stashed in the session at submit_payment time. Without these
        # the MPP creates a fresh Task and re-issues the challenge instead
        # of validating the response (current_task is None vs.
        # current_task.status.state == input_required, see
        # roles/merchant_payment_processor_agent/tools.py).
        pending = _session.load_pending_challenge(mcp_session_id) or {}
        prior_task_id = pending.get("task_id")
        prior_ctx_id  = pending.get("context_id") or mcp_session_id

        result = await a2a_helpers.mpp_initiate_payment(
            payment_mandate=pm,
            risk_data=_risk_jwt(user_email=None,
                                session_id=mcp_session_id,
                                token_hash=None),
            challenge_response=challenge_response,
            context_id=prior_ctx_id,
            task_id=prior_task_id,
        )
        if result["status"] == "completed" and result.get("receipt"):
            receipt = result["receipt"]
            order_id = receipt.get("payment_id") or f"ord_{uuid.uuid4().hex[:10]}"
            _session.set_last_order(mcp_session_id, order_id)
            _session.clear_pending_challenge(mcp_session_id)

            # Persist the order to past_orders + decrement inventory.
            # Gather the context we need from the payment mandate and session.
            try:
                sess = _session.get_or_create(
                    token_hash=None, user_email=None, session_id=mcp_session_id)
                cart_id = sess.get("cart_id") or ""
                user_email = sess.get("user_email") or ""
                store_location = sess.get("store_location") or "Unknown"
                # Prefer payer_email from the mandate itself.
                if pm and isinstance(pm, dict):
                    contents = pm.get("payment_mandate_contents") or {}
                    resp = contents.get("payment_response") or {}
                    user_email = resp.get("payer_email") or user_email
                    cart_id = cart_id or (contents.get("payment_details_id") or "")
                total_gbp = float(
                    (receipt.get("amount") or {}).get("value") or 0)
                placed_at = (receipt.get("timestamp")
                             or datetime.now(tz=timezone.utc).isoformat())
                if cart_id:
                    conn = _db.connect()
                    try:
                        # Resolve store_location from the cart if not in session.
                        cart = conn.execute(
                            "SELECT store_location FROM carts WHERE cart_id = ?",
                            (cart_id,)
                        ).fetchone()
                        if cart and cart["store_location"]:
                            store_location = cart["store_location"]
                        _queries.record_order(
                            order_id=order_id,
                            email=user_email,
                            placed_at=placed_at,
                            total_gbp=total_gbp,
                            store_location=store_location,
                            cart_id=cart_id,
                            conn=conn,
                        )
                        _queries.decrement_stock_from_cart(
                            cart_id=cart_id,
                            store_location=store_location,
                            conn=conn,
                        )
                        conn.commit()
                    finally:
                        conn.close()
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "record_order failed (non-fatal): %s", exc)

            payload = _build_receipt_widget_payload(
                order_id=order_id, receipt=receipt,
                payment_mandate=pm, mcp_session_id=mcp_session_id)
            return widget_result(payload, ui_uri=RECEIPT_URI)
        if result["status"] == "input_required":
            ch = dict(result.get("challenge", {}))
            ch.setdefault("demo_hint",
                          "For the mock PSP adapter, reply with OTP `123`.")
            return SubmitResultChallenge(
                challenge=ch,
                challenge_id=challenge_id,
            ).model_dump()
        return SubmitResultRefused(
            status="Refused", error=result.get("error"),
        ).model_dump()

    @mcp.tool()
    async def get_order_status(order_id: str,
                                mcp_session_id: str | None = None) -> dict:
        """Look up the latest known status for an order id from this session."""
        # The receipt is in session.last_order; full lookups would join past_orders.
        if mcp_session_id:
            sess = _session.get_or_create(token_hash=None,
                                          user_email=None,
                                          session_id=mcp_session_id)
            if sess.get("last_order_id") == order_id:
                pm_json = sess.get("payment_mandate_json")
                pm = json.loads(pm_json) if pm_json else None
                return {"order_id": order_id, "status": "Authorised",
                        "payment_mandate": pm}
        return {"order_id": order_id, "status": "unknown"}
