"""本地 LLM 服务：OpenAI 兼容客户端，只连 127.0.0.1 上的 vLLM，数据不出服务器。

所有调用失败必须静默降级（返回 None / 抛 AiUnavailable），由调用方优雅处理，
绝不阻塞主功能。端点/模型/超时来自设置（settings 表 ai.*），否则用 config 默认。
支持结构化 JSON 提取与多模态降级，以及未启用 AI 时的启发式规则提取。
"""
from __future__ import annotations

import base64
import ast
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from .. import config


class AiUnavailable(Exception):
    """AI 服务不可用（未启用 / 连不上 / 超时 / 格式异常），调用方捕获后降级。"""


def _settings_ai() -> dict:
    """读取 AI 配置：
    1. 优先从受 .gitignore 保护的独立本地私有配置文件（local_settings.json）读取；
    2. 若未配置则从 settings 数据库读取；
    3. 保证用户的 API Key、端点和模型信息仅存留在本地专属私有文件，绝不进入 Git 代码。
    """
    out = {}

    # 1. 尝试从本地私有配置文件读取
    if hasattr(config, "LOCAL_SETTINGS_PATH") and config.LOCAL_SETTINGS_PATH.is_file():
        try:
            raw = json.loads(config.LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k.startswith("ai."):
                        out[k] = v
        except Exception:
            pass

    # 2. 如果本地文件读取到了完整的配置，直接返回
    if out.get("ai.profiles") or out.get("ai.endpoint"):
        return out

    # 3. 否则读取本地 SQLite 数据库
    import sqlite3
    try:
        conn = sqlite3.connect(config.DB_PATH)
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'ai.%'").fetchall()
        conn.close()
    except sqlite3.Error:
        return out

    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            out[k] = v
    return out


DEFAULT_PROFILES = [
    {
        "id": "default",
        "name": "Local Ollama (默认)",
        "provider": config.AI_PROVIDER or "ollama",
        "endpoint": config.AI_ENDPOINT or "http://127.0.0.1:11434/v1",
        "model": config.AI_MODEL or "qwen2.5:7b",
        "api_key": config.AI_API_KEY or "unused",
        "timeout": config.AI_TIMEOUT or 60,
        "tunnel_hint": config.AI_TUNNEL_HINT or "",
    },
]


def get_profiles_and_active() -> tuple[list[dict], str, bool]:
    """读取所有保存的模型 Profile、当前激活的 Profile ID 以及总开关状态。"""
    s = _settings_ai()
    enabled_val = s.get("ai.enabled")
    if enabled_val is None:
        env_val = os.environ.get("KRUSKAL_AI_ENABLED")
        if env_val is not None:
            enabled = env_val.lower() in ("1", "true", "yes", "on")
        else:
            enabled = True
    elif isinstance(enabled_val, str):
        enabled = enabled_val.lower() in ("1", "true", "yes", "on")
    else:
        enabled = bool(enabled_val)

    profiles_raw = s.get("ai.profiles")
    if profiles_raw and isinstance(profiles_raw, list) and len(profiles_raw) > 0:
        profiles = [dict(p) for p in profiles_raw]
    else:
        profiles = [dict(p) for p in DEFAULT_PROFILES]
        # 若旧版本单独保存了 endpoint/model，将其并入默认激活项
        saved_ep = s.get("ai.endpoint")
        saved_model = s.get("ai.model")
        if saved_ep or saved_model:
            profiles[0]["endpoint"] = str(saved_ep or profiles[0]["endpoint"])
            profiles[0]["model"] = str(saved_model or profiles[0]["model"])
            if s.get("ai.api_key"):
                profiles[0]["api_key"] = str(s.get("ai.api_key"))
            if s.get("ai.provider"):
                profiles[0]["provider"] = str(s.get("ai.provider"))
            if s.get("ai.timeout"):
                profiles[0]["timeout"] = int(s.get("ai.timeout"))

    # 兼容性迁移：若数据库保存了历史旧配置 (如包含特定私有服务器环境的旧模板)，平滑迁移为中性模板
    for p in profiles:
        pid = str(p.get("id", "")).lower()
        hint = str(p.get("tunnel_hint", "")).lower()
        name = str(p.get("name", "")).lower()
        if "qwen" in pid and ("hpc" in pid or "strata" in pid or pid.startswith("x")):
            p["id"] = "remote-tunnel"
        if any(k in hint for k in ["hpc", "strata"]):
            p["tunnel_hint"] = "ssh -N -L 127.0.0.1:8080:127.0.0.1:8000 user@remote-host"
        if any(k in name for k in ["hpc", "strata"]):
            p["name"] = "远程 SSH 隧道"

    active_id = str(s.get("ai.active_profile_id") or "")
    if "qwen" in active_id.lower() and (active_id.lower().startswith("x") or "hpc" in active_id.lower()):
        active_id = "remote-tunnel"

    if not any(p.get("id") == active_id for p in profiles):
        active_id = profiles[0]["id"]

    return profiles, active_id, enabled


def _cfg() -> dict:
    profiles, active_id, enabled = get_profiles_and_active()
    active_profile = next((p for p in profiles if p.get("id") == active_id), profiles[0])

    return {
        "enabled": enabled,
        "active_profile_id": active_id,
        "provider": str(active_profile.get("provider") or config.AI_PROVIDER),
        "endpoint": str(active_profile.get("endpoint") or config.AI_ENDPOINT),
        "model": str(active_profile.get("model") or config.AI_MODEL),
        "api_key": str(active_profile.get("api_key") or config.AI_API_KEY),
        "timeout": int(active_profile.get("timeout") or config.AI_TIMEOUT),
        "tunnel_hint": str(active_profile.get("tunnel_hint") or config.AI_TUNNEL_HINT),
        "name": str(active_profile.get("name") or active_id),
    }


def is_enabled() -> bool:
    return _cfg()["enabled"]


def normalize_endpoint(url: str) -> str:
    """标准 OpenAI 兼容 Endpoint 规范化：
    1. 去除两端空白与尾部斜杠；
    2. 若未带协议头，默认补充 http://；
    3. 若以 /chat/completions 或 /models 结尾，剥离为 Base URL；
    4. 若未以 /v1 结尾且非特定第三方多级路径，自动规范化补齐 /v1。
    """
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "http://" + u
    if u.endswith("/chat/completions"):
        u = u[:-len("/chat/completions")].rstrip("/")
    elif u.endswith("/models"):
        u = u[:-len("/models")].rstrip("/")
    if not (u.endswith("/v1") or "/v1/" in u or u.endswith("/v1beta") or "/api/" in u):
        u = u + "/v1"
    return u


def _do_request(cfg: dict, messages: list[dict], max_tokens: int, temperature: float) -> str:
    endpoint = normalize_endpoint(cfg.get("endpoint") or "")
    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key") and cfg["api_key"] != "unused":
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        msg = data["choices"][0]["message"]
        out = msg.get("content")
        # 推理过程不是最终答案，不能将其作为结构化结果使用。
    except (KeyError, IndexError, TypeError):
        raise AiUnavailable("AI 返回格式异常")
    if isinstance(out, list):
        # 兼容部分 OpenAI 兼容服务返回的文本片段数组。
        out = "\n".join(str(part.get("text", "")) for part in out
                        if isinstance(part, dict) and part.get("type") in ("text", "output_text"))
    if out is not None and not isinstance(out, str):
        raise AiUnavailable("AI 返回的最终答案不是文本")
    return (out or "").strip()


def chat(messages: list[dict], max_tokens: int = 1500, temperature: float = 0.3,
         timeout_override: int | None = None) -> str:
    """标准 chat 调用，返回补全文本；支持多模态；失败抛 AiUnavailable。

    严禁静默丢弃图片或隐蔽移除视觉输入！若请求失败，必须保留真实的失败原因。
    """
    if not is_enabled():
        cfg = _cfg()
        raise AiUnavailable(f"AI 服务未启用。请检查配置或开启 SSH 隧道: {cfg['tunnel_hint']}")
    cfg = _cfg()
    if timeout_override is not None or max_tokens >= 100000:
        cfg = dict(cfg)
        cfg["timeout"] = max(cfg["timeout"], timeout_override or 180)
    try:
        return _do_request(cfg, messages, max_tokens, temperature)
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        has_image = any(
            isinstance(m.get("content"), list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"]
            )
            for m in messages
        )
        if has_image:
            # 严禁静默丢弃图片与无声降级！保留多模态失败真实原因
            raise AiUnavailable(
                f"视觉多模态模型调用失败(HTTP {e.code}): {err_body or e.reason}。模型可能未开启视觉模块或无法解析图像。请检查模型或 SSH 隧道: {cfg['tunnel_hint']}"
            )
        raise AiUnavailable(f"AI 服务不可用(HTTP {e.code}): {err_body or e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        has_image = any(
            isinstance(m.get("content"), list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"]
            )
            for m in messages
        )
        img_hint = "视觉模型接口连接超时或服务未就绪" if has_image else "AI 服务连接不可用"
        raise AiUnavailable(
            f"{img_hint}: 无法连接至 {cfg['endpoint']} ({e})。请确认模型已启动或运行 SSH 隧道: {cfg['tunnel_hint']}"
        )


def _parse_json(text: str) -> dict:
    """提取完整对象；允许代码块、说明文字、尾逗号和 Python 字面量。

    不补全截断内容，不使用 eval，不从未闭合的外层对象提取内部片段。
    """
    if not isinstance(text, str):
        raise ValueError("模型最终答案不是文本")
    s = re.sub(r"<think\b[^>]*>[\s\S]*?</think\s*>", "", text, flags=re.I).strip().lstrip("\ufeff")
    if re.search(r"</?think\b", s, flags=re.I):
        raise ValueError("模型思考输出未结束，缺少完整的最终答案")

    def json_compatible(value):
        if value is None or isinstance(value, (str, bool, int)):
            return True
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, list):
            return all(json_compatible(item) for item in value)
        if isinstance(value, dict):
            return all(isinstance(k, str) and json_compatible(v) for k, v in value.items())
        return False

    def parse_candidate(candidate: str):
        # strict=False 接受字符串里的原始换行；不会修补缺失内容。
        try:
            result = json.loads(candidate, strict=False)
            if isinstance(result, dict) and json_compatible(result):
                return result
        except (ValueError, TypeError):
            pass
        # 只删除字符串外、紧邻 } 或 ] 的尾逗号，不改动文本字段。
        cleaned = []
        in_string = False
        escape = False
        for pos, ch in enumerate(candidate):
            if in_string:
                cleaned.append(ch)
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            if ch == "," and candidate[pos + 1:].lstrip().startswith(("}", "]")):
                continue
            cleaned.append(ch)
        try:
            result = json.loads("".join(cleaned), strict=False)
            if isinstance(result, dict) and json_compatible(result):
                return result
        except (ValueError, TypeError):
            pass
        # 有些服务输出 Python 风格单引号/True/None；literal_eval 只解析字面量。
        try:
            result = ast.literal_eval(candidate)
            if isinstance(result, dict) and json_compatible(result):
                return result
        except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
            pass
        return None

    # 扫描顶层花括号并正确处理字符串内的花括号及转义。
    start = None
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(s):
        if start is None:
            if char == "{":
                start, depth, quote, escaped = index, 1, None, False
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start:index + 1]
                result = parse_candidate(candidate)
                if result is not None:
                    return result
                start = None

    if not s:
        raise ValueError("模型没有返回最终答案")
    raise ValueError("无法从输出中提取完整的 JSON 对象")


