"""Pure-python helpers for invoking the AP2 sample agents over A2A.

These helpers exist so that *any* outer surface — the legacy ADK shopping
agent, the new MCP gateway, ad-hoc CLI scripts, integration tests — can
talk to the Merchant Agent (MA), Credentials Provider (CP), and Merchant
Payment Processor (MPP) without dragging ADK's ``ToolContext`` into
scope.

Design rules:
  * No globals beyond a small per-process client cache (one
    ``PaymentRemoteA2aClient`` per base URL). Connections are lazy.
  * Every helper takes its target URL via env var (matching the
    docker-compose setup) with explicit kwarg overrides for tests.
  * Every helper returns *plain Python dicts* (already
    ``model_dump``-ed) — no Pydantic objects leak across the boundary,
    so callers in different runtimes (FastMCP, pytest, ADK) can serialise
    freely.
  * Errors are always raised as ``A2AHelperError`` with structured
    context — never silently dropped.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from a2a import types as a2a_types

from ap2.types.contact_picker import ContactAddress
from ap2.types.mandate import (
    CART_MANDATE_DATA_KEY,
    INTENT_MANDATE_DATA_KEY,
    PAYMENT_MANDATE_DATA_KEY,
    CartMandate,
    IntentMandate,
    PaymentMandate,
)
from ap2.types.payment_request import PaymentMethodData
from ap2.types.payment_receipt import PAYMENT_RECEIPT_DATA_KEY, PaymentReceipt

from .a2a_extension_utils import EXTENSION_URI
from .a2a_message_builder import A2aMessageBuilder
from .artifact_utils import find_canonical_objects, get_first_data_part
from .message_utils import find_data_part
from .payment_remote_a2a_client import PaymentRemoteA2aClient


_LOG = logging.getLogger("ap2.common.a2a_helpers")


# --------------------------------------------------------------------- errors

class A2AHelperError(RuntimeError):
    """Raised when an A2A round-trip cannot be parsed into a useful result."""

    def __init__(self, message: str, *, target: str | None = None,
                 task_state: str | None = None,
                 raw: Any = None) -> None:
        super().__init__(message)
        self.target = target
        self.task_state = task_state
        self.raw = raw


# --------------------------------------------------------------------- client cache

_CLIENTS: dict[str, PaymentRemoteA2aClient] = {}


def _client_for(name: str, base_url: str) -> PaymentRemoteA2aClient:
    """One ``PaymentRemoteA2aClient`` per ``base_url`` for the process."""
    key = f"{name}@{base_url.rstrip('/')}"
    c = _CLIENTS.get(key)
    if c is None:
        c = PaymentRemoteA2aClient(
            name=name, base_url=base_url.rstrip("/"),
            required_extensions={EXTENSION_URI},
        )
        _CLIENTS[key] = c
    return c


# Each AP2 agent mounts its JSON-RPC handler — and therefore its
# ``/.well-known/agent-card.json`` — under a per-role prefix. If the
# operator only sets the host:port part in the env var, fold the prefix
# in here so we don't 404 on agent-card discovery.
_RPC_SUFFIXES: dict[str, str] = {
    "MERCHANT_AGENT_URL":             "/a2a/merchant_agent",
    "CREDENTIALS_PROVIDER_URL":       "/a2a/credentials_provider",
    "MERCHANT_PAYMENT_PROCESSOR_URL": "/a2a/merchant_payment_processor_agent",
}


def _resolve_url(env_var: str, override: str | None) -> str:
    val = override or os.environ.get(env_var)
    if not val:
        raise A2AHelperError(
            f"missing service URL: pass override or set ${env_var}",
            target=env_var,
        )
    suffix = _RPC_SUFFIXES.get(env_var)
    if suffix and suffix not in val:
        val = val.rstrip("/") + suffix
    return val


# Identity stamp every outbound A2A request carries. Backend agents
# whitelist this against ``KNOWN_SHOPPING_AGENTS`` to gate the
# A2A surface — see roles/merchant_agent/agent_executor.py.
SHOPPING_AGENT_ID = os.environ.get("AP2_SHOPPING_AGENT_ID",
                                   "ap2_mcp_gateway")


def _stamp_identity(builder: A2aMessageBuilder,
                    *, tool_hint: str | None = None) -> A2aMessageBuilder:
    """Add the shopping-agent identity (and optional ``tool_hint``) to every
    outbound message.

    The ``tool_hint`` is honoured by ``BaseServerExecutor._handle_request``
    and bypasses the Gemini-Flash tool resolver — which is non-deterministic
    and was occasionally routing a "list payment methods" prompt to
    ``find_items_workflow`` (and back again) across retries.
    """
    builder.add_data("shopping_agent_id", SHOPPING_AGENT_ID)
    if tool_hint:
        builder.add_data("tool_hint", tool_hint)
    return builder


# --------------------------------------------------------------------- task helpers

def _data_parts(task: a2a_types.Task) -> list[dict[str, Any]]:
    """Flatten every DataPart payload off a Task.

    Walks three places, in priority order:
      1. ``task.artifacts``  — where ``add_artifact`` puts results.
      2. ``task.status.message`` — final agent message.
      3. ``task.history``   — full request/response history.

    Artifacts come first because that's where most response payloads
    actually live; history first would have us pick up the request's
    own DataParts on round-trips that echo them back.
    """
    parts: list[dict[str, Any]] = []
    for art in (task.artifacts or []):
        for p in (getattr(art, "parts", None) or []):
            root = getattr(p, "root", None)
            data = getattr(root, "data", None)
            if isinstance(data, dict):
                parts.append(data)
    if task.status and task.status.message:
        for p in (task.status.message.parts or []):
            root = getattr(p, "root", None)
            data = getattr(root, "data", None)
            if isinstance(data, dict):
                parts.append(data)
    for msg in (task.history or []):
        for p in (msg.parts or []):
            root = getattr(p, "root", None)
            data = getattr(root, "data", None)
            if isinstance(data, dict):
                parts.append(data)
    return parts


def _text_parts(task: a2a_types.Task) -> list[str]:
    out: list[str] = []
    for msg in (task.history or []):
        for p in (msg.parts or []):
            root = getattr(p, "root", None)
            text = getattr(root, "text", None)
            if isinstance(text, str):
                out.append(text)
    if task.status and task.status.message:
        for p in (task.status.message.parts or []):
            root = getattr(p, "root", None)
            text = getattr(root, "text", None)
            if isinstance(text, str):
                out.append(text)
    return out


def _state_value(task: a2a_types.Task) -> str | None:
    state = getattr(getattr(task, "status", None), "state", None)
    if state is None:
        return None
    return getattr(state, "value", str(state))


# ====================================================================
# Merchant Agent
# ====================================================================

def _ma_url(override: str | None) -> str:
    return _resolve_url("MERCHANT_AGENT_URL", override)


async def merchant_find_products(
    *,
    intent_mandate: IntentMandate | dict,
    user_email: str | None = None,
    store_location: str | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Ask the merchant agent for matching products → returns CartMandates.

    Returns ``{"cart_mandates": [<dict>, ...], "extras": [...]}``.
    ``extras`` carries the per-product DataPart fields the catalog agent
    surfaces alongside each CartMandate (``product_ref``, ``brand``,
    ``shelf_location``, ``qty_in_stock`` etc).
    """
    intent_dump = (intent_mandate
                   if isinstance(intent_mandate, dict)
                   else intent_mandate.model_dump())
    builder = (A2aMessageBuilder()
               .add_text(intent_dump.get("natural_language_description") or "")
               .add_data(INTENT_MANDATE_DATA_KEY, intent_dump))
    if user_email:
        builder.add_data("user_email", user_email)
    if store_location:
        builder.add_data("store_location", store_location)
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("merchant_agent", _ma_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(builder, tool_hint="find_items_workflow").build())

    cart_mandates = find_canonical_objects(
        task.artifacts or [], CART_MANDATE_DATA_KEY, CartMandate)
    return {
        "cart_mandates": [m.model_dump() for m in cart_mandates],
        "extras":        _data_parts(task),
        "task_state":    _state_value(task),
    }


