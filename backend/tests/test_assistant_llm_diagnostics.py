"""助手大模型接入、多模态视觉协议、连通性诊断与错误可见重试机制测试套件。

覆盖验收要求：
1. GET /api/assistant/diagnostics/llm 真实探测大模型连通性与延迟，若不通返回明确的 SSH 隧道命令；
2. format_multimodal_message 严格遵循 OpenAI Completions 视觉多模态协议；
3. 多模态请求失败时严禁静默丢弃图片重试，保留真实失败原因；
4. 模型不可用或异常时作业状态记录为 status='failed'，保存真实 error_msg，严禁伪装为成功；
5. 提供用户明确触发的规则降级接口 POST /api/assistant/records/{id}/fallback-rule，把控制权交给用户。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment
from app import config, vault
from app.db import db
from app.routers import assistant as asst_mod
from app.services import llm

env = TestEnvironment(prefix="kruskal_llm_diag_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def auth_headers() -> dict[str, str]:
    return env.auth_headers()


# ==================== 测试用例 ====================

def test_1_llm_diagnostics_offline():
    """测试大模型端点离线时的诊断接口输出，验证错误提示。"""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("[Errno 111] Connection refused")):
        resp = client.get("/api/assistant/diagnostics/llm", headers=auth_headers())
        assert resp.status_code == 200, f"诊断接口应返回 200: {resp.text}"
        data = resp.json()
        assert data["connected"] is False
        assert "11434" in data["endpoint"] or "http" in data["endpoint"]
        assert "Connection refused" in data["error_hint"] or "连接" in data["error_hint"]


def test_2_llm_diagnostics_connected():
    """测试大模型端点在线时的诊断接口输出。"""
    active_model = llm._cfg()["model"]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"object": "list", "data": [{"id": active_model}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        resp = client.get("/api/assistant/diagnostics/llm", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["latency_ms"] >= 1
        assert data["model"] == active_model
        assert data["error_hint"] == ""


def test_3_format_multimodal_message_openai_spec():
    """测试视觉多模态消息构造完全符合 OpenAI Completions 协议。"""
    test_bytes = b"fake-png-binary-content"
    msg = llm.format_multimodal_message("user", "请提取图中的通知要求", [(test_bytes, "image/png")])

    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert len(msg["content"]) == 2

    text_part = msg["content"][0]
    assert text_part["type"] == "text"
    assert text_part["text"] == "请提取图中的通知要求"

    img_part = msg["content"][1]
    assert img_part["type"] == "image_url"
    b64_str = base64.b64encode(test_bytes).decode("ascii")
    assert img_part["image_url"]["url"] == f"data:image/png;base64,{b64_str}"

    # 测试当 text 为空时，自动注入默认提示词，防止模型拒绝空文本 prompt
    empty_text_msg = llm.format_multimodal_message("user", "", [(test_bytes, "image/png")])
    assert empty_text_msg["content"][0]["type"] == "text"
    assert len(empty_text_msg["content"][0]["text"]) > 0


def test_4_no_silent_image_dropping_on_error():
    """测试当视觉请求失败时，绝不在背后静默剔除图片重试，必须保留真实的失败原因。"""
    test_bytes = b"fake-image"
    msg = llm.format_multimodal_message("user", "请看图", [(test_bytes, "image/png")])

    call_count = 0

    def mock_do_request(cfg, messages, max_tokens, temperature):
        nonlocal call_count
        call_count += 1
        # 模拟模型端点返回 400 不支持视觉
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:11434/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=MagicMock(read=lambda *args: b'{"error": "Vision input is not supported by this worker"}'),
        )

    with patch("app.services.llm._do_request", side_effect=mock_do_request), \
         patch("app.services.llm.is_enabled", return_value=True):
        try:
            llm.chat([msg])
            assert False, "应抛出 AiUnavailable 异常"
        except llm.AiUnavailable as e:
            err_text = str(e)
            assert "视觉多模态模型调用失败" in err_text or "Vision input" in err_text

    # 严禁在背后剔除图片进行第二次请求（call_count 必须为 1）
    assert call_count == 1, f"严禁静默重试剔除图片！实际调用次数为 {call_count}"


def test_5_failure_visibility_and_error_msg_preservation():
    """测试大模型调用失败时，作业状态记录为 status='failed' 并保留真实的 error_msg，严禁伪成功。"""
    n_text = "【紧急项目申报延期】关于2026年重点研究计划申报延期至12月1日。"
    simulated_error = "无法连接至模型端点 (Connection Refused)。"

    with patch("app.services.llm.is_enabled", return_value=True), \
         patch("app.services.llm.chat_structured", side_effect=llm.AiUnavailable(simulated_error)):
        submit_resp = client.post(
            "/api/assistant/submit",
            json={"text": n_text, "mode": "notice", "user_note": "关注新截止时间"},
            headers=auth_headers(),
        )
        assert submit_resp.status_code == 201
        rec_id = submit_resp.json()["id"]

    # 验证 1：记录状态必须为 failed，绝不能用前两行伪装成 ready
    rec_resp = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers())
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["status"] == "failed", f"失败必须可见，当前状态: {rec_data['status']}"
    assert simulated_error in rec_data["error_msg"]

    # 验证 2：列表接口中也透出 error_msg 与 failed 状态
    list_resp = client.get("/api/assistant/records?scope=all", headers=auth_headers())
    item_in_list = next((it for it in list_resp.json()["items"] if it["id"] == rec_id), None)
    assert item_in_list is not None
    assert item_in_list["status"] == "failed"
    assert simulated_error in item_in_list["error_msg"]

    # 验证 3：原始输入文本完整保留在加密 raw.enc 中，严禁清理
    assert rec_data["raw_text"] == n_text


def test_6_explicit_user_rule_fallback_control():
    """测试用户显式点击「改用规则降级整理」时，才切换为规则整理并置为 ready，把控制权交还给用户。"""
    n_text = (
        "【2026年国家重点实验室学术研讨会】\n"
        "定于2026年12月20日09:00在综合楼召开。\n"
        "参会报名截止时间：2026-12-10 18:00。"
    )

    # 1. 模拟初次模型处理失败
    with patch("app.services.llm.is_enabled", return_value=True), \
         patch("app.services.llm.chat_structured", side_effect=llm.AiUnavailable("模型超时")):
        submit_resp = client.post(
            "/api/assistant/submit",
            json={"text": n_text, "mode": "notice", "user_note": "研讨会报名提醒"},
            headers=auth_headers(),
        )
        assert submit_resp.status_code == 201
        rec_id = submit_resp.json()["id"]

    rec_fail = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert rec_fail["status"] == "failed"

    # 2. 用户在前端显式点击 [改用规则降级整理]
    fb_resp = client.post(f"/api/assistant/records/{rec_id}/fallback-rule", headers=auth_headers())
    assert fb_resp.status_code == 200
    assert fb_resp.json()["ok"] is True

    # 3. 验证：显式降级后状态成功流转为 ready，并提取出截止日期与标题
    rec_ready = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert rec_ready["status"] == "ready", f"用户显式选择规则降级后状态应为 ready: {rec_ready['status']}"
    assert "国家重点实验室学术研讨会" in rec_ready["title"]
    assert rec_ready["thread"] is not None
    assert rec_ready["thread"]["deadline_date"] == "2026-12-10"
