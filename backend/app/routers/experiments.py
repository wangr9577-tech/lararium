"""实验记录本（M4，P2 核心）：实验/run 两级，指标序列存储 + 多 run 对比。

设计红线：只做记录，不托管产物 —— checkpoint/日志/数据集留在原处，库内仅存
路径引用（code_path/log_path/ckpt_path）；删除仅删自身记录，绝不碰产物文件。
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

STATUSES = ("active", "paused", "done", "archived", "failed")
MAX_METRICS = 400_000  # 指标点上限（单 run），超过拒绝写入提示升级 jsonl


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _metrics(metrics: dict) -> dict:
    """规范化指标：{"acc": {"0": 0.1}, ...} → {"acc": {"0": 0.1}}（步号转字符串）。"""
    out = {}
    for name, series in metrics.items():
        if not isinstance(series, dict):
            continue
        norm = {}
        for k, v in series.items():
            try:
                norm[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
        if norm:
            out[name] = norm
    return out


def _exp_row(r) -> dict:
    return {
        "id": r["id"], "title": r["title"], "goal": r["goal"], "hypothesis": r["hypothesis"],
        "status": r["status"], "code_path": r["code_path"], "tags": json.loads(r["tags"] or "[]"),
        "conclusion": r["conclusion"], "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _run_row(r) -> dict:
    return {
        "id": r["id"], "experiment_id": r["experiment_id"], "name": r["name"],
        "config": json.loads(r["config_json"] or "{}"), "git_commit": r["git_commit"],
        "env_info": r["env_info"], "metrics": json.loads(r["metrics_json"] or "{}"),
        "log_path": r["log_path"], "ckpt_path": r["ckpt_path"], "note": r["note"],
        "created_at": r["created_at"],
    }


class ExperimentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(default="", max_length=4000)
    hypothesis: str = Field(default="", max_length=4000)
    status: str = Field(default="active")
    code_path: str = Field(default="", max_length=400)
    tags: list[str] = Field(default_factory=list, max_length=20)
    conclusion: str = Field(default="", max_length=20_000)


class RunIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: dict = Field(default_factory=dict)
    git_commit: str = Field(default="", max_length=80)
    env_info: str = Field(default="", max_length=300)
    metrics: dict = Field(default_factory=dict)
    log_path: str = Field(default="", max_length=400)
    ckpt_path: str = Field(default="", max_length=400)
    note: str = Field(default="", max_length=4000)


@router.get("")
def list_experiments(status: str = "", _user: dict = Depends(get_current)):
    sql = "SELECT * FROM experiments WHERE 1=1"
    args: list = []
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
        sql += " AND status=?"
        args.append(status)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()
    return {"items": [_exp_row(r) for r in rows]}


@router.post("", status_code=201)
def create_experiment(body: ExperimentIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO experiments(title, goal, hypothesis, status, code_path, tags, conclusion, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (body.title.strip()[:200], body.goal.strip()[:4000], body.hypothesis.strip()[:4000],
             body.status, body.code_path.strip()[:400], json.dumps(body.tags[:20], ensure_ascii=False),
             body.conclusion.strip()[:20000], now, now),
        )
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (cur.lastrowid,)).fetchone()
    return _exp_row(row)


@router.get("/{exp_id}")
def get_experiment(exp_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "实验不存在")
        runs = conn.execute(
            "SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY id", (exp_id,)).fetchall()
    out = _exp_row(row)
    out["runs"] = [_run_row(r) for r in runs]
    return out


@router.put("/{exp_id}")
def update_experiment(exp_id: int, body: ExperimentIn, _user: dict = Depends(get_current)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status 只能是 {list(STATUSES)}")
    with db() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "实验不存在")
        conn.execute(
            "UPDATE experiments SET title=?, goal=?, hypothesis=?, status=?, code_path=?, "
            "tags=?, conclusion=?, updated_at=? WHERE id=?",
            (body.title.strip()[:200], body.goal.strip()[:4000], body.hypothesis.strip()[:4000],
             body.status, body.code_path.strip()[:400], json.dumps(body.tags[:20], ensure_ascii=False),
             body.conclusion.strip()[:20000], _now(), exp_id),
        )
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    return _exp_row(row)


@router.delete("/{exp_id}")
def delete_experiment(exp_id: int, _user: dict = Depends(get_current)):
    """仅删除实验记录（SQLite 行），绝不触碰 log/ckpt/code 等产物文件。"""
    with db() as conn:
        cur = conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
        conn.execute("DELETE FROM experiment_runs WHERE experiment_id=?", (exp_id,))
        conn.execute("DELETE FROM idea_links WHERE target_type='experiment' AND target_id=?",
                     (str(exp_id),))
    if cur.rowcount == 0:
        raise HTTPException(404, "实验不存在")
    return {"ok": True}


@router.post("/{exp_id}/runs", status_code=201)
def create_run(exp_id: int, body: RunIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "实验不存在")
        try:
            cur = conn.execute(
                "INSERT INTO experiment_runs(experiment_id, name, config_json, git_commit, "
                "env_info, metrics_json, log_path, ckpt_path, note, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (exp_id, body.name.strip()[:120], json.dumps(body.config, ensure_ascii=False),
                 body.git_commit.strip()[:80], body.env_info.strip()[:300],
                 json.dumps(_metrics(body.metrics), ensure_ascii=False),
                 body.log_path.strip()[:400], body.ckpt_path.strip()[:400],
                 body.note.strip()[:4000], _now()),
            )
        except Exception:
            raise HTTPException(409, "同名 run 已存在")
        row = conn.execute("SELECT * FROM experiment_runs WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.execute("UPDATE experiments SET updated_at=? WHERE id=?", (_now(), exp_id))
    return _run_row(row)


@router.put("/runs/{run_id}")
def update_run(run_id: int, body: RunIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM experiment_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "run 不存在")
        conn.execute(
            "UPDATE experiment_runs SET name=?, config_json=?, git_commit=?, env_info=?, "
            "metrics_json=?, log_path=?, ckpt_path=?, note=? WHERE id=?",
            (body.name.strip()[:120], json.dumps(body.config, ensure_ascii=False),
             body.git_commit.strip()[:80], body.env_info.strip()[:300],
             json.dumps(_metrics(body.metrics), ensure_ascii=False),
             body.log_path.strip()[:400], body.ckpt_path.strip()[:400],
             body.note.strip()[:4000], run_id),
        )
        row = conn.execute("SELECT * FROM experiment_runs WHERE id=?", (run_id,)).fetchone()
        conn.execute(
            "UPDATE experiments SET updated_at=? WHERE id=?", (_now(), row["experiment_id"]))
    return _run_row(row)


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, _user: dict = Depends(get_current)):
    """仅删 run 记录，不碰产物文件。"""
    with db() as conn:
        cur = conn.execute("DELETE FROM experiment_runs WHERE id=?", (run_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "run 不存在")
    return {"ok": True}


@router.get("/{exp_id}/compare")
def compare_runs(exp_id: int, run_ids: str, _user: dict = Depends(get_current)):
    """多 run 指标对比：?run_ids=1,2,3 → 各 run 的序列数据。"""
    ids = [x.strip() for x in run_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "run_ids 至少一个")
    placeholders = ",".join("?" * len(ids))
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM experiment_runs WHERE experiment_id=? AND id IN ({placeholders}) "
            "ORDER BY id", (exp_id, *ids)).fetchall()
    return {"items": [_run_row(r) for r in rows]}