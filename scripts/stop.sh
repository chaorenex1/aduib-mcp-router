#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -f app.pid ]; then
  echo "[WARN] app.pid not found, app may not be running"
  exit 0
fi

PID=$(cat app.pid)

if ps -p "$PID" >/dev/null 2>&1; then
  echo "[INFO] Stopping app (PID=$PID)..."
  kill "$PID"

  # 等待进程退出
  sleep 2

  if ps -p "$PID" >/dev/null 2>&1; then
    echo "[WARN] Process still running, force killing..."
    kill -9 "$PID"
  fi
else
  echo "[INFO] Process already stopped"
fi

rm -f app.pid

echo "[SUCCESS] App stopped"