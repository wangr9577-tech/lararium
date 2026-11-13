"""只读分享：把笔记/个人主页渲染为独立 HTML 快照对外发布。

设计：正文加密（DEK 在启动解锁后驻内存），因此"公开副本"在分享时刻由站长生成
快照保存（明文 html，即显式公开的内容），公开链接免登录直接访问；撤销 = 删除快照。

存储：
  data/share/<token>.html      快照（公开副本）
  data/share/_map.json         加密映射：token -> {target, ref, title, created, updated}
"""
from __future__ import annotations

import base64
import html
import json
import re
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import config, vault
from ..auth import get_current
from .notes import IMAGES_DIR, IMG_EXT, _load as _load_note
from .settings import _load as _load_settings

router = APIRouter(tags=["share"])

SHARE_DIR = config.DATA_DIR / "share"
MAP_PATH = SHARE_DIR / "_map.json"
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

_PAGE_CSS = """
:root{--bg:#f6f7fb;--ink:#26303c;--sub:#5b6b7f;--line:#e5e8f0;--acc:#8b5cf6;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif;line-height:1.9}
.wrap{max-width:820px;margin:0 auto;padding:34px 22px 60px}
.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:30px 38px;box-shadow:0 10px 30px rgba(60,50,120,.06)}
h1{font-size:26px;margin:0 0 8px}
.meta{color:var(--sub);font-size:13px;margin-bottom:16px}
.lead{color:var(--sub);border-left:4px solid var(--acc);background:#f5f1ff;padding:8px 14px;border-radius:0 10px 10px 0;margin-bottom:16px}
h2{font-size:20px;margin:1.4em 0 .5em;padding-left:10px;border-left:4px solid var(--acc)}
h3{font-size:17px;margin:1.1em 0 .4em}
table{border-collapse:collapse;margin:.8em 0}
th,td{border:1px solid var(--line);padding:6px 14px}
th{background:#f4f2ff}
code{background:#f1f3f8;padding:1px 7px;border-radius:6px;font-family:Consolas,monospace;font-size:.92em}
pre{background:#141a2c;color:#e8edf7;padding:14px 18px;border-radius:12px;overflow-x:auto}
pre code{background:none;color:inherit;padding:0}
blockquote{margin:.6em 0;padding:6px 16px;color:var(--sub);border-left:4px solid #38bdf8;background:#f0f9ff;border-radius:0 10px 10px 0}
a{color:var(--acc)}
img{max-width:100%;border-radius:10px}
hr{border:none;border-top:2px dashed var(--line);margin:1.4em 0}
.tag{display:inline-block;font-size:12px;color:var(--acc);background:#f2ecff;border:1px solid #e3d9ff;padding:1px 10px;border-radius:999px;margin:0 6px 6px 0}
.note{color:#8b97a8;font-size:12px;margin-top:20px}
/* 主页 */
.name{font-size:24px;font-weight:800}
.pos{color:var(--acc);margin:2px 0 14px}
.field-line{margin:4px 0;font-size:15px}
.fk{color:var(--sub);display:inline-block;min-width:74px}
.bio{color:var(--sub);margin-top:8px;font-size:14.5px}
h4{font-size:16px;margin:22px 0 6px;color:#3c4a5e}
.honor{display:inline-block;background:#f2ecff;border:1px solid #e0d5ff;border-radius:999px;padding:2px 14px;margin:4px 6px 0 0;font-size:13.5px}
.pub{border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:8px 0}
.pub .t{font-weight:700}
.pub .s{color:var(--sub);font-size:13.5px;margin-top:2px}
.badge{font-size:12px;background:var(--acc);color:#fff;border-radius:6px;padding:0 8px;margin-left:6px}
.mline{position:relative;padding:0 0 14px 22px;border-left:2px solid #dcd6ff;margin-left:6px}
.mline:last-child{border-left-color:transparent}
.mtime{color:var(--acc);font-weight:600}
.mtitle{font-weight:600}
.mdone .mtitle{text-decoration:line-through;color:#9aa7b8}
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _map() -> dict:
    if MAP_PATH.is_file():
        try:
            return vault.read_json(MAP_PATH)
        except Exception as exc:
            # 读失败绝不静默当空表——否则下一次写回即丢掉全部分享记录（快照成孤儿且无法撤销）
            raise HTTPException(
                503, "分享索引读取失败（数据未解锁或文件损坏），已阻止写入以防丢失分享记录，请重启本机服务后重试") from exc
    return {}


def _save_map(m: dict) -> None:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    vault.write_json(MAP_PATH, m)


def _pandoc() -> str | None:
    from ..external_tools import pandoc
    return pandoc()


def _md_to_html(md_text: str) -> str:
    pandoc = _pandoc()
    if not pandoc:
        return "<pre>" + html.escape(md_text) + "</pre>"
    src = config.TMP_DIR / f"share-{secrets.token_hex(4)}.md"
    try:
        src.write_text(md_text or "", encoding="utf-8")
        proc = subprocess.run([pandoc, str(src), "-f", "markdown+tex_math_dollars-raw_tex-raw_html", "-t", "html5"],
                              capture_output=True, timeout=90)
        body = proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""
        if not body.strip():
            body = "<pre>" + html.escape(md_text or "") + "</pre>"
        return body
    except Exception:
        return "<pre>" + html.escape(md_text or "") + "</pre>"
    finally:
        try:
            src.unlink(missing_ok=True)
        except OSError:
            pass


def _embed_notes_images(html_body: str) -> str:
    """快照是显式公开副本：把站内图片 /api/notes/images/<name> 内嵌为 base64 data URI，
    收图人免登录也能看到图片（无需开放图片读取接口，不泄露其它未分享内容）。"""
    def _repl(m: re.Match) -> str:
        name = m.group(0).rsplit("/", 1)[-1]
        p = IMAGES_DIR / name
        if not p.is_file():
            return m.group(0)  # 图片缺失（已被清理等）：保留原样
        try:
            b64 = base64.b64encode(vault.read_bytes(p)).decode("ascii")
        except Exception:
            return m.group(0)
        ext = name.rsplit(".", 1)[-1]
        return f"data:{IMG_EXT.get(ext, 'application/octet-stream')};base64,{b64}"

    return re.sub(r"/api/notes/images/[0-9a-f]{12}\.(?:jpg|jpeg|png|webp|gif)", _repl, html_body)


def _page(title: str, inner: str) -> str:
    e = html.escape
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/><title>{e(title)}</title>
<style>{_PAGE_CSS}</style></head><body><div class="wrap"><div class="card">
{inner}
<div class="note">由站长通过个人站分享 · 内容快照</div>
</div></div></body></html>"""


