"""Pydantic models for MCP tool inputs / outputs.

Every tool returns *structured JSON* so Claude / ChatGPT don't need to
parse free text. The shapes here are the contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- catalog

class ProductSummary(BaseModel):
    product_ref:    str
    title:          str
    brand:          str | None = None
    category:       str | None = None
    price_gbp:      float
    in_stock:       bool
    qty_in_stock:   int | None = None
    shelf:          str | None = None


class ProductDetail(ProductSummary):
    description:    str | None = None
    policy:         str | None = None
    ingredients:    str | None = None
    base_price_gbp: float | None = None


class StoreInventoryRow(BaseModel):
    product_ref:    str
    title:          str
    brand:          str | None = None
    category:       str | None = None
    qty_in_stock:   int
    local_price_gbp: float | None = None
    shelf_location: str | None = None


# --------------------------------------------------------------------- cart

class CartLine(BaseModel):
    product_ref:    str
    qty:            int
    unit_price_gbp: float
    title:          str | None = None


class CartView(BaseModel):
    cart_id:        str
    user_email:     str | None = None
    store_location: str | None = None
    items:          list[CartLine] = Field(default_factory=list)
    subtotal_gbp:   float
    shipping_gbp:   float = 0.0
    tax_gbp:        float = 0.0
    total_gbp:      float
    expires_at:     str | None = None


class CartFinalised(BaseModel):
    cart_id:                  str
    cart_mandate:             dict[str, Any]
    merchant_authorization:   str
    total_gbp:                float
    currency:                 str = "GBP"


# --------------------------------------------------------------------- payment methods

class PaymentMethodSummary(BaseModel):
    alias:          str
    source:         Literal["merchant_on_file", "credentials_provider"]
    brand:          str | None = None
    last4:          str | None = None
    display_name:   str | None = None
    raw:            dict[str, Any] = Field(default_factory=dict)


class PaymentMethodToken(BaseModel):
    token:          str
    source:         Literal["merchant_on_file", "credentials_provider"]
    alias:          str | None = None
    brand:          str | None = None
    last4:          str | None = None


# --------------------------------------------------------------------- mandates

class PaymentMandateBuilt(BaseModel):
    payment_mandate_id: str
    contents:           dict[str, Any]
    signed:             bool = False


class SubmitResultAuthorized(BaseModel):
    status:        Literal["Authorised"] = "Authorised"
    order_id:      str
    receipt:       dict[str, Any]


class SubmitResultChallenge(BaseModel):
    status:        Literal["ChallengeShopper"] = "ChallengeShopper"
    challenge:     dict[str, Any]
    challenge_id:  str | None = None


class SubmitResultRefused(BaseModel):
    status:        Literal["Refused", "Error"]
    error:         str | None = None


# --------------------------------------------------------------------- history

class PastOrderHead(BaseModel):
    order_id:        str
    placed_at:       str
    total_gbp:       float
    store_location:  str | None = None
    stored_method_id: str | None = None


class PastOrderDetail(PastOrderHead):
    lines:           list[dict[str, Any]] = Field(default_factory=list)
