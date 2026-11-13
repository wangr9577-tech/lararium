from backend.tests.test_env import TestEnvironment
import pytest
from fastapi import HTTPException
from app.routers.client_state import StateIn, read_state, write_state

env = TestEnvironment(prefix="kruskal_client_state_")


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_state_encrypted_and_stale_write_rejected():
    key = 'krs_pomo_name'
    assert write_state(key, StateIn(value='私人任务', revision=0), {}) == {'revision': 1}
    with pytest.raises(HTTPException) as exc:
        write_state(key, StateIn(value='旧页面', revision=0), {})
    assert exc.value.status_code == 409
    assert read_state({})[key] == {'value': '私人任务', 'revision': 1}
    assert write_state(key, StateIn(value='新任务', revision=1), {}) == {'revision': 2}
    from app.db import db
    with db() as conn:
        raw = conn.execute("SELECT value FROM client_state WHERE key='krs_pomo_name'").fetchone()['value']
    assert b'KRSLC1\n' in raw and '新任务'.encode() not in raw


def test_state_does_not_accept_session_token():
    with pytest.raises(HTTPException) as exc:
        write_state('krs_token', StateIn(value='secret', revision=0), {})
    assert exc.value.status_code == 400
