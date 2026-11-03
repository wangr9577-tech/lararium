"""工作台：事项树 + 当前思路 + 小记 + 随手收集箱 + 相关资料链接。

内容模型（与 docs/WORKBENCH_REDESIGN_SPEC.md 一致）：
  事项            workbench_items 行 + data/workbench/items/<id>/thinking.md（当前思路正文）
  小记            workbench_entries 行 + data/workbench/items/<id>/entries/<eid>.md
  收集片段        workbench_captures 行 + data/workbench/captures/<cid>.md
  相关资料        workbench_links 行（只存指向论文/博客笔记的入口，不复制正文）

存储约定：
  - 所有正文（当前思路/小记/收集片段）一律经 vault 加密落盘，SQLite 只放索引与
    低敏元数据：items.summary 是当前思路的短摘要（列表页要直接显示，不读正文即可渲染，
    与笔记列表读 frontmatter 元数据同级）；小记与收集片段的文字永远不落库。
  - 事项不强制日期/优先级/任务状态，只有标题、父事项、排序、归档。

前端约定：
  - 列表接口只返回摘要；展开某个事项后再拉完整正文与小记（避免首页同时解密所有长文）。
  - 首页一次只展开一个事项（记住上次展开项），这是前端行为，后端不限。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

WB_DIR = config.DATA_DIR / "workbench"
ITEMS_DIR = WB_DIR / "items"
CAPTURES_DIR = WB_DIR / "captures"
NOTES_DIR = config.DATA_DIR / "notes"
PAPERS_DIR = config.DATA_DIR / "papers"

MAX_TITLE = 200
MAX_THINKING = 200_000     # 当前思路正文上限（约 20 万字符）
MAX_ENTRY = 20_000         # 单条小记上限
MAX_CAPTURE = 50_000       # 单条收集片段上限
MAX_SOURCE = 100
MAX_URL = 1000
MAX_CONTENT_TAG = 60       # 事务性字段（kind 等）的宽松上限

TARGET_TYPES = ("note", "paper", "doc", "project_doc", "assistant_record")

UNNAMED = "未命名"          # 标题留空时的事项名（首次写入思路会自动改成正文第一行）


# ---------- 基础工具 ----------

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _int_id(raw: object, what: str = "ID") -> int:
    try:
        v = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what}不合法")
    if v <= 0:
        raise HTTPException(400, f"{what}不合法")
    return v


def _text(raw: object, limit: int, what: str) -> str:
    s = str(raw or "").strip()
    if len(s) > limit:
        raise HTTPException(400, f"{what}最长 {limit} 字")
    return s


def _require_dek() -> None:
    """写正文前必须先解锁：锁定态返回 423，前端拦截后引导重新登录（与笔记一致）。"""
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重新登录后重试")


def summarize(body: str, n: int = 80) -> str:
    """当前思路正文 → 一行短摘要（去 Markdown 记号，供首页收起态显示）。"""
    s = re.sub(r"```.*?```", " ", body or "", flags=re.S)
    s = re.sub(r"[#>*`_~\-\[\]()]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def first_line(body: str, n: int = 40) -> str:
    """正文的第一行有内容的文字 → 用作「未命名」事项的自动标题。

    支持"先写后命名"：用户先在输入框里写，标题留空建出来的事项叫「未命名」，
    首次写入思路时把第一行提上来当标题，用户之后仍可随时改名。
    """
    for raw in (body or "").splitlines():
        s = re.sub(r"^[#>*`\-+\s]+", "", raw).strip()
        if s:
            return s[:n]
    return ""


# ---------- 文件布局 ----------

def _item_dir(item_id: int) -> Path:
    return ITEMS_DIR / str(item_id)


def _thinking_path(item_id: int) -> Path:
    return _item_dir(item_id) / "thinking.md"


def _entry_path(item_id: int, entry_id: int) -> Path:
    return _item_dir(item_id) / "entries" / f"{entry_id}.md"


def _capture_path(capture_id: int) -> Path:
    return CAPTURES_DIR / f"{capture_id}.md"


def _write_content(path: Path, text: str) -> None:
    _require_dek()
    path.parent.mkdir(parents=True, exist_ok=True)
    vault.write_text(path, text)


def _read_content(path: Path) -> str:
    """读正文；文件不存在返回 ''（索引行在而文件缺失时不炸整个列表）。"""
    if not path.is_file():
        return ""
    return vault.read_text(path)


def _touch_item(conn, item_id: int) -> None:
    conn.execute("UPDATE workbench_items SET updated_at=? WHERE id=?", (now_iso(), item_id))


def _item_row(conn, item_id: int):
    return conn.execute("SELECT * FROM workbench_items WHERE id=?", (item_id,)).fetchone()


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ---------- 资料存在性（论文 / 博客笔记，只读，不修改任何资料） ----------

_NOTE_TYPES = ("blog", "note", "project")


def _note_meta(note_id: str) -> dict | None:
    """读一篇博客笔记的 frontmatter 元数据（不解密正文）；不存在返回 None。"""
    p = NOTES_DIR / f"{note_id}.md"
    if not p.is_file():
        return None
    try:
        raw = vault.read_text(p)
    except Exception:
        return None
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    title = meta.get("title")
    if not title:
        return None
    return {
        "id": note_id,
        "title": str(title),
        "type": meta.get("type") if meta.get("type") in _NOTE_TYPES else "note",
        "folder": meta.get("folder", "") or "",
        "summary": meta.get("summary", "") or "",
        "updated": meta.get("updated", "") or "",
    }


def _paper_meta(paper_id: str) -> dict | None:
    """读一篇论文的元数据（加密 JSON）；不存在返回 None。"""
    p = PAPERS_DIR / f"{paper_id}.json"
    if not p.is_file():
        return None
    try:
        m = vault.read_json(p)
    except Exception:
        return None
    if not isinstance(m, dict) or not m.get("title"):
        return None
    return {
        "id": paper_id,
        "title": str(m.get("title")),
        "author": m.get("author", "") or "",
        "status": m.get("status", "") or "",
    }


def _doc_meta(target_id: str) -> dict | None:
    """读外部项目文档的元信息（标题/路径）；不存在或无法读取返回 None。"""
    try:
        from .fs import _safe, _peek_title, _load_sources
        if ":" in target_id:
            sid, rel = target_id.split(":", 1)
            src, p, relp = _safe(sid, rel)
            if not p.is_file():
                return None
            title = _peek_title(p)
            return {
                "id": target_id,
                "title": title or p.stem,
                "type": "doc",
                "folder": f"{src.get('name', '')}/{relp}",
                "sid": sid,
                "path": relp,
            }
        else:
            for s in _load_sources():
                try:
                    src, p, relp = _safe(s["id"], target_id)
                    if p.is_file():
                        title = _peek_title(p)
                        return {
                            "id": f"{s['id']}:{relp}",
                            "title": title or p.stem,
                            "type": "doc",
                            "folder": f"{src.get('name', '')}/{relp}",
                            "sid": s["id"],
                            "path": relp,
                        }
                except Exception:
                    continue
            return None
    except Exception:
        return None


def _target_meta(target_type: str, target_id: str) -> dict | None:
    if target_type == "note":
        return _note_meta(target_id)
    if target_type == "paper":
        return _paper_meta(target_id)
    if target_type in ("doc", "project_doc"):
        return _doc_meta(target_id)
    if target_type == "assistant_record":
        with db() as conn:
            r = conn.execute("SELECT id, title FROM assistant_records WHERE id=?", (target_id,)).fetchone()
            if r:
                return {"id": r["id"], "title": r["title"] or "助手事项记录", "exists": True}
            return {"id": target_id, "title": "已删除的助手记录", "exists": False}
    return None


def _route_of(target_type: str, target_id: str) -> str:
    if target_type == "note":
        return f"/notes/{target_id}"
    if target_type == "paper":
        return f"/papers/{target_id}"
    if target_type in ("doc", "project_doc"):
        from urllib.parse import quote
        if ":" in target_id:
            sid, p = target_id.split(":", 1)
            return f"/projects/doc?sid={quote(sid)}&path={quote(p)}"
        return f"/projects/doc?path={quote(target_id)}"
    if target_type == "assistant_record":
        return f"/assistant?record_id={target_id}"
    return ""


# ---------- 请求模型 ----------

class ItemIn(BaseModel):
    # 不设 Pydantic min/max_length：空标题/超长交给下面的 _text 统一出 400 中文文案
    # （用 Field 约束会变成 FastAPI 422 结构化数组，前端 e?.response?.data?.detail 兜底不友好）
    title: str = ""
    parent_id: int | None = None


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    parent_id: int | None = None
    move_parent: bool = False      # True=同时应用 parent_id（含置空）；False=不动层级
    archived: bool | None = None


class MoveIn(BaseModel):
    direction: str = "up"          # up | down


class ThinkingIn(BaseModel):
    content: str = ""


class EntryIn(BaseModel):
    text: str = ""


class CaptureIn(BaseModel):
    text: str = ""
    source: str = ""
    url: str = ""
    user_note: str = ""
    item_id: int | None = None


class CapturePatch(BaseModel):
    text: str | None = None
    source: str | None = None
    url: str | None = None


class CaptureMoveIn(BaseModel):
    item_id: int | None = None
    archived: bool | None = None


class LinkIn(BaseModel):
    target_type: str = ""
    target_id: str = ""   # 长度/字符集校验见 add_link（统一 400 中文文案）


# ---------- 事项 ----------

def _check_parent(conn, parent_id: int | None) -> int | None:
    if parent_id is None:
        return None
    row = _item_row(conn, parent_id)
    if row is None:
        raise HTTPException(404, "父事项不存在")
    if row["parent_id"] is not None:
        raise HTTPException(400, "子事项下不能再建子事项（只支持一层）")
    return parent_id


def _next_sort(conn, parent_id: int | None) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort), -1) AS m FROM workbench_items "
        "WHERE " + ("parent_id IS NULL" if parent_id is None else "parent_id=?"),
        () if parent_id is None else (parent_id,),
    ).fetchone()
    return int(row["m"]) + 1


def _count_sub(conn, item_id: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM workbench_items WHERE parent_id=?", (item_id,)).fetchone()["c"])


def _sub_counts(conn) -> dict[int, int]:
    """每事项的直接子事项数（单次聚合查询，避免列表里逐事项查）。"""
    return {
        int(r["parent_id"]): int(r["c"])
        for r in conn.execute(
            "SELECT parent_id, COUNT(*) AS c FROM workbench_items "
            "WHERE parent_id IS NOT NULL GROUP BY parent_id")
    }


def _entry_counts(conn) -> dict[int, dict]:
    """每事项小记数 + 最近小记时间（单次聚合查询，避免逐事项查）。"""
    out: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT item_id, COUNT(*) AS c, MAX(created_at) AS last FROM workbench_entries GROUP BY item_id"
    ):
        out[int(r["item_id"])] = {"count": int(r["c"]), "last": r["last"] or ""}
    return out


def _capture_counts(conn) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT item_id, COUNT(*) AS c, MAX(created_at) AS last FROM workbench_captures "
        "WHERE item_id IS NOT NULL AND archived=0 GROUP BY item_id"
    ):
        out[int(r["item_id"])] = {"count": int(r["c"]), "last": r["last"] or ""}
    return out


def _updated_of(row, ent: dict, cap: dict) -> str:
    """事项的「最近更新时间」= 当前思路 / 小记 / 收集片段三者最新（无内容时=建档时间）。"""
    cands = [row["updated_at"] or "", row["created_at"] or ""]
    if ent.get("last"):
        cands.append(ent["last"])
    if cap.get("last"):
        cands.append(cap["last"])
    return max(c for c in cands if c)


def _item_brief(conn, row, ents: dict, caps: dict, subs: dict) -> dict:
    iid = int(row["id"])
    ent = ents.get(iid, {})
    cap = caps.get(iid, {})
    return {
        "id": iid,
        "title": row["title"],
        "parent_id": row["parent_id"],
        "sort": int(row["sort"]),
        "archived": bool(row["archived"]),
        "summary": row["summary"] or "",
        "entry_count": int(ent.get("count", 0)),
        "capture_count": int(cap.get("count", 0)),
        "sub_count": int(subs.get(iid, 0)),
        "updated_at": _updated_of(row, ent, cap),
        "created_at": row["created_at"],
    }


@router.get("")
def overview(include_archived: bool = False, _user: dict = Depends(get_current)):
    """工作台首页数据：事项树（主事项 + 一层子事项）+ 未归类收集箱最近片段 + 计数。

    include_archived=True 时额外带上已归档的事项（含已归档子事项），
    便于「看看归档了什么」；缺省只看在办的事项。
    只返回摘要（summary）与计数，不返回当前思路正文、小记正文、片段文字。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM workbench_items "
            + ("" if include_archived else "WHERE archived=0 ")
            + "ORDER BY archived, sort, id",
        ).fetchall()
        ents = _entry_counts(conn)
        caps = _capture_counts(conn)
        subs = _sub_counts(conn)
        briefs = [_item_brief(conn, r, ents, caps, subs) for r in rows]
        by_parent: dict[int | None, list[dict]] = {}
        for b in briefs:
            by_parent.setdefault(b["parent_id"], []).append(b)
        tree = []
        for b in by_parent.get(None, []):
            tree.append({**b, "children": by_parent.get(b["id"], [])})
        # 未归类收集箱：最近 5 条（文字摘要 + 来源 + 链接）
        inbox_rows = conn.execute(
            "SELECT id, source, url, created_at FROM workbench_captures "
            "WHERE item_id IS NULL AND archived=0 ORDER BY created_at DESC, id DESC LIMIT 5"
        ).fetchall()
        inbox_total = int(conn.execute(
            "SELECT COUNT(*) AS c FROM workbench_captures WHERE item_id IS NULL AND archived=0"
        ).fetchone()["c"])
    inbox = []
    for r in inbox_rows:
        try:
            text = _read_content(_capture_path(int(r["id"])))
        except HTTPException:
            raise
        except Exception:
            text = ""
        inbox.append({
            "id": int(r["id"]),
            "excerpt": summarize(text, 60),
            "has_text": bool(text.strip()),
            "source": r["source"] or "",
            "url": r["url"] or "",
            "created_at": r["created_at"],
        })
    return {"items": tree, "inbox": inbox, "inbox_total": inbox_total}


