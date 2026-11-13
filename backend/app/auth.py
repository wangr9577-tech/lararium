"""本机单用户会话基建：无账号密码，靠启动时解锁的数据密钥 + Bearer token 维持访问。

应用只在本机运行（见 main.py 启动流程）：
  1. 启动时用本机密钥 `.autokey` 解开 `.kek.auto`，把 DEK 放进 vault；
  2. 浏览器通过 `POST /api/auth/local-session` 换取 token；
  3. 之后所有 `/api` 请求带 `Authorization: Bearer <token>`，由 token_user 判定。

`users` 表沿用旧库结构（保留 pw_hash/salt 两列以兼容已存在的数据目录），
但不再写入密码，只作为 token 的归属记录。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import Header, HTTPException

from . import config
from .db import db


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now() -> datetime:
    return datetime.now()


def ensure_local_user() -> dict:
    """确保本机唯一用户存在（不设密码），返回 {id, username}。"""
    with db() as conn:
        row = conn.execute("SELECT id, username FROM users ORDER BY id LIMIT 1").fetchone()
        if row is not None:
            return {"id": row["id"], "username": row["username"]}
        cur = conn.execute(
            "INSERT INTO users(username, pw_hash, salt, created_at) VALUES(?,?,?,?)",
            (config.ADMIN_USERNAME, "", "", now_iso()),
        )
    return {"id": int(cur.lastrowid), "username": config.ADMIN_USERNAME}


MAX_ACTIVE_SESSIONS = 20  # 本机活跃会话封顶，超出挤掉最旧（P1：token 治理）


def issue_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    with db() as conn:
        conn.execute("DELETE FROM tokens WHERE expires_at <= ?", (now_iso(),))  # 顺手清过期
        conn.execute(
            "INSERT INTO tokens(token, user_id, created_at, expires_at) VALUES(?,?,?,?)",
            (token, user_id, now_iso(),
             (_now() + timedelta(days=config.TOKEN_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            "DELETE FROM tokens WHERE user_id=? AND token NOT IN "
            "(SELECT token FROM tokens WHERE user_id=? ORDER BY created_at DESC LIMIT ?)",
            (user_id, user_id, MAX_ACTIVE_SESSIONS),
        )
    return token


def sweep_expired() -> int:
    """启动时清一轮历史过期 token，返回删除数。"""
    with db() as conn:
        return conn.execute("DELETE FROM tokens WHERE expires_at <= ?", (now_iso(),)).rowcount


def revoke_token(token: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM tokens WHERE token=?", (token,))


def token_user(token: str) -> dict | None:
    """token → 用户（无效/过期返回 None）。供鉴权依赖与全局中间件共用一份判定。"""
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT u.id, u.username FROM tokens t JOIN users u ON u.id = t.user_id "
            "WHERE t.token=? AND t.expires_at > ?",
            (token, now_iso()),
        ).fetchone()
    return {"id": row["id"], "username": row["username"]} if row else None


def get_current(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未建立本机会话")
    user = token_user(authorization[7:])
    if user is None:
        raise HTTPException(status_code=401, detail="本机会话已失效，请刷新页面")
    return user
