"""加密保存客户端业务状态；按键比较版本，避免旧页面覆盖其他设备的更改。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import crypto, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/client-state", tags=["client-state"])


class StateIn(BaseModel):
    value: str = Field(max_length=2_000_000)
    revision: int = Field(ge=0)


@router.get("")
def read_state(_user: dict = Depends(get_current)):
    with db() as conn:
        rows = conn.execute("SELECT key, value, revision FROM client_state").fetchall()
    return {r["key"]: {"value": crypto.dec_bytes(r["value"], vault.dek()).decode("utf-8"),
                       "revision": r["revision"]} for r in rows}


@router.put("/{key}")
def write_state(key: str, body: StateIn, _user: dict = Depends(get_current)):
    if not key.startswith("krs_") or len(key) > 180 or key in {"krs_token", "krs_user"}:
        raise HTTPException(status_code=400, detail="无效的状态键")
    ciphertext = crypto.enc_bytes(body.value.encode("utf-8"), vault.dek())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT revision FROM client_state WHERE key=?", (key,)).fetchone()
        current = old["revision"] if old else 0
        if body.revision != current:
            raise HTTPException(status_code=409, detail="此数据已在其他页面或设备更改")
        revision = current + 1
        conn.execute("INSERT INTO client_state(key, value, revision) VALUES(?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, revision=excluded.revision",
                     (key, ciphertext, revision))
    return {"revision": revision}
