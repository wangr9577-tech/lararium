"""科研周报（M6）：聚合本周新增卡片/想法/实验 → Markdown，可选调本地 AI 起草。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import config, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _week_range(days: int) -> tuple[str, str]:
    end = datetime.now()
    start = end - timedelta(days=days - 1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


@router.get("/weekly")
def weekly(days: int = 7, _user: dict = Depends(get_current)):
    days = max(1, min(days, 31))
    start, end = _week_range(days)
    items: list[dict] = []
    with db() as conn:
        cards = conn.execute(
            "SELECT id, title FROM cards WHERE created_at>=? AND created_at<=? ORDER BY id",
            (start, end)).fetchall()
        ideas = conn.execute(
            "SELECT id, title, status FROM ideas WHERE created_at>=? AND created_at<=? ORDER BY id",
            (start, end)).fetchall()
        exps = conn.execute(
            "SELECT id, title, status FROM experiments WHERE created_at>=? AND created_at<=? ORDER BY id",
            (start, end)).fetchall()
    for c in cards:
        items.append({"kind": "卡片", "title": c["title"], "id": f"card:{c['id']}"})
    for i in ideas:
        items.append({"kind": "想法", "title": i["title"], "id": f"idea:{i['id']}"})
    for e in exps:
        items.append({"kind": "实验", "title": e["title"], "id": f"exp:{e['id']}"})

    md_lines = [
        f"# 科研周报（{datetime.now().strftime('%Y-%m-%d')} 起最近 {days} 天）",
        "",
        f"- 本周新增卡片 **{len(cards)}** 张",
        f"- 本周新增想法 **{len(ideas)}** 条",
        f"- 本周新增实验 **{len(exps)}** 个",
        "",
    ]
    if items:
        md_lines.append("## 明细")
        for it in items:
            md_lines.append(f"- [{it['kind']}] {it['title']}")
    else:
        md_lines.append("本周暂无新增科研条目。")
    return {
        "days": days,
        "items": items,
        "counts": {"cards": len(cards), "ideas": len(ideas), "experiments": len(exps)},
        "markdown": "\n".join(md_lines),
    }


class ReportSaveIn(BaseModel):
    content: str = Field(min_length=1, max_length=60_000)
    title: str = Field(default="", max_length=120)


@router.post("/save-as-note")
def save_as_note(body: ReportSaveIn, _user: dict = Depends(get_current)):
    """周报落地为笔记（复用 notes 存储：frontmatter type=note）。"""
    import uuid
    from .. import config as _config
    from ..routers.notes import _dump_file

    note_id = uuid.uuid4().hex[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = body.title.strip() or f"科研周报 {datetime.now().strftime('%Y-%m-%d')}"
    _dump_file(note_id, {
        "title": title[:120], "type": "note", "fmt": "md", "tags": ["周报"],
        "created": now, "updated": now,
    }, body.content)
    return {"ok": True, "note_id": note_id, "title": title}