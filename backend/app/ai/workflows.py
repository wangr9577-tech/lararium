"""AI task workflows shared by HTTP handlers and future integrations."""
from __future__ import annotations

from . import llm
from ..services import pdf_text


def summarize(paper_id: str = "", text: str = "") -> str:
    if not text and paper_id:
        from .. import vault
        from ..routers import papers
        path = papers._pdf_path(paper_id)
        if not path.is_file():
            raise llm.AiUnavailable("论文文件不存在")
        text = pdf_text.extract_text(vault.read_bytes(path))
    if not text.strip():
        raise llm.AiUnavailable("PDF 无文本层（扫描版无法自动摘要），可手动粘贴摘要输入")
    prompt = (
        "请为以下论文内容生成结构化中文摘要，包含：研究问题、方法、主要结果、局限。"
        "若内容是英文，摘要用中文输出。控制在 400 字以内：\n\n" + text[:18000]
    )
    return llm.chat([{"role": "user", "content": prompt}], max_tokens=900)


def polish(text: str, kind: str) -> str:
    hint = {
        "experiment": "Deep learning / Agent 实验结果的英文描述段",
        "conclusion": "论文结论段",
        "related_work": "相关工作段",
    }.get(kind, "学术段落")
    prompt = (
        f"你正在帮一位研究者把中文草稿润色为地道的英文学术写作（{hint}）。"
        "保留原意，输出英文，可适度重构句式。若已是英文则润色并纠错。\n\n" + text
    )
    return llm.chat([{"role": "user", "content": prompt}], max_tokens=1200)


def report_draft(items: list[dict]) -> str:
    lines = [f"- [{it.get('kind', '条目')}] {it.get('title', '')}" for it in items]
    if not lines:
        raise llm.AiUnavailable("本周没有可聚合的条目")
    prompt = (
        "请根据以下本周科研条目列表，起草一份简洁的中文科研周报（目标：导师/自己回顾用）。"
        "包含：本周产出要点、进展归纳、下周建议。不要虚构条目内容：\n\n" + "\n".join(lines)
    )
    return llm.chat([{"role": "user", "content": prompt}], max_tokens=900)
