import json

import pytest

from app.ai import llm, paper_reading


def test_summary_uses_only_real_excerpt_ids_and_reports_truncation(monkeypatch):
    pages = ["one " * 5000, "page two"]
    monkeypatch.setattr(paper_reading, "_load_pages", lambda _: pages)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: json.dumps({"items": [
        {"section": "方法", "text": "supported", "sources": ["1", "99999"]},
        {"section": "结果", "text": "fake", "sources": ["99999"]},
    ]}))
    result = paper_reading.summary("0123456789ab")
    assert len(result["items"]) == 1
    assert result["items"][0]["sources"][0]["quote"] in pages[0]
    assert result["coverage"]["included_pages"] == [1]
    assert result["coverage"]["truncated_pages"] == [1, 2]


def test_explanation_rejects_unmatched_selection_before_calling_model(monkeypatch):
    monkeypatch.setattr(paper_reading, "_load_pages", lambda _: ["A method on this page"])
    def reject_call(*args, **kwargs):
        raise AssertionError("model must not be called")
    monkeypatch.setattr(llm, "chat", reject_call)
    with pytest.raises(llm.AiUnavailable, match="核对"):
        paper_reading.explain("0123456789ab", 1, "invented quotation")


def test_explanation_returns_verified_text_and_page(monkeypatch):
    monkeypatch.setattr(paper_reading, "_load_pages", lambda _: ["first", "A method on this page"])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "这是解释。")
    result = paper_reading.explain("0123456789ab", 2, "method on this")
    assert result["page"] == 2
    assert result["quote"] == "method on this"
    assert result["coverage"]["included_pages"] == [2]


def test_summary_retries_invalid_json_with_larger_output_budget(monkeypatch):
    monkeypatch.setattr(paper_reading, "_load_pages", lambda _: ["A verified source."])
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return '{"items": ['
        return json.dumps({"items": [{"section": "方法", "text": "摘要", "sources": ["1"]}]})

    monkeypatch.setattr(llm, "chat", fake_chat)
    result = paper_reading.summary("0123456789ab")
    assert result["items"][0]["sources"][0]["quote"] == "A verified source."
    assert len(calls) == 2
    assert all(call["max_tokens"] == 16384 and call["timeout_override"] == 300 for call in calls)
