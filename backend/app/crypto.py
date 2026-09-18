"""AES-256-GCM 静态加密工具（后端基建，功能期写入正文时使用）。

威胁模型：共享服务器上"其他普通用户直接读文件"不可行。
  内容文件加密 key = DEK；DEK 由登录主密码经 scrypt 派生后包裹存 .kek。
  root/管理员级别仍可读进程内存 —— 这是静态加密的边界，方案中已声明。

用法（登录流程）：
  payload, dek = crypto.create_keywrap(password)      # 首次登录创建
  dek = crypto.unwrap_keywrap(payload, password)      # 校验/解锁
  blob = crypto.enc_bytes(plain, dek)                  # 写正文文件
  plain = crypto.dec_bytes(blob, dek)                  # 读正文文件
"""
from __future__ import annotations

import base64
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = 1
MAGIC = b"KRSLC1\n"          # 加密文件头
SALT_LEN = 16
NONCE_LEN = 12

_b64e = lambda b: base64.b64encode(b).decode("ascii")
_b64d = lambda s: base64.b64decode(s.encode("ascii"))


def derive_key(password: str, salt: bytes) -> bytes:
    """scrypt 派生 KEK（对主密码做抗暴力破解拉伸）。"""
    return Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1).derive(password.encode("utf-8"))


def new_dek() -> bytes:
    return secrets.token_bytes(32)


def _wrap_payload(dek: bytes, kek: bytes, salt: bytes) -> dict:
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(kek).encrypt(nonce, dek, None)
    return {"v": VERSION, "salt": _b64e(salt), "nonce": _b64e(nonce), "ct": _b64e(ct)}


def create_keywrap(password: str) -> tuple[dict, bytes]:
    """用主密码创建密钥包裹，返回 (payload, dek)。payload 落盘 .kek，dek 仅驻内存。"""
    salt = secrets.token_bytes(SALT_LEN)
    kek = derive_key(password, salt)
    dek = new_dek()
    return _wrap_payload(dek, kek, salt), dek


def create_keywrap_with_dek(password: str, dek: bytes) -> dict:
    salt = secrets.token_bytes(SALT_LEN)
    kek = derive_key(password, salt)
    return _wrap_payload(dek, kek, salt)


def unwrap_keywrap(payload: dict, password: str) -> bytes | None:
    """密码正确返回 DEK，错误返回 None。"""
    try:
        kek = derive_key(password, _b64d(payload["salt"]))
        return AESGCM(kek).decrypt(_b64d(payload["nonce"]), _b64d(payload["ct"]), None)
    except Exception:
        return None


def rewrap_keywrap(payload: dict, old_password: str, new_password: str) -> dict:
    """改密：用旧密码解出 DEK，再用新密码重新包裹。"""
    dek = unwrap_keywrap(payload, old_password)
    if dek is None:
        raise ValueError("旧密码不正确，无法解锁数据密钥")
    return create_keywrap_with_dek(new_password, dek)


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
