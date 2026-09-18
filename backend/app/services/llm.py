"""本地 LLM 服务：OpenAI 兼容客户端，只连 127.0.0.1 上的 vLLM，数据不出服务器。

所有调用失败必须静默降级（返回 None / 抛 AiUnavailable），由调用方优雅处理，
绝不阻塞主功能。端点/模型/超时来自设置（settings 表 ai.*），否则用 config 默认。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

from .. import config


class AiUnavailable(Exception):
    """AI 服务不可用（未启用 / 连不上 / 超时），调用方捕获后降级。"""


def _settings_ai() -> dict:
    """从 settings 表读 AI 配置（避免循环依赖，直接查 sqlite）。"""
    import sqlite3
    try:
        conn = sqlite3.connect(config.DB_PATH)
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'ai.%'").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            out[k] = v
    return out


def _cfg() -> dict:
    s = _settings_ai()
    enabled = s.get("ai.enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("1", "true", "yes", "on")
    return {
        "enabled": bool(enabled),
        "endpoint": str(s.get("ai.endpoint") or config.AI_ENDPOINT),
        "model": str(s.get("ai.model") or config.AI_MODEL),
        "timeout": int(s.get("ai.timeout") or config.AI_TIMEOUT),
    }


def is_enabled() -> bool:
    return _cfg()["enabled"]


def chat(messages: list[dict], max_tokens: int = 1500, temperature: float = 0.3) -> str:
    """标准 chat 调用，返回补全文本；失败抛 AiUnavailable。"""
    if not is_enabled():
        raise AiUnavailable("AI 服务未启用")
    cfg = _cfg()
    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["endpoint"].rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise AiUnavailable(f"AI 服务不可用: {e}")
    try:
        out = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiUnavailable("AI 返回格式异常")
    return (out or "").strip()