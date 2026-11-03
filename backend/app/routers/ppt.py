"""PPT 笔记导入：.pptx → 每张幻灯片一张矢量 SVG → 一篇 v2 多页白板笔记。

设计：python-pptx 解析（纯 Python，无 LibreOffice 依赖）；服务器不落盘原始文件，
把每张幻灯片渲染为 SVG（文字/形状/纯色填充/线条/嵌入图片/旋转），作为白板页的
整页底层图；用户随后可在上面手写/荧光笔/插图。只支持新版 .pptx 格式。

已知近似：母版占位符字体继承、SmartArt、图表、渐变/图案填充、形状阴影、艺术字、
动画等不做精细还原（图表/复杂版式建议先导出 PDF）。
"""
from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from ..auth import get_current
from ..upload import read_upload
from . import notes as notes_mod

router = APIRouter(prefix="/api/ppt", tags=["ppt"])

MAX_FILE = 50 * 1024 * 1024
MAX_PAGES = 80
MAX_TOTAL_IMG = 30 * 1024 * 1024   # 渲染后图像/矢量总量上限（防撑爆笔记文件）
PX_PER_EMU = 96 / 914400  # 1 EMU = 1/914400 in，输出按 96dpi
MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff", "webp": "image/webp",
}


def _px(v: int | float | None) -> float:
    if v is None:
        return 0.0
    return float(v) * PX_PER_EMU


def _color_str(color) -> str | None:
    """返回 #rrggbb；主题色/异常返回 None"""
    try:
        rgb = str(color.rgb)
        if re.fullmatch(r"[0-9a-fA-F]{6}", rgb):
            return "#" + rgb.lower()
    except Exception:
        return None
    return None


def _fill_attr(shape, is_line: bool = False) -> dict:
    """取纯色填充/描边；非纯色（无填充/渐变/图片填充）返回空"""
    try:
        f = shape.line if is_line else shape.fill
        if f.type != 1:  # MSO_FILL_TYPE.SOLID == 1（避免额外枚举导入）
            return {}
        c = _color_str(f.fore_color)
        if not c:
            return {}
        return {"color": c}
    except Exception:
        return {}


