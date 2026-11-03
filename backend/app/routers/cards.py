"""卡片笔记（M2）：原子化知识 = 标题 + 正文 md（vault 加密）+ 标签 + 双链。

正文：data/cards/<card_id>.md（加密），标题/标签/来源/关联在 SQLite。
双链：card_links（card→card / card→paper），双向展示。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/cards", tags=["cards"])

CARDS_DIR = config.DATA_DIR / "cards"
MAX_LEN = 200_000  # 卡片正文上限


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(card_id: int) -> Path:
    return CARDS_DIR / f"{card_id}.md"


def _row(r, with_content: bool = True) -> dict:
    out = {
        "id": r["id"], "title": r["title"], "tags": json.loads(r["tags"] or "[]"),
        "paper_id": r["paper_id"], "ref_type": r["ref_type"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }
    if with_content:
        try:
            out["content"] = vault.read_text(_path(r["id"]))
        except Exception:
            out["content"] = ""
    return out


def _links_of(card_id: int, conn) -> list[dict]:
    rows = conn.execute(
        "SELECT target_type, target_id FROM card_links WHERE card_id=? ORDER BY id", (card_id,)
    ).fetchall()
    return [{"target_type": r["target_type"], "target_id": r["target_id"]} for r in rows]


class CardIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=MAX_LEN)
    tags: list[str] = Field(default_factory=list, max_length=20)
    paper_id: str = Field(default="", max_length=40)
    ref_type: str = Field(default="manual", max_length=20)  # highlight | idea | manual


class LinkIn(BaseModel):
    target_type: str = Field(pattern="^(card|paper)$")
    target_id: str = Field(min_length=1, max_length=40)


@router.get("")
def list_cards(tag: str = "", q: str = "", paper_id: str = "", _user: dict = Depends(get_current)):
    sql = "SELECT * FROM cards WHERE 1=1"
    args: list = []
    if tag:
        sql += " AND tags LIKE ?"
        args.append(f'%"{tag}"%')
    if paper_id:
        sql += " AND paper_id=?"
        args.append(paper_id)
    if q.strip():
        like = f"%{q.strip()}%"
        sql += " AND (title LIKE ? OR id IN (SELECT id FROM cards WHERE 1=0))"
        args.append(like)
        # 全文搜索正文：标题命中优先；正文遍历加密文件（个人规模可接受）
        all_rows = []
        with db() as conn:
            rows = conn.execute(sql, args).fetchall()
        for r in rows:
            try:
                content = vault.read_text(_path(r["id"]))
            except Exception:
                content = ""
            if like.strip("%") in r["title"] or like.strip("%") in content:
                all_rows.append(_row(r, with_content=False))
        return {"items": all_rows, "total": len(all_rows)}
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at DESC", args).fetchall()
    return {"items": [_row(r, with_content=False) for r in rows], "total": len(rows)}


@router.post("", status_code=201)
def create_card(body: CardIn, _user: dict = Depends(get_current)):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO cards(title, tags, paper_id, ref_type, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (title[:200], json.dumps(body.tags[:20], ensure_ascii=False),
             body.paper_id.strip()[:40], body.ref_type[:20], now, now),
        )
        card_id = cur.lastrowid
    vault.write_text(_path(card_id), body.content)
    with db() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    return _row(row)


@router.get("/{card_id}")
def get_card(card_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "卡片不存在")
        links = _links_of(card_id, conn)
        backlinks = conn.execute(
            "SELECT c.id, c.title FROM card_links L JOIN cards c ON c.id=L.card_id "
            "WHERE L.target_type='card' AND L.target_id=? ORDER BY c.id", (str(card_id),)
        ).fetchall()
    out = _row(row)
    out["links"] = links
    out["backlinks"] = [{"id": c["id"], "title": c["title"]} for c in backlinks]
    return out


@router.put("/{card_id}")
def update_card(card_id: int, body: CardIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "卡片不存在")
        conn.execute(
            "UPDATE cards SET title=?, tags=?, paper_id=?, ref_type=?, updated_at=? WHERE id=?",
            (body.title.strip()[:200], json.dumps(body.tags[:20], ensure_ascii=False),
             body.paper_id.strip()[:40], body.ref_type[:20], _now(), card_id),
        )
    vault.write_text(_path(card_id), body.content)
    with db() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    return _row(row)


@router.delete("/{card_id}")
def delete_card(card_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        conn.execute("DELETE FROM card_links WHERE card_id=? OR (target_type='card' AND target_id=?)",
                     (card_id, str(card_id)))
    if cur.rowcount == 0:
        raise HTTPException(404, "卡片不存在")
    try:
        p = config.DATA_DIR / "cards" / f"{card_id}.md"
        if p.is_file():
            p.unlink()
    except OSError:
        pass
    return {"ok": True}


@router.post("/{card_id}/links", status_code=201)
def add_link(card_id: int, body: LinkIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "卡片不存在")
        try:
            conn.execute(
                "INSERT INTO card_links(card_id, target_type, target_id) VALUES(?,?,?)",
                (card_id, body.target_type, body.target_id.strip()[:40]),
            )
        except Exception:
            raise HTTPException(400, "该链接已存在")
    return {"ok": True}


@router.delete("/{card_id}/links")
def remove_link(card_id: int, target_type: str, target_id: str, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM card_links WHERE card_id=? AND target_type=? AND target_id=?",
            (card_id, target_type, target_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "链接不存在")
    return {"ok": True}