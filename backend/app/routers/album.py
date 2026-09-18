"""相册：分组管理；原图 AES-GCM 加密落盘（vault 字节读写）。

data/album/<albumId>/ 目录
  _photos.json   加密：照片元数据列表
  <photoId>.<ext>  加密：原图
索引 data/album/_index.json（加密）{albums:[{id,name,note,created}]}
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current

router = APIRouter(prefix="/api/album", tags=["album"])

ALBUM_DIR = config.DATA_DIR / "album"
INDEX_PATH = ALBUM_DIR / "_index.json"
ID_RE = re.compile(r"^[0-9a-f]{8,12}$")
PHOTO_ID_RE = re.compile(r"^[0-9a-f]{8}$")
EXT_OK = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
          "webp": "image/webp", "gif": "image/gif"}
MAX_PHOTO = 20 * 1024 * 1024


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _index() -> dict:
    if INDEX_PATH.is_file():
        try:
            return vault.read_json(INDEX_PATH)
        except Exception as exc:
            # 读失败绝不静默当空表——否则下一次写回即抹掉全部相册记录（原图成孤儿目录）
            raise HTTPException(
                503, "相册索引读取失败（数据未解锁或文件损坏），已阻止写入以防丢失相册记录，请重新登录后重试") from exc
    return {"albums": []}


def _save_index(data: dict) -> None:
    ALBUM_DIR.mkdir(parents=True, exist_ok=True)
    vault.write_json(INDEX_PATH, data)


def _album_dir(aid: str) -> Path:
    return ALBUM_DIR / aid


def _photos_path(aid: str) -> Path:
    return _album_dir(aid) / "_photos.json"


def _load_photos(aid: str) -> list[dict]:
    p = _photos_path(aid)
    if p.is_file():
        try:
            return vault.read_json(p).get("items", [])
        except Exception:
            return []
    return []


def _save_photos(aid: str, items: list[dict]) -> None:
    _album_dir(aid).mkdir(parents=True, exist_ok=True)
    vault.write_json(_photos_path(aid), {"items": items})


def _album_meta(alb: dict) -> dict:
    return {**alb, "count": len(_load_photos(alb["id"]))}


class AlbumIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=200)


@router.get("")
def list_albums(_user: dict = Depends(get_current)):
    data = _index()
    albums = [_album_meta(a) for a in data.get("albums", [])]
    albums.sort(key=lambda x: x.get("created", ""), reverse=True)
    return {"albums": albums}


@router.post("", status_code=201)
def create_album(body: AlbumIn, _user: dict = Depends(get_current)):
    data = _index()
    aid = uuid.uuid4().hex[:12]
    alb = {"id": aid, "name": body.name.strip(), "note": body.note.strip(), "created": _now()}
    data.setdefault("albums", []).append(alb)
    _save_index(data)
    _save_photos(aid, [])
    return _album_meta(alb)


@router.put("/{album_id}")
def update_album(album_id: str, body: AlbumIn, _user: dict = Depends(get_current)):
    if not ID_RE.match(album_id):
        raise HTTPException(404, "相册不存在")
    data = _index()
    for a in data.get("albums", []):
        if a["id"] == album_id:
            a["name"] = body.name.strip()
            a["note"] = body.note.strip()
            _save_index(data)
            return _album_meta(a)
    raise HTTPException(404, "相册不存在")


@router.delete("/{album_id}")
def delete_album(album_id: str, _user: dict = Depends(get_current)):
    if not ID_RE.match(album_id):
        raise HTTPException(404, "相册不存在")
    data = _index()
    orig_list = list(data.get("albums", []))
    alb = next((a for a in orig_list if a["id"] == album_id), None)
    if alb is None:
        raise HTTPException(404, "相册不存在")
    data["albums"] = [a for a in orig_list if a["id"] != album_id]
    _save_index(data)
    d = _album_dir(album_id)
    tid = None
    if d.is_dir():
        # 整个相册目录（原图 + _photos.json）移入回收站，可整册恢复
        try:
            tid = trashbin.move_to_trash([d], module="album", label=alb.get("name") or "相册")
        except Exception:
            data["albums"] = orig_list  # 移动失败则整表回滚，相册与顺序保持原样
            _save_index(data)
            raise
    return {"ok": True, "trash_id": tid}


@router.get("/{album_id}")
def get_album(album_id: str, _user: dict = Depends(get_current)):
    if not ID_RE.match(album_id):
        raise HTTPException(404, "相册不存在")
    data = _index()
    alb = next((a for a in data.get("albums", []) if a["id"] == album_id), None)
    if alb is None:
        raise HTTPException(404, "相册不存在")
    photos = sorted(_load_photos(album_id), key=lambda x: x.get("added", ""), reverse=True)
    for ph in photos:
        p = _album_dir(album_id) / f"{ph['id']}.{ph['ext']}"
        ph["size"] = p.stat().st_size if p.is_file() else 0
    return {"album": _album_meta(alb), "photos": photos}


@router.post("/{album_id}/photos", status_code=201)
async def upload_photos(album_id: str, files: list[UploadFile] = File(...),
                        _user: dict = Depends(get_current)):
    if not ID_RE.match(album_id):
        raise HTTPException(404, "相册不存在")
    data = _index()
    if not any(a["id"] == album_id for a in data.get("albums", [])):
        raise HTTPException(404, "相册不存在")
    if len(files) > 30:
        raise HTTPException(400, "一次最多上传 30 张")
    items = _load_photos(album_id)
    added = []
    for f in files:
        name = (f.filename or "").lower()
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in EXT_OK:
            raise HTTPException(400, f"{f.filename} 不是支持的图片（jpg/png/webp/gif）")
        raw = await f.read()
        if len(raw) > MAX_PHOTO:
            raise HTTPException(400, f"{f.filename} 超过 20MB")
        pid = uuid.uuid4().hex[:8]
        vault.write_bytes(_album_dir(album_id) / f"{pid}.{ext}", raw)
        items.append({"id": pid, "ext": ext, "added": _now()})
        added.append({"id": pid, "ext": ext, "added": items[-1]["added"]})
    _save_photos(album_id, items)
    return {"added": added}


@router.get("/{album_id}/photos/{photo_id}/file")
def photo_file(album_id: str, photo_id: str, _user: dict = Depends(get_current)):
    if not (ID_RE.match(album_id) and PHOTO_ID_RE.match(photo_id)):
        raise HTTPException(404, "照片不存在")
    items = {p["id"]: p for p in _load_photos(album_id)}
    meta = items.get(photo_id)
    if meta is None:
        raise HTTPException(404, "照片不存在")
    p = _album_dir(album_id) / f"{photo_id}.{meta['ext']}"
    if not p.is_file():
        raise HTTPException(404, "照片不存在")
    return Response(content=vault.read_bytes(p), media_type=EXT_OK.get(meta["ext"], "application/octet-stream"))


@router.delete("/{album_id}/photos/{photo_id}")
def delete_photo(album_id: str, photo_id: str, _user: dict = Depends(get_current)):
    if not (ID_RE.match(album_id) and PHOTO_ID_RE.match(photo_id)):
        raise HTTPException(404, "照片不存在")
    items = _load_photos(album_id)
    items = [p for p in items if p["id"] != photo_id]
    _save_photos(album_id, items)
    p = _album_dir(album_id) / f"{photo_id}.*"
    for f in _album_dir(album_id).glob(f"{photo_id}.*"):
        try:
            f.unlink()
        except OSError:
            pass
    return {"ok": True}
