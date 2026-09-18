"""记账本：收入/支出明细 + 余额与统计。

金额以"分"(int) 存储避免浮点误差；接口出入参用元(float)。分类自由填写。
余额 = 起始余额(settings.ledger.start_balance) + 累计收入 - 累计支出。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current
from ..db import db
from .settings import _load as _load_settings

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cents(yuan: float) -> int:
    return int(round(yuan * 100))


def _row(r) -> dict:
    fen = r["amount"]
    return {"id": r["id"], "date": r["date"], "kind": r["kind"],
            "amount": fen, "amount_yuan": round(fen / 100, 2),
            "category": r["category"], "note": r["note"], "created": r["created"]}


def _start_balance() -> float:
    cfg = _load_settings()
    try:
        return float(cfg.get("ledger.start_balance", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _month_prefix(month: str) -> str:
    return month + "-"


class LedgerIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    kind: str = "expense"
    amount: float = Field(gt=0, le=1_000_000_000)
    category: str = Field(default="", max_length=30)
    note: str = Field(default="", max_length=300)


def _validate(body: LedgerIn) -> None:
    if body.kind not in ("income", "expense"):
        raise HTTPException(400, "kind 只能是 income / expense")
    if not DATE_RE.match(body.date):
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")


@router.get("")
def list_ledger(month: str | None = None, kind: str | None = None,
                q: str | None = None, _user: dict = Depends(get_current)):
    sql = "SELECT * FROM ledger WHERE 1=1"
    args: list = []
    if month:
        if not MONTH_RE.match(month):
            raise HTTPException(400, "month 应为 YYYY-MM")
        sql += " AND date LIKE ?"
        args.append(_month_prefix(month) + "%")
    if kind in ("income", "expense"):
        sql += " AND kind=?"
        args.append(kind)
    if q and q.strip():
        sql += " AND (category LIKE ? OR note LIKE ?)"
        like = f"%{q.strip()}%"
        args += [like, like]
    sql += " ORDER BY date DESC, id DESC"
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("", status_code=201)
def create_ledger(body: LedgerIn, _user: dict = Depends(get_current)):
    _validate(body)
    cents = _cents(body.amount)
    if cents <= 0:
        raise HTTPException(400, "金额需大于 0")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) VALUES(?,?,?,?,?,?)",
            (body.date, body.kind, cents, body.category.strip()[:30], body.note.strip()[:300], _now()),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row)


@router.put("/{ledger_id}")
def update_ledger(ledger_id: int, body: LedgerIn, _user: dict = Depends(get_current)):
    _validate(body)
    cents = _cents(body.amount)
    if cents <= 0:
        raise HTTPException(400, "金额需大于 0")
    with db() as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id=?", (ledger_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "记录不存在")
        conn.execute(
            "UPDATE ledger SET date=?, kind=?, amount=?, category=?, note=? WHERE id=?",
            (body.date, body.kind, cents, body.category.strip()[:30], body.note.strip()[:300], ledger_id),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id=?", (ledger_id,)).fetchone()
    return _row(row)


@router.delete("/{ledger_id}")
def delete_ledger(ledger_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM ledger WHERE id=?", (ledger_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.get("/stats")
def ledger_stats(month: str | None = None, _user: dict = Depends(get_current)):
    """余额 / 本月收支 / 支出&收入去向（按分类）/ 近 6 个月趋势。"""
    m = month or datetime.now().strftime("%Y-%m")
    if not MONTH_RE.match(m):
        raise HTTPException(400, "month 应为 YYYY-MM")
    prefix = _month_prefix(m)

    def agg(kind: str, like: str | None = None) -> tuple[int, int]:
        sql = "SELECT SUM(amount) s, COUNT(*) c FROM ledger WHERE kind=?"
        args = [kind]
        if like:
            sql += " AND date LIKE ?"
            args.append(like + "%")
        with db() as conn:
            r = conn.execute(sql, args).fetchone()
        return (r["s"] or 0, r["c"] or 0)

    all_inc, _ = agg("income")
    all_exp, _ = agg("expense")
    m_inc, m_inc_c = agg("income", prefix)
    m_exp, m_exp_c = agg("expense", prefix)

    def by_cat(kind: str, like: str) -> list[dict]:
        sql = ("SELECT category, SUM(amount) s, COUNT(*) c FROM ledger "
               "WHERE kind=? AND date LIKE ? AND category<>'' GROUP BY category ORDER BY s DESC")
        with db() as conn:
            rows = conn.execute(sql, (kind, like + "%")).fetchall()
        out = [{"category": r["category"], "amount": round(r["s"] / 100, 2), "count": r["c"]} for r in rows]
        # 无分类归入"其他"
        sql0 = "SELECT SUM(amount) s, COUNT(*) c FROM ledger WHERE kind=? AND date LIKE ? AND category=''"
        with db() as conn:
            r0 = conn.execute(sql0, (kind, like + "%")).fetchone()
        if r0 and r0["s"]:
            out.append({"category": "（未分类）", "amount": round(r0["s"] / 100, 2), "count": r0["c"]})
        return out

    # 近 6 个月趋势
    trend = []
    now = datetime.now()
    for i in range(5, -1, -1):
        d = (now.replace(day=1) - timedelta(days=i * 31)).replace(day=1)
        ym = d.strftime("%Y-%m")
        like = ym + "-"
        inc, _ = agg("income", like)
        exp, _ = agg("expense", like)
        trend.append({"month": ym, "income": round(inc / 100, 2), "expense": round(exp / 100, 2)})

    start = _start_balance()
    bal = start + (all_inc - all_exp) / 100.0
    return {
        "start_balance": round(start, 2),
        "balance": round(bal, 2),
        "total": {"income": round(all_inc / 100, 2), "expense": round(all_exp / 100, 2)},
        "month": {
            "ym": m, "income": round(m_inc / 100, 2), "expense": round(m_exp / 100, 2),
            "income_count": m_inc_c, "expense_count": m_exp_c,
            "expense_by_category": by_cat("expense", prefix),
            "income_by_category": by_cat("income", prefix),
        },
        "trend": trend,
    }
