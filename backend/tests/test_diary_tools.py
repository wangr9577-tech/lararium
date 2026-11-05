import json
from datetime import datetime, timedelta
from uuid import uuid4

from backend.tests.test_env import TestEnvironment
from app.services import llm
from app.routers import diary_tools

env = TestEnvironment(prefix="kruskal_diary_tools_")


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_suggestions_and_explicit_task(monkeypatch):
    client, headers = env.client, env.auth_headers()
    date = "2026-11-08"
    base = f"/api/diary-assistant/{date}"
    item = client.post(base + "/fragments", headers=headers, json={"content": "今天想起明天交报告"}).json()
    output = {"suggestions": [{"fragment_id": item["id"], "diary": True, "tasks": [{"title": "交报告"}]}]}
    monkeypatch.setattr(llm, "chat", lambda *a, **kw: json.dumps(output, ensure_ascii=False))
    tools = f"/api/diary-tools/{date}"
    suggestion = client.post(tools + "/suggest", headers=headers, json={"fragment_ids": [item["id"]]}).json()
    assert suggestion["suggestions"] == output["suggestions"]
    assert client.get("/api/schedule/day?date=2026-11-09", headers=headers).json()["items"] == []
    assert client.get(base, headers=headers).json()["diary"]["version"] == "missing"
    task = {"fragment_id": item["id"], "fragment_version": suggestion["fragment_versions"][item["id"]], "title": "交报告", "date": "2026-11-09", "idempotency_key": str(uuid4())}
    created = client.post(tools + "/tasks", headers=headers, json=task)
    assert created.status_code == 201
    assert client.post(tools + "/tasks", headers=headers, json=task).json() == created.json()
    assert client.post(tools + "/tasks", headers=headers, json={**task, "title": "不同任务"}).status_code == 409
    assert len(client.get("/api/schedule/day?date=2026-11-09", headers=headers).json()["items"]) == 1
    client.patch(base + "/fragments/" + item["id"], headers=headers, json={"content": "已更新"})
    assert client.post(tools + "/tasks", headers=headers, json=task).json() == created.json()
    assert client.post(tools + "/tasks", headers=headers, json={**task, "idempotency_key": str(uuid4())}).status_code == 409
    assert client.get(base, headers=headers).json()["fragments"][0]["content"] == "已更新"


def test_invalid_model_output_does_not_write(monkeypatch):
    client, headers = env.client, env.auth_headers()
    date = "2026-11-10"
    item = client.post(f"/api/diary-assistant/{date}/fragments", headers=headers, json={"content": "原文"}).json()
    monkeypatch.setattr(llm, "chat", lambda *a, **kw: '{"suggestions": []}')
    response = client.post(f"/api/diary-tools/{date}/suggest", headers=headers, json={"fragment_ids": [item["id"]]})
    assert response.status_code == 502
    assert client.get(f"/api/diary-assistant/{date}", headers=headers).json()["fragments"][0]["content"] == "原文"


def test_suggest_uses_vision_for_image_only_fragments(monkeypatch):
    client, headers = env.client, env.auth_headers()
    date = "2026-11-12"
    base = f"/api/diary-assistant/{date}"
    item = client.post(base + "/fragments/upload", headers=headers,
                       files={"files": ("photo.png", b"image bytes", "image/png")}).json()
    seen = {}
    def respond(messages, **kwargs):
        seen["messages"] = messages
        return json.dumps({"suggestions": [{"fragment_id": item["id"], "diary": True, "tasks": []}]})
    monkeypatch.setattr(llm, "chat", respond)
    result = client.post(f"/api/diary-tools/{date}/suggest", headers=headers, json={"fragment_ids": [item["id"]]})
    assert result.status_code == 200
    parts = seen["messages"][1]["content"]
    assert item["id"] in parts[0]["text"] and "图片 1" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_scheduled_draft_is_encrypted_and_never_applied(monkeypatch):
    client, headers = env.client, env.auth_headers()
    date = "2026-11-11"
    base = f"/api/diary-assistant/{date}"
    item = client.post(base + "/fragments", headers=headers, json={"content": "私密日记片段"}).json()
    url = f"/api/diary-tools/{date}/scheduled-draft"
    run_at = (datetime.now() + timedelta(minutes=1)).isoformat(timespec="seconds")
    request = {"fragment_ids": [item["id"]], "run_at": run_at}
    assert client.post(url, headers=headers, json=request).json()["status"] == "queued"
    assert client.post(url, headers=headers, json=request).status_code == 409
    monkeypatch.setattr(llm, "chat", lambda *a, **kw: "整理草稿")
    diary_tools.run_due_scheduled(datetime.now() + timedelta(minutes=2))
    job = client.get(url, headers=headers).json()
    assert job["status"] == "ready" and job["content"] == "整理草稿"
    assert "整理草稿".encode() not in diary_tools._scheduled_path(date).read_bytes()
    assert client.get(base, headers=headers).json()["diary"]["version"] == "missing"
    assert client.delete(url, headers=headers).status_code == 200
