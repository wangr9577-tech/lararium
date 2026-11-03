"""记账本：收入/支出/欠款明细 + 可用余额与统计。

金额以"分"(int) 存储避免浮点误差；接口出入参用元(float)。分类自由填写。

账目分三种 kind：
  income   收入
  expense  支出——分类不在「欠款渠道」清单里 → 现金支出，直接扣可用余额；
                     分类命中欠款渠道（花呗/京东白条/美团月付/抖音月付…）→ 信用消费，
                     不计入现金支出，改为计入该渠道「欠款」。
  repay    还款——冲减对应渠道欠款，同时减少现金余额（余额是真的流出去了）。

  可用余额 = 起始余额(settings.ledger.start_balance) + Σ收入 − Σ现金支出 − Σ还款
  欠款(渠道) = Σ该渠道信用消费 − Σ该渠道还款
  净资产    = 可用余额 − 欠款合计

欠款渠道清单存 settings.ledger.debt_channels（页面可增删），默认见 DEFAULT_DEBT_CHANNELS。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, vault
from ..auth import get_current
from ..db import db
from .settings import _load as _load_settings

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

SETTING_DEBT_CHANNELS = "ledger.debt_channels"
DEFAULT_DEBT_CHANNELS = ("花呗", "京东白条", "美团月付", "抖音月付", "微信分付", "信用卡", "拼多多先用后付")
KINDS = ("income", "expense", "repay")
MAX_CHANNELS = 50


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cents(yuan: float) -> int:
    """元 → 分：走 Decimal 十进制定点 + 四舍五入。

    不能用 int(round(yuan*100))：float 表示误差 + Python 银行家舍入会让
    int(round(8.615*100)) == 861（少 1 分）、int(round(1.005*100)) == 100。
    """
    return int((Decimal(str(yuan)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _clean_channels(items) -> list[str]:
    """渠道名清洗：去空白、截 30 字、去重、限量。非列表/异常输入 → 空列表。"""
    out: list[str] = []
    if not isinstance(items, (list, tuple)):
        return out
    for x in items:
        s = str(x).strip()[:30]
        if s and s not in out:
            out.append(s)
        if len(out) >= MAX_CHANNELS:
            break
    return out


def debt_channels() -> list[str]:
    """欠款渠道清单：settings.ledger.debt_channels；未设置过用默认清单。

    注意：用户显式存了空列表 [] 时返回空（视为"没有欠款渠道"，全部支出按现金算），
    不会回退到默认值——否则用户没法把默认清单清空。
    """
    cfg = _load_settings()
    raw = cfg.get(SETTING_DEBT_CHANNELS)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = None
    if not isinstance(raw, (list, tuple)):
        return list(DEFAULT_DEBT_CHANNELS)
    return _clean_channels(raw)


def _is_debt_category(cat: str, channels: list[str]) -> bool:
    c = (cat or "").strip()
    return bool(c) and c in channels


def _row(r, channels: list[str] | None = None) -> dict:
    fen = r["amount"]
    cat = r["category"]
    is_debt = _is_debt_category(cat, channels if channels is not None else debt_channels())
    return {"id": r["id"], "date": r["date"], "kind": r["kind"],
            "amount": fen, "amount_yuan": round(fen / 100, 2),
            "category": cat, "note": r["note"], "created": r["created"],
            # is_debt：命中欠款渠道的信用消费；channel：对应渠道名（非欠款为空串）
            "is_debt": is_debt, "channel": cat if is_debt else ""}


def _archive_rows(rows: list[dict], scope: dict) -> Path:
    """清空前留档：把待删行整体写成 JSON（原子写 + 0600）。

    存 DATA_DIR 根下与 site.db 同级：随 deploy/backup.sh 一起被加密备份带走。
    文件名 ledger_cleared_<时间戳>.json；同秒重复清空时追加序号，绝不覆盖。
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.DATA_DIR / f"ledger_cleared_{ts}.json"
    n = 1
    while path.exists():
        n += 1
        path = config.DATA_DIR / f"ledger_cleared_{ts}-{n}.json"
    payload = {
        "exported_at": _now(),
        "reason": "ledger clear",
        "scope": scope,
        # 存档当时的欠款渠道清单：日后回看才知道哪些行算欠款
        "debt_channels": debt_channels(),
        "count": len(rows),
        "total_amount_yuan": round(sum(r["amount"] for r in rows) / 100, 2),
        "restore_hint": ("恢复：把 items 逐行 INSERT 回 ledger(id,date,kind,amount,"
                         "category,note,created)，amount 单位是分。"
                         "kind='repay' 是还款记录；分类命中 debt_channels 的 expense 是信用消费。"),
        "items": rows,
    }
    vault.atomic_write_bytes(
        path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def _start_balance() -> float:
    cfg = _load_settings()
    try:
        return float(cfg.get("ledger.start_balance", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _month_prefix(month: str) -> str:
    return month + "-"


def _check_month(month: str) -> str:
    """校验 YYYY-MM：形状之外还要是真月份（旧实现放行 2026-13）。"""
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month 应为 YYYY-MM")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "无效月份")
    return month


def _check_date(date: str) -> str:
    if not DATE_RE.match(date):
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "无效日期")
    return date


def _shift_month(ym: str, delta: int) -> str:
    """按自然月平移，纯整数运算。

    不能用 (day1 - timedelta(days=i*31))：31 天一步会踩过 30 天的月份——
    实测从 2026-10 往前算 6 个月得到 04/05/06/07/08/10，9 月被整月跳过。
    """
    y, mo = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (mo - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


class LedgerIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    kind: str = "expense"
    amount: float = Field(gt=0, le=1_000_000_000)
    category: str = Field(default="", max_length=30)
    note: str = Field(default="", max_length=300)


def _validate(body: LedgerIn, channels: list[str]) -> None:
    if body.kind not in KINDS:
        raise HTTPException(400, "kind 只能是 income / expense / repay")
    _check_date(body.date)
    if body.kind == "repay":
        # 还款必须落在渠道清单内，否则这条记录既减不了欠款、语义也说不清
        ch = body.category.strip()[:30]
        if not ch:
            raise HTTPException(400, "还款需要指定欠款渠道")
        if ch not in channels:
            raise HTTPException(400, f"「{ch}」不在欠款渠道清单里，请先到「管理渠道」添加")


@router.get("")
def list_ledger(month: str | None = None, kind: str | None = None,
                q: str | None = None, channel: str | None = None,
                _user: dict = Depends(get_current)):
    """明细列表。kind=debt 是虚拟类型：欠款渠道的信用消费 + 还款记录。"""
    channels = debt_channels()
    sql = "SELECT * FROM ledger WHERE 1=1"
    args: list = []
    if month:
        sql += " AND date LIKE ?"
        args.append(_month_prefix(_check_month(month)) + "%")
    if kind == "debt":
        conds = ["kind='repay'"]
        if channels:
            marks = ",".join("?" * len(channels))
            conds.append(f"(kind='expense' AND category IN ({marks}))")
            args += channels
        sql += " AND (" + " OR ".join(conds) + ")"
    elif kind in KINDS:
        sql += " AND kind=?"
        args.append(kind)
    elif kind:
        raise HTTPException(400, "kind 只能是 income / expense / repay / debt")
    if channel and channel.strip():
        sql += " AND category=?"
        args.append(channel.strip()[:30])
    if q and q.strip():
        sql += " AND (category LIKE ? OR note LIKE ?)"
        like = f"%{q.strip()}%"
        args += [like, like]
    sql += " ORDER BY date DESC, id DESC"
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"items": [_row(r, channels) for r in rows], "debt_channels": channels}


@router.post("", status_code=201)
def create_ledger(body: LedgerIn, _user: dict = Depends(get_current)):
    channels = debt_channels()
    _validate(body, channels)
    cents = _cents(body.amount)
    if cents <= 0:
        raise HTTPException(400, "金额需大于 0")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) VALUES(?,?,?,?,?,?)",
            (body.date, body.kind, cents, body.category.strip()[:30], body.note.strip()[:300], _now()),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row, channels)


