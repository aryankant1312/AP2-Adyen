#!/usr/bin/env bash
# Tear down the AP2 Boots stack started by scripts/start_stack.sh.
# Idempotent — silent if nothing is up.

set -uo pipefail

kill_port() {
  local port="$1" name="$2"
  local pids
  pids=$(ss -lntp 2>/dev/null \
        | awk -v p=":$port" '$4 ~ p {print $0}' \
        | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
  if [[ -z "${pids}" ]]; then
    pids=$(lsof -ti tcp:"${port}" 2>/dev/null || true)
  fi
  if [[ -z "${pids}" ]]; then
    echo "  · :${port} ${name} — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ :${port} ${name} — killing PID ${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
  done
}

kill_by_name() {
  local name="$1"
  local pids
  pids=$(pgrep -f "${name}" 2>/dev/null || true)
  if [[ -z "${pids}" ]]; then
    echo "  · ${name} — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ ${name} — killing PID ${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
  done
}

echo "==> stopping AP2 Boots stack"
kill_port 8080 "gateway-legacy"
kill_port "${MCP_HTTP_PORT:-5000}" "gateway"
kill_port 8003 "mpp"
kill_port 8002 "cp"
kill_port 8001 "merchant"
kill_by_name "ngrok http"
kill_by_name "cloudflared"
echo "==> done"