def chat_structured(messages: list[dict], system_prompt: str = "",
                    max_tokens: int = 100000, temperature: float = 0.2,
                    required_keys: tuple[str, ...] = (), timeout_override: int | None = None) -> dict:
    """请求结构化 JSON 输出，并进行健壮解析与校验。"""
    sys_instruction = "请严格返回合法的 JSON 对象，不要输出包含 markdown 外围解释的其他说明。"
    full_sys = f"{system_prompt}\n\n{sys_instruction}" if system_prompt else sys_instruction

    msgs = []
    has_system = False
    for m in messages:
        if m.get("role") == "system":
            msgs.append({"role": "system", "content": f"{m.get('content', '')}\n\n{full_sys}"})
            has_system = True
        else:
            msgs.append(m)
    if not has_system:
        msgs.insert(0, {"role": "system", "content": full_sys})

    def parse_and_check(text: str) -> dict:
        result = _parse_json(text)
        missing = [key for key in required_keys if key not in result]
        if missing:
            raise ValueError("JSON 对象缺少必要字段：" + "、".join(missing))
        return result

    call_options = {"max_tokens": max_tokens, "temperature": temperature}
    if timeout_override is not None:
        call_options["timeout_override"] = timeout_override
    raw_text = chat(msgs, **call_options)
    try:
        return parse_and_check(raw_text)
    except ValueError:
        # 保留原始文字和图片，再请求一次完整答案；不把推理内容当结果，
        # 也不将用户资料或模型输出写入日志。
        retry_msgs = msgs + [{"role": "user", "content":
            "上次回答无法解析。请重新完成原任务，只输出一个完整有效的 JSON 对象，"
            "使用双引号，不要输出思考过程、代码块或解释。"}]
        retry_options = dict(call_options)
        retry_options["temperature"] = 0.0
        retry_text = chat(retry_msgs, **retry_options)
        try:
            return parse_and_check(retry_text)
        except ValueError as e:
            raise AiUnavailable(f"AI 两次输出均未通过 JSON 解析或字段检查：{e}。请检查模型是否输出了完整最终答案，或稍后重试。") from e


