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

"""Clients used by the shopping agent to communicate with remote agents.

Clients request activation of the Agent Payments Protocol extension by including
the X-A2A-Extensions header in each HTTP request.

This registry serves as the initial allowlist of remote agents that the shopping
agent trusts.

Endpoint URLs default to the localhost ports used by the upstream sample stack
but can be overridden via environment variables, enabling deployment against
remote Merchant / Credentials Provider / Merchant Payment Processor agents
built by other teams:

  - MERCHANT_AGENT_URL
  - CREDENTIALS_PROVIDER_URL
  - MERCHANT_PAYMENT_PROCESSOR_URL  (optional; only used if the Shopping Agent
    talks to the MPP directly rather than via the Merchant Agent relay)
"""

import os

from common.a2a_extension_utils import EXTENSION_URI
from common.payment_remote_a2a_client import PaymentRemoteA2aClient


credentials_provider_client = PaymentRemoteA2aClient(
    name="credentials_provider",
    base_url=os.environ.get(
        "CREDENTIALS_PROVIDER_URL",
        "http://localhost:8002/a2a/credentials_provider",
    ),
    required_extensions={
        EXTENSION_URI,
    },
)


merchant_agent_client = PaymentRemoteA2aClient(
    name="merchant_agent",
    base_url=os.environ.get(
        "MERCHANT_AGENT_URL",
        "http://localhost:8001/a2a/merchant_agent",
    ),
    required_extensions={
        EXTENSION_URI,
    },
)


# Optional direct-to-MPP client. Instantiated only when the env var is set so
# deployments using the default Merchant-relay topology are unaffected.
_mpp_url = os.environ.get("MERCHANT_PAYMENT_PROCESSOR_URL")
merchant_payment_processor_client: PaymentRemoteA2aClient | None = (
    PaymentRemoteA2aClient(
        name="merchant_payment_processor",
        base_url=_mpp_url,
        required_extensions={EXTENSION_URI},
    )
    if _mpp_url
    else None
)
