"""本机会话路由（无登录）：浏览器用一个 POST 换取 Bearer token。

只接受来自本机回环地址、且 Origin（浏览器会带）与 Host 同源的请求，
避免别的网页用 DNS rebinding / 跨站表单悄悄取走本机 token。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from .. import auth as authz
from .. import vault

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _check_local_origin(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")
    host = request.headers.get("host", "").lower()
    origin = request.headers.get("origin", "")
    if not origin:
        return  # 非浏览器客户端（curl/测试）没有 Origin，不存在 CSRF 风险
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != host:
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


@router.post("/local-session")
def local_session(request: Request):
    """本机免登录换取 token（端口随启动参数变化，不写死）。"""
    _check_local_origin(request)
    if not vault.has_dek():
        raise HTTPException(status_code=503, detail="本机数据密钥不可用，请重启服务")
    user = authz.ensure_local_user()
    return {"token": authz.issue_token(user["id"]), "username": user["username"]}
