"""时光机：把博客/笔记与日记聚合成时间轴（都从加密源读取，需登录解锁）。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends

from .. import config, vault
from ..auth import get_current
from .notes import _list_all as _notes_all
from .settings import _load as _load_settings

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

DIARY_DIR = config.DATA_DIR / "diary"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_RE = re.compile(r"^(\d{4})")


def _diary_meta() -> list[dict]:
    out = []
    for p in DIARY_DIR.glob("*.md"):
        if not DATE_RE.match(p.stem):
            continue
        try:
            raw = vault.read_text(p)
        except Exception:
            continue
        meta = {}
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        content = raw
        if m:
            try:
                import yaml
                meta = yaml.safe_load(m.group(1)) or {}
            except Exception:
                meta = {}
            content = m.group(2)
        if content.strip():
            out.append({"date": p.stem, "mood": meta.get("mood", ""),
                        "updated": meta.get("updated", "")})
    return out


@router.get("")
def timeline(_user: dict = Depends(get_current)):
    items = []
    for n in _notes_all():
        if n.get("module") or n.get("parent"):  # 模块子页 / 笔记内子页 不进时光机
            continue
        items.append({
            "date": (n.get("created") or n.get("updated") or "")[:10],
            "kind": "note", "title": n.get("title", "（无标题）"),
            "ref": n.get("id", ""), "sub": n.get("type", "note"),
            "tag": n.get("tags", [])[:3],
        })
    for d in _diary_meta():
        items.append({
            "date": d["date"], "kind": "diary", "title": "日记",
            "ref": d["date"], "sub": d.get("mood", ""), "tag": [],
        })
    # 申请里程碑（个人主页 me.milestones，时间以年份开头的纳入对应年份）
    ms = (_load_settings().get("me.milestones") or [])
    for m in ms:
        time_s = str(m.get("time", ""))
        if not m.get("title") or not YEAR_RE.match(time_s):
            continue
        year = YEAR_RE.match(time_s).group(1)
        items.append({
            "date": f"{year}-01-01", "kind": "milestone", "title": m.get("title"),
            "ref": "", "sub": time_s, "tag": [], "done": bool(m.get("done")),
        })
    items = [x for x in items if x["date"] and len(x["date"]) == 10]
    items.sort(key=lambda x: x["date"], reverse=True)
    return {"items": items}
