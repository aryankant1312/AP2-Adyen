#!/usr/bin/env bash
# Bring the whole AP2 pharmacy stack up in the background.
#
# Starts (skipping any port already listening):
#   :8001 merchant_agent
#   :8002 credentials_provider
#   :8003 merchant_payment_processor
#   :8080 mcp_gateway  (MCP server — endpoint: /mcp)
#   (optional) ngrok/cloudflared tunnel — only if --tunnel is passed AND
#              ngrok or cloudflared is on PATH (ngrok takes priority).
#
# Logs go to <repo>/.logs/ap2-*.log. Use scripts/stop_stack.sh to tear down.
#
# Usage:
#   ./scripts/start_stack.sh             # 4 backend services, no tunnel
#   ./scripts/start_stack.sh --tunnel    # also start ngrok (or cloudflared)

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/.logs"
mkdir -p "${LOG_DIR}"

MCP_PORT="${MCP_HTTP_PORT:-8080}"
ENV_FILE="${REPO_ROOT}/ops/envs/.env"

# Add ngrok install location to PATH if it's at the typical Windows spot.
if [[ -x "/c/Users/${USERNAME:-}/AppData/Local/ngrok/ngrok.exe" ]]; then
  export PATH="/c/Users/${USERNAME}/AppData/Local/ngrok:${PATH}"
fi
# Add cloudflared install location to PATH if it's at the typical Windows spot.
if [[ -x "/c/Program Files (x86)/cloudflared/cloudflared.exe" ]]; then
  export PATH="/c/Program Files (x86)/cloudflared:${PATH}"
fi

WANT_TUNNEL=0
[[ "${1:-}" == "--tunnel" ]] && WANT_TUNNEL=1

# ----------------------------------------------------------------- helpers

port_in_use() {
  netstat -ano 2>/dev/null | grep -q ":$1 .*LISTENING"
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
  echo "(no MCP_TOKENS set — run: python ops/gen_token.py --write-env)"
}

print_mcp_banner() {
  local base_url="$1"
  local token="$2"
  local auth_req
  auth_req="$(echo "${MCP_REQUIRE_AUTH:-false}" | tr '[:upper:]' '[:lower:]')"
  echo ""
  echo "================================================================================"
  echo "  AP2 MCP Gateway"
  echo "--------------------------------------------------------------------------------"
  echo "  MCP URL    : ${base_url}/mcp"
  echo "  Health     : ${base_url}/healthz"
  case "${auth_req}" in
    1|true|yes|on)
      echo "  Auth       : Bearer ${token}"
      echo ""
      echo "  Claude:  Settings → Connectors → Add custom connector"
      echo "           URL   : ${base_url}/mcp"
      echo "           Auth  : Bearer"
      echo "           Token : ${token}"
      ;;
    *)
      echo "  Auth       : none (MCP_REQUIRE_AUTH is off)"
      echo ""
      echo "  Claude:  Settings → Connectors → Add custom connector"
      echo "           URL   : ${base_url}/mcp"
      echo "           Auth  : (none)"
      ;;
  esac
  echo "================================================================================"
}

# ------------------------------------------------------------------- main

echo "==> launching AP2 stack (logs in ${LOG_DIR})"

start_bg "merchant" 8001 "python ops/run_agents.py merchant"
start_bg "cp"       8002 "python ops/run_agents.py cp"
start_bg "mpp"      8003 "python ops/run_agents.py mpp"
start_bg "gateway"  "${MCP_PORT}" "python ops/run_gateway.py"

# The agents have no /healthz; just give them a moment, then health-check
# the gateway (which depends on them at first tool call, not at startup).
sleep 2
wait_for_health "http://localhost:${MCP_PORT}/healthz" "mcp-gateway"

BEARER="$(read_token)"
PUBLIC_MCP_URL=""

