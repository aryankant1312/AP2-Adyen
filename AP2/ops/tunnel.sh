#!/usr/bin/env bash
# Open a public HTTPS tunnel to the local MCP gateway.
# Tries cloudflared first, falls back to ngrok.
#
# After the tunnel is up, prints the exact URL + bearer line you should
# paste into Claude Custom Connectors / ChatGPT Developer-mode connectors:
#
#   MCP URL:   https://random.trycloudflare.com/mcp
#   Auth:      Authorization: Bearer <token>
#
# (cloudflared writes the URL to stderr; we tee it through and grep it
# back so we can also surface the connector banner.)

set -euo pipefail

PORT="${MCP_HTTP_PORT:-8080}"
URL="http://localhost:${PORT}"

# ---- pull a bearer token from MCP_TOKENS env or ops/envs/.env -----------
THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${THIS_DIR}/envs/.env"

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
  echo "(no MCP_TOKENS set — generate with python ops/gen_token.py --write-env)"
}

BEARER="$(read_token)"

print_banner() {
  local public="$1"
  cat <<EOF

================================================================================
  AP2 Pharmacy MCP Gateway — public tunnel ready
--------------------------------------------------------------------------------
  MCP URL:       ${public}/mcp
  Health check:  ${public}/healthz
  Auth header:   Authorization: Bearer ${BEARER}

  Claude:   Settings → Connectors → Add custom connector
            URL ${public}/mcp · Auth: Bearer · Token: <above>

  ChatGPT:  Settings → Connectors → Developer mode → Add MCP server
            URL ${public}/mcp · Auth: Bearer <above>
================================================================================
EOF
}

if command -v cloudflared >/dev/null 2>&1; then
  echo "[tunnel] using cloudflared → ${URL}"
  # cloudflared writes the public URL to stderr. Tee both streams to a
  # tmp log, watch for the URL, print our banner once, then keep
  # streaming the live log so the tunnel stays attached to this PID.
  TMP_LOG="$(mktemp -t ap2-tunnel.XXXXXX.log)"
  trap 'rm -f "${TMP_LOG}"' EXIT

  ( cloudflared tunnel --url "${URL}" --no-autoupdate 2>&1 | tee "${TMP_LOG}" ) &
  TUNNEL_PID=$!

  # Watch the log for up to 30s for the trycloudflare URL.
  PUBLIC=""
  for _ in $(seq 1 60); do
    if PUBLIC="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "${TMP_LOG}" \
                   | head -n1)" && [[ -n "${PUBLIC}" ]]; then
      break
    fi
    sleep 0.5
  done

  if [[ -n "${PUBLIC}" ]]; then
    print_banner "${PUBLIC}"
  else
    echo "[tunnel] could not detect public URL within 30s — check the log above."
  fi

  wait "${TUNNEL_PID}"

elif command -v ngrok >/dev/null 2>&1; then
  echo "[tunnel] using ngrok → ${URL}"
  ngrok http "${PORT}" > /dev/null &
  TUNNEL_PID=$!
  # Poll ngrok's local API for the public URL.
  PUBLIC=""
  for _ in $(seq 1 60); do
    if PUBLIC="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
                   | python -c 'import sys,json;
d=json.load(sys.stdin);
ts=d.get("tunnels",[]);
print((ts[0] or {}).get("public_url","")) if ts else print("")' 2>/dev/null)" \
        && [[ -n "${PUBLIC}" ]]; then
      break
    fi
    sleep 0.5
  done
  if [[ -n "${PUBLIC}" ]]; then
    print_banner "${PUBLIC}"
  else
    echo "[tunnel] could not detect ngrok public URL within 30s."
  fi
  wait "${TUNNEL_PID}"
else
  cat <<EOF >&2
[tunnel] neither cloudflared nor ngrok is installed.
  - cloudflared: https://github.com/cloudflare/cloudflared/releases
  - ngrok:       https://ngrok.com/download
EOF
  exit 1
fi
