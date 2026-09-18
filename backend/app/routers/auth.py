"""认证路由：登录（首次登录创建数据密钥包裹）、登出、当前用户、修改密码。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .. import auth as authz
from .. import config, crypto, vault
from ..db import db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/login")
def login(body: LoginIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if row is None or not authz.verify_password(body.password, row["salt"], row["pw_hash"]):
        raise HTTPException(status_code=401, detail="账号或密码错误")
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


@router.post("/logout")
def logout(user: dict = Depends(authz.get_current),
           authorization: str = Header(default="")):
    if authorization.startswith("Bearer "):
        authz.revoke_token(authorization[7:])
    return {"ok": True}


@router.post("/lock")
def lock(user: dict = Depends(authz.get_current)):
    """一键上锁：撤销该用户全部 token 并清空内存数据密钥(DEK)。

    锁上后所有会话失效，加密正文/日记/相册等立即回到加密锁定态，
    必须重新输入主密码登录（login 会自动重新解锁 DEK）才能访问。
    """
    authz.revoke_all_for(user["id"])
    vault.clear_dek()
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(authz.get_current)):
    return {"id": user["id"], "username": user["username"]}


@router.put("/password")
def change_password(body: PasswordIn, user: dict = Depends(authz.get_current)):
    import os
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
    authz.revoke_all_for(user["id"])  # 令其他会话失效，需重新登录
    try:
        if config.INIT_PW_FILE.exists():
            config.INIT_PW_FILE.unlink()
    except OSError:
        pass
    return {"ok": True, "relogin": True}
