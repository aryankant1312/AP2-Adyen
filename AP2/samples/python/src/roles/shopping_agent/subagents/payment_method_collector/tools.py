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

"""Tools used by the payment method collector subagent.

Each agent uses individual tools to handle distinct tasks throughout the
shopping and purchasing process.
"""

from google.adk.tools.tool_context import ToolContext

from ap2.types.payment_request import PAYMENT_METHOD_DATA_DATA_KEY
from common.a2a_message_builder import A2aMessageBuilder
from common import artifact_utils
from roles.shopping_agent.remote_agents import credentials_provider_client
from roles.shopping_agent.remote_agents import merchant_agent_client


async def get_payment_methods(
    user_email: str,
    tool_context: ToolContext,
) -> list[str]:
  """Gets the user's payment methods from the credentials provider.

  These will match the payment method on the cart being purchased.

  Args:
    user_email: Identifies the user's account
    tool_context: The ADK supplied tool context.

  Returns:
    A dictionary of the user's applicable payment methods.
  """
  cart_mandate = tool_context.state["cart_mandate"]
  message_builder = (
      A2aMessageBuilder()
      .set_context_id(tool_context.state["shopping_context_id"])
      .add_text("Get a filtered list of the user's payment methods.")
      .add_data("user_email", user_email)
  )
  for method_data in cart_mandate.contents.payment_request.method_data:
    message_builder.add_data(
        PAYMENT_METHOD_DATA_DATA_KEY,
        method_data.model_dump(),
    )
  task = await credentials_provider_client.send_a2a_message(
      message_builder.build()
  )
  payment_methods = artifact_utils.get_first_data_part(task.artifacts)
  return payment_methods


async def get_payment_credential_token(
    user_email: str,
    payment_method_alias: str,
    tool_context: ToolContext,
) -> str:
  """Gets a payment credential token from the credentials provider.

  Args:
    user_email: The user's email address.
    payment_method_alias: The payment method alias.
    tool_context: The ADK supplied tool context.

  Returns:
    Status of the call and the payment credential token.
  """
  message = (
      A2aMessageBuilder()
      .set_context_id(tool_context.state["shopping_context_id"])
      .add_text("Get a payment credential token for the user's payment method.")
      .add_data("payment_method_alias", payment_method_alias)
      .add_data("user_email", user_email)
      .build()
  )
  task = await credentials_provider_client.send_a2a_message(message)
  data = artifact_utils.get_first_data_part(task.artifacts)
  token = data.get("token")
  credentials_provider_agent_card = (
      await credentials_provider_client.get_agent_card()
  )

  tool_context.state["payment_credential_token"] = {
      "value": token,
      "url": credentials_provider_agent_card.url,
  }
  return {"status": "success", "token": token}


async def get_merchant_on_file_payment_methods(
    user_email: str,
    tool_context: ToolContext,
) -> dict:
  """Fetches the merchant's on-file payment methods (Mode 2) via A2A.

  Use this when the merchant advertises that it already has the customer's
  cards / UPI / etc. stored from prior purchases (e.g. a returning pharmacy
  customer). The shopping agent should present these alongside (or instead
  of) options returned by a Credentials Provider.

  Args:
    user_email: The customer's email; used by the merchant to look up its
      own customer record.
    tool_context: The ADK supplied tool context.

  Returns:
    Dict with `source`, and `payment_method_aliases` for UI display.
  """
  message = (
      A2aMessageBuilder()
      .set_context_id(tool_context.state["shopping_context_id"])
      .add_text(
          "Return the on-file payment methods the merchant has stored for"
          " this user."
      )
      .add_data("user_email", user_email)
      .add_data("shopping_agent_id", "trusted_shopping_agent")
      .build()
  )
  task = await merchant_agent_client.send_a2a_message(message)
  payload = artifact_utils.get_first_data_part(task.artifacts) or {}
  methods = payload.get("on_file_payment_methods", [])
  aliases = [m["alias"] for m in methods]
  # Cache full method metadata so the agent can display brand / last4 etc.
  tool_context.state["merchant_on_file_methods"] = methods
  return {
      "source": payload.get("source", "merchant_on_file"),
      "payment_method_aliases": aliases,
  }


async def get_merchant_on_file_token(
    user_email: str,
    payment_method_alias: str,
    tool_context: ToolContext,
) -> dict:
  """Exchanges a chosen on-file alias for a PSP charge token via the merchant.

  The returned token, NOT the PSP reference or any raw credential, is what
  the shopping agent embeds in the PaymentMandate's
  `payment_response.details.token`. The merchant later presents the same
  token to its PSP to actually move money.

  Args:
    user_email: The customer's email.
    payment_method_alias: The alias the user selected from the picker.
    tool_context: The ADK supplied tool context.

  Returns:
    Dict with the opaque charge token and the source tag.
  """
  message = (
      A2aMessageBuilder()
      .set_context_id(tool_context.state["shopping_context_id"])
      .add_text(
          "Mint a PSP charge token for this on-file payment method."
      )
      .add_data("user_email", user_email)
      .add_data("payment_method_alias", payment_method_alias)
      .add_data("shopping_agent_id", "trusted_shopping_agent")
      .build()
  )
  task = await merchant_agent_client.send_a2a_message(message)
  data = artifact_utils.get_first_data_part(task.artifacts) or {}
  token = data.get("token")
  merchant_agent_card = await merchant_agent_client.get_agent_card()

  # Mirror the CP path's shape so downstream create_payment_mandate code
  # works unchanged; the merchant URL takes the CP-URL slot because the
  # merchant is the one holding the token binding here.
  tool_context.state["payment_credential_token"] = {
      "value": token,
      "url": merchant_agent_card.url,
      "source": "merchant_on_file",
  }
  return {
      "status": "success",
      "source": data.get("source", "merchant_on_file"),
      "token": token,
  }
