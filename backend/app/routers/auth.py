"""认证路由：登录（首次登录创建数据密钥包裹）、登出、当前用户、修改密码。"""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth as authz
from .. import autokey, config, crypto, vault
from ..db import db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---- 登录防爆破（P2-L3）：单进程内存滑窗，10 分钟内同 IP 或同用户名
# 累计失败 10 次即 429 冷却；成功清零。进程重启自然复位，个人站够用。 ----
_FAIL_WINDOW = 600.0
_FAIL_MAX = 10
_login_fails: dict[str, list[float]] = {}


def _window_hits(key: str) -> int:
    now = time.monotonic()
    hits = [t for t in _login_fails.get(key, ()) if now - t < _FAIL_WINDOW]
    if hits:
        _login_fails[key] = hits
    else:
        _login_fails.pop(key, None)
    return len(hits)


def _note_fail(keys: list[str]) -> None:
    if len(_login_fails) > 2048:  # 防随机用户名撑爆内存
        _login_fails.clear()
    now = time.monotonic()
    for k in keys:
        _login_fails.setdefault(k, []).append(now)


def _clear_fails(keys: list[str]) -> None:
    for k in keys:
        _login_fails.pop(k, None)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AutoUnlockIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/local-session")
def local_session(request: Request):
    if not config.LOCAL_NO_PASSWORD:
        raise HTTPException(status_code=404, detail="Not found")
    host = request.headers.get("host", "").lower()
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    if (request.client is None or request.client.host not in ("127.0.0.1", "::1")
            or host not in ("127.0.0.1:18080", "localhost:18080")
            or parsed.scheme != "http" or parsed.netloc.lower() != host):
        raise HTTPException(status_code=403, detail="Local access only")
    if not vault.has_dek():
        raise HTTPException(status_code=503, detail="Local data key unavailable")
    with db() as conn:
        row = conn.execute("SELECT id, username FROM users ORDER BY id LIMIT 1").fetchone()
    return {"token": authz.issue_token(row["id"]), "username": row["username"]}


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    keys = [f"ip:{ip}", f"user:{body.username}"]
    if any(_window_hits(k) >= _FAIL_MAX for k in keys):
        raise HTTPException(status_code=429, detail="失败次数过多，请 10 分钟后再试")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if row is None or not authz.verify_password(body.password, row["salt"], row["pw_hash"]):
        _note_fail(keys)
        raise HTTPException(status_code=401, detail="账号或密码错误")
    _clear_fails(keys)
    authz.ensure_keywrap(body.password)
    _unlock_vault(body.password)  # 登录即解锁数据密钥，正文读写可用
    token = authz.issue_token(row["id"])
    return {"token": token, "username": row["username"]}


def _unlock_vault(password: str) -> None:
    """用主密码解开 .kek，把 DEK 放入进程 vault；失败视为凭据异常。

    P1-H2 崩溃自愈：改密采用"日志提交"——新包裹先写 .kek.journal，DB 更新成功后
    才 rename 转正。若崩在两步之间（DB=新密码、.kek=旧包裹），旧密码登录会解锁失败，
    但此时按 DB 已认的新密码能在日志里解开 → 用日志转正 .kek，恢复服务。
    反之（日志残留但 DB 未提交）主文件直接解开 → 日志视为作废清除。任何时刻都不会锁死。
    """
    import os
    dek = None
    try:
        raw = crypto.unwrap_keywrap(json.loads(config.KEYWRAP_PATH.read_text()), password)
        dek = raw if raw else None  # 空 DEK（bootstrap 空口令包）视同未解锁
    except (OSError, ValueError):
        pass  # .kek 缺失/损坏：下面走日志修复，仍失败才 401
    if not dek and config.KEYWRAP_JOURNAL.is_file():
        try:
            raw = crypto.unwrap_keywrap(json.loads(config.KEYWRAP_JOURNAL.read_text()), password)
            jd = raw if raw else None
        except ValueError:
            jd = None
        if jd:
            os.replace(config.KEYWRAP_JOURNAL, config.KEYWRAP_PATH)
            dek = jd
    if not dek:
        raise HTTPException(status_code=401, detail="数据密钥解锁失败")
    if config.KEYWRAP_JOURNAL.exists():  # 主文件解开成功而日志仍在 → 改密未提交，作废旧日志
        try:
            config.KEYWRAP_JOURNAL.unlink()
        except OSError:
            pass
    vault.set_dek(dek)
    try:
        from .assistant import resume_paused_jobs
        resume_paused_jobs()
    except Exception:
        pass


@router.post("/logout")
def logout(user: dict = Depends(authz.get_current),
           authorization: str = Header(default="")):
    if authorization.startswith("Bearer "):
        authz.revoke_token(authorization[7:])
    return {"ok": True}


