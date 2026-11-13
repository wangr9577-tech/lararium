"""24h 每日时间表：按日期 + 格子起始分钟（slot_min）存一条文字。

行距（30 分钟 / 20 分钟）只是前端视图口径，存储只认 slot_min：
前端渲染某行 [t, t+span) 时显示落在该区间内的条目；保存某行时带上 span，
后端先删掉该行区间内的旧条目再写入，两种行距切换互不丢字、也不会重复显示。
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/timetable", tags=["timetable"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _check_date(date: str) -> None:
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")


class SlotIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    slot_min: int = Field(ge=0, lt=1440)
    text: str = Field(default="", max_length=300)
    # 当前行距（分钟）：保存时覆盖 [slot_min, slot_min+span) 的旧条目
    span: int = Field(default=30, ge=5, le=1440)


@router.get("/day")
def day_slots(date: str, _user: dict = Depends(get_current)):
    _check_date(date)
    with db() as conn:
        rows = conn.execute(
            "SELECT slot_min, text FROM timetable WHERE date=? ORDER BY slot_min",
            (date,)).fetchall()
    return {"items": [{"slot_min": r["slot_min"], "text": r["text"]} for r in rows]}


@router.put("/slot")
def put_slot(body: SlotIn, _user: dict = Depends(get_current)):
    _check_date(body.date)
    text = body.text.strip()
    with db() as conn:
        # 先清掉该行 span 覆盖范围内的旧条目（含另一种行距下写入的），再按新起点写入
        conn.execute(
            "DELETE FROM timetable WHERE date=? AND slot_min>=? AND slot_min<?",
            (body.date, body.slot_min, body.slot_min + body.span),
        )
        if text:
            conn.execute(
                "INSERT INTO timetable(date, slot_min, text, updated) VALUES(?,?,?,?) "
                "ON CONFLICT(date, slot_min) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                (body.date, body.slot_min, text, _now()),
            )
    return {"ok": True}


@router.delete("/day")
def clear_day(date: str, _user: dict = Depends(get_current)):
    _check_date(date)
    with db() as conn:
        conn.execute("DELETE FROM timetable WHERE date=?", (date,))
    return {"ok": True}
