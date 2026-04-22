#!/usr/bin/env bash
# Bring the AP2 Boots-pharmacy MCP stack up and expose it via ngrok.
#
# Default behaviour (no flags):
#   - Starts the three backend agents in the background:
#       :8001 merchant_agent
#       :8002 credentials_provider
#       :8003 merchant_payment_processor
#   - Starts the MCP gateway on :${MCP_HTTP_PORT:-5000} (or skips if that
#     port is already serving — typical when the Replit workflow has it).
#   - Always launches an ngrok HTTPS tunnel pointing at the gateway.
#   - Prints a paste-ready ChatGPT / Claude connector banner.
#
# Skip the tunnel by passing  --no-tunnel.
#
# Required:
#   NGROK_AUTHTOKEN   Replit secret. Used once with `ngrok config add-authtoken`.
#
# Logs go to <repo>/.logs/ap2-*.log. Use scripts/stop_stack.sh to tear down.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/.logs"
mkdir -p "${LOG_DIR}"

MCP_PORT="${MCP_HTTP_PORT:-5000}"
ENV_FILE="${REPO_ROOT}/ops/envs/.env"

# Load env file if present so things like NGROK_AUTHTOKEN don't have to be
# exported manually in the shell.
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

# Prefer the bundled ngrok binary; fall back to PATH.
NGROK_BIN="${REPO_ROOT}/.bin/ngrok"
if [[ ! -x "${NGROK_BIN}" ]] && command -v ngrok >/dev/null 2>&1; then
  NGROK_BIN="$(command -v ngrok)"
fi

WANT_TUNNEL=1
[[ "${1:-}" == "--no-tunnel" ]] && WANT_TUNNEL=0
[[ "${1:-}" == "--tunnel"    ]] && WANT_TUNNEL=1   # back-compat: harmless

# ----------------------------------------------------------------- helpers

port_in_use() {
  if command -v ss >/dev/null 2>&1; then
    ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
  else
    (echo > "/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
  fi
}

start_bg() {
  local name="$1" port="$2" cmd="$3"
  local log="${LOG_DIR}/ap2-${name}.log"
  if port_in_use "${port}"; then
    echo "  ✓ ${name} already up on :${port} (skipping)"
    return 0
  fi
  echo "  ▶ starting ${name} on :${port}  → log: ${log}"
  ( cd "${REPO_ROOT}" && eval "${cmd}" ) > "${log}" 2>&1 &
  disown $! 2>/dev/null || true
}

wait_for_health() {
  local url="$1" name="$2" tries=30
  while (( tries-- > 0 )); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "  ✓ ${name} healthy"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ ${name} did NOT come up within 30s — check its log"
  return 1
}

# Read the first bearer token from MCP_TOKENS env var or ops/envs/.env.
read_token() {
  if [[ -n "${MCP_TOKENS:-}" ]]; then
    echo "${MCP_TOKENS%%,*}"
    return 0
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    local line
    line="$(grep -E '^MCP_TOKENS=' "${ENV_FILE}" | head -n1 || true)"
    if [[ -n "${line}" ]]; then
      echo "${line#MCP_TOKENS=}" | cut -d',' -f1 | tr -d '"'
      return 0
    fi
  fi
  echo ""
}

print_banner() {
  local public_url="$1"
  local local_url="$2"
  local token="$3"
  local auth_req
  auth_req="$(echo "${MCP_REQUIRE_AUTH:-false}" | tr '[:upper:]' '[:lower:]')"
  cat <<EOF

================================================================================
  Boots Pharmacy — AP2 MCP Gateway
--------------------------------------------------------------------------------
  Local URL    : ${local_url}/mcp
  Local health : ${local_url}/healthz
EOF
  if [[ -n "${public_url}" ]]; then
    cat <<EOF
  Public URL   : ${public_url}/mcp        ← paste this into ChatGPT
  Public health: ${public_url}/healthz
EOF
  fi
  case "${auth_req}" in
    1|true|yes|on)
      echo "  Auth         : Bearer ${token}"
      ;;
    *)
      echo "  Auth         : (none — gateway is in open mode)"
      ;;
  esac
  cat <<EOF
