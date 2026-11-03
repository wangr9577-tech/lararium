"""笔记/博客真实 CRUD：正文 md 文件（frontmatter 元数据）+ AES-GCM 加密落盘。

文件结构：data/notes/<id>.md
  ---
  title: 标题
  type: blog | note | project
  fmt: md | ink            # 正文形式：md=Markdown 文本；ink=白板手写（正文为笔迹 JSON）
  tags: [a, b]
  summary: 摘要（可空）
  created: 2026-09-06 01:00:00
  updated: 2026-09-06 01:00:00
  ---
  正文：fmt=md 时为 Markdown 文本；fmt=ink 时为笔迹 JSON（页面比例 + 笔画数组）。
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
import json
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current
from ..db import db
from ..upload import read_upload

router = APIRouter(prefix="/api/notes", tags=["notes"])

NOTES_DIR = config.DATA_DIR / "notes"
IMAGES_DIR = config.DATA_DIR / "images"  # 笔记正文站内图片（粘贴/拖拽上传），AES 加密落盘
TYPES = ("blog", "note", "project")
MODULES = ("", "ielts")  # 空=普通博客笔记；ielts=雅思学习模块子页
MAX_FOLDER_DEPTH = 3    # 目录最大深度（a=1 层，a/b=2 层）
MAX_FOLDER_TOTAL = 160  # 目录全路径最大长度（笔记 folder 字段同样适用）
FM_KEYS = ("title", "type", "fmt", "tags", "summary", "created", "updated", "module", "folder", "ppt", "pdf", "parent")
FMTS = ("md", "ink", "card")
IMG_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
           "webp": "image/webp", "gif": "image/gif"}
IMG_NAME_RE = re.compile(r"^[0-9a-f]{12}\.(?:jpg|jpeg|png|webp|gif)$")
MAX_IMG = 20 * 1024 * 1024


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_fmt(raw: object) -> str:
    return raw if raw in FMTS else "md"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- 文件 <-> 对象 ----------

def _dump_file(id_: str, meta: dict, content: str) -> None:
    # 只写非空字段：老笔记没有 module/folder 时重写不新增空键
    head = yaml.safe_dump(
        {k: meta.get(k) for k in FM_KEYS if meta.get(k) not in (None, "")},
        allow_unicode=True, sort_keys=False, default_flow_style=None,
    ).strip()
    vault.write_text(NOTES_DIR / f"{id_}.md", f"---\n{head}\n---\n\n{content or ''}")


def _split(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw.strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2).lstrip("\r\n")


def _load(id_: str) -> dict | None:
    p = NOTES_DIR / f"{id_}.md"
    if not p.is_file():
        return None
    meta, content = _split(vault.read_text(p))
    if not meta.get("title"):
        meta["title"] = "(无标题)"
    return {
        "id": id_,
        "title": meta.get("title", ""),
        "type": meta.get("type") if meta.get("type") in TYPES else "note",
        "fmt": _norm_fmt(meta.get("fmt", "md")),
        "module": meta.get("module", "") or "",
        "folder": meta.get("folder", "") or "",
        "parent": meta.get("parent", "") or "",
        "tags": [t for t in (meta.get("tags") or []) if isinstance(t, str)],
        "summary": meta.get("summary", ""),
        "ppt": meta.get("ppt", "") or "",
        "pdf": meta.get("pdf", "") or "",
        "created": meta.get("created", ""),
        "updated": meta.get("updated", ""),
        "content": content.rstrip("\n"),
    }


# ---------- 列表缓存（进程内，消除 列表/目录计数/标签云 三个接口重复全量解密） ----------
# 安全前提：缓存里只有 frontmatter 明文元数据（不含正文），与 DEK 同生命周期——
# vault.has_dek() 变假（数据上锁）时立即清空，锁定态绝不从缓存吐出任何内容。
# 不加锁：本模块接口是同步函数（FastAPI 线程池执行），dict 赋值是原子的，
# 最坏情况是两个请求同时重建，只是多算一次，结果一致，无害。
_LIST_CACHE: dict = {"sig": None, "items": None}


def _notes_sig() -> tuple:
    """笔记目录签名：只用 p.stat()（绝不读文件内容、绝不解密）。
    文件增/删/改名、mtime_ns 或 size 变化都会改变签名 → 缓存失效重建。"""
    rows = []
    for p in NOTES_DIR.glob("*.md"):
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append((p.name, st.st_mtime_ns, st.st_size))
    return (vault.has_dek(), tuple(sorted(rows)))


def _build_items(include_content: bool = False) -> list[dict]:
    """单次遍历 NOTES_DIR 构建列表项（原 _list_all 循环体，行为逐字不变）。
    include_content=True 时每项额外带内部字段 _search（正文明文），
    仅供搜索匹配用，必须在返回给前端前 pop 掉，严禁泄漏到响应/日志。"""
    out = []
    parent_counts: dict[str, int] = {}
    for p in sorted(NOTES_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            raw = vault.read_text(p)
        except HTTPException:
            raise
        except Exception:
            continue
        meta, content = _split(raw)
        if not meta.get("title"):
            continue
        par = meta.get("parent", "") or ""
        if par:
            parent_counts[par] = parent_counts.get(par, 0) + 1
        fmt = _norm_fmt(meta.get("fmt", "md"))
        out.append({
            "id": p.stem,
            "title": meta.get("title", ""),
            "type": meta.get("type") if meta.get("type") in TYPES else "note",
            "fmt": fmt,
            "module": meta.get("module", "") or "",
            "folder": meta.get("folder", "") or "",
            "parent": par,
            "tags": [t for t in (meta.get("tags") or []) if isinstance(t, str)],
            "summary": meta.get("summary", ""),
            "ppt": meta.get("ppt", "") or "",
            "pdf": meta.get("pdf", "") or "",
            "created": meta.get("created", ""),
            "updated": meta.get("updated", ""),
            "content": (content.rstrip("\n") if fmt == "card" else ""),
            **({"_search": content or ""} if include_content else {}),
        })
    for n in out:
        n["subs"] = parent_counts.get(n["id"], 0)  # 直接子页数（parent 指向该 id 的笔记数）
    return out


def _list_all(include_content: bool = False) -> list[dict]:
    """列出全部笔记（按 mtime 倒序）。include_content=True 时每项额外带内部字段 _search
    （正文明文），仅供搜索匹配用，必须在返回给前端前 pop 掉，严禁泄漏到响应/日志。

    include_content=False（列表/目录计数/标签云三个接口共用路径）走进程内缓存：
    签名（_notes_sig，纯 stat，不解密）未变时直接返回缓存副本，
    避免一次页面交互触发三次全量解密。"""
    if include_content:
        # 搜索路径：一次性全量解密含正文，不读缓存也不写缓存
        return _build_items(include_content=True)
    if not vault.has_dek():
        # 数据已上锁：先清缓存，再走原路径（vault.read_text 会正常抛 423，
        # 保持「锁定态绝不吐明文」的安全语义——锁定态绝不从缓存返回数据）
        _LIST_CACHE["sig"] = None
        _LIST_CACHE["items"] = None
        return _build_items(include_content=False)
    sig = _notes_sig()
    cached = _LIST_CACHE["items"]
    if _LIST_CACHE["sig"] == sig and cached is not None:
        return [dict(it) for it in cached]  # 必须副本：防止调用方改动污染缓存
    items = _build_items(include_content=False)
    _LIST_CACHE["sig"] = sig
    _LIST_CACHE["items"] = items
    return [dict(it) for it in items]


# ---------- 模型 ----------

class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "note"
    fmt: str = "md"  # md=Markdown 文本；ink=白板手写（content 为笔迹 JSON）
    module: str | None = Field(default=None, max_length=20)  # None=沿用/默认普通
    folder: str | None = None  # None=沿用；''=未分类；支持子目录全路径（如 'A/B'），长度/层级由 clean_folder_path 统一出 400
    parent: str | None = Field(default=None, max_length=16)  # None=沿用；''=无父；<id>=父页面（一层，子页不能套子页）
    tags: list[str] = Field(default_factory=list)
    summary: str = Field(default="", max_length=600)
    content: str = ""
    source_record_id: int | None = None  # 来源助手记录 id（写笔记联动）


def _check_module(module: str) -> None:
    if module not in MODULES:
        raise HTTPException(400, "module 只能是空（普通笔记）或 ielts（雅思子页）")


def _clean(body: NoteIn, module: str | None = None, folder: str | None = None, parent: str | None = None) -> dict:
    if body.type not in TYPES:
        raise HTTPException(400, "type 只能是 blog / note / project")
    if body.fmt not in FMTS:
        raise HTTPException(400, "fmt 只能是 md（文本）/ ink（白板手写）/ card（卡片速记）")
    if body.fmt == "ink":
        # 白板正文必须是一段合法 JSON：v1 单页 {page, strokes} 或 v2 多页 {pages:[...]}
        try:
            ink = json.loads(body.content or "null")
            if not isinstance(ink, dict):
                raise ValueError
            if not (isinstance(ink.get("strokes"), list) or isinstance(ink.get("pages"), list)):
                raise ValueError
        except Exception:
            raise HTTPException(400, "白板笔记正文必须是笔迹 JSON（{page, strokes} 或 {pages: [...]}）")
    tags = []
    seen = set()
    for t in body.tags:
        t = t.strip().strip("#").strip()
        if t and t not in seen:
            tags.append(t[:30])
            seen.add(t)
    m = module if module is not None else (body.module or "")
    _check_module(m)
    # 目录支持子文件夹：folder 存全路径（如 'A/B'），逐段校验
    f = clean_folder_path(folder if folder is not None else (body.folder or ""))
    p = (parent if parent is not None else (body.parent or "")).strip()
    if len(p) > 16:
        raise HTTPException(400, "父页面 id 过长")
    if p:
        pn = _load(p)
        if pn is None:
            raise HTTPException(400, "父页面不存在")
        if pn.get("parent", ""):
            raise HTTPException(400, "子页面不能再包含子页面（一层结构）")
    return {
        "title": body.title.strip(),
        "type": body.type,
        "fmt": body.fmt,
        "module": m,
        "folder": f,
        "parent": p,
        "tags": tags,
        "summary": body.summary.strip(),
        "content": body.content,
    }


# ---------- 接口 ----------

@router.get("")
def list_notes(type_: str | None = None, tag: str | None = None, q: str | None = None,
               module: str | None = None, folder: str | None = None, parent: str | None = None,
               subtree: bool = True,
               _user: dict = Depends(get_current)):
    """module 过滤：不传=只看普通笔记（排除雅思子页）；'all'=全部；'ielts'=雅思子页。
    folder 过滤：不传=不过滤；''（显式空）=只看未分类；其它=目录全路径。
    subtree 过滤：True（缺省）=子树匹配（含该目录自身及所有子目录下的笔记，向后兼容）；
    False=精确匹配（只看直接归属该目录的笔记，笔记只在其最邻近上级文件夹显示）。
    parent 过滤：不传=只看顶层（排除笔记内子页）；''=顶层；<id>=该父页面的子页。"""
    items = []
    for n in _list_all(include_content=bool(q and q.strip())):
        m = n.get("module", "") or ""
        if module == "all":
            pass
        elif module is None:
            if m:
                continue
        elif m != module:
            continue
        np = n.get("parent", "") or ""
        if parent is None or parent == "":
            if np:
                continue
        elif np != parent:
            continue
        if folder is not None and not _folder_match(n.get("folder", "") or "", folder, subtree):
            continue
        if type_ and n["type"] != type_:
            continue
        if tag and tag not in n["tags"]:
            continue
        if q:
            hay = f'{n["title"]} {n["summary"]} {" ".join(n["tags"])} {n.get("_search", "")}'.lower()
            if q.strip().lower() not in hay:
                continue
        items.append(n)
    # 正文是解密后的明文，仅在内存里用于搜索匹配；返回前必须剔除内部字段 _search
    for n in items:
        n.pop("_search", None)
    return {"items": items}


@router.get("/tags")
def list_tags(_user: dict = Depends(get_current)):
    counter: dict[str, int] = {}
    for n in _list_all():
        if n.get("module") or n.get("parent"):
            continue  # 雅思子页/笔记内子页的标签不进普通笔记的标签栏
        for t in n["tags"]:
            counter[t] = counter.get(t, 0) + 1
    return {"tags": [{"name": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]}


# ---------- 目录（子文件夹：全路径标识、按 module 隔离；需注册在 /{note_id} 之前） ----------
#
# 数据模型：notes_folders(module, name, parent, path, created)
#   parent=父目录全路径（''=顶层）；path=自身全路径（顶层=名字，如 'A'、'A/B'）。
#   唯一约束 (module, path) → 不同父目录下允许重名（A/词汇 与 B/词汇）。
# 笔记 frontmatter 的 folder 字段存目录全路径；列表/计数按子树语义（含子目录）。

class FolderIn(BaseModel):
    module: str = Field(default="", max_length=20)
    # 不设 Pydantic min/max_length：空/超长/含 / 交给 _clean_folder_name 与 clean_folder_path 统一出 400 中文文案（避免 422 数组）
    name: str
    parent: str = ""  # 父目录全路径；''=建在顶层


class FolderRenameIn(BaseModel):
    module: str = Field(default="", max_length=20)
    path: str = ""  # 要改名的目录全路径（新前端）
    name: str = ""  # 兼容旧前端：传顶层目录名
    new_name: str  # 空/超长/含 / 由 _clean_folder_name 统一出 400


def _clean_folder_name(name: str) -> str:
    n = name.strip()
    if not n or len(n) > 40:
        raise HTTPException(400, "目录名需为 1-40 字")
    if "/" in n:
        raise HTTPException(400, "目录名不能包含 /")
    return n


def clean_folder_path(path: str) -> str:
    """校验目录全路径（如 'A/B/C'）：每段 1-40 字、深度 ≤ MAX_FOLDER_DEPTH、总长 ≤ MAX_FOLDER_TOTAL。
    空串合法（=未分类），返回 strip 后的路径。"""
    p = (path or "").strip()
    if not p:
        return ""
    if len(p) > MAX_FOLDER_TOTAL:
        raise HTTPException(400, f"目录路径最长 {MAX_FOLDER_TOTAL} 字")
    parts = p.split("/")
    if len(parts) > MAX_FOLDER_DEPTH:
        raise HTTPException(400, f"目录最多 {MAX_FOLDER_DEPTH} 层")
    for seg in parts:
        if not seg.strip():
            raise HTTPException(400, "目录路径不合法（含空段）")
        if len(seg) > 40:
            raise HTTPException(400, "目录名最长 40 字")
    return p


def _folder_match(note_folder: str, folder: str, subtree: bool = True) -> bool:
    """笔记 folder 是否命中筛选：''=只看未分类；
    否则 subtree=true 子树匹配（自身 + 全部子目录），subtree=false 精确匹配（只看直接归属该目录的笔记）。"""
    if folder == "":
        return note_folder == ""
    if not subtree:
        return note_folder == folder
    return note_folder == folder or note_folder.startswith(folder + "/")


def _like_escape(s: str) -> str:
    """LIKE 前缀转义（目录名允许含 _/% 等字符，避免通配符误匹配子树）"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _folder_subtree(conn, module: str, path: str) -> list:
    """以 path 为根的目录子树全部行（含自身）；path 不存在时可能只含后代（正常树不会发生）"""
    return conn.execute(
        "SELECT * FROM notes_folders WHERE module=? AND (path=? OR path LIKE ? ESCAPE '\\')",
        (module, path, _like_escape(path) + "/%"),
    ).fetchall()


