"""各功能模块占位路由：接口形状预先定好，功能期逐个填真。
当前统一返回空结构，前端壳页面据此渲染空态。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current

auth = Depends(get_current)

schedule_router = None  # 已由 routers/schedule.py 真实实现替换
# 其余占位路由已全部由真实实现替换（diary/notes/papers/vocab/schedule/focus/
# holiday/anniversary/timeline/album/share 均已实现），本文件仅作历史说明。

