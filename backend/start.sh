#!/usr/bin/env bash
# 启动 Kruskal（生产：后端托管前端 dist，单端口 18080）
# 用法: ./backend/start.sh [port]
# 环境变量：KRUSKAL_HOST（默认 127.0.0.1）、KRUSKAL_PORT（默认 18080）、
#           KRUSKAL_DEV=1 才开 --reload（P1：生产重载会反复清空内存密钥，已默认关闭）
# 注意：开发模式（改码自动重载）请用 KRUSKAL_DEV=1 ./backend/start.sh，别在生产常驻开。
set -euo pipefail
# 本机 shell 常驻 127.0.0.1:7890 代理变量但代理进程常不运行；
# 服务外呼（翻译/一言 等）一律直连，故清掉代理环境变量。
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
cd "$(dirname "$0")/.."

PY_BIN="${KRUSKAL_PY:-/mnt/data_server/home/stu_wr/miniconda3/envs/site/bin/python}"
HOST="${KRUSKAL_HOST:-127.0.0.1}"
PORT="${1:-${KRUSKAL_PORT:-18080}}"

if [ ! -x "$PY_BIN" ]; then
  echo "找不到 Python: $PY_BIN （先 conda create -n site python=3.11）" >&2
  exit 1
fi

RELOAD_ARGS=()
if [ "${KRUSKAL_DEV:-0}" = "1" ]; then
  RELOAD_ARGS+=(--reload)
  echo "[kruskal] DEV 模式：--reload 已开（注意：每次重载都会清空内存密钥，需重新登录解锁）"
fi

echo "[kruskal] starting on $HOST:$PORT (数据目录见 config.py)"
exec "$PY_BIN" -m uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT" "${RELOAD_ARGS[@]}"
