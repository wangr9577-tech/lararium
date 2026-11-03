"""附件与图片资产管理器路由：孤立附件体检与安全清理 (Asset Garbage Collector)。

借鉴 Blossom 资产追踪与安全垃圾回收能力：
- 扫描 uploads / album / images 下的所有文件（图片、PDF、附件等）；
- 解密读取 notes / diary / daynote / workbench / cards / ideas 所有文档，精准交叉比对引用关系；
- 统计总存储占用、总文件数、孤立未引用文件列表、被引用文件及关联文档；
- 提供一键清理与多选清理，支持移动到回收站 (data/trash) 或物理删除；
- 具备严格的 Bearer Token 与 DEK 数据解锁鉴权守卫。
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current
from ..crypto import MAGIC
from ..db import db

logger = logging.getLogger("assets")

router = APIRouter(prefix="/api/assets", tags=["assets"])

# 允许扫描与管理的资产目录
ASSET_SUBDIRS = ["uploads", "album", "images"]
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "svg", "bmp", "ico", "avif"}


def _format_bytes(num: int) -> str:
    """字节大小人性化展示格式化。"""
    n = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def _get_allowed_roots() -> list[Path]:
    roots = []
    for sub in ASSET_SUBDIRS:
        p = config.DATA_DIR / sub
        p.mkdir(parents=True, exist_ok=True)
        roots.append(p.resolve())
    return roots


def _validate_safe_path(rel_or_abs: str | Path) -> Path:
    """检验并解析安全路径，严防穿越到 uploads/album/images 以外的目录。"""
    clean = str(rel_or_abs).strip().replace("\\", "/").lstrip("/")
    target = (config.DATA_DIR / clean).resolve()
    if not target.is_file():
        raise HTTPException(404, f"文件不存在: {clean}")

    allowed = False
    for root in _get_allowed_roots():
        try:
            target.relative_to(root)
            allowed = True
            break
        except ValueError:
            pass

    if not allowed:
        raise HTTPException(403, "禁止操作非资产目录文件")

    if target.name.startswith(("_", ".")):
        raise HTTPException(403, "禁止操作系统元数据或受保护文件")

    return target


def _collect_documents() -> list[dict[str, Any]]:
    """读取并解密所有正文文档（笔记、白板、日记、随手记、工作台思考/小记/收集、卡片、想法）。"""
    docs: list[dict[str, Any]] = []

    # 1. 笔记与白板 (data/notes/*.md)
    notes_dir = config.DATA_DIR / "notes"
    if notes_dir.is_dir():
        for p in notes_dir.glob("*.md"):
            try:
                raw = vault.read_text(p)
            except Exception as e:
                logger.warning("解密笔记 %s 失败: %s", p.name, e)
                continue

            title = p.stem
            fmt = "md"
            m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
            if m:
                try:
                    meta = yaml.safe_load(m.group(1)) or {}
                    title = meta.get("title") or title
                    fmt = meta.get("fmt", "md")
                except Exception:
                    pass

            docs.append({
                "title": title,
                "type": "白板" if fmt == "ink" else "笔记",
                "path": f"notes/{p.name}",
                "content": raw,
            })

    # 2. 日记 (data/diary/*.md)
    diary_dir = config.DATA_DIR / "diary"
    if diary_dir.is_dir():
        for p in diary_dir.glob("*.md"):
            try:
                raw = vault.read_text(p)
            except Exception as e:
                logger.warning("解密日记 %s 失败: %s", p.name, e)
                continue

            docs.append({
                "title": f"日记 ({p.stem})",
                "type": "日记",
                "path": f"diary/{p.name}",
                "content": raw,
            })

    # 3. 随手记 (data/daynote/note.md)
    daynote_path = config.DATA_DIR / "daynote" / "note.md"
    if daynote_path.is_file():
        try:
            raw = vault.read_text(daynote_path)
            docs.append({
                "title": "今日安排随手记",
                "type": "随手记",
                "path": "daynote/note.md",
                "content": raw,
            })
        except Exception as e:
            logger.warning("解密随手记失败: %s", e)

    # 4. 工作台小记与思考 (data/workbench)
    wb_dir = config.DATA_DIR / "workbench"
    if wb_dir.is_dir():
        wb_items: dict[int, str] = {}
        wb_entries: dict[int, str] = {}
        wb_captures: dict[int, str] = {}
        try:
            with db() as conn:
                wb_items = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM workbench_items")}
                wb_entries = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM workbench_entries")}
                wb_captures = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM workbench_captures")}
        except Exception as e:
            logger.warning("查询工作台数据库元信息失败: %s", e)

        for p in wb_dir.rglob("*.md"):
            try:
                raw = vault.read_text(p)
            except Exception as e:
                logger.warning("解密工作台文档 %s 失败: %s", p, e)
                continue

            rel = p.relative_to(wb_dir).as_posix()
            m_th = re.match(r"^items/(\d+)/thinking\.md$", rel)
            m_ent = re.match(r"^items/(\d+)/entries/(\d+)\.md$", rel)
            m_cap = re.match(r"^captures/(\d+)\.md$", rel)

            if m_th:
                iid = int(m_th.group(1))
                t = wb_items.get(iid)
                title = f"工作台思路: {t}" if t else f"工作台事项 #{iid} 思路"
                doc_type = "工作台思路"
            elif m_ent:
                eid = int(m_ent.group(2))
                t = wb_entries.get(eid)
                title = f"工作台小记: {t}" if t else f"工作台小记 #{eid}"
                doc_type = "工作台小记"
            elif m_cap:
                cid = int(m_cap.group(1))
                t = wb_captures.get(cid)
                title = f"收集箱: {t}" if t else f"收集箱 #{cid}"
                doc_type = "工作台收集"
            else:
                title = f"工作台: {p.name}"
                doc_type = "工作台"

            docs.append({
                "title": title,
                "type": doc_type,
                "path": f"workbench/{rel}",
                "content": raw,
            })

    # 5. 卡片库 (data/cards/*.md)
    cards_dir = config.DATA_DIR / "cards"
    if cards_dir.is_dir():
        cards_titles: dict[str, str] = {}
        try:
            with db() as conn:
                cards_titles = {str(r["id"]): r["title"] for r in conn.execute("SELECT id, title FROM cards")}
        except Exception:
            pass

        for p in cards_dir.glob("*.md"):
            try:
                raw = vault.read_text(p)
            except Exception as e:
                logger.warning("解密卡片 %s 失败: %s", p.name, e)
                continue
            t = cards_titles.get(p.stem)
            title = f"卡片: {t}" if t else f"卡片 #{p.stem}"
            docs.append({
                "title": title,
                "type": "卡片",
                "path": f"cards/{p.name}",
                "content": raw,
            })

    # 6. 想法库 (data/ideas/*.md)
    ideas_dir = config.DATA_DIR / "ideas"
    if ideas_dir.is_dir():
        ideas_titles: dict[str, str] = {}
        try:
            with db() as conn:
                ideas_titles = {str(r["id"]): r["title"] for r in conn.execute("SELECT id, title FROM ideas")}
        except Exception:
            pass

        for p in ideas_dir.glob("*.md"):
            try:
                raw = vault.read_text(p)
            except Exception as e:
                logger.warning("解密想法 %s 失败: %s", p.name, e)
                continue
            t = ideas_titles.get(p.stem)
            title = f"想法: {t}" if t else f"想法 #{p.stem}"
            docs.append({
                "title": title,
                "type": "想法",
                "path": f"ideas/{p.name}",
                "content": raw,
            })

    return docs


def _collect_album_metadata() -> dict[tuple[str, str], str]:
    """读取相册索引，返回 (album_id, photo_id) -> album_name 的引用映射。"""
    album_dir = config.DATA_DIR / "album"
    photo_map: dict[tuple[str, str], str] = {}
    if not album_dir.is_dir():
        return photo_map

    album_names: dict[str, str] = {}
    idx_path = album_dir / "_index.json"
    if idx_path.is_file():
        try:
            idx_data = vault.read_json(idx_path)
            for alb in idx_data.get("albums", []):
                album_names[alb["id"]] = alb.get("name") or "未命名相册"
        except Exception as e:
            logger.warning("读取相册 _index.json 失败: %s", e)

    for adir in album_dir.iterdir():
        if adir.is_dir() and not adir.name.startswith(("_", ".")):
            pjson = adir / "_photos.json"
            if pjson.is_file():
                try:
                    pdata = vault.read_json(pjson)
                    aname = album_names.get(adir.name, f"相册 {adir.name}")
                    for item in pdata.get("items", []):
                        pid = item.get("id")
                        if pid:
                            photo_map[(adir.name, pid)] = aname
                except Exception as e:
                    logger.warning("读取相册照片清单 %s 失败: %s", pjson, e)

    return photo_map


def _scan_all_assets() -> dict[str, Any]:
    """执行全面体检扫描，核算引用关系并生成报告。"""
    # 强制验证 DEK 解锁状态，未解锁抛 423
    vault.dek()

    # 1. 解密汇总所有文档
    docs = _collect_documents()
    album_refs = _collect_album_metadata()

    # 2. 遍历 uploads, album, images 目录下的实际物理文件
    all_files: list[dict[str, Any]] = []

    for sub in ASSET_SUBDIRS:
        folder = config.DATA_DIR / sub
        if not folder.is_dir():
            continue

        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            # 过滤相册/系统元数据文件
            if p.name.startswith(("_", ".")):
                continue

            rel_posix = p.relative_to(config.DATA_DIR).as_posix()
            filename = p.name
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            stat = p.stat()
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            is_image = ext in IMAGE_EXTENSIONS

            mime, _ = mimetypes.guess_type(filename)
            if not mime:
                mime = f"image/{ext}" if is_image else "application/octet-stream"

            quoted_filename = urllib.parse.quote(filename)
            quoted_rel = urllib.parse.quote(rel_posix)

            # 3. 计算文档引用
            references: list[dict[str, str]] = []
            seen_doc_paths: set[str] = set()

            # 相册系统自身的照片记录引用
            if sub == "album":
                # 路径结构为 album/<aid>/<pid>.<ext>
                parts = rel_posix.split("/")
                if len(parts) >= 3:
                    aid = parts[1]
                    pid = parts[2].rsplit(".", 1)[0]
                    if (aid, pid) in album_refs:
                        aname = album_refs[(aid, pid)]
                        doc_key = f"album/{aid}"
                        seen_doc_paths.add(doc_key)
                        references.append({
                            "title": f"相册: {aname}",
                            "type": "相册",
                            "path": doc_key,
                        })

            # 正文文档匹配检查：支持纯文件名、相对路径、URL 编码、接口形式 (/api/notes/images/..., /api/fs/raw/...)
            for doc in docs:
                if doc["path"] in seen_doc_paths:
                    continue
                content = doc["content"]
                # 检查文件名、相对路径或 URL 编码是否包含在正文中
                if (filename in content or
                    rel_posix in content or
                    quoted_filename in content or
                    quoted_rel in content or
                    f"images/{filename}" in content or
                    f"uploads/{filename}" in content):
                    seen_doc_paths.add(doc["path"])
                    references.append({
                        "title": doc["title"],
                        "type": doc["type"],
                        "path": doc["path"],
                    })

            all_files.append({
                "filename": filename,
                "path": rel_posix,
                "category": sub,
                "size": size,
                "size_human": _format_bytes(size),
                "mtime": mtime,
                "is_image": is_image,
                "mime_type": mime,
                "preview_url": f"/api/assets/file?path={urllib.parse.quote(rel_posix)}",
                "ref_count": len(references),
                "references": references,
            })

    total_files = len(all_files)
    total_bytes = sum(f["size"] for f in all_files)

    unreferenced_files = [f for f in all_files if f["ref_count"] == 0]
    referenced_files = [f for f in all_files if f["ref_count"] > 0]

    unreferenced_count = len(unreferenced_files)
    unreferenced_bytes = sum(f["size"] for f in unreferenced_files)

    # 排序：未引用文件默认按占用体积从大到小排列，方便清理最耗空间的大文件
    unreferenced_files.sort(key=lambda x: x["size"], reverse=True)
    referenced_files.sort(key=lambda x: x["ref_count"], reverse=True)

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_human": _format_bytes(total_bytes),
        "unreferenced_count": unreferenced_count,
        "unreferenced_bytes": unreferenced_bytes,
        "unreferenced_size_human": _format_bytes(unreferenced_bytes),
        "unreferenced_files": unreferenced_files,
        "referenced_files": referenced_files,
    }


class CleanIn(BaseModel):
    filenames: list[str] = Field(default_factory=list, description="要清理的文件名或相对路径列表")
    paths: list[str] = Field(default_factory=list, description="要清理的相对路径列表")
    all_unreferenced: bool = Field(default=False, description="是否一键清理所有未引用的孤立文件")
    permanent: bool = Field(default=False, description="是否物理永久删除（默认 False 移入回收站）")


# ---------- 接口定义 ----------

@router.get("/scan")
def scan_assets(_user: dict = Depends(get_current)):
    """扫描 uploads/album/images 下所有资产，返回体检报告与孤立未引用文件清单。"""
    return _scan_all_assets()


@router.post("/clean")
def clean_assets(body: CleanIn, _user: dict = Depends(get_current)):
    """清理指定的未引用文件或一键清理全部孤立文件。默认安全移入回收站 (data/trash)。"""
    vault.dek()  # 鉴权守卫

    scan_res = _scan_all_assets()
    unref_dict = {f["path"]: f for f in scan_res["unreferenced_files"]}
    unref_by_name: dict[str, list[dict[str, Any]]] = {}
    for f in scan_res["unreferenced_files"]:
        unref_by_name.setdefault(f["filename"], []).append(f)

    target_paths: set[str] = set()

    if body.all_unreferenced:
        target_paths = set(unref_dict.keys())
    else:
        # 合并 filenames 与 paths 传参
        req_items = set(body.paths) | set(body.filenames)
        for item in req_items:
            clean_item = item.strip().replace("\\", "/").lstrip("/")
            if clean_item in unref_dict:
                target_paths.add(clean_item)
            elif clean_item in unref_by_name:
                for match in unref_by_name[clean_item]:
                    target_paths.add(match["path"])
            else:
                logger.warning("请求清理的文件 %s 未在孤立附件列表中，跳过处理以防误删引用文件", clean_item)

    if not target_paths:
        return {
            "ok": True,
            "cleaned_count": 0,
            "freed_bytes": 0,
            "freed_size_human": "0 B",
            "trash_id": None,
            "cleaned_files": [],
        }

    items_to_clean: list[Path] = []
    freed_bytes = 0
    cleaned_rel_paths: list[str] = []

    for rel in target_paths:
        try:
            target = _validate_safe_path(rel)
            stat = target.stat()
            freed_bytes += stat.st_size
            items_to_clean.append(target)
            cleaned_rel_paths.append(rel)
        except Exception as e:
            logger.warning("准备清理文件 %s 遇到异常: %s", rel, e)

    tid: str | None = None
    if body.permanent:
        # 物理彻底删除
        for p in items_to_clean:
            try:
                p.unlink()
            except OSError as e:
                logger.error("物理删除文件 %s 失败: %s", p, e)
    else:
        # 安全移入回收站 (支持从回收站一键复原)
        label = f"清理孤立附件 ({len(items_to_clean)} 个文件)"
        tid = trashbin.move_to_trash(items_to_clean, module="assets", label=label)

    return {
        "ok": True,
        "cleaned_count": len(cleaned_rel_paths),
        "freed_bytes": freed_bytes,
        "freed_size_human": _format_bytes(freed_bytes),
        "trash_id": tid,
        "cleaned_files": cleaned_rel_paths,
    }


@router.get("/file")
def get_asset_file(
    path: str = Query(..., min_length=1, description="相对 DATA_DIR 的资产文件路径"),
    download: bool = Query(default=False, description="是否作为附件下载"),
    _user: dict = Depends(get_current),
):
    """安全读取/预览资产文件。若文件经 AES-GCM 加密落盘，则通过 vault 解密后返回明文。"""
    vault.dek()  # 鉴权守卫
    target = _validate_safe_path(path)

    raw_bytes = target.read_bytes()
    # 如果文件是 Kruskal 加密格式 (MAGIC 开头)，解密为明文返回
    if raw_bytes.startswith(MAGIC):
        try:
            content_bytes = vault.read_bytes(target)
        except Exception as e:
            raise HTTPException(500, f"文件解密失败: {e}")
    else:
        content_bytes = raw_bytes

    ext = target.name.rsplit(".", 1)[-1].lower() if "." in target.name else ""
    mime, _ = mimetypes.guess_type(target.name)
    if not mime:
        mime = f"image/{ext}" if ext in IMAGE_EXTENSIONS else "application/octet-stream"

    headers = {}
    if download:
        safe_name = urllib.parse.quote(target.name)
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{safe_name}"

    return Response(content=content_bytes, media_type=mime, headers=headers)
