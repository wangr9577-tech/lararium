"""官方节假日：联网抓取并本地缓存（data/holidays/<year>.json），之后离线可用。

数据源：timor.tech 免费接口为主；缓存命中即不再联网。?refresh=1 强制更新。
接口区分三种状态（另有一条确定性短路：尚未到公布窗口的年份直接按「尚未公布」返回）：
  ① 抓取成功且有数据 → 200，available=true，写缓存；
  ② 抓取成功但该年尚未公布（空表）→ 200，available=false + reason=not_published，
     写「空结果负缓存」，EMPTY_TTL_SECONDS 内不再联网（未公布年份 ?refresh 无意义）；
  ③ 数据源真故障（网络异常/非 200/JSON 解析失败/结构异常）→ 优先回退本地非空旧缓存
     并加 stale=true；无任何可用旧缓存才 502。
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
EMPTY_TTL_SECONDS = 12 * 3600  # 空结果（尚未公布）负缓存时长


class _FetchError(Exception):
    """数据源真故障（网络/HTTP/JSON/结构异常）——区别于「该年尚未公布」。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cache_path(year: int) -> Path:
    return HOLIDAY_DIR / f"{year}.json"


def _http_get(url: str, timeout: float = 12.0) -> dict:
    """抓取并解析 JSON；真故障（网络异常/HTTP 非 200/JSON 解析失败）抛 _FetchError。"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        raise _FetchError(str(e)) from e
    if not isinstance(data, dict):
        raise _FetchError("数据源响应不是 JSON 对象")
    return data


def _parse_timor(data: dict, year: int) -> list[dict] | None:
    """timor.tech: data.holiday = {date: {holiday: bool, name: str|null}}，日期键可能是 YYYY-MM-DD 或 MM-DD。
    返回 [] = 该年尚未公布（空表，非故障）；None = 结构异常（真故障）。"""
    hm = data.get("holiday")
    if not isinstance(hm, dict):
        return None  # 缺字段/结构异常 → 真故障
    if not hm:
        return []    # 空表 → 该年尚未公布
    try:
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


def _read_cache(year: int) -> dict | None:
    """读缓存文件；不存在/解析失败返回 None。向后兼容旧文件（补 available/fetched_at）。"""
    p = _cache_path(year)
    if not p.is_file():
        return None
    try:
        cached = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(cached, dict):
        return None
    items = cached.get("items", [])
    # 结构校验：缓存只认「对象数组，且每条有 date 与 is_off」。别的形状——写一半被截断的
    # 文件、被别的程序覆盖、早期格式、items 是字符串——一律当「没有缓存」，让上层去联网
    # 重建。脏缓存绝不能冒成 500：2026-11 日程页每次打开都弹「节假日数据暂不可用」，
    # 就是坏缓存文件在 _read_cache 里抛异常直接掀翻了整个接口。
    if not isinstance(items, list):
        return None
    items = [it for it in items
             if isinstance(it, dict) and isinstance(it.get("date"), str) and "is_off" in it]
    available = bool(cached.get("available", bool(items)))  # 旧文件无该字段：按 items 推断
    fetched_at = cached.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        # 旧文件无 fetched_at：尝试从 updated 解析，失败则视为过期（需重新联网）
        try:
            fetched_at = datetime.strptime(cached.get("updated", ""), "%Y-%m-%d %H:%M:%S").timestamp()
        except (TypeError, ValueError):
            fetched_at = 0
    return {"updated": cached.get("updated", ""), "items": items,
            "available": available, "fetched_at": fetched_at}


def _write_cache(year: int, updated: str, items: list[dict], available: bool) -> None:
    try:
        HOLIDAY_DIR.mkdir(parents=True, exist_ok=True)
        from .. import vault
        payload = {"year": year, "updated": updated, "items": items,
                   "available": available, "fetched_at": datetime.now().timestamp()}
        vault.atomic_write_bytes(
            _cache_path(year), json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except OSError:
        print(f"[kruskal] 节假日缓存写入失败（不影响返回）: {_cache_path(year)}")


def _not_published_payload(year: int, updated: str) -> dict:
    return {"year": year, "updated": updated, "items": [], "available": False,
            "reason": "not_published",
            "message": f"{year} 年放假安排尚未公布（国务院一般于前一年 11 月前后发布），暂无法显示节假日标记"}


def _before_publication_window(year: int) -> bool:
    """该年度放假安排是否还不可能公布。

    国务院惯例在前一年 11 月前后发文，这里取「前一年 10 月 1 日」作为可以开始联网尝试的
    保守边界：边界之前直接按「尚未公布」返回——既省掉无意义的联网请求，也不会因为数据源
    临时不可用（如 Cloudflare 挑战页）把「还没公布」误报成抓取失败。
    """
    now = datetime.now()
    return year > now.year and now < datetime(now.year, 10, 1)


@router.get("/{year}")
def holidays(year: int, refresh: bool = False, _user: dict = Depends(get_current)):
    if year < 2000 or year > 2100:
        raise HTTPException(400, "年份无效")
    # 0) 还没到可能公布的窗口（例：2026-09 看 2027）：直接按「尚未公布」返回，不联网、不报错
    if _before_publication_window(year):
        return _not_published_payload(year, _now())
    # 1) 缓存命中且不强制刷新：有数据直接用；未公布（available=false）在负缓存 TTL 内也不再联网
    if not refresh:
        cached = _read_cache(year)
        if cached:
            if cached["items"]:
                return {"year": year, "updated": cached["updated"],
                        "items": cached["items"], "available": True}
            if (not cached["available"]) and \
                    (datetime.now().timestamp() - cached["fetched_at"]) < EMPTY_TTL_SECONDS:
                return _not_published_payload(year, cached["updated"])
    # 2) 联网（refresh=1 或缓存缺失/过期）
    try:
        data = _http_get(f"https://timor.tech/api/holiday/year/{year}")
        items = _parse_timor(data, year)
    except _FetchError:
        items = None
    if items is not None:
        _write_cache(year, _now(), items, bool(items))
        if not items:
            return _not_published_payload(year, _now())  # 抓取成功但未公布
        return {"year": year, "updated": _now(), "items": items, "available": True}
    # 3) 真故障：优先回退本地非空旧缓存（stale=true），没有任何可用旧缓存才 502
    cached = _read_cache(year)
    if cached and cached["items"]:
        return {"year": year, "updated": cached["updated"], "items": cached["items"],
                "available": True, "stale": True}
    raise HTTPException(502, f"{year} 年节假日数据获取失败：数据源 timor.tech 暂时不可用，请稍后重试")
