"""本机数据密钥（DEK）的持久化解锁。

DEK 只存在于进程内存（`vault.set_dek`），所以每次重启都必须能重新拿到它。
单机模式下不再有主密码，改为：启动时用**本机密钥**解开 `.kek.auto` 恢复 DEK。

安全边界（与 README「数据与安全」一节保持一致，别夸大）：

- `.kek.auto`（包裹）与 `.autokey`（本机密钥）都落在 `DATA_DIR` 里，跟数据一起备份。
  因此它们**挡不住**能读到整个数据目录或备份包的人：本机加密的边界是文件权限
  （`DATA_DIR` 0700）+ 操作系统账户，而不是密码。
- 它仍然挡住「只拿到单个文件」或「同机其他普通用户」的场景；应保护本机账户、
  数据目录与备份文件，且不要把服务暴露到本机以外。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config, vault

VERSION = 1
_AAD = b"kruskal-autokey-v1"   # 绑定用途：别的场景加密出来的 blob 不会被当成本机密钥解开

_b64e = lambda b: base64.b64encode(b).decode("ascii")
_b64d = lambda s: base64.b64decode(s.encode("ascii"))


def _secret_to_0600(path) -> None:
    try:
        os.chmod(path, 0o600)  # 同机其他普通用户不可读；NFS 等场景可能被拒
    except OSError:
        pass


def enabled() -> bool:
    return config.AUTOKEY_WRAP.is_file() and config.AUTOKEY_KEY.is_file()


def enable(dek: bytes) -> None:
    """用本机密钥把 DEK 再包一层（首次启动、数据目录为空时调用）。"""
    uk = secrets.token_bytes(32)
    key_path = config.AUTOKEY_KEY
    key_path.parent.mkdir(parents=True, exist_ok=True)
    vault.atomic_write_bytes(key_path, _b64e(uk).encode("ascii"))
    _secret_to_0600(key_path)

    nonce = secrets.token_bytes(12)
    ct = AESGCM(uk).encrypt(nonce, dek, _AAD)
    payload = {"v": VERSION, "alg": "AES-256-GCM", "nonce": _b64e(nonce), "ct": _b64e(ct)}
    config.AUTOKEY_WRAP.parent.mkdir(parents=True, exist_ok=True)
    vault.atomic_write_bytes(config.AUTOKEY_WRAP, json.dumps(payload).encode("utf-8"))
    _secret_to_0600(config.AUTOKEY_WRAP)


def try_unlock() -> bool:
    """启动时用本机密钥解锁 DEK；解不开就返回 False，由调用方决定是否中止启动。"""
    if not enabled():
        return False
    try:
        uk = _b64d(config.AUTOKEY_KEY.read_text(encoding="ascii").strip())
        payload = json.loads(config.AUTOKEY_WRAP.read_text(encoding="utf-8"))
        if int(payload.get("v", 0)) != VERSION:
            return False
        dek = AESGCM(uk).decrypt(_b64d(payload["nonce"]), _b64d(payload["ct"]), _AAD)
    except Exception as exc:  # 密钥被删/被改/换机器/格式不符
        logging.getLogger("kruskal").warning("本机数据密钥解锁失败：%s", exc)
        return False
    if len(dek) != 32:
        return False
    vault.set_dek(dek)
    return True
