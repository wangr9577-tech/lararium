"""论文问答的页码覆盖、证据校验及 API 边界。无需真实模型。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pymupdf
import pytest
from fastapi import HTTPException
from app.ai import paper_qa
from app.routers import paper_qa as route


def make_pdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "The experiment uses a baseline model.")
    doc.new_page()
    doc.new_page().insert_text((72, 72), "Results show lower error in the experiment.")
    result = doc.tobytes()
    doc.close()
    return result


def test_answer_citations_are_checked_and_taken_from_original(monkeypatch):
    def fake_chat(*args, **kwargs):
        return {"claims": [
            {"text": "有实验结果", "citations": ["P1S1"]},
            {"text": "假引用", "citations": ["P999S1"]},
            {"text": "混合假引用", "citations": ["P1S1", "P2S1"]},
            {"text": "没有引用", "citations": []},
        ], "uncertainty": "仅基于部分片段"}
    monkeypatch.setattr(paper_qa.llm, "chat_structured", fake_chat)
    out = paper_qa.answer("experiment", [{"id": "aaaaaaaaaaaa", "title": "Test", "bytes": make_pdf()}])
    assert len(out["claims"]) == 1
    ref = out["claims"][0]["citations"][0]
    assert ref["paper_id"] == "aaaaaaaaaaaa"
    assert ref["page"] in (1, 3)
    assert "experiment" in ref["text"]
    assert out["coverage"][0]["total_pages"] == 3
    assert out["coverage"][0]["text_pages"] == 2
    assert out["coverage"][0]["sent_pages"] == [1, 3]


def test_no_match_uses_explicitly_labelled_sampling_and_empty_pdf_does_not_call_model(monkeypatch):
    pages = [{"page": i, "text": f"text page {i}"} for i in range(1, 9)]
    chunks, selection = paper_qa.select_chunks(pages, "比较结果")
    assert selection == "sample"
    assert [c["page"] for c in chunks] == [1, 3, 6, 8]
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    monkeypatch.setattr(paper_qa.llm, "chat_structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call model")))
    result = paper_qa.answer("问题", [{"id": "aaaaaaaaaaaa", "title": "扫描", "bytes": data}])
    assert not result["ok"]
    assert result["coverage"][0]["text_pages"] == 0


def test_api_rejects_invalid_or_duplicate_ids():
    for ids in (["../x"], ["a" * 12, "a" * 12]):
        with pytest.raises(HTTPException) as exc:
            route.paper_question(route.QuestionIn(paper_ids=ids, question="q"), _user={})
        assert exc.value.status_code == 400
