"""vault：进程内持有数据密钥(DEK)，提供加密正文文件的读写统一入口。

解锁时机：服务启动时由 `app/autokey.py` 用本机密钥注入 DEK（见 main.py）。
未解锁时抛 423（正常情况下启动阶段就会中止，不会跑到这里）。

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
_epoch: int = 0


def epoch() -> int:
    """返回当前数据密钥世代号（DEK Epoch），每次 set_dek/clear_dek 自增。"""
    return _epoch


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
    global _dek, _epoch
    _dek = dek
    _epoch += 1


def clear_dek() -> None:
    global _dek, _epoch
    _dek = None
    _epoch += 1


def has_dek() -> bool:
    return _dek is not None


def dek() -> bytes:
    if _dek is None:
        raise HTTPException(status_code=423, detail="数据未解锁，请重启本机服务后重试")
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