def _rewrite_folder_prefix(module: str, old_prefix: str, new_prefix: str) -> int:
    """把 module 下子树（folder==old_prefix 或其子路径）的笔记 folder 批量改写为新前缀。
    new_prefix=''=全部回未分类（移除 folder 字段）；子目录下笔记保留后缀路径（A/B → Z/B）。"""
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重新登录后重试")
    changed = 0
    for p in NOTES_DIR.glob("*.md"):
        try:
            raw = vault.read_text(p)
        except Exception:
            continue
        meta, content = _split(raw)
        if (meta.get("module", "") or "") != module:
            continue
        f = meta.get("folder", "") or ""
        if f == old_prefix:
            new = new_prefix
        elif f.startswith(old_prefix + "/"):
            rest = f[len(old_prefix) + 1:]
            new = f"{new_prefix}/{rest}" if new_prefix else ""
        else:
            continue
        meta2 = dict(meta)
        if new:
            meta2["folder"] = new
        else:
            meta2.pop("folder", None)
        _dump_file(p.stem, meta2, content)
        changed += 1
    return changed


@router.get("/folders")
def list_folders(module: str = "", _user: dict = Depends(get_current)):
    """返回平铺目录列表 {name, path, parent, count}，前端按 parent 组树。
    count=子树笔记数（含子目录下笔记），与点击该目录后看到的内容一致。"""
    _check_module(module)
    with db() as conn:
        rows = conn.execute(
            "SELECT name, path, parent FROM notes_folders WHERE module=? ORDER BY id",
            (module,)).fetchall()
    by_path = {r["path"] for r in rows}
    counts: dict[str, int] = {}
    for n in _list_all():
        if (n.get("module", "") or "") != module:
            continue
        f = n.get("folder", "") or ""
        if not f:
            continue
        # 沿笔记目录路径逐级向上，给路径上每个真实存在的目录各计一篇（子树计数）
        acc = ""
        for seg in f.split("/"):
            acc = f"{acc}/{seg}" if acc else seg
            if acc in by_path:
                counts[acc] = counts.get(acc, 0) + 1
    return {"items": [
        {"name": r["name"], "path": r["path"], "parent": r["parent"],
         "count": counts.get(r["path"], 0)}
        for r in rows
    ]}


