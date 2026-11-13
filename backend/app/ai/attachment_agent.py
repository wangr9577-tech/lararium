"""Turn attachments into source text before classification and summarization."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import assistant_prompts, llm

IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}
MAX_SCANNED_PAGES = 30


def _transcribe_image(content: bytes, mime: str, name: str) -> str:
    message = llm.format_multimodal_message("user", "请逐行转写此附件中的文字。", [(content, mime)])
    result = llm.chat_structured([message], system_prompt=assistant_prompts.ATTACHMENT_TRANSCRIPTION_PROMPT,
                                 required_keys=("text",), timeout_override=180)
    value = result.get("text")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"附件「{name}」没有识别到可用文字，请检查图片清晰度。")
    return value.strip()


def convert(filename: str, content: bytes, text_extractor: Callable[[str, bytes], str]) -> str:
    """Preserve native document text; use the vision agent only where OCR is needed."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_TYPES:
        text = _transcribe_image(content, IMAGE_TYPES[ext], filename)
        return f"【图片附件 {filename} 识别文字（请核对原图）】\n{text}"
    if ext == ".pdf":
        try:
            import pymupdf
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                if len(doc) > MAX_SCANNED_PAGES and any(not page.get_text().strip() for page in doc):
                    raise ValueError(f"附件「{filename}」需要识别的 PDF 超过 {MAX_SCANNED_PAGES} 页，请拆分后上传。")
                pages = []
                for index, page in enumerate(doc):
                    text = page.get_text().strip()
                    if not text:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                        text = _transcribe_image(pix.tobytes("png"), "image/png", f"{filename} 第 {index + 1} 页")
                        label = "（图像识别，请核对原件）"
                    else:
                        label = ""
                    pages.append(f"--- [第 {index + 1} 页]{label} ---\n{text}")
                if pages:
                    return f"【PDF 附件 {filename} 文本解析内容】\n" + "\n".join(pages)
        except (RuntimeError, OSError) as exc:
            raise ValueError(f"附件「{filename}」无法读取，请检查 PDF 文件。") from exc
        raise ValueError(f"附件「{filename}」没有可读取的页面。")
    text = text_extractor(filename, content).strip()
    if not text:
        raise ValueError(f"附件「{filename}」无法提取正文：格式不支持、文件损坏或文件为空。附件已保存，请转换为可搜索的 PDF、Word 或图片后重试。")
    return text
