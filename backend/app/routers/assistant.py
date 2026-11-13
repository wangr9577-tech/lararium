"""助手（Assistant）路由器：统一收集、通知聚合研判、稍后看轻量卡片、日程与工作台闭环。

核心规范：
- 分流（Auto）：auto 模式先按 CLASSIFY_PROMPT 让模型判 notice/later（图片输入可用），模型不可用才退回关键词规则；
  notice 走通知流，later 走稍后看流；用户显式选择的模式永远优先。
- 通知流（Notice）：保存原文与证据文件，抽取 DDL 并聚合到相同事务线程，创建唯一日程 DDL 项（防污染）；
- 稍后看流（Later）：轻量卡片（简介+关注理由+分类+标签），不聚合事项、不产出 DDL，处理完清理临时大文件；
- 状态与加解密：低敏元数据存 SQLite，正文与卡片存 Vault（data/assistant/）；
- 上锁防御：调用前后比对 DEK Epoch，上锁时转为 paused_locked，杜绝越权与异常。
"""
from __future__ import annotations

import json
import io
import logging
import mimetypes
import os
import re
import shutil
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current, token_user
from ..db import db
from ..services import llm, assistant_prompts, attachment_agent
from ..ai import assistant_workflows as assistant_ai

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger("assistant")
_source_summary_jobs: dict[int, dict[str, str]] = {}

MAX_TEXT = 200_000
MAX_TITLE = 200
MAX_NOTE = 5_000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
_job_locks: dict[int, threading.Lock] = {}
_job_locks_guard = threading.Lock()


def _job_lock(record_id: int) -> threading.Lock:
    with _job_locks_guard:
        return _job_locks.setdefault(record_id, threading.Lock())

KINDS = ("notice", "later")
MODES = ("auto", "notice", "later")
READ_STATES = ("unread", "read", "noted")
SCOPES = ("all", "alerts", "notice", "later", "archived")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _require_dek() -> None:
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重启本机服务后重试")


def _asst_dir() -> Path:
    return config.DATA_DIR / "assistant"


def _records_dir() -> Path:
    return _asst_dir() / "records"


def _threads_dir() -> Path:
    return _asst_dir() / "threads"


def _record_dir(record_id: int) -> Path:
    return _records_dir() / str(record_id)


def _thread_dir(thread_id: int) -> Path:
    return _threads_dir() / str(thread_id)


def _extract_text_from_file_bytes(filename: str, content: bytes) -> str:
    """从附件提取文本；无法读取时返回空字符串，由后台作业报告。"""
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 16 * 1024 * 1024 or len(archive.infolist()) > 2048:
                    return ""
                xml = archive.read(info)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    return ""
                root = ET.fromstring(xml)
                ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                paragraphs = []
                for paragraph in root.iter(ns + "p"):
                    parts = []
                    for node in paragraph.iter():
                        if node.tag == ns + "t":
                            parts.append(node.text or "")
                        elif node.tag == ns + "tab":
                            parts.append("\t")
                        elif node.tag in (ns + "br", ns + "cr"):
                            parts.append("\n")
                    value = "".join(parts).strip()
                    if value:
                        paragraphs.append(value)
                if paragraphs:
                    return f"\n\n【Word 附件 {filename} 文本解析内容】\n" + "\n".join(paragraphs)
        except (KeyError, ValueError, OSError, zipfile.BadZipFile, ET.ParseError):
            pass
    elif ext == ".pdf":
        try:
            import pymupdf as fitz
            doc = fitz.open(stream=content, filetype="pdf")
            pages = []
            for i, page in enumerate(doc):
                txt = page.get_text()
                if txt.strip():
                    pages.append(f"--- [第 {i+1} 页] ---\n{txt.strip()}")
            if pages:
                return f"\n\n【PDF 附件 {filename} 文本解析内容】\n" + "\n".join(pages).strip()
        except Exception:
            pass
    elif ext in (".txt", ".md", ".json", ".csv", ".log", ".py", ".ts", ".html"):
        try:
            decoded = content.decode("utf-8-sig").strip()
            return f"\n\n【文本附件 {filename} 提取内容】\n" + decoded if decoded else ""
        except Exception:
            pass
    return ""


def _combine_source_tasks(tasks: list[dict]) -> list[dict]:
    """Only collapse identical actions with identical dates; preserve differing deadlines."""
    combined: list[dict] = []
    keys: dict[tuple, dict] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        key = (re.sub(r"\s+", "", str(task.get("title") or "")).casefold(),
               task.get("deadline_date") or "", task.get("deadline_time") or "", task.get("kind") or "deadline")
        if not key[0]:
            continue
        if key in keys:
            target = keys[key]
            target["source_record_ids"] = list(dict.fromkeys(
                (target.get("source_record_ids") or []) + (task.get("source_record_ids") or [])
            ))
        else:
            target = dict(task)
            keys[key] = target
            combined.append(target)
    dates_by_title: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for task in combined:
        key = (re.sub(r"\s+", "", str(task.get("title") or "")).casefold(), task.get("kind") or "deadline")
        if task.get("deadline_date"):
            dates_by_title.setdefault(key, set()).add((task["deadline_date"], task.get("deadline_time") or ""))
    for task in combined:
        key = (re.sub(r"\s+", "", str(task.get("title") or "")).casefold(), task.get("kind") or "deadline")
        task["date_conflict"] = len(dates_by_title.get(key, set())) > 1
    return combined


def _normalize_notice_tasks(values: Any, raw_text: str, record_id: int) -> list[dict]:
    result = []
    if not isinstance(values, list):
        return result
    for value in values[:50]:
        if not isinstance(value, dict) or not str(value.get("title") or "").strip():
            continue
        date = str(value.get("deadline_date") or "").strip()
        time = str(value.get("deadline_time") or "").strip()
        try:
            if date:
                datetime.strptime(date, "%Y-%m-%d")
            if time:
                datetime.strptime(time, "%H:%M")
        except ValueError:
            date, time = "", ""
        quote = str(value.get("quote") or value.get("evidence") or "").strip()
        if quote and quote not in raw_text:
            quote = ""
        result.append({"id": uuid.uuid4().hex, "title": str(value["title"]).strip()[:300],
                       "deadline_date": date, "deadline_time": time,
                       "kind": value.get("kind") if value.get("kind") in ("deadline", "event") else "deadline",
                       "quote": quote, "source_record_ids": [record_id], "done": False})
    return result


def _source_messages(source_rows: list[Any]) -> list[dict]:
    """每条来源各有独立摘要和可在该来源中核对的原文摘录。"""
    messages = []
    for source in source_rows:
        record_id = int(source["id"])
        card = _read_encrypted_json(_record_dir(record_id) / "card.enc")
        if not card:
            messages.append({"record_id": record_id, "title": source["title"], "summary": "",
                             "evidence_quotes": [], "needs_summary": True})
            continue
        summary = str(card.get("source_summary") or "").strip()
        needs_summary = not summary and card.get("change_type") not in (None, "", "new")
        if not summary and not needs_summary:
            summary = str(card.get("summary") or card.get("brief") or "").strip()
        try:
            raw = vault.read_text(_record_dir(record_id) / "raw.enc") if vault.has_dek() else ""
        except Exception:
            raw = ""
        quotes = []
        for quote in [card.get("quote")] + (card.get("evidence_quotes") if isinstance(card.get("evidence_quotes"), list) else []):
            if isinstance(quote, str):
                quote = quote.strip()
                if quote and quote in raw and quote not in quotes:
                    quotes.append(quote)
        messages.append({"record_id": record_id, "title": source["title"], "summary": summary,
                         "evidence_quotes": quotes, "needs_summary": needs_summary})
    return messages


def _sync_task_schedules(thread_id: int, tasks: list[dict]) -> None:
    """Synchronize dated tasks without overriding a user-modified or dismissed schedule."""
    with db() as conn:
        for task in tasks:
            task_id = task.get("id")
            date = task.get("deadline_date") or ""
            if not task_id:
                continue
            link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND task_id=? ORDER BY id LIMIT 1",
                (thread_id, task_id),
            ).fetchone()
            if not link:
                sources = task.get("source_record_ids") or []
                dismissed = None
                for source_id in sources:
                    dismissed = conn.execute(
                        "SELECT id FROM assistant_schedule_links WHERE thread_id=? AND record_id=? AND task_id IS NULL AND user_dismissed=1 LIMIT 1",
                        (thread_id, source_id),
                    ).fetchone()
                    if dismissed:
                        break
                if dismissed:
                    # The old link no longer contains its deleted date. Preserve the
                    # user's deletion rather than guessing which extracted task it was.
                    conn.execute("INSERT INTO assistant_schedule_links(thread_id,record_id,schedule_id,role,locked_by_user,user_dismissed,created_at,task_id) VALUES(?,?,NULL,'ddl',0,1,?,?)",
                                 (thread_id, sources[0], now_iso(), task_id))
                    continue
            if not link and date:
                # Adopt an existing legacy deadline only when its date and time match.
                link = conn.execute(
                    "SELECT sl.* FROM assistant_schedule_links sl JOIN schedule s ON s.id=sl.schedule_id "
                    "WHERE sl.thread_id=? AND sl.task_id IS NULL AND s.date=? AND COALESCE(s.time_start,'')=? LIMIT 1",
                    (thread_id, date, task.get("deadline_time") or ""),
                ).fetchone()
                if link:
                    conn.execute("UPDATE assistant_schedule_links SET task_id=? WHERE id=?", (task_id, link["id"]))
            if link and (link["locked_by_user"] or link["user_dismissed"]):
                continue
            if link and link["schedule_id"]:
                if date:
                    conn.execute("UPDATE schedule SET date=?,time_start=?,title=?,done=? WHERE id=?",
                                 (date, task.get("deadline_time") or "", f"【截止】{task['title']}", int(bool(task.get("done"))), link["schedule_id"]))
                else:
                    conn.execute("DELETE FROM schedule WHERE id=?", (link["schedule_id"],))
                    conn.execute("DELETE FROM assistant_schedule_links WHERE id=?", (link["id"],))
            elif not link and date and task.get("kind") != "event" and not task.get("date_conflict"):
                now = now_iso()
                cur = conn.execute(
                    "INSERT INTO schedule(date,kind,type,title,time_start,note,done,sort,created_at) VALUES(?,?,?,?,?,?,?,0,?)",
                    (date, "daily", "ddl", f"【截止】{task['title']}", task.get("deadline_time") or "", "详见助手通知事项", int(bool(task.get("done"))), now),
                )
                sources = task.get("source_record_ids") or []
                conn.execute("INSERT INTO assistant_schedule_links(thread_id,record_id,schedule_id,role,locked_by_user,user_dismissed,created_at,task_id) VALUES(?,?,?,'ddl',0,0,?,?)",
                             (thread_id, sources[0] if sources else None, cur.lastrowid, now, task_id))


def _extract_quote_and_evidence(text: str, ddl_date: str = "", ddl_time: str = "") -> tuple[str, list[str]]:
    """从原文中精准定位最核心的事实依据句子（如截止时间所在原句），并提取支撑事实段落。"""
    if not text:
        return "", []

    raw_sentences = []
    lines = [l.strip() for l in re.split(r"[\r\n]+", text) if l.strip()]
    for line in lines:
        parts = re.split(r"(?<=[。；!！\?？\n])", line)
        for part in parts:
            p = part.strip()
            if len(p) >= 6:
                raw_sentences.append(p)

    candidates: list[tuple[float, str]] = []
    evidence_list: list[str] = []

    ddl_keywords = (
        "截止", "申报截止", "提交截止", "系统截止", "报名截止", "有效至", "逾期",
        "前完成", "最晚于", "前提交", "前报送", "前发送", "前上传", "延期至", "顺延至", "推迟至", "关闭"
    )
    req_keywords = ("要求", "注意", "务必", "材料", "申报", "提交", "通知", "审核", "流程", "推荐信")

    date_parts = []
    if ddl_date:
        parts = ddl_date.split("-")
        if len(parts) == 3:
            y, m, d = parts
            date_parts = [f"{int(m)}月{int(d)}", f"{m}-{d}", f"{m}/{d}", f"{y}年", f"{y}-{m}"]

    for sent in raw_sentences:
        score = 0.0
        for kw in ddl_keywords:
            if kw in sent:
                score += 15.0
        for dp in date_parts:
            if dp in sent:
                score += 25.0
        if ddl_time and ddl_time in sent:
            score += 10.0

        if score > 0:
            candidates.append((score, sent))

        if any(rk in sent for rk in req_keywords) and len(sent) <= 120:
            if sent not in evidence_list:
                evidence_list.append(sent)

    candidates.sort(key=lambda x: x[0], reverse=True)
    primary_quote = candidates[0][1] if candidates else ""

    if not primary_quote and raw_sentences:
        for s in raw_sentences:
            if any(k in s for k in ("通知", "关于", "项目", "申报", "时间", "要求")):
                primary_quote = s
                break
        if not primary_quote:
            primary_quote = raw_sentences[0]

    filtered_evidence = [e for e in evidence_list if e != primary_quote][:4]
    return primary_quote[:300], filtered_evidence


def _get_record_attachments(record_id: int) -> list[dict]:
    """获取记录的附件清单，包含完整下载预览 URL 与元数据。"""
    rec_dir = _record_dir(record_id)
    assets_dir = rec_dir / "assets"
    attachments: list[dict] = []
    if not assets_dir.is_dir():
        return attachments

    meta_map: dict[str, dict] = {}
    meta_p = rec_dir / "attachments_meta.enc"
    if meta_p.exists() and vault.has_dek():
        try:
            for m in vault.read_json(meta_p):
                meta_map[m.get("filename")] = m
        except Exception:
            pass

    for p in sorted(assets_dir.glob("*"), key=lambda x: x.name):
        if not p.is_file() or p.name.startswith((".", "_")):
            continue
        ext = p.suffix.lower()
        is_img = ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")
        meta = meta_map.get(p.name, {})
        orig_name = meta.get("original_name") or p.name
        sz = meta.get("size")
        if sz is None:
            try:
                sz = p.stat().st_size
            except Exception:
                sz = 0

        mime = meta.get("mime") or mimetypes.guess_type(orig_name)[0] or "application/octet-stream"
        attachments.append({
            "filename": p.name,
            "original_name": orig_name,
            "url": f"/api/assistant/records/{record_id}/attachments/{p.name}",
            "size": sz,
            "is_image": is_img,
            "mime": mime,
        })
    return attachments


def _authenticate_user_for_attachment(
    authorization: str = "",
    token: str = "",
    request: Request | None = None,
) -> dict:
    """附件访问鉴权：优先使用 Bearer Token，支持从 URL Query 参数 ?token= 读取（用于浏览器新标签预览/下载及 img 标签）。"""
    raw_token = ""
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[7:].strip()
    elif token:
        raw_token = token.strip()
    elif request and "access_token" in request.cookies:
        raw_token = request.cookies.get("access_token", "").strip()

    if not raw_token:
        raise HTTPException(status_code=401, detail="缺少本机会话令牌")
    user = token_user(raw_token)
    if user is None:
        raise HTTPException(status_code=401, detail="本机会话已失效，请刷新页面")
    return user