def format_multimodal_message(
    role: str,
    text: str,
    images: list[tuple[bytes, str] | str | dict] | None = None,
) -> dict:
    """构造符合 OpenAI Completions 视觉协议的多模态消息内容，支持 base64 与图像 URL。"""
    if not images:
        return {"role": role, "content": text or ""}

    parts: list[dict] = []
    prompt_text = (text or "").strip()
    if not prompt_text:
        prompt_text = "请观察并提取图中所有的关键信息、文字要求与事实内容。"
    parts.append({"type": "text", "text": prompt_text})

    for item in images:
        if isinstance(item, tuple) and len(item) == 2:
            b_data, m_type = item
            if isinstance(b_data, bytes):
                b64 = base64.b64encode(b_data).decode("ascii")
                url = f"data:{m_type};base64,{b64}"
            elif isinstance(b_data, str) and (b_data.startswith("data:") or b_data.startswith("http")):
                url = b_data
            else:
                continue
            parts.append({
                "type": "image_url",
                "image_url": {"url": url}
            })
        elif isinstance(item, str):
            if item.startswith("data:") or item.startswith("http"):
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": item}
                })
        elif isinstance(item, dict) and item.get("type") == "image_url":
            parts.append(item)

    return {"role": role, "content": parts}


def fetch_endpoint_models(endpoint: str, api_key: str = "", timeout: int = 8) -> list[str]:
    """尝试从 endpoint 的 /models 接口获取可用模型 ID 列表。"""
    ep = normalize_endpoint(endpoint)
    if not ep:
        return []
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "unused":
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{ep}/models", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = []
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if isinstance(item, dict) and item.get("id"):
                        models.append(str(item["id"]))
            return models
    except Exception:
        return []


