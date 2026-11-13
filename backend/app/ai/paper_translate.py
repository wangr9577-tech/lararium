"""论文中文翻译：PyMuPDF 解析版面 + 本地 LLM 逐块翻译，原位擦除英文并回写中文。

与 PDFMathTranslate 的思路一致——保留公式、图表与分栏坐标，页数/页面尺寸不变，
因此可以和原文 PDF 逐页左右对照。产物加密缓存在 data/papers/trans/：
  <id>.pdf   中文译文 PDF（供右侧栏渲染）
  <id>.json  进度/状态（state/pages/done/blocks/model/updated/error）

设计约束：
- 只在后台线程跑，前端轮询状态；绝不阻塞主功能。
- **上传即翻译**：入库后自动进队列（`start()`），串行消费（本地模型只有一个推理槽位，
  并发只会互相拖慢并撞超时）；服务重启会把没跑完的队列重新排上（`resume_pending()`）。
- 任何 LLM 失败都逐块降级（整批 JSON → 单条纯文本 → 保留原文），绝不伪造成译文。
- 公式字体（CM/MS/Symbol/Mono/Math…）、竖排/旋转文字、作者邮箱行跳过，原文保留。
- 中文回写用 MuPDF Story（insert_htmlbox）：中英混排自动换行、放不下自动缩小，
  排完统一 subset 字体，避免每块内嵌一份 CJK 字体把 PDF 撑到几十 MB。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime

from .. import vault
from . import llm

ENGINE = "pymupdf-llm"
MIN_FONT = 4.0
BATCH_CHARS = 2200          # 单次请求的原文长度上限（固定开销大，批量越大越划算）
BATCH_ITEMS = 12            # 单次请求的条目数上限
MAX_UNIT_CHARS = 1200       # 单个文本单元（块）原文上限，超长按行切分
MAX_PAGES = 200             # 防超大 PDF 撑爆本地模型时间

_SYS_PROMPT = (
    "你是学术论文的专业翻译引擎，面向机器学习/人工智能方向的研究者。"
    "把给出的英文片段翻译成准确、通顺、术语规范的简体中文；"
    "保留公式、变量名、数字、引用编号以及 $...$ 包裹的内容不变；"
    "不要添加解释，不要输出 Markdown 代码块。"
)

_lock = threading.RLock()   # read_status/_alive 会在 start() 持锁时被再次调用 → 必须可重入
_queue: list[tuple[str, bool]] = []   # 待翻译队列（串行消费，避免并发抢本地模型）
_active: set[str] = set()             # 正在翻译的论文
_runner: threading.Thread | None = None
_mem: dict[str, dict] = {}       # 内存进度（比落盘更细，块级更新）
_cancel: set[str] = set()        # 用户点了"取消"的论文（线程在页间检查）


# ---------------------------------------------------------------- 路径/状态

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _trans_dir(create: bool = True):
    """译文目录跟着 papers.PAPERS_DIR 走（config.rebind_data_dir 会重绑该属性）。"""
    from ..routers import papers as papers_mod

    d = papers_mod.PAPERS_DIR / "trans"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def paths(paper_id: str, create: bool = True):
    d = _trans_dir(create=create)
    return d / f"{paper_id}.json", d / f"{paper_id}.pdf"


def _empty_state() -> dict:
    return {
        "state": "none", "engine": ENGINE, "model": "",
        "pages": 0, "done": 0, "blocks": 0, "translated": 0, "failed": 0,
        "started": "", "updated": "", "error": "",
    }


def _queued_ids() -> set[str]:
    """当前排队或在译的论文（持锁调用）。"""
    return set(_active) | {pid for pid, _f in _queue}


def _alive(paper_id: str) -> bool:
    with _lock:
        return paper_id in _active or any(pid == paper_id for pid, _f in _queue)


def read_status(paper_id: str) -> dict:
    """合并磁盘状态与内存进度；进程重启后遗留的 running/queued 视作中断。"""
    meta_path, pdf_path = paths(paper_id)
    st = _empty_state()
    if meta_path.is_file():
        try:
            st.update(vault.read_json(meta_path))
        except Exception:
            pass
    if pdf_path.is_file():
        st["has_pdf"] = True
    else:
        st["has_pdf"] = False
        if st.get("state") == "ready":
            st["state"] = "none"
    with _lock:
        mem = dict(_mem.get(paper_id) or {})
    if mem:
        st.update(mem)
    if st.get("state") in ("running", "queued") and not _alive(paper_id):
        st.update({
            "state": "failed",
            "error": "上次翻译被中断（服务重启或任务异常退出），请重试",
            "updated": _now(),
        })
    return st


def state_of(paper_id: str) -> str:
    """只取状态字符串（列表页用，未翻译时不解密任何文件）。"""
    meta_path, pdf_path = paths(paper_id, create=False)
    with _lock:
        mem_state = str((_mem.get(paper_id) or {}).get("state") or "")
        live = paper_id in _active or any(pid == paper_id for pid, _f in _queue)
    if mem_state in ("running", "queued") and live:
        return mem_state
    if pdf_path.is_file():
        return "ready"
    if not meta_path.is_file():
        return "none"
    try:
        st = vault.read_json(meta_path)
    except Exception:
        return "none"
    state = str(st.get("state") or "none")
    if state in ("running", "queued") and not live:
        return "failed"
    return state


def _save(paper_id: str, st: dict) -> None:
    meta_path, _pdf = paths(paper_id)
    payload = {k: v for k, v in st.items() if k != "has_pdf"}
    try:
        vault.write_json(meta_path, payload)
    except Exception:
        pass


def _set_mem(paper_id: str, **kw) -> None:
    with _lock:
        cur = dict(_mem.get(paper_id) or {})
        cur.update(kw)
        cur["updated"] = _now()
        _mem[paper_id] = cur


def read_pdf(paper_id: str) -> bytes | None:
    _meta, pdf_path = paths(paper_id)
    if not pdf_path.is_file():
        return None
    try:
        return vault.read_bytes(pdf_path)
    except Exception:
        return None


def remove(paper_id: str) -> None:
    """取消在跑的翻译并删除缓存（含状态文件）。"""
    cancel(paper_id)
    meta_path, pdf_path = paths(paper_id)
    for p in (meta_path, pdf_path):
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    with _lock:
        _mem.pop(paper_id, None)


def cancel(paper_id: str) -> None:
    """取消：还在排队就直接出队并清干净；已在译则由页间检查点停下。"""
    with _lock:
        _cancel.add(paper_id)
        before = len(_queue)
        _queue[:] = [(pid, f) for pid, f in _queue if pid != paper_id]
        removed = len(_queue) != before
        active = paper_id in _active
    if removed and not active:
        _finish_cancel(paper_id)


def _is_cancelled(paper_id: str) -> bool:
    with _lock:
        return paper_id in _cancel


def _drop_cancel(paper_id: str) -> None:
    with _lock:
        _cancel.discard(paper_id)
        _mem.pop(paper_id, None)


def _finish_cancel(paper_id: str) -> None:
    """用户取消：有旧译文就保留状态 ready，没有就清掉状态文件（回到 none）。"""
    meta_path, pdf_path = paths(paper_id)
    _drop_cancel(paper_id)
    try:
        if pdf_path.is_file():
            _save(paper_id, {
                "state": "ready", "engine": ENGINE, "model": _model_name(),
                "pages": 0, "done": 0, "blocks": 0, "translated": 0, "failed": 0,
                "started": "", "updated": _now(), "error": "",
            })
        elif meta_path.is_file():
            meta_path.unlink()
    except OSError:
        pass


def start(paper_id: str, force: bool = False) -> dict:
    """把论文排进翻译队列（幂等）：已在队列/在译就复用，已就绪且非 force 直接返回。

    队列是串行的：本地模型只有一个推理槽位，并发只会互相拖慢并撞超时。
    因此上传后批量自动翻译、以及用户手动点「翻译」，都走同一个队列。
    """
    with _lock:
        st = read_status(paper_id)
        state = st.get("state")
        if state in ("queued", "running"):
            return st
        if state == "ready" and not force:
            return st
        if not llm.is_enabled():
            raise RuntimeError("AI 服务未启用：请先在「设置 - AI 服务」里配置并打开模型")
        _cancel.discard(paper_id)
        _queue.append((paper_id, bool(force)))
        _mem[paper_id] = {
            "state": "queued", "engine": ENGINE, "model": _model_name(),
            "pages": st.get("pages", 0), "done": 0, "blocks": 0,
            "translated": 0, "failed": 0, "started": _now(), "updated": _now(),
            "error": "",
        }
        _save(paper_id, dict(_mem[paper_id]))
        _ensure_runner_locked()
    return read_status(paper_id)


def queued_count() -> int:
    with _lock:
        return len(_queue) + len(_active)


def _ensure_runner_locked() -> None:
    """确保后台串行 worker 在跑（持锁调用）。"""
    global _runner
    if _runner is not None and _runner.is_alive():
        return
    _runner = threading.Thread(target=_runner_loop, daemon=True, name="paper-trans-worker")
    _runner.start()


def _runner_loop() -> None:
    global _runner
    while True:
        with _lock:
            if not _queue:
                _runner = None
                return
            paper_id, _force = _queue.pop(0)
            if paper_id in _active:
                continue
            _active.add(paper_id)
            _mem[paper_id] = {
                **_empty_state(), "state": "running", "engine": ENGINE,
                "model": _model_name(), "started": _now(), "updated": _now(),
            }
        try:
            _run(paper_id)
        except Exception:  # noqa: BLE001 - worker 不能因为一篇论文崩掉
            _fail(paper_id, "翻译任务异常退出，请重试")
        finally:
            with _lock:
                _active.discard(paper_id)


def resume_pending() -> int:
    """服务启动时把上次没跑完的（排队/中断）论文重新排队。"""
    n = 0
    d = _trans_dir(create=False)
    if not d.is_dir():
        return 0
    for meta_path in sorted(d.glob("*.json")):
        try:
            st = vault.read_json(meta_path)
        except Exception:
            continue
        if str(st.get("state")) in ("queued", "running"):
            try:
                start(meta_path.stem)
                n += 1
            except Exception:
                pass
    return n


def _model_name() -> str:
    try:
        _, _, _ = llm.get_profiles_and_active()
        return str(llm._cfg().get("model") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------- 后台任务

def _run(paper_id: str) -> None:
    try:
        src = _read_source(paper_id)
        zh = translate_pdf(src, paper_id=paper_id)
        meta_path, pdf_path = paths(paper_id)
        vault.write_bytes(pdf_path, zh)
        st = read_status(paper_id)
        st.update({"state": "ready", "updated": _now(), "error": "", "done": st.get("pages", 0)})
        _save(paper_id, st)
        with _lock:
            _mem.pop(paper_id, None)
    except llm.AiUnavailable as e:
        if _is_cancelled(paper_id):
            _finish_cancel(paper_id)
            return
        _fail(paper_id, f"AI 调用失败：{e}")
    except Exception as e:  # noqa: BLE001 - 后台任务必须吞掉异常并落状态
        if _is_cancelled(paper_id):
            _finish_cancel(paper_id)
            return
        _fail(paper_id, f"翻译失败：{e}")


def _fail(paper_id: str, msg: str) -> None:
    st = read_status(paper_id)
    st.update({"state": "failed", "error": msg[:300], "updated": _now()})
    _set_mem(paper_id, state="failed", error=msg[:300])
    _save(paper_id, st)


def _read_source(paper_id: str) -> bytes:
    from ..routers import papers as papers_mod

    p = papers_mod._pdf_path(paper_id)
    if not p.is_file():
        raise FileNotFoundError("论文文件不存在")
    return vault.read_bytes(p)


# ---------------------------------------------------------------- 版面解析

_MATH_FONT_RE = re.compile(
    r"(cm[a-z]|msam|msbm|stmary|wasy|eufm|rsfs|txsy|cmsy|cmex|cmr\d|"
    r"symbol|wingding|math|mono|code|courier|consolas|"
    r"italic|oblique|times-?new-?roman.*(math|sym))",
    re.I,
)
_MATH_CHARS = set("=+−-<>≤≥≈≠∑∏∫√±×÷∈∉∀∃∂∇∞→←↔⇒⇔⊂⊃∪∩αβγδεζηθλμνξπρστφχψωΓΔΘΛΞΠΣΦΨΩ")


def _load_pymupdf():
    try:
        import pymupdf  # PyMuPDF ≥1.24 的新模块名
        return pymupdf
    except ImportError:  # pragma: no cover - 兼容旧版
        import fitz as pymupdf
        return pymupdf


def _is_math_font(name: str) -> bool:
    n = (name or "").lower()
    if not n:
        return False
    if n.startswith("cm") and not n.startswith("cmr"):
        return True
    return bool(_MATH_FONT_RE.search(n))


def _span_is_math(font: str, text: str) -> bool:
    """字体属于公式/等宽族且片段很短 → 视为公式片段（保留原文）。"""
    if not _is_math_font(font):
        return False
    t = text.strip()
    if not t or len(t) > 16:
        return False
    return True


def _squeeze(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _line_text(parts) -> str:
    """行内片段拼成一行文本：公式片段用 $...$ 包裹，交给模型原样保留。"""
    out = []
    for kind, text in parts:
        if kind == "math":
            t = text.strip()
            if t:
                out.append(f"${t}$")
        else:
            out.append(text)
    return _squeeze("".join(out))


def _join_lines(texts: list[str]) -> str:
    out = ""
    for s in texts:
        if not s:
            continue
        if out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + s        # 行末连字符：英文单词被折断
        elif out:
            out = out + " " + s
        else:
            out = s
    return _squeeze(out)


def _worth_translating(text: str) -> bool:
    """只翻「有文字的正文片段」：公式块、纯数字、已是中文的块一律保留原文。"""
    plain = re.sub(r"\$[^$]*\$", "", text)      # 去掉公式片段后再判断
    letters = sum(1 for c in plain if c.isascii() and c.isalpha())
    cjk = sum(1 for c in plain if "\u4e00" <= c <= "\u9fff")
    if letters < 2:
        return False
    if cjk >= letters:            # 已经是中文（或中英混排偏中文）
        return False
    # 作者/机构行（带邮箱的短行）：人名与邮箱不该被"翻译"
    if len(plain) <= 120 and re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", plain):
        return False
    syms = sum(1 for c in plain if c in _MATH_CHARS)
    if syms >= 8 and syms * 3 >= len(plain):
        return False
    return True


def _page_lines(page):
    """抽取整页行记录（parts / bbox / 字号 / 颜色 / 字符数）。

    只借用 PyMuPDF 的「行」粒度，不信任它的 block 分组：论文常见的双栏排版会被
    合进同一个 block，导致整页 bbox 被一起擦除。分块交给 `_group_lines` 自己算。
    """
    data = page.get_text("dict")
    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text_parts: list[tuple[str, str]] = []
            content_chars: list[str] = []
            sizes: list[float] = []
            color = 0
            prev_span = None
            for span in line.get("spans", []):
                text = span.get("text") or ""
                if not text.strip():
                    continue
                font = span.get("font") or ""
                size = float(span.get("size") or 0)
                if size > 0:
                    sizes.append(size)
                # run-in 小标题/公式后的正文常靠坐标留白分隔，没有空格字符；
                # 不补空格会让"sub-layers.The first"粘在一起
                if prev_span is not None and text_parts:
                    gap = float(span["bbox"][0]) - float(prev_span["bbox"][2])
                    if gap > max(0.5, 0.18 * (size or 10.0)) and not text_parts[-1][1].endswith(" "):
                        text_parts.append(("text", " "))
                color = int(span.get("color") or 0) or color
                text_parts.append(("math" if _span_is_math(font, text) else "text", text))
                content_chars.append(text.strip())
                prev_span = span
            if not text_parts:
                continue
            bbox = line.get("bbox")
            if not bbox:
                continue
            direction = line.get("dir") or (1, 0)
            if abs(float(direction[1])) > 0.12:   # 竖排/旋转文字：保持原样，不重排
                continue
            text = _line_text(text_parts)
            if not text:
                continue
            lines.append({
                "parts": text_parts, "bbox": tuple(bbox),
                "size": min(max(sizes) if sizes else 10.0, 48.0),
                "color": color, "chars": len("".join(content_chars)),
                "text": text,
            })
    return lines


def _h_overlap(a: tuple, b: tuple) -> float:
    """两行水平重叠比例（相对较窄者）。"""
    lo = max(a[0], b[0])
    hi = min(a[2], b[2])
    if hi <= lo:
        return 0.0
    narrow = min(max(1e-6, a[2] - a[0]), max(1e-6, b[2] - b[0]))
    return (hi - lo) / narrow


def _group_lines(lines: list[dict]) -> list[list[dict]]:
    """按「竖直相邻 + 水平重叠 + 字号相近」把行聚成段落块（天然区分双栏）。

    同一基线上的碎片（典型的 run-in 小标题：`Encoder: sub-layers.` 后面紧跟正文）
    会被 PyMuPDF 拆成两条 line，这里按「基线相同且水平紧邻」重新拼回同一块，
    否则两块会覆盖同一片区域，擦写后中文互相叠字。
    """
    order = sorted(lines, key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    blocks: list[list[dict]] = []
    for ln in order:
        size = ln["size"] or 10.0
        target = None
        for blk in reversed(blocks[-8:]):
            last = blk[-1]
            same_baseline = abs(ln["bbox"][1] - last["bbox"][1]) <= size * 0.3
            gap_x = ln["bbox"][0] - last["bbox"][2]
            if same_baseline and -1.0 <= gap_x <= max(2.0, size * 0.9):
                target = blk
                break
            gap = ln["bbox"][1] - last["bbox"][3]
            if gap < -size * 1.2 or gap > max(3.0, size * 0.85):
                continue
            if _h_overlap(ln["bbox"], last["bbox"]) < 0.55:
                continue
            if abs((last["size"] or size) - size) > max(0.6, size * 0.10):
                continue
            target = blk
            break
        if target is None:
            blocks.append([ln])
        else:
            target.append(ln)
    return blocks


def _block_unit(lines: list[dict]) -> dict | None:
    text = _join_lines([ln["text"] for ln in lines])
    if not text or not _worth_translating(text):
        return None
    x0 = min(ln["bbox"][0] for ln in lines)
    y0 = min(ln["bbox"][1] for ln in lines)
    x1 = max(ln["bbox"][2] for ln in lines)
    y1 = max(ln["bbox"][3] for ln in lines)
    sizes = [ln["size"] for ln in lines if ln["size"]]
    colors = [ln["color"] for ln in lines if ln["color"]]
    return {
        "text": text[:3000],
        "bbox": (x0, y0, x1, y1),
        "size": min(sizes) if sizes else 10.0,
        "color": max(set(colors), key=colors.count) if colors else 0,
    }


def _rect_overlap_ratio(a: tuple, b: tuple) -> float:
    """交叠面积 / 较小块面积。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = max(1e-6, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))
    return (w * h) / area


