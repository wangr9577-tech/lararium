"""助手（Assistant）路由器：统一收集、通知聚合研判、稍后看轻量卡片、日程与工作台闭环。

核心规范：
- 通知流（Notice）：保存原文与证据文件，抽取 DDL 并聚合到相同事务线程，创建唯一日程 DDL 项（防污染）；
- 稍后看流（Later）：轻量卡片（简介+关注理由+分类+标签），不存论文全文，处理完清理临时大文件；
- 状态与加解密：低敏元数据存 SQLite，正文与卡片存 Vault（data/assistant/）；
- 上锁防御：调用前后比对 DEK Epoch，上锁时转为 paused_locked，杜绝越权与异常。
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import shutil
import uuid
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
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current, token_user
from ..db import db
from ..services import llm

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger("assistant")

MAX_TEXT = 200_000
MAX_TITLE = 200
MAX_NOTE = 5_000

KINDS = ("notice", "later")
MODES = ("auto", "notice", "later")
READ_STATES = ("unread", "read", "noted")
SCOPES = ("all", "alerts", "notice", "later", "archived")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _require_dek() -> None:
    if not vault.has_dek():
        raise HTTPException(423, "数据未解锁，请重新登录后重试")


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
    """从上传的文件二进制数据中安全提取纯文本（支持 PDF / Markdown / TXT / 源码等）。"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
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
            return f"\n\n【文本附件 {filename} 提取内容】\n" + content.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass
    return ""


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
        raise HTTPException(status_code=401, detail="未登录或未提供授权令牌")
    user = token_user(raw_token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录令牌无效或已过期，请重新登录")
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


class LinkWorkbenchIn(BaseModel):
    wb_item_id: int


# ---------- 核心后台作业处理逻辑 ----------

def process_record_job(record_id: int, use_fallback_rule: bool = False) -> None:
    """处理单个助手记录的后台作业。具备 DEK Epoch 校验和防上锁机制。"""
    if not vault.has_dek():
        with db() as conn:
            conn.execute(
                "UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE record_id=?",
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

    assets_dir = rec_dir / "assets"
    images: list[tuple[bytes, str]] = []
    file_extracted_parts: list[str] = []

    if assets_dir.is_dir():
        for asset in assets_dir.glob("*"):
            ext = asset.suffix.lower()
            try:
                b = vault.read_bytes(asset)
            except Exception:
                continue

            if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                mime = "image/png" if ext == ".png" else "image/jpeg"
                images.append((b, mime))
            else:
                extracted_txt = _extract_text_from_file_bytes(asset.name, b)
                if extracted_txt:
                    file_extracted_parts.append(extracted_txt)

    if file_extracted_parts:
        merged_extra = "\n".join(file_extracted_parts)
        raw_text = (raw_text + "\n" + merged_extra).strip()
        # 将解析到的正文保存入加密 raw.enc
        try:
            vault.write_text(raw_path, raw_text)
        except Exception:
            pass

    kind = rec["kind"]
    if kind not in ("notice", "later"):
        kind = llm.heuristic_detect_mode(raw_text, rec["user_note"])

    try:
        if kind == "notice":
            _handle_notice_pipeline(record_id, rec, raw_text, images, job, use_fallback_rule=use_fallback_rule)
        else:
            _handle_later_pipeline(record_id, rec, raw_text, images, job, use_fallback_rule=use_fallback_rule)
    except Exception as e:
        now = now_iso()
        with db() as conn:
            conn.execute("UPDATE assistant_records SET status='failed', updated_at=? WHERE id=?", (now, record_id))
            conn.execute(
                "UPDATE assistant_jobs SET stage='failed', error_msg=?, updated_at=? WHERE id=?",
                (str(e)[:500], now, job["id"]),
            )


def _handle_notice_pipeline(record_id: int, rec: Any, raw_text: str,
                            images: list[tuple[bytes, str]], job: Any,
                            use_fallback_rule: bool = False) -> None:
    """通知事项流水线：结构化提取 -> 线程匹配与版本研判 -> 日程同步 -> 留存加密原文与事实。"""
    job_epoch = job["dek_epoch"]
    extracted = None

    if use_fallback_rule:
        # 用户显式触发：改用规则降级整理
        extracted = llm.heuristic_extract_notice(raw_text, user_note=rec["user_note"])
        if not extracted or not isinstance(extracted, dict) or not extracted.get("title"):
            extracted = {
                "title": rec["user_note"] or (rec["title"] if rec["title"] and rec["title"] != "新记录" else "已收录通知事项"),
                "summary": "（规则模式整理）已保留原始内容与图片，请根据需要确认具体要求与截止时间。",
                "highlights": [],
                "deadline_date": "",
                "deadline_time": "",
                "event_keywords": ["规则整理"],
            }
    else:
        # 默认真实调用 AI 模型，严禁静默吞没异常或降级假成功！
        if not llm.is_enabled():
            cfg = llm._cfg()
            raise llm.AiUnavailable(
                f"AI 模型服务未启用。请检查配置或开启 SSH 隧道: {cfg['tunnel_hint']}，亦可在卡片中选择「改用规则降级整理」。"
            )

        sys_prompt = (
            "你是一个事务性通知信息提取专家。请从提交的通知/邮件文本或截图中提取核心事实。\n"
            "特别要求：必须从原文中提取用于支撑关键要求与截止时间的核心依据原句（quote 与 evidence_quotes），以便用户追溯核对事实。\n"
            "返回 JSON 格式：\n"
            "{\n"
            '  "title": "事项简明标题（20字以内）",\n'
            '  "summary": "核心要求事实摘要（100字以内）",\n'
            '  "highlights": ["要点1", "要点2", ...],\n'
            '  "deadline_date": "截止日期 YYYY-MM-DD，若无则为空字符串",\n'
            '  "deadline_time": "截止时间 HH:MM，若无则为空字符串",\n'
            '  "event_keywords": ["核心关键词1", "核心关键词2"],\n'
            '  "quote": "提取关键事实与截止时间依据的原文原句（例如：申报系统将于2026年11月20日18:00关闭）",\n'
            '  "evidence_quotes": ["核心依据原文句子1", "核心依据原文句子2"]\n'
            "}"
        )
        content_prompt = f"通知原文如下：\n{raw_text}\n用户备注：{rec['user_note']}"
        msg = llm.format_multimodal_message("user", content_prompt, images)
        extracted = llm.chat_structured([msg], system_prompt=sys_prompt)

    if not extracted or not isinstance(extracted, dict) or not extracted.get("title"):
        raise llm.AiUnavailable("模型未能输出有效的通知结构化信息（缺少 title）")

    # 3. 校验上锁
    if not vault.has_dek() or vault.epoch() != job_epoch:
        with db() as conn:
            conn.execute("UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?", (now_iso(), job["id"]))
        return

    title = str(extracted.get("title") or "未命名通知").strip()[:MAX_TITLE]
    summary = str(extracted.get("summary") or "").strip()
    highlights = extracted.get("highlights") or []
    if isinstance(highlights, str):
        highlights = [highlights]
    deadline_date = str(extracted.get("deadline_date") or "").strip()
    deadline_time = str(extracted.get("deadline_time") or "").strip()
    keywords = extracted.get("event_keywords") or []

    primary_quote = str(extracted.get("quote") or "").strip()
    evidence_quotes = extracted.get("evidence_quotes") or []
    if isinstance(evidence_quotes, str):
        evidence_quotes = [evidence_quotes]

    # 若大模型未输出 quote，启发式从原文中提取精准依据句子
    if not primary_quote:
        p_q, ev_q = _extract_quote_and_evidence(raw_text, deadline_date, deadline_time)
        primary_quote = p_q
        if not evidence_quotes:
            evidence_quotes = ev_q

    # 4. 线程匹配（Reconciliation Engine）
    matched_thread = None
    with db() as conn:
        active_threads = conn.execute(
            "SELECT * FROM assistant_threads WHERE status != 'archived' ORDER BY updated_at DESC"
        ).fetchall()

    def _extract_year(s: str) -> str:
        m = re.search(r"\b(20\d{2})\b", s) or re.search(r"(20\d{2})年", s)
        return m.group(1) if m else ""

    def _clean_topic(s: str) -> str:
        # 去除外层标点书名号、关于、前缀通知类型及年份
        c = s.strip()
        c = re.sub(r"^[【\[（(《\s]+", "", c)
        c = re.sub(r"[】\]）)》\s]+$", "", c)
        c = re.sub(r"\b20\d{2}年?", "", c)
        c = re.sub(r"^(?:关于|关于进一步|关于开展)?", "", c)
        c = re.sub(r"^(?:补充|延期|紧急|重要|最新|变更|修改)?(?:通知|公告|指南|要求|安排)[:：\s]*", "", c)
        c = re.sub(r"^(?:关于|关于进一步|关于开展)?", "", c)
        c = re.sub(r"(?:的通知|的公告|的指南|的要求|通知|公告|指南)$", "", c)
        c = re.sub(r"^[【\[（(《\s]+", "", c)
        c = re.sub(r"[】\]）)》\s]+$", "", c)
        return c.strip()

    y_new = _extract_year(title) or _extract_year(raw_text[:200])

    def _similarity(t_row: Any) -> float:
        t_title = t_row["title"]
        y_old = _extract_year(t_title)

        # 核心修复：不同年份的事项一票否决，绝对禁止合并（例如 2025 vs 2026）
        if y_new and y_old and y_new != y_old:
            return -999.0

        # 互斥批次/季度冲突一票否决
        for p1, p2 in (("春季", "秋季"), ("第一批", "第二批"), ("上半年", "下半年"), ("阶段一", "阶段二")):
            if (p1 in title and p2 in t_title) or (p2 in title and p1 in t_title):
                return -999.0

        score = 0.0
        c1 = _clean_topic(title)
        c2 = _clean_topic(t_title)

        if c1 and c2 and (c1 in c2 or c2 in c1 or c1 == c2):
            score += 4.0
        elif len(c1) >= 4 and len(c2) >= 4:
            import difflib
            sim_ratio = difflib.SequenceMatcher(None, c1, c2).ratio()
            if sim_ratio >= 0.6:
                score += sim_ratio * 4.0
            else:
                for sz in range(min(len(c1), len(c2)), 3, -1):
                    found = any(c1[i:i+sz] in c2 for i in range(len(c1) - sz + 1))
                    if found:
                        score += float(sz) / 2.0
                        break

        # 关键词匹配
        for kw in keywords:
            if kw and not re.match(r"^\d{4}$", kw):
                if kw in t_title:
                    score += 1.0
        return score

    best_match = None
    best_score = 0.0
    for t_row in active_threads:
        s = _similarity(t_row)
        if s > best_score:
            best_score = s
            best_match = t_row

    if best_match and best_score >= 3.0:
        matched_thread = best_match

    now = now_iso()
    thread_id = None
    change_type = "new"
    change_reason = "初始通知"

    if matched_thread:
        thread_id = matched_thread["id"]
        # 版本研判
        reconciled = None
        if llm.is_enabled():
            recon_sys = (
                "你是一个通知版本研判助手。比较既有事项事实与最新到来的通知内容，判断演进关系。\n"
                "如果两者属于不同年份、不同会议或不同批次，必须设置 is_same_event 为 false。\n"
                "change_type 必须是: new / update / postpone / cancel / conflict 之一。\n"
                "返回 JSON 格式：\n"
                "{\n"
                '  "is_same_event": true,\n'
                '  "change_type": "postpone",\n'
                '  "change_reason": "截止时间由原定...延期至...",\n'
                '  "summary": "整合后的最新事实摘要",\n'
                '  "highlights": ["最新事项1", ...],\n'
                '  "deadline_date": "最新 YYYY-MM-DD",\n'
                '  "deadline_time": "最新 HH:MM"\n'
                "}"
            )
            recon_user = (
                f"【既有事实】标题: {matched_thread['title']}\n"
                f"截止: {matched_thread['deadline_date']} {matched_thread['deadline_time']}\n"
                f"【新通知】\n{json.dumps(extracted, ensure_ascii=False)}"
            )
            try:
                reconciled = llm.chat_structured([{"role": "user", "content": recon_user}], system_prompt=recon_sys)
            except Exception:
                reconciled = None

        # 检查模型是否明确拒绝合并
        if reconciled and isinstance(reconciled, dict) and reconciled.get("is_same_event") is False:
            matched_thread = None  # 拒绝合并，退回新建独立线程分支
        else:
            if not reconciled or not isinstance(reconciled, dict):
                reconciled = llm.heuristic_reconcile_notice(dict(matched_thread), extracted)

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

        has_conflict = 1 if (change_type == "conflict" or matched_thread["has_conflict"]) else 0

        # 更新线程与持久化加密事实
        with db() as conn:
            # 检查是否有日程锁定或已主动移除
            sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND schedule_id IS NOT NULL", (thread_id,)
            ).fetchone()
            dismissed_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND user_dismissed=1", (thread_id,)
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
            if sched_link and not sched_link["locked_by_user"] and not sched_link["user_dismissed"]:
                if eff_ddl_date:
                    sched_title = f"【截止】{matched_thread['title']}"
                    conn.execute(
                        "UPDATE schedule SET date=?, time_start=?, title=?, note=? WHERE id=?",
                        (eff_ddl_date, eff_ddl_time, sched_title, "详见助手通知事项", sched_link["schedule_id"]),
                    )
            elif not sched_link and not dismissed_link and eff_ddl_date:
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
    else:
        # 新建独立线程
        with db() as conn:
            short_summary = summary[:80]
            cur_t = conn.execute(
                "INSERT INTO assistant_threads(title, summary, highlights, latest_change, deadline_date, deadline_time, has_conflict, status, created_at, updated_at) "
                "VALUES(?,?,'[]',?,?,?,0, 'active', ?, ?)",
                (title, short_summary, "初始通知导入", deadline_date, deadline_time, now, now),
            )
            thread_id = int(cur_t.lastrowid)

            conn.execute(
                "INSERT INTO assistant_thread_sources(thread_id, record_id, sequence, change_type, change_reason, received_at, created_at) "
                "VALUES(?,?,1,'new','初始创建',?,?)",
                (thread_id, record_id, rec["created_at"], now),
            )

            # 建立日程映射（唯一 DDL 原则：绝不额外创建同名 task）
            if deadline_date:
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

    # 5. 持久化加密卡片与事实快照
    rec_dir = _record_dir(record_id)
    vault.write_json(rec_dir / "card.enc", {
        "title": title,
        "summary": summary,
        "highlights": highlights,
        "deadline_date": deadline_date,
        "deadline_time": deadline_time,
        "quote": primary_quote,
        "evidence_quotes": evidence_quotes,
        "change_type": change_type,
        "change_reason": change_reason,
        "thread_id": thread_id,
    })

    with db() as conn:
        conn.execute(
            "UPDATE assistant_records SET status='ready', title=?, category='事务', updated_at=? WHERE id=?",
            (title, now, record_id),
        )
        conn.execute("UPDATE assistant_jobs SET stage='finalize', updated_at=? WHERE id=?", (now, job["id"]))


def _handle_later_pipeline(record_id: int, rec: Any, raw_text: str,
                           images: list[tuple[bytes, str]], job: Any,
                           use_fallback_rule: bool = False) -> None:
    """稍后看流水线：生成轻量卡片（简介+关注理由+分类+标签），清理大型临时原文。"""
    job_epoch = job["dek_epoch"]
    extracted = None

    if use_fallback_rule:
        # 用户显式触发：改用规则降级整理
        extracted = llm.heuristic_extract_later(raw_text, source_url=rec["source_url"], user_note=rec["user_note"])
        if not extracted or not isinstance(extracted, dict) or not extracted.get("title") or extracted.get("brief") == "暂无简介":
            extracted = {
                "title": rec["user_note"] or (rec["title"] if rec["title"] and rec["title"] != "新记录" else "已收录资料卡片"),
                "brief": "（规则模式整理）已保留原始内容或图片附件，未进行视觉多模态提炼。",
                "why_focus": rec["user_note"] or "留存稍后深入研读与查阅",
                "category": "其他",
                "tags": ["规则整理"],
            }
    else:
        # 默认真实调用 AI 模型，严禁静默吞没异常！
        if not llm.is_enabled():
            cfg = llm._cfg()
            raise llm.AiUnavailable(
                f"AI 模型服务未启用。请检查配置或开启 SSH 隧道: {cfg['tunnel_hint']}，亦可在卡片中选择「改用规则降级整理」。"
            )

        sys_prompt = (
            "你是一个知识整理助手。请为用户提交的内容（论文/项目/视频/文章等）生成极简的稍后看卡片。\n"
            "分类必须是以下之一：论文 / 项目 / 教程 / 视频 / 工具 / 事务 / 其他。\n"
            "返回 JSON 格式：\n"
            "{\n"
            '  "title": "项目/论文/文章名称",\n'
            '  "brief": "一至两句客观简介（说明是什么、解决什么问题）",\n'
            '  "why_focus": "为什么值得关注（核心亮点、应用场景或学术启发）",\n'
            '  "category": "论文",\n'
            '  "tags": ["标签1", "标签2"],\n'
            '  "quote": "关于该内容或论文最核心观点的原文原句摘录",\n'
            '  "evidence_quotes": ["核心依据原句1", "核心依据原句2"]\n'
            "}"
        )
        user_content = f"内容文本/线索：\n{raw_text}\n来源URL: {rec['source_url']}\n用户备注: {rec['user_note']}"
        msg = llm.format_multimodal_message("user", user_content, images)
        extracted = llm.chat_structured([msg], system_prompt=sys_prompt)

    if not extracted or not isinstance(extracted, dict) or not extracted.get("title") or not extracted.get("brief"):
        raise llm.AiUnavailable("模型未能输出有效的稍后看结构化卡片（缺少 title 或 brief）")

    # 校验上锁
    if not vault.has_dek() or vault.epoch() != job_epoch:
        with db() as conn:
            conn.execute("UPDATE assistant_jobs SET stage='paused_locked', updated_at=? WHERE id=?", (now_iso(), job["id"]))
        return

    title = str(extracted.get("title") or "").strip()[:MAX_TITLE]
    brief = str(extracted.get("brief") or "").strip()
    why_focus = str(rec["user_note"] or extracted.get("why_focus") or "").strip()
    category = str(extracted.get("category") or "其他").strip()
    tags = extracted.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if category == "论文" and "论文" not in tags:
        tags.append("论文")

    primary_quote = str(extracted.get("quote") or "").strip()
    evidence_quotes = extracted.get("evidence_quotes") or []
    if isinstance(evidence_quotes, str):
        evidence_quotes = [evidence_quotes]
    if not primary_quote:
        p_q, ev_q = _extract_quote_and_evidence(raw_text)
        primary_quote = p_q
        if not evidence_quotes:
            evidence_quotes = ev_q

    rec_dir = _record_dir(record_id)
    # 写入轻量卡片密文
    card_data = {
        "title": title,
        "brief": brief,
        "why_focus": why_focus or "待用户整理",
        "category": category,
        "tags": tags,
        "quote": primary_quote,
        "evidence_quotes": evidence_quotes,
        "source_url": rec["source_url"],
        "user_note": rec["user_note"],
    }
    vault.write_json(rec_dir / "card.enc", card_data)

    now = now_iso()
    # 稍后看即焚策略：长篇论文/大文本正文生成轻量卡片后清理临时 raw.enc 密文，附件则完备保留供查阅
    if category == "论文" or len(raw_text) > 500:
        raw_enc = rec_dir / "raw.enc"
        if raw_enc.is_file():
            try:
                raw_enc.unlink()
            except OSError:
                pass

    with db() as conn:
        conn.execute(
            "UPDATE assistant_records SET status='ready', title=?, category=?, tags=?, updated_at=? WHERE id=?",
            (title, category, json.dumps(tags, ensure_ascii=False), now, record_id),
        )
        conn.execute("UPDATE assistant_jobs SET stage='finalize', error_msg='', updated_at=? WHERE id=?", (now, job["id"]))


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
                    content = await val.read()
                    if content:
                        uploaded_files.append((fn, content))
    else:
        try:
            body = await request.json()
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
                img_bytes = base64.b64decode(b64_data)
                uploaded_files.append(("screenshot.png", img_bytes))
            except Exception:
                pass

    # 纯截图/纯附件也是合法输入
    if not text.strip() and not uploaded_files and not source_url.strip():
        raise HTTPException(400, "提交内容不能为空（文字、链接或文件至少包含一项）")

    if len(text) > MAX_TEXT:
        raise HTTPException(400, f"文本内容最长 {MAX_TEXT} 字符")

    if mode not in MODES:
        mode = "auto"

    # 如果有 PDF 或文本附件，先行提取文本拼接入 text
    file_extracted = []
    for fn, b_content in uploaded_files:
        ext_txt = _extract_text_from_file_bytes(fn, b_content)
        if ext_txt:
            file_extracted.append(ext_txt)
    if file_extracted:
        text = (text + "\n" + "\n".join(file_extracted)).strip()

    kind = mode
    if kind == "auto":
        kind = llm.heuristic_detect_mode(text, user_note)

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
            "INSERT INTO assistant_records(capture_id, kind, title, source_type, source_url, user_note, category, tags, status, read_state, archived, pinned, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,'[]','pending','unread',0,0,?,?)",
            (capture_id, kind, initial_title, source_type, source_url, user_note, "事务" if kind == "notice" else "其他", now, now),
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

    query_sql = f"""
        SELECT r.*,
               wb.title AS wb_item_title,
               t.id AS thread_id, t.title AS thread_title, t.summary AS thread_summary,
               t.deadline_date, t.deadline_time, t.has_conflict,
               (SELECT j.error_msg FROM assistant_jobs j WHERE j.record_id = r.id ORDER BY j.id DESC LIMIT 1) AS error_msg
        FROM assistant_records r
        LEFT JOIN workbench_items wb ON wb.id = r.wb_item_id
        LEFT JOIN assistant_thread_sources ts ON ts.record_id = r.id
        LEFT JOIN assistant_threads t ON ts.thread_id = t.id
        {where_sql}
        ORDER BY r.pinned DESC, r.created_at DESC, r.id DESC
        LIMIT ? OFFSET ?
    """

    count_sql = f"""
        SELECT COUNT(DISTINCT r.id) AS cnt
        FROM assistant_records r
        LEFT JOIN assistant_thread_sources ts ON ts.record_id = r.id
        LEFT JOIN assistant_threads t ON ts.thread_id = t.id
        {where_sql}
    """

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
            "title": r["title"],
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

        # 稍后看卡片：读取卡片密文获取简介与关注理由
        if r["kind"] == "later":
            card_p = _record_dir(int(r["id"])) / "card.enc"
            if card_p.exists() and vault.has_dek():
                try:
                    c_data = vault.read_json(card_p)
                    item["summary"] = c_data.get("brief") or ""
                    item["reason"] = c_data.get("why_focus") or r["user_note"] or ""
                except Exception:
                    pass

        if r["thread_id"]:
            tid = int(r["thread_id"])
            th_summary = r["thread_summary"] or ""
            th_highlights = []
            th_change = r["latest_change"] if "latest_change" in r.keys() else ""

            # 解密 facts.enc 提取详细事实
            facts_p = _thread_dir(tid) / "facts.enc"
            if facts_p.exists() and vault.has_dek():
                try:
                    facts = vault.read_json(facts_p)
                    th_summary = facts.get("summary") or th_summary
                    th_highlights = facts.get("highlights") or []
                    th_change = facts.get("latest_change") or th_change
                except Exception:
                    pass

            item["summary"] = th_summary
            item["highlights"] = th_highlights
            item["latest_change"] = th_change
            item["deadline_date"] = r["deadline_date"] or ""
            item["deadline_time"] = r["deadline_time"] or ""
            item["has_conflict"] = bool(r["has_conflict"])

            item["thread"] = {
                "id": tid,
                "title": r["thread_title"],
                "summary": th_summary,
                "highlights": th_highlights,
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

        quote = ""
        evidence_quotes = []
        if r["kind"] == "later" and card_p.exists() and vault.has_dek():
            try:
                c_data = vault.read_json(card_p)
                quote = c_data.get("quote") or ""
                evidence_quotes = c_data.get("evidence_quotes") or []
            except Exception:
                pass
        elif r["thread_id"]:
            facts_p = _thread_dir(int(r["thread_id"])) / "facts.enc"
            if facts_p.exists() and vault.has_dek():
                try:
                    facts = vault.read_json(facts_p)
                    quote = facts.get("quote") or ""
                    evidence_quotes = facts.get("evidence_quotes") or []
                except Exception:
                    pass
        item["quote"] = quote
        item["evidence_quotes"] = evidence_quotes

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
        ).fetchone()
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
    disp_type = "attachment" if download else "inline"
    encoded_name = quote(meta_name)
    content_disp = f'{disp_type}; filename="{clean_fn}"; filename*=UTF-8\'\'{encoded_name}'

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disp,
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
    fallback_rule: bool = Query(False),
    _user: dict = Depends(get_current),
):
    """手动重新触发整理。若 fallback_rule=True，则改用启发式规则降级整理。"""
    _require_dek()
    now = now_iso()
    with db() as conn:
        r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        if not r:
            raise HTTPException(404, "记录不存在")

        conn.execute("UPDATE assistant_records SET status='pending', updated_at=? WHERE id=?", (now, record_id))
        cur_job = conn.execute(
            "INSERT INTO assistant_jobs(record_id, stage, retry_count, dek_epoch, error_msg, created_at, updated_at) "
            "VALUES(?, 'pending', 0, ?, ?, ?, ?)",
            (record_id, vault.epoch(), "改用规则降级整理" if fallback_rule else "", now, now),
        )
        job_id = int(cur_job.lastrowid)

    background_tasks.add_task(process_record_job, record_id, use_fallback_rule=fallback_rule)
    return {"ok": True, "id": record_id, "status": "pending", "job_id": job_id, "fallback_rule": fallback_rule}


