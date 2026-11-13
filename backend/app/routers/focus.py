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
# 早期番茄钟自动写入的备注「番茄钟 25 分钟（提前结束）」：不是用户起的名字，
# 按名字聚合时归到「专注」，否则每个时长都会切出一块饼。
LEGACY_NOTE_RE = re.compile(r"^番茄钟\s*\d+\s*分钟")
UNNAMED = "专注"


def _label(note: str | None) -> str:
    """专注记录的名字（存在 note 字段里）。"""
    n = (note or "").strip()
    if not n or LEGACY_NOTE_RE.match(n):
        return UNNAMED
    return n


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
        "source": row["source"], "schedule_id": row["schedule_id"],
    }


class StartIn(BaseModel):
    note: str = Field(default="", max_length=200)


class StopIn(BaseModel):
    id: int


class ManualIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(default="", max_length=200)
    source: str = "manual"
    schedule_id: int | None = None


class NoteIn(BaseModel):
    """改名字：番茄钟的「名字」就是这一行的 note，允许清空。"""
    note: str = Field(default="", max_length=200)
    date: str | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)


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
    if body.source not in ("manual", "countdown", "stopwatch"):
        raise HTTPException(400, "无效记录类型")
    with db() as conn:
        # 任务在计时期间可能被删除；保留专注记录，解除已失效的关联。
        schedule_id = body.schedule_id
        if schedule_id is not None and not conn.execute("SELECT 1 FROM schedule WHERE id=?", (schedule_id,)).fetchone():
            schedule_id = None
        cur = conn.execute(
            "INSERT INTO focus(start, end, minutes, note, created_at, source, schedule_id) VALUES(?,?,?,?,?,?,?)",
            (f"{body.date} 00:00:00", f"{body.date} 23:59:59", body.minutes, body.note.strip(), _now(), body.source, schedule_id),
        )
        row = conn.execute("SELECT * FROM focus WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.patch("/{focus_id}")
def rename_focus(focus_id: int, body: NoteIn, _user: dict = Depends(get_current)):
    """给一条专注记录改名（note = 名字），传空串即清空。"""
    note = body.note.strip()
    with db() as conn:
        if conn.execute("SELECT 1 FROM focus WHERE id=?", (focus_id,)).fetchone() is None:
            raise HTTPException(404, "记录不存在")
        row = conn.execute("SELECT * FROM focus WHERE id=?", (focus_id,)).fetchone()
        if row["end"] is None:
            raise HTTPException(400, "不能编辑进行中的专注")
        start, end = row["start"], row["end"]
        if body.date is not None:
            try:
                if not DATE_RE.match(body.date): raise ValueError()
                datetime.strptime(body.date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "无效日期")
            start, end = body.date + start[10:], body.date + end[10:]
        conn.execute("UPDATE focus SET note=?, start=?, end=?, minutes=? WHERE id=?",
                     (note, start, end, body.minutes if body.minutes is not None else row["minutes"], focus_id))
        row = conn.execute("SELECT * FROM focus WHERE id=?", (focus_id,)).fetchone()
    return _row(row)


@router.delete("/{focus_id}")
def delete_focus(focus_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM focus WHERE id=?", (focus_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.get("/records")
def focus_records(q: str = "", from_date: str = "", to_date: str = "", _user: dict = Depends(get_current)):
    for date in (from_date, to_date):
        if date:
            try:
                if not DATE_RE.match(date): raise ValueError()
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "无效日期")
    sql = "SELECT * FROM focus WHERE end IS NOT NULL"
    args: list = []
    if q:
        sql += " AND instr(lower(note), lower(?)) > 0"
        args.append(q[:200])
    if from_date:
        sql += " AND substr(start,1,10) >= ?"
        args.append(from_date)
    if to_date:
        sql += " AND substr(start,1,10) <= ?"
        args.append(to_date)
    sql += " ORDER BY start DESC, id DESC LIMIT 500"
    with db() as conn:
        return {"items": [_row(r) for r in conn.execute(sql, args).fetchall()]}


@router.get("/breakdown")
def focus_breakdown(days: int = 30, _user: dict = Depends(get_current)):
    """按「名字」聚合近 N 天的专注分钟数，饼图用（名字就是 note 字段）。"""
    days = max(1, min(days, 366))
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT note, minutes FROM focus "
            "WHERE end IS NOT NULL AND minutes > 0 AND substr(start,1,10) >= ?",
            (since,),
        ).fetchall()

    agg: dict[str, dict[str, int]] = {}
    total = 0
    for r in rows:
        m = int(r["minutes"] or 0)
        item = agg.setdefault(_label(r["note"]), {"minutes": 0, "sessions": 0})
        item["minutes"] += m
        item["sessions"] += 1
        total += m

    items = [{"name": name, **v} for name, v in agg.items()]
    items.sort(key=lambda x: (-x["minutes"], x["name"]))
    return {"days": days, "since": since, "total": total, "items": items}



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
