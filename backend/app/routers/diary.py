"""日记：每天一个加密 md 文件 data/diary/YYYY-MM-DD.md。

文件结构：
  ---
  mood: 开心        （可空）
  weather: 晴       （可空）
  updated: 2026-09-06 10:00:00
  ---
  正文 Markdown...
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

router = APIRouter(prefix="/api/diary", tags=["diary"])

DIARY_DIR = config.DATA_DIR / "diary"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MOODS = ["", "平静", "开心", "低落", "焦虑", "疲惫", "充实", "其他"]
WEATHERS = ["", "晴", "多云", "阴", "雨", "雪", "雷雨"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(date: str) -> Path:
    return DIARY_DIR / f"{date}.md"


def _split(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw.strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2)


def _dump(date: str, meta: dict, content: str) -> None:
    head = yaml.safe_dump({"mood": meta.get("mood", ""), "weather": meta.get("weather", ""),
                           "updated": meta.get("updated", _now())},
                          allow_unicode=True, sort_keys=False).strip()
    vault.write_text(_path(date), f"---\n{head}\n---\n\n{content or ''}")


class DiaryIn(BaseModel):
    content: str = ""
    mood: str = Field(default="", max_length=20)
    weather: str = Field(default="", max_length=20)


@router.get("/calendar")
def calendar(month: str, _user: dict = Depends(get_current)):
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month 应为 YYYY-MM")
    prefix = month + "-"
    days = sorted(p.stem for p in DIARY_DIR.glob(f"{month}-*.md"))
    return {"month": month, "days": days}


@router.get("/{date}")
def get_diary(date: str, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    p = _path(date)
    if not p.is_file():
        return {"date": date, "mood": "", "weather": "", "content": "", "updated": ""}
    meta, content = _split(vault.read_text(p))
    return {"date": date, "mood": meta.get("mood", ""), "weather": meta.get("weather", ""),
            "content": content.rstrip("\n"), "updated": meta.get("updated", "")}


@router.put("/{date}")
def put_diary(date: str, body: DiaryIn, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")
    if body.mood not in MOODS:
        raise HTTPException(400, f"心情只能是 {[m for m in MOODS if m]}")
    if body.weather not in WEATHERS:
        raise HTTPException(400, f"天气只能是 {[w for w in WEATHERS if w]}")
    _dump(date, {"mood": body.mood, "weather": body.weather, "updated": _now()}, body.content)
    meta, content = _split(vault.read_text(_path(date)))
    return {"date": date, "mood": body.mood, "weather": body.weather,
            "content": body.content, "updated": meta.get("updated", "")}


@router.delete("/{date}")
def delete_diary(date: str, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    p = _path(date)
    tid = None
    if p.is_file():
        # 移入回收站而非物理删（P2-L1）：与笔记/相册/论文一致，误删可恢复
        tid = trashbin.move_to_trash([p], module="diary", label=f"日记 {date}")
    return {"ok": True, "trash_id": tid}
