"""有据问答（/chat 与 /chat/stream）的加密上下文与流式输出测试。"""
from __future__ import annotations

import json
from unittest.mock import patch

from backend.tests.test_env import TestEnvironment
from app.services import llm

env = TestEnvironment(prefix="kruskal_assistant_chat_")
client = env.client

# 超过 80 字，且关键补充放在第 80 字之后：只有真正解密 facts.enc 才能看到。
LONG_SUMMARY = (
    "学院通知：2026 年秋季创新基金申报已启动，需提交盖章版申报书、预算表和两份推荐信，"
    "申报系统将在截止后自动关闭，逾期不予受理。关键补充：还需同时提交导师签字页。"
)
TAIL_MARKER = "还需同时提交导师签字页"
QUOTE = "申报系统将于2026-11-20 18:00关闭，逾期不予受理。"
EVIDENCE = ["纸质材料需一式三份盖章报送科研处。"]


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def _create_notice() -> tuple[int, int]:
    card = {
        "title": "2026年秋季创新基金申报",
        "summary": LONG_SUMMARY,
        "highlights": ["提交盖章申报书", "准备两封推荐信"],
        "deadline_date": "2026-11-20",
        "deadline_time": "18:00",
        "event_keywords": ["创新基金", "申报"],
        "quote": QUOTE,
        "evidence_quotes": EVIDENCE,
    }
    with patch.object(llm, "is_enabled", return_value=True), \
         patch.object(llm, "chat_structured", return_value=card):
        resp = client.post(
            "/api/assistant/submit",
            json={"text": "【申报通知】" + LONG_SUMMARY, "mode": "notice"},
            headers=env.auth_headers(),
        )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    detail = client.get(f"/api/assistant/records/{record_id}", headers=env.auth_headers()).json()
    assert detail["status"] == "ready", detail.get("error_msg")
    return record_id, detail["thread"]["id"]


def test_chat_uses_decrypted_facts_not_the_80_char_summary():
    record_id, thread_id = _create_notice()
    captured: dict = {}

    def fake_chat(messages, max_tokens=1500, temperature=0.3):
        captured["messages"] = messages
        return "根据通知，截止时间为 2026-11-20 18:00。"

    with patch.object(llm, "is_enabled", return_value=True), \
         patch.object(llm, "chat", side_effect=fake_chat):
        resp = client.post(
            "/api/assistant/chat",
            json={"query": "这次申报还差什么材料？", "thread_id": thread_id},
            headers=env.auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    prompt = captured["messages"][-1]["content"]
    assert TAIL_MARKER in prompt, "问答上下文必须来自解密后的 facts.enc，而不是 80 字短摘要"
    assert QUOTE in prompt, "关键依据原句应进入问答上下文"
    assert EVIDENCE[0] in prompt, "佐证原句应进入问答上下文"
    assert payload["sources"][0]["type"] == "thread"
    assert payload["sources"][0]["title"] == "2026年秋季创新基金申报"


def test_chat_stream_emits_meta_delta_done():
    record_id, thread_id = _create_notice()

    def fake_stream(messages, max_tokens=1500, temperature=0.3):
        yield "根据通知，"
        yield "截止 2026-11-20 18:00。"
        yield "需要盖章申报书。"

    with patch.object(llm, "is_enabled", return_value=True), \
         patch.object(llm, "chat_stream", side_effect=fake_stream):
        resp = client.post(
            "/api/assistant/chat/stream",
            json={"query": "什么时候截止？", "thread_id": thread_id},
            headers=env.auth_headers(),
        )

    assert resp.status_code == 200
    body = resp.text
    events = [line[len("event: "):] for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "meta"
    assert events.count("delta") == 3
    assert events[-1] == "done"
    assert "截止 2026-11-20 18:00" in body
    meta_data = [line for line in body.splitlines() if line.startswith("data: ")][0]
    meta = json.loads(meta_data[len("data: "):])
    assert meta["sources"][0]["id"] == thread_id


def test_chat_stream_turns_model_failure_into_error_event():
    record_id, thread_id = _create_notice()

    def broken_stream(messages, max_tokens=1500, temperature=0.3):
        raise llm.AiUnavailable("SSH 隧道断开")
        yield ""  # pragma: no cover

    with patch.object(llm, "is_enabled", return_value=True), \
         patch.object(llm, "chat_stream", side_effect=broken_stream):
        resp = client.post(
            "/api/assistant/chat/stream",
            json={"query": "什么时候截止？", "thread_id": thread_id},
            headers=env.auth_headers(),
        )

    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "SSH 隧道断开" in resp.text


def test_chat_degrades_honestly_when_model_disabled():
    record_id, thread_id = _create_notice()
    with patch.object(llm, "is_enabled", return_value=False):
        resp = client.post(
            "/api/assistant/chat",
            json={"query": "什么时候截止？", "thread_id": thread_id},
            headers=env.auth_headers(),
        )
    payload = resp.json()
    assert payload["degraded"] is True
    assert "AI 服务暂不可用" in payload["answer"]
    assert "2026年秋季创新基金申报" in payload["answer"]
