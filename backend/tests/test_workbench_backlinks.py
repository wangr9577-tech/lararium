"""工作台事项与资料双向反向引用（Backlinks）测试套件。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient
from backend.tests.test_env import TestEnvironment
from app import config, db, vault
from app.db import init_db
from app.main import app

env = TestEnvironment(prefix="kruskal_wb_links_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_workbench_links_and_backlinks():
    headers = env.auth_headers()

    # 2. 创建真实测试笔记
    r_note = client.post("/api/notes", json={
        "title": "测试双向链接笔记",
        "type": "note",
        "folder": "科研项目",
        "tags": ["测试"],
        "content": "# 测试正文",
        "summary": "双向软链接摘要",
    }, headers=headers)
    assert r_note.status_code == 201, f"新建笔记失败: {r_note.text}"
    note_id = r_note.json()["id"]

    # 3. 创建真实测试论文
    papers_dir = config.DATA_DIR / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    paper_id = "testpaper1234"
    vault.write_json(papers_dir / f"{paper_id}.json", {
        "id": paper_id,
        "title": "Attention Is All You Need",
        "author": "Vaswani et al.",
        "status": "精读",
        "tags": ["Transformer"],
    })

    # 4. 创建工作台父事项与子事项
    r_parent = client.post("/api/workbench/items", json={"title": "高校重点实验室申报推进"}, headers=headers)
    assert r_parent.status_code == 201, f"新建父事项失败: {r_parent.text}"
    parent_id = r_parent.json()["id"]

    r_child = client.post("/api/workbench/items", json={
        "title": "编写项目技术方案",
        "parent_id": parent_id,
    }, headers=headers)
    assert r_child.status_code == 201, f"新建子事项失败: {r_child.text}"
    child_id = r_child.json()["id"]

    # 5. 建立关联：子事项 -> 笔记；父事项 -> 论文
    r_link1 = client.post(f"/api/workbench/items/{child_id}/links", json={
        "target_type": "note",
        "target_id": note_id,
    }, headers=headers)
    assert r_link1.status_code == 201, f"关联笔记失败: {r_link1.text}"
    assert r_link1.json()["created"] is True

    r_link2 = client.post(f"/api/workbench/items/{parent_id}/links", json={
        "target_type": "paper",
        "target_id": paper_id,
    }, headers=headers)
    assert r_link2.status_code == 201, f"关联论文失败: {r_link2.text}"

    # 验证 SQLite workbench_links 持久化
    with db.db() as conn:
        row = conn.execute("SELECT * FROM workbench_links WHERE item_id=? AND target_id=?", (child_id, note_id)).fetchone()
        assert row is not None
        assert row["target_type"] == "note"

    # 6. 测试反向引用接口：GET /api/workbench/links/backlinks?target_type=note&target_id=<note_id>
    r_back_note = client.get(f"/api/workbench/links/backlinks?target_type=note&target_id={note_id}", headers=headers)
    assert r_back_note.status_code == 200, f"反向引用查询失败: {r_back_note.text}"
    data_note = r_back_note.json()
    assert "items" in data_note
    assert len(data_note["items"]) == 1
    item = data_note["items"][0]
    assert item["id"] == child_id
    assert item["title"] == "编写项目技术方案"
    assert item["parent_title"] == "高校重点实验室申报推进"
    assert "updated_at" in item

    # 7. 测试论文反向引用接口：GET /api/workbench/links/backlinks?target_type=paper&target_id=<paper_id>
    r_back_paper = client.get(f"/api/workbench/links/backlinks?target_type=paper&target_id={paper_id}", headers=headers)
    assert r_back_paper.status_code == 200, f"论文反向引用查询失败: {r_back_paper.text}"
    data_paper = r_back_paper.json()
    assert len(data_paper["items"]) == 1
    assert data_paper["items"][0]["id"] == parent_id
    assert data_paper["items"][0]["title"] == "高校重点实验室申报推进"
    assert data_paper["items"][0]["parent_title"] is None


if __name__ == "__main__":
    setup_module()
    try:
        test_workbench_links_and_backlinks()
    finally:
        teardown_module()
