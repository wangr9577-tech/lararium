"""Kruskal 入口：FastAPI + 前端构建产物静态托管（SPA 单端口）。

启动：conda activate site && uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18080
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth as authz
from . import config
from .auth import bootstrap_admin
from .db import init_db
from .routers import auth as auth_router
from .routers import album as album_router
from .routers import anniversary as anniversary_router
from .routers import diary as diary_router
from .routers import focus as focus_router
from .routers import holiday as holiday_router
from .routers import ielts as ielts_router
from .routers import ledger as ledger_router
from .routers import notes as notes_router
from .routers import papers as papers_router
from .routers import pdf as pdf_router
from .routers import ppt as ppt_router
from .routers import schedule as schedule_router
from .routers import settings as settings_router
from .routers import share as share_router
from .routers import site as site_router
from .routers import timeline as timeline_router
from .routers import translate, vocab as vocab_router
from .routers import trash as trash_router
# ---- 科研工作台（P1/P2/P3）----
from .routers import ai as ai_router
from .routers import cards as cards_router
from .routers import experiments as experiments_router
from .routers import fs as fs_router
from .routers import ideas as ideas_router
from .routers import reports as reports_router
from .routers import submissions as submissions_router
from .routers import writing as writing_router

logging.basicConfig(level=logging.INFO)

init_db()
bootstrap_admin()
authz.sweep_expired()  # 启动清一轮历史过期会话（P1 token 治理）

# P2-L4：生产不公开 OpenAPI 接口结构（摸接口面变小）；KRUSKAL_DEV=1 才开 /docs
_IS_DEV = os.environ.get("KRUSKAL_DEV") == "1"
app = FastAPI(
    title="Kruskal", version="0.1.0",
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)

# ---- 全局安全网（P1-G2）：/api 一律要求有效 Bearer，白名单除外 ----
# 路由内的 Depends(get_current) 保留不动：中间件兜住"新路由忘写鉴权"的结构性风险。
_PUBLIC_API = ("/api/auth/login", "/api/site")  # 2026-09 审计：94 端点仅这两个公开（/share 页不在 /api 下）
_CSP_ON = os.environ.get("KRUSKAL_CSP", "1") != "0"
_CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; "
        "connect-src 'self'; manifest-src 'self'; frame-ancestors 'self'; base-uri 'self'")


@app.middleware("http")
async def auth_and_csp_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not any(path == p or path.startswith(p + "/") for p in _PUBLIC_API):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if authz.token_user(token) is None:
            resp = JSONResponse({"detail": "未登录"}, status_code=401)
            if _CSP_ON:
                resp.headers["Content-Security-Policy"] = _CSP
            return resp
    response = await call_next(request)
    if _CSP_ON:
        response.headers.setdefault("Content-Security-Policy", _CSP)
    return response

for r in (auth_router.router, settings_router.router, site_router.router,
          translate.router, notes_router.router, focus_router.router,
          schedule_router.router, papers_router.router, vocab_router.router,
          diary_router.router, holiday_router.router, anniversary_router.router,
          share_router.router, album_router.router, timeline_router.router,
          ledger_router.router, ielts_router.router, ppt_router.router,
          pdf_router.router, trash_router.router,
          cards_router.router, ideas_router.router, fs_router.router,
          ai_router.router, experiments_router.router, writing_router.router,
          submissions_router.router, reports_router.router):
    app.include_router(r)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "kruskal", "version": app.version}


# ---- 前端静态资源 ----
_assets = config.DIST_DIR / "assets"
if _assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

# Vditor 编辑器运行时资源（lute/highlight/katex/i18n/emoji），站内托管，不依赖外网 CDN
_vdir = config.DIST_DIR / "vditor"
if _vdir.is_dir():
    app.mount("/vditor", StaticFiles(directory=str(_vdir)), name="vditor")

# ---- PWA 静态资源（清单 + 图标）----
# 注意：以下路由必须注册在 SPA 兜底路由之前，否则会被 /{full_path} 吃掉。
_icons = config.DIST_DIR / "icons"
if _icons.is_dir():
    app.mount("/icons", StaticFiles(directory=str(_icons)), name="icons")


@app.get("/manifest.json", include_in_schema=False)
def web_manifest():
    """Web App Manifest：让站点可被「安装」到桌面/主屏（display: standalone 即无地址栏）。"""
    f = config.DIST_DIR / "manifest.json"
    if f.is_file():
        return FileResponse(
            f,
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    # 静态文件优先：dist 根目录下真实存在的文件（favicon.ico / sw.js / manifest.json 等）
    # 直接返回，只有确实找不到文件时才回退到 index.html 走 SPA 路由。
    if full_path:
        root = config.DIST_DIR.resolve()
        candidate = (root / full_path).resolve()
        if candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
    index = config.DIST_DIR / "index.html"
    if index.is_file():
        # no-cache：保证前端重新构建后浏览器立即拿到新 index.html（哈希资源
        # /assets/* 不受影响，仍可走 ETag/长缓存），避免旧 chunk 404 导致页面打不开
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"status": "api-only", "hint": "前端尚未构建：cd frontend && npm run build"})
