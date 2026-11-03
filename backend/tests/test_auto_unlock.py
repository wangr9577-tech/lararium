"""免密自动解锁（app/autokey.py）行为测试。

覆盖三件事：
1. 开启后重启（等价于 clear_dek + try_unlock）能恢复 DEK，且解出的 DEK
   与用主密码解 `.kek` 得到的是同一把——否则正文根本读不出来；
2. 免密不可用时必须**静默退回主密码**，不抛异常、不阻断启动；
3. 「关闭」与「一键上锁」都能立即撤销免密（否则上锁后重启又自动解锁）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment
from app import autokey, config, crypto, vault

env = TestEnvironment(prefix="kruskal_autokey_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def _login(password: str) -> str:
    resp = client.post("/api/auth/login",
                       json={"username": config.ADMIN_USERNAME, "password": password})
    assert resp.status_code == 200, resp.text
    env.token = resp.json()["token"]
    return env.token


def _status() -> dict:
    r = client.get("/api/auth/auto-unlock", headers=env.auth_headers())
    assert r.status_code == 200, r.text
    return r.json()


def test_off_by_default():
    assert not autokey.enabled()
    st = _status()
    assert st["enabled"] is False and st["unlocked"] is True


def test_enable_requires_correct_password():
    r = client.post("/api/auth/auto-unlock", headers=env.auth_headers(),
                    json={"password": "显然不对的密码"})
    assert r.status_code == 400, r.text
    assert not autokey.enabled()


def test_enable_creates_keypair():
    r = client.post("/api/auth/auto-unlock", headers=env.auth_headers(),
                    json={"password": env.admin_pw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True and body["unlocked"] is True
    assert config.AUTOKEY_KEY.is_file() and config.AUTOKEY_WRAP.is_file()
    # 包裹文件必须是可解析的 JSON，且版本对得上（将来换算法时旧文件要能识别）
    payload = json.loads(config.AUTOKEY_WRAP.read_text(encoding="utf-8"))
    assert payload["v"] == autokey.VERSION and payload["alg"] == "AES-256-GCM"


def test_restart_recovers_the_same_dek():
    """clear_dek 模拟进程重启：免密解出的 DEK 必须与主密码解出的完全一致。"""
    by_password = crypto.unwrap_keywrap(
        json.loads(config.KEYWRAP_PATH.read_text(encoding="utf-8")), env.admin_pw)
    assert by_password

    vault.clear_dek()
    assert not vault.has_dek()
    assert autokey.try_unlock() is True
    assert vault.has_dek()
    assert vault.dek() == by_password


def test_broken_key_degrades_to_password():
    """本机密钥损坏/被删/换机器 → 静默返回 False，绝不异常，也绝不半解锁。"""
    vault.clear_dek()
    config.AUTOKEY_KEY.write_bytes(b"\x00" * 32)  # 长度合法、内容错误
    assert autokey.try_unlock() is False
    assert not vault.has_dek()

    config.AUTOKEY_KEY.unlink()
    assert autokey.try_unlock() is False
    assert not autokey.enabled()

    _login(env.admin_pw)  # 回到主密码路径
    assert vault.has_dek()


def test_me_reports_state():
    client.post("/api/auth/auto-unlock", headers=env.auth_headers(),
                json={"password": env.admin_pw})
    r = client.get("/api/auth/me", headers=env.auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["auto_unlock"] is True


def test_disable_via_api():
    r = client.delete("/api/auth/auto-unlock", headers=env.auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == 2 and r.json()["enabled"] is False
    vault.clear_dek()
    assert autokey.try_unlock() is False
    _login(env.admin_pw)


def test_lock_revokes_auto_unlock():
    """一键上锁必须连免密一起撤销，否则重启就自动解锁，上锁等于没上。"""
    client.post("/api/auth/auto-unlock", headers=env.auth_headers(),
                json={"password": env.admin_pw})
    assert autokey.enabled()
    r = client.post("/api/auth/lock", headers=env.auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["auto_unlock_revoked"] is True
    assert not autokey.enabled()

    _login(env.admin_pw)


def test_password_change_keeps_auto_unlock():
    """改密只重新包裹 DEK（DEK 不变），免密应当继续有效，不必重开。"""
    client.post("/api/auth/auto-unlock", headers=env.auth_headers(),
                json={"password": env.admin_pw})
    new_pw = "fresh-password-2026"
    r = client.put("/api/auth/password", headers=env.auth_headers(),
                   json={"old_password": env.admin_pw, "new_password": new_pw})
    assert r.status_code == 200, r.text
    env.admin_pw = new_pw
    _login(new_pw)

    vault.clear_dek()
    assert autokey.try_unlock() is True
    assert vault.has_dek()
