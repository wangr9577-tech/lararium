"""日程日历：按日日程（task/ddl/event）+ 整月计划清单（kind=monthly, date=YYYY-MM）。

打勾口径：task/ddl 计入完成率；event 纯展示。heatmap 按日返回 done/total。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import uuid4

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
        "priority": r["priority"], "estimate_min": r["estimate_min"], "series_id": r["series_id"],
    }


class EntryIn(BaseModel):
    date: str = Field(min_length=7, max_length=10)
    kind: str = "daily"
    type: str = "task"
    title: str = Field(min_length=1, max_length=200)
    time_start: str = Field(default="", max_length=5)
    note: str = Field(default="", max_length=500)
    priority: str | None = None
    estimate_min: int | None = Field(default=None, ge=1, le=1440)
    repeat: str = "none"
    repeat_until: str = ""
    scope: str = "one"


class DoneIn(BaseModel):
    done: bool


def _validate(body: EntryIn) -> None:
    if body.priority not in (None, "", "low", "medium", "high"):
        raise HTTPException(400, "无效优先级")
    if body.repeat not in ("none", "daily", "weekly") or body.scope not in ("one", "series"):
        raise HTTPException(400, "无效重复设置")
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
            "WHERE kind='daily' AND type IN ('task','ddl') AND substr(date,1,4)=? GROUP BY date",
            (str(year),)).fetchall()
    days = {r["date"]: {"done": r["d"], "total": r["c"]} for r in rows}
    return {"year": year, "days": days}


@router.post("", status_code=201)
def create_entry(body: EntryIn, _user: dict = Depends(get_current)):
    _validate(body)
    dates = [body.date]
    series_id = ""
    if body.repeat != "none":
        if body.kind != "daily":
            raise HTTPException(400, "只有按日条目可以重复")
        try:
            first = datetime.strptime(body.date, "%Y-%m-%d")
            last = datetime.strptime(body.repeat_until, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "请选择有效重复结束日期")
        if last < first or (last - first).days > 730:
            raise HTTPException(400, "重复结束日期须在开始日期后两年内")
        step = 1 if body.repeat == "daily" else 7
        dates = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(0, (last-first).days+1, step)]
        series_id = uuid4().hex
    with db() as conn:
        first_id = None
        for date in dates:
            cur = conn.execute(
                "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at, priority, estimate_min, series_id) VALUES(?,?,?,?,?,?,0,0,?,?,?,?)",
                (date, body.kind, body.type, body.title.strip(), body.time_start.strip(), body.note.strip(), _now(), body.priority or "", body.estimate_min, series_id),
            )
            if first_id is None: first_id = cur.lastrowid
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (first_id,)).fetchone()
    return _row(row)

@router.put("/{entry_id}")
def update_entry(entry_id: int, body: EntryIn, _user: dict = Depends(get_current)):
    _validate(body)
    with db() as conn:
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        priority = row["priority"] if body.priority is None else body.priority
        estimate = row["estimate_min"] if "estimate_min" not in body.model_fields_set else body.estimate_min
        if body.scope == "series" and row["series_id"]:
            conn.execute("UPDATE schedule SET type=?, title=?, time_start=?, note=?, priority=?, estimate_min=? WHERE series_id=?",
                         (body.type, body.title.strip(), body.time_start.strip(), body.note.strip(), priority, estimate, row["series_id"]))
        else:
            conn.execute("UPDATE schedule SET date=?, kind=?, type=?, title=?, time_start=?, note=?, priority=?, estimate_min=? WHERE id=?",
                         (body.date, body.kind, body.type, body.title.strip(), body.time_start.strip(), body.note.strip(), priority, estimate, entry_id))
        try:
            if body.scope == "series" and row["series_id"]:
                conn.execute("UPDATE assistant_schedule_links SET locked_by_user=1 WHERE schedule_id IN (SELECT id FROM schedule WHERE series_id=?)", (row["series_id"],))
            else:
                conn.execute("UPDATE assistant_schedule_links SET locked_by_user=1 WHERE schedule_id=?", (entry_id,))
        except Exception:
            pass
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
    return _row(row)


@router.put("/{entry_id}/done")
def toggle_done(entry_id: int, body: DoneIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute("UPDATE schedule SET done=? WHERE id=?", (1 if body.done else 0, entry_id))
        try:
            conn.execute("UPDATE assistant_schedule_links SET locked_by_user=1 WHERE schedule_id=?", (entry_id,))
        except Exception:
            pass
        row = conn.execute("SELECT * FROM schedule WHERE id=?", (entry_id,)).fetchone()
    return _row(row)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, scope: str = "one", _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT series_id FROM schedule WHERE id=?", (entry_id,)).fetchone()
        if row is None: raise HTTPException(404, "条目不存在")
        ids = [r[0] for r in conn.execute("SELECT id FROM schedule WHERE series_id=?", (row["series_id"],)).fetchall()] if scope == "series" and row["series_id"] else [entry_id]
        try:
            for sid in ids:
                conn.execute("UPDATE assistant_schedule_links SET user_dismissed=1, schedule_id=NULL WHERE schedule_id=?", (sid,))
        except Exception:
            pass
        conn.execute("UPDATE focus SET schedule_id=NULL WHERE schedule_id IN (%s)" % ",".join("?" * len(ids)), ids)
        cur = conn.execute("DELETE FROM schedule WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    if cur.rowcount == 0:
        raise HTTPException(404, "条目不存在")
    return {"ok": True}

