"""划词查询（F4）：有道词典词义（词级）→ 无结果时退有道网页翻译（句/短语级）。
全部走免费接口、直连（start.sh 已清代理）；不稳定接口失败时优雅降级为空结果。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current

router = APIRouter(prefix="/api/translate", tags=["translate"])

SOURCES = [
    {"id": "youdao-web", "name": "有道网页翻译", "need_key": False,
     "note": "免费、无需 key，国内实测毫秒级可达（非官方接口，偶尔可能失效）"},
    {"id": "youdao-dict", "name": "有道词典（单词释义）", "need_key": False,
     "note": "免费词义接口，划词首选"},
    {"id": "baidu", "name": "百度翻译开放平台", "need_key": True,
     "note": "需注册免费 key，稳定可靠（备选）"},
    {"id": "mymemory", "name": "MyMemory", "need_key": False,
     "note": "免费但较慢（兜底）"},
    {"id": "offline-ecdic", "name": "本地离线词典 ECDICT", "need_key": False,
     "note": "词库下载后完全离线可用（兜底）"},
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Kruskal/0.1"}


def _http_get(url: str, timeout: float = 8.0) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _http_post(url: str, data: str, timeout: float = 8.0) -> bytes | None:
    try:
        req = urllib.request.Request(url, data=data.encode("utf-8"), headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


@router.get("/sources")
def sources(_user: dict = Depends(get_current)):
    return {"sources": SOURCES, "default": "youdao-dict"}


class LookupIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


def _dict_lookup(text: str) -> dict:
    """有道词典 jsonapi：音标/基本释义(ec) + 网络释义(web_trans) + 词组(web)。"""
    url = "https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(text)
    raw = _http_get(url)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict = {"phonetic": "", "meanings": [], "phrases": []}
    ec = data.get("ec", {})
    words = (ec.get("word") or []) if isinstance(ec, dict) else []
    seen = set()
    for w in words[:3]:
        if not out["phonetic"]:
            out["phonetic"] = w.get("phonetic", "") or ""
        for tr in (w.get("trs") or [])[:8]:
            for item in (tr.get("tr") or []):
                l = item.get("l") or {}
                t = (l.get("t") or [""])[0]
                if t and t not in seen:
                    seen.add(t)
                    out["meanings"].append(t)
        if len(out["meanings"]) >= 8:
            break
    # 网络释义（web_trans）常带更完整的中文解释
    for item in (((data.get("web_trans") or {}).get("web-translation")) or [])[:3]:
        key = item.get("key", "")
        for tr in (item.get("trans") or [])[:5]:
            val = tr.get("value") or ""
            if val:
                if key and key.lower() == text.lower():
                    out["meanings"].append(val)
                else:
                    out["phrases"].append({"key": key, "value": [val]})
    if len(out["meanings"]) >= 8:
        return out
    for ph in (data.get("web") or [])[:5]:
        key = ph.get("key", "")
        vals = [v for v in (ph.get("value") or [])[:3]]
        if key:
            out["phrases"].append({"key": key, "value": vals})
    return out


def _web_translate(text: str) -> str:
    """句/短语级翻译回退：MyMemory（免费、国内可达，约数秒）。"""
    url = "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(text) + "&langpair=en|zh-CN"
    raw = _http_get(url, timeout=12.0)
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        return (data.get("responseData") or {}).get("translatedText") or ""
    except (json.JSONDecodeError, AttributeError):
        return ""


@router.post("/lookup")
def lookup(body: LookupIn, _user: dict = Depends(get_current)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "内容为空")
    result = {"text": text, "phonetic": "", "meanings": [], "phrases": [], "translate": ""}
    if len(text) <= 60:  # 词/短语先查词典
        d = _dict_lookup(text)
        result["phonetic"] = d.get("phonetic", "")
        result["meanings"] = d.get("meanings", [])
        result["phrases"] = d.get("phrases", [])
    if not result["meanings"] and len(text) <= 800:
        result["translate"] = _web_translate(text)
    return result
