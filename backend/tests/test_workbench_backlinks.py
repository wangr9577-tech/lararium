"""工作台事项与资料双向反向引用（Backlinks）与项目文档关联测试套件。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient
from backend.tests.test_env import TestEnvironment
from app import config, db, vault
from app.auth import bootstrap_admin
from app.db import init_db
from app.main import app

env = TestEnvironment(prefix="kruskal_wb_links_test_")
client = env.client


def setup_module():
    env.setup()
    config.CODE_ROOT = Path(env.tmp_dir)


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

    # 8. 测试项目文档 doc / project_doc 支持
    # 配置临时外部项目文档源
    doc_src_dir = Path(env.tmp_dir) / "sample_project"
    doc_src_dir.mkdir(parents=True, exist_ok=True)
    sample_doc = doc_src_dir / "architecture.md"
    sample_doc.write_text("# 架构设计说明\n\n系统多级软链接设计。", encoding="utf-8")

    with db.db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
            ("doc_sources", json.dumps([{
                "id": "proj1",
                "name": "示例工程",
                "root": str(doc_src_dir),
                "include": [],
                "readonly": False,
            }]))
        )

    # 关联 project_doc
    target_doc_id = "proj1:architecture.md"
    r_link_doc = client.post(f"/api/workbench/items/{parent_id}/links", json={
        "target_type": "doc",
        "target_id": target_doc_id,
    }, headers=headers)
    assert r_link_doc.status_code == 201, f"关联项目文档失败: {r_link_doc.text}"

    # 验证反向引用查询 project_doc / doc
    r_back_doc = client.get(f"/api/workbench/links/backlinks?target_type=doc&target_id={target_doc_id}", headers=headers)
    assert r_back_doc.status_code == 200
    assert len(r_back_doc.json()["items"]) == 1
    assert r_back_doc.json()["items"][0]["id"] == parent_id

    # 用 project_doc 查询也能命中
    r_back_pdoc = client.get(f"/api/workbench/links/backlinks?target_type=project_doc&target_id={target_doc_id}", headers=headers)
    assert r_back_pdoc.status_code == 200
    assert len(r_back_pdoc.json()["items"]) == 1

    # 9. 测试 selector 检索 doc
    r_sel = client.get("/api/workbench/selector?kind=all&q=架构", headers=headers)
    assert r_sel.status_code == 200
    items = r_sel.json()["items"]
    assert any(it["target_type"] == "doc" and "架构" in it["title"] for it in items)


if __name__ == "__main__":
    setup_module()
    try:
        test_workbench_links_and_backlinks()
    finally:
        teardown_module()
