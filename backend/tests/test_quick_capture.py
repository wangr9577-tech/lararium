"""Quick Capture 全局便签极速录入真实接口打通与边界测试套件。"""
from __future__ import annotations

import io
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
from app.db import init_db
from app.main import app

env = TestEnvironment(prefix="kruskal_qc_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_quick_capture_flow():
    headers = env.auth_headers()

    # 2. 上传截图测试：POST /api/notes/images
    img_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    file_payload = {"file": ("screenshot_test.png", io.BytesIO(img_data), "image/png")}
    r_img = client.post("/api/notes/images", files=file_payload, headers=headers)
    assert r_img.status_code == 201, f"图片上传失败: {r_img.text}"
    img_url = r_img.json()["url"]
    assert img_url.startswith("/api/notes/images/")

    # 验证上传的图片可以通过接口读取
    r_img_get = client.get(img_url, headers=headers)
    assert r_img_get.status_code == 200
    assert r_img_get.headers["content-type"] == "image/png"

    # 3. 投递目标 1：工作台收集箱 POST /api/workbench/captures
    capture_body = {
        "text": f"关于 Kruskal 闪念极速录入的架构设计 #灵感 #待办\n\n![截图]({img_url})",
        "source": "网页采集",
        "url": "https://github.com/google/kruskal",
        "user_note": "需要整合到工作台",
        "item_id": None,
    }
    r_cap = client.post("/api/workbench/captures", json=capture_body, headers=headers)
    assert r_cap.status_code == 201, f"收集箱录入失败: {r_cap.text}"
    cap_data = r_cap.json()
    assert cap_data["id"] > 0
    assert cap_data["has_text"] is True
    assert cap_data["source"] == "网页采集"
    assert cap_data["url"] == "https://github.com/google/kruskal"
    assert cap_data["item_id"] is None

    # 读取详情验证正文包含 user_note 和图片 markdown
    r_detail = client.get(f"/api/workbench/captures/{cap_data['id']}", headers=headers)
    assert r_detail.status_code == 200
    detail = r_detail.json()
    assert "关于 Kruskal 闪念极速录入" in detail["text"]
    assert "附注: 需要整合到工作台" in detail["text"]
    assert img_url in detail["text"]

    # 验证在收集箱列表(inbox)中能正确检索到
    r_list = client.get("/api/workbench/captures?scope=inbox", headers=headers)
    assert r_list.status_code == 200
    items = r_list.json()["items"]
    assert any(item["id"] == cap_data["id"] for item in items)

    # 4. 投递目标 2：首页今日安排 PUT /api/daynote
    r_day_get = client.get("/api/daynote", headers=headers)
    assert r_day_get.status_code == 200
    initial_content = r_day_get.json().get("content", "")
    new_plan = initial_content + "\n- [ ] 全局随手记测试事项 #待办"
    r_day_put = client.put("/api/daynote", json={"content": new_plan}, headers=headers)
    assert r_day_put.status_code == 200
    r_day_verify = client.get("/api/daynote", headers=headers)
    assert "全局随手记测试事项" in r_day_verify.json()["content"]

    # 5. 投递目标 3：智能助手 POST /api/assistant/submit
    assistant_payload = {
        "text": "整理周会待办事项 #待办",
        "mode": "auto",
        "source_url": "https://example.com/meeting",
        "user_note": "请提取截至时间",
        "source_type": "text",
    }
    r_asst = client.post("/api/assistant/submit", json=assistant_payload, headers=headers)
    assert r_asst.status_code in (200, 201), f"助手递交失败: {r_asst.text}"
    asst_id = r_asst.json().get("id")
    assert asst_id is not None

    print("\n[SUCCESS] Quick Capture 全部目标真实后端接口与闭环流程测试通过！")


if __name__ == "__main__":
    setup_module()
    try:
        test_quick_capture_flow()
    finally:
        teardown_module()
