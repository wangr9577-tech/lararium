"""每日专注时长：开始/结束计时、漏记补录、统计与可视化数据接口。

focus 表（SQLite）：
  start/end 本地时间字符串 'YYYY-MM-DD HH:MM:SS'；end 为空 = 进行中；
  minutes 为结束时的分钟数；补录记录 start=当日 00:00:00、end=23:59:59。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/focus", tags=["focus"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _elapsed_min(start: str) -> int:
    try:
        s = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        return max(1, int((datetime.now() - s).total_seconds() // 60))
    except ValueError:
        return 1


def _row(row) -> dict | None:
    if row is None:
        return None
    ms = None
    try:
        ms = int(time.mktime(time.strptime(row["start"], "%Y-%m-%d %H:%M:%S")) * 1000)
    except (ValueError, OverflowError):
        pass
    return {
        "id": row["id"], "start": row["start"], "end": row["end"],
        "minutes": row["minutes"], "note": row["note"], "start_ms": ms,
    }


class StartIn(BaseModel):
    note: str = Field(default="", max_length=200)


class StopIn(BaseModel):
    id: int


class ManualIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(default="", max_length=200)


@router.post("/start")
def start_focus(body: StartIn, _user: dict = Depends(get_current)):
    with db() as conn:
        running = conn.execute("SELECT * FROM focus WHERE end IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if running:
            raise HTTPException(400, "已有进行中的专注，请先结束它")
        cur = conn.execute(
            "INSERT INTO focus(start, end, minutes, note, created_at) VALUES(?, NULL, 0, ?, ?)",
            (_now(), body.note.strip(), _now()),
        )
        row = conn.execute("SELECT * FROM focus WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.get("/running")
def running_focus(_user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM focus WHERE end IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return {"running": _row(row)}


@router.post("/stop")
def stop_focus(body: StopIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM focus WHERE id=? AND end IS NULL", (body.id,)).fetchone()
        if row is None:
            raise HTTPException(404, "没有找到进行中的专注会话")
        minutes = _elapsed_min(row["start"])
        end = _now()
        conn.execute("UPDATE focus SET end=?, minutes=? WHERE id=?", (end, minutes, body.id))
        row = conn.execute("SELECT * FROM focus WHERE id=?", (body.id,)).fetchone()
    r = _row(row)
    return {**r, "minutes": minutes}


@router.post("/manual")
def manual_focus(body: ManualIn, _user: dict = Depends(get_current)):
    if not DATE_RE.match(body.date):
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO focus(start, end, minutes, note, created_at) VALUES(?,?,?,?,?)",
            (f"{body.date} 00:00:00", f"{body.date} 23:59:59", body.minutes, body.note.strip(), _now()),
        )
        row = conn.execute("SELECT * FROM focus WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.delete("/{focus_id}")
def delete_focus(focus_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM focus WHERE id=?", (focus_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.get("/stats")
def focus_stats(days: int = 30, _user: dict = Depends(get_current)):
    days = max(1, min(days, 366))
    with db() as conn:
        rows = conn.execute(
            "SELECT substr(start,1,10) AS d, SUM(minutes) AS m, COUNT(*) AS c "
            "FROM focus WHERE end IS NOT NULL GROUP BY d"
        ).fetchall()
        running = conn.execute("SELECT * FROM focus WHERE end IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        recent = conn.execute(
            "SELECT * FROM focus WHERE end IS NOT NULL ORDER BY id DESC LIMIT 10"
        ).fetchall()

    by_day = {r["d"]: {"minutes": r["m"], "sessions": r["c"]} for r in rows}
    today = datetime.now().strftime("%Y-%m-%d")
    today_min = by_day.get(today, {}).get("minutes", 0)
    today_cnt = by_day.get(today, {}).get("sessions", 0)
    run = _row(running)
    if run:
        today_min += _elapsed_min(run["start"])

    daily = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        daily.append({"date": d, "minutes": by_day.get(d, {}).get("minutes", 0)})

    return {
        "today": {"date": today, "minutes": today_min, "sessions": today_cnt, "running": run},
        "daily": daily,
        "recent": [_row(r) for r in recent],
    }


@router.get("/heatmap")
def focus_heatmap(year: int | None = None, _user: dict = Depends(get_current)):
    year = year or datetime.now().year
    with db() as conn:
        rows = conn.execute(
            "SELECT substr(start,1,10) AS d, SUM(minutes) AS m FROM focus "
            "WHERE end IS NOT NULL AND substr(start,1,4)=? GROUP BY d",
            (str(year),),
        ).fetchall()
    return {"year": year, "days": {r["d"]: r["m"] for r in rows}}