@router.post("/lock")
def lock(user: dict = Depends(authz.get_current)):
    """一键上锁：撤销该用户全部 token、清空内存数据密钥(DEK)，并撤销免密解锁。

    锁上后所有会话失效，加密正文/日记/相册等立即回到加密锁定态，
    必须重新输入主密码登录（login 会自动重新解锁 DEK）才能访问。

    顺带撤销 `.kek.auto` 是必须的：否则「上锁」之后进程一重启又自动解锁，
    上锁按钮就成了摆设。想恢复免密在 设置 → 账户安全 里重新打开即可（要输一次密码）。
    """
    if config.LOCAL_NO_PASSWORD:
        raise HTTPException(status_code=400, detail="本机免密码模式不支持上锁")
    authz.revoke_all_for(user["id"])
    vault.clear_dek()
    removed = autokey.disable()
    return {"ok": True, "auto_unlock_revoked": removed > 0}


@router.get("/me")
def me(user: dict = Depends(authz.get_current)):
    return {"id": user["id"], "username": user["username"], "auto_unlock": autokey.enabled()}


# ---- 免密自动解锁（可选）：服务器重启后不再需要人工输入主密码 ----
# 安全边界见 app/autokey.py 模块文档：它把「主密码」降级为「本机文件权限 + 备份口令」，
# 仍挡住同机其他普通用户，不再挡 root / 恶意进程 / 同时拷走两个文件的人。

def _auto_status() -> dict:
    return {"enabled": autokey.enabled(), "unlocked": vault.has_dek(),
            "key_outside_data": autokey.key_outside_data_dir()}


@router.get("/auto-unlock")
def auto_unlock_status(user: dict = Depends(authz.get_current)):
    return _auto_status()


@router.post("/auto-unlock")
def auto_unlock_enable(body: AutoUnlockIn, user: dict = Depends(authz.get_current)):
    """开启免密：必须已解锁（DEK 在内存）且用当前主密码二次确认。"""
    if not vault.has_dek():
        raise HTTPException(status_code=423, detail="数据未解锁，请先用主密码登录")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if row is None or not authz.verify_password(body.password, row["salt"], row["pw_hash"]):
        raise HTTPException(status_code=400, detail="密码不正确")
    info = autokey.enable(vault.dek())
    return {"ok": True, **info, "unlocked": True}


@router.delete("/auto-unlock")
def auto_unlock_disable(user: dict = Depends(authz.get_current)):
    """关闭免密：删掉包裹与本机密钥，之后重启回到必须输入主密码。"""
    if config.LOCAL_NO_PASSWORD:
        raise HTTPException(status_code=400, detail="本机免密码模式不能关闭本机密钥")
    removed = autokey.disable()
    return {"ok": True, "removed": removed, **_auto_status()}


@router.put("/password")
def change_password(body: PasswordIn, user: dict = Depends(authz.get_current)):
    import os
    if config.LOCAL_NO_PASSWORD:
        raise HTTPException(status_code=400, detail="本机免密码模式不支持修改密码")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if row is None or not authz.verify_password(body.old_password, row["salt"], row["pw_hash"]):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    # 重新包裹数据密钥（DEK 不变，仅换加密它的密码）。两阶段：新包裹先落日志，
    # DB 提交成功后 rename 转正；崩溃窗口由 _unlock_vault 的日志自愈兜住（P1-H2）。
    dek = None
    journal = False
    if config.KEYWRAP_PATH.exists():
        try:
            payload = json.loads(config.KEYWRAP_PATH.read_text())
            new_payload = crypto.rewrap_keywrap(payload, body.old_password, body.new_password)
            dek = crypto.unwrap_keywrap(payload, body.old_password)  # DEK 不变，保持解锁
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        vault.atomic_write_bytes(config.KEYWRAP_JOURNAL, json.dumps(new_payload).encode("utf-8"))
        journal = True
    salt, h = authz.hash_password(body.new_password)
    with db() as conn:
        conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (h, salt, user["id"]))
    if journal:
        os.replace(config.KEYWRAP_JOURNAL, config.KEYWRAP_PATH)  # DB 已提交 → 转正
    if dek is not None:
        vault.set_dek(dek)
    try:
        from .assistant import resume_paused_jobs
        resume_paused_jobs()
    except Exception:
        pass
    authz.revoke_all_for(user["id"])  # 令其他会话失效，需重新登录
    try:
        if config.INIT_PW_FILE.exists():
            config.INIT_PW_FILE.unlink()
    except OSError:
        pass
    return {"ok": True, "relogin": True}
