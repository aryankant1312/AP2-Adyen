#!/usr/bin/env bash
# Print the current public MCP URL + bearer token + paste-ready
# Claude/ChatGPT connector instructions. Useful after the tunnel has
# been running for a while and the start banner has scrolled away.
#
# Usage:
#   ./scripts/show_url.sh

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TUNNEL_LOG="${REPO_ROOT}/.logs/ap2-tunnel.log"
ENV_FILE="${REPO_ROOT}/ops/envs/.env"

# ---- locate public URL (ngrok API first, then cloudflare log) -----------

PUBLIC=""
# Try ngrok's local API if the process is running.
if curl -s http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
  PUBLIC="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
             | python -c '
import sys, json
try:
    d = json.load(sys.stdin)
    ts = d.get("tunnels", [])
    print(next((t.get("public_url","") for t in ts if t.get("public_url","")), ""))
except Exception:
    print("")
' 2>/dev/null || true)"
fi
# Fall back to scanning the cloudflared tunnel log.
if [[ -z "${PUBLIC}" && -f "${TUNNEL_LOG}" ]]; then
  PUBLIC="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' \
              "${TUNNEL_LOG}" 2>/dev/null | tail -n1 || true)"
fi

# ---- locate bearer token ------------------------------------------------

TOKENS=""
if [[ -n "${MCP_TOKENS:-}" ]]; then
  TOKENS="${MCP_TOKENS}"
elif [[ -f "${ENV_FILE}" ]]; then
  TOKENS="$(grep -E '^MCP_TOKENS=' "${ENV_FILE}" | head -n1 | cut -d= -f2- \
              | tr -d '"' || true)"
fi
TOK_PRIMARY="${TOKENS%%,*}"
TOK_SECONDARY=""
if [[ "${TOKENS}" == *,* ]]; then
  TOK_SECONDARY="$(echo "${TOKENS}" | cut -d, -f2-)"
fi

# ---- gateway local health (sanity) --------------------------------------

if curl -fsS http://localhost:8080/healthz >/dev/null 2>&1; then
  HEALTH="up"
else
  HEALTH="DOWN — run ./scripts/start_stack.sh"
fi

# ---- auth mode (matches what BearerAuthMiddleware enforces) -------------

AUTH_REQ="${MCP_REQUIRE_AUTH:-true}"
case "$(echo "${AUTH_REQ}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) AUTH_MODE="open (no bearer required)" ;;
  *)              AUTH_MODE="bearer-required" ;;
esac

# ---- output -------------------------------------------------------------

cat <<EOF

================================================================================
  AP2 Pharmacy MCP Gateway — connector info
--------------------------------------------------------------------------------
  Local gateway   : http://localhost:8080  (${HEALTH})
  Auth mode       : ${AUTH_MODE}
EOF

if [[ -z "${PUBLIC}" ]]; then
  cat <<EOF
  Public URL      : (none — start the tunnel:
                     ./scripts/start_stack.sh --tunnel)
EOF
else
  cat <<EOF
  Public MCP URL  : ${PUBLIC}/mcp
  Health check    : ${PUBLIC}/healthz
EOF
fi

cat <<EOF
  Bearer (primary): ${TOK_PRIMARY:-<missing — check ops/envs/.env>}
EOF
[[ -n "${TOK_SECONDARY}" ]] && \
  echo "  Bearer (spare)  : ${TOK_SECONDARY}"

if [[ -n "${PUBLIC}" ]]; then
  cat <<EOF

  Claude:   Settings → Connectors → Add custom connector
            URL  : ${PUBLIC}/mcp
EOF
  if [[ "${AUTH_MODE}" == bearer-required ]]; then
    cat <<EOF
            Auth : Bearer
            Token: ${TOK_PRIMARY:-<missing>}
EOF
  else
    cat <<EOF
            Auth : (none — gateway is in open mode)
EOF
  fi
  cat <<EOF

  ChatGPT:  Settings → Connectors → Developer mode → Add MCP server
            URL  : ${PUBLIC}/mcp
EOF
  if [[ "${AUTH_MODE}" == bearer-required ]]; then
    cat <<EOF
            Auth : ChatGPT only offers OAuth / Mixed / No auth — none
                   accept a plain bearer. To use ChatGPT, restart the
                   gateway in open mode:
                       MCP_REQUIRE_AUTH=false ./scripts/start_stack.sh
                   then pick "No auth" in the ChatGPT dialog.
EOF
  else
    cat <<EOF
            Auth : pick "No auth" radio
                   (gateway is open; URL is the only secret)
EOF
  fi
fi
echo "================================================================================"
