"""vault：进程内持有数据密钥(DEK)，提供加密正文文件的读写统一入口。

解锁时机：登录 / 修改密码成功后由 routers.auth 注入 DEK。
未解锁时抛 423（前端拦截后引导重新登录，登录即自动解锁）。

所有落盘写入一律原子化：同目录临时文件 + fsync + os.replace，
避免崩溃/掉电留下半截密文导致整个文件报废。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException

from . import crypto

_dek: bytes | None = None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """同目录临时文件 + fsync + os.replace 的原子写（0600 权限）。"""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_dek(dek: bytes) -> None:
    global _dek
    _dek = dek


def clear_dek() -> None:
    global _dek
    _dek = None


def has_dek() -> bool:
    return _dek is not None


def dek() -> bytes:
    if _dek is None:
        raise HTTPException(status_code=423, detail="数据未解锁，请重新登录后重试")
    return _dek


# ---------- 文本文件 ----------

def read_text(path: Path) -> str:
    return crypto.dec_bytes(path.read_bytes(), dek()).decode("utf-8")


def write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, crypto.enc_bytes(text.encode("utf-8"), dek()))


# ---------- 二进制文件（PDF 等） ----------

def read_bytes(path: Path) -> bytes:
    return crypto.dec_bytes(path.read_bytes(), dek())


def write_bytes(path: Path, data: bytes) -> None:
    atomic_write_bytes(path, crypto.enc_bytes(data, dek()))


# ---------- JSON 文件 ----------

def read_json(path: Path) -> dict:
    return json.loads(read_text(path))


def write_json(path: Path, payload: dict) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