def _note_snapshot(note: dict) -> str:
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in note.get("tags", []))
    lead = f'<div class="lead">{html.escape(note.get("summary", "") or "")}</div>' if note.get("summary") else ""
    body = _embed_notes_images(_md_to_html(note.get("content", "")))
    return _page(
        note["title"],
        f"<h1>{html.escape(note['title'])}</h1>"
        f'<div class="meta">分类：{note.get("type", "")} · 更新于 {html.escape(note.get("updated", ""))}{tags}</div>'
        f"{lead}{body}",
    )


def _me_snapshot(cfg: dict) -> str:
    p = cfg.get("me.profile") or {}
    f = lambda v: html.escape(str(v or ""))
    fields = []
    for lab, key in (("学校", "school"), ("专业", "major"), ("年级", "grade")):
        if p.get(key):
            fields.append(f'<div class="field-line"><span class="fk">{lab}</span>{f(p.get(key))}</div>')
    inner = f'<div class="name">{f(p.get("name"))}</div>'
    if p.get("tagline"):
        inner += f'<div class="pos">{f(p.get("tagline"))}</div>'
    inner += "".join(fields)
    if p.get("bio"):
        inner += f'<div class="bio">{f(p.get("bio"))}</div>'

    honors = cfg.get("me.honors") or []
    if honors:
        inner += "<h4>荣誉 / 奖项</h4>" + "".join(
            f'<span class="honor">{html.escape(str(h.get("year", "")))} {html.escape(str(h.get("title", "")))}</span>'
            for h in honors if h.get("title"))
    pubs = cfg.get("me.publications") or []
    if pubs:
        inner += "<h4>论文 / 学术成果</h4>"
        for pb in pubs:
            if not pb.get("title"):
                continue
            badge = f'<span class="badge">{html.escape(str(pb.get("status", "")))}</span>' if pb.get("status") else ""
            inner += ('<div class="pub"><div class="t">' + html.escape(str(pb["title"])) + badge + "</div>"
                      + (f'<div class="s">{html.escape(str(pb.get("venue", "")))} · {html.escape(str(pb.get("year", "")))}</div>' if pb.get("venue") or pb.get("year") else "")
                      + (f'<div class="s">{html.escape(str(pb.get("note", "")))}</div>' if pb.get("note") else "")
                      + "</div>")
    ms = cfg.get("me.milestones") or []
    if ms:
        inner += "<h4>重要里程碑</h4><div style='margin-top:8px'>"
        for m in ms:
            if not m.get("title"):
                continue
            inner += f'<div class="mline {"mdone" if m.get("done") else ""}">' \
                     f'<div class="mtime">{html.escape(str(m.get("time", "")))}</div>' \
                     f'<div class="mtitle">{html.escape(str(m.get("title", "")))}</div>' \
                     + (f'<div class="s">{html.escape(str(m.get("note", "")))}</div>' if m.get("note") else "") + "</div>"
        inner += "</div>"
    return _page(f"{p.get('name') or '个人主页'} · 主页分享", inner)