def check_diagnostics(override_cfg: dict | None = None) -> dict:
    """真实探测大模型服务连通性与模型可用性。
    1. 探测 /models 获取远端真实已加载的模型列表；
    2. 严格核对配置的 model 是否存在；
    3. 发送微型 chat/completions 推理测试，彻底避免端口监听成功但模型无法调用的假阳性！
    """
    if override_cfg:
        cfg = {
            "enabled": True,
            "provider": str(override_cfg.get("provider") or "openai"),
            "endpoint": str(override_cfg.get("endpoint") or "").rstrip("/"),
            "model": str(override_cfg.get("model") or "").strip(),
            "api_key": str(override_cfg.get("api_key") or ""),
            "timeout": int(override_cfg.get("timeout") or 60),
            "tunnel_hint": str(override_cfg.get("tunnel_hint") or ""),
            "name": str(override_cfg.get("name") or "临时测试配置"),
        }
    else:
        cfg = _cfg()

    endpoint = normalize_endpoint(cfg.get("endpoint") or "")
    model = cfg.get("model", "").strip()
    provider = cfg.get("provider", "openai")
    tunnel_hint = cfg.get("tunnel_hint", "")
    name = cfg.get("name", "")

    if not cfg["enabled"]:
        return {
            "connected": False,
            "latency_ms": 0,
            "name": name,
            "model": model,
            "provider": provider,
            "endpoint": endpoint,
            "available_models": [],
            "error_hint": f"AI 服务总开关未启用 (ai.enabled=False)。请在设置中打开「启用 AI 服务」开关，或运行 SSH 隧道: {tunnel_hint}",
        }

    if not endpoint:
        return {
            "connected": False,
            "latency_ms": 0,
            "name": name,
            "model": model,
            "provider": provider,
            "endpoint": "",
            "available_models": [],
            "error_hint": "未配置 API 服务地址 (Endpoint)",
        }

    start = time.perf_counter()
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key") and cfg["api_key"] != "unused":
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    # 1. 尝试获取服务端所有已加载/可用模型列表
    available_models = fetch_endpoint_models(endpoint, cfg.get("api_key", ""), timeout=min(cfg["timeout"], 6))

    # 2. 如果成功抓取到模型列表，且用户配置了 model，但该 model 不在列表中
    if available_models and model and model not in available_models:
        latency = int((time.perf_counter() - start) * 1000)
        return {
            "connected": False,
            "latency_ms": latency,
            "name": name,
            "model": model,
            "provider": provider,
            "endpoint": endpoint,
            "available_models": available_models,
            "error_hint": f"端点连接成功，但未找到配置的模型 '{model}'！服务端当前可用模型: {available_models}。请将模型配置修改为有效模型名称。",
        }

    # 3. 执行真实 chat/completions 推理探测
    test_model = model or (available_models[0] if available_models else "default")
    ping_body = json.dumps({
        "model": test_model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 10,
    }).encode("utf-8")
    ping_req = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=ping_body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(ping_req, timeout=min(cfg["timeout"], 60)) as resp:
            resp.read()
            latency = int((time.perf_counter() - start) * 1000)
            return {
                "connected": True,
                "latency_ms": max(1, latency),
                "name": name,
                "model": test_model,
                "provider": provider,
                "endpoint": endpoint,
                "available_models": available_models,
                "error_hint": "",
            }
    except Exception as e_ping:
        latency = int((time.perf_counter() - start) * 1000)
        err_msg = str(e_ping)
        if isinstance(e_ping, urllib.error.HTTPError):
            try:
                err_body = e_ping.read().decode("utf-8", errors="ignore")
                if err_body:
                    err_msg = f"HTTP {e_ping.code}: {err_body[:200]}"
            except Exception:
                pass
        return {
            "connected": False,
            "latency_ms": latency,
            "name": name,
            "model": test_model,
            "provider": provider,
            "endpoint": endpoint,
            "available_models": available_models,
            "error_hint": f"模型调用失败: {err_msg}。若使用远程模型，请在本机运行 SSH 隧道命令: {tunnel_hint}",
        }