def _merge_overlaps(units: list[dict]) -> list[dict]:
    """同一片区域被切成多块时合并成一块：否则擦除区域重叠、译文会互相叠字。"""
    out: list[dict] = []
    for u in sorted(units, key=lambda x: (x["bbox"][1], x["bbox"][0])):
        for v in out:
            if _rect_overlap_ratio(u["bbox"], v["bbox"]) > 0.55:
                if u["bbox"][0] < v["bbox"][0] - 1:
                    v["text"] = u["text"] + " " + v["text"]
                else:
                    v["text"] = v["text"] + " " + u["text"]
                v["bbox"] = (
                    min(u["bbox"][0], v["bbox"][0]), min(u["bbox"][1], v["bbox"][1]),
                    max(u["bbox"][2], v["bbox"][2]), max(u["bbox"][3], v["bbox"][3]),
                )
                v["size"] = min(v["size"], u["size"])
                v["text"] = v["text"][:3000]
                break
        else:
            out.append(dict(u))
    return out


def page_units(page) -> list[dict]:
    """一页 → 可翻译文本单元列表（超长段落按行切成多段，各带独立 bbox）。"""
    blocks = _group_lines(_page_lines(page))
    units: list[dict] = []
    for lines in blocks:
        # 超长段落按行切分，避免一次翻译几千字导致模型吞内容 / 回写溢出
        part: list[dict] = []
        chars = 0
        for ln in lines:
            if part and chars + ln["chars"] > MAX_UNIT_CHARS:
                unit = _block_unit(part)
                if unit:
                    units.append(unit)
                part, chars = [], 0
            part.append(ln)
            chars += ln["chars"]
        if part:
            unit = _block_unit(part)
            if unit:
                units.append(unit)
    units = _merge_overlaps(units)
    # 阅读顺序：先按栏（x 起点分桶）再按 y，双栏论文即「左栏从上到下、右栏从上到下」
    return sorted(units, key=lambda u: (round(u["bbox"][0] / 60.0), u["bbox"][1]))


