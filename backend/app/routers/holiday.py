"""官方节假日：联网抓取并本地缓存（data/holidays/<year>.json），之后离线可用。

数据源：timor.tech 免费接口为主；缓存命中即不再联网。?refresh=1 强制更新。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..auth import get_current

router = APIRouter(prefix="/api/holiday", tags=["holiday"])

HOLIDAY_DIR = config.DATA_DIR / "holidays"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Kruskal/0.1"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cache_path(year: int) -> Path:
    return HOLIDAY_DIR / f"{year}.json"


def _http_get(url: str, timeout: float = 12.0) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _parse_timor(data: dict, year: int) -> list[dict] | None:
    """timor.tech: data.holiday = {date: {holiday: bool, name: str|null}}，日期键可能是 YYYY-MM-DD 或 MM-DD"""
    try:
        hm = (data.get("holiday") or {})
        if not isinstance(hm, dict) or not hm:
            return None
        items = []
        for date, v in hm.items():
            if not isinstance(v, dict):
                continue
            if len(date) == 5:  # MM-DD -> YYYY-MM-DD
                date = f"{year}-{date}"
            is_off = bool(v.get("holiday", True))
            name = (v.get("name") or "").strip()
            items.append({
                "date": date, "name": name if is_off else (name or "班"),
                "is_off": is_off, "is_workday": not is_off and bool(name),
            })
        return sorted(items, key=lambda x: x["date"]) or None
    except Exception:
        return None


def _fetch(year: int) -> list[dict]:
    """抓取并规范化：返回 items；失败抛异常由调用方处理。"""
    data = _http_get(f"https://timor.tech/api/holiday/year/{year}")
    items = _parse_timor(data, year) if isinstance(data, dict) else None
    if items is None:
        raise HTTPException(502, f"{year} 年节假日数据获取失败（网络或源不可用），请稍后用 ?refresh=1 重试")
    return items


@router.get("/{year}")
def holidays(year: int, refresh: bool = False, _user: dict = Depends(get_current)):
    if year < 2000 or year > 2100:
        raise HTTPException(400, "年份无效")
    p = _cache_path(year)
    if not refresh and p.is_file():
        try:
            cached = json.loads(p.read_text())
            return {"year": year, "updated": cached.get("updated", ""), "items": cached.get("items", [])}
        except (json.JSONDecodeError, OSError):
            pass
    items = _fetch(year)
    try:
        HOLIDAY_DIR.mkdir(parents=True, exist_ok=True)
        from .. import vault
        vault.atomic_write_bytes(
            p, json.dumps({"year": year, "updated": _now(), "items": items}, ensure_ascii=False).encode("utf-8"))
    except OSError:
        print(f"[kruskal] 节假日缓存写入失败（不影响返回）: {p}")
    return {"year": year, "updated": _now(), "items": items}
