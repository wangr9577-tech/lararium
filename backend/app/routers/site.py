"""公共站点信息（无需登录）：登录页/侧栏品牌读取 site.name / site.slogan。

内容从 settings 读取（受保护接口写入），这里只暴露最小公开字段。
另提供 /quote：服务端代理一言（hitokoto），带内存缓存，避免未登录访客的
浏览器直接外泄 IP/UA 给第三方（P1-K3）。
"""
from __future__ import annotations

import json
import time
import urllib.request

from fastapi import APIRouter

from .settings import _load

router = APIRouter(prefix="/api/site", tags=["site"])

DEFAULTS = {"name": "Kruskal", "slogan": "日程 · 笔记 · 论文 · 二次元小站"}

# 一言代理：命中缓存直接返回；拉取失败回落到静态句子，绝不因外网抖动卡登录页。
_QUOTE_TTL = 6 * 3600
_QUOTE_FALLBACK = [
    "海内存知己，天涯若比邻。",
    "星光不问赶路人，时光不负有心人。",
    "路漫漫其修远兮，吾将上下而求索。",
    "博观而约取，厚积而薄发。",
    "长风破浪会有时，直挂云帆济沧海。",
]
_quote_cache: dict = {"text": "", "exp": 0.0}
_quote_rr = 0  # 回落句子轮转游标


@router.get("")
def site_info():
    cfg = _load()
    return {
        "name": cfg.get("site.name") or DEFAULTS["name"],
        "slogan": cfg.get("site.slogan") or DEFAULTS["slogan"],
    }


@router.get("/quote")
def site_quote():
    now = time.time()
    if _quote_cache["text"] and now < _quote_cache["exp"]:
        return {"quote": _quote_cache["text"]}
    text = ""
    try:
        req = urllib.request.Request(
            "https://v1.hitokoto.cn/?encode=json",
            headers={"User-Agent": "KruskalSite/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        cand = str(data.get("hitokoto") or "").strip()
        if 0 < len(cand) <= 120:  # 长度护栏：异常长文/空文不进缓存
            text = cand
    except Exception:
        text = ""  # noqa: BLE001 外网失败静默回落，登录页不应因此报错
    if text:
        _quote_cache.update(text=text, exp=now + _QUOTE_TTL)
        return {"quote": text}
    # 回落：优先用旧缓存（哪怕过期），否则轮转静态句子
    global _quote_rr
    if _quote_cache["text"]:
        return {"quote": _quote_cache["text"]}
    _quote_rr = (_quote_rr + 1) % len(_QUOTE_FALLBACK)
    return {"quote": _QUOTE_FALLBACK[_quote_rr]}
