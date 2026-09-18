"""认证基建：密码哈希(PBKDF2)、单用户 admin 引导、token 会话、请求鉴权依赖。"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
from datetime import datetime, timedelta

from fastapi import Header, HTTPException

from . import config, crypto
from .db import db

_ITER = 600_000


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now() -> datetime:
    return datetime.now()


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITER)
    return salt, digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, recomputed = hash_password(password, salt_hex)
    return secrets.compare_digest(recomputed, hash_hex)


def bootstrap_admin() -> None:
    """首次启动创建默认账号 admin + 随机密码，密码写入 data/initial_password.txt。"""
    with db() as conn:
        row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        if row:
            return
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        salt, h = hash_password(pw)
        conn.execute(
            "INSERT INTO users(username, pw_hash, salt, created_at) VALUES(?,?,?,?)",
            (config.ADMIN_USERNAME, h, salt, now_iso()),
        )
    try:
        config.INIT_PW_FILE.write_text(
            f"Kruskal 初始账号\n账号: {config.ADMIN_USERNAME}\n密码: {pw}\n\n"
            "登录后请立即在 设置 → 账户 中修改密码；修改成功后本文件会自动删除。\n"
        )
        os.chmod(config.INIT_PW_FILE, 0o600)
    except OSError:
        pass
    print(f"[kruskal] 首次启动，初始账号 {config.ADMIN_USERNAME} / 密码 {pw}"
          f"（已写入 {config.INIT_PW_FILE}，登录后请修改）")


def ensure_keywrap(password: str) -> None:
    """首次登录时创建数据密钥包裹；已存在则跳过。"""
    if not config.KEYWRAP_PATH.exists():
        payload, _ = crypto.create_keywrap(password)
        from . import vault
        vault.atomic_write_bytes(config.KEYWRAP_PATH, json.dumps(payload).encode("utf-8"))


MAX_ACTIVE_SESSIONS = 20  # 每用户活跃会话封顶，超出挤掉最旧（P1：token 治理）


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


def revoke_all_for(user_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))


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
        raise HTTPException(status_code=401, detail="未登录")
    user = token_user(authorization[7:])
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user
