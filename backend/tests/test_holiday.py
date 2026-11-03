"""节假日缓存读取的健壮性回归测试。

真实故障复盘（2026-11-02）：`GET /api/holiday/2026` 返回 **500**，堆栈落在
`_read_cache` 的 `json.loads(...)` —— 缓存文件坏掉/被截断/是别的格式时，
读缓存直接抛异常冒成 500，前端每次打开日程页都弹「节假日数据暂不可用」，
节假日功能整个不可用。

约定：缓存读失败必须**退化成「没有缓存」**去联网，联网真失败才 502；
任何情况下都不能 500。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment
from app import config
from app.routers import holiday as H

env = TestEnvironment(prefix="kruskal_holiday_")
client = env.client

GOOD = [{"date": "2026-01-01", "name": "元旦", "is_off": True, "is_workday": False},
        {"date": "2026-02-17", "name": "春节", "is_off": True, "is_workday": False}]

# HOLIDAY_DIR 是 import 时由 config.DATA_DIR 拼出来的模块级常量，测试在 import 之后
# 才 rebind 数据目录，所以必须显式改指沙箱——否则测试会往真实的 backend/data/holidays
# 里写垃圾文件。
_ORIG_HOLIDAY_DIR = H.HOLIDAY_DIR


def setup_module():
    env.setup()
    H.HOLIDAY_DIR = Path(config.DATA_DIR) / "holidays"


def teardown_module():
    H.HOLIDAY_DIR = _ORIG_HOLIDAY_DIR
    env.teardown()


def _get(year: int = 2026, refresh: bool = False):
    q = "?refresh=1" if refresh else ""
    return client.get(f"/api/holiday/{year}{q}", headers=env.auth_headers())


def _with_http(result, fn):
    original = H._http_get
    H._http_get = _fake(result)
    try:
        return fn()
    finally:
        H._http_get = original


def _fake(result):
    def fake(url: str, timeout: float = 12.0):
        if isinstance(result, Exception):
            raise result
        return result
    return fake


def test_good_cache_is_used_without_network():
    H._write_cache(2026, H._now(), GOOD, True)
    r = _with_http(H._FetchError("这里绝不该被调用"), lambda: _get())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and len(body["items"]) == 2
    assert body.get("stale") is not True


def test_corrupt_cache_never_returns_500():
    """缓存文件被写坏（截断 / 垃圾 / 二进制 / 空）都必须退化成重新联网。"""
    cases = [
        b'{"year": 2026, "items": [',                        # 写一半被截断
        b'not json at all',                                   # 垃圾文本
        b'\x14\x81KRSLC1\n\x00\x01\x02garbage',               # 看着像 Kruskal 密文头
        b'',                                                  # 空文件
        b'[1, 2, 3]',                                         # 顶层不是对象
        b'{"year": 2026, "items": "oops"}',                   # items 不是数组
    ]
    ok = {"holiday": {"2026-01-01": {"holiday": True, "name": "元旦"}}}
    for blob in cases:
        H._cache_path(2026).write_bytes(blob)
        r = _with_http(ok, lambda: _get())
        assert r.status_code == 200, f"缓存内容 {blob[:24]!r} 导致了 {r.status_code}"
        body = r.json()
        assert body["available"] is True and body["items"], f"{blob[:24]!r} 没拿到数据"
        assert all(set(("date", "name", "is_off")) <= set(it) for it in body["items"])


def test_fetch_failure_with_corrupt_cache_is_502_not_500():
    """缓存坏 + 数据源也坏：502（前端可解释），而不是 500（对用户就是"打不开"）。"""
    H._cache_path(2026).write_bytes(b'{"year": 2026, "items": [')
    r = _with_http(H._FetchError("timor.tech 不可达"), lambda: _get())
    assert r.status_code == 502, r.text
    assert "timor.tech" in r.json()["detail"]


def test_stale_cache_fallback_when_source_down():
    """数据源挂了但有旧的非空缓存：用旧数据 + stale=true，不报错。"""
    H._write_cache(2026, H._now(), GOOD, True)
    r = _with_http(H._FetchError("网络中断"), lambda: _get(refresh=True))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["stale"] is True and len(body["items"]) == 2


def test_not_published_is_200_with_negative_cache():
    """抓到空表 = 尚未公布：200 + available=false，且负缓存 TTL 内不再联网。"""
    H._cache_path(2027).unlink(missing_ok=True)
    r = _with_http({"holiday": {}}, lambda: _get(2027))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False and body["reason"] == "not_published"

    # 第二次即使网络层会抛异常，也必须直接吃负缓存（省掉无意义的联网）
    r2 = _with_http(H._FetchError("不该再联网"), lambda: _get(2027))
    assert r2.status_code == 200, r2.text
    assert r2.json()["available"] is False


def test_before_publication_window_short_circuit():
    """10 月 1 日之前看还没公布的年份：直接返回「尚未公布」，不联网、更不报错。

    （国务院惯例前一年 11 月前后发文。今天已过 10 月 1 日，所以用假时钟验证这条分支。）
    """
    real = H.datetime

    class MarchFirst(real):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 1)

    H.datetime = MarchFirst
    try:
        assert H._before_publication_window(2027) is True     # 3 月看明年：不该联网
        assert H._before_publication_window(2026) is False    # 当年永远要联网
        assert H._before_publication_window(2025) is False    # 已公布的往年不受影响
        r = _with_http(H._FetchError("这条分支绝不该联网"), lambda: _get(2027))
    finally:
        H.datetime = real
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "not_published"


def test_year_validation_and_auth():
    assert client.get("/api/holiday/1999", headers=env.auth_headers()).status_code == 400
    assert client.get("/api/holiday/2026").status_code == 401
