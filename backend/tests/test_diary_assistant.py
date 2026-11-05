from backend.tests.test_env import TestEnvironment
from app.routers import diary_assistant
from app.services import llm
from app import vault

env = TestEnvironment(prefix="kruskal_diary_assistant_")


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_fragments_draft_apply_and_conflict(monkeypatch):
    client, headers = env.client, env.auth_headers()
    url = "/api/diary-assistant/2026-11-04"
    state = client.get(url, headers=headers).json()
    assert state["diary"]["version"] == "missing"
    fragment = client.post(url + "/fragments", headers=headers, json={"content": "独特的私密原文"}).json()
    path = env.data_dir / "diary-assistant" / "2026-11-04" / (fragment["id"] + ".enc")
    assert "独特的私密原文".encode() not in path.read_bytes()
    monkeypatch.setattr(llm, "chat", lambda *a, **kw: "整理后的日记")
    draft = client.post(url + "/draft", headers=headers, json={"fragment_ids": [fragment["id"]]})
    assert draft.status_code == 200 and draft.json()["content"] == "整理后的日记"
    assert client.get(url, headers=headers).json()["diary"]["version"] == "missing"
    saved = client.put("/api/diary/2026-11-04", headers=headers, json={"content": "原有日记", "mood": "开心", "weather": "晴", "expected_version": "missing"}).json()
    stale = client.post(url + "/apply", headers=headers, json={"content": "草稿", "mode": "append", "expected_version": "missing", "fragment_ids": [fragment["id"]], "fragment_versions": draft.json()["fragment_versions"]})
    assert stale.status_code == 409
    assert client.get(url, headers=headers).json()["fragments"][0]["adopted_at"] is None
    applied = client.post(url + "/apply", headers=headers, json={"content": "草稿", "mode": "append", "expected_version": saved["version"], "fragment_ids": [fragment["id"]], "fragment_versions": draft.json()["fragment_versions"]})
    assert applied.status_code == 200
    assert applied.json()["content"] == "原有日记\n\n草稿"
    assert applied.json()["mood"] == "开心" and applied.json()["weather"] == "晴"
    assert client.get(url, headers=headers).json()["fragments"][0]["adopted_at"]
    assert client.put("/api/diary/2026-11-04", headers=headers, json={"content": "旧编辑器", "expected_version": saved["version"]}).status_code == 409


def test_changed_source_rejects_apply(monkeypatch):
    client, headers = env.client, env.auth_headers()
    url = "/api/diary-assistant/2026-11-06"
    item = client.post(url + "/fragments", headers=headers, json={"content": "初始内容"}).json()
    monkeypatch.setattr(llm, "chat", lambda *a, **kw: "草稿")
    draft = client.post(url + "/draft", headers=headers, json={"fragment_ids": [item["id"]]}).json()
    client.patch(url + "/fragments/" + item["id"], headers=headers, json={"content": "修改之后"})
    response = client.post(url + "/apply", headers=headers, json={"content": draft["content"], "mode": "append", "expected_version": "missing", "fragment_ids": draft["fragment_ids"], "fragment_versions": draft["fragment_versions"]})
    assert response.status_code == 409
    state = client.get(url, headers=headers).json()
    assert state["diary"]["version"] == "missing" and state["fragments"][0]["adopted_at"] is None


def test_draft_failures_preserve_fragments(monkeypatch):
    client, headers = env.client, env.auth_headers()
    url = "/api/diary-assistant/2026-11-05"
    item = client.post(url + "/fragments", headers=headers, json={"content": "保留我"}).json()
    def fail(*args, **kwargs):
        raise llm.AiUnavailable("unavailable")
    monkeypatch.setattr(llm, "chat", fail)
    assert client.post(url + "/draft", headers=headers, json={"fragment_ids": [item["id"]]}).status_code == 503
    assert client.get(url, headers=headers).json()["fragments"][0]["content"] == "保留我"
    assert client.patch(url + "/fragments/" + item["id"], headers=headers, json={"included": False}).status_code == 200
    assert client.post(url + "/draft", headers=headers, json={"fragment_ids": [item["id"]]}).status_code == 400
    assert client.delete(url + "/fragments/" + item["id"], headers=headers).status_code == 200


def test_attachment_fragments_are_encrypted_and_sent_to_model(monkeypatch):
    client, headers = env.client, env.auth_headers()
    url = "/api/diary-assistant/2026-11-07"
    result = client.post(url + "/fragments/upload", headers=headers, data={"content": "这是今天的记录"}, files=[
        ("files", ("note.txt", "私密附件文字".encode(), "text/plain")),
        ("files", ("photo.png", b"fake-png-data", "image/png")),
    ])
    assert result.status_code == 200, result.text
    item = result.json()
    assert len(item["attachments"]) == 2
    asset = diary_assistant._asset_path("2026-11-07", item["id"], item["attachments"][0]["id"])
    assert "私密附件文字".encode() not in asset.read_bytes()
    seen = {}
    def chat(messages, **kwargs):
        seen["messages"] = messages
        return "草稿"
    monkeypatch.setattr(llm, "chat", chat)
    response = client.post(url + "/draft", headers=headers, json={"fragment_ids": [item["id"]]})
    assert response.status_code == 200
    parts = seen["messages"][1]["content"]
    assert "私密附件文字" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    download = client.get(url + f"/fragments/{item['id']}/attachments/{item['attachments'][0]['id']}", headers=headers)
    assert download.content == "私密附件文字".encode()
    assert "attachment" in download.headers["content-disposition"]
    assert client.delete(url + "/fragments/" + item["id"], headers=headers).status_code == 200
    assert not asset.exists()


def test_attachment_upload_rejects_unsupported_files():
    response = env.client.post("/api/diary-assistant/2026-11-07/fragments/upload", headers=env.auth_headers(),
                               files={"files": ("unsafe.html", b"<script></script>", "text/html")})
    assert response.status_code == 400


def test_move_fragment_preserves_encrypted_attachment():
    client, headers = env.client, env.auth_headers()
    old = "/api/diary-assistant/2026-11-08"
    item = client.post(old + "/fragments/upload", headers=headers,
                       files={"files": ("note.txt", b"original attachment", "text/plain")}).json()
    ident, asset = item["id"], item["attachments"][0]["id"]
    moved = client.post(old + f"/fragments/{ident}/move", headers=headers, json={"date": "2026-11-09"})
    assert moved.status_code == 200
    assert not client.get(old, headers=headers).json()["fragments"]
    new = "/api/diary-assistant/2026-11-09"
    assert client.get(new + f"/fragments/{ident}/attachments/{asset}", headers=headers).content == b"original attachment"


def test_lock_change_during_generation_rejects_result(monkeypatch):
    client, headers = env.client, env.auth_headers()
    url = "/api/diary-assistant/2026-11-10"
    item = client.post(url + "/fragments", headers=headers, json={"content": "内容"}).json()
    key = vault.dek()
    def change_epoch(*args, **kwargs):
        vault.set_dek(key)
        return "草稿"
    monkeypatch.setattr(llm, "chat", change_epoch)
    result = client.post(url + "/draft", headers=headers, json={"fragment_ids": [item["id"]]})
    assert result.status_code == 409
