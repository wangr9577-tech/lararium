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
from ..services import llm, paper_translate
from ..upload import read_upload
from .settings import _load as _load_settings

router = APIRouter(prefix="/api/papers", tags=["papers"])

PAPERS_DIR = config.DATA_DIR / "papers"
STATUSES = ("想读", "在读", "精读", "读完", "搁置")
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
        pid = p.stem
        out.append({**m, "id": pid, "trans_state": paper_translate.state_of(pid)})
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
    # ---- 科研工作台新增元数据 ----
    doi: str = Field(default="", max_length=120)
    arxiv_id: str = Field(default="", max_length=40)
    year: str = Field(default="", max_length=20)
    venue: str = Field(default="", max_length=120)
    authors: list[str] = Field(default_factory=list, max_length=50)
    abstract: str = Field(default="", max_length=8000)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    related_ids: list[str] = Field(default_factory=list, max_length=50)


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
    auto_translate: str = Form(default="1"),
    _user: dict = Depends(get_current),
):
    if len(files) > 30:
        raise HTTPException(400, "一次最多上传 30 篇")
    tags_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()][:10]
    want_translate = str(auto_translate).lower() not in ("0", "false", "no", "off", "")
    created = []
    for f in files:
        raw = await read_upload(f, MAX_UPLOAD, too_big=f"{f.filename} 超过 {MAX_UPLOAD // (1 << 20)}MB 上限")
        if not raw.startswith(b"%PDF"):
            raise HTTPException(400, f"{f.filename} 不是 PDF 文件")
        id_ = uuid.uuid4().hex[:12]
        # 单个文件且手动填了标题时用标题，否则用文件名
        name = (title if (title and len(files) == 1) else (f.filename or "未命名论文")).replace(".pdf", "").strip()[:200]
        now = _now()
        vault.write_bytes(_pdf_path(id_), raw)
        meta = {
            "title": name, "author": "", "status": "想读", "tags": tags_list,
            "note": "", "page_count": 0, "category": category.strip()[:30],
            "subcategory": subcategory.strip()[:30], "link": "", "added": now, "updated": now,
            "doi": "", "arxiv_id": "", "year": "", "venue": "",
            "authors": [], "abstract": "", "keywords": [], "related_ids": [],
        }
        vault.write_json(_meta_path(id_), meta)
        vault.write_json(_hl_path(id_), {"items": []})
        created.append({"id": id_, **meta})
    # 上传即排队翻译：不用等到打开论文时才开始（慢慢排在后台，打开时通常已就绪）。
    # 翻译失败绝不影响上传结果，逐个隔离异常。
    if want_translate:
        for item in created:
            try:
                paper_translate.start(item["id"])
            except Exception:
                pass
    return {"items": [{**c, "trans_state": paper_translate.state_of(c["id"])} for c in created]}


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


# ---------------------------------------------------------------- 中文翻译

class TranslateIn(BaseModel):
    force: bool = False


@router.get("/{paper_id}/translation")
def get_translation(paper_id: str, _user: dict = Depends(get_current)):
    """译文状态：none / queued / running / ready / failed（含页数进度与失败原因）。"""
    if not _meta_path(paper_id).is_file():
        raise HTTPException(404, "论文不存在")
    st = paper_translate.read_status(paper_id)
    st["ai_enabled"] = llm.is_enabled()
    st["queue_depth"] = paper_translate.queued_count()
    return st


@router.post("/{paper_id}/translation", status_code=202)
def start_translation(paper_id: str, body: TranslateIn | None = None,
                      _user: dict = Depends(get_current)):
    """按需翻译（后台线程）：已有译文且未 force 时直接返回 ready。"""
    if not _meta_path(paper_id).is_file():
        raise HTTPException(404, "论文不存在")
    if not _pdf_path(paper_id).is_file():
        raise HTTPException(404, "这篇论文还没有 PDF 原文")
    if not llm.is_enabled():
        raise HTTPException(503, "AI 服务未启用：请先在「设置」里配置并打开模型")
    try:
        return paper_translate.start(paper_id, force=bool(body and body.force))
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/{paper_id}/translation/cancel")
def cancel_translation(paper_id: str, _user: dict = Depends(get_current)):
    """请求停止翻译（当前页译完即停，不落半成品译文）。"""
    if not _meta_path(paper_id).is_file():
        raise HTTPException(404, "论文不存在")
    paper_translate.cancel(paper_id)
    return {**paper_translate.read_status(paper_id), "cancelling": True}


@router.get("/{paper_id}/translation/file")
def translation_file(paper_id: str, _user: dict = Depends(get_current)):
    data = paper_translate.read_pdf(paper_id)
    if data is None:
        raise HTTPException(404, "还没有中文译文")
    return Response(content=data, media_type="application/pdf")


