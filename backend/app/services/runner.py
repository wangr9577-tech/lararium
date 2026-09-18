"""后台任务运行器：在 CODE_ROOT 白名单内启动脚本/训练命令，日志流式可查。

- 任务记录放内存 dict（重启即清，历史日志留在 data/tmp/runs/ 不落库）
- 默认超时 30 分钟，kill 接口可随时终止；并发上限 2（超了直接拒绝）
- 安全：只允许在 CODE_ROOT 内执行；命令由用户从前端显式输入
"""
from __future__ import annotations

import os
import secrets
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import config

MAX_CONCURRENT = 2
DEFAULT_TIMEOUT = int(os.environ.get("KRUSKAL_RUN_TIMEOUT", "1800"))

RUNS_DIR = config.DATA_DIR / "tmp" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tail(path: Path, n: int = 2000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = data.splitlines()
    return "\n".join(lines[-n:])


def list_tasks() -> list[dict]:
    with _lock:
        return [snapshot(r) for r in _tasks.values()]


def snapshot(t: dict) -> dict:
    return {
        "rid": t["rid"],
        "cmd": t["cmd"],
        "workdir": t["workdir"],
        "status": t["status"],
        "started_at": t["started_at"],
        "finished_at": t.get("finished_at", ""),
        "exit_code": t.get("exit_code"),
    }


def get_task(rid: str) -> dict | None:
    with _lock:
        t = _tasks.get(rid)
        return snapshot(t) if t else None


def start(workdir: str, cmd: list[str], timeout: int | None = None) -> dict:
    root = config.CODE_ROOT.resolve()
    wd = (Path(workdir) if Path(workdir).is_absolute() else root / workdir).resolve()
    if root not in wd.parents and wd != root:
        raise ValueError(f"工作目录必须在 {root} 内")
    with _lock:
        running = sum(1 for t in _tasks.values() if t["status"] == "running")
        if running >= MAX_CONCURRENT:
            raise RuntimeError(f"同时最多运行 {MAX_CONCURRENT} 个任务，请先终止其他任务")
        rid = secrets.token_hex(6)
        task = {
            "rid": rid, "cmd": " ".join(cmd), "workdir": str(wd),
            "status": "running", "started_at": _now(), "finished_at": "", "exit_code": None,
            "log_path": RUNS_DIR / f"{rid}.log", "timeout": timeout or DEFAULT_TIMEOUT,
            "proc": None, "timer": None,
        }
        task["log_path"].write_text("", encoding="utf-8")
        _tasks[rid] = task
    task["proc"] = subprocess.Popen(
        cmd, cwd=str(wd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,  # kill 时连子进程一起（进程组）
    )
    task["timer"] = threading.Timer(task["timeout"], lambda: _timeout_kill(task))
    task["timer"].start()
    threading.Thread(target=_pump, args=(task,), daemon=True).start()
    return snapshot(task)


def _pump(t: dict) -> None:
    proc = t["proc"]
    assert proc.stdout is not None
    try:
        for chunk in iter(proc.stdout.readline, b""):
            with open(t["log_path"], "ab") as f:
                f.write(chunk)
    except Exception:
        pass
    proc.wait()
    try:
        rc = proc.returncode if proc.returncode is not None else 1
        with _lock:
            t["status"] = "done"
            t["exit_code"] = rc
            t["finished_at"] = _now()
        if t["timer"]:
            t["timer"].cancel()
    except Exception:
        pass


def _timeout_kill(t: dict) -> None:
    try:
        if t.get("proc") and t["proc"].poll() is None:
            _kill(t["rid"])
            with _lock:
                if t["status"] == "running":
                    t["status"] = "done"
                    t["exit_code"] = 124
                    t["finished_at"] = _now()
    except Exception:
        pass


def kill_task(rid: str) -> dict:
    with _lock:
        t = _tasks.get(rid)
        if t is None:
            raise KeyError("任务不存在")
        proc = t.get("proc")
        if t["status"] != "running" or proc is None:
            return snapshot(t)
    _kill(rid)
    with _lock:
        t["status"] = "killed"
        t["exit_code"] = -9
        t["finished_at"] = _now()
        if t["timer"]:
            t["timer"].cancel()
    return snapshot(t)


def _kill(rid: str) -> None:
    with _lock:
        t = _tasks.get(rid)
        proc = t.get("proc") if t else None
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), 9)  # 进程组全杀
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:
            pass


def get_log(rid: str) -> dict:
    with _lock:
        t = _tasks.get(rid)
        if t is None:
            raise KeyError("任务不存在")
        log_path = t["log_path"]
        status = t["status"]
        exit_code = t.get("exit_code")
    return {"rid": rid, "status": status, "exit_code": exit_code, "log": _tail(log_path)}