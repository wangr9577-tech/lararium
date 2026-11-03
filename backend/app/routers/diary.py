"""日记：每天一个加密 md 文件 data/diary/YYYY-MM-DD.md。

文件结构：
  ---
  mood: 开心        （可空）
  weather: 晴       （可空）
  updated: 2026-09-06 10:00:00
  ---
  正文 Markdown...
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import config, trashbin, vault
from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/diary", tags=["diary"])

DIARY_DIR = config.DATA_DIR / "diary"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MOODS = ["", "平静", "开心", "低落", "焦虑", "疲惫", "充实", "其他"]
WEATHERS = ["", "晴", "多云", "阴", "雨", "雪", "雷雨"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(date: str) -> Path:
    return DIARY_DIR / f"{date}.md"


def _split(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw.strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2)


def _dump(date: str, meta: dict, content: str) -> None:
    head = yaml.safe_dump({"mood": meta.get("mood", ""), "weather": meta.get("weather", ""),
                           "updated": meta.get("updated", _now())},
                          allow_unicode=True, sort_keys=False).strip()
    vault.write_text(_path(date), f"---\n{head}\n---\n\n{content or ''}")


class DiaryIn(BaseModel):
    content: str = Field(default="", max_length=2_000_000)  # 防止误贴大文件写爆盘，超限由 FastAPI 返回 422
    mood: str = Field(default="", max_length=20)
    weather: str = Field(default="", max_length=20)


@router.get("/calendar")
def calendar(month: str, _user: dict = Depends(get_current)):
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month 应为 YYYY-MM")
    prefix = month + "-"
    days = sorted(p.stem for p in DIARY_DIR.glob(f"{month}-*.md"))
    return {"month": month, "days": days}


def _format_footprint_markdown(
    date: str,
    completed_tasks: list[str],
    pending_tasks: list[str],
    events: list[str],
    total_expense_fen: int,
    total_income_fen: int,
    top_expense_categories: list[dict],
    top_income_categories: list[dict],
    assistant_records: list[dict],
    assistant_sources: list[dict],
    wb_entries: list[dict],
    wb_new_items: list[dict],
    created_notes: list[str],
    updated_notes: list[str],
) -> str:
    lines = []

    # 1. 日程打卡
    schedule_parts = []
    if completed_tasks:
        titles_str = "、".join(completed_tasks[:3]) + ("…" if len(completed_tasks) > 3 else "")
        schedule_parts.append(f"完成 {len(completed_tasks)} 项（{titles_str}）")
    if pending_tasks:
        titles_str = "、".join(pending_tasks[:3]) + ("…" if len(pending_tasks) > 3 else "")
        schedule_parts.append(f"进行中 {len(pending_tasks)} 项（{titles_str}）")
    if events and not completed_tasks and not pending_tasks:
        titles_str = "、".join(events[:3]) + ("…" if len(events) > 3 else "")
        schedule_parts.append(f"活动日程（{titles_str}）")
    if schedule_parts:
        lines.append(f"> - **日程打卡**：{'，'.join(schedule_parts)}")

    # 2. 钱包记账
    ledger_parts = []
    if total_expense_fen > 0:
        exp_yuan = round(total_expense_fen / 100, 2)
        cat_items = []
        for c in top_expense_categories[:3]:
            cat_amt = c["amount"]
            amt_str = f"{int(cat_amt)}" if cat_amt == int(cat_amt) else f"{cat_amt:.2f}"
            cat_items.append(f"{c['category']} ¥{amt_str}")
        cat_str = "，".join(cat_items)
        exp_str = f"{int(exp_yuan)}" if exp_yuan == int(exp_yuan) else f"{exp_yuan:.2f}"
        ledger_parts.append(f"支出 ¥{exp_str}" + (f"（{cat_str}）" if cat_str else ""))
    if total_income_fen > 0:
        inc_yuan = round(total_income_fen / 100, 2)
        inc_str = f"{int(inc_yuan)}" if inc_yuan == int(inc_yuan) else f"{inc_yuan:.2f}"
        ledger_parts.append(f"收入 ¥{inc_str}")
    if ledger_parts:
        lines.append(f"> - **钱包记账**：{'，'.join(ledger_parts)}")

    # 3. 信息整理（助手 / 工作台）
    info_parts = []
    if assistant_records:
        titles = [r["title"] for r in assistant_records if r.get("title")]
        titles_str = ("（" + "、".join(titles[:2]) + ("…" if len(titles) > 2 else "") + "）") if titles else ""
        info_parts.append(f"助手新收录 {len(assistant_records)} 项待办事项{titles_str}")
    elif assistant_sources:
        info_parts.append(f"助手更新 {len(assistant_sources)} 个事项进展")

    if wb_entries:
        items_set = [e["item_title"] for e in wb_entries if e.get("item_title")]
        dedup_items = []
        for it in items_set:
            if it not in dedup_items:
                dedup_items.append(it)
        items_str = ("（" + "、".join(dedup_items[:2]) + ("…" if len(dedup_items) > 2 else "") + "）") if dedup_items else ""
        info_parts.append(f"工作台记录 {len(wb_entries)} 条小记{items_str}")
    elif wb_new_items:
        items_str = "、".join([i["title"] for i in wb_new_items[:2]]) + ("…" if len(wb_new_items) > 2 else "")
        info_parts.append(f"工作台新建 {len(wb_new_items)} 个事项（{items_str}）")

    if info_parts:
        lines.append(f"> - **信息整理**：{'；'.join(info_parts)}")

    # 4. 知识沉淀（笔记 / 博客）
    note_parts = []
    if created_notes:
        titles_str = "《" + "》、《".join(created_notes[:2]) + "》" + ("…" if len(created_notes) > 2 else "")
        note_parts.append(f"新建 {titles_str}")
    if updated_notes:
        titles_str = "《" + "》、《".join(updated_notes[:2]) + "》" + ("…" if len(updated_notes) > 2 else "")
        note_parts.append(f"编辑 {titles_str}")
    if note_parts:
        lines.append(f"> - **知识沉淀**：{'；'.join(note_parts)}")

    if not lines:
        lines.append("> - 今日暂无各模块动态记录，静心享受生活吧~")

    body = "\n".join(lines)
    return f"""> 📅 **今日足迹自动汇总**
{body}

