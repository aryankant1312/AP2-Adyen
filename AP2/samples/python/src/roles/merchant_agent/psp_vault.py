# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0

"""Mock PSP-layer vault.

This module models the boundary between the merchant and the PSP. In the
SQLite-backed POC, the only "raw" credential the merchant ever sees is
the ``adyen_stored_payment_method_id`` (which is itself a token, not a
PAN). For the Adyen real-PSP path, this module is bypassed in favour of
``merchant_agent/psp/adyen_adapter.py``.

Public API (preserved from the in-memory version):
    describe(psp_ref)       -> safe agent-layer description
    is_still_valid(psp_ref) -> bool
    mint_charge_token(psp_ref, user_email)
    bind_mandate(token, payment_mandate_id)
    charge(token, payment_mandate_id, amount, currency)
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import date
from typing import Any

from pharmacy_data import db as _pd_db


# Short-lived charge tokens (mock PSP). These never need to survive a
# restart; TTL is 15 min by design.
_charge_tokens: dict[str, dict[str, Any]] = {}
_CHARGE_TOKEN_TTL_SECONDS = 15 * 60


def _lookup_by_psp_ref(psp_ref: str) -> dict[str, Any] | None:
    """Find the merchant_on_file_methods row whose stored_id == psp_ref."""
    conn = _pd_db.connect()
    row = conn.execute(
        "SELECT id, email, adyen_stored_payment_method_id, brand, last4, "
        "alias, expiry_month, expiry_year, is_expired "
        "FROM merchant_on_file_methods "
        "WHERE adyen_stored_payment_method_id = ? LIMIT 1",
        (psp_ref,),
    ).fetchone()
    return dict(row) if row else None


def describe(psp_ref: str) -> dict[str, Any]:
    """SAFE description: alias + last4 + brand + expiry + eligibility."""
    row = _lookup_by_psp_ref(psp_ref)
    if not row:
        raise KeyError(psp_ref)
    return {
        "psp_ref":               psp_ref,
        "type":                  "CARD",
        "brand":                 row["brand"],
        "last4":                 row["last4"],
        "exp_month":             f"{row['expiry_month']:02d}",
        "exp_year":              str(row["expiry_year"]),
        "network_token_eligible": row["is_expired"] == 0,
        "alias":                 row["alias"],
    }


def is_still_valid(psp_ref: str) -> bool:
    """Eligibility check: row exists, not flagged expired, and not past expiry date."""
    row = _lookup_by_psp_ref(psp_ref)
    if not row:
        return False
    if row["is_expired"]:
        return False
    today = date.today()
    if row["expiry_year"] < today.year:
        return False
    if row["expiry_year"] == today.year and row["expiry_month"] < today.month:
        return False
    return True


def mint_charge_token(psp_ref: str, user_email: str) -> str:
    """Mint a one-shot charge token bound to (psp_ref, user_email)."""
    if not _lookup_by_psp_ref(psp_ref):
        raise KeyError(psp_ref)
    token = f"ct_{secrets.token_urlsafe(18)}"
    _charge_tokens[token] = {
        "psp_ref":            psp_ref,
        "user_email":         user_email,
        "expires_at":         time.time() + _CHARGE_TOKEN_TTL_SECONDS,
        "payment_mandate_id": None,
    }
    return token


def bind_mandate(token: str, payment_mandate_id: str) -> None:
    """Bind a charge token to a specific payment mandate. One-shot binding."""
    record = _charge_tokens.get(token)
    if not record:
        raise ValueError("Unknown charge token")
    if record["payment_mandate_id"] is not None:
        raise ValueError("Charge token already bound")
    record["payment_mandate_id"] = payment_mandate_id


def charge(token: str, payment_mandate_id: str, amount: str,
           currency: str) -> dict[str, Any]:
    """Mock-PSP charge. Validates token + binding, returns synthetic receipt."""
    record = _charge_tokens.get(token)
    if not record:
        return {"status": "failed", "reason": "unknown_token"}
    if record["expires_at"] < time.time():
        return {"status": "failed", "reason": "token_expired"}
    if record["payment_mandate_id"] != payment_mandate_id:
        return {"status": "failed", "reason": "mandate_mismatch"}

    psp_txn_id = f"psp_txn_{uuid.uuid4().hex[:12]}"
    auth_code  = secrets.token_hex(3).upper()
    del _charge_tokens[token]
    return {
        "status":              "success",
        "psp_transaction_id":  psp_txn_id,
        "auth_code":           auth_code,
        "amount":              amount,
        "currency":            currency,
        "payment_method_kind": "CARD",
    }
