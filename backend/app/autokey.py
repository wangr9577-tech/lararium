"""免密自动解锁（可选，默认关闭）。

解决的问题：DEK 只存在于进程内存（`vault.set_dek`），所以服务器每次重启、
每次开机自启之后都必须重新输入主密码才能读正文——数据并没有更安全，只是麻烦。
开启免密后，启动时用**本机密钥**解开 `.kek.auto` 即可恢复 DEK，无需人工输入。

安全边界（与 README「数据与安全」一节的说法保持一致，别夸大）：

- `.kek.auto` 落在 `DATA_DIR` 里，跟数据一起备份；它本身解不开，单独拿到没用。
- 本机密钥默认落在 **`DATA_DIR` 之外**（`backend/.autokey`，0600，已 gitignore），
  因此 **不会** 被 `deploy/backup.sh` 打进备份包 —— 两个文件分处备份边界两侧，
  拷走备份 = 拿到 `.kek` 与 `.kek.auto` 两道都解不开的密文。
- 开启后，防线从「主密码」降级为「本机文件权限 + 备份口令」：仍然挡住同机其他
  普通用户（`DATA_DIR` 是 0700），**不再** 挡住 root、恶意进程，以及同时拷走
  这两个文件（且能读 git 忽略文件）的人。
- 忘记主密码依旧不可恢复：本机密钥只在当前主机有效，换机器 / 重装 / 从备份还原
  到新机器，都仍然必须用主密码解锁。

关闭方式有三处，任何一种都立即回到「必须输入主密码」：
设置 → 账户安全 的开关（`DELETE /api/auth/auto-unlock`）、
一键上锁（`POST /api/auth/lock` 顺带撤销免密，否则上锁后重启又自动解锁，锁等于没锁）、
或直接删掉 `.kek.auto`。
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


def key_outside_data_dir() -> bool:
    """本机密钥是否落在数据目录之外（= 不会被 backup.sh 打进备份包）。"""
    try:
        config.AUTOKEY_KEY.resolve().relative_to(config.DATA_DIR.resolve())
        return False
    except (ValueError, OSError):
        return True


def enabled() -> bool:
    return config.AUTOKEY_WRAP.is_file() and config.AUTOKEY_KEY.is_file()


def enable(dek: bytes) -> dict:
    """用本机密钥把 DEK 再包一层。调用方必须已经解锁（拿到 DEK）。"""
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
    return {"enabled": True, "key_outside_data": key_outside_data_dir()}


def disable() -> int:
    """删掉包裹与本机密钥，回到必须输入主密码。返回删掉的文件数。"""
    removed = 0
    for path in (config.AUTOKEY_WRAP, config.AUTOKEY_KEY):
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def try_unlock() -> bool:
    """启动时用本机密钥解锁 DEK。任何异常都只当「免密不可用」，绝不阻断启动。"""
    if not enabled():
        return False
    try:
        uk = _b64d(config.AUTOKEY_KEY.read_text(encoding="ascii").strip())
        payload = json.loads(config.AUTOKEY_WRAP.read_text(encoding="utf-8"))
        if int(payload.get("v", 0)) != VERSION:
            return False
        dek = AESGCM(uk).decrypt(_b64d(payload["nonce"]), _b64d(payload["ct"]), _AAD)
    except Exception as exc:  # 密钥被删/被改/换机器/格式不符：都退回主密码
        logging.getLogger("kruskal").warning("免密解锁不可用，需输入主密码：%s", exc)
        return False
    if len(dek) != 32:
        return False
    vault.set_dek(dek)
    return True