def _shape_tag(shape, ox: int, oy: int, svg: list[str], skipped: list[str]) -> None:
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE

    try:
        st = shape.shape_type
    except Exception:
        return

    # 组合：子形状坐标相对组合原点
    if st == MSO_SHAPE_TYPE.GROUP:
        try:
            children = shape.shapes
            for ch in children:
                _shape_tag(ch, ox + (shape.left or 0), oy + (shape.top or 0), svg, skipped)
        except Exception:
            pass
        return

    left = _px(shape.left) if shape.left is not None else None
    top = _px(shape.top) if shape.top is not None else None
    width = _px(shape.width) if shape.width is not None else None
    height = _px(shape.height) if shape.height is not None else None
    # 占位符若无显式几何，回退到版式占位符（尽力而为）
    if None in (left, top, width, height):
        try:
            ph = shape.placeholder_format
            for lp in shape.slide_layout.placeholders:
                if lp.placeholder_format.idx == ph.idx and lp.left is not None:
                    left = _px(lp.left); top = _px(lp.top)
                    width = _px(lp.width); height = _px(lp.height)
                    break
        except Exception:
            pass
    if None in (left, top, width, height):
        skipped.append("占位符无几何")
        return
    left += _px(ox)
    top += _px(oy)

    # 图片
    if st == MSO_SHAPE_TYPE.PICTURE:
        try:
            ext = (shape.image.ext or "").lower()
            if ext not in MIME:
                skipped.append(f"图片格式 {ext}")
                return
            b64 = base64.b64encode(shape.image.blob).decode("ascii")
            svg.append(
                f'<image x="{left:.2f}" y="{top:.2f}" width="{width:.2f}" height="{height:.2f}" '
                f'preserveAspectRatio="xMidYMid meet" href="data:{MIME[ext]};base64,{b64}"/>'
            )
        except Exception as e:
            skipped.append(f"图片读取失败:{e}")
        return

    has_text = False
    try:
        has_text = bool(shape.has_text_frame and shape.text_frame.text.strip())
    except Exception:
        has_text = False

    fill = _fill_attr(shape)
    line = _fill_attr(shape, is_line=True)
    if not fill and not line and not has_text:
        # 装饰性空形状
        if st == MSO_SHAPE_TYPE.AUTO_SHAPE and shape.auto_shape_type in (MSO_SHAPE.RECTANGLE, MSO_SHAPE.ROUNDED_RECTANGLE):
            pass
        else:
            return

    inner = ""
    geom_el = ""
    rx = 0.0
    tag = None
    try:
        atype = shape.auto_shape_type
        if atype == MSO_SHAPE.ROUNDED_RECTANGLE:
            tag = "rect"; rx = min(width, height) * 0.15
            geom_el = f'<rect x="{left:.2f}" y="{top:.2f}" width="{width:.2f}" height="{height:.2f}" rx="{rx:.2f}"'
        elif atype == MSO_SHAPE.OVAL:
            tag = "ellipse"
            geom_el = f'<ellipse cx="{left + width / 2:.2f}" cy="{top + height / 2:.2f}" rx="{width / 2:.2f}" ry="{height / 2:.2f}"'
        elif atype == MSO_SHAPE.DIAMOND:
            tag = "poly"
            geom_el = (f'<polygon points="{(left + width / 2):.2f},{top:.2f} {left + width:.2f},{top + height / 2:.2f} '
                       f'{left + width / 2:.2f},{top + height:.2f} {left:.2f},{top + height / 2:.2f}"')
        elif atype in (MSO_SHAPE.ISOCELES_TRIANGLE, MSO_SHAPE.RIGHT_TRIANGLE):
            tag = "poly"
            if atype == MSO_SHAPE.RIGHT_TRIANGLE:
                geom_el = f'<polygon points="{left:.2f},{top:.2f} {left + width:.2f},{top:.2f} {left:.2f},{top + height:.2f}"'
            else:
                geom_el = (f'<polygon points="{left + width / 2:.2f},{top:.2f} {left:.2f},{top + height:.2f} '
                           f'{left + width:.2f},{top + height:.2f}"')
        else:
            tag = "rect"
            geom_el = f'<rect x="{left:.2f}" y="{top:.2f}" width="{width:.2f}" height="{height:.2f}"'
    except Exception:
        tag = "rect"
        geom_el = f'<rect x="{left:.2f}" y="{top:.2f}" width="{width:.2f}" height="{height:.2f}"'

    style = []
    if fill:
        style.append(f"fill:{fill['color']}")
    else:
        style.append("fill:none")
    if line:
        style.append(f"stroke:{line['color']}")
        try:
            wpx = _px(shape.line.width) if shape.line.width is not None else 1.0
            style.append(f"stroke-width:{max(0.5, wpx):.2f}")
        except Exception:
            style.append("stroke-width:1")
    style.append("stroke-linejoin:round")

    rot = ""
    try:
        deg = float(shape.rotation or 0)
        if abs(deg) > 0.05:
            cx = left + width / 2
            cy = top + height / 2
            rot = f' transform="rotate({deg:.2f} {cx:.2f} {cy:.2f})"'
    except Exception:
        pass

    inner = geom_el + f' style="{";".join(style)}"/>'

    # 文字
    text_svg = ""
    if has_text:
        text_svg = _text_svg(shape, left, top, width, height, skipped)

    if text_svg or tag:
        wrap = f'<g{rot}>{inner}{text_svg}</g>'
        svg.append(wrap)


def _text_svg(shape, left: float, top: float, width: float, height: float, skipped: list[str]) -> str:
    from pptx.enum.text import MSO_ANCHOR
    parts: list[str] = []
    try:
        tf = shape.text_frame
        margin_l = _px(tf.margin_left if tf.margin_left is not None else 91440)
        margin_t = _px(tf.margin_top if tf.margin_top is not None else 45720)
        anchor = tf.vertical_anchor if tf.vertical_anchor is not None else MSO_ANCHOR.TOP
    except Exception:
        return ""
    # 计算文本总高做垂直居中（近似：逐段 1.25 行高）
    paras = list(tf.paragraphs)
    if not paras:
        return ""
    line_hs: list[float] = []
    for para in paras:
        if not para.text.strip():
            continue
        size_px = 0.0
        for run in para.runs:
            try:
                if run.font.size is not None:
                    size_px = max(size_px, run.font.size.pt * 4 / 3)
            except Exception:
                pass
        size_px = size_px or 24.0
        line_hs.append(size_px * 1.25)
    total_h = sum(line_hs)
    y_start = top + margin_t
    if anchor == MSO_ANCHOR.MIDDLE:
        y_start = top + max(margin_t, (height - total_h) / 2)
    elif anchor == MSO_ANCHOR.BOTTOM:
        y_start = top + height - margin_t - total_h
    y = y_start
    for para in paras:
        if not para.text.strip():
            y += 14
            continue
        # 取首段有效 run 的样式
        size_pt = 18.0
        bold = False
        italic = False
        col = "#1f2937"
        for run in para.runs:
            try:
                if run.font.size is not None:
                    size_pt = run.font.size.pt
                if run.font.bold is not None and run.font.bold:
                    bold = True
                if run.font.italic is not None and run.font.italic:
                    italic = True
                c = _color_str(run.font.color)
                if c:
                    col = c
            except Exception:
                pass
        size_px = size_pt * 4 / 3
        fw = "bold" if bold else "normal"
        fs = "italic" if italic else "normal"
        valign_bump = size_px * 0.85  # 文字基线近似
        txt = escape(para.text.strip())
        txt = txt.replace("\u000b", "\n")
        parts.append(
            f'<text x="{left + margin_l:.2f}" y="{y + valign_bump:.2f}" font-size="{size_px:.2f}" '
            f'font-weight="{fw}" font-style="{fs}" fill="{col}" '
            f'font-family="Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif">{txt}</text>'
        )
        y += size_px * 1.25
    return "".join(parts)


