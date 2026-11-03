"""项目文档源（`/api/fs`）：把 CODE_ROOT 白名单内的项目目录挂成「文档源」，在站内浏览 /
搜索 / 阅读 / 编辑这些 md —— **文件留在原处**（明文、git 管、agent 直接可读），网站只是
它的一个视图 + 可选编辑器，从根上避免「博客一份、项目一份」两份文档分叉。

设计要点
- 只挂 md（`.md/.markdown`）：其它格式一律不挂，读写都拒绝。
- 唯一真相在项目目录里；站内的笔记（AES 加密那一套）不受影响，两者互不写入对方。
- 源配置存 settings 表 key=`doc_sources`（JSON），不新增表、不做迁移。
- 删除源只删配置，**绝不碰磁盘上的任何文件**。

安全边界（与 P1/P2 审计同一姿势）
- 所有路径 `resolve()` 后必须落在 `CODE_ROOT` 内、且落在该源 root 内（symlink 逃逸一并兜住）；
- 噪声/隐藏目录（.git、node_modules、data、tmp…）任何深度都跳过，除非 include 规则显式点名；
- 单文件读写 ≤1MB、目录每层 ≤200 项、搜索命中 ≤50 且扫描数封顶；
- 写回只在用户点击保存时发生：`base_sha256` 不匹配 → 409（绝不静默覆盖 agent 的改动），
  同目录临时文件 + `os.replace` 原子替换、权限沿用原文件、拒绝写符号链接；
- 本模块不做任何删除/移动文件的操作，外部源也不进 share 快照（分享页永远拿不到这里的内容）。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import config
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/fs", tags=["docsources"])

SETTINGS_KEY = "doc_sources"
MAX_NAME = 40
MAX_RULES = 20
MAX_RULE_LEN = 200
COUNT_TTL = 60          # 源内 md 篇数缓存 60 秒（页面刷新不重复全盘扫）
_DISCOVER_BUDGET = 2.5  # discover 总时长预算（秒），超时返回已发现的部分

_IMAGE_EXT = tuple(config.DOC_IMG_EXT.keys())
_count_cache: dict[str, tuple[float, int, bool]] = {}


# ---------- 基础工具 ----------

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ts(st: os.stat_result) -> str:
    return datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def is_doc(name: str) -> bool:
    return name.lower().endswith(config.DOC_EXTS)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _root() -> Path:
    return config.CODE_ROOT.resolve()


# ---------- 源配置（settings 表 KV，不建表） ----------

def _load_sources() -> list[dict]:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
    if not row:
        return []
    try:
        data = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for s in data:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
            out.append({
                "id": s["id"],
                "name": str(s.get("name") or ""),
                "root": str(s.get("root") or ""),
                "include": [str(x) for x in (s.get("include") or []) if isinstance(x, (str, int))],
                "readonly": bool(s.get("readonly")),
            })
    return out


def _save_sources(items: list[dict]) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SETTINGS_KEY, json.dumps(items, ensure_ascii=False)),
        )


def _get_source(sid: str) -> dict:
    for s in _load_sources():
        if s["id"] == sid:
            return s
    raise HTTPException(404, "文档源不存在（可能已被移除）")


def _norm_root(raw: str) -> tuple[str, Path]:
    """规范源根目录 → (相对 CODE_ROOT 的路径, 绝对 Path)；越界/不存在一律拒绝。"""
    root = _root()
    txt = (raw or "").strip()
    # 空串 / "." = CODE_ROOT 本身（允许把整个工作区当一个源来看）
    p = Path(txt) if txt not in ("", ".") else root
    cand = p if p.is_absolute() else root / p
    try:
        rp = cand.resolve()
    except OSError:
        raise HTTPException(400, "路径无法解析")
    if rp != root and root not in rp.parents:
        raise HTTPException(400, f"只能挂载 {root} 之内的目录")
    if not rp.is_dir():
        raise HTTPException(400, "目录不存在或不是目录")
    rel = "" if rp == root else rp.relative_to(root).as_posix()
    return rel, rp


def _norm_rel(raw: str) -> str:
    """相对路径规范化：拒绝 `..` 段，容忍漏写/多写的斜杠。"""
    s = (raw or "").replace("\\", "/").strip()
    parts = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise HTTPException(400, "非法路径")
        parts.append(seg)
    return "/".join(parts)


def _hidden_ok(target: str, patterns: list[str]) -> bool:
    """hidden/噪声目录是否被 include 规则显式放行（放行才允许进入）。"""
    t = target.strip("/")
    for pat in patterns:
        p = pat.strip().lstrip("./").rstrip("/")
        if not p:
            continue
        if p == t or p.startswith(t + "/"):
            return True
    return False


def _safe(sid: str, rel: str) -> tuple[dict, Path, str]:
    """(源, 绝对路径, 相对路径)：把源 + 相对路径解析成真实路径，并做全部越界校验。"""
    src = _get_source(sid)
    _, src_root = _norm_root(src["root"])          # 每次重新校验：配置被改/目录被删也兜住
    relp = _norm_rel(rel)
    patterns = src.get("include") or []
    parts = relp.split("/") if relp else []
    for i, seg in enumerate(parts):
        if seg in config.DOC_HIDE_DIRS or seg.startswith("."):
            if not _hidden_ok("/".join(parts[: i + 1]), patterns):
                raise HTTPException(403, "该目录不在挂载范围内")
    p = src_root.joinpath(*parts) if parts else src_root
    try:
        rp = p.resolve()
    except OSError:
        raise HTTPException(400, "路径无法解析")
    if rp != src_root and src_root not in rp.parents:
        raise HTTPException(403, "路径越界（符号链接指向了源外）")
    return src, rp, relp


# ---------- include 规则 ----------

def _included(rel: str, patterns: list[str]) -> bool:
    """include 规则命中判定：规则为空 = 全挂；支持精确名、目录前缀、glob。"""
    if not patterns:
        return True
    rel = rel.lstrip("./")
    for pat in patterns:
        p = pat.strip().lstrip("./").rstrip("/")
        if not p:
            continue
        if rel == p or rel.startswith(p + "/") or fnmatch.fnmatch(rel, p):
            return True
    return False


# ---------- 扫描 ----------

def _subdirs(d: Path, patterns: list[str], relprefix: str) -> list[Path]:
    out = []
    try:
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return out
    for e in entries:
        if e.name.startswith(".") or e.name in config.DOC_HIDE_DIRS:
            if not _hidden_ok(f"{relprefix}{e.name}", patterns):
                continue
        try:
            if e.is_dir(follow_symlinks=False):
                out.append(Path(e.path))
        except OSError:
            continue
    return out


def _walk_md(root: Path, patterns: list[str], max_depth: int, budget: int,
             deadline: float | None = None):
    """按源规则遍历 root 下的 md，产出 (Path, 相对路径)。name-only，不读文件内容。

    deadline（monotonic 时刻，可选）用于给 discover 这类"先探一探"的调用兜底超时。
    """
    stack: list[tuple[Path, str, int]] = [(root, "", 0)]
    seen = 0
    checked = 0
    while stack:
        d, relprefix, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in entries:
            checked += 1
            if deadline and checked % 256 == 0 and time.monotonic() > deadline:
                return
            if e.name.startswith(".") or e.name in config.DOC_HIDE_DIRS:
                if not _hidden_ok(f"{relprefix}{e.name}", patterns):
                    continue
            crel = f"{relprefix}{e.name}"
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth + 1 <= max_depth:
                        stack.append((Path(e.path), crel + "/", depth + 1))
                    continue
                if not is_doc(e.name) or not _included(crel, patterns):
                    continue
            except OSError:
                continue
            seen += 1
            if seen > budget:
                return
            yield Path(e.path), crel


def _count_md(root: Path, patterns: list[str], deadline: float | None = None) -> tuple[int, bool]:
    """源内 md 篇数（带 60s 缓存）：返回 (篇数, 是否被上限/超时截断)。"""
    key = f"{root}|{','.join(patterns)}"
    hit = _count_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < COUNT_TTL:
        return hit[1], hit[2]
    cap = config.DOC_SEARCH_SCAN_MAX
    n = 0
    for _ in _walk_md(root, patterns, config.DOC_SCAN_MAX_DEPTH, cap + 1, deadline):
        n += 1
    timed_out = bool(deadline and time.monotonic() > deadline)
    truncated = n > cap or timed_out
    if n > cap:
        n = cap
    if not timed_out:                    # 超时得到的只是一部分，不写缓存
        _count_cache[key] = (now, n, truncated)
    return n, truncated


# ---------- 标题/标签（frontmatter 优先，其次首个 # 标题，最后文件名） ----------

_FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)


def _meta_of(text: str, stem: str) -> dict:
    title, tags, summary = "", [], ""
    fm: dict = {}
    m = _FM_RE.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            fm = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            fm = {}
    if fm:
        t = fm.get("title") or fm.get("name")
        if isinstance(t, str):
            title = t.strip()
        tg = fm.get("tags") or fm.get("keywords")
        if isinstance(tg, str):
            tags = [x.strip() for x in re.split(r"[,，;；]", tg) if x.strip()]
        elif isinstance(tg, list):
            tags = [str(x).strip() for x in tg if str(x).strip()]
        sm = fm.get("summary") or fm.get("description")
        if isinstance(sm, str):
            summary = sm.strip()
    body = text[m.end():] if m else text
    if not title:
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            h = re.match(r"^#{1,3}\s+(.+?)\s*#*$", s)
            if h:
                title = h.group(1).strip()
            break
    if not title:
        title = stem
    return {"title": title[:200], "tags": tags[:12], "summary": summary[:300]}


def _peek_title(p: Path) -> str:
    """只读文件头 4KB 取标题（列目录时用，避免整文件读取）。"""
    try:
        with p.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return p.stem
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        text = head.decode("utf-8", errors="ignore")
        if "\ufffd" in text[:64]:       # 开头就是乱码＝大概率二进制/密文
            return p.stem
    return _meta_of(text, p.stem)["title"]


def _read_text(p: Path) -> str:
    st = p.stat()
    if st.st_size > config.DOC_MAX_BYTES:
        raise HTTPException(413, f"文件超过 {config.DOC_MAX_BYTES // 1024}KB 上限，站内不打开")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "不是 UTF-8 文本（可能是加密/二进制文件），已拒绝读取")
    except OSError:
        raise HTTPException(400, "文件读取失败")


# ---------- 源管理 ----------

class SourceIn(BaseModel):
    name: str = ""
    root: str = ""
    include: list[str] = []
    readonly: bool = False


def _clean_rules(rules: list[str]) -> list[str]:
    out = []
    for r in rules[:MAX_RULES]:
        s = str(r).strip()
        if not s:
            continue
        if len(s) > MAX_RULE_LEN:
            raise HTTPException(400, f"include 规则过长（≤{MAX_RULE_LEN} 字）")
        out.append(s)
    return out


def _view(src: dict) -> dict:
    out = dict(src)
    try:
        rel, rp = _norm_root(src["root"])
        out["root"] = rel
        out["exists"] = True
        n, cut = _count_md(rp, src.get("include") or [])
        out["md_count"] = n
        out["md_count_truncated"] = cut
    except HTTPException:
        out["exists"] = False
        out["md_count"] = 0
        out["md_count_truncated"] = False
    return out


@router.get("/sources")
def list_sources(_user: dict = Depends(get_current)):
    """已挂载的文档源 + 每个源里的 md 篇数（篇数带 60 秒缓存）。"""
    root = _root()
    return {"root": str(root), "items": [_view(s) for s in _load_sources()]}


@router.post("/sources", status_code=201)
def add_source(body: SourceIn, _user: dict = Depends(get_current)):
    """挂载一个项目目录为文档源（只写配置，不复制、不改动任何文件）。"""
    rel, _rp = _norm_root(body.root)
    items = _load_sources()
    if any(s["root"] == rel for s in items):
        raise HTTPException(409, "这个目录已经挂载过了")
    name = (body.name or "").strip()[:MAX_NAME] or (rel.split("/")[-1] or str(_root().name))
    item = {"id": secrets.token_hex(4), "name": name, "root": rel,
            "include": _clean_rules(body.include), "readonly": bool(body.readonly)}
    items.append(item)
    _save_sources(items)
    return _view(item)


@router.put("/sources/{sid}")
def update_source(sid: str, body: SourceIn, _user: dict = Depends(get_current)):
    items = _load_sources()
    cur = next((s for s in items if s["id"] == sid), None)
    if cur is None:
        raise HTTPException(404, "文档源不存在")
    rel, _rp = _norm_root(body.root or cur["root"])
    if any(s["root"] == rel and s["id"] != sid for s in items):
        raise HTTPException(409, "这个目录已经挂载过了")
    cur["name"] = (body.name or "").strip()[:MAX_NAME] or (rel.split("/")[-1] or "文档源")
    cur["root"] = rel
    cur["include"] = _clean_rules(body.include)
    cur["readonly"] = bool(body.readonly)
    _save_sources(items)
    return _view(cur)


@router.delete("/sources/{sid}")
def remove_source(sid: str, _user: dict = Depends(get_current)):
    """移除文档源：**只删这条配置，磁盘上的文件一个都不动**。"""
    items = _load_sources()
    left = [s for s in items if s["id"] != sid]
    if len(left) == len(items):
        raise HTTPException(404, "文档源不存在")
    _save_sources(left)
    return {"ok": True, "removed": sid, "note": "只移除了挂载配置，项目里的文件没有任何改动"}


@router.get("/discover")
def discover(_user: dict = Depends(get_current)):
    """列出 CODE_ROOT 下「看起来像项目」的候选目录（只列不写，勾选后由用户显式添加）。"""
    root = _root()
    items = _load_sources()
    added = {s["root"] for s in items}
    deadline = time.monotonic() + _DISCOVER_BUDGET
    out: list[dict] = []
    truncated = False

    def scan(d: Path, rel: str, depth: int) -> None:
        nonlocal truncated
        if len(out) >= 40 or time.monotonic() > deadline:
            truncated = True
            return
        has_git = (d / ".git").exists()
        n, cut = _count_md(d, [], deadline)
        if n == 0 and not has_git:
            return
        out.append({"root": rel, "name": d.name, "md_count": n,
                    "md_count_truncated": cut, "has_git": has_git, "added": rel in added})
        if depth >= 2:
            return
        for sub in _subdirs(d, [], rel + "/"):
            if time.monotonic() > deadline:
                truncated = True
                return
            scan(sub, f"{rel}/{sub.name}", depth + 1)

    for top in _subdirs(root, [], ""):
        if time.monotonic() > deadline:
            truncated = True
            break
        scan(top, top.name, 1)
    out.sort(key=lambda x: (-x["md_count"], x["root"]))
    return {"root": str(root), "items": out, "truncated": truncated}


# ---------- 目录树 / 文件 ----------

@router.get("/tree")
def tree(sid: str, path: str = "", _user: dict = Depends(get_current)):
    """某一层的目录 + md 文件（懒加载：前端按需逐层拉，不一次枚举整棵树）。"""
    _src, d, relp = _safe(sid, path)
    if not d.is_dir():
        raise HTTPException(400, "不是目录")
    src = _get_source(sid)
    patterns = src.get("include") or []
    dirs: list[dict] = []
    files: list[dict] = []
    truncated = False
    try:
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        raise HTTPException(400, "目录无法读取")
    for e in entries:
        crel = f"{relp}/{e.name}" if relp else e.name
        if e.name.startswith(".") or e.name in config.DOC_HIDE_DIRS:
            if not _hidden_ok(crel, patterns):
                continue
        try:
            if e.is_dir(follow_symlinks=False):
                dirs.append({"name": e.name, "path": crel})
                continue
            if not is_doc(e.name) or not _included(crel, patterns):
                continue
            st = e.stat()
        except OSError:
            continue
        files.append({"name": e.name, "path": crel, "size": st.st_size,
                      "mtime": _ts(st), "title": _peek_title(Path(e.path))})
        if len(files) + len(dirs) >= config.DOC_LIST_MAX:
            truncated = True
            break
    return {"path": relp, "dirs": dirs, "files": files, "truncated": truncated,
            "source": {"id": src["id"], "name": src["name"], "readonly": src["readonly"]}}


@router.get("/file")
def read_file(sid: str, path: str, _user: dict = Depends(get_current)):
    """读一篇 md（≤1MB）：正文 + 元信息（标题/标签/摘要/sha256，sha256 用于保存时比对冲突）。"""
    src, p, relp = _safe(sid, path)
    if p.is_dir() or not p.is_file():
        raise HTTPException(404, "文件不存在")
    if not is_doc(p.name):
        raise HTTPException(400, "只支持 md 文档")
    if not _included(relp, src.get("include") or []):
        raise HTTPException(403, "该文件不在挂载范围内")
    text = _read_text(p)
    st = p.stat()
    return {
        "sid": src["id"], "path": relp, "name": p.name,
        "size": st.st_size, "mtime": _ts(st),
        "sha256": _sha256(p.read_bytes()),
        "content": text,
        "meta": _meta_of(text, p.stem),
        "source": {"id": src["id"], "name": src["name"], "root": src["root"],
                   "readonly": src["readonly"]},
    }


class SaveIn(BaseModel):
    sid: str
    path: str
    content: str
    base_sha256: str


@router.put("/file")
def save_file(body: SaveIn, _user: dict = Depends(get_current)):
    """原子写回原文件。`base_sha256` 必须等于当前内容哈希，否则 409（不静默覆盖）。"""
    src, p, relp = _safe(body.sid, body.path)
    if src.get("readonly"):
        raise HTTPException(403, "这个文档源被标记为只读，如需编辑请先在「管理源」里取消只读")
    if p.is_dir() or not p.is_file():
        raise HTTPException(404, "文件不存在（本功能只编辑已存在的文件）")
    if not is_doc(p.name):
        raise HTTPException(400, "只支持 md 文档")
    if not _included(relp, src.get("include") or []):
        raise HTTPException(403, "该文件不在挂载范围内")
    if p.is_symlink():
        raise HTTPException(400, "拒绝写入符号链接文件")
    raw = body.content.encode("utf-8")
    if len(raw) > config.DOC_MAX_BYTES:
        raise HTTPException(413, f"内容超过 {config.DOC_MAX_BYTES // 1024}KB 上限")
    if not body.base_sha256:
        raise HTTPException(400, "缺少 base_sha256（保存前请重新加载文件）")
    try:
        cur = _sha256(p.read_bytes())
    except OSError:
        raise HTTPException(400, "文件读取失败")
    if cur != body.base_sha256:
        st = p.stat()
        raise HTTPException(409, detail={
            "message": "文件已被其它程序（如 agent / 编辑器）改动，本次保存未执行",
            "current_sha256": cur, "current_mtime": _ts(st),
        })
    tmp = p.parent / f".{p.name}.krswrite-{secrets.token_hex(4)}"
    try:
        with tmp.open("wb") as f:
            f.write(raw)
        os.chmod(tmp, p.stat().st_mode & 0o777)   # 权限沿用原文件
        os.replace(tmp, p)                        # 同目录原子替换
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(400, "写入失败（磁盘权限或空间不足）")
    st = p.stat()
    return {"path": relp, "size": st.st_size, "mtime": _ts(st), "sha256": _sha256(raw)}


@router.get("/blob")
def blob(sid: str, path: str, _user: dict = Depends(get_current)):
    """md 内嵌图片的只读通道（<img> 带不了鉴权头，前端取 blob 后换 objectURL）。"""
    _src, p, _rel = _safe(sid, path)
    ext = p.suffix.lower().lstrip(".")
    if ext not in config.DOC_IMG_EXT:
        raise HTTPException(400, "只支持 png/jpg/gif/webp/bmp/avif 图片")
    if p.is_dir() or not p.is_file():
        raise HTTPException(404, "文件不存在")
    if p.stat().st_size > config.DOC_IMG_MAX_BYTES:
        raise HTTPException(413, "图片超过 20MB 上限")
    return Response(content=p.read_bytes(), media_type=config.DOC_IMG_EXT[ext],
                    headers={"Cache-Control": "private, max-age=60"})


# ---------- 搜索 ----------

@router.get("/search")
def search(q: str, sid: str = "", _user: dict = Depends(get_current)):
    """跨源（或指定源）搜文件名 + 正文；命中上限 50、扫描数封顶，返回是否被截断。"""
    kw = (q or "").strip().lower()
    if len(kw) < 1:
        return {"items": [], "scanned": 0, "truncated": False}
    srcs = [_get_source(sid)] if sid else _load_sources()
    hits: list[dict] = []
    scanned = 0
    truncated = False
    for src in srcs:
        try:
            _, src_root = _norm_root(src["root"])
        except HTTPException:
            continue
        patterns = src.get("include") or []
        for p, relp in _walk_md(src_root, patterns, config.DOC_SCAN_MAX_DEPTH,
                                config.DOC_SEARCH_SCAN_MAX):
            scanned += 1
            if scanned > config.DOC_SEARCH_SCAN_MAX:
                truncated = True
                break
            name_hit = kw in relp.lower()
            excerpt = ""
            title = p.stem
            try:
                text = _read_text(p)
            except HTTPException:
                continue
            meta = _meta_of(text, p.stem)
            title = meta["title"]
            body_hit = kw in text.lower()
            if not (name_hit or body_hit or kw in title.lower()):
                continue
            if body_hit:
                i = text.lower().find(kw)
                excerpt = re.sub(r"\s+", " ", text[max(0, i - 40): i + 80]).strip()
            try:
                st = p.stat()
            except OSError:
                continue
            hits.append({"sid": src["id"], "source": src["name"], "path": relp,
                         "name": p.name, "title": title, "excerpt": excerpt,
                         "mtime": _ts(st)})
            if len(hits) >= config.DOC_SEARCH_MAX:
                truncated = True
                break
        if len(hits) >= config.DOC_SEARCH_MAX or scanned > config.DOC_SEARCH_SCAN_MAX:
            truncated = True
            break
    hits.sort(key=lambda h: h["mtime"], reverse=True)
    return {"items": hits, "scanned": scanned, "truncated": truncated}