@router.post("/folders", status_code=201)
def create_folder(body: FolderIn, _user: dict = Depends(get_current)):
    module = body.module.strip()
    _check_module(module)
    name = _clean_folder_name(body.name)
    parent = clean_folder_path(body.parent)
    if parent:
        with db() as conn:
            if conn.execute(
                "SELECT 1 FROM notes_folders WHERE module=? AND path=?",
                (module, parent)).fetchone() is None:
                raise HTTPException(400, "父目录不存在")
    path = f"{parent}/{name}" if parent else name
    if path.count("/") + 1 > MAX_FOLDER_DEPTH:
        raise HTTPException(400, f"目录最多 {MAX_FOLDER_DEPTH} 层")
    if len(path) > MAX_FOLDER_TOTAL:
        raise HTTPException(400, f"目录路径最长 {MAX_FOLDER_TOTAL} 字")
    with db() as conn:
        try:
            conn.execute(
                "INSERT INTO notes_folders(module, name, parent, path, created) VALUES(?,?,?,?,?)",
                (module, name, parent, path, now_iso()),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "同级已存在同名目录")
    return {"name": name, "path": path, "parent": parent, "count": 0}


@router.put("/folders")
def rename_folder(body: FolderRenameIn, _user: dict = Depends(get_current)):
    module = body.module.strip()
    _check_module(module)
    # 目录行 DB 写入会先提交，笔记文件重写在后（文件无法进事务）：
    # 锁定态必须前置 423，杜绝「目录已改名、笔记未跟随」的不一致
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重新登录后重试")
    new_name = _clean_folder_name(body.new_name)
    # 新前端传全路径；旧前端只传 name（顶层目录名=全路径），兼容
    old_path = clean_folder_path(body.path or body.name)
    if not old_path:
        raise HTTPException(400, "缺少目录标识（path）")
    with db() as conn:
        row = conn.execute(
            "SELECT id, parent FROM notes_folders WHERE module=? AND path=?",
            (module, old_path)).fetchone()
        if row is None:
            raise HTTPException(404, "目录不存在")
        parent = row["parent"]
        new_path = f"{parent}/{new_name}" if parent else new_name
        if new_path == old_path:
            return {"name": new_name, "path": new_path, "renamed_notes": 0}
        if len(new_path) > MAX_FOLDER_TOTAL:
            raise HTTPException(400, f"目录路径最长 {MAX_FOLDER_TOTAL} 字")
        # 全库唯一约束 (module, path) 保证不与任何目录（含子树外）冲突，
        # 冲突时事务整体回滚。新名为单段（禁 /），不可能改出自身后代成环。
        try:
            conn.execute(
                "UPDATE notes_folders SET name=?, path=? WHERE module=? AND id=?",
                (new_name, new_path, module, row["id"]),
            )
            # 子树后代目录：path 与 parent 同步前缀替换（保留后缀，A/B/C → Z/B/C；
            # 直接子目录的 parent 由旧路径变为新路径，substr 越界返回空串）
            conn.execute(
                "UPDATE notes_folders SET "
                "path=? || substr(path, ?), parent=? || substr(parent, ?) "
                "WHERE module=? AND path LIKE ? ESCAPE '\\'",
                (new_path, len(old_path) + 1, new_path, len(old_path) + 1,
                 module, _like_escape(old_path) + "/%"),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "目标位置已存在同名目录")
    changed = _rewrite_folder_prefix(module, old_path, new_path)
    return {"name": new_name, "path": new_path, "renamed_notes": changed}


