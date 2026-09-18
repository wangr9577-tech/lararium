"""日程日历：按日日程（task/ddl/event）+ 整月计划清单（kind=monthly, date=YYYY-MM）。

打勾口径：task/ddl 计入完成率；event 纯展示。heatmap 按日返回 done/total。
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
TYPES = ("task", "ddl", "event")
KINDS = ("daily", "monthly")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(r) -> dict:
    return {
        "id": r["id"], "date": r["date"], "kind": r["kind"], "type": r["type"],
        "title": r["title"], "time_start": r["time_start"], "note": r["note"],
        "done": bool(r["done"]), "created": r["created_at"],
    }


class EntryIn(BaseModel):
    date: str = Field(min_length=7, max_length=10)
    kind: str = "daily"
    type: str = "task"
    title: str = Field(min_length=1, max_length=200)
    time_start: str = Field(default="", max_length=5)
    note: str = Field(default="", max_length=500)


class DoneIn(BaseModel):
    done: bool


def _validate(body: EntryIn) -> None:
    if body.kind not in KINDS:
        raise HTTPException(400, "kind 只能是 daily / monthly")
    if body.type not in TYPES:
        raise HTTPException(400, "type 只能是 task / ddl / event")
    if body.kind == "monthly":
        if not MONTH_RE.match(body.date):
            raise HTTPException(400, "整月清单的日期应为 YYYY-MM")
    else:
        if not DATE_RE.match(body.date):
            raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
        try:
            datetime.strptime(body.date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "无效日期")
    if body.time_start and not re.match(r"^\d{1,2}:\d{2}$", body.time_start):
        raise HTTPException(400, "时间格式应为 HH:MM")


def _entries(sql: str, args: tuple) -> list[dict]:
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row(r) for r in rows]


@router.get("/range")
def range_entries(from_: str = Query(alias="from"), to: str = Query(alias="to"),
                  _user: dict = Depends(get_current)):
    if not (DATE_RE.match(from_) and DATE_RE.match(to)):
        raise HTTPException(400, "from/to 应为 YYYY-MM-DD")
    return {"items": _entries(
        "SELECT * FROM schedule WHERE kind='daily' AND date BETWEEN ? AND ? ORDER BY date, sort, id",
        (from_, to))}


@router.get("/monthly")
def monthly_entries(month: str, _user: dict = Depends(get_current)):
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month 应为 YYYY-MM")
    return {"items": _entries(
        "SELECT * FROM schedule WHERE kind='monthly' AND date=? ORDER BY done, sort, id", (month,))}


@router.get("/day")
def day_entries(date: str, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    return {"items": _entries(
        "SELECT * FROM schedule WHERE kind='daily' AND date=? ORDER BY done, time_start, sort, id", (date,))}


@router.get("/heatmap")
def schedule_heatmap(year: int | None = None, _user: dict = Depends(get_current)):
    year = year or datetime.now().year
    with db() as conn:
        rows = conn.execute(
            "SELECT date, SUM(done) AS d, COUNT(*) AS c FROM schedule "
            "WHERE kind='daily' AND substr(date,1,4)=? GROUP BY date", (str(year),)).fetchall()
    days = {r["date"]: {"done": r["d"], "total": r["c"]} for r in rows}
    return {"year": year, "days": days}


@router.post("", status_code=201)
def create_entry(body: EntryIn, _user: dict = Depends(get_current)):
    _validate(body)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at) "
            "VALUES(?,?,?,?,?,?,0,0,?)",
            (body.date, body.kind, body.type, body.title.strip(), body.time_start.strip(),
             body.note.strip(), _now()),
        )
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.put("/{entry_id}")
def update_entry(entry_id: int, body: EntryIn, _user: dict = Depends(get_current)):
    _validate(body)
    with db() as conn:
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute(
            "UPDATE schedule SET date=?, kind=?, type=?, title=?, time_start=?, note=? WHERE id=?",
            (body.date, body.kind, body.type, body.title.strip(), body.time_start.strip(),
             body.note.strip(), entry_id),
        )
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
    return _row(row)


@router.put("/{entry_id}/done")
def toggle_done(entry_id: int, body: DoneIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute("UPDATE schedule SET done=? WHERE id=?", (1 if body.done else 0, entry_id))
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
    return _row(row)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM schedule WHERE id=?", (entry_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "条目不存在")
    return {"ok": True}