@router.put("/{ledger_id}")
def update_ledger(ledger_id: int, body: LedgerIn, _user: dict = Depends(get_current)):
    channels = debt_channels()
    _validate(body, channels)
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
    return _row(row, channels)


def _channel_owed_cents(channel: str) -> int:
    """某渠道当前欠款（分）= 该渠道信用消费 − 该渠道还款（可为负=多还了）。"""
    with db() as conn:
        r = conn.execute(
            "SELECT (SELECT COALESCE(SUM(amount),0) FROM ledger WHERE kind='expense' AND category=?)"
            " - (SELECT COALESCE(SUM(amount),0) FROM ledger WHERE kind='repay' AND category=?) AS o",
            (channel, channel)).fetchone()
    return int(r["o"] or 0)


class RepayIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    channel: str = Field(min_length=1, max_length=30)
    amount: float = Field(gt=0, le=1_000_000_000)
    note: str = Field(default="", max_length=300)


@router.post("/debt/repay", status_code=201)
def repay_debt(body: RepayIn, _user: dict = Depends(get_current)):
    """记一笔还款：写一条 kind='repay' 记录，冲减该渠道欠款并减少现金余额。

    多还（超过当前欠款）不拦截——可能是提前还款/记错，前端会提示"已还清/多还"。
    """
    channels = debt_channels()
    ch = body.channel.strip()[:30]
    if ch not in channels:
        raise HTTPException(400, f"「{ch}」不在欠款渠道清单里，请先到「管理渠道」添加")
    _check_date(body.date)
    cents = _cents(body.amount)
    if cents <= 0:
        raise HTTPException(400, "金额需大于 0")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) VALUES(?,?,?,?,?,?)",
            (body.date, "repay", cents, ch, body.note.strip()[:300], _now()),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id=?", (cur.lastrowid,)).fetchone()
    owed = round(_channel_owed_cents(ch) / 100, 2)
    return {"ok": True, "row": _row(row, channels), "channel": ch,
            "owed": owed, "overpaid": owed < 0}


