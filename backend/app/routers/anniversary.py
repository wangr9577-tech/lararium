"""纪念日：如生日。存首次日期 YYYY-MM-DD，日历按"每年同月同日"重复标注。"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import lunar
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/anniversaries", tags=["anniversaries"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(r) -> dict:
    lm, ld = lunar.solar_to_lunar_md(r["date"])
    return {"id": r["id"], "name": r["name"], "date": r["date"],
            "lunar": f"{lm}-{ld}", "lunar_text": lunar.lunar_text(lm, ld),
            "note": r["note"], "created": r["created"]}


class AnniversaryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    date: str = Field(min_length=10, max_length=10)
    note: str = Field(default="", max_length=200)


def _validate(body: AnniversaryIn) -> None:
    if not DATE_RE.match(body.date):
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")


@router.get("/occ")
def occurrences(year: int, _user: dict = Depends(get_current)):
    """某公历年内所有纪念日的标注日：{date, name, kind: solar|lunar}"""
    with db() as conn:
        rows = conn.execute("SELECT * FROM anniversaries").fetchall()
    out = []
    for r in rows:
        name = r["name"]
        for occ in lunar.occurrences_in_year(r["date"], year):
            out.append({"date": occ["date"], "name": name,
                        "kind": occ["kind"], "note": r["note"]})
    out.sort(key=lambda x: x["date"])
    return {"year": year, "items": out}


@router.get("")
def list_anniversaries(_user: dict = Depends(get_current)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM anniversaries ORDER BY substr(date,6), substr(date,1,4), id").fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("", status_code=201)
def add_anniversary(body: AnniversaryIn, _user: dict = Depends(get_current)):
    _validate(body)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO anniversaries(name, date, note, created) VALUES(?,?,?,?)",
            (body.name.strip(), body.date, body.note.strip(), _now()),
        )
        row = conn.execute("SELECT * FROM anniversaries WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.put("/{ann_id}")
def update_anniversary(ann_id: int, body: AnniversaryIn, _user: dict = Depends(get_current)):
    _validate(body)
    with db() as conn:
        row = conn.execute("SELECT * FROM anniversaries WHERE id=?", (ann_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "纪念日不存在")
        conn.execute("UPDATE anniversaries SET name=?, date=?, note=? WHERE id=?",
                     (body.name.strip(), body.date, body.note.strip(), ann_id))
        row = conn.execute("SELECT * FROM anniversaries WHERE id=?", (ann_id,)).fetchone()
    return _row(row)


@router.delete("/{ann_id}")
def delete_anniversary(ann_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM anniversaries WHERE id=?", (ann_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "纪念日不存在")
    return {"ok": True}