class ShareIn(BaseModel):
    target: str = Field(pattern="^(note|me)$")
    ref: str = Field(default="")


def _find_existing(m: dict, target: str, ref: str) -> str | None:
    for tok, v in m.items():
        if v.get("target") == target and v.get("ref") == ref:
            return tok
    return None


@router.post("/api/share")
def create_share(body: ShareIn, _user: dict = Depends(get_current)):
    if body.target == "note":
        if not body.ref:
            raise HTTPException(400, "缺少笔记 id")
        note = _load_note(body.ref)
        if note is None:
            raise HTTPException(404, "笔记不存在")
        if note.get("fmt") == "ink":
            raise HTTPException(400, "白板（手写）笔记暂不支持对外分享")
        snapshot = _note_snapshot(note)
        title = note["title"]
    else:
        cfg = _load_settings()
        snapshot = _me_snapshot(cfg)
        p = cfg.get("me.profile") or {}
        title = str(p.get("name") or "个人主页")

    m = _map()
    tok = _find_existing(m, body.target, body.ref)
    if tok is None:
        tok = secrets.token_hex(16)
        m[tok] = {"target": body.target, "ref": body.ref, "title": title, "created": _now(), "updated": _now()}
    else:
        m[tok]["updated"] = _now()
        m[tok]["title"] = title
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    vault.atomic_write_bytes(SHARE_DIR / f"{tok}.html", snapshot.encode("utf-8"))
    _save_map(m)
    return {"token": tok, "url": f"/share/{tok}", "target": body.target, "ref": body.ref,
            "title": title, "created": m[tok]["created"], "updated": m[tok]["updated"]}


@router.get("/api/share")
def list_shares(_user: dict = Depends(get_current)):
    m = _map()
    items = [{"token": tok, **v, "url": f"/share/{tok}"} for tok, v in m.items()]
    items.sort(key=lambda x: x.get("created", ""), reverse=True)
    return {"items": items}


@router.delete("/api/share/{token}")
def revoke_share(token: str, _user: dict = Depends(get_current)):
    if not TOKEN_RE.match(token):
        raise HTTPException(404, "分享不存在")
    # 先删快照文件、后删索引：即使中途失败，最坏是"文件没了但索引残留"，
    # 公开访问仍 404（无文件），且用户在 UI 还能再点一次撤销（幂等）。
    # 反之若先删索引，删文件失败会留下"索引已删但公开页仍可访问"的撤销不彻底。
    p = SHARE_DIR / f"{token}.html"
    if p.is_file():
        try:
            p.unlink()
        except OSError as exc:
            raise HTTPException(500, "撤销失败：快照文件删除出错，请重试") from exc
    m = _map()
    m.pop(token, None)
    _save_map(m)
    return {"ok": True}


@router.get("/share/{token}")
def public_share(token: str):
    """公开只读页：免登录返回快照 HTML。"""
    if not TOKEN_RE.match(token):
        raise HTTPException(404, "分享不存在")
    p = SHARE_DIR / f"{token}.html"
    if not p.is_file():
        raise HTTPException(404, "分享不存在或已撤销")
    return FileResponse(p, media_type="text/html; charset=utf-8")
