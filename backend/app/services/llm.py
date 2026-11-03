"""本地 LLM 服务：OpenAI 兼容客户端，只连 127.0.0.1 上的 vLLM，数据不出服务器。

所有调用失败必须静默降级（返回 None / 抛 AiUnavailable），由调用方优雅处理，
绝不阻塞主功能。端点/模型/超时来自设置（settings 表 ai.*），否则用 config 默认。
支持结构化 JSON 提取与多模态降级，以及未启用 AI 时的启发式规则提取。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

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
        "id": "local-ollama",
        "name": "Local Ollama (默认)",
        "provider": "ollama",
        "endpoint": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "api_key": "unused",
        "timeout": 60,
        "tunnel_hint": "",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek 官方 API",
        "provider": "deepseek",
        "endpoint": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "timeout": 60,
        "tunnel_hint": "",
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow 硅基流动",
        "provider": "openai",
        "endpoint": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "api_key": "",
        "timeout": 60,
        "tunnel_hint": "",
    },
    {
        "id": "local-vllm",
        "name": "本地 vLLM / LocalAI",
        "provider": "openai",
        "endpoint": "http://127.0.0.1:8000/v1",
        "model": "qwen2.5-7b-instruct",
        "api_key": "unused",
        "timeout": 60,
        "tunnel_hint": "",
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

    active_id = str(s.get("ai.active_profile_id") or "")
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
        out = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiUnavailable("AI 返回格式异常")
    return (out or "").strip()


def chat(messages: list[dict], max_tokens: int = 1500, temperature: float = 0.3) -> str:
    """标准 chat 调用，返回补全文本；支持多模态；失败抛 AiUnavailable。

    严禁静默丢弃图片或隐蔽移除视觉输入！若请求失败，必须保留真实的失败原因。
    """
    if not is_enabled():
        cfg = _cfg()
        raise AiUnavailable(f"AI 服务未启用。请检查配置或开启 SSH 隧道: {cfg['tunnel_hint']}")
    cfg = _cfg()
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
    """健壮提取与解析文本中的 JSON 对象。"""
    s = text.strip()
    # 1. 直接 json.loads
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. 剥离 ```json 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. 寻找最外层 { ... }
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = s[first_brace:last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    raise ValueError("无法从输出中提取合法 JSON 对象")


def chat_structured(messages: list[dict], system_prompt: str = "",
                    max_tokens: int = 2000, temperature: float = 0.2) -> dict:
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

    raw_text = chat(msgs, max_tokens=max_tokens, temperature=temperature)
    try:
        return _parse_json(raw_text)
    except Exception as e:
        raise AiUnavailable(f"AI 输出解析为结构化 JSON 失败: {e}")


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


def check_diagnostics(override_cfg: dict | None = None) -> dict:
    """真实探测大模型服务连通性（优先检测 /v1/models，备选微型 completion），返回连通状态与延迟，若不通则提供 SSH 隧道提示。"""
    if override_cfg:
        cfg = {
            "enabled": True,
            "provider": str(override_cfg.get("provider") or "openai"),
            "endpoint": str(override_cfg.get("endpoint") or "").rstrip("/"),
            "model": str(override_cfg.get("model") or ""),
            "api_key": str(override_cfg.get("api_key") or ""),
            "timeout": int(override_cfg.get("timeout") or 10),
            "tunnel_hint": str(override_cfg.get("tunnel_hint") or ""),
            "name": str(override_cfg.get("name") or "临时测试配置"),
        }
    else:
        cfg = _cfg()

    endpoint = normalize_endpoint(cfg.get("endpoint") or "")
    model = cfg["model"]
    provider = cfg["provider"]
    tunnel_hint = cfg["tunnel_hint"]
    name = cfg.get("name", "")

    if not cfg["enabled"]:
        return {
            "connected": False,
            "latency_ms": 0,
            "name": name,
            "model": model,
            "provider": provider,
            "endpoint": endpoint,
            "error_hint": f"AI 服务未启用 (ai.enabled=False)。请在设置中开启，或运行 SSH 隧道: {tunnel_hint}",
        }

    start = time.perf_counter()
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key") and cfg["api_key"] != "unused":
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    # 1. 优先探测 GET /models
    req = urllib.request.Request(
        f"{endpoint}/models",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(cfg["timeout"], 8)) as resp:
            resp.read()
            latency = int((time.perf_counter() - start) * 1000)
            return {
                "connected": True,
                "latency_ms": max(1, latency),
                "name": name,
                "model": model,
                "provider": provider,
                "endpoint": endpoint,
                "error_hint": "",
            }
    except Exception as e_models:
        # 2. 备选探测：部分反代或网关禁止 /models，尝试微型 ping 补全
        try:
            ping_body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }).encode("utf-8")
            ping_req = urllib.request.Request(
                f"{endpoint}/chat/completions",
                data=ping_body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(ping_req, timeout=min(cfg["timeout"], 10)) as resp:
                resp.read()
                latency = int((time.perf_counter() - start) * 1000)
                return {
                    "connected": True,
                    "latency_ms": max(1, latency),
                    "name": name,
                    "model": model,
                    "provider": provider,
                    "endpoint": endpoint,
                    "error_hint": "",
                }
        except Exception as e_ping:
            latency = int((time.perf_counter() - start) * 1000)
            return {
                "connected": False,
                "latency_ms": latency,
                "name": name,
                "model": model,
                "provider": provider,
                "endpoint": endpoint,
                "error_hint": f"无法连接到模型端点 ({endpoint}): {e_ping}。若使用远程模型，请在本机运行 SSH 隧道命令: {tunnel_hint}",
            }


# ==================== 启发式规则提取（AI 停用/故障时的无缝降级兜底） ====================

_NOTICE_KEYWORDS = ("通知", "截止", "报名", "提交", "申请", "缴费", "申报", "答辩", "会议", "提醒", "安排", "选课", "ddl", "deadline")


def heuristic_detect_mode(text: str, user_note: str = "") -> str:
    """根据关键词推断模式是 notice 还是 later。"""
    combined = f"{text} {user_note}".lower()
    for kw in _NOTICE_KEYWORDS:
        if kw in combined:
            return "notice"
    return "later"


def heuristic_extract_date(text: str) -> tuple[str, str]:
    """从文本中结合上下文语境智能提取截止日期与时间，严格区分截止日期与发布日期。
    返回 (YYYY-MM-DD, HH:MM)。若无明确截止时间则返回 ("", "")。
    """
    now = datetime.now()
    cur_year = now.year

    # 截止/延期强特征关键词
    deadline_keywords = ("截止", "申报截止", "提交截止", "系统截止", "报名截止", "有效至", "逾期",
                         "前完成", "最晚于", "前提交", "前报送", "前发送", "前寄达", "前上传", "ddl", "deadline",
                         "延期至", "顺延至", "推迟至", "延长至", "调整为")
    # 发布/发文排除关键词
    publish_keywords = ("发布", "印发", "发文", "通知日期", "发布时间", "签发", "发于", "起发布")

    # 匹配各类日期表达式
    date_patterns = [
        # 1. 2026年11月20日 / 2026-11-20 / 2026/11/20
        re.compile(r"(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})(?:日)?(?:\s*(\d{1,2})[:点时](\d{2}))?"),
        # 2. 11月20日 / 11-20
        re.compile(r"(?<!\d)(\d{1,2})[-/月\.](\d{1,2})(?:日)?(?:\s*(\d{1,2})[:点时](\d{2}))?"),
    ]

    candidates: list[dict] = []

    for pat in date_patterns:
        for match in pat.finditer(text):
            groups = match.groups()
            start, end = match.span()
            if len(groups) == 5:  # 带年份
                y = int(groups[0])
                m = int(groups[1])
                d = int(groups[2])
                hh = groups[3]
                mm = groups[4]
            else:  # 不带年份
                y = cur_year
                m = int(groups[0])
                d = int(groups[1])
                hh = groups[2]
                mm = groups[3]

            try:
                dt = datetime(y, m, d)
                date_str = dt.strftime("%Y-%m-%d")
                time_str = f"{int(hh):02d}:{int(mm):02d}" if hh and mm else ""
            except ValueError:
                continue

            # 上下文窗口探测：限定在当前短句内（不跨越逗号、句号、分号或换行），防止前一句的发布修饰污染后一句的截止
            prefix = re.split(r"[。；！\n，,]", text[:start])[-1].lower()
            suffix = re.split(r"[。；！\n，,]", text[end:])[0].lower()
            window = f"{prefix} {suffix}"

            score = 0
            # 命中截止语境
            for kw in deadline_keywords:
                if kw in prefix:
                    score += 20  # 关键词在日期前面（如“截止时间为 11-20”）权重最高
                elif kw in suffix:
                    score += 15  # 关键词在日期后面（如“11-20 前完成系统填报”）
            # 命中发布语境惩罚（仅在当前分句生效）
            for pkw in publish_keywords:
                if pkw in window:
                    score -= 20

            candidates.append({
                "date": date_str,
                "time": time_str,
                "score": score,
                "pos": start,
            })

    if not candidates:
        return "", ""

    # 按置信度排序，优先选择截止语境分数高的
    candidates.sort(key=lambda c: (c["score"], c["pos"]), reverse=True)
    best = candidates[0]

    # 如果最高分的日期依然是严重惩罚的纯发布日期（score < 0），说明文中没有截止期限，坚决不误判为 DDL
    if best["score"] < 0:
        return "", ""

    # 如果有明确截止语境候选（score > 0），选用最佳候选
    if best["score"] > 0:
        return best["date"], best["time"]

    # 无法通过词语判断时，如果存在多个日期，排除掉首个可能是发文日期的项，取最后一个
    if len(candidates) > 1:
        return candidates[-1]["date"], candidates[-1]["time"]

    return best["date"], best["time"]


def heuristic_extract_notice(text: str, user_note: str = "") -> dict:
    """当大模型不可用时，基于启发式规则抽取通知核心事实。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    raw_head = lines[0] if lines else "新通知事项"
    # 清理 markdown 标题符号
    title = re.sub(r"^[#>*`\-\+\s]+", "", raw_head)[:60].strip() or "未命名通知"

    ddl_date, ddl_time = heuristic_extract_date(f"{user_note} {text}")

    # 提炼要点/注意事项清单
    highlights: list[str] = []
    for line in lines[1:10]:
        clean_l = re.sub(r"^[#>*`\-\+\s]+", "", line).strip()
        if re.match(r"^(\d+[\.、\)]|[一二三四五六七八九十]+[\.、\)]|注意|务必|要求|材料)", clean_l):
            if clean_l and len(clean_l) <= 100:
                highlights.append(clean_l)
        if len(highlights) >= 4:
            break

    summary = " ".join(lines[:3])[:200]
    if user_note:
        summary = f"[{user_note}] {summary}"

    kw_candidates = [w for w in re.split(r"[\s,，、:：【】\[\]()（）/_\-]+", f"{title} {user_note}") if len(w) >= 2]
    return {
        "title": title,
        "summary": summary,
        "highlights": highlights,
        "deadline_date": ddl_date,
        "deadline_time": ddl_time,
        "event_keywords": kw_candidates[:6],
    }


