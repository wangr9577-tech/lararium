#!/usr/bin/env bash
# 备份 Kruskal 数据目录：sqlite 一致性快照 → tar → openssl AES-256 口令加密 → .tar.gz.enc + .sha256
#
# 说明：
#   - site.db 用 python stdlib sqlite3.backup() 先做一致性快照再打包（WAL 模式直拷会撕裂/丢最近数据）；
#   - 归档用 openssl enc（PBKDF2 60万次迭代 + 随机盐）加密——需要【备份口令】，
#     与数据密钥相互独立：备份口令忘记 = 备份不可恢复；数据目录泄露 ≠ 备份泄露。
#   - 恢复：deploy/restore.sh <文件.tar.gz.enc>（会先校验 sha256）。
#   - cron 非交互场景：设 KRUSKAL_BACKUP_PW 环境变量（注意该方式口令可被同机用户从进程环境读出，权衡使用）。
# 用法: ./deploy/backup.sh [输出目录，默认 <仓库根>/backups]
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-backups}"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
ENC="$OUT/kruskal-data-$STAMP.tar.gz.enc"

PY_BIN="${KRUSKAL_PY:-python3}"
[ -x "$PY_BIN" ] || PY_BIN="$(command -v python3 || command -v python || echo python3)"

DATA_DIR="${KRUSKAL_DATA_DIR:-${KRUSKAL_DATA:-backend/data}}"
DATA_PARENT="$(dirname "$DATA_DIR")"
DATA_BASENAME="$(basename "$DATA_DIR")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 1) SQLite 一致性快照（含 WAL 中未 checkpoint 的数据）
if [ -f "$DATA_DIR/site.db" ]; then
  "$PY_BIN" - "$WORK/site.db" "$DATA_DIR/site.db" <<'PYEOF'
import sqlite3, sys
dst = sqlite3.connect(sys.argv[1])
src = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close(); dst.close()
print("[backup] sqlite 快照完成（WAL 已并入）")
PYEOF
else
  echo "[backup] 提示: $DATA_DIR/site.db 不存在（首次备份前请至少启动一次服务）" >&2
fi

# 2) 打 tar：排除运行残留；活动库换成快照（成员名保持 data/... 前缀，restore.sh 依赖此约定）
# 注意：GNU tar 的 --exclude 必须放在目录操作数之前，否则报 "has no effect"
tar -cf "$WORK/data.tar" \
  --exclude "$DATA_BASENAME/tmp" --exclude "$DATA_BASENAME/.git" --exclude "$DATA_BASENAME/site.db*" \
  -C "$DATA_PARENT" "$DATA_BASENAME"
if [ -f "$WORK/site.db" ]; then
  mkdir -p "$WORK/stage/$DATA_BASENAME"
  mv "$WORK/site.db" "$WORK/stage/$DATA_BASENAME/site.db"
  tar -rf "$WORK/data.tar" -C "$WORK/stage" "$DATA_BASENAME"
fi
gzip -c "$WORK/data.tar" > "$WORK/data.tar.gz"

# 3) 口令加密（优先 env，否则交互式两次输入，经 fd 传递不落 ps）
if [ -n "${KRUSKAL_BACKUP_PW:-}" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
    -pass env:KRUSKAL_BACKUP_PW -in "$WORK/data.tar.gz" -out "$ENC"
else
  printf '备份口令: ' >&2; IFS= read -rs PW1 </dev/tty; printf '\n' >&2
  printf '再次输入确认: ' >&2; IFS= read -rs PW2 </dev/tty; printf '\n' >&2
  if [ "$PW1" != "$PW2" ]; then echo "[backup] 两次口令不一致，中止" >&2; exit 1; fi
  [ -n "$PW1" ] || { echo "[backup] 口令不能为空（非交互场景请设 KRUSKAL_BACKUP_PW）" >&2; exit 1; }
  printf '%s' "$PW1" > "$WORK/.pw"; chmod 600 "$WORK/.pw"
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
    -pass file:"$WORK/.pw" -in "$WORK/data.tar.gz" -out "$ENC"
  unset PW1 PW2
fi
chmod 600 "$ENC"
( cd "$OUT" && sha256sum "$(basename "$ENC")" > "$(basename "$ENC").sha256" )

echo "备份完成: $ENC（含 .sha256 校验文件，请一并保存）"
echo "提示: 建议把 .enc 与 .sha256 一起 rsync 到 NAS 或异地存储的另一安全位置。"
