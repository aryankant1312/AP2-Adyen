"""Adyen zero-auth CLI — provision a real ``storedPaymentMethodId``.

Usage:

    python -m ops.adyen_zero_auth \
        --email aarav.sharma@example.com \
        --test-card 4111111111111111 \
        --expiry 03/2030 --cvc 737 \
        --holder "Aarav Sharma" \
        --alias-prefix "Visa"

Calls Adyen's Checkout ``/payments`` endpoint with ``storePaymentMethod=true``
against a tokenisation-eligible test card. On success it patches the
``merchant_on_file_methods`` row whose ``adyen_stored_payment_method_id``
currently holds a ``stored_mock_*`` placeholder for that customer, replacing
it with the freshly minted real id. Picks the row whose alias starts with
``--alias-prefix`` (case-insensitive) or, if none matches, the row whose
``last4`` matches the card's last 4 digits.

Why a separate CLI: the runtime adapter (``mpp/adyen_adapter.py``) only
ever calls ``ContAuth`` against an existing stored id; minting that id
needs a real (or test) card PAN, which the runtime path is intentionally
forbidden from touching.

Env requirements (same as the runtime adapter):

    ADYEN_API_KEY
    ADYEN_MERCHANT_ACCOUNT
    ADYEN_ENV         optional ("TEST" default)
    ADYEN_API_BASE    optional override

This script never persists the PAN — only the resulting
``recurringDetailReference`` / ``storedPaymentMethodId`` is written to
SQLite.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any

import httpx

# Re-use the existing pharmacy_data DB layer.
from pharmacy_data import queries
from pharmacy_data.db import connect


_DEFAULT_TEST_BASE = "https://checkout-test.adyen.com/v71"


def _api_base() -> str:
    if os.environ.get("ADYEN_API_BASE"):
        return os.environ["ADYEN_API_BASE"].rstrip("/")
    if os.environ.get("ADYEN_ENV", "TEST").upper() == "LIVE":
        # Per-account live URL — must be set explicitly.
        return os.environ["ADYEN_API_BASE"].rstrip("/")
    return _DEFAULT_TEST_BASE


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"missing env var: {name}")
    return val


def _parse_expiry(s: str) -> tuple[str, str]:
    # Accept "MM/YYYY" or "MM/YY".
    if "/" not in s:
        raise SystemExit(f"--expiry must be MM/YYYY or MM/YY, got {s!r}")
    mm, yy = s.split("/", 1)
    mm = mm.strip().zfill(2)
    yy = yy.strip()
    if len(yy) == 2:
        yy = "20" + yy
    if len(yy) != 4 or not yy.isdigit() or not mm.isdigit():
        raise SystemExit(f"unparseable --expiry {s!r}")
    return mm, yy


def _build_zero_auth_body(*,
                          merchant_account: str,
                          email: str,
                          card_number: str,
                          expiry_month: str,
                          expiry_year: str,
                          cvc: str,
                          holder_name: str) -> dict[str, Any]:
    """Assemble Adyen zero-auth request body.

    Notes:
      * ``shopperInteraction="Ecommerce"`` + ``recurringProcessingModel=
        "CardOnFile"`` + ``storePaymentMethod=true`` is Adyen's documented
        contract for "store the card now, charge it later under ContAuth".
      * ``amount`` is intentionally a tiny value; for cards that don't
        support true £0 zero-auth, Adyen will auto-reverse this if your
        merchant account has zero-auth disabled.
    """
    return {
        "merchantAccount":           merchant_account,
        "amount": {
            "currency": "GBP",
            "value":    0,            # zero-auth; Adyen routes this as account-verification
        },
        "reference":                 f"zero_auth_{uuid.uuid4().hex[:12]}",
        "shopperReference":          email,
        "shopperEmail":              email,
        "shopperInteraction":        "Ecommerce",
        "recurringProcessingModel":  "CardOnFile",
        "storePaymentMethod":        True,
        "paymentMethod": {
            "type":         "scheme",
            "number":       card_number,
            "expiryMonth":  expiry_month,
            "expiryYear":   expiry_year,
            "cvc":          cvc,
            "holderName":   holder_name,
        },
        "channel":                   "Web",
        "returnUrl": os.environ.get(
            "ADYEN_RETURN_URL",
            "https://example.com/ap2-poc/zero-auth-return",
        ),
        "metadata": {
            "purpose":   "ap2-pharmacy-poc:zero-auth",
            "shopper":   email,
        },
    }


def _extract_stored_id(resp: dict[str, Any]) -> str | None:
    """Pull the new stored-payment-method id from the Adyen response.

    Adyen returns it in different fields depending on the contract:
      * ``additionalData.recurring.recurringDetailReference``
      * ``additionalData.recurringDetailReference``
      * Top-level ``recurringDetailReference`` (rare, older flows)
    """
    add = resp.get("additionalData") or {}
    return (
        (add.get("recurring") or {}).get("recurringDetailReference")
        or add.get("recurring.recurringDetailReference")
        or add.get("recurringDetailReference")
        or resp.get("recurringDetailReference")
    )


def _pick_target_mof_row(*, email: str, card_last4: str,
                          alias_prefix: str | None,
                          conn) -> dict[str, Any]:
    """Pick which ``merchant_on_file_methods`` row to patch.

    Priority:
      1. row whose alias starts with ``alias_prefix`` (case-insensitive)
         AND whose ``adyen_stored_payment_method_id`` still looks mock
         (``stored_mock_*``).
      2. row whose ``last4`` == ``card_last4`` AND mock id.
      3. any row for this email with a mock id.
    Falls back to error if none.
    """
    rows = queries.list_mof_methods(email, include_expired=True, conn=conn)
    if not rows:
        raise SystemExit(f"no merchant_on_file_methods rows for {email!r}")

    mock_rows = [r for r in rows
                 if (r.get("adyen_stored_payment_method_id") or "")
                 .startswith("stored_mock_")]
    if not mock_rows:
        raise SystemExit(
            f"all stored ids for {email!r} already look real "
            f"(no 'stored_mock_*' placeholder to replace)"
        )

    if alias_prefix:
        ap = alias_prefix.lower()
        for r in mock_rows:
            if (r.get("alias") or "").lower().startswith(ap):
                return r
    for r in mock_rows:
        if (r.get("last4") or "") == card_last4:
            return r
    return mock_rows[0]


def _post_payments(body: dict[str, Any]) -> dict[str, Any]:
    base = _api_base()
    api_key = _required_env("ADYEN_API_KEY")
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{base}/payments",
            headers={
                "X-API-Key":     api_key,
                "Content-Type":  "application/json",
            },
            json=body,
        )
    if r.status_code >= 500:
        raise SystemExit(f"adyen 5xx {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError as e:
        raise SystemExit(f"adyen returned non-json ({e}): {r.text[:400]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", required=True,
                   help="customer email (must exist in customers table)")
    p.add_argument("--test-card", required=True,
                   help="test PAN, e.g. 4111111111111111")
    p.add_argument("--expiry", default="03/2030",
                   help="MM/YYYY or MM/YY, default 03/2030")
    p.add_argument("--cvc", default="737",
                   help="CVC, default 737 (Adyen test value)")
    p.add_argument("--holder", default="AP2 POC Test",
                   help="cardholder name")
    p.add_argument("--alias-prefix", default=None,
                   help="prefer the MOF row whose alias starts with this "
                        "(case-insensitive); falls back to last4 match")
    p.add_argument("--db", default=None,
                   help="override SQLite DB path (defaults to repo data dir)")
    p.add_argument("--dry-run", action="store_true",
                   help="show the request body and target row, don't call Adyen")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    card = "".join(c for c in args.test_card if c.isdigit())
    if len(card) < 12:
        raise SystemExit("--test-card must be a numeric PAN")
    last4 = card[-4:]
    mm, yyyy = _parse_expiry(args.expiry)

    db_conn = connect(args.db) if args.db else connect()
    target = _pick_target_mof_row(
        email=args.email, card_last4=last4,
        alias_prefix=args.alias_prefix, conn=db_conn,
    )
    logging.info("target MOF row id=%s alias=%r last4=%s placeholder=%s",
                 target.get("id"), target.get("alias"),
                 target.get("last4"),
                 target.get("adyen_stored_payment_method_id"))

    body = _build_zero_auth_body(
        merchant_account=_required_env("ADYEN_MERCHANT_ACCOUNT"),
        email=args.email,
        card_number=card,
        expiry_month=mm, expiry_year=yyyy,
        cvc=args.cvc, holder_name=args.holder,
    )

    if args.dry_run:
        # Redact card before printing.
        redacted = json.loads(json.dumps(body))
        pm = redacted["paymentMethod"]
        pm["number"] = f"****{last4}"
        pm["cvc"]    = "***"
        print(json.dumps(redacted, indent=2))
        return 0

    resp = _post_payments(body)
    logging.debug("adyen response: %s", json.dumps(resp)[:1000])

    rc = resp.get("resultCode")
    stored_id = _extract_stored_id(resp)
    if rc not in ("Authorised", "Received") or not stored_id:
        print(json.dumps(
            {"ok": False, "resultCode": rc,
             "refusalReason": resp.get("refusalReason"),
             "pspReference": resp.get("pspReference"),
             "raw_keys": list(resp.keys())},
            indent=2))
        return 2

    queries.upsert_mof_stored_id(
        mof_id=target["id"],
        real_stored_id=stored_id,
        conn=db_conn,
    )
    db_conn.commit()
    print(json.dumps({
        "ok":                       True,
        "email":                    args.email,
        "mof_id":                   target["id"],
        "alias":                    target.get("alias"),
        "previous_stored_id":       target.get("adyen_stored_payment_method_id"),
        "new_stored_id":            stored_id,
        "psp_reference":            resp.get("pspReference"),
        "result_code":              rc,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
