"""投稿跟踪（M6）：会议/期刊投稿状态机 + 时间线事件。"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

STATUSES = ("draft", "submitted", "under_review", "major", "minor", "accepted", "rejected")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(r) -> dict:
    return {
        "id": r["id"], "title": r["title"], "venue": r["venue"], "status": r["status"],
        "deadline": r["deadline"], "submitted_at": r["submitted_at"], "notes": r["notes"],
        "events": json.loads(r["events_json"] or "[]"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


class SubmissionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    venue: str = Field(default="", max_length=120)
    status: str = Field(default="draft")
    deadline: str = Field(default="", max_length=20)
    submitted_at: str = Field(default="", max_length=20)
    notes: str = Field(default="", max_length=4000)
    events: list[dict] = Field(default_factory=list, max_length=100)


@router.get("")
def list_submissions(status: str = "", _user: dict = Depends(get_current)):
    sql = "SELECT * FROM submissions WHERE 1=1"
    args: list = []
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
        sql += " AND status=?"
        args.append(status)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("", status_code=201)
def create_submission(body: SubmissionIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO submissions(title, venue, status, deadline, submitted_at, notes, "
            "events_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (body.title.strip()[:200], body.venue.strip()[:120], body.status,
             body.deadline.strip()[:20], body.submitted_at.strip()[:20], body.notes.strip()[:4000],
             json.dumps(body.events[:100], ensure_ascii=False), now, now),
        )
        row = conn.execute("SELECT * FROM submissions WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.get("/{sub_id}")
def get_submission(sub_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "投稿不存在")
    return _row(row)


@router.put("/{sub_id}")
def update_submission(sub_id: int, body: SubmissionIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    with db() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "投稿不存在")
        conn.execute(
            "UPDATE submissions SET title=?, venue=?, status=?, deadline=?, submitted_at=?, "
            "notes=?, events_json=?, updated_at=? WHERE id=?",
            (body.title.strip()[:200], body.venue.strip()[:120], body.status,
             body.deadline.strip()[:20], body.submitted_at.strip()[:20], body.notes.strip()[:4000],
             json.dumps(body.events[:100], ensure_ascii=False), _now(), sub_id),
        )
        row = conn.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
    return _row(row)


@router.delete("/{sub_id}")
def delete_submission(sub_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM submissions WHERE id=?", (sub_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "投稿不存在")
    return {"ok": True}