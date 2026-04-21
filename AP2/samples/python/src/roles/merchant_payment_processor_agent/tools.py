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

"""Tools for the merchant payment processor agent.

Each agent uses individual tools to handle distinct tasks throughout the
shopping and purchasing process.
"""

from datetime import datetime
from datetime import timezone
import logging
import os
from typing import Any
import uuid

from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import DataPart
from a2a.types import Part
from a2a.types import Task
from a2a.types import TaskState
from a2a.types import TextPart
from ap2.types.mandate import PAYMENT_MANDATE_DATA_KEY
from ap2.types.mandate import PaymentMandate
from ap2.types.payment_receipt import PAYMENT_RECEIPT_DATA_KEY
from ap2.types.payment_receipt import PaymentReceipt
from ap2.types.payment_receipt import Success
from common import artifact_utils
from common import message_utils
from common.a2a_extension_utils import EXTENSION_URI
from common.a2a_message_builder import A2aMessageBuilder
from common.payment_remote_a2a_client import PaymentRemoteA2aClient

from . import mpp as _mpp_strategy
from .mpp.base import AuthorizeStatus, Challenge, PaymentAdapter


async def initiate_payment(
    data_parts: list[dict[str, Any]],
    updater: TaskUpdater,
    current_task: Task | None,
    debug_mode: bool = False,
) -> None:
  """Handles the initiation of a payment.

  The adapter is selected from the inbound payment mandate's
  ``method_name`` (so per-cart routing works), falling back to the
  legacy ``$PAYMENT_METHOD`` env var for back-compat.
  """
  payment_mandate = message_utils.find_data_part(
      PAYMENT_MANDATE_DATA_KEY, data_parts
  )
  if not payment_mandate:
    error_message = _create_text_parts("Missing payment_mandate.")
    await updater.failed(message=updater.new_agent_message(parts=error_message))
    return

  pm = PaymentMandate.model_validate(payment_mandate)
  method_name = pm.payment_mandate_contents.payment_response.method_name
  adapter = _mpp_strategy.get_adapter(method_name)
  logging.info("MPP routing payment via adapter '%s' (method_name=%s)",
               adapter.name, method_name)

  risk_data = message_utils.find_data_part("risk_data", data_parts) or ""
  challenge_response = (
      message_utils.find_data_part("challenge_response", data_parts) or ""
  )
  await _handle_payment_mandate(
      pm, challenge_response, risk_data, updater, current_task,
      debug_mode, adapter,
  )


async def _handle_payment_mandate(
    payment_mandate: PaymentMandate,
    challenge_response: str,
    risk_data: str,
    updater: TaskUpdater,
    current_task: Task | None,
    debug_mode: bool,
    adapter: PaymentAdapter,
) -> None:
  """Strategy-driven payment dispatch.

  1. New task         → ask adapter for a challenge (or skip if "none").
  2. input_required   → validate the response, then ``adapter.authorize``.
  """
  if current_task is None:
    challenge = await adapter.raise_challenge(payment_mandate)
    if challenge.type == "none":
      # Adapter wants to authorize directly with no step-up.
      await _authorize_and_complete(
          payment_mandate, risk_data, updater, debug_mode, adapter
      )
      return
    await _emit_challenge(updater, challenge)
    return

  if current_task.status.state == TaskState.input_required:
    if not await adapter.validate_challenge_response(challenge_response):
      await updater.requires_input(
          message=updater.new_agent_message(
              _create_text_parts("Challenge response incorrect.")))
      return
    await _authorize_and_complete(
        payment_mandate, risk_data, updater, debug_mode, adapter
    )


async def _emit_challenge(updater: TaskUpdater, challenge: Challenge) -> None:
  """Translates a Challenge into the legacy A2A ``input_required`` message."""
  challenge_data = {
      "type":         challenge.type,
      "challenge_id": challenge.challenge_id,
      **challenge.payload,
  }
  message = updater.new_agent_message(parts=[
      Part(root=TextPart(
          text="Please provide the challenge response to complete the payment."
      )),
      Part(root=DataPart(data={"challenge": challenge_data})),
  ])
  await updater.requires_input(message=message)


