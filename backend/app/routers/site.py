"""公共站点信息（无需登录）：登录页/侧栏品牌读取 site.name / site.slogan。

内容从 settings 读取（受保护接口写入），这里只暴露最小公开字段。
"""
from __future__ import annotations

from fastapi import APIRouter

from .settings import _load

router = APIRouter(prefix="/api/site", tags=["site"])

DEFAULTS = {"name": "Kruskal", "slogan": "日程 · 笔记 · 论文 · 二次元小站"}


@router.get("")
def site_info():
    cfg = _load()
    return {
        "name": cfg.get("site.name") or DEFAULTS["name"],
        "slogan": cfg.get("site.slogan") or DEFAULTS["slogan"],
    }