# ---------------------------------------------------------------- LLM 翻译

def _clean_zh(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip().strip('"').strip()
    return s


def _bad_translation(src: str, zh: str) -> bool:
    if not zh:
        return True
    if zh == src:
        return True
    if len(zh) > max(200, len(src) * 4):
        return True
    if "```" in zh:
        return True
    if re.search(r"(无法翻译|抱歉|as an AI|I cannot)", zh, re.I):
        return True
    return False


def _chunks(units: list[dict]) -> list[list[int]]:
    out: list[list[int]] = []
    cur: list[int] = []
    chars = 0
    for i, u in enumerate(units):
        if cur and (chars + len(u["text"]) > BATCH_CHARS or len(cur) >= BATCH_ITEMS):
            out.append(cur)
            cur, chars = [], 0
        cur.append(i)
        chars += len(u["text"])
    if cur:
        out.append(cur)
    return out


def _translate_batch(items: list[tuple[int, str]]) -> dict[int, str]:
    """整批 JSON 翻译；解析失败或数量不符时抛 AiUnavailable，由调用方逐条降级。"""
    import json as _json

    payload = _json.dumps([{"i": i, "en": t} for i, t in items], ensure_ascii=False)
    user = (
        "把下面 JSON 数组里每个条目的 en 字段翻译成简体中文，条目数必须与输入一致。\n"
        '只输出 JSON：{"items":[{"i":0,"zh":"译文"},…]}，不要任何解释。\n\n' + payload
    )
    data = llm.chat_structured(
        [{"role": "user", "content": user}],
        system_prompt=_SYS_PROMPT,
        max_tokens=max(3000, min(6000, sum(len(t) for _i, t in items) * 3)),
        temperature=0.15,
        required_keys=("items",),
        timeout_override=180,
    )
    got: dict[int, str] = {}
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        zh = _clean_zh(str(it.get("zh") or ""))
        if zh:
            got[idx] = zh
    return got


def _translate_one(text: str) -> str:
    zh = llm.chat(
        [{"role": "system", "content": _SYS_PROMPT},
         {"role": "user", "content": text}],
        max_tokens=2000, temperature=0.15, timeout_override=180,
    )
    return _clean_zh(zh)


def translate_units(units: list[dict], paper_id: str = "") -> tuple[dict[int, str], int]:
    """把一页的文本单元翻译成中文，返回 ({索引: 译文}, 失败数)。

    整批失败 → 逐条纯文本重试 → 仍失败则保留原文（计入失败数）。
    """
    out: dict[int, str] = {}
    failed = 0
    for chunk in _chunks(units):
        if paper_id and _is_cancelled(paper_id):
            break
        chunk_ok = 0
        chunk_failed = 0
        items = [(i, units[i]["text"]) for i in chunk]
        try:
            got = _translate_batch(items)
        except Exception:
            got = {}
        for i in [i for i in chunk if i not in got]:
            try:
                got[i] = _translate_one(units[i]["text"])
            except Exception:
                got.pop(i, None)
        for i, zh in got.items():
            if zh.strip() == units[i]["text"].strip():
                # 专名/公式行模型原样返回：视为"保持原文"，不算失败
                continue
            if _bad_translation(units[i]["text"], zh):
                chunk_failed += 1
                continue
            out[i] = zh
            chunk_ok += 1
        failed += chunk_failed
        if paper_id:
            with _lock:
                cur = dict(_mem.get(paper_id) or {})
                cur["translated"] = int(cur.get("translated", 0)) + chunk_ok
                cur["failed"] = int(cur.get("failed", 0)) + chunk_failed
            _set_mem(paper_id, translated=cur["translated"], failed=cur["failed"])
    return out, failed


# ---------------------------------------------------------------- 中文回写

def _escape_html(text: str) -> str:
    """译文 → HTML 片段：去掉 $…$ 占位包装，转义标签字符，换行压成空格。"""
    import html as _html

    text = re.sub(r"\$([^$]*)\$", r"\1", text)
    text = _squeeze(text.replace("\n", " "))
    return _html.escape(text)


def _draw(pymupdf, page, rect, text: str, base: float, color, attempt: int = 0) -> bool:
    """把中文写进原 bbox：MuPDF Story 自动处理中英混排与自动缩放。

    insert_htmlbox 的返回值 (spare_height, scale)：spare < 0 表示这一块没排完，
    此时把该块重新擦一遍、按更小字号重写（只影响本块，不动相邻块）。

    排版高度比原文字形 bbox 高（行距 ≈1.26em），单行小标题的 bbox 只有 ~0.9em，
    直接塞会被自动缩到 0.65 倍。所以绘制区上下各放宽 0.22em（擦除区仍用原 bbox）。
    """
    size = max(MIN_FONT, min(float(base), 30.0))
    r, g, b = color
    draw_rect = pymupdf.Rect(rect.x0, rect.y0 - size * 0.22,
                             rect.x1, rect.y1 + size * 0.22)
    draw_rect &= page.rect
    css = ("* {margin:0; padding:0; text-align:left; line-height:1.2; "
           "font-size:" + f"{size:.2f}" + "pt; color:rgb(" + f"{r},{g},{b}" + ");}")
    try:
        spare, _scale = page.insert_htmlbox(draw_rect, _escape_html(text),
                                            css=css, scale_low=0.55)
    except Exception:
        spare = -1
    if spare >= 0:
        return True
    if attempt >= 2:
        return False
    page.add_redact_annot(rect)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    return _draw(pymupdf, page, rect, text, size * 0.82, color, attempt + 1)


def _apply_page(pymupdf, page, units: list[dict], zh: dict[int, str]) -> int:
    done = 0
    targets = []
    for i, u in enumerate(units):
        if i not in zh:
            continue
        rect = pymupdf.Rect(*u["bbox"])
        if rect.width < 4 or rect.height < 4:
            continue
        targets.append((i, rect))
        page.add_redact_annot(rect)
    if not targets:
        return 0
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for i, rect in targets:
        u = units[i]
        color = (0, 0, 0)
        try:
            if u["color"]:
                color = pymupdf.sRGB_to_rgb(u["color"])
        except Exception:
            pass
        if _draw(pymupdf, page, rect, zh[i], float(u["size"]), color):
            done += 1
    return done


# ---------------------------------------------------------------- 主流程

def translate_pdf(src: bytes, paper_id: str = "") -> bytes:
    """整篇翻译：返回中文 PDF 字节流（页数与页面尺寸与原文件一致）。"""
    pymupdf = _load_pymupdf()
    try:
        doc = pymupdf.open(stream=src, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"PDF 解析失败：{str(e)[:120]}") from e
    try:
        if doc.needs_pass:
            raise RuntimeError("PDF 有密码保护，无法翻译")
        total = doc.page_count
        if total < 1:
            raise RuntimeError("PDF 没有页面")
        if total > MAX_PAGES:
            raise RuntimeError(f"PDF 共 {total} 页，超过翻译上限 {MAX_PAGES} 页")
        if paper_id:
            _set_mem(paper_id, state="running", pages=total, done=0,
                     blocks=0, translated=0, failed=0, error="")

        blocks_total = 0
        translated_total = 0
        for pno in range(total):
            if paper_id and _is_cancelled(paper_id):
                raise RuntimeError("翻译已取消")
            page = doc[pno]
            rotation = page.rotation
            if rotation:
                page.set_rotation(0)          # 在处理空间里读写，最后还原
            try:
                units = page_units(page)
                blocks_total += len(units)
                zh: dict[int, str] = {}
                if units:
                    zh, _failed = translate_units(units, paper_id=paper_id)
                    translated_total += len(zh)
                _apply_page(pymupdf, page, units, zh)
            finally:
                if rotation:
                    page.set_rotation(rotation)
            if paper_id:
                _set_mem(paper_id, done=pno + 1, pages=total, blocks=blocks_total)
                st = read_status(paper_id)
                st.update({"state": "running", "done": pno + 1, "pages": total,
                           "blocks": blocks_total})
                _save(paper_id, st)
        if blocks_total == 0:
            raise RuntimeError("这篇 PDF 没有文本层（可能是扫描版），无法生成中文译文")
        if translated_total == 0:
            raise llm.AiUnavailable("所有文本块都翻译失败（模型无响应或返回格式异常）")
        # Story 每次插入都会内嵌一份字体（一页能有 8 份 Droid Sans Fallback），
        # 必须先 subset 再 GC，否则 1 页样张就能到 8MB。
        try:
            doc.subset_fonts()
        except Exception:
            pass
        try:
            return doc.tobytes(garbage=4, deflate=True, clean=True)
        except Exception:
            try:
                return doc.tobytes(garbage=3, deflate=True)
            except Exception:
                return doc.tobytes()
    finally:
        doc.close()