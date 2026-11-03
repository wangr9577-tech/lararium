"""Notes Quick Memo Card (速记小卡片) 单元与集成测试。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment

env = TestEnvironment(prefix="kruskal_notes_card_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_quick_memo_card_crud():
    headers = env.auth_headers()

    # 1. 创建速记小卡片 POST /api/notes (fmt='card')
    card_payload = {
        "title": "速记：关于卡片功能的设计思路",
        "type": "note",
        "fmt": "card",
        "folder": "",
        "tags": ["灵感", "速记", "设计"],
        "summary": "这是摘要",
        "content": "直接在目录页面创建并输入内容，无需跳入新页面。\n支持多行随记与 Markdown。\n- 待办项 1\n- 待办项 2",
    }
    r_create = client.post("/api/notes", json=card_payload, headers=headers)
    assert r_create.status_code == 201, f"创建卡片失败: {r_create.text}"
    card_data = r_create.json()
    card_id = card_data["id"]
    assert card_data["fmt"] == "card"
    assert card_data["title"] == "速记：关于卡片功能的设计思路"

    # 2. 列表查询 GET /api/notes：验证返回 content 字段
    r_list = client.get("/api/notes", headers=headers)
    assert r_list.status_code == 200
    items = r_list.json()["items"]
    matched = [it for it in items if it["id"] == card_id]
    assert len(matched) == 1
    item = matched[0]
    assert item["fmt"] == "card"
    assert "直接在目录页面创建并输入内容" in item.get("content", "")

    # 3. 详情获取 GET /api/notes/{id}
    r_get = client.get(f"/api/notes/{card_id}", headers=headers)
    assert r_get.status_code == 200
    detail = r_get.json()
    assert detail["fmt"] == "card"
    assert "待办项 2" in detail["content"]

    # 4. 行内快速更新 PUT /api/notes/{id}
    update_payload = {
        "title": "速记：更新后的思路",
        "type": "note",
        "fmt": "card",
        "folder": "",
        "tags": ["灵感", "已完成"],
        "summary": "更新后的摘要",
        "content": "内容已更新，无需跳入新界面！",
    }
    r_put = client.put(f"/api/notes/{card_id}", json=update_payload, headers=headers)
    assert r_put.status_code == 200

    # 再次读取验证更新落盘
    r_get_updated = client.get(f"/api/notes/{card_id}", headers=headers)
    assert r_get_updated.status_code == 200
    assert r_get_updated.json()["title"] == "速记：更新后的思路"
    assert r_get_updated.json()["content"] == "内容已更新，无需跳入新界面！"
