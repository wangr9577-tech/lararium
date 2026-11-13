"""AES-256-GCM 静态加密工具（后端基建，正文/附件落盘时使用）。

单机模式：DEK 由启动时解锁的本机密钥（`app/autokey.py`）恢复，不再有主密码派生。

  dek = crypto.new_dek()                # 首次启动生成数据密钥
  blob = crypto.enc_bytes(plain, dek)   # 写正文文件
  plain = crypto.dec_bytes(blob, dek)   # 读正文文件
"""
from __future__ import annotations

import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KRSLC1\n"          # 加密文件头
NONCE_LEN = 12


def new_dek() -> bytes:
    return secrets.token_bytes(32)


# ---------- 文件级加解密 ----------

def enc_bytes(plain: bytes, dek: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(dek).encrypt(nonce, plain, None)
    return MAGIC + nonce + ct


def dec_bytes(blob: bytes, dek: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("文件不是 Kruskal 加密格式")
    nonce = blob[len(MAGIC): len(MAGIC) + NONCE_LEN]
    ct = blob[len(MAGIC) + NONCE_LEN:]
    return AESGCM(dek).decrypt(nonce, ct, None)


def to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