async def merchant_update_cart(
    *,
    cart_mandate: CartMandate | dict,
    shipping_address: ContactAddress | dict,
    risk_data: str | dict | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Ask the merchant agent to recompute totals + bind shipping address.

    Returns a fresh CartMandate dict with totals filled in.
    """
    cart_dump = (cart_mandate
                 if isinstance(cart_mandate, dict)
                 else cart_mandate.model_dump())
    addr_dump = (shipping_address
                 if isinstance(shipping_address, dict)
                 else shipping_address.model_dump())

    builder = (A2aMessageBuilder()
               .add_text("Please update the cart with these shipping details.")
               .add_data(CART_MANDATE_DATA_KEY, cart_dump)
               .add_data("shipping_address", addr_dump))
    if risk_data is not None:
        if isinstance(risk_data, dict):
            builder.add_data("risk_data", risk_data)
        else:
            builder.add_data("risk_data", str(risk_data))
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("merchant_agent", _ma_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(builder, tool_hint="update_cart").build())
    updated = find_canonical_objects(
        task.artifacts or [], CART_MANDATE_DATA_KEY, CartMandate)
    if not updated:
        raise A2AHelperError(
            "merchant did not return an updated CartMandate",
            target="merchant_agent", task_state=_state_value(task),
            raw=_data_parts(task),
        )
    return updated[0].model_dump()


async def merchant_get_on_file_methods(
    *,
    user_email: str,
    intent_mandate: IntentMandate | dict | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> list[dict[str, Any]]:
    """Look up the customer's saved (merchant-on-file) payment methods.

    Returns a list of ``{"alias", "psp_ref", "brand", "last4", ...}``
    dicts. Empty list ⇒ caller should fall back to the Credentials
    Provider.
    """
    builder = (A2aMessageBuilder()
               .add_text("List the saved payment methods on file for this user.")
               .add_data("user_email", user_email))
    if intent_mandate is not None:
        intent_dump = (intent_mandate if isinstance(intent_mandate, dict)
                       else intent_mandate.model_dump())
        builder.add_data(INTENT_MANDATE_DATA_KEY, intent_dump)
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("merchant_agent", _ma_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(
                builder,
                tool_hint="get_merchant_on_file_payment_methods",
            ).build())
    parts = _data_parts(task)
    # MA emits the list under "on_file_payment_methods" (see
    # roles/merchant_agent/tools.py::merchant_on_file). Accept the
    # alternative spelling too in case future versions change it.
    methods = (find_data_part("on_file_payment_methods", parts)
               or find_data_part("merchant_on_file_methods", parts))
    return list(methods or [])


async def merchant_create_on_file_token(
    *,
    user_email: str,
    alias: str,
    cart_mandate: CartMandate | dict | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Mint a charge token for an alias the customer chose.

    Returns ``{"token", "source": "merchant_on_file", ...}``.
    """
    builder = (A2aMessageBuilder()
               # MA's create_merchant_on_file_token expects the alias under
               # "payment_method_alias" (not "alias").
               .add_text(f"Create a charge token for {alias}.")
               .add_data("user_email", user_email)
               .add_data("payment_method_alias", alias))
    if cart_mandate is not None:
        cart_dump = (cart_mandate if isinstance(cart_mandate, dict)
                     else cart_mandate.model_dump())
        builder.add_data(CART_MANDATE_DATA_KEY, cart_dump)
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("merchant_agent", _ma_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(
                builder, tool_hint="create_merchant_on_file_token",
            ).build())
    parts = _data_parts(task)

    # MA emits a flat data part: {source, alias, token}. Find the first
    # part that carries a `token` field, with structured fallbacks for
    # legacy/alternative shapes.
    token_obj: dict | None = None
    for p in parts:
        if isinstance(p, dict) and "token" in p:
            token_obj = dict(p)
            break
    if token_obj is None:
        # Legacy keys we used to send under (kept for forward compat).
        token_obj = (find_data_part("merchant_on_file_token", parts)
                     or find_data_part("payment_method_token", parts))

    if not token_obj:
        raise A2AHelperError(
            "merchant did not return a merchant-on-file token",
            target="merchant_agent", task_state=_state_value(task),
            raw=parts,
        )
    if isinstance(token_obj, str):
        token_obj = {"token": token_obj, "source": "merchant_on_file"}
    token_obj.setdefault("source", "merchant_on_file")
    return token_obj


# ====================================================================
# Credentials Provider
# ====================================================================

def _cp_url(override: str | None) -> str:
    return _resolve_url("CREDENTIALS_PROVIDER_URL", override)


async def cp_search_payment_methods(
    *,
    user_email: str,
    accepted_methods: list[PaymentMethodData | dict] | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> list[dict[str, Any]]:
    """Ask the CP for compatible payment methods for this user."""
    builder = (A2aMessageBuilder()
               .add_text("List payment methods this user can use.")
               .add_data("user_email", user_email))
    if accepted_methods:
        dumped = [m if isinstance(m, dict) else m.model_dump()
                  for m in accepted_methods]
        builder.add_data("accepted_payment_methods", dumped)
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("credentials_provider",
                             _cp_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(
                builder, tool_hint="handle_search_payment_methods",
            ).build())
    methods = find_data_part("payment_methods", _data_parts(task))
    return list(methods or [])


async def cp_create_payment_credential_token(
    *,
    user_email: str,
    payment_method_id: str,
    cart_mandate: CartMandate | dict | None = None,
    context_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Ask the CP to mint a payment credential token for a chosen method."""
    builder = (A2aMessageBuilder()
               .add_text("Create a payment credential token for this method.")
               .add_data("user_email", user_email)
               .add_data("payment_method_id", payment_method_id))
    if cart_mandate is not None:
        cart_dump = (cart_mandate if isinstance(cart_mandate, dict)
                     else cart_mandate.model_dump())
        builder.add_data(CART_MANDATE_DATA_KEY, cart_dump)
    if context_id:
        builder.set_context_id(context_id)

    task = await _client_for("credentials_provider",
                             _cp_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(
                builder, tool_hint="handle_create_payment_credential_token",
            ).build())
    parts = _data_parts(task)
    token = find_data_part("payment_credential_token", parts) \
        or find_data_part("payment_method_token", parts)
    if not token:
        raise A2AHelperError(
            "credentials provider did not return a token",
            target="credentials_provider",
            task_state=_state_value(task), raw=parts,
        )
    if isinstance(token, str):
        token = {"token": token, "source": "credentials_provider"}
    token.setdefault("source", "credentials_provider")
    return token


# ====================================================================
# Merchant Payment Processor
# ====================================================================

def _mpp_url(override: str | None) -> str:
    return _resolve_url("MERCHANT_PAYMENT_PROCESSOR_URL", override)


async def mpp_initiate_payment(
    *,
    payment_mandate: PaymentMandate | dict,
    risk_data: str | dict | None = None,
    challenge_response: str | None = None,
    context_id: str | None = None,
    task_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Send a PaymentMandate to the MPP. Returns one of:

      {"status": "completed", "receipt": {...}}
      {"status": "input_required", "challenge": {...}}
      {"status": "failed", "error": "...", "raw": [...]}

    For step-up resolution the caller MUST pass the original ``task_id``
    (and matching ``context_id``) returned in the previous
    ``input_required`` payload — otherwise the MPP creates a fresh
    Task and re-issues the challenge instead of validating the response.
    """
    pm_dump = (payment_mandate if isinstance(payment_mandate, dict)
               else payment_mandate.model_dump())
    builder = (A2aMessageBuilder()
               .add_text("Please initiate payment for this mandate.")
               .add_data(PAYMENT_MANDATE_DATA_KEY, pm_dump))
    if risk_data is not None:
        if isinstance(risk_data, dict):
            builder.add_data("risk_data", risk_data)
        else:
            builder.add_data("risk_data", str(risk_data))
    if challenge_response is not None:
        builder.add_data("challenge_response", challenge_response)
    if context_id:
        builder.set_context_id(context_id)
    if task_id:
        builder.set_task_id(task_id)

    task = await _client_for("merchant_payment_processor",
                             _mpp_url(base_url)) \
        .send_a2a_message(
            _stamp_identity(builder, tool_hint="initiate_payment").build())
    state = _state_value(task)
    parts = _data_parts(task)

    # The A2A SDK's TaskState.input_required serializes as the hyphenated
    # string "input-required" on the wire. Accept both spellings so we
    # don't silently treat a step-up challenge as a hard failure.
    if state in ("input_required", "input-required"):
        challenge = find_data_part("challenge", parts) or {}
        return {
            "status":     "input_required",
            "challenge":  challenge,
            "task_id":    task.id,
            "context_id": task.context_id,
        }

    if state in ("completed", "succeeded"):
        receipts = find_canonical_objects(
            task.artifacts or [], PAYMENT_RECEIPT_DATA_KEY, PaymentReceipt)
        if receipts:
            return {
                "status":  "completed",
                "receipt": receipts[0].model_dump(),
                "task_id": task.id,
            }
        # Fallback: surface raw text if no receipt artifact.
        return {
            "status": "completed",
            "receipt": None,
            "messages": _text_parts(task),
            "task_id": task.id,
        }

    return {
        "status":  "failed",
        "error":   "; ".join(_text_parts(task)) or f"unexpected state {state}",
        "task_state": state,
        "raw":     parts,
    }


# ====================================================================
# Convenience: synchronous wrappers (handy for CLI / tests)
# ====================================================================

def run_sync(coro):
    """Execute an async helper from sync code without re-entering a loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Caller is already inside an event loop — that's a bug here.
            raise RuntimeError(
                "run_sync called from inside a running event loop; "
                "await the coroutine directly instead."
            )
    except RuntimeError:
        pass
    return asyncio.run(coro)
