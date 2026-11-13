"""AI 本地小模型服务（M7）：摘要/润色/周报草稿，全部走 services/llm（127.0.0.1）。

所有端点：ai_enabled 关闭或调用失败 → 返回 {"ok": false, "reason": ...}，
前端提示「AI 服务不可用」，绝不阻塞主功能。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import get_current
from ..ai import llm, workflows, paper_reading

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
    return _run(lambda: workflows.summarize(body.paper_id, body.text))


class PaperReadingIn(BaseModel):
    paper_id: str = Field(min_length=12, max_length=12)
    page: int = Field(default=1, ge=1)
    selection: str = Field(default="", max_length=600)


@router.post("/paper-summary")
def paper_summary(body: PaperReadingIn, _user: dict = Depends(get_current)):
    try:
        return {"ok": True, **paper_reading.summary(body.paper_id)}
    except llm.AiUnavailable as exc:
        return {"ok": False, "reason": str(exc)}


@router.post("/paper-explain")
def paper_explain(body: PaperReadingIn, _user: dict = Depends(get_current)):
    try:
        return {"ok": True, **paper_reading.explain(body.paper_id, body.page, body.selection)}
    except llm.AiUnavailable as exc:
        return {"ok": False, "reason": str(exc)}


class PolishIn(BaseModel):
    text: str = Field(min_length=2, max_length=8_000)
    kind: str = Field(default="experiment", max_length=20)  # experiment | conclusion | related_work


@router.post("/polish")
def ai_polish(body: PolishIn, _user: dict = Depends(get_current)):
    return _run(lambda: workflows.polish(body.text, body.kind))


class ReportDraftIn(BaseModel):
    items: list[dict] = Field(default_factory=list, max_length=60)


@router.post("/report-draft")
def ai_report_draft(body: ReportDraftIn, _user: dict = Depends(get_current)):
    return _run(lambda: workflows.report_draft(body.items))


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
        "available_models": res.get("available_models", []),
        "reason": res.get("error_hint", "") if not res["connected"] else "连接成功",
    }


class DiscoverModelsIn(BaseModel):
    endpoint: str
    api_key: str | None = None


@router.post("/discover-models")
def ai_discover_models(body: DiscoverModelsIn, _user: dict = Depends(get_current)):
    """获取指定端点当前加载的所有可用模型。"""
    models = llm.fetch_endpoint_models(body.endpoint, body.api_key or "")
    return {"ok": bool(models), "models": models}


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
