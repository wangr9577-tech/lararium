"""AI 本地小模型服务（M7）：摘要/润色/周报草稿，全部走 services/llm（127.0.0.1）。

所有端点：ai_enabled 关闭或调用失败 → 返回 {"ok": false, "reason": ...}，
前端提示「AI 服务不可用」，绝不阻塞主功能。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import get_current
from ..services import llm, pdf_text

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _run(fn):
    try:
        return {"ok": True, "text": fn()}
    except llm.AiUnavailable as e:
        return {"ok": False, "reason": str(e)}
    except Exception as e:
        return {"ok": False, "reason": f"处理失败: {e}"}


class SummarizeIn(BaseModel):
    paper_id: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=60_000)


@router.post("/summarize")
def ai_summarize(body: SummarizeIn, _user: dict = Depends(get_current)):
    """论文摘要：优先按 paper_id 取 PDF 抽文本，否则用传入 text。"""
    def do() -> str:
        text = body.text or ""
        if not text and body.paper_id:
            from .. import vault
            from ..routers import papers as papers_mod
            p = papers_mod._pdf_path(body.paper_id)
            if not p.is_file():
                raise llm.AiUnavailable("论文文件不存在")
            text = pdf_text.extract_text(vault.read_bytes(p))
        if not text.strip():
            raise llm.AiUnavailable("PDF 无文本层（扫描版无法自动摘要），可手动粘贴摘要输入")
        prompt = (
            "请为以下论文内容生成结构化中文摘要，包含：研究问题、方法、主要结果、局限。"
            "若内容是英文，摘要用中文输出。控制在 400 字以内：\n\n" + text[:18000]
        )
        return llm.chat([{"role": "user", "content": prompt}], max_tokens=900)
    return _run(do)


class PolishIn(BaseModel):
    text: str = Field(min_length=2, max_length=8_000)
    kind: str = Field(default="experiment", max_length=20)  # experiment | conclusion | related_work


@router.post("/polish")
def ai_polish(body: PolishIn, _user: dict = Depends(get_current)):
    def do() -> str:
        kind_hint = {
            "experiment": "Deep learning / Agent 实验结果的英文描述段",
            "conclusion": "论文结论段",
            "related_work": "相关工作段",
        }.get(body.kind, "学术段落")
        prompt = (
            f"你正在帮一位研究者把中文草稿润色为地道的英文学术写作（{kind_hint}）。"
            "保留原意，输出英文，可适度重构句式。若已是英文则润色并纠错。\n\n" + body.text
        )
        return llm.chat([{"role": "user", "content": prompt}], max_tokens=1200)
    return _run(do)


class ReportDraftIn(BaseModel):
    items: list[dict] = Field(default_factory=list, max_length=60)


@router.post("/report-draft")
def ai_report_draft(body: ReportDraftIn, _user: dict = Depends(get_current)):
    def do() -> str:
        lines = []
        for it in body.items:
            kind = it.get("kind", "条目")
            title = it.get("title", "")
            lines.append(f"- [{kind}] {title}")
        if not lines:
            raise llm.AiUnavailable("本周没有可聚合的条目")
        prompt = (
            "请根据以下本周科研条目列表，起草一份简洁的中文科研周报（目标：导师/自己回顾用）。"
            "包含：本周产出要点、进展归纳、下周建议。不要虚构条目内容：\n\n"
            + "\n".join(lines)
        )
        return llm.chat([{"role": "user", "content": prompt}], max_tokens=900)
    return _run(do)


@router.get("/status")
def ai_status(_user: dict = Depends(get_current)):
    return {"enabled": llm.is_enabled()}


class TestAiIn(BaseModel):
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout: int | None = None
    provider: str | None = None
    tunnel_hint: str | None = None
    name: str | None = None


@router.post("/test")
def ai_test_connection(body: TestAiIn | None = None, _user: dict = Depends(get_current)):
    """测试模型连接。若传入 body 则测试该指定配置，否则测试当前全局生效配置。"""
    override = body.model_dump(exclude_unset=True) if body else None
    res = llm.check_diagnostics(override_cfg=override)
    return {
        "ok": res["connected"],
        "latency_ms": res.get("latency_ms", 0),
        "model": res.get("model", ""),
        "provider": res.get("provider", ""),
        "endpoint": res.get("endpoint", ""),
        "reason": res.get("error_hint", "") if not res["connected"] else "连接成功",
    }


@router.get("/profiles")
def ai_get_profiles(_user: dict = Depends(get_current)):
    """获取所有模型配置、当前激活的配置以及可用模板。"""
    profiles, active_id, enabled = llm.get_profiles_and_active()
    return {
        "enabled": enabled,
        "active_profile_id": active_id,
        "profiles": profiles,
        "default_profiles": llm.DEFAULT_PROFILES,
    }
