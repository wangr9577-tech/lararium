"""生词本：论文阅读划词收集 + 简单间隔复习（Leitner 盒子 0-5）。

box 0=新/忘词(今天再练)，答对升级到 box+1，间隔按 [0,1,3,7,15,30] 天；
box=5 视为"已掌握"。next_due 存 YYYY-MM-DD（box0/空 = 立即可复习）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

BOX_DAYS = [0, 1, 3, 7, 15, 30]
MASTER_BOX = 5


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _row(r) -> dict:
    return {"id": r["id"], "word": r["word"], "meaning": r["meaning"], "sentence": r["sentence"],
            "source": r["source"], "added": r["added"],
            "box": r["box"], "reviews": r["reviews"], "next_due": r["next_due"]}


class VocabIn(BaseModel):
    word: str = Field(min_length=1, max_length=120)
    meaning: str = Field(default="", max_length=1000)
    sentence: str = Field(default="", max_length=1000)
    source: str = Field(default="", max_length=80)


class ReviewIn(BaseModel):
    correct: bool


@router.get("")
def list_vocab(q: str | None = None, _user: dict = Depends(get_current)):
    if q and q.strip():
        like = f"%{q.strip()}%"
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM vocab WHERE word LIKE ? OR meaning LIKE ? ORDER BY id DESC",
                (like, like)).fetchall()
    else:
        with db() as conn:
            rows = conn.execute("SELECT * FROM vocab ORDER BY id DESC").fetchall()
    return {"items": [_row(r) for r in rows]}


@router.get("/stats")
def vocab_stats(_user: dict = Depends(get_current)):
    today = _today()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM vocab").fetchone()["c"]
        due = conn.execute(
            "SELECT COUNT(*) c FROM vocab WHERE box=0 OR next_due='' OR next_due<=?", (today,)).fetchone()["c"]
        mastered = conn.execute("SELECT COUNT(*) c FROM vocab WHERE box>=?", (MASTER_BOX,)).fetchone()["c"]
        fresh = conn.execute("SELECT COUNT(*) c FROM vocab WHERE reviews=0").fetchone()["c"]
    return {"total": total, "due": due, "mastered": mastered, "fresh": fresh}


@router.get("/review")
def review_pack(limit: int = 15, _user: dict = Depends(get_current)):
    limit = max(1, min(limit, 60))
    today = _today()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM vocab WHERE box=0 OR next_due='' OR next_due<=? ORDER BY RANDOM() LIMIT ?",
            (today, limit)).fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("", status_code=201)
def add_vocab(body: VocabIn, _user: dict = Depends(get_current)):
    word = body.word.strip()
    if not word:
        raise HTTPException(400, "单词不能为空")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO vocab(word, meaning, sentence, source, added) VALUES(?,?,?,?,?)",
            (word[:120], body.meaning.strip()[:1000], body.sentence.strip()[:1000],
             body.source.strip()[:80], _now()),
        )
        row = conn.execute("SELECT * FROM vocab WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.put("/{vocab_id}")
def update_vocab(vocab_id: int, body: VocabIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "词条不存在")
        conn.execute(
            "UPDATE vocab SET word=?, meaning=?, sentence=?, source=? WHERE id=?",
            (body.word.strip()[:120], body.meaning.strip()[:1000], body.sentence.strip()[:1000],
             body.source.strip()[:80], vocab_id),
        )
        row = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
    return _row(row)


@router.post("/{vocab_id}/review")
def review_vocab(vocab_id: int, body: ReviewIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "词条不存在")
        box = row["box"]
        if body.correct:
            box = min(box + 1, MASTER_BOX)
        else:
            box = 0
        days = BOX_DAYS[min(box, len(BOX_DAYS) - 1)]
        next_due = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d") if box > 0 else _today()
        conn.execute(
            "UPDATE vocab SET box=?, reviews=reviews+1, next_due=? WHERE id=?",
            (box, next_due, vocab_id),
        )
        row = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
    return _row(row)


@router.delete("/{vocab_id}")
def delete_vocab(vocab_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM vocab WHERE id=?", (vocab_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "词条不存在")
    return {"ok": True}