def chat_stream(messages: list[dict], max_tokens: int = 1500,
                temperature: float = 0.3) -> Iterator[str]:
    """流式 chat：逐个产出 OpenAI 兼容 SSE 的增量文本；失败抛 AiUnavailable。

    与 chat 共用同一套配置与错误语义；服务端不支持 stream 时，回退解析完整 JSON。
    """
    if not is_enabled():
        cfg = _cfg()
        raise AiUnavailable(f"AI 服务未启用。请检查配置或开启 SSH 隧道: {cfg['tunnel_hint']}")
    cfg = _cfg()
    endpoint = normalize_endpoint(cfg.get("endpoint") or "")
    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
               "Accept-Encoding": "identity"}
    if cfg.get("api_key") and cfg["api_key"] != "unused":
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=cfg["timeout"])
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise AiUnavailable(f"AI 服务不可用(HTTP {e.code}): {err_body or e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AiUnavailable(
            f"AI 服务连接不可用: 无法连接至 {cfg['endpoint']} ({e})。"
            f"请确认模型已启动或运行 SSH 隧道: {cfg['tunnel_hint']}"
        )

    buffer: list[str] = []
    emitted = False
    try:
        with resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                buffer.append(line)
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    emitted = True
                    yield piece
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AiUnavailable(f"AI 流式输出中断: {e}")

    if emitted:
        return
    # 某些兼容服务忽略 stream 参数，直接返回整段 JSON：兜底解析，避免“空回答”。
    text = "\n".join(buffer)
    try:
        data = json.loads(text)
        content = data["choices"][0]["message"].get("content")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        content = None
    if isinstance(content, str) and content.strip():
        yield content.strip()
        return
    raise AiUnavailable("AI 流式输出为空或格式异常")