--------------------------------------------------------------------------------
  ChatGPT (developer mode):
    Settings → Connectors → Add custom connector
      URL  : ${public_url:-${local_url}}/mcp
      Auth : (No auth)
  Claude (custom connector):
    Settings → Connectors → Add custom connector
      URL  : ${public_url:-${local_url}}/mcp
EOF
  case "${auth_req}" in
    1|true|yes|on)
      cat <<EOF
      Auth : Bearer
      Token: ${token}
EOF
      ;;
    *) ;;
  esac
  echo "================================================================================"
}

# ------------------------------------------------------------------- main

echo "==> launching AP2 Boots stack (logs in ${LOG_DIR})"

# Backend agents (best-effort — gateway also works without them for catalog/cart;
# they are needed for the full payment-mandate signing path).
start_bg "merchant" 8001 "uv run --no-sync python ops/run_agents.py merchant"
start_bg "cp"       8002 "uv run --no-sync python ops/run_agents.py cp"
start_bg "mpp"      8003 "uv run --no-sync python ops/run_agents.py mpp"

# Gateway. If 5000 is already serving (Replit dev workflow), reuse it.
start_bg "gateway"  "${MCP_PORT}" \
  "MCP_HTTP_PORT=${MCP_PORT} uv run --no-sync python ops/run_gateway.py --http 0.0.0.0:${MCP_PORT}"

sleep 2
wait_for_health "http://localhost:${MCP_PORT}/healthz" "mcp-gateway" || true

BEARER="$(read_token)"
PUBLIC_MCP_URL=""
LOCAL_URL="http://localhost:${MCP_PORT}"

if (( WANT_TUNNEL == 1 )); then
  if [[ ! -x "${NGROK_BIN}" ]]; then
    echo "  ✗ ngrok binary not found at ${NGROK_BIN} — install it (see scripts/install_ngrok.sh) or pass --no-tunnel."
  elif [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
    echo "  ✗ NGROK_AUTHTOKEN env var is not set. Add it to your Replit secrets, then re-run."
  else
    echo ""
    TUNNEL_LOG="${LOG_DIR}/ap2-tunnel.log"

    # Configure once (idempotent — overwrites if already set).
    "${NGROK_BIN}" config add-authtoken "${NGROK_AUTHTOKEN}" >/dev/null 2>&1 || true

    if pgrep -f "ngrok http" >/dev/null 2>&1; then
      echo "  ✓ ngrok already running (skipping)"
    else
      echo "  ▶ starting ngrok tunnel  → log: ${TUNNEL_LOG}"
      ( "${NGROK_BIN}" http "${MCP_PORT}" --log=stdout --log-format=logfmt ) \
          > "${TUNNEL_LOG}" 2>&1 &
      disown $! 2>/dev/null || true
    fi

    # Poll ngrok's local API for the public URL (give it ~20s).
    for _ in $(seq 1 40); do
      PUBLIC_MCP_URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
                         | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    ts = d.get("tunnels", [])
    print(next((t.get("public_url","") for t in ts
                if t.get("public_url","").startswith("https://")), ""))
except Exception:
    print("")
' 2>/dev/null || true)"
      [[ -n "${PUBLIC_MCP_URL}" ]] && break
      sleep 0.5
    done
    if [[ -z "${PUBLIC_MCP_URL}" ]]; then
      echo "  ✗ ngrok up but public URL not detected in 20s — check ${TUNNEL_LOG}"
    fi
  fi
fi

print_banner "${PUBLIC_MCP_URL}" "${LOCAL_URL}" "${BEARER}"

echo ""
echo "  tail logs : tail -f ${LOG_DIR}/ap2-{merchant,cp,mpp,gateway,tunnel}.log"
echo "  tear down : ${REPO_ROOT}/scripts/stop_stack.sh"