@router.post("/items", status_code=201)
def create_item(body: ItemIn, _user: dict = Depends(get_current)):
    """新建事项。标题可以留空（=「未命名」）：支持"先随手写、之后再决定名字"，
    首次写入当前思路时会把正文第一行自动提上来当标题。"""
    _require_dek()
    title = _text(body.title, MAX_TITLE, "事项标题") or UNNAMED
    with db() as conn:
        parent_id = _check_parent(conn, body.parent_id)
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO workbench_items(parent_id, title, sort, archived, summary, created_at, updated_at) "
            "VALUES(?,?,?,0,'',?,?)",
            (parent_id, title, _next_sort(conn, parent_id), now, now),
        )
        item_id = int(cur.lastrowid)
    # 先建空正文文件：此后「当前思路」文件存在性与事项一一对应（也不写入空明文）
    _write_content(_thinking_path(item_id), "")
    return {"id": item_id, "title": title, "parent_id": parent_id}


@router.get("/items/{item_id}")
def get_item(item_id: int, _user: dict = Depends(get_current)):
    """事项详情：当前思路正文 + 全部小记 + 收集片段 + 子事项 + 相关资料。"""
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        ents = _entry_counts(conn)
        caps = _capture_counts(conn)
        subs_map = _sub_counts(conn)
        brief = _item_brief(conn, row, ents, caps, subs_map)
        sub_rows = conn.execute(
            "SELECT * FROM workbench_items WHERE parent_id=? ORDER BY sort, id", (item_id,)).fetchall()
        subs = [_item_brief(conn, r, ents, caps, subs_map) for r in sub_rows]
        parent = None
        if row["parent_id"] is not None:
            pr = _item_row(conn, int(row["parent_id"]))
            if pr is not None:
                parent = {"id": int(pr["id"]), "title": pr["title"]}
        siblings = [
            {"id": int(r["id"]), "title": r["title"]}
            for r in conn.execute(
                "SELECT id, title FROM workbench_items WHERE "
                + ("parent_id IS NULL" if row["parent_id"] is None else "parent_id=?")
                + " AND archived=0 ORDER BY sort, id",
                () if row["parent_id"] is None else (int(row["parent_id"]),),
            ).fetchall()
        ]
        entry_rows = conn.execute(
            "SELECT id, created_at, updated_at FROM workbench_entries WHERE item_id=? "
            "ORDER BY created_at DESC, id DESC", (item_id,)).fetchall()
        capture_rows = conn.execute(
            "SELECT id, source, url, created_at FROM workbench_captures "
            "WHERE item_id=? AND archived=0 ORDER BY created_at DESC, id DESC", (item_id,)).fetchall()
        link_rows = conn.execute(
            "SELECT id, target_type, target_id, sort FROM workbench_links "
            "WHERE item_id=? ORDER BY sort, id", (item_id,)).fetchall()

    thinking = _read_content(_thinking_path(item_id))
    entries = []
    for r in entry_rows:
        try:
            text = _read_content(_entry_path(item_id, int(r["id"])))
        except HTTPException:
            raise
        except Exception:
            text = ""
        entries.append({
            "id": int(r["id"]),
            "text": text,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    captures = []
    for r in capture_rows:
        try:
            text = _read_content(_capture_path(int(r["id"])))
        except HTTPException:
            raise
        except Exception:
            text = ""
        captures.append({
            "id": int(r["id"]),
            "text": text,
            "source": r["source"] or "",
            "url": r["url"] or "",
            "created_at": r["created_at"],
        })
    links = []
    for r in link_rows:
        t_type, t_id = r["target_type"], r["target_id"]
        meta = _target_meta(t_type, t_id)
        links.append({
            "id": int(r["id"]),
            "target_type": t_type,
            "target_id": t_id,
            "title": meta["title"] if meta else "资料已删除",
            "route": _route_of(t_type, t_id),
            "missing": meta is None,
            **({"author": meta.get("author", "")} if meta and t_type == "paper" else {}),
            **({"folder": meta.get("folder", "")} if meta and "folder" in meta else {}),
        })
    return {
        **brief,
        "thinking": thinking,
        "entries": entries,
        "captures": captures,
        "links": links,
        "children": subs,
        "parent": parent,
        "siblings": siblings,
    }


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, _user: dict = Depends(get_current)):
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        sets, args = [], []
        if body.title is not None:
            title = _text(body.title, MAX_TITLE, "事项标题")
            if not title:
                raise HTTPException(400, "请填写事项标题")
            sets.append("title=?")
            args.append(title)
        if body.move_parent:
            pid = body.parent_id
            if pid is not None:
                if int(pid) == int(item_id):
                    raise HTTPException(400, "事项不能作为自己的父事项")
                if _count_sub(conn, item_id) > 0:
                    raise HTTPException(400, "该事项下已有子事项，不能再成为子事项（只支持一层）")
            _check_parent(conn, pid)
            sets.append("parent_id=?")
            args.append(pid)
            sets.append("sort=?")
            args.append(_next_sort(conn, pid))
        if body.archived is not None:
            sets.append("archived=?")
            args.append(1 if body.archived else 0)
        if not sets:
            return {"ok": True}
        sets.append("updated_at=?")
        args.append(now_iso())
        args.append(item_id)
        conn.execute(f"UPDATE workbench_items SET {', '.join(sets)} WHERE id=?", args)
    return {"ok": True}


@router.post("/items/{item_id}/move")
def move_item(item_id: int, body: MoveIn, _user: dict = Depends(get_current)):
    """在同级内上移/下移一位（首页手动调整顺序）。"""
    if body.direction not in ("up", "down"):
        raise HTTPException(400, "direction 只能是 up / down")
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        pid = row["parent_id"]
        sibs = conn.execute(
            "SELECT id, sort FROM workbench_items WHERE "
            + ("parent_id IS NULL" if pid is None else "parent_id=?")
            + " ORDER BY sort, id",
            () if pid is None else (int(pid),),
        ).fetchall()
        ids = [int(r["id"]) for r in sibs]
        if item_id not in ids:
            raise HTTPException(404, "事项不存在")
        i = ids.index(item_id)
        j = i - 1 if body.direction == "up" else i + 1
        if j < 0 or j >= len(ids):
            return {"ok": True, "moved": False}
        ids[i], ids[j] = ids[j], ids[i]
        for k, iid in enumerate(ids):      # 顺序整体重排为 0..n-1，避免历史 sort 值空洞
            conn.execute("UPDATE workbench_items SET sort=? WHERE id=?", (k, iid))
    return {"ok": True, "moved": True}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, _user: dict = Depends(get_current)):
    """删除事项：连同其子事项、小记、收集片段、资料链接一并删除。

    只删工作台自己的数据 —— 博客笔记、论文、日程等既有模块的数据一律不动；
    随笔正文文件（当前思路/小记/片段）移入回收站，可恢复。"""
    _require_dek()
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        item_ids = [item_id] + [
            int(r["id"]) for r in conn.execute(
                "SELECT id FROM workbench_items WHERE parent_id=?", (item_id,)).fetchall()
        ]
        ph = ",".join("?" * len(item_ids))
        capture_rows = conn.execute(
            f"SELECT id FROM workbench_captures WHERE item_id IN ({ph})", item_ids).fetchall()
        capture_ids = [int(r["id"]) for r in capture_rows]
        conn.execute(f"DELETE FROM workbench_entries WHERE item_id IN ({ph})", item_ids)
        conn.execute(f"DELETE FROM workbench_links WHERE item_id IN ({ph})", item_ids)
        conn.execute(f"DELETE FROM workbench_captures WHERE item_id IN ({ph})", item_ids)
        conn.execute(f"DELETE FROM workbench_items WHERE id IN ({ph})", item_ids)
        title = row["title"]
        subs = len(item_ids) - 1
    # 正文文件进回收站（模块 workbench，只包含本事项自己的随笔与片段）
    victims: list[Path] = []
    for iid in item_ids:
        victims.append(_thinking_path(iid))
    for iid in item_ids:
        d = _item_dir(iid) / "entries"
        if d.is_dir():
            victims.extend(sorted(d.glob("*.md")))
    for cid in capture_ids:
        victims.append(_capture_path(cid))
    victims = [p for p in victims if p.is_file()]
    label = title if subs == 0 else f"{title}（含 {subs} 个子事项）"
    tid = trashbin.move_to_trash(victims, module="workbench", label=label)
    for iid in item_ids:
        # 只清掉刚刚搬空的目录（rmdir 遇非空会失败并被忽略）——
        # 绝不用 rmtree 递归删：万一目录里有本模块不认识的东西，宁可留着也不误删。
        try:
            (_item_dir(iid) / "entries").rmdir()
        except OSError:
            pass
        try:
            _item_dir(iid).rmdir()
        except OSError:
            pass
    return {"ok": True, "deleted_items": len(item_ids), "trash_id": tid}


