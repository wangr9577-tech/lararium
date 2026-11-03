"""研究想法 Backlog（M3）：问题/假设/研究方向，状态机 + 优先级 + 与论文/卡片/实验双链。

正文：data/ideas/<idea_id>.md（vault 加密），元数据在 SQLite ideas + idea_links。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/ideas", tags=["ideas"])

IDEAS_DIR = config.DATA_DIR / "ideas"
STATUSES = ("backlog", "active", "done", "dropped")
PRIORITIES = ("high", "medium", "low")
MAX_LEN = 100_000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(idea_id: int) -> Path:
    return IDEAS_DIR / f"{idea_id}.md"


def _row(r, with_content: bool = True) -> dict:
    out = {
        "id": r["id"], "title": r["title"], "summary": r["summary"],
        "status": r["status"], "priority": r["priority"], "tags": json.loads(r["tags"] or "[]"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }
    if with_content:
        try:
            out["content"] = vault.read_text(_path(r["id"]))
        except Exception:
            out["content"] = ""
    return out


def _links_of(idea_id: int, conn) -> list[dict]:
    rows = conn.execute(
        "SELECT target_type, target_id FROM idea_links WHERE idea_id=? ORDER BY id", (idea_id,)
    ).fetchall()
    return [{"target_type": r["target_type"], "target_id": r["target_id"]} for r in rows]


class IdeaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=MAX_LEN)
    status: str = Field(default="backlog")
    priority: str = Field(default="medium")
    tags: list[str] = Field(default_factory=list, max_length=20)


class IdeaLinkIn(BaseModel):
    target_type: str = Field(pattern="^(paper|card|experiment)$")
    target_id: str = Field(min_length=1, max_length=40)


@router.get("")
def list_ideas(status: str = "", _user: dict = Depends(get_current)):
    sql = "SELECT * FROM ideas WHERE 1=1"
    args: list = []
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
        sql += " AND status=?"
        args.append(status)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()
    return {"items": [_row(r, with_content=False) for r in rows]}


@router.post("", status_code=201)
def create_idea(body: IdeaIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    if body.priority not in PRIORITIES:
        raise HTTPException(400, f"priority 只能是 {list(PRIORITIES)}")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ideas(title, summary, status, priority, tags, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (title[:200], body.summary.strip()[:500], body.status, body.priority,
             json.dumps(body.tags[:20], ensure_ascii=False), now, now),
        )
        idea_id = cur.lastrowid
    vault.write_text(_path(idea_id), body.content)
    with db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return _row(row)


@router.get("/{idea_id}")
def get_idea(idea_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "想法不存在")
        links = _links_of(idea_id, conn)
    out = _row(row)
    out["links"] = links
    return out


@router.put("/{idea_id}")
def update_idea(idea_id: int, body: IdeaIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    if body.priority not in PRIORITIES:
        raise HTTPException(400, f"priority 只能是 {list(PRIORITIES)}")
    with db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "想法不存在")
        conn.execute(
            "UPDATE ideas SET title=?, summary=?, status=?, priority=?, tags=?, updated_at=? "
            "WHERE id=?",
            (body.title.strip()[:200], body.summary.strip()[:500], body.status, body.priority,
             json.dumps(body.tags[:20], ensure_ascii=False), _now(), idea_id),
        )
    vault.write_text(_path(idea_id), body.content)
    with db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return _row(row)


@router.delete("/{idea_id}")
def delete_idea(idea_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
        conn.execute("DELETE FROM idea_links WHERE idea_id=?", (idea_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "想法不存在")
    try:
        p = config.DATA_DIR / "ideas" / f"{idea_id}.md"
        if p.is_file():
            p.unlink()
    except OSError:
        pass
    return {"ok": True}


@router.post("/{idea_id}/links", status_code=201)
def add_idea_link(idea_id: int, body: IdeaLinkIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "想法不存在")
        try:
            conn.execute(
                "INSERT INTO idea_links(idea_id, target_type, target_id) VALUES(?,?,?)",
                (idea_id, body.target_type, body.target_id.strip()[:40]),
            )
        except Exception:
            raise HTTPException(400, "该关联已存在")
    return {"ok": True}


@router.delete("/{idea_id}/links")
def remove_idea_link(idea_id: int, target_type: str, target_id: str, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM idea_links WHERE idea_id=? AND target_type=? AND target_id=?",
            (idea_id, target_type, target_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "关联不存在")
    return {"ok": True}