#!/usr/bin/env bash
# 还原 Kruskal 数据目录（会替换当前 backend/data —— 旧目录先备份为 backend/data.bak-<时间戳>，不物理删除）
# 用法: ./deploy/restore.sh <备份文件.tar.gz.enc|.tar.gz> [备份口令]
#   - .tar.gz.enc：openssl 解密（口令第二参数传入，否则交互输入；cron 可用 KRUSKAL_BACKUP_PW）
#   - 旧版明文 .tar.gz：直接解包（兼容历史备份）
#   - 同名 .sha256 存在时先做完整性校验
set -euo pipefail
cd "$(dirname "$0")/.."

[ $# -ge 1 ] || { echo "用法: $0 <备份文件> [备份口令]" >&2; exit 1; }
SRC="$1"
[ -f "$SRC" ] || { echo "找不到备份文件: $SRC" >&2; exit 1; }

# 1) 完整性校验
SHA="${SRC}.sha256"
if [ -f "$SHA" ]; then
  ( cd "$(dirname "$SRC")" && sha256sum -c "$(basename "$SHA")" ) || { echo "sha256 校验失败：文件不完整或被篡改" >&2; exit 1; }
  echo "[restore] sha256 校验通过"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 2) 解密（若是 .enc）
TARBALL="$SRC"
if [ "${SRC##*.}" = "enc" ]; then
  PW="${2:-${KRUSKAL_BACKUP_PW:-}}"
  if [ -z "$PW" ]; then
    printf '备份口令: ' >&2; IFS= read -rs PW </dev/tty; printf '\n' >&2
  fi
  [ -n "$PW" ] || { echo "[restore] 口令不能为空" >&2; exit 1; }
  printf '%s' "$PW" > "$WORK/.pw"; chmod 600 "$WORK/.pw"
  tarball="$WORK/data.tar.gz"
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -d -pass file:"$WORK/.pw" -in "$SRC" -out "$tarball" \
    || { echo "[restore] 解密失败（口令错误或文件损坏）" >&2; exit 1; }
  TARBALL="$tarball"
  unset PW
fi

# 3) 解包到 staging，校验成员结构（backup.sh 约定成员为 data/...）
tar -tzf "$TARBALL" >/dev/null
# 注意：set -o pipefail 下 `tar|head|grep` 会因 head 提前关管道让 tar 吃 SIGPIPE(141) 而整链判非零——
# 曾导致一切合法备份都被误判"结构异常"。先单独取首行再判前缀。
top="$(tar -tzf "$TARBALL" | head -n1 || true)"
[ "${top#data/}" != "$top" ] || { echo "[restore] 归档结构异常（顶层不是 data/），中止" >&2; exit 1; }
tar -xzf "$TARBALL" -C "$WORK"

# 4) 停服检查
if pgrep -f 'uvicorn app.main:app' >/dev/null 2>&1; then
  echo "[restore] 警告: 检测到 Kruskal 服务正在运行 —— 请先停止（Ctrl+C 或 kill 对应进程）再还原，避免半新半旧。" >&2
fi

# 5) 确认并原子换入（旧 data 保留为 data.bak-*，绝不 rm）
DATA_DIR="${KRUSKAL_DATA_DIR:-${KRUSKAL_DATA:-backend/data}}"
if [ -d "$DATA_DIR" ] && [ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
  echo "警告: 将用备份整体替换 $DATA_DIR（旧目录自动备份为 $DATA_DIR.bak-<时间戳>，不会删除）。" >&2
  read -r -p "确认还原？输入 yes 继续: " ok </dev/tty || ok=""
  [ "$ok" = "yes" ] || { echo "已取消"; exit 1; }
  STAMP="$(date +%Y%m%d-%H%M%S)"
  mv "$DATA_DIR" "$DATA_DIR.bak-$STAMP"
  echo "[restore] 旧数据已保留为 $DATA_DIR.bak-$STAMP（确认还原无误后可自行清理）"
fi
mkdir -p "$(dirname "$DATA_DIR")"
mv "$WORK/data" "$DATA_DIR"
chmod 700 "$DATA_DIR"
echo "还原完成。请重启服务: bash backend/start.sh"
