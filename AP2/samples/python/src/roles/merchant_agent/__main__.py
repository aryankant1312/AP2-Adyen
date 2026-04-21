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

"""Main for the merchant agent.

Mounts two extra surfaces on top of the standard A2A server:

  * ``/webhooks/adyen/...`` — Adyen notification + 3DS2 return endpoints
    (HMAC-validated, see :mod:`roles.merchant_agent.webhooks.adyen`).
  * ``/.well-known/merchant-key.pem`` — public RSA key used to verify
    ``cart_mandate.merchant_authorization`` JWTs.
"""

from collections.abc import Sequence
import logging
import os

from absl import app
from starlette.routing import Mount, Route
import uvicorn

from roles.merchant_agent import agent_executor as _agent_executor
from roles.merchant_agent.agent_executor import MerchantAgentExecutor
from roles.merchant_agent.webhooks.adyen import build_app as _build_adyen_webhook
from common import server, watch_log
from common.signing import serve_public_key_pem


AGENT_MERCHANT_PORT = int(os.environ.get("PORT", "8001"))


def _trust_extra_callers() -> None:
    """Allow extra agent IDs from ``$KNOWN_SHOPPING_AGENTS`` (csv)."""
    extras = os.environ.get("KNOWN_SHOPPING_AGENTS", "ap2_mcp_gateway")
    for s in (x.strip() for x in extras.split(",")):
        if s and s not in _agent_executor._KNOWN_SHOPPING_AGENTS:
            _agent_executor._KNOWN_SHOPPING_AGENTS.append(s)


def main(argv: Sequence[str]) -> None:
    _trust_extra_callers()

    agent_card = server.load_local_agent_card(__file__)
    executor = MerchantAgentExecutor(agent_card.capabilities.extensions)

    starlette_app = server._build_starlette_app(
        agent_card, executor=executor, rpc_url="/a2a/merchant_agent",
    )

    # Add the webhook + JWKS routes before middleware wraps the router.
    starlette_app.routes.append(
        Mount("/webhooks/adyen", app=_build_adyen_webhook())
    )
    starlette_app.routes.append(
        Route("/.well-known/merchant-key.pem",
              serve_public_key_pem(), methods=["GET"])
    )

    logger = logging.getLogger(__name__)
    logger.addHandler(watch_log.create_file_handler())
    server._add_middlewares(starlette_app, logger)

    logger.info("%s listening on http://0.0.0.0:%d",
                agent_card.name, AGENT_MERCHANT_PORT)
    uvicorn.run(starlette_app,
                host=os.environ.get("HOST", "0.0.0.0"),
                port=AGENT_MERCHANT_PORT,
                log_level="info", timeout_keep_alive=120)


if __name__ == "__main__":
    app.run(main)
