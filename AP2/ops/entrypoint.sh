#!/usr/bin/env bash
# Container entrypoint — dispatches to a service based on $ROLE.
set -euo pipefail

case "${ROLE:-mcp_gateway}" in
  mcp_gateway)
    exec python -m mcp_gateway --http "0.0.0.0:${MCP_HTTP_PORT:-8080}" "$@"
    ;;
  merchant_agent)
    exec python -m roles.merchant_agent "$@"
    ;;
  credentials_provider)
    exec python -m roles.credentials_provider_agent "$@"
    ;;
  merchant_payment_processor)
    exec python -m roles.merchant_payment_processor_agent "$@"
    ;;
  seed)
    exec python -m pharmacy_data.seed "$@"
    ;;
  zero_auth)
    exec python -m ops.adyen_zero_auth "$@"
    ;;
  *)
    echo "unknown ROLE='$ROLE' (expected: mcp_gateway, merchant_agent, "
    echo "credentials_provider, merchant_payment_processor, seed, zero_auth)"
    exit 64
    ;;
esac