@router.delete("/folders")
def delete_folder(module: str = "", path: str = "", name: str = "",
                  _user: dict = Depends(get_current)):
    """级联删除目录及其全部子目录；笔记不删，子树下所有笔记回到「未分类」。
    新前端传 path（全路径）；旧前端传 name（顶层目录名）。"""
    _check_module(module)
    # 同 rename_folder：锁定态前置 423，避免目录行先删、笔记未回未分类的不一致
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重新登录后重试")
    target = clean_folder_path(path or name)
    if not target:
        raise HTTPException(400, "缺少目录标识")
    with db() as conn:
        rows = _folder_subtree(conn, module, target)
        if not any(r["path"] == target for r in rows):
            raise HTTPException(404, "目录不存在")
        paths = [r["path"] for r in rows]
        ph = ",".join("?" * len(paths))
        conn.execute(
            f"DELETE FROM notes_folders WHERE module=? AND path IN ({ph})",
            [module, *paths],
        )
    moved = _rewrite_folder_prefix(module, target, "")
    return {"ok": True, "deleted_folders": len(paths), "moved_to_root": moved}


@router.get("/{note_id}")
def get_note(note_id: str, _user: dict = Depends(get_current)):
    n = _load(note_id)
    if n is None:
        raise HTTPException(404, "笔记不存在")
    return n


