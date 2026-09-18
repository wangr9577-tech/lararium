"""回收站：删除的文件先进 data/trash/<tid>/，显式"永久删除"才物理删。

manifest.json 用 vault 加密（与全站内容同等级：删除项的标题等也算内容）。
清单结构：{tid, module, label, deleted_at, entries:[{rel, stored}]}
  rel    = 相对 DATA_DIR 的原路径（恢复目的地）
  stored = 回收站内暂存文件名（rel 的扁平化，防重名）
"""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from . import config, vault

TRASH_DIR = config.DATA_DIR / "trash"
TID_RE = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _entry_dir(tid: str) -> Path:
    return TRASH_DIR / tid


def _manifest_path(tid: str) -> Path:
    return _entry_dir(tid) / "manifest.json"


def _flatten(rel: str) -> str:
    return rel.replace("/", "__")


def move_to_trash(items: list[Path], *, module: str, label: str) -> str | None:
    """把 DATA_DIR 下的文件/目录整体移入回收站；返回回收站 id。

    移动中途失败则把已移动的回滚回原位置再抛错，绝不留下"原处没了、回收站也没有"。
    无可移动项（路径都不存在）返回 None。
    """
    entries: list[dict] = []
    moved: list[tuple[Path, str]] = []  # (回收站内暂存路径, 原相对路径)
    tid = uuid.uuid4().hex
    dest = _entry_dir(tid)
    try:
        for p in items:
            if not p.exists():
                continue
            rel = p.relative_to(config.DATA_DIR).as_posix()
            dest.mkdir(parents=True, exist_ok=True)
            stored = _flatten(rel)
            shutil.move(str(p), str(dest / stored))
            moved.append((dest / stored, rel))
            entries.append({"rel": rel, "stored": stored})
        if not entries:
            return None
        manifest = {"tid": tid, "module": module, "label": label,
                    "deleted_at": _now(), "entries": entries}
        vault.write_json(_manifest_path(tid), manifest)
        return tid
    except Exception:
        for src, rel in moved:  # 回滚
            try:
                target = config.DATA_DIR / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(target))
            except OSError:
                pass
        shutil.rmtree(dest, ignore_errors=True)
        raise


def list_items() -> list[dict]:
    out = []
    if not TRASH_DIR.is_dir():
        return out
    for d in sorted(TRASH_DIR.iterdir(), reverse=True):
        mp = d / "manifest.json"
        if not d.is_dir() or not mp.is_file():
            continue
        try:
            m = vault.read_json(mp)
        except Exception:
            # 损坏/未解锁：未解锁由 vault.dek() 抛 423 冒泡；此处只兜底真正的坏文件，不让列表整体炸
            out.append({"tid": d.name, "module": "?", "label": "（清单损坏，无法解读）",
                        "deleted_at": "", "entries": [], "broken": True})
            continue
        out.append({
            "tid": m.get("tid", d.name), "module": m.get("module", ""),
            "label": m.get("label", ""), "deleted_at": m.get("deleted_at", ""),
            "count": len(m.get("entries", [])),
        })
    out.sort(key=lambda x: x.get("deleted_at", ""), reverse=True)
    return out


def _read_manifest(tid: str) -> dict:
    mp = _manifest_path(tid)
    if not TID_RE.match(tid) or not mp.is_file():
        raise HTTPException(404, "回收站条目不存在")
    return vault.read_json(mp)


def restore(tid: str) -> dict:
    """恢复一个回收站条目回原路径；目的地已有同名文件则 409 中止（不覆盖任何东西）。"""
    m = _read_manifest(tid)
    for e in m.get("entries", []):
        if (config.DATA_DIR / e["rel"]).exists():
            raise HTTPException(409, f"恢复目的地已存在（{e['rel']}），未做任何改动")
    restored: list[tuple[Path, str]] = []  # (目标路径, 暂存名) 用于回滚
    try:
        for e in m.get("entries", []):
            src = _entry_dir(tid) / e["stored"]
            if not src.exists():
                raise HTTPException(500, f"回收站内文件缺失：{e['stored']}")
            target = config.DATA_DIR / e["rel"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            restored.append((target, e["stored"]))
    except Exception:
        for target, stored in restored:  # 回滚已恢复的
            try:
                shutil.move(str(target), str(_entry_dir(tid) / stored))
            except OSError:
                pass
        raise
    shutil.rmtree(_entry_dir(tid), ignore_errors=True)
    return {"ok": True, "module": m.get("module"), "label": m.get("label"),
            "deleted_at": m.get("deleted_at", ""),
            "restored": len(m.get("entries", [])),
            "rels": [e["rel"] for e in m.get("entries", [])]}


def purge(tid: str) -> dict:
    """永久删除（物理删）。这是全项目唯一的"真删"入口，仅供用户显式操作。"""
    if not TID_RE.match(tid) or not _entry_dir(tid).is_dir():
        raise HTTPException(404, "回收站条目不存在")
    shutil.rmtree(_entry_dir(tid))
    return {"ok": True}