def heuristic_extract_later(text: str, source_url: str = "", user_note: str = "") -> dict:
    """当大模型不可用时，基于启发式规则抽取稍后看卡片。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    title = re.sub(r"^[#>*`\-\+\s]+", "", first_line)[:60].strip()
    if not title:
        if source_url:
            title = source_url.split("/")[-1] or source_url
        else:
            title = "稍后看卡片"

    # 分类检测
    combined = f"{text} {source_url} {user_note}".lower()
    category = "其他"
    if any(k in combined for k in ("arxiv", "paper", "pdf", "cvpr", "icml", "neurips", "acl", "ieee", "论文")):
        category = "论文"
    elif any(k in combined for k in ("github", "repo", "git", "代码", "开源")):
        category = "项目"
    elif any(k in combined for k in ("bilibili", "youtube", "b23", "video", "视频")):
        category = "视频"
    elif any(k in combined for k in ("tutorial", "guide", "docs", "教程", "手册", "指南")):
        category = "教程"
    elif any(k in combined for k in ("tool", "cli", "app", "工具", "软件", "插件")):
        category = "工具"

    brief = " ".join(lines[:2])[:150] if lines else "暂无简介"
    why_focus = user_note if user_note else "留存稍后深入研读与查阅"
    tags = [category] if category != "其他" else ["稍后看"]

    return {
        "title": title,
        "brief": brief,
        "why_focus": why_focus,
        "category": category,
        "tags": tags,
    }


def heuristic_reconcile_notice(existing_thread: dict, new_notice: dict) -> dict:
    """启发式研判前后两封通知的版本演进关系，保障旧通知录入时不回滚最新有效 DDL。"""
    old_date = existing_thread.get("deadline_date", "")
    new_date = new_notice.get("deadline_date", "")

    change_type = "update"
    change_reason = "补充新要求与通知事实"
    effective_date = old_date
    effective_time = existing_thread.get("deadline_time", "")

    new_text_combined = f"{new_notice.get('title', '')} {new_notice.get('summary', '')}".lower()
    is_explicit_postpone = any(w in new_text_combined for w in ("延期", "顺延", "推迟", "延长", "延至", "调整为"))
    is_explicit_advance = any(w in new_text_combined for w in ("提前", "提前至", "压缩"))

    if new_date and old_date:
        if new_date > old_date:
            # 日期更晚，且语境为延期或自然顺延
            change_type = "postpone"
            change_reason = f"截止时间由 {old_date} 延期至 {new_date}"
            effective_date = new_date
            effective_time = new_notice.get("deadline_time") or effective_time
        elif new_date < old_date:
            if is_explicit_advance:
                change_type = "update"
                change_reason = f"截止时间提前至 {new_date}"
                effective_date = new_date
                effective_time = new_notice.get("deadline_time") or effective_time
            else:
                # 关键修复：后导入的旧邮件/早期通知，绝对不能回退已有最新生效截止日！
                change_type = "update"
                change_reason = f"录入历史阶段通知（原载截止日 {new_date}），保留当前有效最新截止时间 {old_date}"
                effective_date = old_date
        else:
            change_type = "update"
            change_reason = "补充同截止期事项的材料或细节要求"
    elif new_date and not old_date:
        change_type = "update"
        change_reason = f"明确截止时间为 {new_date}"
        effective_date = new_date
        effective_time = new_notice.get("deadline_time") or ""
    elif old_date and not new_date:
        effective_date = old_date

    # 检测是否有取消关键词
    if any(k in new_text_combined for k in ("取消", "作废", "终止", "暂停")):
        change_type = "cancel"
        change_reason = "通知表明活动或事项已取消/暂停"

    summary = new_notice.get("summary") or existing_thread.get("summary", "")
    highlights = new_notice.get("highlights") or []

    return {
        "change_type": change_type,
        "change_reason": change_reason,
        "summary": summary,
        "highlights": highlights,
        "deadline_date": effective_date,
        "deadline_time": effective_time,
    }