@router.delete("/{paper_id}/translation")
def delete_translation(paper_id: str, _user: dict = Depends(get_current)):
    paper_translate.remove(paper_id)
    return {"ok": True}


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
        raise HTTPException(400, "status 只能是 想读 / 在读 / 精读 / 读完 / 搁置")
    meta = {
        "title": body.title.strip(), "author": body.author.strip(), "status": body.status,
        "tags": [t[:30] for t in body.tags][:10], "note": body.note.strip(),
        "page_count": max(0, body.page_count), "category": body.category.strip()[:30],
        "link": body.link.strip()[:300],
        "added": m.get("added", _now()), "updated": _now(),
        "doi": body.doi.strip()[:120], "arxiv_id": body.arxiv_id.strip()[:40],
        "year": body.year.strip()[:20], "venue": body.venue.strip()[:120],
        "authors": [a[:120] for a in body.authors][:50], "abstract": body.abstract.strip()[:8000],
        "keywords": [k[:30] for k in body.keywords][:30],
        "related_ids": [r[:40] for r in body.related_ids][:50],
        "subcategory": body.subcategory.strip()[:30],
    }
    vault.write_json(_meta_path(paper_id), meta)
    return {"id": paper_id, **meta}


class ImportMetaIn(BaseModel):
    source: str = Field(pattern="^(arxiv|doi)$")
    id: str = Field(min_length=1, max_length=200)


@router.post("/import-meta")
def import_meta(body: ImportMetaIn, _user: dict = Depends(get_current)):
    """按 arXiv id 或 DOI 拉取元数据（arXiv API / doi.org），返回可直接写入的字段。"""
    import urllib.parse
    import urllib.request

    meta: dict = {}
    try:
        if body.source == "arxiv":
            url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(body.id.strip())}"
            with urllib.request.urlopen(url, timeout=15) as resp:
                xml = resp.read().decode("utf-8")
            import re
            def _pick(tag: str) -> str:
                m = re.search(fr"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
                return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
            title = _pick("title").replace("\n ", "")
            summary = _pick("summary")
            authors = re.findall(r"<name>(.*?)</name>", xml)
            meta = {
                "title": title[:200], "abstract": summary[:8000],
                "authors": [a.strip()[:120] for a in authors][:50],
                "arxiv_id": body.id.strip()[:40], "year": (re.search(r"20\d{2}", xml) or [None, ""])[0] if re.search(r"20\d{2}", xml) else "",
            }
            if not title:
                raise HTTPException(404, "arXiv 未找到该论文")
        else:  # doi
            url = f"https://api.crossref.org/works/{urllib.parse.quote(body.id.strip())}"
            with urllib.request.urlopen(url, timeout=15) as resp:
                import json
                data = json.loads(resp.read().decode("utf-8"))["message"]
            auths = [a.get("given", "") + " " + a.get("family", "") for a in data.get("author", [])]
            meta = {
                "title": (data.get("title") or [""])[0][:200],
                "doi": body.id.strip()[:120],
                "year": str(data.get("issued", {}).get("date-parts", [[""]])[0][0])[:20],
                "venue": (data.get("container-title") or [""])[0][:120],
                "authors": [a.strip()[:120] for a in auths][:50],
                "abstract": (re.sub(r"<[^>]+>", "", data.get("abstract", "")) if data.get("abstract") else "")[:8000],
            }
            if not meta["title"]:
                raise HTTPException(404, "DOI 未找到该文献")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"拉取元数据失败（服务器网络）：{e}")
    return {"source": body.source, "meta": meta}


class RelatedIn(BaseModel):
    related_id: str = Field(min_length=1, max_length=40)


@router.post("/{paper_id}/related")
def add_related(paper_id: str, body: RelatedIn, _user: dict = Depends(get_current)):
    """建立论文间双向关联（related_ids）。"""
    m = _load_meta(paper_id)
    other = _load_meta(body.related_id)
    if m is None or other is None:
        raise HTTPException(404, "论文不存在")
    cur = [r for r in m.get("related_ids", []) if r != body.related_id]
    new = cur + [body.related_id]
    m["related_ids"] = new[:50]
    m["updated"] = _now()
    vault.write_json(_meta_path(paper_id), m)
    # 反向
    o = [r for r in other.get("related_ids", []) if r != paper_id]
    other["related_ids"] = (o + [paper_id])[:50]
    other["updated"] = _now()
    vault.write_json(_meta_path(body.related_id), other)
    return {"ok": True, "related_ids": new}


@router.delete("/{paper_id}")
def delete_paper(paper_id: str, _user: dict = Depends(get_current)):
    victims = [p for p in (_pdf_path(paper_id), _meta_path(paper_id), _hl_path(paper_id)) if p.is_file()]
    if not victims:
        raise HTTPException(404, "论文不存在")
    tmeta, tpdf = paper_translate.paths(paper_id)
    victims += [p for p in (tmeta, tpdf) if p.is_file()]
    m = _load_meta(paper_id) or {}
    tid = trashbin.move_to_trash(victims, module="paper", label=m.get("title") or "论文")
    paper_translate.remove(paper_id)
    return {"ok": True, "trash_id": tid}
