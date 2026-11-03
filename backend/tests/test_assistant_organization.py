"""Regression tests for assistant classification, structured output and grouped notices."""
from unittest.mock import patch

from backend.tests.test_env import TestEnvironment
from app.services import llm

env = TestEnvironment(prefix="kruskal_organization_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_structured_output_retry_preserves_original_message():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "请分类"}, image]}]
    with patch.object(llm, "chat", side_effect=["<think>思考中</think>", '说明： {"kind":"later"}']) as chat:
        assert llm.chat_structured(messages) == {"kind": "later"}
    assert chat.call_count == 2
    assert image in chat.call_args.args[0][1]["content"]


def test_automatic_classification_and_notice_cards():
    def model(messages, system_prompt="", **kwargs):
        if "信息分流器" in system_prompt:
            text = str(messages)
            return {"kind": "later" if "论文" in text else "notice", "reason": "测试"}
        if "事务性通知信息提取专家" in system_prompt:
            return {"title": "会议报名", "summary": "准备报名材料", "highlights": ["填写表格"],
                    "deadline_date": "", "deadline_time": "", "event_keywords": ["会议报名"]}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "change_reason": "补充表格",
                    "summary": "准备报名材料并填写表格", "highlights": ["填写表格"],
                    "deadline_date": "", "deadline_time": ""}
        if "知识整理助手" in system_prompt:
            return {"title": "会议中的多智能体论文", "brief": "研究多智能体。", "category": "论文", "tags": ["多智能体"]}
        raise AssertionError(system_prompt)

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = []
        for text in ("会议报名通知：准备材料", "会议报名通知：补充填写表格", "论文：会议中的多智能体研究"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "auto"}, headers=env.auth_headers())
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        notice = client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()
        assert notice["total"] == 1
        assert len(notice["items"]) == 1
        assert "填写表格" in notice["items"][0]["summary"]
        detail = client.get(f"/api/assistant/records/{ids[2]}", headers=env.auth_headers()).json()
        assert detail["kind"] == "later"
        thread_id = notice["items"][0]["thread"]["id"]
        thread = client.get(f"/api/assistant/threads/{thread_id}", headers=env.auth_headers()).json()
        assert len(thread["sources"]) == 2
        assert client.patch(f"/api/assistant/records/{ids[1]}", json={"archived": 1}, headers=env.auth_headers()).status_code == 200
        assert client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["total"] == 0
        assert client.patch(f"/api/assistant/records/{ids[1]}", json={"archived": 0}, headers=env.auth_headers()).status_code == 200
        assert client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["total"] == 1


def test_screenshot_is_available_to_automatic_classifier():
    seen = []
    def model(messages, system_prompt="", **kwargs):
        if "信息分流器" in system_prompt:
            seen.append(messages)
            return {"kind": "later"}
        return {"title": "截图中的项目", "brief": "一个项目简介。", "category": "项目", "tags": []}
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        resp = client.post("/api/assistant/submit", data={"mode": "auto"},
                           files={"file": ("screen.png", b"fake-image", "image/png")}, headers=env.auth_headers())
    assert resp.status_code == 201
    assert seen and any(part.get("type") == "image_url" for part in seen[0][0]["content"])


def test_old_notice_cannot_silently_move_deadline():
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            date = "2026-11-15" if "旧通知" in str(messages) else "2026-11-20"
            return {"title": "独立项目材料截止测试", "summary": "提交材料", "highlights": [],
                    "deadline_date": date, "deadline_time": "", "event_keywords": []}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "提交材料",
                    "deadline_date": "2026-11-15", "deadline_time": ""}
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        for text in ("独立项目通知：截止2026年11月20日", "独立项目旧通知：截止2026年11月15日"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers())
            assert resp.status_code == 201
        detail = client.get(f"/api/assistant/records/{resp.json()['id']}", headers=env.auth_headers()).json()
        assert detail["thread"]["deadline_date"] == "2026-11-20"
        assert detail["thread"]["has_conflict"]


def test_different_titles_can_match_same_notice_thread():
    import json
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            title = "开题报告安排" if "第一次" in str(messages) else "研究计划材料补充"
            return {"title": title, "summary": "同一研究计划", "highlights": [],
                    "deadline_date": "", "deadline_time": "", "event_keywords": []}
        if "判断新通知是否" in system_prompt:
            text = messages[0]["content"]
            candidates = json.loads(text.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
            match = next((c for c in candidates if c["title"] == "开题报告安排"), None)
            return {"same_event": bool(match), "thread_id": match["id"] if match else None}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "开题报告及材料补充",
                    "deadline_date": "", "deadline_time": ""}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = []
        for text in ("第一次：研究计划开题报告", "第二次：研究计划需要补充材料"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers())
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        first = client.get(f"/api/assistant/records/{ids[0]}", headers=env.auth_headers()).json()
        second = client.get(f"/api/assistant/records/{ids[1]}", headers=env.auth_headers()).json()
        assert first["thread"]["id"] == second["thread"]["id"]
