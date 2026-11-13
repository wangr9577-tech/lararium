"""论文问答接口：加载加密论文后交给 AI 模块处理。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import vault
from ..ai import llm, paper_qa
from ..auth import get_current
from . import papers

router = APIRouter(prefix="/api/ai", tags=["ai"])


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    paper_ids: list[str] = Field(min_length=1, max_length=paper_qa.MAX_PAPERS)


@router.post("/paper-question")
def paper_question(body: QuestionIn, _user: dict = Depends(get_current)):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "请输入问题")
    if len(set(body.paper_ids)) != len(body.paper_ids):
        raise HTTPException(400, "请勿重复选择论文")
    selected = []
    for paper_id in body.paper_ids:
        if not re.fullmatch(r"[0-9a-f]{12}", paper_id):
            raise HTTPException(400, "论文标识无效")
        meta = papers._load_meta(paper_id)
        path = papers._pdf_path(paper_id)
        if meta is None or not path.is_file():
            raise HTTPException(404, "论文不存在")
        selected.append({"id": paper_id, "title": meta.get("title") or "未命名论文", "bytes": vault.read_bytes(path)})
    try:
        return paper_qa.answer(question, selected)
    except llm.AiUnavailable as e:
        return {"ok": False, "reason": str(e), "coverage": [], "claims": []}
    except ValueError:
        return {"ok": False, "reason": "AI 返回的结果无法解析，请重试。", "coverage": [], "claims": []}
