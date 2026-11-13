"""日记今日足迹汇总接口测试套件。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient
from backend.tests.test_env import TestEnvironment
from app import config, db, vault
from app.db import init_db
from app.main import app

env = TestEnvironment(prefix="kruskal_test_diary_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_diary_footprint():
    headers = env.auth_headers()

    # 2. 测试空数据日期的足迹
    resp = client.get("/api/diary/footprint?date=2026-11-02", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["date"] == "2026-11-02"
    assert data["schedule"]["total"] == 0
    assert "今日暂无各模块动态记录" in data["template"]

    # 3. 准备测试数据
    test_date = "2026-11-02"
    with db.db() as conn:
        # 日程打卡
        conn.execute(
            "INSERT INTO schedule(date, kind, type, title, time_start, note, done, created_at) "
            "VALUES (?, 'daily', 'task', '重点实验室申报', '09:00', '', 1, '2026-11-02 09:00:00')",
            (test_date,)
        )
        conn.execute(
            "INSERT INTO schedule(date, kind, type, title, time_start, note, done, created_at) "
            "VALUES (?, 'daily', 'task', '算法复盘', '14:00', '', 1, '2026-11-02 14:00:00')",
            (test_date,)
        )
        conn.execute(
            "INSERT INTO schedule(date, kind, type, title, time_start, note, done, created_at) "
            "VALUES (?, 'daily', 'ddl', '提交阶段论文初稿', '18:00', '', 0, '2026-11-02 10:00:00')",
            (test_date,)
        )

        # 记账
        conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) "
            "VALUES (?, 'expense', 3000, '餐饮', '工作餐', '2026-11-02 12:30:00')",
            (test_date,)
        )
        conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) "
            "VALUES (?, 'expense', 1250, '交通', '地铁', '2026-11-02 18:30:00')",
            (test_date,)
        )

        # 助手记录
        conn.execute(
            "INSERT INTO assistant_records(title, kind, category, created_at, updated_at) "
            "VALUES ('研讨会材料准备', 'later', '事务', '2026-11-02 11:20:00', '2026-11-02 11:20:00')"
        )

        # 工作台小记
        conn.execute(
            "INSERT INTO workbench_items(id, title, created_at, updated_at) "
            "VALUES (101, '图神经网络研究', '2026-11-01 10:00:00', '2026-11-01 10:00:00')"
        )
        conn.execute(
            "INSERT INTO workbench_entries(item_id, created_at, updated_at) "
            "VALUES (101, '2026-11-02 15:30:00', '2026-11-02 15:30:00')"
        )

    # 4. 再次获取足迹
    resp = client.get(f"/api/diary/footprint?date={test_date}", headers=headers)
    assert resp.status_code == 200, resp.text
    fp = resp.json()

    assert fp["schedule"]["completed_count"] == 2
    assert fp["schedule"]["pending_count"] == 1
    assert "重点实验室申报" in fp["schedule"]["completed"]
    assert "算法复盘" in fp["schedule"]["completed"]
    assert "提交阶段论文初稿" in fp["schedule"]["pending"]

    assert fp["ledger"]["total_expense"] == 42.50
    assert fp["ledger"]["top_categories"][0]["category"] == "餐饮"
    assert fp["ledger"]["top_categories"][0]["amount"] == 30.00
    assert fp["ledger"]["top_categories"][1]["category"] == "交通"
    assert fp["ledger"]["top_categories"][1]["amount"] == 12.50

    assert fp["assistant_workbench"]["assistant_records_count"] == 1
    assert "研讨会材料准备" in fp["assistant_workbench"]["assistant_records"]
    assert fp["assistant_workbench"]["workbench_entries_count"] == 1

    template = fp["template"]
    # assert emoji and text
    assert "📅 **今日足迹自动汇总**" in template
    assert "完成 2 项（重点实验室申报、算法复盘）" in template
    assert "支出 ¥42.50（餐饮 ¥30，交通 ¥12.50）" in template
    assert "研讨会材料准备" in template
    assert "图神经网络研究" in template
    assert "### 💭 今日感想与复盘" in template

    # 5. 测试不带 date 参数（默认今天）与无效参数
    resp_def = client.get("/api/diary/footprint", headers=headers)
    assert resp_def.status_code == 200

    resp_bad = client.get("/api/diary/footprint?date=invalid-date", headers=headers)
    assert resp_bad.status_code == 400


if __name__ == "__main__":
    setup_module()
    try:
        test_diary_footprint()
    finally:
        teardown_module()