@router.post("/records/{record_id}/fallback-rule")
def fallback_rule_record(
    record_id: int,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current),
):
    """显式改用规则降级整理，把控制权明确交还给用户，而不是背地里偷偷假成功。"""
    return retry_record(record_id=record_id, background_tasks=background_tasks, fallback_rule=True, _user=_user)


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
                "latest_change": "从误合并中拆分独立建档",
                "deadline_date": new_ddl_date,
                "deadline_time": new_ddl_time,
                "updated_at": now,
            })

        # 为新事项建立独立日程 DDL（若包含截止日期）
        if new_ddl_date:
            rec_sched_link = conn.execute(
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND record_id=?",
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
                "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND schedule_id IS NOT NULL",
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
            elif not orig_sched_link and eff_ddl_date:
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
                    "latest_change": eff_latest_change,
                    "deadline_date": eff_ddl_date,
                    "deadline_time": eff_ddl_time,
                    "updated_at": now,
                })

    return {
        "ok": True,
        "old_thread_id": thread_id,
        "new_thread_id": new_thread_id,
        "split_record_id": record_id,
        "remaining_count": len(remaining_sources),
    }


@router.post("/chat")
def chat_assistant(body: ChatIn, _user: dict = Depends(get_current)):
    """基于当前已归档事实的有据问答接口。不胡编、标明出处。"""
    query = body.query.strip()
    facts_context = []

    with db() as conn:
        if body.thread_id:
            t = conn.execute("SELECT * FROM assistant_threads WHERE id=?", (body.thread_id,)).fetchone()
            if t:
                facts_context.append(
                    f"【事项】{t['title']}\n"
                    f"状态: {t['status']}\n"
                    f"截止时间: {t['deadline_date']} {t['deadline_time']}\n"
                    f"最新变动: {t['latest_change']}\n"
                    f"核心事实: {t['summary']}\n"
                    f"重点要求: {t['highlights']}\n"
                )
        elif body.record_id:
            r = conn.execute("SELECT * FROM assistant_records WHERE id=?", (body.record_id,)).fetchone()
            if r:
                facts_context.append(
                    f"【记录】{r['title']}\n"
                    f"类型: {r['kind']}\n"
                    f"分类: {r['category']}\n"
                    f"备注: {r['user_note']}\n"
                    f"来源: {r['source_url']}\n"
                )
        else:
            # 综合检索活跃线程与重点卡片
            threads = conn.execute(
                "SELECT * FROM assistant_threads WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 6"
            ).fetchall()
            for t in threads:
                facts_context.append(
                    f"- 事项《{t['title']}》: 截止 {t['deadline_date']} {t['deadline_time']}; 最新变动: {t['latest_change']}; 摘要: {t['summary']}"
                )

            records = conn.execute(
                "SELECT * FROM assistant_records WHERE archived=0 ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
            for r in records:
                facts_context.append(
                    f"- 记录《{r['title']}》({r['kind']}): 类别 {r['category']}; 备注 {r['user_note']}"
                )

    context_str = "\n".join(facts_context)

    if llm.is_enabled():
        system_prompt = (
            "你是一个严谨的个人信息与事务助手。\n"
            "请根据以下【已知归档事实】回答用户问题。严格遵循下列守则：\n"
            "1. 严格基于已知事实回答，绝不可捏造事实、日期或规定；\n"
            "2. 若已知事实不足以回答，如实说明已知部分并明确指出缺失信息；\n"
            "3. 回答时清晰标注所引用的事项名称或记录来源。\n\n"
            f"【已知归档事实】\n{context_str}"
        )
        try:
            ans = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ], max_tokens=1000)
            return {"answer": ans, "sources_used": len(facts_context)}
        except Exception:
            pass

    # 降级输出
    fallback_text = (
        f"基于已归档事实查得：\n\n{context_str}\n\n"
        f"针对您的问题『{query}』，请核对上述相关事项与截止时间安排。"
    )
    return {"answer": fallback_text, "sources_used": len(facts_context)}


# ---------- 解锁唤醒与挂起作业恢复 ----------

def resume_paused_jobs() -> list[int]:
    """用户重新登录并注入 DEK 或系统启动后，扫描 paused_locked 及中断的 pending/parsing 作业，恢复处理。"""
    if not vault.has_dek():
        return []
    cur_epoch = vault.epoch()
    now = now_iso()
    resumed_records: list[int] = []
    with db() as conn:
        rows = conn.execute(
            "SELECT id, record_id FROM assistant_jobs WHERE stage IN ('paused_locked', 'pending', 'parsing')"
        ).fetchall()
        for row in rows:
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

