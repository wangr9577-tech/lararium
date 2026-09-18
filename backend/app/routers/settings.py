"""设置读写（真实现）：通用 key-value，前端主题/翻译源/LLM 渠道配置均存这里。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    updates: dict


def _load() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    out = {}
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
    return _load()
