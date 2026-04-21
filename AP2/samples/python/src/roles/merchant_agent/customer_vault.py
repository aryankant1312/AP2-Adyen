# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0

"""Merchant-side customer vault, now SQLite-backed.

Public API is identical to the previous in-memory version so callers
(tools.py, the agent_executor) don't change. Behind the scenes, lookups
hit the ``customers`` and ``merchant_on_file_methods`` tables seeded by
``pharmacy_data.seed``.

For the active PSP adapter (mock/Adyen) we delegate the alias->PSP-ref
side to ``psp_vault.describe`` which now reads from SQLite as well, so
both halves see the same data.
"""

from __future__ import annotations

from typing import Any

from . import psp_vault
from pharmacy_data import queries


def get_on_file_methods(user_email: str) -> list[dict[str, Any]]:
    """Returns agent-layer-safe descriptions of saved methods for this user.

    Filters out anything flagged as no-longer-chargeable. Each returned
    entry is safe to forward to the shopping agent / MCP gateway: contains
    no PAN / CVV / raw credentials of any kind.
    """
    rows = queries.list_mof_methods(user_email, include_expired=False)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({
            "alias":             row["alias"],
            "nickname":          row["alias"],
            "type":              "CARD",
            "brand":             row["brand"],
            "last_used_summary": row["last4"],
            # NOTE: still no psp_ref / stored_payment_method_id leaks upward.
        })
    return out


def resolve_alias_to_psp_ref(user_email: str, alias: str) -> str | None:
    """Merchant-internal helper: alias shown to agent -> PSP reference.

    For the SQLite-backed vault, the PSP reference is the row's
    ``adyen_stored_payment_method_id`` (which may be a ``stored_mock_*``
    value until the Adyen zero-auth CLI has been run for this method).
    """
    row = queries.get_mof_by_alias(user_email, alias)
    if not row:
        return None
    if not psp_vault.is_still_valid(row["adyen_stored_payment_method_id"]):
        return None
    return row["adyen_stored_payment_method_id"]
