#!/usr/bin/env bash
# 启动 Kruskal（生产：后端托管前端 dist，单端口 18080）
# 用法: ./backend/start.sh [port]
set -euo pipefail
# 本机 shell 常驻 127.0.0.1:7890 代理变量但代理进程常不运行；
# 服务外呼（翻译/LLM 等）一律直连，故清掉代理环境变量。
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
cd "$(dirname "$0")/.."

PY_BIN="${KRUSKAL_PY:-/mnt/data_server/home/stu_wr/miniconda3/envs/site/bin/python}"
PORT="${1:-${KRUSKAL_PORT:-18080}}"

if [ ! -x "$PY_BIN" ]; then
  echo "找不到 Python: $PY_BIN （先 conda create -n site python=3.11）" >&2
  exit 1
fi

echo "[kruskal] starting on 127.0.0.1:$PORT (数据目录见 config.py)"
echo "[kruskal] --reload 已开启：改 backend 代码保存即自动重载，无需手动重启"
exec "$PY_BIN" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT" --reload