class ChannelsIn(BaseModel):
    channels: list[str] = Field(default_factory=list)


@router.get("/debt/channels")
def get_debt_channels(_user: dict = Depends(get_current)):
    """读欠款渠道清单；顺带给出记账里实际出现过的分类，方便一键补进清单。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) c FROM ledger WHERE category<>'' "
            "GROUP BY category ORDER BY c DESC, category LIMIT 60").fetchall()
    return {"channels": debt_channels(), "defaults": list(DEFAULT_DEBT_CHANNELS),
            "used_categories": [r["category"] for r in rows]}


@router.put("/debt/channels")
def put_debt_channels(body: ChannelsIn, _user: dict = Depends(get_current)):
    """覆盖保存渠道清单（存 settings，不改动任何历史记录）。

    从清单里删掉的渠道，其支出会自动重新算作普通现金支出（记录本身不动）。
    """
    channels = _clean_channels(body.channels)
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SETTING_DEBT_CHANNELS, json.dumps(channels, ensure_ascii=False)))
    return {"channels": channels}


@router.delete("/clear")
def clear_ledger(month: str | None = None, kind: str | None = None, yes: bool = False,
                 _user: dict = Depends(get_current)):
    """批量清空（危险操作）。可选 month / kind 限定范围（kind=debt 只清欠款相关记录）。

    两道闸：必须显式 yes=true；删除前先把待删行导出 JSON 存档
    （DATA_DIR/ledger_cleared_<时间戳>.json，0600），清空永远可回溯。
    注意：本路由必须声明在 /{ledger_id} 之前，否则 DELETE /clear 会被
    路径参数路由吃掉（int 解析失败 → 422）。
    """
    if not yes:
        raise HTTPException(400, "清空需显式确认（yes=true），此操作会删除记录")
    channels = debt_channels()
    sql = "SELECT * FROM ledger WHERE 1=1"
    args: list = []
    scope: dict = {"month": None, "kind": None}
    if month:
        sql += " AND date LIKE ?"
        args.append(_month_prefix(_check_month(month)) + "%")
        scope["month"] = month
    if kind:
        if kind == "debt":
            conds = ["kind='repay'"]
            if channels:
                marks = ",".join("?" * len(channels))
                conds.append(f"(kind='expense' AND category IN ({marks}))")
                args += channels
            sql += " AND (" + " OR ".join(conds) + ")"
        elif kind in KINDS:
            sql += " AND kind=?"
            args.append(kind)
        else:
            raise HTTPException(400, "kind 只能是 income / expense / repay / debt")
        scope["kind"] = kind
    sql += " ORDER BY date, id"
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    if not rows:
        return {"deleted": 0, "backup": None, "deleted_amount_yuan": 0.0}
    backup = _archive_rows(rows, scope)
    marks = ",".join("?" * len(rows))
    with db() as conn:
        cur = conn.execute(f"DELETE FROM ledger WHERE id IN ({marks})", [r["id"] for r in rows])
    return {"deleted": cur.rowcount, "backup": str(backup),
            "deleted_amount_yuan": round(sum(r["amount"] for r in rows) / 100, 2)}


@router.delete("/{ledger_id}")
def delete_ledger(ledger_id: int, _user: dict = Depends(get_current)):
    with db() as conn:
        cur = conn.execute("DELETE FROM ledger WHERE id=?", (ledger_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.get("/stats")
def ledger_stats(month: str | None = None, _user: dict = Depends(get_current)):
    """可用余额 / 欠款（按渠道）/ 本月收支 / 去向（分类·渠道）/ 近 6 个月趋势。

    口径：现金支出与"支出去向"都**排除**欠款渠道——那些是信用消费，只进欠款。
    """
    m = month or datetime.now().strftime("%Y-%m")
    _check_month(m)
    prefix = _month_prefix(m)
    channels = debt_channels()
    marks = ",".join("?" * len(channels))

    def q(where: str, args: list, like: str | None = None) -> tuple[int, int]:
        sql = f"SELECT SUM(amount) s, COUNT(*) c FROM ledger WHERE ({where})"
        a = list(args)
        if like:
            sql += " AND date LIKE ?"
            a.append(like + "%")
        with db() as conn:
            r = conn.execute(sql, a).fetchone()
        return (r["s"] or 0, r["c"] or 0)

    def grouped(kind: str, like: str | None = None) -> dict[str, tuple[int, int]]:
        sql = "SELECT category k, SUM(amount) s, COUNT(*) c FROM ledger WHERE kind=?"
        a: list = [kind]
        if like:
            sql += " AND date LIKE ?"
            a.append(like + "%")
        sql += " GROUP BY category"
        with db() as conn:
            rows = conn.execute(sql, a).fetchall()
        return {r["k"]: (r["s"] or 0, r["c"] or 0) for r in rows}

    exp_all, rep_all = grouped("expense"), grouped("repay")
    exp_m, rep_m = grouped("expense", prefix), grouped("repay", prefix)

    # 现金支出 = 分类不在渠道清单里的支出；清单为空时所有支出都算现金支出
    if channels:
        cash_pred, cash_args = f"kind='expense' AND category NOT IN ({marks})", list(channels)
        debt_pred, debt_args = f"kind='expense' AND category IN ({marks})", list(channels)
    else:
        cash_pred, cash_args = "kind='expense'", []
        debt_pred, debt_args = "1=0", []
    # 还款一律算现金流出（渠道被删掉的历史还款既不能白记，也不能凭空消失）
    repay_pred, repay_args = "kind='repay'", []

    all_inc, _ = q("kind='income'", [])
    all_cash, _ = q(cash_pred, cash_args)
    all_debt, _ = q(debt_pred, debt_args)
    all_repay, _ = q(repay_pred, repay_args)
    m_inc, m_inc_c = q("kind='income'", [], prefix)
    m_cash, m_cash_c = q(cash_pred, cash_args, prefix)
    m_debt, m_debt_c = q(debt_pred, debt_args, prefix)
    m_repay, m_repay_c = q(repay_pred, repay_args, prefix)

    ch_stat: list[dict] = []
    spent_total = repaid_total = m_spent_total = m_repaid_total = 0
    for c in channels:
        s, n = exp_all.get(c, (0, 0))
        p, _ = rep_all.get(c, (0, 0))
        ms, mn = exp_m.get(c, (0, 0))
        mp, _ = rep_m.get(c, (0, 0))
        spent_total += s
        repaid_total += p
        m_spent_total += ms
        m_repaid_total += mp
        ch_stat.append({
            "channel": c,
            "spent": round(s / 100, 2), "repaid": round(p / 100, 2),
            "owed": round((s - p) / 100, 2), "count": n,
            "month_spent": round(ms / 100, 2), "month_repaid": round(mp / 100, 2),
            "month_count": mn,
        })
    owed_cents = spent_total - repaid_total

    def by_cat(kind: str, like: str) -> list[dict]:
        sql = ("SELECT category, SUM(amount) s, COUNT(*) c FROM ledger "
               "WHERE kind=? AND date LIKE ? AND category<>''")
        args: list = [kind, like + "%"]
        if kind == "expense" and channels:
            sql += f" AND category NOT IN ({marks})"
            args += channels
        sql += " GROUP BY category ORDER BY s DESC"
        with db() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = [{"category": r["category"], "amount": round(r["s"] / 100, 2), "count": r["c"]} for r in rows]
        # 无分类归入"其他"
        sql0 = "SELECT SUM(amount) s, COUNT(*) c FROM ledger WHERE kind=? AND date LIKE ? AND category=''"
        with db() as conn:
            r0 = conn.execute(sql0, (kind, like + "%")).fetchone()
        if r0 and r0["s"]:
            out.append({"category": "（未分类）", "amount": round(r0["s"] / 100, 2), "count": r0["c"]})
        return out

    debt_by_channel = [{"channel": x["channel"], "amount": x["month_spent"], "count": x["month_count"],
                        "repaid": x["month_repaid"]}
                       for x in ch_stat if x["month_spent"] or x["month_repaid"]]

    # 近 6 个月趋势：以"正在看的这个月"为基准往前数 6 个自然月
    #（页面本身是月份作用域的：翻到 9 月就该看到 4–9 月的趋势）
    trend = []
    for i in range(5, -1, -1):
        ym = _shift_month(m, -i)
        inc, _ = q("kind='income'", [], ym + "-")
        cash, _ = q(cash_pred, cash_args, ym + "-")
        debt, _ = q(debt_pred, debt_args, ym + "-")
        rep, _ = q(repay_pred, repay_args, ym + "-")
        trend.append({"month": ym, "income": round(inc / 100, 2), "expense": round(cash / 100, 2),
                      "debt_expense": round(debt / 100, 2), "repay": round(rep / 100, 2)})

    start = _start_balance()
    bal = start + (all_inc - all_cash - all_repay) / 100.0
    owed = owed_cents / 100.0
    return {
        "start_balance": round(start, 2),
        "balance": round(bal, 2),
        "net_worth": round(bal - owed, 2),
        "debt_channels": channels,
        "total": {"income": round(all_inc / 100, 2), "expense": round(all_cash / 100, 2),
                  "debt_expense": round(all_debt / 100, 2), "repay": round(all_repay / 100, 2)},
        "debt": {
            "owed_total": round(owed, 2),
            "spent_total": round(spent_total / 100, 2),
            "repaid_total": round(repaid_total / 100, 2),
            "month_spent": round(m_spent_total / 100, 2),
            "month_repaid": round(m_repaid_total / 100, 2),
            "channels": ch_stat,
        },
        "month": {
            "ym": m, "income": round(m_inc / 100, 2), "expense": round(m_cash / 100, 2),
            "debt_expense": round(m_debt / 100, 2), "repay": round(m_repay / 100, 2),
            "income_count": m_inc_c, "expense_count": m_cash_c,
            "debt_count": m_debt_c, "repay_count": m_repay_c,
            "expense_by_category": by_cat("expense", prefix),
            "income_by_category": by_cat("income", prefix),
            "debt_by_channel": debt_by_channel,
        },
        "trend": trend,
    }