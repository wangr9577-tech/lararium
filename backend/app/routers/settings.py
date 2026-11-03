"""设置读写（真实现）：通用 key-value，前端主题/翻译源/LLM 渠道配置均存这里。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import config
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    updates: dict


def _load() -> dict:
    """优先从受 .gitignore 保护的独立本地配置文件读取；若不存在则查 sqlite。"""
    if config.LOCAL_SETTINGS_PATH.is_file():
        try:
            local_data = json.loads(config.LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(local_data, dict) and len(local_data) > 0:
                return local_data
        except Exception:
            pass

    out = {}
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value"]
    return out


@router.get("")
def get_settings(_user: dict = Depends(get_current)):
    return _load()


@router.put("")
def put_settings(body: SettingsIn, _user: dict = Depends(get_current)):
    with db() as conn:
        for key, value in body.updates.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    # 重新从 DB 取出所有设置项
    latest = {}
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        try:
            latest[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            latest[r["key"]] = r["value"]

    # 安全同步写入受 .gitignore 严格忽略的独立本地配置文件 local_settings.json
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.LOCAL_SETTINGS_PATH.write_text(
            json.dumps(latest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return latest