# ---------- 当前思路 ----------

@router.get("/items/{item_id}/thinking")
def get_thinking(item_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
    return {"content": _read_content(_thinking_path(item_id))}


@router.put("/items/{item_id}/thinking")
def put_thinking(item_id: int, body: ThinkingIn, _user: dict = Depends(get_current)):
    """整篇覆盖保存「当前思路」（可反复修改）。同时刷新列表用的短摘要。

    若该事项还是「未命名」（用户先写后命名），把正文第一行自动提上来当标题；
    用户改过名字（或之后再改名）都不会被覆盖。"""
    if len(body.content) > MAX_THINKING:
        raise HTTPException(400, f"当前思路最长 {MAX_THINKING} 字符")
    _require_dek()
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        now = now_iso()
        _write_content(_thinking_path(item_id), body.content)
        title = row["title"]
        adopted = False
        if (title or "").strip() in ("", UNNAMED):
            guess = first_line(body.content)
            if guess and guess != title:
                title = guess
                adopted = True
        if adopted:
            conn.execute(
                "UPDATE workbench_items SET title=?, summary=?, updated_at=? WHERE id=?",
                (title, summarize(body.content), now, item_id),
            )
        else:
            conn.execute(
                "UPDATE workbench_items SET summary=?, updated_at=? WHERE id=?",
                (summarize(body.content), now, item_id),
            )
    return {"ok": True, "updated_at": now, "summary": summarize(body.content),
            "title": title, "title_adopted": adopted}


# ---------- 小记 ----------

@router.post("/items/{item_id}/entries", status_code=201)
def create_entry(item_id: int, body: EntryIn, _user: dict = Depends(get_current)):
    text = body.text or ""
    if not text.strip():
        raise HTTPException(400, "小记内容不能为空")
    if len(text) > MAX_ENTRY:
        raise HTTPException(400, f"小记最长 {MAX_ENTRY} 字符")
    _require_dek()
    with db() as conn:
        row = _item_row(conn, item_id)
        if row is None:
            raise HTTPException(404, "事项不存在")
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO workbench_entries(item_id, created_at, updated_at) VALUES(?,?,?)",
            (item_id, now, now),
        )
        entry_id = int(cur.lastrowid)
        _write_content(_entry_path(item_id, entry_id), text)
        _touch_item(conn, item_id)
    return {"id": entry_id, "text": text, "created_at": now, "updated_at": now}


