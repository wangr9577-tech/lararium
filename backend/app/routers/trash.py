"""回收站 API：查看 / 恢复 / 永久删除（均需登录）。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException

from .. import trashbin
from ..auth import get_current

router = APIRouter(prefix="/api/trash", tags=["trash"])

_ALBUM_ID_RE = re.compile(r"^[0-9a-f]{8,12}$")


@router.get("")
def list_trash(_user: dict = Depends(get_current)):
    return {"items": trashbin.list_items()}


@router.post("/{tid}/restore")
def restore(tid: str, _user: dict = Depends(get_current)):
    result = trashbin.restore(tid)
    if result.get("module") == "album":
        # 相册的列表条目存在 _index.json 里：文件恢复回磁盘后，还要把条目补回索引才会重新可见
        from .album import ALBUM_DIR, _album_dir, _index, _save_index
        aid = ""
        for rel in result.get("rels", []):
            if rel.startswith("album/") and rel.count("/") == 1:
                aid = rel.split("/", 1)[1]
        if aid and _ALBUM_ID_RE.match(aid) and _album_dir(aid).is_dir():
            data = _index()
            if not any(a.get("id") == aid for a in data.get("albums", [])):
                data.setdefault("albums", []).insert(0, {
                    "id": aid, "name": result.get("label") or "恢复的相册",
                    "note": "", "created": result.get("deleted_at", ""),
                })
                _save_index(data)
                result["album_relisted"] = True
    elif result.get("module") == "assistant":
        from ..db import db
        for rel in result.get("rels", []):
            if rel.startswith("assistant/records/"):
                parts = rel.split("/")
                if len(parts) >= 3 and parts[2].isdigit():
                    rid = int(parts[2])
                    with db() as conn:
                        conn.execute("UPDATE assistant_records SET archived=0 WHERE id=?", (rid,))
    return result


@router.delete("/{tid}")
def purge(tid: str, yes: bool = False, _user: dict = Depends(get_current)):
    """永久删除：必须显式带 ?yes=true，防误调。"""
    if not yes:
        raise HTTPException(400, "永久删除需显式确认（yes=true），此操作不可恢复")
    return trashbin.purge(tid)
