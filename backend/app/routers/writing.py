"""写作资产库（M5）：BibTeX 条目 / 常用句式 / 图资产（路径引用，不复制产物）。"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/writing", tags=["writing"])


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- BibTeX ----------

class BibIn(BaseModel):
    bib_key: str = Field(min_length=1, max_length=80)
    entry_type: str = Field(default="misc", max_length=30)
    fields: dict = Field(default_factory=dict)
    paper_id: str = Field(default="", max_length=40)


def _bib_row(r) -> dict:
    return {
        "id": r["id"], "bib_key": r["bib_key"], "entry_type": r["entry_type"],
        "fields": json.loads(r["fields_json"] or "{}"), "paper_id": r["paper_id"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _bib_to_str(e: dict) -> str:
    fields = "\n".join(f'  {k} = {{{v}}},' for k, v in e["fields"].items())
    return f"@{e['entry_type']}{{{e['bib_key']},\n{fields}\n}}"


@router.get("/bib")
def list_bib(q: str = "", _user: dict = Depends(get_current)):
    with db() as conn:
        rows = conn.execute("SELECT * FROM bib_entries ORDER BY updated_at DESC").fetchall()
    items = [_bib_row(r) for r in rows]
    if q.strip():
        ql = q.strip().lower()
        items = [it for it in items if ql in it["bib_key"].lower()
                 or ql in str(it["fields"]).lower()]
    return {"items": items}


@router.post("/bib")
def add_bib(body: BibIn, _user: dict = Depends(get_current)):
    now = _now()
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO bib_entries(bib_key, entry_type, fields_json, paper_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (body.bib_key.strip()[:80], body.entry_type.strip()[:30],
                 json.dumps(body.fields, ensure_ascii=False), body.paper_id.strip()[:40], now, now),
            )
        except Exception:
            raise HTTPException(409, "bib key 已存在")
        row = conn.execute("SELECT * FROM bib_entries WHERE id=?", (cur.lastrowid,)).fetchone()
    return _bib_row(row)


@router.post("/bib/from-paper")
def bib_from_paper(paper_id: str, _user: dict = Depends(get_current)):
    """从论文库元数据自动生成 BibTeX（title/authors/year/venue/doi）。"""
    from ..routers import papers as papers_mod
    m = papers_mod._load_meta(paper_id)
    if m is None:
        raise HTTPException(404, "论文不存在")
    authors = m.get("authors") or ([a for a in [str(m.get("author", ""))] if a])
    if not authors and m.get("author"):
        authors = [m["author"]]
    fields = {}
    if authors:
        fields["author"] = " and ".join(authors)
    if m.get("title"):
        fields["title"] = m["title"]
    if m.get("year"):
        fields["year"] = str(m["year"])
    if m.get("venue"):
        fields["journal" if m.get("venue") else "journal"] = m.get("venue", "")
        fields["journal"] = m["venue"]
    if m.get("doi"):
        fields["doi"] = m["doi"]
    if not fields:
        raise HTTPException(400, "论文元数据为空，无法生成 BibTeX，请先补全元数据")
    key = "".join(c for c in (m.get("title") or "paper").lower().split()[0][:20] if c.isalnum()) \
        or f"paper{paper_id}"
    now = _now()
    with db() as conn:
        exists = conn.execute("SELECT id FROM bib_entries WHERE bib_key=?", (key,)).fetchone()
        if exists:
            raise HTTPException(409, f"bib key {key} 已存在")
        cur = conn.execute(
            "INSERT INTO bib_entries(bib_key, entry_type, fields_json, paper_id, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (key, "article", json.dumps(fields, ensure_ascii=False), paper_id, now, now),
        )
        row = conn.execute("SELECT * FROM bib_entries WHERE id=?", (cur.lastrowid,)).fetchone()
    return _bib_row(row)


@router.put("/bib/{bib_id}")
def update_bib(bib_id: int, body: BibIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM bib_entries WHERE id=?", (bib_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute(
            "UPDATE bib_entries SET bib_key=?, entry_type=?, fields_json=?, paper_id=?, updated_at=? "
            "WHERE id=?",
            (body.bib_key.strip()[:80], body.entry_type.strip()[:30],
             json.dumps(body.fields, ensure_ascii=False), body.paper_id.strip()[:40], _now(), bib_id),
        )
        row = conn.execute("SELECT * FROM bib_entries WHERE id=?", (bib_id,)).fetchone()
    return _bib_row(row)


@router.get("/bib/{bib_id}/export")
def export_bib(bib_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM bib_entries WHERE id=?", (bib_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
    return {"bibtex": _bib_to_str(_bib_row(row))}


@router.delete("/bib/{bib_id}")
def delete_bib(bib_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM bib_entries WHERE id=?", (bib_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "条目不存在")
    return {"ok": True}


# ---------- 句式库 ----------

class SnippetIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=8000)
    use_for: str = Field(default="other", max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=20)


def _snip_row(r) -> dict:
    return {
        "id": r["id"], "title": r["title"], "content": r["content"],
        "use_for": r["use_for"], "tags": json.loads(r["tags"] or "[]"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


@router.get("/snippets")
def list_snippets(use_for: str = "", _user: dict = Depends(get_current)):
    sql = "SELECT * FROM snippets WHERE 1=1"
    args: list = []
    if use_for:
        sql += " AND use_for=?"
        args.append(use_for)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at DESC", args).fetchall()
    return {"items": [_snip_row(r) for r in rows]}


@router.post("/snippets")
def add_snippet(body: SnippetIn, _user: dict = Depends(get_current)):
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO snippets(title, content, use_for, tags, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (body.title.strip()[:120], body.content.strip()[:8000], body.use_for.strip()[:30],
             json.dumps(body.tags[:20], ensure_ascii=False), now, now),
        )
        row = conn.execute("SELECT * FROM snippets WHERE id=?", (cur.lastrowid,)).fetchone()
    return _snip_row(row)


@router.put("/snippets/{snip_id}")
def update_snippet(snip_id: int, body: SnippetIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM snippets WHERE id=?", (snip_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "句式不存在")
        conn.execute(
            "UPDATE snippets SET title=?, content=?, use_for=?, tags=?, updated_at=? WHERE id=?",
            (body.title.strip()[:120], body.content.strip()[:8000], body.use_for.strip()[:30],
             json.dumps(body.tags[:20], ensure_ascii=False), _now(), snip_id),
        )
        row = conn.execute("SELECT * FROM snippets WHERE id=?", (snip_id,)).fetchone()
    return _snip_row(row)


@router.delete("/snippets/{snip_id}")
def delete_snippet(snip_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM snippets WHERE id=?", (snip_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "句式不存在")
    return {"ok": True}


# ---------- 图资产 ----------

class FigureIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    caption: str = Field(default="", max_length=1000)
    file_path: str = Field(default="", max_length=800)
    run_id: int = Field(default=0, ge=0)


def _fig_row(r) -> dict:
    return {
        "id": r["id"], "title": r["title"], "caption": r["caption"],
        "file_path": r["file_path"], "run_id": r["run_id"], "created_at": r["created_at"],
    }


@router.get("/figures")
def list_figures(_user: dict = Depends(get_current)):
    with db() as conn:
        rows = conn.execute("SELECT * FROM figures ORDER BY id DESC").fetchall()
    return {"items": [_fig_row(r) for r in rows]}


@router.post("/figures")
def add_figure(body: FigureIn, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO figures(title, caption, file_path, run_id, created_at) VALUES(?,?,?,?,?)",
            (body.title.strip()[:120], body.caption.strip()[:1000], body.file_path.strip()[:800],
             body.run_id, _now()),
        )
        row = conn.execute("SELECT * FROM figures WHERE id=?", (cur.lastrowid,)).fetchone()
    return _fig_row(row)


@router.put("/figures/{fig_id}")
def update_figure(fig_id: int, body: FigureIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM figures WHERE id=?", (fig_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "图不存在")
        conn.execute(
            "UPDATE figures SET title=?, caption=?, file_path=?, run_id=? WHERE id=?",
            (body.title.strip()[:120], body.caption.strip()[:1000], body.file_path.strip()[:800],
             body.run_id, fig_id),
        )
        row = conn.execute("SELECT * FROM figures WHERE id=?", (fig_id,)).fetchone()
    return _fig_row(row)


@router.delete("/figures/{fig_id}")
def delete_figure(fig_id: int, _user: dict = Depends(get_current)):
    """只删登记，不删源图文件。"""
    with db() as conn:
        cur = conn.execute("DELETE FROM figures WHERE id=?", (fig_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "图不存在")
    return {"ok": True}