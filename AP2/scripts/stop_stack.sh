#!/usr/bin/env bash
# Tear down the AP2 Boots stack started by scripts/start_stack.sh.
# Idempotent — silent if nothing is up.

set -uo pipefail

is_windows() {
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

kill_pid() {
  local pid="$1"
  if is_windows; then
    taskkill //F //PID "${pid}" >/dev/null 2>&1 || true
  else
    kill -TERM "${pid}" 2>/dev/null || true
  fi
}

kill_port() {
  local port="$1" name="$2"
  local pids=""
  if is_windows; then
    # netstat -ano on Windows: columns are Proto, Local, Foreign, State, PID
    pids=$(netstat -ano 2>/dev/null \
          | awk -v p=":${port}" '$2 ~ p"$" && $4=="LISTENING" {print $5}' \
          | sort -u)
  else
    pids=$(ss -lntp 2>/dev/null \
          | awk -v p=":$port" '$4 ~ p {print $0}' \
          | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
    if [[ -z "${pids}" ]]; then
      pids=$(lsof -ti tcp:"${port}" 2>/dev/null || true)
    fi
  fi
  if [[ -z "${pids}" ]]; then
    echo "  · :${port} ${name} — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ :${port} ${name} — killing PID ${pid}"
    kill_pid "${pid}"
  done
}

kill_by_name() {
  local name="$1"
  local pids=""
  if is_windows; then
    # Map common pattern fragments to Windows image names.
    local image=""
    case "${name}" in
      *ngrok*)       image="ngrok.exe" ;;
      *cloudflared*) image="cloudflared.exe" ;;
      *)             image="${name}" ;;
    esac
    pids=$(tasklist //FI "IMAGENAME eq ${image}" //NH //FO CSV 2>/dev/null \
          | awk -F',' 'NR>=1 {gsub(/"/,"",$2); if ($2 ~ /^[0-9]+$/) print $2}' \
          | sort -u)
  else
    pids=$(pgrep -f "${name}" 2>/dev/null || true)
  fi
  if [[ -z "${pids}" ]]; then
    echo "  · ${name} — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ ${name} — killing PID ${pid}"
    kill_pid "${pid}"
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
