"""代码工作区（M8）：白名单根目录内浏览/编辑/后台运行。

安全：
- 所有路径 resolve() 后必须位于 CODE_ROOT 内，越界 403
- 浏览只读；写入必须前端主动 PUT；单文件 ≤1MB
- 运行任务：services/runner（超时/并发/kill），日志在 data/tmp/runs
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..auth import get_current
from ..services import runner

router = APIRouter(prefix="/api/fs", tags=["fs"])

ROOT = config.CODE_ROOT
MAX_FILE = 1024 * 1024  # 1MB
MAX_DEPTH = 4
MAX_ENTRIES = 200
GIT_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea"}


def _safe(path: str) -> Path:
    raw = Path(path)
    p = raw if raw.is_absolute() else (ROOT / raw)
    resolved = p.resolve()
    if resolved != ROOT.resolve() and ROOT.resolve() not in resolved.parents:
        raise HTTPException(403, "路径不在代码工作区白名单内")
    return resolved


def _git_status(path: Path) -> dict:
    """轻量 git 状态：目录若在 git 仓库内返回分支与最近提交。"""
    try:
        branch = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True, text=True, timeout=3).stdout.strip() != ""
        return {"branch": branch, "commit": commit, "dirty": dirty}
    except Exception:
        return {"branch": "", "commit": "", "dirty": False}


@router.get("/root")
def fs_root(_user: dict = Depends(get_current)):
    return {"root": str(ROOT)}


@router.get("/tree")
def fs_tree(path: str = ".", depth: int = 1, _user: dict = Depends(get_current)):
    depth = max(1, min(depth, MAX_DEPTH))
    p = _safe(path)
    if not p.is_dir():
        raise HTTPException(400, "不是目录")
    git = _git_status(p) if any(x.is_dir() for x in p.iterdir() if x.name == ".git") else {}
    entries = []
    try:
        children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        children = []
    for c in children[:MAX_ENTRIES]:
        if c.name in GIT_DIRS:
            continue
        entries.append({"name": c.name, "type": "dir" if c.is_dir() else "file"})
    return {"path": str(p), "entries": entries, "git": git}


@router.get("/file")
def fs_read(path: str, _user: dict = Depends(get_current)):
    p = _safe(path)
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    size = p.stat().st_size
    if size > MAX_FILE:
        raise HTTPException(413, f"文件过大（>{MAX_FILE // 1024}KB），仅支持浏览")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        raise HTTPException(500, "读取失败")
    return {
        "path": str(p), "name": p.name, "size": size, "content": content,
        "git": _git_status(p.parent),
    }


class FileIn(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=MAX_FILE)


@router.put("/file")
def fs_write(body: FileIn, _user: dict = Depends(get_current)):
    p = _safe(body.path)
    if not p.is_file():
        raise HTTPException(404, "文件不存在（新建文件请用编辑器另存逻辑）")
    if p.stat().st_size > MAX_FILE:
        raise HTTPException(413, "文件过大，拒绝写入")
    try:
        p.write_text(body.content, encoding="utf-8")
    except Exception:
        raise HTTPException(500, "写入失败：权限不足或磁盘错误")
    # 回写 git 状态（若在仓库内）
    return {"ok": True, "path": str(p), "git": _git_status(p.parent)}


@router.get("/git")
def fs_git(path: str = ".", _user: dict = Depends(get_current)):
    p = _safe(path)
    return {"path": str(p), "git": _git_status(p if p.is_dir() else p.parent)}


class RunIn(BaseModel):
    workdir: str = Field(default=".", max_length=400)
    cmd: str = Field(min_length=1, max_length=500)
    timeout: int | None = Field(default=None, ge=60, le=86400)


@router.post("/run")
def fs_run(body: RunIn, _user: dict = Depends(get_current)):
    cmd = body.cmd.strip()
    if not cmd:
        raise HTTPException(400, "命令不能为空")
    # 安全：只允许在代码工作区内执行命令（拼成 shell 由用户自行负责，属本工作台既定能力）
    try:
        task = runner.start(body.workdir or ".", ["/bin/bash", "-c", cmd], body.timeout)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(429, str(e))
    return task


@router.get("/run")
def fs_runs(_user: dict = Depends(get_current)):
    return {"items": runner.list_tasks()}


@router.get("/run/{rid}/log")
def fs_run_log(rid: str, _user: dict = Depends(get_current)):
    try:
        return runner.get_log(rid)
    except KeyError:
        raise HTTPException(404, "任务不存在")


@router.post("/run/{rid}/kill")
def fs_run_kill(rid: str, _user: dict = Depends(get_current)):
    try:
        return runner.kill_task(rid)
    except KeyError:
        raise HTTPException(404, "任务不存在")