@router.post("", status_code=201)
def create_note(body: NoteIn, _user: dict = Depends(get_current)):
    data = _clean(body)
    id_ = new_id()
    now = now_iso()
    meta = {**data, "created": now, "updated": now}
    _dump_file(id_, meta, data["content"])
    if body.source_record_id:
        try:
            with db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO assistant_links(record_id, target_type, target_id, created_at) VALUES(?,?,?,?)",
                    (body.source_record_id, "note", id_, now),
                )
                conn.execute(
                    "UPDATE assistant_records SET read_state='noted', updated_at=? WHERE id=?",
                    (now, body.source_record_id),
                )
        except Exception:
            pass
    return {"id": id_, **{k: meta[k] for k in ("title", "type", "fmt", "module", "folder", "parent", "tags", "summary", "created", "updated")}}


def _renamed_only(old: dict, data: dict) -> bool:
    """是否「纯改名」：除 title 外，内容与元数据完全一致（不算内容更新）。"""
    for k in ("type", "fmt", "module", "folder", "parent", "summary", "content"):
        if (old.get(k) or "") != (data.get(k) or ""):
            return False
    return [t for t in (old.get("tags") or [])] == list(data.get("tags") or [])


@router.put("/{note_id}")
def update_note(note_id: str, body: NoteIn, _user: dict = Depends(get_current)):
    old = _load(note_id)
    if old is None:
        raise HTTPException(404, "笔记不存在")
    # module/folder/parent 未显式传（普通编辑器）→ 沿用原归属，避免误改
    module = body.module if body.module is not None else old.get("module", "")
    folder = body.folder if body.folder is not None else old.get("folder", "")
    parent = body.parent if body.parent is not None else old.get("parent", "")
    data = _clean(body, module=module, folder=folder, parent=parent)
    updated = now_iso()
    # 纯改名不算内容更新：沿用原时间戳，避免列表按更新时间排序时笔记跳到最前
    if old.get("updated") and _renamed_only(old, data):
        updated = old["updated"]
    meta = {
        **data,
        "created": old["created"],
        "updated": updated,
    }
    if old.get("ppt"):
        meta["ppt"] = old["ppt"]  # PPT 笔记标记在编辑时保留
    if old.get("pdf"):
        meta["pdf"] = old["pdf"]  # PDF 笔记标记在编辑时保留
    _dump_file(note_id, meta, data["content"])
    return {"id": note_id, **{k: meta[k] for k in ("title", "type", "fmt", "module", "folder", "parent", "tags", "summary", "created", "updated")}}


