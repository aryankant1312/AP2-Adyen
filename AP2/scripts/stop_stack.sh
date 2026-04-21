#!/usr/bin/env bash
# Tear down the AP2 pharmacy stack started by scripts/start_stack.sh.
#
# Kills any process listening on :8001/:8002/:8003/:8080 plus any running
# ngrok or cloudflared. Idempotent — silent if nothing is up.

set -uo pipefail

kill_port() {
  local port="$1" name="$2"
  local pid
  pid=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTENING \
        | awk '{print $NF}' | head -1)
  if [[ -z "${pid}" || "${pid}" == "0" ]]; then
    echo "  · :${port} ${name} — not running"
    return 0
  fi
  echo "  ✗ :${port} ${name} — killing PID ${pid}"
  powershell -NoProfile -Command "Stop-Process -Id ${pid} -Force" \
      >/dev/null 2>&1 || true
}

kill_ngrok() {
  local pids
  pids=$(powershell -NoProfile -Command \
         "(Get-Process -Name ngrok -ErrorAction SilentlyContinue).Id" \
         2>/dev/null | tr -d '\r' | grep -v '^$' || true)
  if [[ -z "${pids}" ]]; then
    echo "  · ngrok — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ ngrok — killing PID ${pid}"
    powershell -NoProfile -Command "Stop-Process -Id ${pid} -Force" \
        >/dev/null 2>&1 || true
  done
}

kill_cloudflared() {
  local pids
  pids=$(powershell -NoProfile -Command \
         "(Get-Process -Name cloudflared -ErrorAction SilentlyContinue).Id" \
         2>/dev/null | tr -d '\r' | grep -v '^$' || true)
  if [[ -z "${pids}" ]]; then
    echo "  · cloudflared — not running"
    return 0
  fi
  for pid in ${pids}; do
    echo "  ✗ cloudflared — killing PID ${pid}"
    powershell -NoProfile -Command "Stop-Process -Id ${pid} -Force" \
        >/dev/null 2>&1 || true
  done
}

echo "==> stopping AP2 stack"
kill_port 8080 "gateway"
kill_port 8003 "mpp"
kill_port 8002 "cp"
kill_port 8001 "merchant"
kill_ngrok
kill_cloudflared
echo "==> done"