# ---------- Pydantic 模型 ----------

class SubmitIn(BaseModel):
    text: str = ""
    mode: str = "auto"
    source_type: str = "text"
    source_url: str = ""
    user_note: str = ""
    capture_id: int | None = None


class RecordPatchIn(BaseModel):
    read_state: str | None = None
    archived: int | None = None
    pinned: int | None = None
    category: str | None = None
    user_note: str | None = None
    title: str | None = None
    tags: list[str] | None = None


class ThreadReconcileIn(BaseModel):
    title: str | None = None
    summary: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    has_conflict: bool | None = None
    update_schedule: bool = True
    status: str | None = None


class ChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    thread_id: int | None = None
    record_id: int | None = None


class LinkNoteIn(BaseModel):
    note_id: str


class SplitSourceIn(BaseModel):
    record_id: int


class TaskPatchIn(BaseModel):
    title: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    done: bool | None = None


class MergeThreadIn(BaseModel):
    source_thread_id: int


@router.post("/threads/{thread_id}/suggestions/{candidate_thread_id}/dismiss")
def dismiss_match_suggestion(thread_id: int, candidate_thread_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        conn.execute("UPDATE assistant_match_suggestions SET dismissed=1 WHERE thread_id=? AND candidate_thread_id=?", (thread_id, candidate_thread_id))
        left = [r[0] for r in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=?", (thread_id,))]
        right = [r[0] for r in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=?", (candidate_thread_id,))]
        for a in left:
            for b in right:
                conn.execute("INSERT OR IGNORE INTO assistant_separate_sources(record_a,record_b) VALUES(?,?)", tuple(sorted((a, b))))
    return {"ok": True}


class LinkWorkbenchIn(BaseModel):
    wb_item_id: int


# ---------- 核心后台作业处理逻辑 ----------

def _choose_candidate(payload: list[dict], content: str,
                      images: list[tuple[bytes, str]] | None = None) -> dict:
    """让模型检索候选；模型提出可能关联时，再让模型独立核对事项边界。"""
    return assistant_ai.choose_candidate(payload, content, images)


def _classify_record_kind(rec: Any, raw_text: str, images: list[tuple[bytes, str]]) -> tuple[str, int | None]:
    """auto 模式分流：按 CLASSIFY_PROMPT 让模型判 notice/later。

    不做关键词兜底：模型不可用或输出非法时直接抛 AiUnavailable，由作业标记 failed，
    避免静默误分流把待办塞进稍后看。
    """
    result = assistant_ai.classify(raw_text, rec['source_url'], rec['user_note'], images)
    kind = str(result.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise llm.AiUnavailable("模型未能判断内容类型（notice/later），请重试")
    if kind == "later" and (raw_text.strip() or images):
        # 一条补充说明本身可以不要求行动，但仍可能属于已有的考试或项目。
        # 只把文本线索用于召回；是否为同一事项仍由模型明确确认。
        with db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT t.id,t.title,t.summary,t.deadline_date FROM assistant_threads t "
                "JOIN assistant_thread_sources s ON s.thread_id=t.id "
                "JOIN assistant_records r ON r.id=s.record_id "
                "WHERE t.status!='archived' AND r.kind='notice' ORDER BY t.updated_at DESC"
            ).fetchall()
            blocked = {r[0] for r in conn.execute(
                "SELECT CASE WHEN record_a=? THEN record_b ELSE record_a END FROM assistant_separate_sources WHERE record_a=? OR record_b=?",
                (rec["id"], rec["id"], rec["id"]),
            )}
            links = conn.execute(
                "SELECT s.thread_id,s.record_id,r.title FROM assistant_thread_sources s "
                "JOIN assistant_records r ON r.id=s.record_id ORDER BY s.sequence"
            ).fetchall()
        blocked_threads = {r["thread_id"] for r in links if r["record_id"] in blocked}
        eligible = [row for row in rows if row["id"] not in blocked_threads]
        for start in range(0, len(eligible), 25):
            selected = eligible[start:start + 25]
            payload = []
            for row in selected:
                facts = _read_encrypted_json(_thread_dir(row["id"]) / "facts.enc")
                sources = []
                for link in (link for link in links if link["thread_id"] == row["id"]):
                    card = _read_encrypted_json(_record_dir(link["record_id"]) / "card.enc")
                    sources.append({"title": link["title"], "summary": card.get("summary") or card.get("brief") or ""})
                payload.append({"id": row["id"], "title": row["title"],
                                "summary": facts.get("summary") or row["summary"],
                                "deadline": row["deadline_date"], "sources": sources})
            try:
                choice = _choose_candidate(payload, f"补充内容\n原文：{raw_text[:12000]}", images)
                if choice.get("same_event") is True and any(row["id"] == choice.get("thread_id") for row in selected):
                    return "notice", choice["thread_id"]
            except llm.AiUnavailable:
                break
    return kind, None


def _attach_earlier_supplement(thread_id: int, record_id: int, raw_text: str, job_epoch: int) -> None:
    """Consider auto-classified reading records that preceded this notice."""
    if not raw_text.strip():
        return
    with db() as conn:
        rows = conn.execute(
            "SELECT r.id,r.title FROM assistant_records r LEFT JOIN assistant_thread_sources s ON s.record_id=r.id "
            "WHERE r.kind='later' AND r.input_mode='auto' AND r.status='ready' AND r.archived=0 "
            "AND r.id<? AND s.record_id IS NULL ORDER BY r.created_at DESC", (record_id,)
        ).fetchall()
        blocked = {r[0] for r in conn.execute(
            "SELECT CASE WHEN record_a=? THEN record_b ELSE record_a END FROM assistant_separate_sources WHERE record_a=? OR record_b=?",
            (record_id, record_id, record_id),
        )}
    selected = [row for row in rows if row["id"] not in blocked]
    old_id = None
    for start in range(0, len(selected), 25):
        batch = selected[start:start + 25]
        payload = []
        for row in batch:
            card = _read_encrypted_json(_record_dir(row["id"]) / "card.enc")
            payload.append({"id": row["id"], "title": row["title"], "summary": card.get("summary") or card.get("brief") or ""})
        try:
            choice = _choose_candidate(payload, f"新事项\n原文：{raw_text[:12000]}")
        except llm.AiUnavailable:
            return
        if choice.get("same_event") is True and any(r["id"] == choice.get("thread_id") for r in batch):
            old_id = choice["thread_id"]
            break
    if old_id is None:
        return
    if not vault.has_dek() or vault.epoch() != job_epoch:
        return
    card = _read_encrypted_json(_record_dir(old_id) / "card.enc")
    with db() as conn:
        old = conn.execute("SELECT * FROM assistant_records WHERE id=? AND kind='later' AND input_mode='auto'", (old_id,)).fetchone()
        linked = conn.execute("SELECT 1 FROM assistant_thread_sources WHERE record_id=?", (old_id,)).fetchone()
        if not old or linked:
            return
        conn.execute("UPDATE assistant_thread_sources SET sequence=sequence+1 WHERE thread_id=?", (thread_id,))
        conn.execute("INSERT INTO assistant_thread_sources(thread_id,record_id,sequence,change_type,change_reason,received_at,created_at) VALUES(?,?,1,'update','先前补充信息关联到事项',?,?)",
                     (thread_id, old_id, old["created_at"], now_iso()))
        conn.execute("UPDATE assistant_records SET kind='notice',updated_at=? WHERE id=?", (now_iso(), old_id))
    facts_path = _thread_dir(thread_id) / "facts.enc"
    facts = _read_encrypted_json(facts_path)
    supplement = card.get("summary") or card.get("brief") or ""
    if supplement and supplement not in (facts.get("summary") or ""):
        facts["summary"] = (facts.get("summary") or "") + "\n" + supplement
    vault.write_json(facts_path, facts)


def process_record_job(record_id: int) -> None:
    lock = _job_lock(record_id)
    if not lock.acquire(blocking=False):
        return
    try:
        _process_record_job(record_id)
    finally:
        lock.release()


def _process_record_job(record_id: int) -> None:
    """处理单个助手记录的后台作业。具备 DEK Epoch 校验和防上锁机制。"""
    if not vault.has_dek():
        with db() as conn:
            conn.execute(
                "UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=(SELECT MAX(id) FROM assistant_jobs WHERE record_id=?)",
                (now_iso(), record_id),
            )
        return

    current_epoch = vault.epoch()
    with db() as conn:
        job = conn.execute(
            "SELECT * FROM assistant_jobs WHERE record_id=? ORDER BY id DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        rec = conn.execute(
            "SELECT * FROM assistant_records WHERE id=?",
            (record_id,),
        ).fetchone()

    if not job or not rec:
        return

    # 幂等保护：如果已经完成处理，跳过重复执行（由 retry 接口触发的新 job 除外）
    if rec["status"] == "ready" and job["stage"] == "finalize":
        return

    # 上锁防御：如果当前世代号不匹配发起时的世代号，中断并置为 paused_locked
    if job["dek_epoch"] != current_epoch:
        with db() as conn:
            conn.execute(
                "UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?",
                (now_iso(), job["id"]),
            )
        return

    now = now_iso()
    with db() as conn:
        conn.execute("UPDATE assistant_records SET status='processing', updated_at=? WHERE id=?", (now, record_id))
        conn.execute("UPDATE assistant_jobs SET stage='parsing', updated_at=? WHERE id=?", (now, job["id"]))

    rec_dir = _record_dir(record_id)
    raw_path = rec_dir / "raw.enc"
    raw_text = ""
    if raw_path.exists():
        try:
            raw_text = vault.read_text(raw_path)
        except Exception:
            raw_text = ""

    # 附件识别阶段的结果单独加密缓存，重试时不重复调用视觉模型。
    images: list[tuple[bytes, str]] = []

    # 先分流再抽取：显式模式直接用用户选择，auto 模式交给模型判定。
    # 分流失败也要落成 failed 并保留原文，不能把异常抛给后台任务。
    try:
        cache_path = rec_dir / "attachment_text.enc"
        cache = _read_encrypted_json(cache_path) if cache_path.exists() else {}
        for attachment in _get_record_attachments(record_id):
            name = attachment["original_name"]
            asset = rec_dir / "assets" / attachment["filename"]
            extracted_text = cache.get(attachment["filename"])
            if not isinstance(extracted_text, str) or not extracted_text:
                try:
                    content = vault.read_bytes(asset)
                except Exception as exc:
                    raise ValueError(f"附件「{name}」读取失败，附件已保存，请重试。") from exc
                extracted_text = attachment_agent.convert(name, content, _extract_text_from_file_bytes)
                if not vault.has_dek() or vault.epoch() != job["dek_epoch"]:
                    raise ValueError("数据已锁定，请解锁后重试。")
                cache[attachment["filename"]] = extracted_text
                vault.write_json(cache_path, cache)
            if extracted_text not in raw_text:
                raw_text = (raw_text + "\n\n" + extracted_text).strip()
        if len(raw_text) > MAX_TEXT:
            raise ValueError("附件提取后的文字过长，请拆分后重新上传。附件已保存。")
        if not vault.has_dek() or vault.epoch() != job["dek_epoch"]:
            raise ValueError("数据已锁定，请解锁后重试。")
        vault.write_text(raw_path, raw_text)
        mode = str(rec["input_mode"] or "auto") if "input_mode" in rec.keys() else "auto"
        candidate_hint = None
        if mode in KINDS:
            kind = mode
        else:
            kind, candidate_hint = _classify_record_kind(rec, raw_text, images)
            # 分流本身也是一次模型调用，回来必须重新核对上锁状态，防止迟到写入。
            if not vault.has_dek() or vault.epoch() != job["dek_epoch"]:
                with db() as conn:
                    conn.execute(
                        "UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?",
                        (now_iso(), job["id"]),
                    )
                return
            with db() as conn:
                conn.execute(
                    "UPDATE assistant_records SET kind=?, updated_at=? WHERE id=?",
                    (kind, now_iso(), record_id),
                )

        if kind == "notice":
            _handle_notice_pipeline(record_id, rec, raw_text, images, job, candidate_hint=candidate_hint)
        else:
            _handle_later_pipeline(record_id, rec, raw_text, images, job)
    except Exception as e:
        now = now_iso()
        with db() as conn:
            conn.execute("UPDATE assistant_records SET status='failed', updated_at=? WHERE id=?", (now, record_id))
            conn.execute(
                "UPDATE assistant_jobs SET stage='failed', error_msg=?, updated_at=? WHERE id=?",
                (str(e)[:500], now, job["id"]),
            )


def _handle_unified_record_pipeline(
    record_id: int,
    rec: Any,
    raw_text: str,
    images: list[tuple[bytes, str]],
    job: Any,
    kind_hint: str | None = None,
    candidate_hint: int | None = None,
) -> None:
    """统一卡片流水线：结构化提取 -> 智能识别 DDL/待办 -> 事项线程研判与日程同步 -> 保存加密卡片与事实。

    kind_hint 由分流器给出：notice 用 NOTICE_PROMPT、later 用 LATER_PROMPT；
    为空时沿用历史的统一抽取提示词（兼容旧记录）。
    """
    job_epoch = job["dek_epoch"]
    extracted = None

    extracted = assistant_ai.extract_record(raw_text, rec['source_url'], rec['user_note'], images, kind_hint)

    if not extracted or not isinstance(extracted, dict) or not extracted.get("title"):
        raise llm.AiUnavailable("模型未能输出有效的结构化卡片（缺少 title）")

    # 3. 校验上锁
    if not vault.has_dek() or vault.epoch() != job_epoch:
        with db() as conn:
            conn.execute("UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?", (now_iso(), job["id"]))
        return

    title = str(extracted.get("title") or "未命名记录").strip()[:MAX_TITLE]
    summary = str(extracted.get("summary") or extracted.get("brief") or "").strip()
    source_summary = summary
    highlights = extracted.get("highlights") or []
    if isinstance(highlights, str):
        highlights = [highlights]
    why_focus = str(rec["user_note"] or extracted.get("why_focus") or "").strip()
    category = str(extracted.get("category") or "其他").strip()
    tags = extracted.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if category == "论文" and "论文" not in tags:
        tags.append("论文")
    deadline_date = str(extracted.get("deadline_date") or "").strip()
    deadline_time = str(extracted.get("deadline_time") or "").strip()
    try:
        if deadline_date:
            datetime.strptime(deadline_date, "%Y-%m-%d")
        if deadline_time:
            datetime.strptime(deadline_time, "%H:%M")
    except ValueError:
        # 不能把不完整或无效的时间写入日程。
        deadline_date, deadline_time = "", ""
    keywords = extracted.get("event_keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]

    # 分类型补齐：NOTICE_PROMPT 不产出分类/标签，LATER_PROMPT 不产出截止与要点。
    if kind_hint == "notice":
        if not tags:
            tags = [category] + [str(k) for k in keywords[:3] if str(k) != category]
        if not why_focus:
            why_focus = "待办事项，需要处理"
    elif kind_hint == "later":
        # 稍后看只做知识归档：不保留任何截止信号，避免误建日程或在卡片上提示待办。
        deadline_date, deadline_time = "", ""
        if not why_focus:
            why_focus = "留存稍后研读"

    primary_quote = str(extracted.get("quote") or "").strip()
    evidence_quotes = extracted.get("evidence_quotes") or []
    if isinstance(evidence_quotes, str):
        evidence_quotes = [evidence_quotes]

    # 若大模型未输出 quote，启发式从原文中提取精准依据句子（稍后看不做行动依据提取）
    if not primary_quote and kind_hint != "later":
        p_q, ev_q = _extract_quote_and_evidence(raw_text, deadline_date, deadline_time)
        primary_quote = p_q
        if not evidence_quotes:
            evidence_quotes = ev_q

    # 4. 线程匹配（Reconciliation Engine）：稍后看不参与通知事项聚合，避免资料被并进待办线程。
    matched_thread = None
    active_threads = []
    possible_matches = []
    source_text_by_thread: dict[int, list[str]] = {}
    if kind_hint != "later":
        with db() as conn:
            active_threads = conn.execute(
                "SELECT DISTINCT t.* FROM assistant_threads t "
                "JOIN assistant_thread_sources s ON s.thread_id=t.id "
                "JOIN assistant_records r ON r.id=s.record_id "
                "WHERE t.status != 'archived' AND r.kind='notice' ORDER BY t.updated_at DESC"
            ).fetchall()
            source_rows = conn.execute("SELECT ts.thread_id,ts.record_id FROM assistant_thread_sources ts JOIN assistant_threads t ON t.id=ts.thread_id WHERE t.status!='archived' ORDER BY ts.sequence DESC").fetchall()
            excluded = {r[0] for r in conn.execute("SELECT CASE WHEN record_a=? THEN record_b ELSE record_a END FROM assistant_separate_sources WHERE record_a=? OR record_b=?", (record_id, record_id, record_id))}
        excluded_threads = {r["thread_id"] for r in source_rows if r["record_id"] in excluded}
        active_threads = [t for t in active_threads if t["id"] not in excluded_threads]
        for source in source_rows:
            snippets = source_text_by_thread.setdefault(source["thread_id"], [])
            try:
                snippets.append(vault.read_text(_record_dir(source["record_id"]) / "raw.enc")[:5000])
            except Exception:
                continue

    # 所有活跃候选均交给模型，代码只负责分批与验证返回的 ID。
    if candidate_hint is not None:
        matched_thread = next((t for t in active_threads if t["id"] == candidate_hint), None)
    if not matched_thread and active_threads and llm.is_enabled():
        for start in range(0, len(active_threads), 25):
            eligible = active_threads[start:start + 25]
            candidates = [{"id": t["id"], "title": t["title"], "summary": t["summary"],
                           "deadline": t["deadline_date"],
                           "sources": source_text_by_thread.get(t["id"], [])[:2]} for t in eligible]
            try:
                choice = _choose_candidate(candidates,
                    f"{json.dumps(extracted, ensure_ascii=False)}\n原文：{raw_text[:12000]}", images)
                if choice.get("same_event") is True:
                    matched_thread = next((t for t in eligible if t["id"] == choice.get("thread_id")), None)
                possible_id = choice.get("possible_thread_id")
                if any(t["id"] == possible_id for t in eligible):
                    possible_matches.append((possible_id, "模型发现可能关联，请核对原文"))
                if matched_thread:
                    break
            except llm.AiUnavailable:
                break

    now = now_iso()
    thread_id = None
    change_type = "new"
    change_reason = "初始通知"

    def _evaluate_candidate(candidate: Any) -> dict | None:
        candidate_id = candidate["id"]
        previous = _read_encrypted_json(_thread_dir(candidate_id) / "facts.enc")
        excerpts = source_text_by_thread.get(candidate_id, [])[:5]
        try:
            result = assistant_ai.reconcile(candidate, previous, excerpts, extracted, raw_text)
            # 模型若主动输出相反判断，不忽略该信号，也不提交合并。
            return None if result.get("is_same_event") is False else result
        except llm.AiUnavailable:
            return None

    reconciled = None
    if matched_thread:
        thread_id = matched_thread["id"]
        reconciled = _evaluate_candidate(matched_thread)
        if not isinstance(reconciled, dict):
            # 整理失败时不得写入合并结果。
            matched_thread = None

    # 关键修复：二次大模型调用后必须再次检查上锁状态与代次，防止期间锁屏脏写
    if not vault.has_dek() or vault.epoch() != job_epoch:
        with db() as conn:
            conn.execute("UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?", (now_iso(), job["id"]))
        return

    if matched_thread:
        change_type = reconciled.get("change_type", "update")
        if change_type not in ("new", "update", "postpone", "cancel", "conflict"):
            change_type = "update"
        change_reason = reconciled.get("change_reason", "更新通知内容")
        summary = reconciled.get("summary") or summary
        highlights = reconciled.get("highlights") or highlights
        new_ddl_date = reconciled.get("deadline_date") or deadline_date
        new_ddl_time = reconciled.get("deadline_time") or deadline_time

        old_date = matched_thread["deadline_date"] or ""
        separate_tasks = reconciled.get("deadline_relation") == "different_task"
        unverified_deadline = False
        if old_date and new_ddl_date and new_ddl_date != old_date and not separate_tasks:
            change_quote = str(reconciled.get("deadline_change_quote") or "").strip()
            if change_type == "conflict" or not change_quote or change_quote not in raw_text:
                unverified_deadline = True
                change_reason = "新通知日期与已有截止日期不一致，缺少明确变更依据，请核对原文。"
                new_ddl_date = old_date
                new_ddl_time = matched_thread["deadline_time"] or ""

        has_conflict = 1 if (change_type == "conflict" or unverified_deadline or matched_thread["has_conflict"]) else 0
        structured_tasks = bool(extracted.get("tasks")) or bool(_read_encrypted_json(_thread_dir(thread_id) / "facts.enc").get("tasks"))

        # 更新线程与持久化加密事实
        with db() as conn:
            # 检查是否有日程锁定或已主动移除
            sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND task_id IS NULL AND schedule_id IS NOT NULL", (thread_id,)
            ).fetchone()
            dismissed_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND task_id IS NULL AND user_dismissed=1", (thread_id,)
            ).fetchone()

            eff_ddl_date = new_ddl_date
            eff_ddl_time = new_ddl_time
            if sched_link and sched_link["locked_by_user"]:
                # 用户锁定了日程，不静默覆盖
                change_reason = f"{change_reason}（检测到新时间，因用户手动锁定日程未覆盖）"
                sched_entry = conn.execute(
                    "SELECT date, time_start FROM schedule WHERE id=?", (sched_link["schedule_id"],)
                ).fetchone()
                if sched_entry:
                    eff_ddl_date = sched_entry["date"]
                    eff_ddl_time = sched_entry["time_start"]
                else:
                    eff_ddl_date = matched_thread["deadline_date"]
                    eff_ddl_time = matched_thread["deadline_time"]

            # 数据库仅保存受控短摘要，详细敏感事实一律走 facts.enc 加密
            short_summary = summary[:80]
            conn.execute(
                "UPDATE assistant_threads SET summary=?, highlights='[]', latest_change=?, "
                "deadline_date=?, deadline_time=?, has_conflict=?, updated_at=? WHERE id=?",
                (short_summary, change_reason, eff_ddl_date, eff_ddl_time, has_conflict, now, thread_id),
            )

            # 序列号
            max_seq = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS m FROM assistant_thread_sources WHERE thread_id=?",
                (thread_id,),
            ).fetchone()["m"]

            conn.execute(
                "INSERT INTO assistant_thread_sources(thread_id, record_id, sequence, change_type, change_reason, received_at, created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (thread_id, record_id, max_seq + 1, change_type, change_reason, rec["created_at"], now),
            )

            # 同步日程表 schedule（仅 DDL 项，防污染；若用户已主动删除过该条目，则绝对不重新生成）
            if not structured_tasks and sched_link and not sched_link["locked_by_user"] and not sched_link["user_dismissed"]:
                if eff_ddl_date:
                    sched_title = f"【截止】{matched_thread['title']}"
                    conn.execute(
                        "UPDATE schedule SET date=?, time_start=?, title=?, note=? WHERE id=?",
                        (eff_ddl_date, eff_ddl_time, sched_title, "详见助手通知事项", sched_link["schedule_id"]),
                    )
            elif not structured_tasks and not sched_link and not dismissed_link and eff_ddl_date:
                # 只有当用户没有显式删除过此事项日程时，新通知才创建 DDL
                sched_title = f"【截止】{matched_thread['title']}"
                cur_s = conn.execute(
                    "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at) "
                    "VALUES(?,?,?,?,?,?,0,0,?)",
                    (eff_ddl_date, "daily", "ddl", sched_title, eff_ddl_time, "详见助手通知事项", now),
                )
                conn.execute(
                    "INSERT INTO assistant_schedule_links(thread_id, record_id, schedule_id, role, locked_by_user, user_dismissed, created_at) "
                    "VALUES(?,?,?,?,0,0,?)",
                    (thread_id, record_id, cur_s.lastrowid, "ddl", now),
                )

        # 详细敏感事实写入加密 facts.enc
        t_dir = _thread_dir(thread_id)
        t_dir.mkdir(parents=True, exist_ok=True)
        th_title = matched_thread["title"] if "title" in matched_thread.keys() and matched_thread["title"] else title
        vault.write_json(t_dir / "facts.enc", {
            "thread_id": thread_id,
            "title": th_title,
            "summary": summary,
            "highlights": highlights,
            "latest_change": change_reason,
            "deadline_date": eff_ddl_date,
            "deadline_time": eff_ddl_time,
            "quote": primary_quote,
            "evidence_quotes": evidence_quotes,
            "latest_record_id": record_id,
            "updated_at": now,
        })
    elif kind_hint != "later":
        # 新建独立通知线程；稍后看资料保持独立记录。
        with db() as conn:
            short_summary = summary[:80]
            cur_t = conn.execute(
                "INSERT INTO assistant_threads(title, summary, highlights, latest_change, deadline_date, deadline_time, has_conflict, status, created_at, updated_at) "
                "VALUES(?,?,'[]',?,?,?,0, 'active', ?, ?)",
                (title, short_summary, "初始通知导入", deadline_date, deadline_time, now, now),
            )
            thread_id = int(cur_t.lastrowid)

            for possible_id, reason in possible_matches:
                conn.execute("INSERT OR IGNORE INTO assistant_match_suggestions(thread_id,candidate_thread_id,reason,created_at) VALUES(?,?,?,?)", (thread_id, possible_id, reason, now))

            conn.execute(
                "INSERT INTO assistant_thread_sources(thread_id, record_id, sequence, change_type, change_reason, received_at, created_at) "
                "VALUES(?,?,1,'new','初始创建',?,?)",
                (thread_id, record_id, rec["created_at"], now),
            )

            # 建立日程映射（唯一 DDL 原则：绝不额外创建同名 task）
            if deadline_date and not extracted.get("tasks"):
                sched_title = f"【截止】{title}"
                cur_s = conn.execute(
                    "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at) "
                    "VALUES(?,?,?,?,?,?,0,0,?)",
                    (deadline_date, "daily", "ddl", sched_title, deadline_time, "详见助手通知事项", now),
                )
                conn.execute(
                    "INSERT INTO assistant_schedule_links(thread_id, record_id, schedule_id, role, locked_by_user, user_dismissed, created_at) "
                    "VALUES(?,?,?,?,0,0,?)",
                    (thread_id, record_id, cur_s.lastrowid, "ddl", now),
                )

        # 详细敏感事实写入加密 facts.enc
        t_dir = _thread_dir(thread_id)
        t_dir.mkdir(parents=True, exist_ok=True)
        vault.write_json(t_dir / "facts.enc", {
            "thread_id": thread_id,
            "title": title,
            "summary": summary,
            "highlights": highlights,
            "latest_change": "初始通知导入",
            "deadline_date": deadline_date,
            "deadline_time": deadline_time,
            "quote": primary_quote,
            "evidence_quotes": evidence_quotes,
            "latest_record_id": record_id,
            "updated_at": now,
        })

    # 任务按来源保存，避免一份滚动摘要覆盖旧通知中的要求。
    previous_card = _read_encrypted_json(_record_dir(record_id) / "card.enc")
    if kind_hint == "notice" and (previous_card.get("tasks_extracted") or previous_card.get("tasks")):
        # A retry must not replace stable task IDs or overwrite user edits.
        extracted_tasks = previous_card.get("tasks") or []
    else:
        extracted_tasks = _normalize_notice_tasks(extracted.get("tasks"), raw_text, record_id) if kind_hint == "notice" else []

    if thread_id and kind_hint == "notice":
        facts_path = _thread_dir(thread_id) / "facts.enc"
        facts = _read_encrypted_json(facts_path)
        # 读取旧来源自己的任务，不能依赖刚被更新的滚动摘要。
        with db() as conn:
            source_rows = conn.execute(
                "SELECT record_id FROM assistant_thread_sources WHERE thread_id=? AND record_id != ? ORDER BY sequence",
                (thread_id, record_id),
            ).fetchall()
        tasks = []
        for source in source_rows:
            old_card = _read_encrypted_json(_record_dir(source["record_id"]) / "card.enc")
            tasks.extend(old_card.get("tasks") or [])
        tasks.extend(extracted_tasks)
        facts["tasks"] = _combine_source_tasks(tasks)
        vault.write_json(facts_path, facts)
        _sync_task_schedules(thread_id, facts["tasks"])

    # 5. 持久化统一加密卡片 card.enc
    rec_dir = _record_dir(record_id)
    card_data = {
        "title": title,
        "summary": summary,
        "source_summary": source_summary,
        "brief": summary,
        "highlights": highlights,
        "why_focus": why_focus or "留存查阅与处理",
        "category": category,
        "tags": tags,
        "deadline_date": deadline_date,
        "deadline_time": deadline_time,
        "quote": primary_quote,
        "evidence_quotes": evidence_quotes,
        "change_type": change_type,
        "change_reason": change_reason,
        "thread_id": thread_id,
        "tasks": extracted_tasks,
        "tasks_extracted": kind_hint == "notice" and (bool(previous_card.get("tasks_extracted")) or isinstance(extracted.get("tasks"), list)),
        "source_url": rec["source_url"],
        "user_note": rec["user_note"],
    }
    vault.write_json(rec_dir / "card.enc", card_data)

    if kind_hint == "notice" and thread_id:
        _attach_earlier_supplement(thread_id, record_id, raw_text, job_epoch)

    # 保留加密原文，以便重新整理及核对来源。

    # 分流结果为准：notice 不会因为没抽到 DDL 就掉回稍后看，later 也不会因为正文提到日期就变成待办。
    if kind_hint not in KINDS:
        raise ValueError("缺少模型分流结果")
    effective_kind = kind_hint

    with db() as conn:
        conn.execute(
            "UPDATE assistant_records SET status='ready', kind=?, title=?, category=?, tags=?, updated_at=? WHERE id=?",
            (effective_kind, title, category, json.dumps(tags, ensure_ascii=False), now, record_id),
        )
        conn.execute("UPDATE assistant_jobs SET stage='finalize', error_msg='', updated_at=? WHERE id=?", (now, job["id"]))


def _handle_notice_pipeline(record_id: int, rec: Any, raw_text: str,
                            images: list[tuple[bytes, str]], job: Any, candidate_hint: int | None = None) -> None:
    """通知流：按 NOTICE_PROMPT 抽取待办/DDL，进入事项线程研判与唯一日程同步。"""
    return _handle_unified_record_pipeline(
        record_id, rec, raw_text, images, job, kind_hint="notice", candidate_hint=candidate_hint,
    )


def _handle_later_pipeline(record_id: int, rec: Any, raw_text: str,
                           images: list[tuple[bytes, str]], job: Any) -> None:
    """稍后看流：按 LATER_PROMPT 生成知识卡片，不做事项聚合、不产出 DDL。"""
    return _handle_unified_record_pipeline(
        record_id, rec, raw_text, images, job, kind_hint="later",
    )


# ---------- API 端点 ----------

@router.post("/submit", status_code=201)
async def submit_item(
    request: Request,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current),
):
    """统一提交助手入口：支持 JSON 与 Multipart（文本、截图文件、附件、模式选择、备注）。"""
    _require_dek()
    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD_BYTES + MAX_UPLOAD_BYTES // 2 + 1024 * 1024:
        raise HTTPException(413, "请求内容超过大小限制")

    # Bound the actual body even when Content-Length is missing or inaccurate.
    max_request_bytes = MAX_UPLOAD_BYTES + MAX_UPLOAD_BYTES // 2 + 1024 * 1024
    original_receive = request._receive
    received_bytes = 0

    async def limited_receive():
        nonlocal received_bytes
        message = await original_receive()
        if message.get("type") == "http.request":
            received_bytes += len(message.get("body", b""))
            if received_bytes > max_request_bytes:
                raise HTTPException(413, "请求内容超过大小限制")
        return message

    request._receive = limited_receive

    text = ""
    mode = "auto"
    source_type = "text"
    source_url = ""
    user_note = ""
    capture_id = None
    uploaded_files: list[tuple[str, bytes]] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        text = str(form.get("text") or "")
        mode = str(form.get("mode") or "auto")
        source_type = str(form.get("source_type") or "text")
        source_url = str(form.get("source_url") or "")
        user_note = str(form.get("user_note") or "")
        cid_val = form.get("capture_id")
        if cid_val is not None and str(cid_val).isdigit():
            capture_id = int(cid_val)

        # 稳健接收多文件（无论 Starlette 或任何表单结构）
        for key, val in form.multi_items():
            fn = getattr(val, "filename", None)
            if fn:
                read_fn = getattr(val, "read", None)
                if callable(read_fn):
                    chunks = []
                    size = 0
                    while True:
                        chunk = await val.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_FILE_BYTES or sum(len(b) for _, b in uploaded_files) + size > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, "附件超过大小限制")
                        chunks.append(chunk)
                    if size:
                        uploaded_files.append((fn, b"".join(chunks)))
    else:
        try:
            body = await request.json()
        except HTTPException:
            raise
        except Exception:
            body = {}
        text = str(body.get("text") or "")
        mode = str(body.get("mode") or "auto")
        source_type = str(body.get("source_type") or "text")
        source_url = str(body.get("source_url") or "")
        user_note = str(body.get("user_note") or "")
        capture_id = body.get("capture_id")

        # 兼容 JSON 方式传递的 base64 截图
        img_b64 = body.get("image_base64") or body.get("image_preview")
        if img_b64 and "," in str(img_b64):
            import base64
            try:
                b64_data = str(img_b64).split(",", 1)[1]
                if len(b64_data) > ((MAX_FILE_BYTES + 2) // 3) * 4:
                    raise HTTPException(413, "附件超过大小限制")
                img_bytes = base64.b64decode(b64_data)
                if len(img_bytes) > MAX_FILE_BYTES:
                    raise HTTPException(413, "附件超过大小限制")
                uploaded_files.append(("screenshot.png", img_bytes))
            except HTTPException:
                raise
            except Exception:
                pass

    # 纯截图/纯附件也是合法输入
    if not text.strip() and not uploaded_files and not source_url.strip():
        raise HTTPException(400, "提交内容不能为空（文字、链接或文件至少包含一项）")

    if len(text) > MAX_TEXT:
        raise HTTPException(400, f"文本内容最长 {MAX_TEXT} 字符")

    if mode not in MODES:
        mode = "auto"

    kind = mode
    if kind == "auto":
        # 占位分栏：提交接口不阻塞在模型调用上，后台作业按 CLASSIFY_PROMPT 判定后立即改写。
        kind = "later"

    if uploaded_files and source_type == "text":
        is_all_imgs = all(
            Path(fn).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif")
            for fn, _ in uploaded_files
        )
        source_type = "image" if is_all_imgs else "file"

    now = now_iso()
    # 提取首行作为初始标题，没有文本时用文件名或用户备注
    if text.strip():
        initial_title = text.strip().splitlines()[0][:MAX_TITLE]
    elif user_note.strip():
        initial_title = user_note.strip()[:MAX_TITLE]
    elif uploaded_files:
        initial_title = uploaded_files[0][0][:MAX_TITLE]
    elif source_url.strip():
        initial_title = source_url.strip()[:MAX_TITLE]
    else:
        initial_title = "新记录"

    with db() as conn:
        cur = conn.execute(
            "INSERT INTO assistant_records(capture_id, kind, input_mode, title, source_type, source_url, user_note, category, tags, status, read_state, archived, pinned, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'[]','pending','unread',0,0,?,?)",
            (capture_id, kind, mode, initial_title, source_type, source_url, user_note, "事务" if kind == "notice" else "其他", now, now),
        )
        record_id = int(cur.lastrowid)

        # 创建后台作业记录
        cur_job = conn.execute(
            "INSERT INTO assistant_jobs(record_id, stage, retry_count, dek_epoch, error_msg, created_at, updated_at) "
            "VALUES(?, 'pending', 0, ?, '', ?, ?)",
            (record_id, vault.epoch(), now, now),
        )
        job_id = int(cur_job.lastrowid)

    # 保存原始正文及附件（Vault 加密）
    rec_dir = _record_dir(record_id)
    rec_dir.mkdir(parents=True, exist_ok=True)
    vault.write_text(rec_dir / "raw.enc", text)

    if uploaded_files:
        assets_dir = rec_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        attachments_meta = []
        for fn, b_content in uploaded_files:
            ext = Path(fn).suffix.lower()
            safe_fn = f"{uuid.uuid4().hex[:12]}{ext}"
            vault.write_bytes(assets_dir / safe_fn, b_content)
            attachments_meta.append({
                "filename": safe_fn,
                "original_name": fn,
                "size": len(b_content),
                "is_image": ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"),
                "mime": mimetypes.guess_type(fn)[0] or "application/octet-stream",
            })
        try:
            vault.write_json(rec_dir / "attachments_meta.enc", attachments_meta)
        except Exception:
            pass

    # 调度后台整理
    background_tasks.add_task(process_record_job, record_id)

    return {
        "id": record_id,
        "kind": kind,
        "title": initial_title,
        "status": "pending",
        "job_id": job_id,
        "created_at": now,
    }


def auto_archive_stale_threads(days: int = 180) -> int:
    """自动将创建超过 days 天、最后更新超过 days 天且当前无未完成未来 DDL 的活跃事项标记为 status='archived'。"""
    now_dt = datetime.now()
    cutoff_dt = now_dt - timedelta(days=days)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now_dt.strftime("%Y-%m-%d")
    now = now_iso()

    archived_count = 0
    with db() as conn:
        candidates = conn.execute(
            """
            SELECT id, title, deadline_date, deadline_time, status, created_at, updated_at
            FROM assistant_threads
            WHERE status = 'active'
              AND created_at <= ?
              AND updated_at <= ?
            """,
            (cutoff_str, cutoff_str),
        ).fetchall()

        for t in candidates:
            tid = t["id"]
            has_future_ddl = False
            if t["deadline_date"] and t["deadline_date"] >= today_str:
                sched = conn.execute(
                    """
                    SELECT s.done FROM assistant_schedule_links sl
                    JOIN schedule s ON sl.schedule_id = s.id
                    WHERE sl.thread_id = ?
                    """,
                    (tid,),
                ).fetchone()
                if sched is None or not sched["done"]:
                    has_future_ddl = True

            if has_future_ddl:
                continue

            conn.execute(
                "UPDATE assistant_threads SET status='archived', updated_at=? WHERE id=?",
                (now, tid),
            )
            conn.execute(
                """
                UPDATE assistant_records
                SET archived=1, updated_at=?
                WHERE id IN (SELECT record_id FROM assistant_thread_sources WHERE thread_id=?)
                """,
                (now, tid),
            )
            archived_count += 1

    if archived_count > 0:
        logger.info("auto_archive_stale_threads: 自动归档了 %d 个超过 %d 天的过期活跃事项", archived_count, days)
    return archived_count


@router.get("/records")
def list_records(
    scope: str = "all",
    q: str = "",
    category: str = "",
    read_state: str = "",
    offset: int = 0,
    limit: int = 50,
    _user: dict = Depends(get_current),
):
    """查询记录列表：轻量元数据，不解密正文長文本。"""
    try:
        auto_archive_stale_threads(180)
    except Exception as e:
        logger.warning("auto_archive_stale_threads failed during list_records: %s", e)

    if scope not in SCOPES:
        raise HTTPException(400, f"scope 必须是 {SCOPES} 之一")

    clauses: list[str] = []
    args: list[Any] = []

    if scope == "archived":
        clauses.append("r.archived = 1")
    else:
        clauses.append("r.archived = 0")
        if scope == "notice":
            clauses.append("r.kind = 'notice'")
        elif scope == "later":
            clauses.append("r.kind = 'later'")
        elif scope == "alerts":
            clauses.append("(t.has_conflict = 1 OR (t.deadline_date != '' AND t.status = 'active'))")

    if category:
        clauses.append("r.category = ?")
        args.append(category)

    if read_state:
        clauses.append("r.read_state = ?")
        args.append(read_state)

    if q.strip():
        clauses.append("(r.title LIKE ? OR r.user_note LIKE ? OR r.tags LIKE ? OR r.source_url LIKE ?)")
        like_p = f"%{q.strip()}%"
        args.extend([like_p, like_p, like_p, like_p])

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    # 每个通知线程只展示最新来源作为入口，原始通知仍可在详情时间线中逐条查看。
    # 稍后看保持独立记录，前端按分类分组，不把不同论文/项目合成同一条资料。
    grouped_sql = f"""
        SELECT r.*,
               wb.title AS wb_item_title,
               t.id AS thread_id, t.title AS thread_title, t.summary AS thread_summary, t.status AS thread_status,
               t.deadline_date, t.deadline_time, t.has_conflict,
               (SELECT COUNT(*) FROM assistant_thread_sources count_ts WHERE count_ts.thread_id=t.id) AS source_count,
               ROW_NUMBER() OVER (
                   PARTITION BY CASE WHEN r.kind='notice' AND t.id IS NOT NULL
                       THEN 'thread:' || t.id ELSE 'record:' || r.id END
                   ORDER BY r.created_at DESC, r.id DESC
               ) AS card_rank,
               (SELECT j.error_msg FROM assistant_jobs j WHERE j.record_id = r.id ORDER BY j.id DESC LIMIT 1) AS error_msg
        FROM assistant_records r
        LEFT JOIN workbench_items wb ON wb.id = r.wb_item_id
        LEFT JOIN assistant_thread_sources ts ON ts.record_id = r.id AND r.kind = 'notice'
        LEFT JOIN assistant_threads t ON ts.thread_id = t.id
        {where_sql}
    """
    query_sql = f"SELECT * FROM ({grouped_sql}) WHERE card_rank=1 ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ? OFFSET ?"
    count_sql = f"SELECT COUNT(*) AS cnt FROM ({grouped_sql}) WHERE card_rank=1"

    with db() as conn:
        total = conn.execute(count_sql, args).fetchone()["cnt"]
        rows = conn.execute(query_sql, args + [limit, offset]).fetchall()

    items = []
    for r in rows:
        tags = []
        try:
            tags = json.loads(r["tags"] or "[]")
        except Exception:
            pass

        item = {
            "id": r["id"],
            "capture_id": r["capture_id"],
            "wb_item_id": r["wb_item_id"] if "wb_item_id" in r.keys() else None,
            "wb_item_title": (r["wb_item_title"] or "") if "wb_item_title" in r.keys() else "",
            "kind": r["kind"],
            "title": (r["thread_title"] or r["title"]) if r["thread_id"] else r["title"],
            "source_type": r["source_type"],
            "source_url": r["source_url"],
            "user_note": r["user_note"],
            "category": r["category"],
            "tags": tags,
            "status": r["status"],
            "error_msg": r["error_msg"] if "error_msg" in r.keys() and r["error_msg"] else "",
            "read_state": r["read_state"],
            "archived": bool(r["archived"]),
            "pinned": bool(r["pinned"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "summary": "",
            "reason": r["user_note"] or "",
            "deadline_date": "",
            "deadline_time": "",
            "latest_change": "",
            "highlights": [],
            "has_conflict": False,
        }

        # 读取统一卡片密文获取摘要、关注理由、要点与截止时间
        card_p = _record_dir(int(r["id"])) / "card.enc"
        if card_p.exists() and vault.has_dek():
            try:
                c_data = vault.read_json(card_p)
                item["summary"] = c_data.get("summary") or c_data.get("brief") or ""
                item["reason"] = c_data.get("why_focus") or c_data.get("reason") or r["user_note"] or ""
                item["highlights"] = c_data.get("highlights") or []
                item["quote"] = c_data.get("quote") or ""
                item["evidence_quotes"] = c_data.get("evidence_quotes") or []
                if c_data.get("deadline_date"):
                    item["deadline_date"] = c_data["deadline_date"]
                if c_data.get("deadline_time"):
                    item["deadline_time"] = c_data["deadline_time"]
                if c_data.get("change_reason"):
                    item["latest_change"] = c_data["change_reason"]
            except Exception:
                pass

        if r["thread_id"]:
            tid = int(r["thread_id"])
            with db() as conn:
                suggestion_rows = conn.execute(
                    "SELECT s.candidate_thread_id AS id,t.title,s.reason FROM assistant_match_suggestions s "
                    "JOIN assistant_threads t ON t.id=s.candidate_thread_id "
                    "WHERE s.thread_id=? AND s.dismissed=0 AND t.status!='archived'", (tid,)
                ).fetchall()
                source_rows = conn.execute(
                    "SELECT r.id,r.title FROM assistant_thread_sources s JOIN assistant_records r ON r.id=s.record_id WHERE s.thread_id=? ORDER BY s.sequence", (tid,)
                ).fetchall()
                source_titles = [row["title"] for row in source_rows]
            source_deadlines = []
            for source_row in source_rows:
                source_card = _read_encrypted_json(_record_dir(source_row["id"]) / "card.enc")
                if source_card.get("deadline_date"):
                    source_deadlines.append({"record_id": source_row["id"], "title": source_row["title"],
                                             "date": source_card["deadline_date"], "time": source_card.get("deadline_time") or ""})
            th_summary = r["thread_summary"] or ""
            th_highlights = []
            th_tasks = []
            last_manual_merge_id = None
            th_change = r["latest_change"] if "latest_change" in r.keys() else ""

            # 解密 facts.enc 提取详细事实
            facts_p = _thread_dir(tid) / "facts.enc"
            if facts_p.exists() and vault.has_dek():
                try:
                    facts = vault.read_json(facts_p)
                    th_summary = facts.get("summary") or th_summary
                    th_highlights = facts.get("highlights") or []
                    th_tasks = facts.get("tasks") or []
                    last_manual_merge_id = facts.get("last_manual_merge_id")
                    th_change = facts.get("latest_change") or th_change
                except Exception:
                    pass

            item["summary"] = th_summary or item["summary"]
            item["highlights"] = th_highlights or item["highlights"]
            item["tasks"] = th_tasks
            item["latest_change"] = th_change or item["latest_change"]
            item["deadline_date"] = r["deadline_date"] or item["deadline_date"] or ""
            item["deadline_time"] = r["deadline_time"] or item["deadline_time"] or ""
            pending_deadlines = sorted((t for t in th_tasks if t.get("deadline_date") and not t.get("done") and t.get("kind") != "event"),
                                       key=lambda t: (t["deadline_date"], t.get("deadline_time") or ""))
            if pending_deadlines:
                item["deadline_date"] = pending_deadlines[0]["deadline_date"]
                item["deadline_time"] = pending_deadlines[0].get("deadline_time") or ""
            item["has_conflict"] = bool(r["has_conflict"])

            item["thread"] = {
                "id": tid,
                "title": r["thread_title"],
                "status": r["thread_status"],
                "source_count": r["source_count"],
                "source_titles": source_titles,
                "source_messages": _source_messages(source_rows),
                "source_deadlines": source_deadlines,
                "summary": th_summary,
                "highlights": th_highlights,
                "tasks": th_tasks,
                "last_manual_merge_id": last_manual_merge_id,
                "suggestions": [dict(row) for row in suggestion_rows],
                "latest_change": th_change,
                "deadline_date": r["deadline_date"] or "",
                "deadline_time": r["deadline_time"] or "",
                "has_conflict": bool(r["has_conflict"]),
            }

        # 统计或简要提取附件与核心引用依据
        rec_id_int = int(r["id"])
        atts = _get_record_attachments(rec_id_int)
        item["attachments_count"] = len(atts)
        item["attachments"] = atts

        if not item.get("quote") and r["thread_id"]:
            facts_p = _thread_dir(int(r["thread_id"])) / "facts.enc"
            if facts_p.exists() and vault.has_dek():
                try:
                    facts = vault.read_json(facts_p)
                    item["quote"] = facts.get("quote") or ""
                    item["evidence_quotes"] = facts.get("evidence_quotes") or []
                except Exception:
                    pass

        items.append(item)

    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/records/{record_id}")
def get_record(record_id: int, _user: dict = Depends(get_current)):
    """获取单条记录详情：解密并返回原始文本、附件清单与提取事实依据卡片。"""
    _require_dek()
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        # 查找关联线程
        ts_row = conn.execute(
            "SELECT thread_id FROM assistant_thread_sources WHERE record_id=?", (record_id,)
        ).fetchone() if r["kind"] == "notice" else None
        thread_info = None
        schedules_info = []
        if ts_row:
            tid = ts_row["thread_id"]
            t_row = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (tid,)).fetchone()
            if t_row:
                thread_info = dict(t_row)
                facts_p = _thread_dir(tid) / "facts.enc"
                if facts_p.exists() and vault.has_dek():
                    try:
                        facts = vault.read_json(facts_p)
                        thread_info["summary"] = facts.get("summary") or thread_info["summary"]
                        thread_info["highlights"] = facts.get("highlights") or []
                        thread_info["tasks"] = facts.get("tasks") or []
                        thread_info["last_manual_merge_id"] = facts.get("last_manual_merge_id")
                        thread_info["latest_change"] = facts.get("latest_change") or thread_info.get("latest_change", "")
                        thread_info["quote"] = facts.get("quote") or ""
                        thread_info["evidence_quotes"] = facts.get("evidence_quotes") or []
                    except Exception:
                        pass
                else:
                    try:
                        thread_info["highlights"] = json.loads(thread_info["highlights"] or "[]")
                    except Exception:
                        pass

                # 查询该线程的真实来源演进列表
                sources_rows = conn.execute(
                    "SELECT ts.*, r.title AS source_title, r.source_type, r.source_url "
                    "FROM assistant_thread_sources ts "
                    "JOIN assistant_records r ON ts.record_id = r.id "
                    "WHERE ts.thread_id=? ORDER BY ts.sequence ASC",
                    (tid,),
                ).fetchall()
                thread_info["sources"] = [dict(s) for s in sources_rows]

                # 关联日程
                sched_rows = conn.execute(
                    "SELECT sl.*, s.date, s.time_start, s.title, s.done FROM assistant_schedule_links sl "
                    "JOIN schedule s ON sl.schedule_id = s.id WHERE sl.thread_id=?",
                    (tid,),
                ).fetchall()
                schedules_info = [dict(s) for s in sched_rows]

        # 关联笔记/工作台
        links_rows = conn.execute(
            "SELECT target_type, target_id, created_at FROM assistant_links WHERE record_id=?",
            (record_id,),
        ).fetchall()
        links_info = [dict(l) for l in links_rows]

        wb_item_title = ""
        wb_id = r["wb_item_id"] if "wb_item_id" in r.keys() else None
        if wb_id:
            wb_row = conn.execute("SELECT title FROM workbench_items WHERE id=?", (wb_id,)).fetchone()
            if wb_row:
                wb_item_title = wb_row["title"]

    rec_dir = _record_dir(record_id)
    raw_text = ""
    if (rec_dir / "raw.enc").exists():
        try:
            raw_text = vault.read_text(rec_dir / "raw.enc")
        except Exception:
            pass

    card_data = {}
    if (rec_dir / "card.enc").exists():
        try:
            card_data = vault.read_json(rec_dir / "card.enc")
        except Exception:
            pass

    assets_list = []
    assets_dir = rec_dir / "assets"
    if assets_dir.is_dir():
        for p in assets_dir.glob("*"):
            assets_list.append(p.name)

    attachments = _get_record_attachments(record_id)
    quote = card_data.get("quote") or ""
    evidence_quotes = card_data.get("evidence_quotes") or []
    if not quote and thread_info:
        quote = thread_info.get("quote") or ""
    if not evidence_quotes and thread_info:
        evidence_quotes = thread_info.get("evidence_quotes") or []

    # 动态兜底：如果卡片未保存 quote 但存在原文，实时提取核心引用依据
    if not quote and raw_text:
        q_fallback, ev_fallback = _extract_quote_and_evidence(
            raw_text,
            ddl_date=card_data.get("deadline_date") or (thread_info.get("deadline_date") if thread_info else "") or "",
            ddl_time=card_data.get("deadline_time") or (thread_info.get("deadline_time") if thread_info else "") or "",
        )
        quote = q_fallback
        if not evidence_quotes:
            evidence_quotes = ev_fallback

    tags = []
    try:
        tags = json.loads(r["tags"] or "[]")
    except Exception:
        pass

    with db() as conn:
        job_row = conn.execute(
            "SELECT error_msg FROM assistant_jobs WHERE record_id=? ORDER BY id DESC LIMIT 1",
            (record_id,)
        ).fetchone()
        error_msg = job_row["error_msg"] if job_row and job_row["error_msg"] else ""

    return {
        "id": r["id"],
        "capture_id": r["capture_id"],
        "wb_item_id": wb_id,
        "wb_item_title": wb_item_title,
        "kind": r["kind"],
        "title": r["title"],
        "source_type": r["source_type"],
        "source_url": r["source_url"],
        "user_note": r["user_note"],
        "category": r["category"],
        "tags": tags,
        "status": r["status"],
        "error_msg": error_msg,
        "read_state": r["read_state"],
        "archived": bool(r["archived"]),
        "pinned": bool(r["pinned"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "raw_text": raw_text,
        "card": card_data,
        "thread": thread_info,
        "schedules": schedules_info,
        "links": links_info,
        "assets": assets_list,
        "attachments": attachments,
        "quote": quote,
        "evidence_quotes": evidence_quotes,
    }


def _source_summary_job(record_id: int, epoch: int) -> None:
    job = _source_summary_jobs[record_id]
    try:
        raw_path = _record_dir(record_id) / "raw.enc"
        try:
            raw = vault.read_text(raw_path)
        except Exception:
            raw = ""
        images = []
        for asset in (_record_dir(record_id) / "assets").glob("*"):
            if asset.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                try:
                    images.append((vault.read_bytes(asset), mimetypes.guess_type(asset.name)[0] or "image/png"))
                except Exception:
                    pass
        if not raw and not images:
            raise ValueError("这段信息的原文和图片不可用")
        result = assistant_ai.source_summary(raw, images)
        summary = str(result.get("summary") or "").strip()
        if not summary:
            raise ValueError("模型没有返回摘要")
        if not vault.has_dek() or vault.epoch() != epoch:
            job["status"] = "locked"
            return
        path = _record_dir(record_id) / "card.enc"
        card = _read_encrypted_json(path)
        if not card:
            raise ValueError("记录卡片不可用")
        card["source_summary"] = summary
        vault.write_json(path, card)
        job["status"] = "done"
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:200]


@router.post("/records/{record_id}/source-summary")
def refresh_source_summary(record_id: int, background_tasks: BackgroundTasks, _user: dict = Depends(get_current)):
    _require_dek()
    with db() as conn:
        if not conn.execute("SELECT 1 FROM assistant_records WHERE id=?", (record_id,)).fetchone():
            raise HTTPException(404, "记录不存在")
    if _source_summary_jobs.get(record_id, {}).get("status") != "running":
        _source_summary_jobs[record_id] = {"status": "running", "error": ""}
        background_tasks.add_task(_source_summary_job, record_id, vault.epoch())
    return {"ok": True}


@router.get("/records/{record_id}/source-summary")
def source_summary_status(record_id: int, _user: dict = Depends(get_current)):
    _require_dek()
    return _source_summary_jobs.get(record_id, {"status": "idle", "error": ""})


@router.get("/records/{record_id}/attachments")
def list_record_attachments(record_id: int, _user: dict = Depends(get_current)):
    """获取指定记录的全部附件清单，包含完整 URL 与元数据。"""
    _require_dek()
    with db() as conn:
        r = conn.execute("SELECT id FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")
    return {"attachments": _get_record_attachments(record_id)}


@router.get("/records/{record_id}/attachments/{filename}")
def get_record_attachment(
    record_id: int,
    filename: str,
    request: Request,
    download: bool = Query(False),
    token: str = Query(default=""),
    authorization: str = Header(default=""),
):
    """安全读取与下载助手附件接口：
    - 鉴权验证登录与所属权；
    - 严格进行路径白名单与防穿越校验（确保在 data/assistant/records/<id>/assets/<filename> 内）；
    - 读取文件字节并解密；
    - 根据后缀自适应返回正确的 MIME 类型（如 image/png, image/jpeg, application/pdf, text/plain 等）；
    - 支持浏览器直接内联预览（inline）或下载（attachment）。
    """
    _require_dek()
    _authenticate_user_for_attachment(authorization=authorization, token=token, request=request)

    # 1. 验证记录所属权与存在性
    with db() as conn:
        r = conn.execute("SELECT id FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

    # 2. 严格文件名校验与防穿越白名单
    clean_fn = filename.strip()
    if not clean_fn or clean_fn in (".", "..") or "/" in clean_fn or "\\" in clean_fn or "\0" in clean_fn:
        raise HTTPException(400, "非法文件名")

    if not re.match(r"^[\w\-. ]+$", clean_fn):
        raise HTTPException(400, "文件名包含非法字符")

    rec_dir = _record_dir(record_id).resolve()
    assets_dir = (rec_dir / "assets").resolve()
    target_path = (assets_dir / clean_fn).resolve()

    try:
        target_path.relative_to(assets_dir)
    except ValueError:
        raise HTTPException(403, "禁止跨目录访问附件")

    if not target_path.is_file():
        raise HTTPException(404, "附件不存在")

    # 3. 读取并解密文件字节
    try:
        data = vault.read_bytes(target_path)
    except Exception:
        try:
            data = target_path.read_bytes()
        except Exception as e:
            raise HTTPException(500, f"读取附件文件失败: {e}")

    # 4. 获取原始文件名与 MIME 类型
    meta_name = clean_fn
    meta_p = rec_dir / "attachments_meta.enc"
    if meta_p.exists() and vault.has_dek():
        try:
            meta_list = vault.read_json(meta_p)
            for m in meta_list:
                if m.get("filename") == clean_fn:
                    meta_name = m.get("original_name") or clean_fn
                    break
        except Exception:
            pass

    ext = target_path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
        ".csv": "text/csv; charset=utf-8",
        ".log": "text/plain; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".zip": "application/zip",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    media_type = mime_map.get(ext)
    if not media_type:
        guessed, _ = mimetypes.guess_type(meta_name)
        media_type = guessed or "application/octet-stream"

    # 5. Content-Disposition 响应头配置
    safe_inline = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".pdf", ".txt", ".md", ".json", ".csv", ".log"}
    disp_type = "inline" if not download and ext in safe_inline else "attachment"
    encoded_name = quote(meta_name)
    content_disp = f'{disp_type}; filename="{clean_fn}"; filename*=UTF-8\'\'{encoded_name}'

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disp,
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.patch("/records/{record_id}")
def update_record(record_id: int, body: RecordPatchIn, _user: dict = Depends(get_current)):
    """更新记录字段（read_state, archived, pinned, category, user_note, title, tags）。"""
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        sets = []
        args = []
        if body.read_state is not None:
            if body.read_state not in READ_STATES:
                raise HTTPException(400, f"read_state 必须是 {READ_STATES} 之一")
            sets.append("read_state = ?")
            args.append(body.read_state)

        if body.archived is not None:
            sets.append("archived = ?")
            args.append(1 if body.archived else 0)

        if body.pinned is not None:
            sets.append("pinned = ?")
            args.append(1 if body.pinned else 0)

        if body.category is not None:
            sets.append("category = ?")
            args.append(body.category.strip())

        if body.user_note is not None:
            sets.append("user_note = ?")
            args.append(body.user_note.strip())

        if body.title is not None:
            sets.append("title = ?")
            args.append(body.title.strip()[:MAX_TITLE])

        if body.tags is not None:
            sets.append("tags = ?")
            args.append(json.dumps(body.tags, ensure_ascii=False))

        if not sets:
            return {"ok": True, "id": record_id}

        now = now_iso()
        sets.append("updated_at = ?")
        args.append(now)
        args.append(record_id)

        conn.execute(f"UPDATE assistant_records SET {', '.join(sets)} WHERE id = ?", args)
        # 一张通知卡片代表整个事项，归档/恢复时同步该事项的所有来源，
        # 防止归档后另一封旧通知立即重新出现在列表中。
        if body.archived is not None and r["kind"] == "notice":
            conn.execute(
                "UPDATE assistant_records SET archived=?, updated_at=? WHERE id IN "
                "(SELECT record_id FROM assistant_thread_sources WHERE thread_id IN "
                "(SELECT thread_id FROM assistant_thread_sources WHERE record_id=?))",
                (1 if body.archived else 0, now, record_id),
            )
        updated_row = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()

    return {"ok": True, "id": record_id, "status": updated_row["status"], "updated_at": now}


@router.delete("/records/{record_id}")
def delete_record(record_id: int, _user: dict = Depends(get_current)):
    """软删除并移至回收站：移动记录目录至 data/trash/，保持可还原性。"""
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")
        conn.execute("UPDATE assistant_records SET archived=1, updated_at=? WHERE id=?", (now_iso(), record_id))

    rec_dir = _record_dir(record_id)
    tid = None
    if rec_dir.is_dir():
        tid = trashbin.move_to_trash(
            [rec_dir],
            module="assistant",
            label=f"助手记录 #{record_id} ({r['title']})",
        )

    return {"ok": True, "id": record_id, "trash_id": tid}


@router.get("/diagnostics/llm")
def diagnostics_llm(_user: dict = Depends(get_current)):
    """真实探测大模型连通性（向当前配置的 Endpoint 发送测试请求），若不通返回诊断与连接提示。"""
    return llm.check_diagnostics()


@router.post("/records/{record_id}/retry")
def retry_record(
    record_id: int,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current),
):
    """手动重新触发整理（模型不可用、格式异常、上锁中断后重试）。"""
    _require_dek()
    now = now_iso()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        # Retrying a completed notice would run matching and scheduling again.
        # Recovery retries are for incomplete jobs, not re-importing a record.
        if r["status"] == "ready":
            raise HTTPException(409, "记录已整理完成，无需重试")

        latest = conn.execute("SELECT stage FROM assistant_jobs WHERE record_id=? ORDER BY id DESC LIMIT 1", (record_id,)).fetchone()
        if _job_lock(record_id).locked() or (latest and latest["stage"] in ("pending", "parsing")):
            raise HTTPException(409, "记录正在处理中")
        conn.execute("UPDATE assistant_records SET status='pending', updated_at=? WHERE id=?", (now, record_id))
        cur_job = conn.execute(
            "INSERT INTO assistant_jobs(record_id, stage, retry_count, dek_epoch, error_msg, created_at, updated_at) "
            "VALUES(?, 'pending', 0, ?, '', ?, ?)",
            (record_id, vault.epoch(), now, now),
        )
        job_id = int(cur_job.lastrowid)

    background_tasks.add_task(process_record_job, record_id)
    return {"ok": True, "id": record_id, "status": "pending", "job_id": job_id}


@router.get("/records/{record_id}/note-draft")
def get_note_draft(record_id: int, _user: dict = Depends(get_current)):
    """为笔记新建页提供预填草稿内容。"""
    _require_dek()
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

    card_data = {}
    rec_dir = _record_dir(record_id)
    if (rec_dir / "card.enc").exists():
        try:
            card_data = vault.read_json(rec_dir / "card.enc")
        except Exception:
            pass

    title = card_data.get("title") or r["title"] or "未命名笔记"
    brief = card_data.get("brief") or card_data.get("summary") or ""
    why_focus = card_data.get("why_focus") or ""
    highlights = card_data.get("highlights") or []

    content_lines = []
    if brief:
        content_lines.append(f"## 简介\n{brief}\n")
    if why_focus:
        content_lines.append(f"## 关注理由\n{why_focus}\n")
    if highlights:
        content_lines.append("## 核心要点\n" + "\n".join(f"- {h}" for h in highlights) + "\n")
    if r["source_url"]:
        content_lines.append(f"## 来源参考\n- 链接: {r['source_url']}\n- 类型: {r['source_type']}\n")
    if r["user_note"]:
        content_lines.append(f"## 原始备注\n{r['user_note']}\n")

    tags = []
    try:
        tags = json.loads(r["tags"] or "[]")
    except Exception:
        pass

    return {
        "title": title,
        "content": "\n".join(content_lines).strip(),
        "tags": tags,
        "category": r["category"],
        "source_record_id": record_id,
    }


@router.post("/records/{record_id}/link-note")
def link_note(record_id: int, body: LinkNoteIn, _user: dict = Depends(get_current)):
    """建立记录与正式笔记的关联，并将阅读状态标记为 noted。"""
    now = now_iso()
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        conn.execute(
            "INSERT OR IGNORE INTO assistant_links(record_id, target_type, target_id, created_at) VALUES(?,?,?,?)",
            (record_id, "note", body.note_id, now),
        )
        conn.execute(
            "UPDATE assistant_records SET read_state='noted', updated_at=? WHERE id=?",
            (now, record_id),
        )

    return {"ok": True, "record_id": record_id, "note_id": body.note_id}


@router.post("/records/{record_id}/link-workbench")
def link_record_to_workbench(
    record_id: int,
    body: LinkWorkbenchIn,
    _user: dict = Depends(get_current),
):
    """建立助手记录与工作台事项的双向关联。"""
    now = now_iso()
    with db() as conn:
        r = conn.execute("SELECT id, title, wb_item_id FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        wb_item = conn.execute("SELECT id, title FROM workbench_items WHERE id=?", (body.wb_item_id,)).fetchone()
        if not wb_item:
            raise HTTPException(404, "工作台事项不存在")

        # 1. 清除旧的关联
        conn.execute(
            "DELETE FROM workbench_links WHERE target_type='assistant_record' AND target_id=?",
            (str(record_id),),
        )
        conn.execute(
            "DELETE FROM assistant_links WHERE record_id=? AND target_type='workbench_item'",
            (record_id,),
        )

        # 2. 更新 assistant_records.wb_item_id
        conn.execute(
            "UPDATE assistant_records SET wb_item_id=?, updated_at=? WHERE id=?",
            (body.wb_item_id, now, record_id),
        )

        # 3. 同步更新关联线程（若存在）
        ts = conn.execute("SELECT thread_id FROM assistant_thread_sources WHERE record_id=?", (record_id,)).fetchone()
        if ts:
            conn.execute("UPDATE assistant_threads SET wb_item_id=?, updated_at=? WHERE id=?", (body.wb_item_id, now, ts["thread_id"]))

        # 4. 插入 workbench_links
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort), -1) AS m FROM workbench_links WHERE item_id=?",
            (body.wb_item_id,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT OR IGNORE INTO workbench_links(item_id, target_type, target_id, sort, created_at) VALUES(?, 'assistant_record', ?, ?, ?)",
            (body.wb_item_id, str(record_id), max_sort + 1, now),
        )

        # 5. 插入 assistant_links
        conn.execute(
            "INSERT OR IGNORE INTO assistant_links(record_id, target_type, target_id, created_at) VALUES(?, 'workbench_item', ?, ?)",
            (record_id, str(body.wb_item_id), now),
        )

    return {"ok": True, "record_id": record_id, "wb_item_id": body.wb_item_id, "wb_item_title": wb_item["title"]}


@router.delete("/records/{record_id}/link-workbench")
def unlink_record_from_workbench(
    record_id: int,
    _user: dict = Depends(get_current),
):
    """取消助手记录与工作台事项的双向关联。"""
    now = now_iso()
    with db() as conn:
        r = conn.execute("SELECT id, wb_item_id FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        conn.execute(
            "UPDATE assistant_records SET wb_item_id=NULL, updated_at=? WHERE id=?",
            (now, record_id),
        )
        ts = conn.execute("SELECT thread_id FROM assistant_thread_sources WHERE record_id=?", (record_id,)).fetchone()
        if ts:
            conn.execute("UPDATE assistant_threads SET wb_item_id=NULL, updated_at=? WHERE id=?", (now, ts["thread_id"]))

        conn.execute(
            "DELETE FROM workbench_links WHERE target_type='assistant_record' AND target_id=?",
            (str(record_id),),
        )
        conn.execute(
            "DELETE FROM assistant_links WHERE record_id=? AND target_type='workbench_item'",
            (record_id,),
        )

    return {"ok": True, "record_id": record_id}


@router.get("/workbench-items")
def list_assistant_workbench_items(_user: dict = Depends(get_current)):
    """获取工作台事项列表，供关联下拉框选择。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, parent_id, title FROM workbench_items WHERE archived=0 ORDER BY sort ASC, id ASC"
        ).fetchall()
    return [{"id": r["id"], "parent_id": r["parent_id"], "title": r["title"]} for r in rows]


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, _user: dict = Depends(get_current)):
    """获取通知聚合线程详情、历史演变时序与关联日程。"""
    with db() as conn:
        t = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (thread_id,)).fetchone()
        if not t:
            raise HTTPException(404, "通知线程不存在")

        sources = conn.execute(
            "SELECT ts.*, r.title AS record_title, r.source_type, r.source_url, r.created_at AS record_created "
            "FROM assistant_thread_sources ts "
            "JOIN assistant_records r ON ts.record_id = r.id "
            "WHERE ts.thread_id=? ORDER BY ts.sequence ASC",
            (thread_id,),
        ).fetchall()

        schedules = conn.execute(
            "SELECT sl.*, s.date, s.time_start, s.title, s.done "
            "FROM assistant_schedule_links sl "
            "JOIN schedule s ON sl.schedule_id = s.id "
            "WHERE sl.thread_id=?",
            (thread_id,),
        ).fetchall()

    thread_dict = dict(t)
    facts_p = _thread_dir(thread_id) / "facts.enc"
    if facts_p.exists() and vault.has_dek():
        try:
            facts = vault.read_json(facts_p)
            thread_dict["summary"] = facts.get("summary") or thread_dict["summary"]
            thread_dict["highlights"] = facts.get("highlights") or []
            thread_dict["latest_change"] = facts.get("latest_change") or thread_dict.get("latest_change", "")
        except Exception:
            pass
    else:
        try:
            thread_dict["highlights"] = json.loads(thread_dict["highlights"] or "[]")
        except Exception:
            pass

    return {
        **thread_dict,
        "sources": [dict(s) for s in sources],
        "schedules": [dict(s) for s in schedules],
    }


@router.post("/threads/{thread_id}/reconcile")
def reconcile_thread(thread_id: int, body: ThreadReconcileIn, _user: dict = Depends(get_current)):
    """人工调整/解决冲突/同步日程。"""
    now = now_iso()
    with db() as conn:
        t = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (thread_id,)).fetchone()
        if not t:
            raise HTTPException(404, "通知线程不存在")

        sets = []
        args = []
        if body.title is not None:
            sets.append("title = ?")
            args.append(body.title.strip()[:MAX_TITLE])

        if body.summary is not None:
            sets.append("summary = ?")
            args.append(body.summary.strip())

        if body.deadline_date is not None:
            sets.append("deadline_date = ?")
            args.append(body.deadline_date.strip())

        if body.deadline_time is not None:
            sets.append("deadline_time = ?")
            args.append(body.deadline_time.strip())

        if body.has_conflict is not None:
            sets.append("has_conflict = ?")
            args.append(1 if body.has_conflict else 0)

        if body.status is not None:
            if body.status not in ("active", "completed", "archived"):
                raise HTTPException(400, "status 必须是 active / completed / archived")
            sets.append("status = ?")
            args.append(body.status)

        sets.append("updated_at = ?")
        args.append(now)
        args.append(thread_id)

        conn.execute(f"UPDATE assistant_threads SET {', '.join(sets)} WHERE id = ?", args)

        # 同步日程并标记为用户已锁定（locked_by_user = 1，防止后续通知覆盖）
        if body.update_schedule and body.deadline_date is not None:
            sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if sched_link:
                conn.execute(
                    "UPDATE schedule SET date=?, time_start=? WHERE id=?",
                    (body.deadline_date.strip(),
                     (body.deadline_time.strip() if body.deadline_time is not None else ""),
                     sched_link["schedule_id"]),
                )
                conn.execute(
                    "UPDATE assistant_schedule_links SET locked_by_user=1 WHERE thread_id=?",
                    (thread_id,),
                )

        updated_thread = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (thread_id,)).fetchone()

    return {"ok": True, "thread": dict(updated_thread)}


def _tasks_for_sources(source_ids: list[int]) -> list[dict]:
    tasks = []
    for source_id in source_ids:
        tasks.extend(_read_encrypted_json(_record_dir(source_id) / "card.enc").get("tasks") or [])
    return _combine_source_tasks(tasks)


@router.post("/threads/{thread_id}/extract-missing-tasks")
def extract_missing_tasks(thread_id: int, _user: dict = Depends(get_current)):
    """Extract missing tasks from retained sources without replacing edited tasks."""
    _require_dek()
    epoch = vault.epoch()
    with db() as conn:
        rows = conn.execute("SELECT r.id FROM assistant_thread_sources ts JOIN assistant_records r ON r.id=ts.record_id WHERE ts.thread_id=? ORDER BY ts.sequence", (thread_id,)).fetchall()
    if not rows:
        raise HTTPException(404, "事项不存在或没有通知来源")
    processed = 0
    errors = []
    for row in rows:
        record_id = row["id"]
        card_path = _record_dir(record_id) / "card.enc"
        card = _read_encrypted_json(card_path)
        if not card or card.get("tasks_extracted") or card.get("tasks"):
            continue
        try:
            raw = vault.read_text(_record_dir(record_id) / "raw.enc")
        except Exception:
            raw = ""
        images = []
        for asset in (_record_dir(record_id) / "assets").glob("*"):
            if asset.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                try:
                    images.append((vault.read_bytes(asset), mimetypes.guess_type(asset.name)[0] or "image/png"))
                except Exception:
                    pass
        if not raw and not images:
            errors.append({"record_id": record_id, "reason": "原文和图片不可用"})
            continue
        try:
            result = assistant_ai.notice_tasks(raw, images)
            if not isinstance(result.get("tasks"), list):
                raise llm.AiUnavailable("模型没有返回有效待办列表")
            if not vault.has_dek() or vault.epoch() != epoch:
                raise HTTPException(423, "数据已锁定，停止处理")
            card["tasks"] = _normalize_notice_tasks(result["tasks"], raw, record_id)
            card["tasks_extracted"] = True
            vault.write_json(card_path, card)
            processed += 1
        except llm.AiUnavailable as exc:
            errors.append({"record_id": record_id, "reason": str(exc)[:200]})
    if not vault.has_dek() or vault.epoch() != epoch:
        raise HTTPException(423, "数据已锁定，停止处理")
    facts_path = _thread_dir(thread_id) / "facts.enc"
    facts = _read_encrypted_json(facts_path)
    facts["tasks"] = _tasks_for_sources([r["id"] for r in rows])
    vault.write_json(facts_path, facts)
    _sync_task_schedules(thread_id, facts["tasks"])
    return {"ok": True, "processed": processed, "errors": errors}


@router.post("/threads/{thread_id}/merge")
def merge_threads(thread_id: int, body: MergeThreadIn, _user: dict = Depends(get_current)):
    _require_dek()
    source_id = body.source_thread_id
    if source_id == thread_id:
        raise HTTPException(400, "不能合并同一事项")
    with db() as conn:
        target = conn.execute("SELECT * FROM assistant_threads WHERE id=? AND status!='archived'", (thread_id,)).fetchone()
        source = conn.execute("SELECT * FROM assistant_threads WHERE id=? AND status!='archived'", (source_id,)).fetchone()
        if not target or not source:
            raise HTTPException(404, "事项不存在或已归档")
        target_ids = [r["record_id"] for r in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=? ORDER BY sequence", (thread_id,))]
        source_rows = conn.execute("SELECT record_id,sequence,change_reason FROM assistant_thread_sources WHERE thread_id=? ORDER BY sequence", (source_id,)).fetchall()
        source_ids = [r["record_id"] for r in source_rows]
        if not target_ids or not source_ids:
            raise HTTPException(409, "事项缺少来源，无法合并")
        for a in target_ids:
            for b in source_ids:
                conn.execute("DELETE FROM assistant_separate_sources WHERE record_a=? AND record_b=?", tuple(sorted((a, b))))
        links = [r["id"] for r in conn.execute("SELECT id FROM assistant_schedule_links WHERE thread_id=?", (source_id,))]
        source_kinds = {str(r["id"]): r["kind"] for r in conn.execute(
            "SELECT r.id,r.kind FROM assistant_records r JOIN assistant_thread_sources s ON s.record_id=r.id WHERE s.thread_id=?", (source_id,))}
        snapshot = {"target": _read_encrypted_json(_thread_dir(thread_id) / "facts.enc"),
                    "source": _read_encrypted_json(_thread_dir(source_id) / "facts.enc"), "source_status": source["status"],
                    "source_rows": [dict(r) for r in source_rows], "source_kinds": source_kinds}
        cur = conn.execute("INSERT INTO assistant_manual_merges(target_thread_id,source_thread_id,record_ids,schedule_link_ids,created_at) VALUES(?,?,?,?,?)",
                           (thread_id, source_id, json.dumps({"target": target_ids, "source": source_ids}), json.dumps(links), now_iso()))
        merge_id = cur.lastrowid
        vault.write_json(_thread_dir(source_id) / f"merge-{merge_id}.enc", snapshot)
        offset = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM assistant_thread_sources WHERE thread_id=?", (thread_id,)).fetchone()[0]
        for i, record_id in enumerate(source_ids, 1):
            conn.execute("UPDATE assistant_thread_sources SET thread_id=?,sequence=?,change_reason=? WHERE thread_id=? AND record_id=?",
                         (thread_id, offset + i, "用户手动合并", source_id, record_id))
            conn.execute("UPDATE assistant_records SET kind='notice',updated_at=? WHERE id=? AND kind='later'", (now_iso(), record_id))
        merged_rows = conn.execute(
            "SELECT s.id FROM assistant_thread_sources s JOIN assistant_records r ON r.id=s.record_id "
            "WHERE s.thread_id=? ORDER BY r.created_at,s.record_id", (thread_id,)
        ).fetchall()
        for sequence, row in enumerate(merged_rows, 1):
            conn.execute("UPDATE assistant_thread_sources SET sequence=? WHERE id=?", (sequence, row["id"]))
        conn.execute("UPDATE assistant_schedule_links SET thread_id=? WHERE thread_id=?", (thread_id, source_id))
        conn.execute("UPDATE assistant_threads SET status='archived',updated_at=? WHERE id=?", (now_iso(), source_id))
        conn.execute("UPDATE assistant_threads SET latest_change='用户手动合并事项',updated_at=? WHERE id=?", (now_iso(), thread_id))
    facts = snapshot["target"]
    source_summary = snapshot["source"].get("summary") or source["summary"]
    if source_summary and source_summary not in (facts.get("summary") or ""):
        facts["summary"] = (facts.get("summary") or target["summary"]) + "\n" + source_summary
    facts["highlights"] = list(dict.fromkeys(
        (facts.get("highlights") or []) + (snapshot["source"].get("highlights") or [])
    ))
    facts["tasks"] = _tasks_for_sources(target_ids + source_ids)
    facts["latest_change"] = "用户手动合并事项"
    facts["last_manual_merge_id"] = merge_id
    vault.write_json(_thread_dir(thread_id) / "facts.enc", facts)
    return {"ok": True, "merge_id": merge_id}


@router.post("/merges/{merge_id}/undo")
def undo_manual_merge(merge_id: int, _user: dict = Depends(get_current)):
    _require_dek()
    with db() as conn:
        merge = conn.execute("SELECT * FROM assistant_manual_merges WHERE id=? AND undone=0", (merge_id,)).fetchone()
        if not merge:
            raise HTTPException(404, "合并记录不存在或已撤销")
        target_id, source_id = merge["target_thread_id"], merge["source_thread_id"]
        ids = json.loads(merge["record_ids"])
        current = [r["record_id"] for r in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=? ORDER BY sequence", (target_id,))]
        if set(current) != set(ids["target"] + ids["source"]):
            raise HTTPException(409, "事项来源已发生变化，请先拆分新增来源后再撤销")
        snapshot = _read_encrypted_json(_thread_dir(source_id) / f"merge-{merge_id}.enc")
        if not snapshot:
            raise HTTPException(409, "找不到合并前的快照")
        for a in ids["target"]:
            for b in ids["source"]:
                conn.execute("INSERT OR IGNORE INTO assistant_separate_sources(record_a,record_b) VALUES(?,?)", tuple(sorted((a, b))))
        for i, record_id in enumerate(ids["source"], 1):
            old = next((r for r in snapshot.get("source_rows", []) if r["record_id"] == record_id), {})
            conn.execute("UPDATE assistant_thread_sources SET thread_id=?,sequence=?,change_reason=? WHERE thread_id=? AND record_id=?", (source_id, old.get("sequence", i), old.get("change_reason", ""), target_id, record_id))
            previous_kind = snapshot.get("source_kinds", {}).get(str(record_id))
            if previous_kind in KINDS:
                conn.execute("UPDATE assistant_records SET kind=?,updated_at=? WHERE id=?", (previous_kind, now_iso(), record_id))
        for i, record_id in enumerate(ids["target"], 1):
            conn.execute("UPDATE assistant_thread_sources SET sequence=? WHERE thread_id=? AND record_id=?", (i, target_id, record_id))
        for link_id in json.loads(merge["schedule_link_ids"]):
            conn.execute("UPDATE assistant_schedule_links SET thread_id=? WHERE id=? AND thread_id=?", (source_id, link_id, target_id))
        conn.execute("UPDATE assistant_threads SET status=?,updated_at=? WHERE id=?", (snapshot.get("source_status", "active"), now_iso(), source_id))
        conn.execute("UPDATE assistant_threads SET latest_change='已撤销手动合并',updated_at=? WHERE id=?", (now_iso(), target_id))
        conn.execute("UPDATE assistant_manual_merges SET undone=1 WHERE id=?", (merge_id,))
    for tid, key in ((target_id, "target"), (source_id, "source")):
        facts = snapshot.get(key) or {}
        facts["tasks"] = _tasks_for_sources(ids[key])
        vault.write_json(_thread_dir(tid) / "facts.enc", facts)
        _sync_task_schedules(tid, facts["tasks"])
    return {"ok": True}


@router.patch("/threads/{thread_id}/tasks/{task_id}")
def update_thread_task(thread_id: int, task_id: str, body: TaskPatchIn, _user: dict = Depends(get_current)):
    _require_dek()
    facts_path = _thread_dir(thread_id) / "facts.enc"
    facts = _read_encrypted_json(facts_path)
    tasks = facts.get("tasks") or []
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(404, "待办不存在")
    changes = body.model_dump(exclude_none=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()[:300]
        if not changes["title"]:
            raise HTTPException(422, "待办标题不能为空")
    try:
        if changes.get("deadline_date"):
            datetime.strptime(changes["deadline_date"], "%Y-%m-%d")
        if changes.get("deadline_time"):
            datetime.strptime(changes["deadline_time"], "%H:%M")
    except ValueError:
        raise HTTPException(422, "日期或时间格式无效")
    old_key = (task.get("title"), task.get("deadline_date") or "", task.get("deadline_time") or "", task.get("kind"))
    with db() as conn:
        source_ids = [r["record_id"] for r in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=?", (thread_id,))]
    for source_id in source_ids:
        card_path = _record_dir(source_id) / "card.enc"
        card = _read_encrypted_json(card_path)
        changed = False
        for source_task in card.get("tasks") or []:
            key = (source_task.get("title"), source_task.get("deadline_date") or "", source_task.get("deadline_time") or "", source_task.get("kind"))
            if source_task.get("id") == task_id or (source_id in (task.get("source_record_ids") or []) and key == old_key):
                source_task.update(changes)
                source_task["user_edited"] = True
                changed = True
        if changed:
            vault.write_json(card_path, card)
    task.update(changes)
    task["user_edited"] = True
    facts["tasks"] = _tasks_for_sources(source_ids)
    vault.write_json(facts_path, facts)
    _sync_task_schedules(thread_id, facts["tasks"])
    return {"ok": True, "task": task}


@router.post("/threads/{thread_id}/split-source")
def split_source_from_thread(
    thread_id: int,
    body: SplitSourceIn,
    _user: dict = Depends(get_current),
):
    """误合并事项的拆分与撤销接口：
    将误并入原事项 thread_id 的某条 record_id 拆分出来，恢复为独立事项并建立属于它的独立日程 DDL，
    同时重新计算原事项的事实、截止时间与日程。"""
    record_id = body.record_id
    now = now_iso()

    with db() as conn:
        t_row = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (thread_id,)).fetchone()
        if not t_row:
            raise HTTPException(404, "通知线程不存在")

        r_row = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r_row:
            raise HTTPException(404, "记录不存在")

        src_row = conn.execute(
            "SELECT * FROM assistant_thread_sources WHERE thread_id=? AND record_id=?",
            (thread_id, record_id),
        ).fetchone()
        if not src_row:
            raise HTTPException(400, "该记录不属于此事项线程")
        source_count = conn.execute("SELECT COUNT(*) FROM assistant_thread_sources WHERE thread_id=?", (thread_id,)).fetchone()[0]
        if source_count < 2:
            raise HTTPException(409, "事项只有一条来源，不能拆分")
        for other in conn.execute("SELECT record_id FROM assistant_thread_sources WHERE thread_id=? AND record_id!=?", (thread_id, record_id)):
            conn.execute("INSERT OR IGNORE INTO assistant_separate_sources(record_a,record_b) VALUES(?,?)", tuple(sorted((record_id, other["record_id"]))))

        # 1. 从当前 assistant_thread_sources 移除该记录
        conn.execute(
            "DELETE FROM assistant_thread_sources WHERE thread_id=? AND record_id=?",
            (thread_id, record_id),
        )

        # 2. 为该记录新建一个独立的 assistant_threads 事项
        rec_dir = _record_dir(record_id)
        card_p = rec_dir / "card.enc"
        rec_card = {}
        if card_p.exists() and vault.has_dek():
            try:
                rec_card = vault.read_json(card_p)
            except Exception:
                pass

        new_title = rec_card.get("title") or r_row["title"] or "独立通知事项"
        new_summary = rec_card.get("summary") or r_row["user_note"] or ""
        new_highlights = rec_card.get("highlights") or []
        new_ddl_date = rec_card.get("deadline_date") or ""
        new_ddl_time = rec_card.get("deadline_time") or ""
        new_wb_id = r_row["wb_item_id"] if "wb_item_id" in r_row.keys() else None

        cur_t = conn.execute(
            """
            INSERT INTO assistant_threads(title, summary, highlights, latest_change, deadline_date, deadline_time, has_conflict, wb_item_id, status, created_at, updated_at)
            VALUES(?,?,'[]',?,?,?,0,?, 'active', ?, ?)
            """,
            (new_title, new_summary[:80], "从误合并中拆分撤销为独立事项", new_ddl_date, new_ddl_time, new_wb_id, r_row["created_at"], now),
        )
        new_thread_id = int(cur_t.lastrowid)

        # 为新事项创建首条 source
        conn.execute(
            """
            INSERT INTO assistant_thread_sources(thread_id, record_id, sequence, change_type, change_reason, received_at, created_at)
            VALUES(?,?,1,'new','从误合并中拆分独立建档',?,?)
            """,
            (new_thread_id, record_id, r_row["created_at"], now),
        )

        # 写入新事项加密 facts.enc
        new_tdir = _thread_dir(new_thread_id)
        new_tdir.mkdir(parents=True, exist_ok=True)
        if vault.has_dek():
            vault.write_json(new_tdir / "facts.enc", {
                "summary": new_summary,
                "highlights": new_highlights,
                "tasks": rec_card.get("tasks") or [],
                "latest_change": "从误合并中拆分独立建档",
                "deadline_date": new_ddl_date,
                "deadline_time": new_ddl_time,
                "updated_at": now,
            })

        # 为新事项建立独立日程 DDL（若包含截止日期）
        if new_ddl_date and not rec_card.get("tasks"):
            rec_sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND record_id=? AND task_id IS NULL",
                (thread_id, record_id),
            ).fetchone()

            if rec_sched_link:
                conn.execute(
                    "UPDATE assistant_schedule_links SET thread_id=? WHERE id=?",
                    (new_thread_id, rec_sched_link["id"]),
                )
                sched_title = f"【截止】{new_title}"
                conn.execute(
                    "UPDATE schedule SET date=?, time_start=?, title=?, note=? WHERE id=?",
                    (new_ddl_date, new_ddl_time, sched_title, "详见助手通知事项", rec_sched_link["schedule_id"]),
                )
            else:
                sched_title = f"【截止】{new_title}"
                cur_s = conn.execute(
                    "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at) "
                    "VALUES(?,?,?,?,?,?,0,0,?)",
                    (new_ddl_date, "daily", "ddl", sched_title, new_ddl_time, "详见助手通知事项", now),
                )
                conn.execute(
                    "INSERT INTO assistant_schedule_links(thread_id, record_id, schedule_id, role, locked_by_user, user_dismissed, created_at) "
                    "VALUES(?,?,?,?,0,0,?)",
                    (new_thread_id, record_id, cur_s.lastrowid, "ddl", now),
                )

        # 3. 重新计算原线程 thread_id
        remaining_sources = conn.execute(
            """
            SELECT ts.*, r.title AS record_title, r.created_at AS record_created
            FROM assistant_thread_sources ts
            JOIN assistant_records r ON ts.record_id = r.id
            WHERE ts.thread_id=?
            ORDER BY ts.sequence ASC, ts.id ASC
            """,
            (thread_id,),
        ).fetchall()

        if len(remaining_sources) == 0:
            # 原线程已无剩余通知，归档并清理孤立日程
            conn.execute("UPDATE assistant_threads SET status='archived', updated_at=? WHERE id=?", (now, thread_id))
            for sl in conn.execute("SELECT schedule_id FROM assistant_schedule_links WHERE thread_id=?", (thread_id,)).fetchall():
                if sl["schedule_id"]:
                    conn.execute("DELETE FROM schedule WHERE id=?", (sl["schedule_id"],))
            conn.execute("DELETE FROM assistant_schedule_links WHERE thread_id=?", (thread_id,))
        else:
            # 重排剩余通知序号
            for idx, s in enumerate(remaining_sources):
                conn.execute("UPDATE assistant_thread_sources SET sequence=? WHERE id=?", (idx + 1, s["id"]))

            # 提取剩余通知卡片数据，计算最新事实与截止日期
            rem_cards = []
            for s in remaining_sources:
                s_card_p = _record_dir(int(s["record_id"])) / "card.enc"
                c = {}
                if s_card_p.exists() and vault.has_dek():
                    try:
                        c = vault.read_json(s_card_p)
                    except Exception:
                        pass
                rem_cards.append({
                    "record_id": s["record_id"],
                    "title": c.get("title") or s["record_title"],
                    "summary": c.get("summary") or "",
                    "highlights": c.get("highlights") or [],
                    "tasks": c.get("tasks") or [],
                    "deadline_date": c.get("deadline_date") or "",
                    "deadline_time": c.get("deadline_time") or "",
                    "change_reason": s["change_reason"],
                })

            eff_summary = rem_cards[-1]["summary"] or rem_cards[0]["summary"]
            eff_highlights = rem_cards[-1]["highlights"] or rem_cards[0]["highlights"]

            # 从最新通知向前寻找有效截止日期
            eff_ddl_date = ""
            eff_ddl_time = ""
            for rc in reversed(rem_cards):
                if rc["deadline_date"]:
                    eff_ddl_date = rc["deadline_date"]
                    eff_ddl_time = rc["deadline_time"]
                    break

            if len(remaining_sources) == 1:
                eff_latest_change = "初始通知建档（已拆分撤销误合并）"
            else:
                eff_latest_change = rem_cards[-1]["change_reason"] or "通知规则更新"

            # 更新或恢复原日程
            orig_sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND task_id IS NULL AND schedule_id IS NOT NULL",
                (thread_id,),
            ).fetchone()

            if orig_sched_link and not orig_sched_link["locked_by_user"]:
                if eff_ddl_date:
                    sched_title = f"【截止】{t_row['title']}"
                    conn.execute(
                        "UPDATE schedule SET date=?, time_start=?, title=?, note=? WHERE id=?",
                        (eff_ddl_date, eff_ddl_time, sched_title, "详见助手通知事项", orig_sched_link["schedule_id"]),
                    )
                else:
                    # 拆分后原事项无剩余 DDL，清理日程
                    conn.execute("DELETE FROM schedule WHERE id=?", (orig_sched_link["schedule_id"],))
                    conn.execute("DELETE FROM assistant_schedule_links WHERE id=?", (orig_sched_link["id"],))
            elif not orig_sched_link and eff_ddl_date and not any(c["tasks"] for c in rem_cards):
                # 重新建立原事项 DDL
                sched_title = f"【截止】{t_row['title']}"
                cur_s = conn.execute(
                    "INSERT INTO schedule(date, kind, type, title, time_start, note, done, sort, created_at) "
                    "VALUES(?,?,?,?,?,?,0,0,?)",
                    (eff_ddl_date, "daily", "ddl", sched_title, eff_ddl_time, "详见助手通知事项", now),
                )
                conn.execute(
                    "INSERT INTO assistant_schedule_links(thread_id, record_id, schedule_id, role, locked_by_user, user_dismissed, created_at) "
                    "VALUES(?,?,?,?,0,0,?)",
                    (thread_id, remaining_sources[0]["record_id"], cur_s.lastrowid, "ddl", now),
                )

            # 更新原线程事实
            conn.execute(
                "UPDATE assistant_threads SET summary=?, highlights='[]', latest_change=?, deadline_date=?, deadline_time=?, updated_at=? WHERE id=?",
                (eff_summary[:80], eff_latest_change, eff_ddl_date, eff_ddl_time, now, thread_id),
            )

            # 更新原线程加密 facts.enc
            orig_tdir = _thread_dir(thread_id)
            orig_tdir.mkdir(parents=True, exist_ok=True)
            if vault.has_dek():
                vault.write_json(orig_tdir / "facts.enc", {
                    "summary": eff_summary,
                    "highlights": eff_highlights,
                    "tasks": _combine_source_tasks([task for card in rem_cards for task in card["tasks"]]),
                    "latest_change": eff_latest_change,
                    "deadline_date": eff_ddl_date,
                    "deadline_time": eff_ddl_time,
                    "updated_at": now,
                })

    with db() as conn:
        for task in rec_card.get("tasks") or []:
            conn.execute("UPDATE assistant_schedule_links SET thread_id=? WHERE thread_id=? AND task_id=?",
                         (new_thread_id, thread_id, task.get("id")))
    _sync_task_schedules(new_thread_id, rec_card.get("tasks") or [])
    if remaining_sources:
        remaining_facts = _read_encrypted_json(_thread_dir(thread_id) / "facts.enc")
        _sync_task_schedules(thread_id, remaining_facts.get("tasks") or [])
    return {
        "ok": True,
        "old_thread_id": thread_id,
        "new_thread_id": new_thread_id,
        "split_record_id": record_id,
        "remaining_count": len(remaining_sources),
    }


CHAT_SYSTEM_PROMPT = assistant_ai.CHAT_SYSTEM_PROMPT


def _read_encrypted_json(path: Path) -> dict:
    """读取加密 JSON（facts.enc / card.enc）；文件缺失或解密失败返回空字典。"""
    try:
        if path.is_file() and vault.has_dek():
            data = vault.read_json(path)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _chat_context(body: ChatIn) -> tuple[str, list[dict]]:
    """构建有据问答上下文：优先解密 facts.enc / card.enc / raw.enc，拿不到才退回数据库短摘要。"""
    _require_dek()
    blocks: list[str] = []
    sources: list[dict] = []

    with db() as conn:
        if body.thread_id:
            t = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (body.thread_id,)).fetchone()
            if t:
                facts = _read_encrypted_json(_thread_dir(t["id"]) / "facts.enc")
                summary = facts.get("summary") or t["summary"]
                highlights = facts.get("highlights") or []
                quote = facts.get("quote") or ""
                evidence = facts.get("evidence_quotes") or []
                src_titles = [
                    row["title"] for row in conn.execute(
                        "SELECT r.title FROM assistant_thread_sources ts "
                        "JOIN assistant_records r ON ts.record_id = r.id "
                        "WHERE ts.thread_id=? ORDER BY ts.sequence ASC",
                        (t["id"],),
                    ).fetchall()
                ]
                lines = [
                    f"【事项】{t['title']}",
                    f"状态: {t['status']}",
                    f"截止时间: {t['deadline_date']} {t['deadline_time']}",
                    f"最新变动: {facts.get('latest_change') or t['latest_change']}",
                    f"核心事实: {summary}",
                ]
                if highlights:
                    lines.append("重点要求: " + "；".join(str(h) for h in highlights))
                if quote:
                    lines.append(f"关键依据原句: {quote}")
                if evidence:
                    lines.append("佐证原句: " + " | ".join(str(e) for e in evidence[:4]))
                if src_titles:
                    lines.append("来源通知: " + " / ".join(src_titles[:8]))
                blocks.append("\n".join(lines))
                sources.append({
                    "type": "thread",
                    "id": t["id"],
                    "title": t["title"],
                    "deadline_date": t["deadline_date"] or "",
                    "quote": quote,
                })
        elif body.record_id:
            r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (body.record_id,)).fetchone()
            if r:
                rec_dir = _record_dir(r["id"])
                card = _read_encrypted_json(rec_dir / "card.enc")
                raw = ""
                raw_path = rec_dir / "raw.enc"
                if raw_path.is_file():
                    try:
                        raw = vault.read_text(raw_path)
                    except Exception:
                        raw = ""
                lines = [
                    f"【记录】{r['title']}",
                    f"类型: {r['kind']}",
                    f"分类: {r['category']}",
                    f"备注: {r['user_note']}",
                    f"来源: {r['source_url']}",
                ]
                card_summary = card.get("summary") or card.get("brief") or ""
                if card_summary:
                    lines.append(f"摘要: {card_summary}")
                if card.get("why_focus"):
                    lines.append(f"关注理由: {card['why_focus']}")
                if card.get("highlights"):
                    lines.append("要点: " + "；".join(str(h) for h in card["highlights"]))
                if card.get("quote"):
                    lines.append(f"关键依据原句: {card['quote']}")
                if card.get("evidence_quotes"):
                    lines.append("佐证原句: " + " | ".join(str(e) for e in card["evidence_quotes"][:4]))
                if raw:
                    lines.append(f"原文节选:\n{raw[:6000]}")
                blocks.append("\n".join(lines))
                sources.append({
                    "type": "record",
                    "id": r["id"],
                    "title": r["title"],
                    "quote": card.get("quote") or "",
                })
        else:
            # 综合检索活跃线程与重点卡片（同样解密，而不是只给 80 字短摘要）
            threads = conn.execute(
                "SELECT * FROM assistant_threads WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 6"
            ).fetchall()
            for t in threads:
                facts = _read_encrypted_json(_thread_dir(t["id"]) / "facts.enc")
                summary = facts.get("summary") or t["summary"]
                lines = [
                    f"- 事项《{t['title']}》: 截止 {t['deadline_date']} {t['deadline_time']}; "
                    f"最新变动: {facts.get('latest_change') or t['latest_change']}; 摘要: {summary}"
                ]
                if facts.get("quote"):
                    lines.append(f"  关键依据: {facts['quote']}")
                blocks.append("\n".join(lines))
                sources.append({
                    "type": "thread",
                    "id": t["id"],
                    "title": t["title"],
                    "deadline_date": t["deadline_date"] or "",
                    "quote": facts.get("quote") or "",
                })

            records = conn.execute(
                "SELECT * FROM assistant_records WHERE archived=0 ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
            for r in records:
                card = _read_encrypted_json(_record_dir(r["id"]) / "card.enc")
                summary = card.get("summary") or card.get("brief") or ""
                lines = [
                    f"- 记录《{r['title']}》({r['kind']}): 类别 {r['category']}; 备注 {r['user_note']}"
                ]
                if summary:
                    lines.append(f"  摘要: {summary}")
                if card.get("quote"):
                    lines.append(f"  关键依据: {card['quote']}")
                blocks.append("\n".join(lines))
                sources.append({
                    "type": "record",
                    "id": r["id"],
                    "title": r["title"],
                    "quote": card.get("quote") or "",
                })

    return "\n\n".join(blocks), sources


def _chat_messages(query: str, context: str) -> list[dict]:
    return assistant_ai.chat_messages(query, context)


@router.post("/chat")
def chat_assistant(body: ChatIn, _user: dict = Depends(get_current)):
    """基于已归档事实的有据问答（非流式；流式请用 /chat/stream）。"""
    query = body.query.strip()
    context_str, sources = _chat_context(body)

    try:
        ans = assistant_ai.chat(_chat_messages(query, context_str))
        return {"answer": ans, "sources_used": len(sources), "sources": sources}
    except llm.AiUnavailable as e:
        # 明确告知模型不可用，只把检索到的原始资料交给用户核对，不伪装成模型回答。
        fallback_text = (
            f"AI 服务暂不可用（{e}）。以下是根据已保存资料检索到的内容，请自行核对：\n\n"
            f"{context_str}"
        )
        return {"answer": fallback_text, "sources_used": len(sources), "sources": sources,
                "degraded": True, "error": str(e)}


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_assistant_stream(body: ChatIn, _user: dict = Depends(get_current)):
    """有据问答的流式版本：SSE 推送 meta / delta / done / error 事件。

    上下文在响应开始前同步构建（含解密），生成器只负责转发模型增量。
    """
    query = body.query.strip()
    context_str, sources = _chat_context(body)
    messages = _chat_messages(query, context_str)

    def generate():
        yield _sse("meta", {"sources": sources})
        try:
            for piece in assistant_ai.chat_stream(messages):
                yield _sse("delta", {"text": piece})
            yield _sse("done", {"sources_used": len(sources)})
        except llm.AiUnavailable as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:  # 生成器里不能再抛回 FastAPI，统一转成 error 事件
            yield _sse("error", {"message": f"流式输出失败: {e}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 解锁唤醒与挂起作业恢复 ----------

def resume_paused_jobs() -> list[int]:
    """服务启动（或数据密钥恢复）后，扫描 paused_locked 及中断的 pending/parsing 作业，恢复处理。"""
    if not vault.has_dek():
        return []
    cur_epoch = vault.epoch()
    now = now_iso()
    resumed_records: list[int] = []
    with db() as conn:
        rows = conn.execute(
            "SELECT j.id, j.record_id FROM assistant_jobs j WHERE j.id=(SELECT MAX(id) FROM assistant_jobs WHERE record_id=j.record_id) AND j.stage IN ('paused_locked', 'pending', 'parsing')"
        ).fetchall()
        for row in rows:
            if _job_lock(row["record_id"]).locked():
                continue
            conn.execute(
                "UPDATE assistant_jobs SET stage='pending', dek_epoch=?, updated_at=? WHERE id=?",
                (cur_epoch, now, row["id"]),
            )
            conn.execute(
                "UPDATE assistant_records SET status='pending', updated_at=? WHERE id=?",
                (now, row["record_id"]),
            )
            resumed_records.append(row["record_id"])

    for rid in resumed_records:
        try:
            process_record_job(rid)
        except Exception:
            pass
    return resumed_records


@router.post("/resume-paused")
def api_resume_paused(_user: dict = Depends(get_current)):
    """手动或系统触发恢复挂起的作业。"""
    resumed = resume_paused_jobs()
    return {"ok": True, "resumed_records": resumed}