### 💭 今日感想与复盘
（在此记录今天的心情、灵感与思考…）
"""


@router.get("/footprint")
def get_footprint(date: str = Query(default=""), _user: dict = Depends(get_current)):
    target_date = date.strip() if date else datetime.now().strftime("%Y-%m-%d")
    if not DATE_RE.match(target_date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")

    schedule_items = []
    completed_tasks = []
    pending_tasks = []
    events = []
    total_expense_fen = 0
    total_income_fen = 0
    expense_by_cat: dict[str, int] = {}
    income_by_cat: dict[str, int] = {}
    assistant_records = []
    assistant_sources = []
    wb_entries = []
    wb_new_items = []
    created_notes = []
    updated_notes = []

    try:
        with db() as conn:
            # 1. schedule
            s_rows = conn.execute(
                "SELECT id, type, title, done, time_start, note FROM schedule "
                "WHERE kind='daily' AND date=? ORDER BY done DESC, time_start, sort, id",
                (target_date,)
            ).fetchall()
            for r in s_rows:
                t = r["title"] or "未命名日程"
                schedule_items.append({
                    "id": r["id"], "type": r["type"], "title": t,
                    "done": bool(r["done"]), "time_start": r["time_start"]
                })
                if r["type"] == "event":
                    events.append(t)
                elif r["done"]:
                    completed_tasks.append(t)
                else:
                    pending_tasks.append(t)

            # 2. ledger
            l_rows = conn.execute(
                "SELECT id, kind, amount, category, note FROM ledger WHERE date=? ORDER BY id",
                (target_date,)
            ).fetchall()
            for r in l_rows:
                amt = r["amount"]
                cat = (r["category"] or "").strip() or "其它"
                if r["kind"] == "expense":
                    total_expense_fen += amt
                    expense_by_cat[cat] = expense_by_cat.get(cat, 0) + amt
                elif r["kind"] == "income":
                    total_income_fen += amt
                    income_by_cat[cat] = income_by_cat.get(cat, 0) + amt

            # 3. assistant & workbench
            try:
                ar_rows = conn.execute(
                    "SELECT id, kind, title, category, created_at FROM assistant_records "
                    "WHERE created_at LIKE ? ORDER BY id",
                    (f"{target_date}%",)
                ).fetchall()
                for r in ar_rows:
                    t = (r["title"] or "").strip() or (r["category"] or "").strip() or f"记录#{r['id']}"
                    assistant_records.append({"id": r["id"], "kind": r["kind"], "title": t})
            except Exception:
                pass

            try:
                ats_rows = conn.execute(
                    "SELECT ts.id, ts.change_type, t.title FROM assistant_thread_sources ts "
                    "JOIN assistant_threads t ON ts.thread_id = t.id "
                    "WHERE ts.created_at LIKE ? ORDER BY ts.id",
                    (f"{target_date}%",)
                ).fetchall()
                for r in ats_rows:
                    assistant_sources.append({"id": r["id"], "change_type": r["change_type"], "thread_title": r["title"]})
            except Exception:
                pass

            try:
                wbe_rows = conn.execute(
                    "SELECT e.id, e.item_id, i.title as item_title FROM workbench_entries e "
                    "JOIN workbench_items i ON e.item_id = i.id "
                    "WHERE e.created_at LIKE ? ORDER BY e.id",
                    (f"{target_date}%",)
                ).fetchall()
                for r in wbe_rows:
                    wb_entries.append({"id": r["id"], "item_id": r["item_id"], "item_title": r["item_title"]})
            except Exception:
                pass

            try:
                wbi_rows = conn.execute(
                    "SELECT id, title FROM workbench_items WHERE created_at LIKE ? ORDER BY id",
                    (f"{target_date}%",)
                ).fetchall()
                for r in wbi_rows:
                    wb_new_items.append({"id": r["id"], "title": r["title"]})
            except Exception:
                pass
    except Exception:
        pass

    # 4. notes
    if vault.has_dek():
        try:
            from .notes import _list_all
            all_notes = _list_all(include_content=False)
            for n in all_notes:
                c = (n.get("created") or "")[:10]
                u = (n.get("updated") or "")[:10]
                t = n.get("title") or "无标题笔记"
                if c == target_date:
                    created_notes.append(t)
                elif u == target_date:
                    updated_notes.append(t)
        except Exception:
            pass

    top_expense_categories = [
        {"category": cat, "amount": round(fen / 100, 2)}
        for cat, fen in sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True)
    ]
    top_income_categories = [
        {"category": cat, "amount": round(fen / 100, 2)}
        for cat, fen in sorted(income_by_cat.items(), key=lambda x: x[1], reverse=True)
    ]

    template = _format_footprint_markdown(
        date=target_date,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        events=events,
        total_expense_fen=total_expense_fen,
        total_income_fen=total_income_fen,
        top_expense_categories=top_expense_categories,
        top_income_categories=top_income_categories,
        assistant_records=assistant_records,
        assistant_sources=assistant_sources,
        wb_entries=wb_entries,
        wb_new_items=wb_new_items,
        created_notes=created_notes,
        updated_notes=updated_notes,
    )

    return {
        "date": target_date,
        "schedule": {
            "total": len(schedule_items),
            "completed_count": len(completed_tasks),
            "pending_count": len(pending_tasks),
            "completed": completed_tasks,
            "pending": pending_tasks,
            "events": events,
            "items": schedule_items,
        },
        "ledger": {
            "total_expense": round(total_expense_fen / 100, 2),
            "total_income": round(total_income_fen / 100, 2),
            "top_categories": top_expense_categories,
            "top_income_categories": top_income_categories,
        },
        "assistant_workbench": {
            "assistant_records_count": len(assistant_records),
            "assistant_records": [r["title"] for r in assistant_records],
            "assistant_sources_count": len(assistant_sources),
            "workbench_entries_count": len(wb_entries),
            "workbench_items_count": len(wb_new_items),
            "workbench_items": [i["title"] for i in wb_new_items],
        },
        "notes": {
            "created": created_notes,
            "updated": updated_notes,
        },
        "template": template,
    }


@router.get("/{date}")
def get_diary(date: str, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    p = _path(date)
    if not p.is_file():
        return {"date": date, "mood": "", "weather": "", "content": "", "updated": ""}
    meta, content = _split(vault.read_text(p))
    return {"date": date, "mood": meta.get("mood", ""), "weather": meta.get("weather", ""),
            "content": content.rstrip("\n"), "updated": meta.get("updated", "")}


@router.put("/{date}")
def put_diary(date: str, body: DiaryIn, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")
    if body.mood not in MOODS:
        raise HTTPException(400, f"心情只能是 {[m for m in MOODS if m]}")
    if body.weather not in WEATHERS:
        raise HTTPException(400, f"天气只能是 {[w for w in WEATHERS if w]}")
    _dump(date, {"mood": body.mood, "weather": body.weather, "updated": _now()}, body.content)
    meta, content = _split(vault.read_text(_path(date)))
    return {"date": date, "mood": body.mood, "weather": body.weather,
            "content": body.content, "updated": meta.get("updated", "")}


@router.delete("/{date}")
def delete_diary(date: str, _user: dict = Depends(get_current)):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date 应为 YYYY-MM-DD")
    p = _path(date)
    tid = None
    if p.is_file():
        # 移入回收站而非物理删（P2-L1）：与笔记/相册/论文一致，误删可恢复
        tid = trashbin.move_to_trash([p], module="diary", label=f"日记 {date}")
    return {"ok": True, "trash_id": tid}