if (( WANT_TUNNEL == 1 )); then
  echo ""
  TUNNEL_LOG="${LOG_DIR}/ap2-tunnel.log"

  if command -v ngrok >/dev/null 2>&1; then
    # ----------------------------------------------------------------- ngrok
    if pgrep -f "ngrok http" >/dev/null 2>&1 \
       || powershell -NoProfile -Command \
            "(Get-Process -Name ngrok -ErrorAction SilentlyContinue).Id" \
            2>/dev/null | grep -q .
    then
      echo "  ✓ ngrok already running (skipping)"
      # Still try to read the current public URL from the API.
      PUBLIC_MCP_URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
                         | python -c '
import sys, json
try:
    d = json.load(sys.stdin)
    ts = d.get("tunnels", [])
    print(next((t.get("public_url","") for t in ts if t.get("public_url","")), ""))
except Exception:
    print("")
' 2>/dev/null || true)"
    else
      echo "  ▶ starting ngrok tunnel  → log: ${TUNNEL_LOG}"
      ( ngrok http "${MCP_PORT}" ) > "${TUNNEL_LOG}" 2>&1 &
      disown $! 2>/dev/null || true
      # Poll ngrok's local API for the public URL.
      for _ in $(seq 1 60); do
        PUBLIC_MCP_URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
                           | python -c '
import sys, json
try:
    d = json.load(sys.stdin)
    ts = d.get("tunnels", [])
    print(next((t.get("public_url","") for t in ts if t.get("public_url","")), ""))
except Exception:
    print("")
' 2>/dev/null || true)"
        [[ -n "${PUBLIC_MCP_URL}" ]] && break
        sleep 0.5
      done
      if [[ -z "${PUBLIC_MCP_URL}" ]]; then
        echo "  ✗ ngrok up but URL not detected in 30s — check log"
      fi
    fi

  elif command -v cloudflared >/dev/null 2>&1; then
    # ----------------------------------------------------------- cloudflared
    if pgrep -f "cloudflared.*tunnel" >/dev/null 2>&1 \
       || powershell -NoProfile -Command \
            "(Get-Process -Name cloudflared -ErrorAction SilentlyContinue).Id" \
            2>/dev/null | grep -q .
    then
      echo "  ✓ cloudflared already running (skipping)"
      PUBLIC_MCP_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' \
                          "${TUNNEL_LOG}" 2>/dev/null | tail -n1 || true)"
    else
      echo "  ▶ starting cloudflared tunnel  → log: ${TUNNEL_LOG}"
      ( cloudflared tunnel --url "http://localhost:${MCP_PORT}" --no-autoupdate \
          > "${TUNNEL_LOG}" 2>&1 ) &
      disown $! 2>/dev/null || true
      for _ in $(seq 1 60); do
        PUBLIC_MCP_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' \
                            "${TUNNEL_LOG}" 2>/dev/null | head -n1 || true)"
        [[ -n "${PUBLIC_MCP_URL}" ]] && break
        sleep 0.5
      done
      if [[ -z "${PUBLIC_MCP_URL}" ]]; then
        echo "  ✗ tunnel up but URL not detected in 30s — check log"
      fi
    fi

  else
    echo "  ✗ neither ngrok nor cloudflared found — install one:"
    echo "      ngrok:       https://ngrok.com/download"
    echo "      cloudflared: winget install Cloudflare.cloudflared"
  fi
fi

# -------------------------------------------------- MCP connection banner

if [[ -n "${PUBLIC_MCP_URL}" ]]; then
  print_mcp_banner "${PUBLIC_MCP_URL}" "${BEARER}"
else
  print_mcp_banner "http://localhost:${MCP_PORT}" "${BEARER}"
fi

# ------------------------------------------------------------- quick ref

echo ""
echo "  tail logs  : tail -f ${LOG_DIR}/ap2-{merchant,cp,mpp,gateway,tunnel}.log"
echo "  smoke test : python ops/smoke_gateway.py \\"
echo "                   --base-url http://127.0.0.1:${MCP_PORT}/mcp \\"
echo "                   --token \$(grep ^MCP_TOKENS ${ENV_FILE} | cut -d= -f2 | cut -d, -f1)"
echo "  tear down  : ./scripts/stop_stack.sh"
