"""PDF 文本抽取：PyMuPDF 抽取前 N 页文本，用于 AI 摘要/检索。

扫描版（无文本层）返回 text=""。接口为纯函数，不抛异常（失败返回空串）。
"""
from __future__ import annotations

import io

MAX_PAGES = 12  # 摘要取前 N 页，控制 token 开销
MAX_CHARS = 18000  # 抽出来的文本截断长度


def extract_text(pdf_bytes: bytes, max_pages: int = MAX_PAGES, max_chars: int = MAX_CHARS) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    parts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        t = page.get_text("text") or ""
        t = " ".join(t.split())
        if t:
            parts.append(f"[第{i + 1}页] {t}")
        total = sum(len(p) for p in parts)
        if total >= max_chars:
            break
    doc.close()
    return "\n".join(parts)[:max_chars]