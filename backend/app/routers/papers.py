"""论文库：PDF 原文件与元数据/高亮 JSON 均加密落盘（data/papers/）。

文件：
  papers/<id>.pdf      原始 PDF（AES-GCM）
  papers/<id>.json     元数据（加密 JSON）
  papers/<id>.hl.json  高亮标注数组（加密 JSON）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current
from ..db import db
from .settings import _load as _load_settings

router = APIRouter(prefix="/api/papers", tags=["papers"])

PAPERS_DIR = config.DATA_DIR / "papers"
STATUSES = ("想读", "在读", "读完")
MAX_UPLOAD = 50 * 1024 * 1024  # 50MB


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _meta_path(id_: str):
    return PAPERS_DIR / f"{id_}.json"


def _hl_path(id_: str):
    return PAPERS_DIR / f"{id_}.hl.json"


def _pdf_path(id_: str):
    return PAPERS_DIR / f"{id_}.pdf"


def _load_meta(id_: str) -> dict | None:
    p = _meta_path(id_)
    if not p.is_file():
        return None
    m = vault.read_json(p)
    return {**m, "id": id_}


def _list_all() -> list[dict]:
    out = []
    for p in sorted(PAPERS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".hl.json"):
            continue
        try:
            m = vault.read_json(p)
        except Exception:
            continue
        out.append({**m, "id": p.stem})
    return out


class MetaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=200)
    status: str = "想读"
    tags: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=600)
    page_count: int = Field(default=0, ge=0)
    category: str = Field(default="", max_length=30)
    subcategory: str = Field(default="", max_length=30)
    link: str = Field(default="", max_length=300)


class Highlight(BaseModel):
    id: str
    page: int = Field(ge=1)
    rects: list[dict] = Field(default_factory=list)
    text: str = ""
    color: str = "#fde047"
    note: str = ""
    created: str = ""


class HighlightsIn(BaseModel):
    items: list[Highlight]


@router.get("")
def list_papers(_user: dict = Depends(get_current)):
    return {"items": _list_all()}


@router.post("", status_code=201)
async def upload_paper(
    files: list[UploadFile] = File(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    category: str = Form(default=""),
    subcategory: str = Form(default=""),
    _user: dict = Depends(get_current),
):
    if len(files) > 30:
        raise HTTPException(400, "一次最多上传 30 篇")
    tags_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()][:10]
    created = []
    for f in files:
        raw = await f.read()
        if not raw.startswith(b"%PDF"):
            raise HTTPException(400, f"{f.filename} 不是 PDF 文件")
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(400, f"{f.filename} 超过 20MB")
        id_ = uuid.uuid4().hex[:12]
        # 单个文件且手动填了标题时用标题，否则用文件名
        name = (title if (title and len(files) == 1) else (f.filename or "未命名论文")).replace(".pdf", "").strip()[:200]
        now = _now()
        vault.write_bytes(_pdf_path(id_), raw)
        meta = {
            "title": name, "author": "", "status": "想读", "tags": tags_list,
            "note": "", "page_count": 0, "category": category.strip()[:30],
            "subcategory": subcategory.strip()[:30], "link": "", "added": now, "updated": now,
        }
        vault.write_json(_meta_path(id_), meta)
        vault.write_json(_hl_path(id_), {"items": []})
        created.append({"id": id_, **meta})
    return {"items": created}


@router.get("/categories")
def list_categories(_user: dict = Depends(get_current)):
    """分类清单 + 二级子分组：设置里的清单 ∪ 实际被论文使用的分类。"""
    cfg = _load_settings()
    listed = [c for c in (cfg.get("paper.categories") or []) if isinstance(c, str) and c.strip()]
    sub_listed = cfg.get("paper.subcategories") or []
    if isinstance(sub_listed, dict):
        sub_listed = [{"category": k, "name": v} for k, vs in sub_listed.items() for v in (vs if isinstance(vs, list) else [])]
    sub_map: dict[str, list[str]] = {}
    for s in sub_listed:
        if isinstance(s, dict) and s.get("category") and s.get("name"):
            sub_map.setdefault(s["category"], [])
            if s["name"] not in sub_map[s["category"]]:
                sub_map[s["category"]].append(s["name"])
    used = [m.get("category", "").strip() for m in _list_all() if m.get("category")]
    seen = set()
    cats = []
    for c in listed + used:
        if c and c not in seen:
            seen.add(c); cats.append(c)
    for m in _list_all():
        c = (m.get("category") or "").strip()
        sc = (m.get("subcategory") or "").strip()
        if c and sc:
            sub_map.setdefault(c, [])
            if sc not in sub_map[c]:
                sub_map[c].append(sc)
    subcats = {c: sub_map.get(c, []) for c in cats}
    return {"categories": cats, "subcategories": subcats}

@router.get("/{paper_id}")
def get_paper(paper_id: str, _user: dict = Depends(get_current)):
    m = _load_meta(paper_id)
    if m is None:
        raise HTTPException(404, "论文不存在")
    return m


@router.get("/{paper_id}/file")
def paper_file(paper_id: str, _user: dict = Depends(get_current)):
    p = _pdf_path(paper_id)
    if not p.is_file():
        raise HTTPException(404, "论文不存在")
    data = vault.read_bytes(p)
    return Response(content=data, media_type="application/pdf")


@router.get("/{paper_id}/highlights")
def get_highlights(paper_id: str, _user: dict = Depends(get_current)):
    if not _meta_path(paper_id).is_file():
        raise HTTPException(404, "论文不存在")
    p = _hl_path(paper_id)
    if not p.is_file():
        return {"items": []}
    return vault.read_json(p)


@router.put("/{paper_id}/highlights")
def put_highlights(paper_id: str, body: HighlightsIn, _user: dict = Depends(get_current)):
    if not _meta_path(paper_id).is_file():
        raise HTTPException(404, "论文不存在")
    items = [h.model_dump() for h in body.items]
    payload = {"items": items}
    vault.write_json(_hl_path(paper_id), payload)
    return payload


@router.put("/{paper_id}/meta")
def put_meta(paper_id: str, body: MetaIn, _user: dict = Depends(get_current)):
    m = _load_meta(paper_id)
    if m is None:
        raise HTTPException(404, "论文不存在")
    if body.status not in STATUSES:
        raise HTTPException(400, "status 只能是 想读 / 在读 / 读完")
    meta = {
        "title": body.title.strip(), "author": body.author.strip(), "status": body.status,
        "tags": [t[:30] for t in body.tags][:10], "note": body.note.strip(),
        "page_count": max(0, body.page_count), "category": body.category.strip()[:30],
        "link": body.link.strip()[:300],
        "added": m.get("added", _now()), "updated": _now(),
    }
    vault.write_json(_meta_path(paper_id), meta)
    return {"id": paper_id, **meta}



@router.delete("/{paper_id}")
def delete_paper(paper_id: str, _user: dict = Depends(get_current)):
    victims = [p for p in (_pdf_path(paper_id), _meta_path(paper_id), _hl_path(paper_id)) if p.is_file()]
    if not victims:
        raise HTTPException(404, "论文不存在")
    m = _load_meta(paper_id) or {}
    tid = trashbin.move_to_trash(victims, module="paper", label=m.get("title") or "论文")
    return {"ok": True, "trash_id": tid}
