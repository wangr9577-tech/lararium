"""AI 模型服务多渠道配置、保存、切换与连接测试单元测试套件。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment
from app.services import llm

env = TestEnvironment(prefix="kruskal_ai_profiles_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def auth_headers() -> dict[str, str]:
    return env.auth_headers()


def test_ai_profiles_and_switching():
    headers = auth_headers()

    # 1. 查询初始配置与 profiles
    resp = client.get("/api/ai/profiles", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "profiles" in data
    assert len(data["profiles"]) >= 1
    assert data["active_profile_id"] == "xmu-qwen"

    # 2. 保存自定义多模型列表，包含 XMU-Qwen 与新添加的 DeepSeek
    custom_profiles = [
        {
            "id": "xmu-qwen",
            "name": "XMU-Qwen (HPC 隧道)",
            "provider": "xmu-qwen",
            "endpoint": "http://127.0.0.1:18081/v1",
            "model": "qwen3.8-flash-next-unsloth-ud-q4_k_xl",
            "api_key": "unused",
            "timeout": 120,
            "tunnel_hint": "ssh -N -L 127.0.0.1:18081:127.0.0.1:8080 xmu-hpc",
        },
        {
            "id": "my-deepseek",
            "name": "我的 DeepSeek 渠道",
            "provider": "deepseek",
            "endpoint": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test123456",
            "timeout": 60,
            "tunnel_hint": "",
        },
    ]

    put_resp = client.put(
        "/api/settings",
        headers=headers,
        json={
            "updates": {
                "ai.enabled": True,
                "ai.active_profile_id": "my-deepseek",
                "ai.profiles": custom_profiles,
                "ai.endpoint": custom_profiles[1]["endpoint"],
                "ai.model": custom_profiles[1]["model"],
                "ai.api_key": custom_profiles[1]["api_key"],
            }
        },
    )
    assert put_resp.status_code == 200

    # 3. 验证后端生效的激活模型切换为 my-deepseek
    cfg = llm._cfg()
    assert cfg["active_profile_id"] == "my-deepseek"
    assert cfg["model"] == "deepseek-chat"
    assert cfg["api_key"] == "sk-test123456"

    # 4. 再次切换回 xmu-qwen 并持久化
    put_resp2 = client.put(
        "/api/settings",
        headers=headers,
        json={
            "updates": {
                "ai.active_profile_id": "xmu-qwen",
                "ai.endpoint": custom_profiles[0]["endpoint"],
                "ai.model": custom_profiles[0]["model"],
                "ai.api_key": custom_profiles[0]["api_key"],
            }
        },
    )
    assert put_resp2.status_code == 200

    cfg2 = llm._cfg()
    assert cfg2["active_profile_id"] == "xmu-qwen"
    assert cfg2["model"] == "qwen3.8-flash-next-unsloth-ud-q4_k_xl"

    # 5. 测试 /api/ai/test 探测真实 XMU-Qwen 连通性
    test_resp = client.post(
        "/api/ai/test",
        headers=headers,
        json={
            "endpoint": "http://127.0.0.1:18081/v1",
            "model": "qwen3.8-flash-next-unsloth-ud-q4_k_xl",
            "api_key": "unused",
            "timeout": 10,
        },
    )
    assert test_resp.status_code == 200
    t_data = test_resp.json()
    assert t_data["ok"] is True
    assert t_data["latency_ms"] > 0
    assert t_data["model"] == "qwen3.8-flash-next-unsloth-ud-q4_k_xl"
