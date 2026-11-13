"""The legacy import paths must share state and patches with AI modules."""
import importlib

import pytest


@pytest.mark.parametrize("name", ["llm", "paper_translate", "assistant_prompts", "attachment_agent"])
def test_legacy_import_is_same_module(name):
    legacy = importlib.import_module(f"app.services.{name}")
    current = importlib.import_module(f"app.ai.{name}")
    assert legacy is current


def test_translation_queue_and_llm_patch_are_shared(monkeypatch):
    from app.ai import llm, paper_translate
    from app.services import llm as old_llm, paper_translate as old_translate

    monkeypatch.setattr(old_llm, "is_enabled", lambda: True)
    assert llm.is_enabled()
    assert old_translate._queue is paper_translate._queue
    assert old_translate._lock is paper_translate._lock


def test_workflows_keep_existing_model_contract(monkeypatch):
    from app.ai import llm, workflows

    calls = []
    def fake_chat(messages, max_tokens):
        calls.append((messages, max_tokens))
        return "result"
    monkeypatch.setattr(llm, "chat", fake_chat)
    assert workflows.summarize(text="original text") == "result"
    assert calls[-1][1] == 900 and "original text" in calls[-1][0][0]["content"]
    assert workflows.polish("draft", "conclusion") == "result"
    assert calls[-1][1] == 1200
    assert workflows.report_draft([{"kind": "实验", "title": "A"}]) == "result"
    assert "[实验] A" in calls[-1][0][0]["content"]
    with pytest.raises(llm.AiUnavailable):
        workflows.report_draft([])


def test_assistant_uses_shared_llm(monkeypatch):
    from app.ai import assistant_workflows, llm, assistant_prompts

    requests = []
    def structured(messages, **kwargs):
        requests.append((messages, kwargs))
        return {"title": "T", "summary": "S", "kind": "notice"}
    monkeypatch.setattr(llm, "chat_structured", structured)
    monkeypatch.setattr(llm, "is_enabled", lambda: True)
    assistant_workflows.classify("body", "url", "note", [])
    assert requests[-1][1]["system_prompt"] == assistant_prompts.CLASSIFY_PROMPT
    assistant_workflows.extract_record("body", "url", "note", [], "notice")
    assert requests[-1][1]["required_keys"] == ("title", "summary")
    assert "body" in requests[-1][0][0]["content"]