@router.delete("/{note_id}")
def delete_note(note_id: str, _user: dict = Depends(get_current)):
    p = NOTES_DIR / f"{note_id}.md"
    if not p.is_file():
        raise HTTPException(404, "笔记不存在")
    # 级联删除其下子页（用户确认：删除父页，子页一并删除）——移入回收站，可恢复
    victims = [p]
    try:
        title = _split(vault.read_text(p))[0].get("title") or "(无标题)"
    except Exception:
        title = "(无标题)"
    subs = 0
    for sp in NOTES_DIR.glob("*.md"):
        if sp.name == p.name:
            continue
        try:
            raw = vault.read_text(sp)
        except Exception:
            continue
        meta, _ = _split(raw)
        if meta.get("parent") == note_id:
            victims.append(sp)
            subs += 1
    label = title if subs == 0 else f"{title}（含 {subs} 篇子页）"
    tid = trashbin.move_to_trash(victims, module="note", label=label)
    return {"ok": True, "deleted_subpages": subs, "trash_id": tid}


# ---------- 站内图片（粘贴/拖拽上传，AES 加密落盘，需登录读取） ----------

@router.post("/images", status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...), _user: dict = Depends(get_current)):
    name = (file.filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in IMG_EXT:
        raise HTTPException(400, "仅支持 jpg / png / webp / gif 图片（可截图后 Ctrl+V，或拖入图片文件）")
    raw = await read_upload(file, MAX_IMG, request=request, too_big=f"图片超过 20MB 上限（{MAX_IMG // (1 << 20)}MB）")
    if not raw:
        raise HTTPException(400, "文件内容为空")
    iid = uuid.uuid4().hex[:12]
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    vault.write_bytes(IMAGES_DIR / f"{iid}.{ext}", raw)
    return {"url": f"/api/notes/images/{iid}.{ext}", "name": f"{iid}.{ext}"}


@router.get("/images/{name}")
def get_image(name: str, _user: dict = Depends(get_current)):
    if not IMG_NAME_RE.match(name):
        raise HTTPException(404, "图片不存在")
    p = IMAGES_DIR / name
    if not p.is_file():
        raise HTTPException(404, "图片不存在")
    ext = name.rsplit(".", 1)[-1]
    return Response(content=vault.read_bytes(p), media_type=IMG_EXT[ext])


# ---------- md -> PDF（pandoc + xelatex/TinyTeX，均用户级安装，无需 sudo） ----------

def _pandoc() -> str | None:
    p = os.environ.get("KRUSKAL_PANDOC")
    if p and Path(p).is_file():
        return p
    cand = Path(sys.executable).parent / "pandoc"
    if cand.is_file():
        return str(cand)
    return shutil.which("pandoc")


def _tinytex_bin() -> Path:
    return Path.home() / ".TinyTeX" / "bin" / "x86_64-linux"


@router.get("/{note_id}/export", summary="导出 PDF（pandoc + xelatex）")
def export_pdf(note_id: str, _user: dict = Depends(get_current)):
    n = _load(note_id)
    if n is None:
        raise HTTPException(404, "笔记不存在")
    if n.get("fmt") == "ink":
        raise HTTPException(400, "白板（手写）笔记不支持 PDF 导出，请在网页内导出 PNG 图片")
    pandoc = _pandoc()
    if not pandoc:
        raise HTTPException(503, "pandoc 未安装：conda install -n site -c conda-forge pandoc")
    tiny = _tinytex_bin()
    if not (tiny / "xelatex").is_file():
        raise HTTPException(503, "未找到 TinyTeX 的 xelatex（预期 ~/.TinyTeX/bin/x86_64-linux/xelatex）")

    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"note-{note_id}-{uuid.uuid4().hex[:6]}"
    src = config.TMP_DIR / f"{stem}.md"
    out = config.TMP_DIR / f"{stem}.pdf"
    env = {**os.environ, "PATH": f"{Path(pandoc).parent}:{tiny}:{os.environ.get('PATH', '')}"}
    images_to_clean: list[Path] = []
    try:
        # 标题仅用于 PDF 封面元数据（title 过长/含换行需清理）
        title = re.sub(r"\s+", " ", n["title"]).strip()[:120]
        # 站内引用 [文字](/notes/id) 在 PDF 中转为纯文字（链接无法点击，只留可读的标题文字）
        body = re.sub(r"\[([^\[\]]*)\]\(/notes/[^)\s]+\)", r"\1", n["content"] or "")
        # 站内图片 /api/notes/images/<name> → 解密写成本地临时文件（pandoc 需真实文件才能渲染进 PDF）
        for m in re.finditer(r"/api/notes/images/([0-9a-f]{12}\.(?:jpg|jpeg|png|webp|gif))", body):
            name = m.group(1)
            p = IMAGES_DIR / name
            if not p.is_file():
                continue
            local = config.TMP_DIR / f"{stem}-{name}"
            if not local.is_file():
                local.write_bytes(vault.read_bytes(p))
                images_to_clean.append(local)
            body = body.replace(m.group(0), str(local))
        src.write_text(body, encoding="utf-8")
        cmd = [
            pandoc, str(src), "-o", str(out),
            "--pdf-engine=xelatex",
            "-f", "markdown+tex_math_dollars-raw_tex",  # 关掉原始 TeX 透传，防 \input 读任意文件
            "-V", "lang=zh-CN",
            "-V", f"CJKmainfont=Noto Serif CJK SC",
            "-V", "geometry:margin=2.5cm",
            "-V", "fontsize=12pt",
            "--highlight-style", "tango",
            "--metadata", f"title={title}",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180, env=env)
        if proc.returncode != 0 or not out.is_file():
            err = (proc.stderr or b"").decode("utf-8", "replace")
            print(f"[export_pdf] pandoc 失败 rc={proc.returncode}：{err[-800:]}", flush=True)
            raise HTTPException(500, "PDF 渲染失败，请稍后重试（首次编译较慢）")
        return Response(content=out.read_bytes(), media_type="application/pdf")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "PDF 渲染超时（180s），请稍后重试")
    finally:
        for p in (src, out):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        for p in images_to_clean:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
