#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

PID_FILE="app.pid"
LOG_FILE="app.log"

# ─── config check ─────────────────────────────────────────
if [ ! -f config.json ]; then
  if [ -f config.json.example ]; then
    echo "config.json not found, copying from config.json.example ..."
    cp config.json.example config.json
    echo "Please edit config.json with your cluster info, then re-run this script."
    exit 1
  else
    echo "config.json not found. Create it first (see config.json.example)."
    exit 1
  fi
fi

# ─── python & venv ────────────────────────────────────────
PYTHON=python3
command -v python3 >/dev/null 2>&1 || PYTHON=python

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

# ─── commands ─────────────────────────────────────────────
is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "$1" in
  stop)
    if is_running; then
      PID=$(cat "$PID_FILE")
      kill "$PID"
      echo "Stopped (PID $PID)"
    else
      echo "Not running"
    fi
    rm -f "$PID_FILE"
    exit 0
    ;;
  status)
    if is_running; then
      echo "Running (PID $(cat "$PID_FILE")), log: $LOG_FILE"
    else
      echo "Not running"
    fi
    exit 0
    ;;
  restart)
    "$0" stop || true
    sleep 1
    exec "$0"
    ;;
esac

# ─── start (default, background) ──────────────────────────
if is_running; then
  echo "Already running (PID $(cat "$PID_FILE"))"
  echo "Use './start.sh stop' or './start.sh restart'"
  exit 0
fi

echo "Starting Apache Doris 作业平台 ..."
nohup "$PYTHON" app.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 2
if is_running; then
  echo "Started in background (PID $(cat "$PID_FILE"))"
  echo "  Web UI : http://localhost:5000"
  echo "  Log    : $LOG_FILE"
  echo "  Stop   : ./start.sh stop"
else
  echo "Failed to start, check $LOG_FILE"
  rm -f "$PID_FILE"
  exit 1
fi