def _slide_svg(prs, slide) -> tuple[str, int, int]:
    from pptx.enum.dml import MSO_FILL
    w = _px(prs.slide_width)
    h = _px(prs.slide_height)
    parts: list[str] = []
    skipped: list[str] = []
    bg = ""
    try:
        if slide.background.fill.type == MSO_FILL.SOLID:
            c = _color_str(slide.background.fill.fore_color)
            if c:
                bg = f'<rect x="0" y="0" width="{w:.2f}" height="{h:.2f}" fill="{c}"/>'
    except Exception:
        pass
    if not bg:
        bg = f'<rect x="0" y="0" width="{w:.2f}" height="{h:.2f}" fill="#ffffff"/>'
    for shape in slide.shapes:
        _shape_tag(shape, 0, 0, parts, skipped)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.2f} {h:.2f}">{bg}{"".join(parts)}</svg>'
    )
    return svg, max(1, round(w)), max(1, round(h))


def _render_ppt_to_pages(data: bytes) -> list[dict]:
    try:
        from pptx import Presentation
        prs = Presentation(BytesIO(data))
    except Exception as e:
        raise HTTPException(400, f"PPT 解析失败（可能已损坏或含加密）：{str(e)[:120]}")

    total = len(prs.slides._sldIdLst)
    if not total:
        raise HTTPException(400, "PPT 中没有幻灯片")
    if total > MAX_PAGES:
        raise HTTPException(400, f"PPT 共 {total} 页，超过上限 {MAX_PAGES} 页（可拆分后再导入）")

    pages = []
    img_total = 0
    for slide in prs.slides:
        try:
            svg, wpx, hpx = _slide_svg(prs, slide)
        except Exception as e:
            raise HTTPException(500, f"第 {len(pages) + 1} 页转换失败：{str(e)[:120]}")
        raw_svg = svg.encode("utf-8")
        img_total += len(raw_svg)
        if img_total > MAX_TOTAL_IMG:
            raise HTTPException(
                400,
                f"PPT 渲染后矢量/图像超过 {MAX_TOTAL_IMG // (1024 * 1024)}MB 上限，"
                "请减少页数或拆分文档",
            )
        b64 = base64.b64encode(raw_svg).decode("ascii")
        ratio = hpx / wpx
        pages.append({
            "page": {"w": wpx, "h": hpx, "paper": {"style": "plain", "color": "white"}},
            "images": [{"id": f"ppt{len(pages) + 1}", "x": 0, "y": 0, "w": 1, "r": ratio,
                        "src": f"data:image/svg+xml;base64,{b64}"}],
            "strokes": [],
        })
    return pages


@router.post("/import")
async def import_ppt(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form(""),
    _user: dict = Depends(get_current),
):
    name = (file.filename or "").strip()
    if not name.lower().endswith(".pptx"):
        raise HTTPException(400, "仅支持新版 PowerPoint 格式 .pptx（老版 .ppt 不支持，可先在 PowerPoint 另存为 .pptx）")
    data = await read_upload(file, MAX_FILE, request=request, too_big="PPT 文件过大（上限 50MB）")
    if not data:
        raise HTTPException(400, "空文件")

    pages = await run_in_threadpool(_render_ppt_to_pages, data)

    title = re.sub(r"\.pptx$", "", name, flags=re.I).strip() or "PPT 笔记"
    if len(title) > 100:
        title = title[:100]
    folder = notes_mod.clean_folder_path(folder)  # 目录全路径校验（支持子文件夹，如 'A/B'）
    id_ = notes_mod.new_id()
    now = notes_mod.now_iso()
    meta = {
        "title": title, "type": "note", "fmt": "ink", "module": "",
        "folder": folder, "tags": [], "summary": "", "ppt": name, "created": now, "updated": now,
    }
    notes_mod._dump_file(id_, meta, json.dumps({"v": 2, "pages": pages}, ensure_ascii=False))
    return {"id": id_, "pages": len(pages), **{k: meta[k] for k in ("title", "type", "fmt", "module", "folder", "tags", "summary", "ppt", "created", "updated")}}