async def _authorize_and_complete(
    payment_mandate: PaymentMandate,
    risk_data: str,
    updater: TaskUpdater,
    debug_mode: bool,
    adapter: PaymentAdapter,
) -> None:
  """Run ``adapter.authorize``; on AUTHORISED emit a receipt + complete.

  The Credentials Provider hop (legacy CARD path) is preserved when the
  inbound mandate carries a CP token URL — the adapter authorize() result
  still flows into the receipt regardless.
  """
  payment_mandate_id = (
      payment_mandate.payment_mandate_contents.payment_mandate_id
  )

  # Legacy CP hop — only when the mandate's payment_response.details.token
  # carries a credentials-provider URL (i.e. the CP path, not MOF/Adyen-direct).
  cp_client = _maybe_get_credentials_provider_client(payment_mandate, adapter.name)
  if cp_client is not None:
    payment_credential = await _request_payment_credential(
        payment_mandate, cp_client, updater, debug_mode, adapter.name,
    )
    logging.info(
        "Got payment credential from CP for mandate %s: %s",
        payment_mandate_id, payment_credential,
    )

  result = await adapter.authorize(payment_mandate, risk_data)

  if result.status == AuthorizeStatus.CHALLENGE_SHOPPER and result.challenge:
    # Adapter raised a step-up mid-authorize (e.g. Adyen 3DS2).
    await _emit_challenge(updater, result.challenge)
    return

  if result.status != AuthorizeStatus.AUTHORISED:
    await updater.failed(
        message=updater.new_agent_message(
            _create_text_parts(
                f"Payment {result.status.value}: {result.error_message or ''}"
            )
        )
    )
    return

  payment_receipt = _create_payment_receipt(
      payment_mandate, adapter.name, result.psp_reference,
  )
  if cp_client is not None:
    await _send_payment_receipt_to_credentials_provider(
        payment_receipt, cp_client, updater, debug_mode, adapter.name,
    )

  await updater.add_artifact([
      Part(root=DataPart(
          data={PAYMENT_RECEIPT_DATA_KEY: payment_receipt.model_dump()}
      ))
  ])
  await updater.complete(
      message=updater.new_agent_message(
          parts=_create_text_parts("{'status': 'success'}")
      )
  )


async def _request_payment_credential(
    payment_mandate: PaymentMandate,
    credentials_provider: PaymentRemoteA2aClient,
    updater: TaskUpdater,
    debug_mode: bool,
    adapter_name: str,
) -> str:
  """Asks the CP to dereference a token into payment-method credentials.

  Only invoked from the legacy CARD/CP path; x402, mock_card and adyen
  return ``None`` from ``_maybe_get_credentials_provider_client`` and so
  never reach this function.
  """
  message_builder = (
      A2aMessageBuilder()
      .set_context_id(updater.context_id)
      .add_text("Give me the payment method credentials for the given token.")
      .add_data(PAYMENT_MANDATE_DATA_KEY, payment_mandate.model_dump())
      .add_data("debug_mode", debug_mode)
  )
  task = await credentials_provider.send_a2a_message(message_builder.build())

  if not task.artifacts:
    raise ValueError("Failed to find the payment method data.")
  return artifact_utils.get_first_data_part(task.artifacts)


def _create_payment_receipt(
    payment_mandate: PaymentMandate,
    adapter_name: str,
    psp_reference: str | None,
) -> PaymentReceipt:
  """Build the receipt; ``psp_reference`` from the adapter wins over a UUID."""
  payment_id = uuid.uuid4().hex
  if adapter_name == "x402":
    method_name_for_receipt = "https://www.x402.org/"
  else:
    method_name_for_receipt = (
        payment_mandate.payment_mandate_contents.payment_response.method_name
    )
  return PaymentReceipt(
      payment_mandate_id=payment_mandate.payment_mandate_contents.payment_mandate_id,
      timestamp=datetime.now(timezone.utc).isoformat(),
      payment_id=payment_id,
      amount=payment_mandate.payment_mandate_contents.payment_details_total.amount,
      payment_status=Success(
          merchant_confirmation_id=payment_id,
          psp_confirmation_id=psp_reference or payment_id,
      ),
      payment_method_details={
          "method_name":   method_name_for_receipt,
          "adapter":       adapter_name,
          "psp_reference": psp_reference,
      },
  )


def _maybe_get_credentials_provider_client(
    payment_mandate: PaymentMandate,
    adapter_name: str,
) -> PaymentRemoteA2aClient | None:
  """Returns a CP client only when the mandate carries a CP token URL.

  Adyen MOF / mock_card / x402 paths do NOT round-trip through a CP — the
  charge token (or stored payment method id) was minted upstream.
  """
  if adapter_name in ("x402", "adyen", "mock_card"):
    return None

  details = payment_mandate.payment_mandate_contents.payment_response.details or {}
  token_object = details.get("token") or {}
  cp_url = token_object.get("url") if isinstance(token_object, dict) else None
  if not cp_url:
    return None
  return PaymentRemoteA2aClient(
      name="credentials_provider",
      base_url=cp_url,
      required_extensions={EXTENSION_URI},
  )


async def _send_payment_receipt_to_credentials_provider(
    payment_receipt: PaymentReceipt,
    credentials_provider: PaymentRemoteA2aClient,
    updater: TaskUpdater,
    debug_mode: bool,
    adapter_name: str,
) -> None:
  """Notifies the CP that the receipt landed. Only the CARD/CP path uses this."""
  message_builder = (
      A2aMessageBuilder()
      .set_context_id(updater.context_id)
      .add_text("Here is the payment receipt. No action is required.")
      .add_data(PAYMENT_RECEIPT_DATA_KEY, payment_receipt.model_dump())
      .add_data("debug_mode", debug_mode)
  )
  await credentials_provider.send_a2a_message(message_builder.build())


def _create_text_parts(*texts: str) -> list[Part]:
  """Helper to create text parts."""
  return [Part(root=TextPart(text=text)) for text in texts]
