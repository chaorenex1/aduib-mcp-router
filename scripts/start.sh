#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 加载环境变量
source scripts/env.sh

echo "[INFO] Project root: $PROJECT_ROOT"

# 1️⃣ 检查 uv
if ! command -v uv >/dev/null 2>&1; then
  echo "[INFO] uv not found, installing..."
  pip install --user uv
fi

# 2️⃣ 创建虚拟环境（若不存在）
if [ ! -d ".venv" ]; then
  echo "[INFO] Creating virtual environment with uv..."
  uv venv
fi

# 3️⃣ 安装依赖（与 Dockerfile 完全一致）
echo "[INFO] Syncing dependencies..."
uv sync --frozen --no-dev

# 4️⃣ 后台启动应用
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "[INFO] Starting app..."
nohup .venv/bin/python aduib_mcp_router/_main_.py \
  > "$LOG_DIR/app.out.log" \
  2> "$LOG_DIR/app.err.log" &

echo $! > app.pid

echo "[SUCCESS] App started"
echo "PID: $(cat app.pid)"