@router.put("/items/{item_id}/entries/{entry_id}")
def update_entry(item_id: int, entry_id: int, body: EntryIn, _user: dict = Depends(get_current)):
    text = body.text or ""
    if not text.strip():
        raise HTTPException(400, "小记内容不能为空")
    if len(text) > MAX_ENTRY:
        raise HTTPException(400, f"小记最长 {MAX_ENTRY} 字符")
    _require_dek()
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM workbench_entries WHERE id=? AND item_id=?", (entry_id, item_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "小记不存在")
        now = now_iso()
        _write_content(_entry_path(item_id, entry_id), text)
        conn.execute("UPDATE workbench_entries SET updated_at=? WHERE id=?", (now, entry_id))
        _touch_item(conn, item_id)
    return {"ok": True, "updated_at": now}


@router.delete("/items/{item_id}/entries/{entry_id}")
def delete_entry(item_id: int, entry_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM workbench_entries WHERE id=? AND item_id=?", (entry_id, item_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "小记不存在")
        conn.execute("DELETE FROM workbench_entries WHERE id=?", (entry_id,))
        _touch_item(conn, item_id)
    p = _entry_path(item_id, entry_id)
    if p.is_file():
        trashbin.move_to_trash([p], module="workbench", label=f"小记 #{entry_id}")
    return {"ok": True}


# ---------- 收集箱 ----------

def _capture_brief(cid: int, *, text: str, source: str, url: str, created_at: str,
                   item_id: int | None, archived: bool = False) -> dict:
    return {
        "id": cid,
        "excerpt": summarize(text, 80),
        "has_text": bool((text or "").strip()),
        "source": source or "",
        "url": url or "",
        "item_id": item_id,
        "archived": archived,
        "created_at": created_at,
    }


@router.get("/captures")
def list_captures(q: str | None = None, scope: str = "inbox", item_id: int | None = None,
                  limit: int = 100, offset: int = 0, _user: dict = Depends(get_current)):
    """收集片段检索。
    scope=inbox：未归类收集箱（缺省）；scope=item：某事项的片段（需 item_id）；
    scope=all：全部未归档片段；scope=archived：已归档片段。
    q：按文字内容 / 来源 / 链接搜索。"""
    if scope not in ("inbox", "item", "all", "archived"):
        raise HTTPException(400, "scope 只能是 inbox / item / all / archived")
    if scope == "item" and item_id is None:
        raise HTTPException(400, "scope=item 时需提供 item_id")
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    where, args = [], []
    if scope == "inbox":
        where.append("item_id IS NULL AND archived=0")
    elif scope == "item":
        where.append("item_id=? AND archived=0")
        args.append(_int_id(item_id, "事项 ID"))
    elif scope == "all":
        where.append("archived=0")
    else:
        where.append("archived=1")
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    with db() as conn:
        rows = conn.execute(
            f"SELECT id, item_id, source, url, created_at FROM workbench_captures{sql_where} "
            "ORDER BY created_at DESC, id DESC", args).fetchall()
    needle = (q or "").strip().lower()
    items = []
    for r in rows:
        try:
            text = _read_content(_capture_path(int(r["id"])))
        except HTTPException:
            raise
        except Exception:
            text = ""
        if needle:
            hay = f"{text} {r['source'] or ''} {r['url'] or ''}".lower()
            if needle not in hay:
                continue
        items.append(_capture_brief(
            int(r["id"]), text=text, source=r["source"] or "", url=r["url"] or "",
            created_at=r["created_at"], item_id=r["item_id"],
        ))
    total = len(items)
    return {"items": items[offset:offset + limit], "total": total}


@router.post("/captures", status_code=201)
def create_capture(body: CaptureIn, _user: dict = Depends(get_current)):
    """随手记：文字 / 链接 / 来源都可以只填一项；item_id 为空=进未归类收集箱。"""
    text = body.text or ""
    if body.user_note:
        note_str = body.user_note.strip()
        if note_str:
            if text.strip():
                text = f"{text}\n\n> 附注: {note_str}"
            else:
                text = note_str
    source = _text(body.source, MAX_SOURCE, "来源")
    url = _text(body.url, MAX_URL, "链接")
    if not text.strip() and not url:
        raise HTTPException(400, "请填写内容或链接")
    if len(text) > MAX_CAPTURE:
        raise HTTPException(400, f"收集片段最长 {MAX_CAPTURE} 字符")
    _require_dek()
    with db() as conn:
        item_id = None
        if body.item_id is not None:
            iid = _int_id(body.item_id, "事项 ID")
            if _item_row(conn, iid) is None:
                raise HTTPException(404, "事项不存在")
            item_id = iid
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO workbench_captures(item_id, source, url, archived, created_at, updated_at) "
            "VALUES(?,?,?,0,?,?)", (item_id, source, url, now, now),
        )
        cid = int(cur.lastrowid)
        _write_content(_capture_path(cid), text)
        if item_id is not None:
            _touch_item(conn, item_id)
    return _capture_brief(cid, text=text, source=source, url=url, created_at=now, item_id=item_id)


