# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SQLite-backed catalog sub-agent.

Replaces the original Gemini-driven catalog hallucinator with a real
keyword search over the pharmacy_data products + inventory tables. Each
matching product becomes its own ``CartMandate`` artifact so the
shopping agent / MCP gateway can render a picker and forward the
chosen one back through ``update_cart``.

Currency is GBP throughout. ``store_location`` (optional in the inbound
data parts) ranks results by store stock.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import DataPart, Part, Task, TextPart

from .. import storage
from ap2.types.mandate import (
    CART_MANDATE_DATA_KEY,
    CartContents,
    CartMandate,
    INTENT_MANDATE_DATA_KEY,
    IntentMandate,
)
from ap2.types.payment_request import (
    PaymentCurrencyAmount,
    PaymentDetailsInit,
    PaymentItem,
    PaymentMethodData,
    PaymentOptions,
    PaymentRequest,
)
from common import message_utils
from common.signing import merchant_authorization_jwt
from pharmacy_data import queries

_MERCHANT_NAME = os.environ.get("MERCHANT_NAME", "Pharmacy POC")
_DEFAULT_CART_TTL_MIN = int(os.environ.get("CART_TTL_MIN", "30"))


async def find_items_workflow(
    data_parts: list[dict[str, Any]],
    updater: TaskUpdater,
    current_task: Task | None,
) -> None:
    """Search SQLite for products matching the IntentMandate and emit carts."""
    intent_mandate = message_utils.parse_canonical_object(
        INTENT_MANDATE_DATA_KEY, data_parts, IntentMandate
    )
    intent_text = intent_mandate.natural_language_description.strip()
    store_location = message_utils.find_data_part("store_location", data_parts)

    # SKU-first path. When the gateway's `finalize_cart` calls us, it
    # carries the exact product_refs in `intent_mandate.skus` — there's
    # no need (and it's actively wrong) to keyword-search again, since
    # the cart was already assembled. Honour the SKUs verbatim.
    sku_list = list(intent_mandate.skus or [])
    products: list[dict[str, Any]] = []
    if sku_list:
        for ref in sku_list:
            prod = queries.get_product(ref)
            if not prod:
                continue
            if store_location:
                priced = queries.price_at_store(ref, store_location)
                if priced:
                    # Merge per-store price + shelf into the product dict.
                    prod = {**prod, **priced}
            products.append(prod)

    if not products:
        products = queries.search_products(
            query=intent_text, store_location=store_location, limit=5
        )

    if not products:
        # Fall back to a broader brand/category search using the first word.
        first_token = intent_text.split()[0] if intent_text else ""
        if first_token:
            products = queries.search_products(
                query=first_token, store_location=store_location, limit=5
            )

    if not products:
        msg = updater.new_agent_message(
            parts=[Part(root=TextPart(
                text=(
                    f"No catalog matches for '{intent_text}'. Try a different "
                    "keyword such as 'paracetamol', 'allergy', or 'cough'."
                )
            ))]
        )
        await updater.failed(message=msg)
        return

    payment_method_kind = os.environ.get("PAYMENT_METHOD", "CARD")
    current_time = datetime.now(timezone.utc)

    for idx, prod in enumerate(products, start=1):
        await _emit_cart_mandate(
            prod=prod,
            idx=idx,
            current_time=current_time,
            updater=updater,
            payment_method=payment_method_kind,
        )

    risk_data = _collect_risk_data(updater)
    updater.add_artifact([
        Part(root=DataPart(data={"risk_data": risk_data})),
    ])
    await updater.complete()


async def _emit_cart_mandate(
    prod: dict[str, Any],
    idx: int,
    current_time: datetime,
    updater: TaskUpdater,
    payment_method: str,
) -> None:
    """Build + persist + emit a single CartMandate artifact for one product."""
    price_value = float(prod.get("price_gbp") or prod["base_price_gbp"])
    label = f"{prod['title']}"

    item = PaymentItem(
        label=label,
        amount=PaymentCurrencyAmount(currency="GBP", value=price_value),
    )

    if payment_method == "x402":
        method_data = [
            PaymentMethodData(
                supported_methods="https://www.x402.org/",
                data={
                    "x402Version": 1,
                    "accepts": [{
                        "scheme": "exact",
                        "network": "base",
                        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bda02913",
                        "payTo": "0xMerchantWalletAddress",
                        "maxAmountRequired": str(int(price_value * 1_000_000)),
                    }],
                },
            )
        ]
    else:
        method_data = [
            PaymentMethodData(
                supported_methods="CARD",
                data={"network": ["visa", "mastercard", "amex"]},
            )
        ]

    payment_request = PaymentRequest(
        method_data=method_data,
        details=PaymentDetailsInit(
            id=f"order_{prod['product_ref']}_{idx}",
            display_items=[item],
            total=PaymentItem(label="Total", amount=item.amount),
        ),
        options=PaymentOptions(request_shipping=True),
    )

    cart_id = f"cart_{prod['product_ref']}_{idx}"
    cart_contents = CartContents(
        id=cart_id,
        user_cart_confirmation_required=True,
        payment_request=payment_request,
        cart_expiry=(current_time + timedelta(
            minutes=_DEFAULT_CART_TTL_MIN
        )).isoformat(),
        merchant_name=_MERCHANT_NAME,
    )

    cart_mandate = CartMandate(contents=cart_contents)
    # RS256-sign the contents; downstream agents verify against
    # /.well-known/merchant-key.pem.
    cart_mandate.merchant_authorization = merchant_authorization_jwt(
        cart_contents.model_dump()
    )
    storage.set_cart_mandate(cart_id, cart_mandate)
    await updater.add_artifact([
        Part(root=DataPart(data={
            CART_MANDATE_DATA_KEY: cart_mandate.model_dump(),
            "product_ref": prod["product_ref"],
            "category": prod["category"],
            "brand": prod["brand"],
            "shelf_location": prod.get("shelf_location") or "",
            "qty_in_stock": prod.get("qty_in_stock"),
        }))
    ])


def _collect_risk_data(updater: TaskUpdater) -> str:
    """Issue a signed merchant-side risk JWT for the in-flight context.

    The MA stamps a small ES256/RS256-signed token here so downstream
    agents (MPP) can verify the risk signal hasn't been swapped en
    route. Format mirrors the Forter / Sardine / Signifyd shape.
    """
    risk_jwt = merchant_authorization_jwt(
        {"context_id": updater.context_id, "schema": "ap2-poc-merchant-risk-v1"},
        audience="ap2-risk-data",
        ttl_seconds=600,
    )
    storage.set_risk_data(updater.context_id, risk_jwt)
    return risk_jwt
