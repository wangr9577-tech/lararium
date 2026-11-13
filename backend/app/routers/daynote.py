"""首页「今日安排」随手记：一份固定的加密 Markdown 小文件。

定位（与既有模块的分工）：
  - 这里是**随手写**：今天的安排、临时想到的事，Markdown 清单，想怎么改就怎么改。
  - **不按天归档、不自动清空、不会每天重置**：内容一直留着，由用户自己维护
    （写了就一直在，什么时候删什么时候改都由用户决定）。
  - 真正要带时间、要勾选、要提醒的，仍然写在「日程表」里（这里不自动同步）。
  - 日记在日程页（data/diary），笔记·博客在 data/notes —— 三者互不影响。

存储：data/daynote/note.md，整篇经 vault 加密落盘（AES-GCM，未解锁不可读）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, vault
from ..auth import get_current

router = APIRouter(prefix="/api/daynote", tags=["daynote"])

DAYNOTE_DIR = config.DATA_DIR / "daynote"
NOTE_PATH = DAYNOTE_DIR / "note.md"
MAX_LEN = 50_000          # 随手记正文上限


class NoteIn(BaseModel):
    # 不设 Pydantic 长度约束：超长交给这里统一出 400 中文文案
    content: str = ""


def _mtime_text() -> str:
    if not NOTE_PATH.is_file():
        return ""
    try:
        return datetime.fromtimestamp(NOTE_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


@router.get("")
def get_daynote(_user: dict = Depends(get_current)):
    """读这份随手记；没写过返回空字符串（不建档）。"""
    content = vault.read_text(NOTE_PATH) if NOTE_PATH.is_file() else ""
    return {"content": content, "updated": _mtime_text()}


@router.put("")
def put_daynote(body: NoteIn, _user: dict = Depends(get_current)):
    """整篇覆盖保存（前端防抖自动保存）。内容不会被自动清空或按天重置。"""
    if len(body.content) > MAX_LEN:
        raise HTTPException(400, f"随手记最长 {MAX_LEN} 字符")
    DAYNOTE_DIR.mkdir(parents=True, exist_ok=True)
    vault.write_text(NOTE_PATH, body.content)
    return {"ok": True, "updated": _mtime_text()}