@router.get("/captures/{capture_id}")
def get_capture(capture_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        r = conn.execute(
            "SELECT id, item_id, source, url, archived, created_at FROM workbench_captures WHERE id=?",
            (capture_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "收集片段不存在")
    text = _read_content(_capture_path(capture_id))
    return {
        "id": int(r["id"]),
        "text": text,
        "source": r["source"] or "",
        "url": r["url"] or "",
        "item_id": r["item_id"],
        "archived": bool(r["archived"]),
        "created_at": r["created_at"],
    }


@router.put("/captures/{capture_id}")
def update_capture(capture_id: int, body: CapturePatch, _user: dict = Depends(get_current)):
    _require_dek()
    with db() as conn:
        r = conn.execute("SELECT id FROM workbench_captures WHERE id=?", (capture_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "收集片段不存在")
        sets, args = [], []
        if body.text is not None:
            if len(body.text) > MAX_CAPTURE:
                raise HTTPException(400, f"收集片段最长 {MAX_CAPTURE} 字符")
            _write_content(_capture_path(capture_id), body.text)
        if body.source is not None:
            sets.append("source=?")
            args.append(_text(body.source, MAX_SOURCE, "来源"))
        if body.url is not None:
            sets.append("url=?")
            args.append(_text(body.url, MAX_URL, "链接"))
        sets.append("updated_at=?")
        args.append(now_iso())
        args.append(capture_id)
        conn.execute(f"UPDATE workbench_captures SET {', '.join(sets)} WHERE id=?", args)
    return {"ok": True}


@router.post("/captures/{capture_id}/move")
def move_capture(capture_id: int, body: CaptureMoveIn, _user: dict = Depends(get_current)):
    """把片段放入某个事项（item_id）或移回收集箱（item_id=null）；archived 可单独切换。"""
    with db() as conn:
        r = conn.execute("SELECT id, item_id FROM workbench_captures WHERE id=?", (capture_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "收集片段不存在")
        sets, args = [], []
        if body.item_id is not None or "item_id" in body.model_fields_set:
            if body.item_id is None:
                sets.append("item_id=NULL")
            else:
                iid = _int_id(body.item_id, "事项 ID")
                if _item_row(conn, iid) is None:
                    raise HTTPException(404, "事项不存在")
                sets.append("item_id=?")
                args.append(iid)
                _touch_item(conn, iid)
            old = r["item_id"]
            if old is not None:
                _touch_item(conn, int(old))
        if body.archived is not None:
            sets.append("archived=?")
            args.append(1 if body.archived else 0)
        if not sets:
            return {"ok": True}
        sets.append("updated_at=?")
        args.append(now_iso())
        args.append(capture_id)
        conn.execute(f"UPDATE workbench_captures SET {', '.join(sets)} WHERE id=?", args)
    return {"ok": True}


@router.delete("/captures/{capture_id}")
def delete_capture(capture_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        r = conn.execute("SELECT id, item_id FROM workbench_captures WHERE id=?", (capture_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "收集片段不存在")
        conn.execute("DELETE FROM workbench_captures WHERE id=?", (capture_id,))
        if r["item_id"] is not None:
            _touch_item(conn, int(r["item_id"]))
    p = _capture_path(capture_id)
    if p.is_file():
        trashbin.move_to_trash([p], module="workbench", label=f"收集片段 #{capture_id}")
    return {"ok": True}


# ---------- 相关资料（指向论文 / 博客笔记的链接） ----------

def _resolve_links(conn, item_id: int) -> list[dict]:
    out = []
    for r in conn.execute(
        "SELECT id, target_type, target_id, sort FROM workbench_links WHERE item_id=? ORDER BY sort, id",
        (item_id,)).fetchall():
        t_type, t_id = r["target_type"], r["target_id"]
        meta = _target_meta(t_type, t_id)
        out.append({
            "id": int(r["id"]),
            "target_type": t_type,
            "target_id": t_id,
            "title": meta["title"] if meta else "资料已删除",
            "route": _route_of(t_type, t_id),
            "missing": meta is None,
            **({"author": meta.get("author", "")} if meta and t_type == "paper" else {}),
            **({"folder": meta.get("folder", "")} if meta and "folder" in meta else {}),
        })
    return out


@router.get("/links/backlinks")
def get_backlinks(target_type: str, target_id: str, _user: dict = Depends(get_current)):
    """反向引用查询接口：查询当前笔记、论文或文档被哪些工作台事项关联引用。

    返回事项的 id, title, parent_id, parent_title, updated_at, archived 等，
    让资料知道自己属于哪些事项，形成双向网状连接。
    """
    t_type = (target_type or "").strip()
    t_id = (target_id or "").strip()
    if not t_type or not t_id:
        raise HTTPException(400, "缺少 target_type 或 target_id")
    type_cands = [t_type]
    if t_type in ("doc", "project_doc"):
        type_cands = ["doc", "project_doc"]
    with db() as conn:
        ph = ",".join("?" * len(type_cands))
        rows = conn.execute(
            f"""
            SELECT 
                w.id,
                w.title,
                w.parent_id,
                w.updated_at,
                w.archived,
                p.title AS parent_title
            FROM workbench_links l
            JOIN workbench_items w ON l.item_id = w.id
            LEFT JOIN workbench_items p ON w.parent_id = p.id
            WHERE l.target_type IN ({ph}) AND l.target_id = ?
            ORDER BY w.archived ASC, w.updated_at DESC, w.id DESC
            """,
            (*type_cands, t_id),
        ).fetchall()
        items = [
            {
                "id": int(r["id"]),
                "title": r["title"],
                "parent_id": int(r["parent_id"]) if r["parent_id"] is not None else None,
                "parent_title": r["parent_title"],
                "updated_at": r["updated_at"] or "",
                "archived": bool(r["archived"]),
            }
            for r in rows
        ]
    return {"items": items}


@router.post("/captures/{capture_id}/promote")
def promote_capture(capture_id: int, _user: dict = Depends(get_current)):
    """把收集片段变成一个事项（整理的时候用）：片段原文直接成为该事项的「当前思路」，
    事项标题取片段第一行；片段本身归档保留（原始记录不删）。

    这样「先随手写、之后再决定归属」不用重新抄一遍：写下的东西原样留在事项里。"""
    _require_dek()
    with db() as conn:
        r = conn.execute(
            "SELECT id, item_id, source, url, archived FROM workbench_captures WHERE id=?",
            (capture_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "收集片段不存在")
    text = _read_content(_capture_path(capture_id))
    title = first_line(text) or (r["source"] or "").strip() or UNNAMED
    now = now_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO workbench_items(parent_id, title, sort, archived, summary, created_at, updated_at) "
            "VALUES(NULL,?,?,0,?,?,?)",
            (title, _next_sort(conn, None), summarize(text), now, now),
        )
        item_id = int(cur.lastrowid)
        _write_content(_thinking_path(item_id), text)
        extra = ""
        if r["url"]:
            extra = f"\n\n来源：{r['source'] or '链接'}\n{r['url']}"
            _write_content(_thinking_path(item_id), text + extra)
        conn.execute("UPDATE workbench_captures SET archived=1, updated_at=? WHERE id=?", (now, capture_id))
        _touch_item(conn, item_id)
    return {"ok": True, "item_id": item_id, "title": title,
            "thinking": text + extra}


@router.get("/items/{item_id}/links")
def list_links(item_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        if _item_row(conn, item_id) is None:
            raise HTTPException(404, "事项不存在")
        return {"items": _resolve_links(conn, item_id)}


@router.post("/items/{item_id}/links", status_code=201)
def add_link(item_id: int, body: LinkIn, _user: dict = Depends(get_current)):
    """关联一份已有资料。幂等：同一事项内同一资料只保留一条（UNIQUE 约束 + INSERT OR IGNORE），
    因此笔记自动保存/多次保存、重复点「关联」都不会产生重复链接。"""
    t_type = (body.target_type or "").strip()
    if t_type not in TARGET_TYPES:
        raise HTTPException(400, "target_type 只能是 note（博客笔记）/ paper（论文）/ doc（项目文档）")
    if t_type in ("note", "paper"):
        t_id = _text(body.target_id, 64, "资料 ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", t_id):
            raise HTTPException(400, "资料 ID 不合法")
    else:
        t_id = _text(body.target_id, 500, "资料 ID")
        if not t_id or len(t_id) < 1:
            raise HTTPException(400, "资料 ID 不合法")
    if _target_meta(t_type, t_id) is None:
        raise HTTPException(404, "资料不存在或已被删除")
    with db() as conn:
        if _item_row(conn, item_id) is None:
            raise HTTPException(404, "事项不存在")
        row = conn.execute(
            "SELECT COALESCE(MAX(sort), -1) AS m FROM workbench_links WHERE item_id=?", (item_id,)
        ).fetchone()
        now = now_iso()
        cur = conn.execute(
            "INSERT OR IGNORE INTO workbench_links(item_id, target_type, target_id, sort, created_at) "
            "VALUES(?,?,?,?,?)", (item_id, t_type, t_id, int(row["m"]) + 1, now),
        )
        created = cur.rowcount > 0
        _touch_item(conn, item_id)
        link = conn.execute(
            "SELECT id FROM workbench_links WHERE item_id=? AND target_type=? AND target_id=?",
            (item_id, t_type, t_id)).fetchone()
    return {"ok": True, "created": created, "link_id": int(link["id"]) if link else None}


@router.delete("/items/{item_id}/links/{link_id}")
def delete_link(item_id: int, link_id: int, _user: dict = Depends(get_current)):
    """只移除工作台的入口链接，不删除论文或博客笔记本身。"""
    with db() as conn:
        r = conn.execute(
            "SELECT id FROM workbench_links WHERE id=? AND item_id=?", (link_id, item_id)).fetchone()
        if r is None:
            raise HTTPException(404, "关联不存在")
        conn.execute("DELETE FROM workbench_links WHERE id=?", (link_id,))
        _touch_item(conn, item_id)
    return {"ok": True}


@router.get("/items/{item_id}/note-link")
def note_link_status(item_id: int, note_id: str, _user: dict = Depends(get_current)):
    """笔记编辑页用：该事项是否已关联这篇笔记（判断要不要补建关联）。"""
    with db() as conn:
        if _item_row(conn, item_id) is None:
            raise HTTPException(404, "事项不存在")
        r = conn.execute(
            "SELECT id FROM workbench_links WHERE item_id=? AND target_type='note' AND target_id=?",
            (item_id, note_id)).fetchone()
    return {"linked": r is not None, "link_id": int(r["id"]) if r else None}


# ---------- 资料搜索选择器（现有论文 + 笔记·博客 + 项目文档） ----------

@router.get("/selector")
def selector(q: str | None = None, kind: str = "all", limit: int = 30,
             _user: dict = Depends(get_current)):
    """搜索可关联的现有资料：kind=all / note / paper / doc / project_doc。
    包含普通博客笔记、论文库里的论文与项目文档；不新建任何资料。"""
    if kind not in ("all", "note", "paper", "doc", "project_doc"):
        raise HTTPException(400, "kind 只能是 all / note / paper / doc / project_doc")
    limit = max(1, min(int(limit or 30), 100))
    needle = (q or "").strip().lower()
    items: list[dict] = []
    if kind in ("all", "note"):
        for p in sorted(NOTES_DIR.glob("*.md"), key=_mtime, reverse=True):
            n = _note_meta(p.stem)
            if n is None:
                continue
            if needle and needle not in f"{n['title']} {n['summary']} {n['folder']}".lower():
                continue
            items.append({
                "target_type": "note", "target_id": n["id"], "title": n["title"],
                "kind": n["type"], "folder": n["folder"], "summary": n["summary"],
            })
    if kind in ("all", "paper"):
        for p in sorted(PAPERS_DIR.glob("*.json"), key=_mtime, reverse=True):
            if p.name.endswith(".hl.json"):
                continue
            m = _paper_meta(p.stem)
            if m is None:
                continue
            if needle and needle not in f"{m['title']} {m['author']}".lower():
                continue
            items.append({
                "target_type": "paper", "target_id": m["id"], "title": m["title"],
                "kind": "paper", "author": m["author"], "status": m["status"],
            })
    if kind in ("all", "doc", "project_doc"):
        try:
            from .fs import _load_sources, _norm_root, _walk_md, _peek_title
            for src in _load_sources():
                try:
                    _, src_root = _norm_root(src["root"])
                except Exception:
                    continue
                patterns = src.get("include") or []
                for doc_path, relp in _walk_md(src_root, patterns, config.DOC_SCAN_MAX_DEPTH, 200):
                    doc_title = _peek_title(doc_path)
                    target_id = f"{src['id']}:{relp}"
                    if needle and needle not in f"{doc_title} {relp} {src['name']}".lower():
                        continue
                    items.append({
                        "target_type": "doc", "target_id": target_id, "title": doc_title,
                        "kind": "doc", "folder": f"{src['name']}/{relp}",
                        "summary": f"项目文档: {src['name']} ({relp})",
                    })
                    if len(items) >= limit * 2:
                        break
        except Exception:
            pass
    return {"items": items[:limit], "total": len(items)}