"""PDF 笔记导入：.pdf → 每页一张 JPEG 整页底图 → 一篇 v2 多页白板笔记。

设计：PyMuPDF 渲染（纯 Python wheel，服务器无需 poppler/gs/LibreOffice），
服务器不落盘原始 PDF，把每页按固定 DPI 渲染为 JPEG，作为白板页的整页底层图；
用户随后可在上面手写 / 荧光笔 / 插图。与 PPT 导入同构（同样产出 fmt=ink 多页
白板笔记，可直接在页面编辑器里书写）。

已知边界：仅栅格化（无文本层，不能选词/搜索正文）；不保留原始 PDF
（需要原文阅读+划词请用「论文」模块）。
"""
from __future__ import annotations

import base64
import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current
from . import notes as notes_mod

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

MAX_FILE = 50 * 1024 * 1024        # 原始 PDF 上限（同 PPT）
MAX_PAGES = 80                     # 页数上限
MAX_TOTAL_IMG = 30 * 1024 * 1024   # 渲染后图像总量上限（防超大扫描件撑爆笔记文件）
DPI = 120                          # 渲染 DPI（A4 ≈ 1000×1400，单页 JPEG ≈ 200KB）
JPEG_QUALITY = 80


@router.post("/import")
async def import_pdf(
    file: UploadFile = File(...),
    folder: str = Form(""),
    _user: dict = Depends(get_current),
):
    name = (file.filename or "").strip()
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件（.pdf）")
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_FILE:
        raise HTTPException(400, "PDF 文件过大（上限 50MB）")

    try:
        try:
            import pymupdf as fitz  # PyMuPDF ≥1.24 的模块名（1.28 起旧别名 fitz 已弃用）
        except ImportError:  # pragma: no cover - 兼容旧版 PyMuPDF
            import fitz
    except ImportError:
        raise HTTPException(503, "服务器缺少 PDF 渲染依赖：pip install pymupdf")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise HTTPException(400, f"PDF 解析失败（可能已损坏）：{str(e)[:120]}")

    try:
        if doc.needs_pass:
            raise HTTPException(400, "该 PDF 有密码保护，请先解除密码后再导入")
        total = doc.page_count
        if total < 1:
            raise HTTPException(400, "PDF 中没有页面")
        if total > MAX_PAGES:
            raise HTTPException(400, f"PDF 共 {total} 页，超过上限 {MAX_PAGES} 页（可拆分后再导入）")

        pages = []
        img_total = 0
        for i in range(total):
            try:
                pix = doc[i].get_pixmap(dpi=DPI)
                img = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
            except Exception as e:
                raise HTTPException(500, f"第 {i + 1} 页渲染失败：{str(e)[:120]}")
            img_total += len(img)
            if img_total > MAX_TOTAL_IMG:
                raise HTTPException(
                    400,
                    f"PDF 渲染后图像超过 {MAX_TOTAL_IMG // (1024 * 1024)}MB 上限，"
                    "请减少页数或改用图片较少的文档",
                )
            w, h = max(1, pix.width), max(1, pix.height)
            b64 = base64.b64encode(img).decode("ascii")
            pages.append({
                "page": {"w": w, "h": h, "paper": {"style": "plain", "color": "white"}},
                "images": [{"id": f"pdf{i + 1}", "x": 0, "y": 0, "w": 1, "r": h / w,
                            "src": f"data:image/jpeg;base64,{b64}"}],
                "strokes": [],
            })
    finally:
        doc.close()

    title = re.sub(r"\.pdf$", "", name, flags=re.I).strip() or "PDF 笔记"
    if len(title) > 100:
        title = title[:100]
    folder = notes_mod.clean_folder_path(folder)  # 目录全路径校验（支持子文件夹）
    id_ = notes_mod.new_id()
    now = notes_mod.now_iso()
    meta = {
        "title": title, "type": "note", "fmt": "ink", "module": "",
        "folder": folder, "tags": [], "summary": "", "pdf": name, "created": now, "updated": now,
    }
    notes_mod._dump_file(id_, meta, json.dumps({"v": 2, "pages": pages}, ensure_ascii=False))
    return {"id": id_, "pages": len(pages),
            **{k: meta[k] for k in ("title", "type", "fmt", "module", "folder",
                                    "tags", "summary", "pdf", "created", "updated")}}