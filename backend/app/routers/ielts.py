"""雅思学习：听力/口语/阅读/写作 四栏时间线条目（要学什么、学了什么，可打勾/修改/删除）。

数据：sqlite 表 ielts_items（结构化，非加密正文域）。首次访问且表为空时自动播种预设
（口语主题清单 + 各科方法条目），随后用户可自由增删改勾。
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db

router = APIRouter(prefix="/api/ielts", tags=["ielts"])

SECTIONS = ("listening", "speaking", "reading", "writing")

# 预设：用户确认过的初始时间线（首启播种，之后一切以用户数据为准）
SEED: dict[str, list[str]] = {
    "listening": [
        "每日泛听 20 分钟磨耳朵（BBC 6 Minute English / 每日英语听力）",
        "雅思官方真题（剑桥雅思 C16–C19）：每套错题重听复盘",
        "听力场景词：租房 / 校园 / 学术讲座 各过一遍",
        "S1/S2 逐句听写训练（每周 3 次）",
        "考前限时模考听力 2 套",
    ],
    "speaking": [
        "工作与学习 Work & Study",
        "家乡与住所 Hometown & Accommodation",
        "家庭与朋友 Family & Friends",
        "爱好与兴趣 Hobbies（音乐 / 电影 / 读书）",
        "运动与健康 Sports & Health",
        "食物与烹饪 Food & Cooking",
        "科技与网络 Technology & Internet",
        "媒体与新闻 Media & News",
        "交通与旅行 Transport & Travel",
        "环境与自然 Environment & Nature",
        "购物与时尚 Shopping & Fashion",
        "节日与文化 Festivals & Culture",
        "教育与老师 Education",
        "天气与季节 Weather & Seasons",
        "动物与宠物 Animals & Pets",
        "城市与建筑 Cities & Buildings",
        "每天 15 分钟影子跟读练流利度",
        "每周 1 次模拟口试并复盘卡顿点",
    ],
    "reading": [
        "每天背单词 30 个（百词斩 · 雅思核心词书）",
        "雅思官方真题阅读（剑桥雅思 C16–C19）：每篇限时 20 分钟",
        "同义替换积累：每篇整理 5–10 组",
        "题型专项：Heading / TFNG / 填空 错题归类",
        "考前整卷模考 2 套",
    ],
    "writing": [
        "小作文图表句型与模板（线图 / 柱图 / 饼图 / 流程）",
        "每周 2 篇小作文（限时 20 分钟）",
        "大作文四类题型结构（同意与否 / 双边讨论 / 利弊 / 报告）",
        "每周 2 篇大作文并逐段打磨",
        "功能句语料积累（开头 / 转折 / 举例 / 结论）",
        "批改后复盘语法错误",
    ],
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(r) -> dict:
    return {"id": r["id"], "section": r["section"], "text": r["text"],
            "done": bool(r["done"]), "created": r["created_at"]}


_SEED_FLAG = "ielts.seeded"


def _ensure_seed(conn) -> None:
    """仅真正的首次安装播种预设。

    用 settings 表标记判断"是否已初始化过"，而非看表空不空——
    否则用户手动删光词库后，下次访问会被预设"复活"（P2 修复）。
    存量部署（已有数据但无标记）首次遇到时补写标记，之后不再播种。
    """
    flagged = conn.execute("SELECT value FROM settings WHERE key=?", (_SEED_FLAG,)).fetchone()
    if flagged is not None:
        return
    n = conn.execute("SELECT COUNT(*) AS c FROM ielts_items").fetchone()["c"]
    if n:  # 老数据补标记，不播种
        conn.execute("INSERT INTO settings(key, value) VALUES(?, '1') "
                     "ON CONFLICT(key) DO NOTHING", (_SEED_FLAG,))
        return
    rows = [(sec, t, _now()) for sec, texts in SEED.items() for t in texts]
    conn.executemany(
        "INSERT INTO ielts_items(section, text, sort, created_at) VALUES(?,?,0,?)",
        rows,
    )
    conn.execute("INSERT INTO settings(key, value) VALUES(?, '1') "
                 "ON CONFLICT(key) DO NOTHING", (_SEED_FLAG,))


class ItemIn(BaseModel):
    section: str
    text: str = Field(min_length=1, max_length=500)


class ItemTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class DoneIn(BaseModel):
    done: bool


def _check_section(section: str) -> None:
    if section not in SECTIONS:
        raise HTTPException(400, "section 只能是 listening / speaking / reading / writing")


@router.get("/items")
def list_items(_user: dict = Depends(get_current)):
    with db() as conn:
        _ensure_seed(conn)
        rows = conn.execute(
            "SELECT * FROM ielts_items ORDER BY section, id").fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("/items", status_code=201)
def create_item(body: ItemIn, _user: dict = Depends(get_current)):
    _check_section(body.section)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "内容不能为空")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ielts_items(section, text, done, sort, created_at) VALUES(?,?,0,0,?)",
            (body.section, text, _now()),
        )
        row = conn.execute("SELECT * FROM ielts_items WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemTextIn, _user: dict = Depends(get_current)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "内容不能为空")
    with db() as conn:
        row = conn.execute("SELECT * FROM ielts_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute("UPDATE ielts_items SET text=? WHERE id=?", (text, item_id))
        row = conn.execute("SELECT * FROM ielts_items WHERE id=?", (item_id,)).fetchone()
    return _row(row)


@router.put("/items/{item_id}/done")
def toggle_done(item_id: int, body: DoneIn, _user: dict = Depends(get_current)):
    with db() as conn:
        row = conn.execute("SELECT * FROM ielts_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        conn.execute("UPDATE ielts_items SET done=? WHERE id=?",
                     (1 if body.done else 0, item_id))
        row = conn.execute("SELECT * FROM ielts_items WHERE id=?", (item_id,)).fetchone()
    return _row(row)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM ielts_items WHERE id=?", (item_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "条目不存在")
    return {"ok": True}


# ---------- 周计划打卡（week=周一日期 YYYY-MM-DD；slot=d1..d7） ----------

WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLOT_RE = re.compile(r"^d[1-7]$")


class PlanIn(BaseModel):
    week: str
    slot: str
    done: bool


def _check_week_slot(week: str, slot: str) -> None:
    if not WEEK_RE.match(week):
        raise HTTPException(400, "week 应为周一日期 YYYY-MM-DD")
    try:
        datetime.strptime(week, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效周日期")
    if not SLOT_RE.match(slot):
        raise HTTPException(400, "slot 应为 d1..d7")


@router.get("/plan")
def get_plan(week: str, _user: dict = Depends(get_current)):
    _check_week_slot(week, "d1")  # 校验 week 格式即可
    with db() as conn:
        rows = conn.execute(
            "SELECT slot, done FROM ielts_plan_done WHERE week=?", (week,)).fetchall()
    return {"week": week, "items": [{"slot": r["slot"], "done": bool(r["done"])} for r in rows]}


@router.put("/plan")
def save_plan(body: PlanIn, _user: dict = Depends(get_current)):
    _check_week_slot(body.week, body.slot)
    with db() as conn:
        conn.execute(
            "INSERT INTO ielts_plan_done(week, slot, done, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(week, slot) DO UPDATE SET done=excluded.done, updated=excluded.updated",
            (body.week, body.slot, 1 if body.done else 0, _now()),
        )
    return {"week": body.week, "slot": body.slot, "done": body.done}
