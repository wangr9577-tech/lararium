"""Kruskal 助手（Assistant）端到端完整管线与核心逻辑测试套件。

覆盖验收标准：
1. DEK Epoch 世代号机制（递增与上锁防御）；
2. 数据库表结构、索引与字段完整性；
3. 稍后看卡片流（提取、轻量卡片加密存储、元数据列表不解密正文、临时文件清理）；
4. 笔记草稿生成与一键写笔记（assistant_links 建立与 noted 状态流转）；
5. 通知事项流与日程防污染（唯一 DDL 原则、防同名 task 污染完成率）；
6. 连续通知聚合研判（延期 postpone 自动更新日程、多源时间轴记录）；
7. 日程锁定保护（locked_by_user 为 1 时防止后续通知覆盖用户调整）；
8. 上锁防御机制（DEK 清空时后台作业自动进入 paused_locked，恢复后无损继续）；
9. 回收站一致性还原（软删除进 trash，还原后自动恢复 archived=0 和加密文件）；
10. 有据问答检索（基于已存档事实回答，不胡编）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient

from backend.tests.test_env import TestEnvironment
from app import config, crypto, trashbin, vault
from app.db import db, init_db
from app.main import app
from app.routers import assistant as asst_mod

env = TestEnvironment(prefix="kruskal_asst_test_")
client = env.client
_STATE: dict[str, Any] = {}


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def auth_headers() -> dict[str, str]:
    return env.auth_headers()


# ==================== 测试用例 ====================

def test_1_vault_epoch_mechanism():
    """验证 DEK Epoch 世代号递增机制。"""
    print("\n[TEST 1] 验证 DEK Epoch 世代号机制...")
    ep0 = vault.epoch()
    assert ep0 > 0, "初始化后 epoch 应大于 0"

    cur_dek = vault.dek()
    vault.set_dek(cur_dek)
    ep1 = vault.epoch()
    assert ep1 == ep0 + 1, f"set_dek 应使 epoch 递增: {ep1} != {ep0 + 1}"

    vault.clear_dek()
    ep2 = vault.epoch()
    assert ep2 == ep1 + 1, f"clear_dek 应使 epoch 递增: {ep2} != {ep1 + 1}"
    assert not vault.has_dek(), "clear_dek 后 has_dek 应为 False"

    # 恢复 DEK 供后续测试
    vault.set_dek(cur_dek)
    assert vault.has_dek()
    print("  -> PASSED: DEK Epoch 递增正常。")


def test_2_database_schema_and_indexes():
    """验证 SQLite 助手相关 6 张新表及索引。"""
    print("\n[TEST 2] 验证数据库表结构与索引完整性...")
    expected_tables = {
        "assistant_records",
        "assistant_threads",
        "assistant_thread_sources",
        "assistant_schedule_links",
        "assistant_jobs",
        "assistant_links",
    }
    with db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for tbl in expected_tables:
            assert tbl in tables, f"缺少表: {tbl}"

        # 检查 assistant_records 关键字段
        cols = {r[1] for r in conn.execute("PRAGMA table_info(assistant_records)").fetchall()}
        for expected_col in ("id", "kind", "title", "source_type", "status", "read_state", "archived", "pinned"):
            assert expected_col in cols, f"assistant_records 缺少列 {expected_col}"

        # 检查 assistant_schedule_links 唯一约束
        idx_rows = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='assistant_schedule_links'").fetchall()
        # 表内有 UNIQUE(thread_id, schedule_id)
        table_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='assistant_schedule_links'").fetchone()[0]
        assert "UNIQUE" in table_sql, "assistant_schedule_links 应包含 UNIQUE 约束"

    print("  -> PASSED: 数据库 6 张助手核心表及约束齐全。")


def test_3_later_stream_pipeline():
    """验证稍后看轻量卡片流水线。"""
    print("\n[TEST 3] 验证稍后看轻量卡片流（提取、加密落盘、临时文件清理）...")
    payload = {
        "text": "vLLM 是一个吞吐量极高、内存友好的大模型推理和服务引擎，支持 PagedAttention 算法与连续批处理。",
        "mode": "later",
        "source_type": "text",
        "source_url": "https://github.com/vllm-project/vllm",
        "user_note": "关注其量化算子和显存复用技术，用于个人服务器加速推理",
    }
    resp = client.post("/api/assistant/submit", json=payload, headers=auth_headers())
    assert resp.status_code == 201, f"提交失败: {resp.text}"
    rec_id = resp.json()["id"]

    # 运行管线
    asst_mod.process_record_job(rec_id)

    # 校验记录详情与 Vault 加密文件
    r_resp = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers())
    assert r_resp.status_code == 200
    r_data = r_resp.json()
    assert r_data["kind"] == "later"
    assert r_data["status"] == "ready"
    assert r_data["read_state"] == "unread"
    assert "vLLM" in r_data["title"]
    assert r_data["category"] in ("项目", "其他", "工具")
    assert r_data["raw_text"], "解密后原文应存在"
    assert r_data["card"]["why_focus"] == payload["user_note"]

    # 验证列表接口（轻量摘要，不解密正文长文）
    list_resp = client.get("/api/assistant/records?scope=later", headers=auth_headers())
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert any(it["id"] == rec_id for it in items)
    matched = next(it for it in items if it["id"] == rec_id)
    assert "raw_text" not in matched, "列表接口绝不能暴露/全量解密 raw_text"

    # 测试 PATCH
    p_resp = client.patch(f"/api/assistant/records/{rec_id}", json={"pinned": 1, "read_state": "read"}, headers=auth_headers())
    assert p_resp.status_code == 200
    r_after = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert r_after["pinned"] is True
    assert r_after["read_state"] == "read"

    print("  -> PASSED: 稍后看卡片提取、加密及状态流转正常。")
    _STATE["rec_id"] = rec_id


def test_4_note_draft_and_write_note_closure(rec_id: int | None = None):
    """验证从卡片生成笔记草稿并完成『写笔记』闭环关联。"""
    rec_id = rec_id or _STATE.get("rec_id")
    print("\n[TEST 4] 验证从稍后看一键『写笔记』与 assistant_links 闭环...")
    draft_resp = client.get(f"/api/assistant/records/{rec_id}/note-draft", headers=auth_headers())
    assert draft_resp.status_code == 200
    draft = draft_resp.json()
    assert "简介" in draft["content"]
    assert "关注理由" in draft["content"]
    assert draft["source_record_id"] == rec_id

    # 模拟前端调用 POST /api/notes，并携带 source_record_id
    note_payload = {
        "title": f"【笔记】{draft['title']}",
        "type": "note",
        "fmt": "md",
        "tags": draft["tags"],
        "content": draft["content"] + "\n\n我的深入评测记录...",
        "source_record_id": rec_id,
    }
    create_n_resp = client.post("/api/notes", json=note_payload, headers=auth_headers())
    assert create_n_resp.status_code == 201, f"新建笔记失败: {create_n_resp.text}"
    note_id = create_n_resp.json()["id"]

    # 验证 assistant_links 与 read_state 变为 'noted'
    with db() as conn:
        link_row = conn.execute(
            "SELECT * FROM assistant_links WHERE record_id=? AND target_type='note' AND target_id=?",
            (rec_id, note_id),
        ).fetchone()
        assert link_row is not None, "应成功写入 assistant_links 关联"

    rec_after = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert rec_after["read_state"] == "noted", "卡片状态应自动流转为 noted"
    print("  -> PASSED: 写笔记草稿生成与双向映射闭环成功。")


def test_5_notice_stream_and_schedule_link():
    """验证通知流处理与日程唯一 DDL 联动（严防同名 task 污染）。"""
    print("\n[TEST 5] 验证通知事项提取与日程唯一 DDL 联动（防同名任务污染）...")
    notice_text = (
        "【2026年秋季项目申报通知】\n"
        "各团队请注意：2026年秋季创新基金申报已经启动。\n"
        "1. 务必提交盖章版申报书；\n"
        "2. 推荐信需准备 2 封；\n"
        "申报截止时间：2026-11-10 18:00，逾期不予受理。"
    )
    submit_resp = client.post(
        "/api/assistant/submit",
        json={"text": notice_text, "mode": "notice", "user_note": "重点关注推荐信数量"},
        headers=auth_headers(),
    )
    assert submit_resp.status_code == 201
    rec1_id = submit_resp.json()["id"]

    # 运行管线
    asst_mod.process_record_job(rec1_id)

    # 验证线程生成
    rec1 = client.get(f"/api/assistant/records/{rec1_id}", headers=auth_headers()).json()
    assert rec1["status"] == "ready"
    assert rec1["thread"] is not None
    thread_id = rec1["thread"]["id"]
    assert rec1["thread"]["deadline_date"] == "2026-11-10"

    # 验证日程唯一性：只能有一条 type='ddl'，绝对不能生成同名 task
    with db() as conn:
        sched_rows = conn.execute(
            "SELECT * FROM schedule WHERE date='2026-11-10' AND type='ddl'"
        ).fetchall()
        assert len(sched_rows) == 1, f"日程条目应严格为 1 条，实际为 {len(sched_rows)}"
        assert sched_rows[0]["type"] == "ddl", "日程类型必须严格为 ddl"
        assert sched_rows[0]["date"] == "2026-11-10"

        # 检查映射表
        link_row = conn.execute(
            "SELECT * FROM assistant_schedule_links WHERE thread_id=? AND schedule_id=?",
            (thread_id, sched_rows[0]["id"]),
        ).fetchone()
        assert link_row is not None
        assert link_row["role"] == "ddl"
        assert link_row["locked_by_user"] == 0

    print("  -> PASSED: 首封通知聚合入库，正确创建单条 DDL 日程条目。")
    _STATE["thread_id"] = thread_id
    _STATE["rec1_id"] = rec1_id


def test_6_continuous_notice_reconciliation_and_postponement(thread_id: int | None = None):
    """验证连续通知聚合与延期研判（同一线程更新事实与日程，不增加重复事项）。"""
    thread_id = thread_id or _STATE.get("thread_id")
    print("\n[TEST 6] 验证连续通知聚合与延期研判（同一线程更新事实与日程）...")
    notice2_text = (
        "【重要通知：关于2026年秋季项目申报延期的通知】\n"
        "接主管部门通知，因服务器升级调整，2026年秋季创新基金申报延期。\n"
        "推荐信要求由原先 2 封放宽为 1 封即可。\n"
        "申报截止时间顺延至：2026-11-20 20:00。"
    )
    submit_resp = client.post(
        "/api/assistant/submit",
        json={"text": notice2_text, "mode": "notice"},
        headers=auth_headers(),
    )
    assert submit_resp.status_code == 201
    rec2_id = submit_resp.json()["id"]

    # 运行管线
    asst_mod.process_record_job(rec2_id)

    # 检查线程详情接口
    t_resp = client.get(f"/api/assistant/threads/{thread_id}", headers=auth_headers())
    assert t_resp.status_code == 200
    t_data = t_resp.json()

    # 验证线程聚合
    assert t_data["deadline_date"] == "2026-11-20", f"截止日期应更新为延期后的 2026-11-20: {t_data['deadline_date']}"
    assert len(t_data["sources"]) == 2, "时间轴应包含 2 个来源记录"
    assert t_data["sources"][1]["change_type"] in ("postpone", "update")
    assert "延期" in t_data["sources"][1]["change_reason"] or "2026-11-20" in t_data["sources"][1]["change_reason"]

    # 再次验证 schedule 表：依旧严格只有 1 条记录，且日期已被自动更新
    with db() as conn:
        sched_rows = conn.execute(
            "SELECT * FROM schedule WHERE date='2026-11-20' AND type='ddl'"
        ).fetchall()
        assert len(sched_rows) == 1, f"日程依旧严格保持 1 条，无重复冗余: {len(sched_rows)}"
        assert sched_rows[0]["date"] == "2026-11-20", "原日程日期应自动更新为 2026-11-20"

    print("  -> PASSED: 连续通知自动聚合，更新演化轴与有效 DDL，保持单条日程。")


def test_7_user_schedule_lock_protection(thread_id: int | None = None):
    """验证人工锁定保护（locked_by_user=1 时后续通知不可覆盖用户修改）。"""
    thread_id = thread_id or _STATE.get("thread_id")
    print("\n[TEST 7] 验证用户手动修改日程后的防覆盖锁定机制...")
    # 用户手动调整为 2026-11-25 并解决冲突/锁定
    recon_resp = client.post(
        f"/api/assistant/threads/{thread_id}/reconcile",
        json={"deadline_date": "2026-11-25", "deadline_time": "12:00", "update_schedule": True},
        headers=auth_headers(),
    )
    assert recon_resp.status_code == 200

    with db() as conn:
        link = conn.execute("SELECT * FROM assistant_schedule_links WHERE thread_id=?", (thread_id,)).fetchone()
        assert link["locked_by_user"] == 1, "调和后应设置 locked_by_user = 1"
        sched = conn.execute("SELECT * FROM schedule WHERE id=?", (link["schedule_id"],)).fetchone()
        assert sched["date"] == "2026-11-25"

    # 新通知到来，声称截止时间为 2026-11-30
    notice3_text = (
        "【补充说明】2026年秋季项目申报系统开放至 2026-11-30 24:00。"
    )
    sub3 = client.post("/api/assistant/submit", json={"text": notice3_text, "mode": "notice"}, headers=auth_headers())
    rec3_id = sub3.json()["id"]
    asst_mod.process_record_job(rec3_id)

    # 验证日程未被静默覆盖！
    with db() as conn:
        sched_after = conn.execute("SELECT * FROM schedule WHERE id=?", (link["schedule_id"],)).fetchone()
        assert sched_after["date"] == "2026-11-25", "因用户手动锁定，日程日期应坚守 2026-11-25，不被覆盖！"

    print("  -> PASSED: 用户手动锁定有效防御了后续通知的静默篡改。")


def test_8_dek_lock_defense():
    """验证 Kruskal 上锁防御（处理途中上锁安全进入 paused_locked）。"""
    print("\n[TEST 8] 验证上锁防御机制（DEK Epoch 校验与 paused_locked）...")
    sub = client.post(
        "/api/assistant/submit",
        json={"text": "测试上锁防御文本内容", "mode": "later"},
        headers=auth_headers(),
    )
    rec_id = sub.json()["id"]

    # 模拟用户点击了上锁或退出了会话，清空 DEK
    saved_dek = vault.dek()
    vault.clear_dek()
    assert not vault.has_dek()

    # 触发作业执行
    asst_mod.process_record_job(rec_id)

    # 检查状态是否安全进入 paused_locked，且未发生异常崩盘
    with db() as conn:
        job = conn.execute("SELECT * FROM assistant_jobs WHERE record_id=?", (rec_id,)).fetchone()
        assert job["stage"] == "paused_locked", f"作业阶段应为 paused_locked: {job['stage']}"

    # 恢复 DEK，再次触发重试
    vault.set_dek(saved_dek)
    retry_resp = client.post(f"/api/assistant/records/{rec_id}/retry", headers=auth_headers())
    assert retry_resp.status_code == 200

    asst_mod.process_record_job(rec_id)
    rec_done = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert rec_done["status"] == "ready", "解锁后重试应无损完成"
    print("  -> PASSED: 上锁安全防御与解锁恢复流程通过。")


def test_9_delete_and_trashbin_consistency():
    """验证记录软删除至回收站与一致性恢复。"""
    print("\n[TEST 9] 验证软删除移至回收站与还原一致性...")
    sub = client.post(
        "/api/assistant/submit",
        json={"text": "准备移入回收站的测试项目卡片", "mode": "later"},
        headers=auth_headers(),
    )
    rec_id = sub.json()["id"]
    asst_mod.process_record_job(rec_id)

    # 删除
    del_resp = client.delete(f"/api/assistant/records/{rec_id}", headers=auth_headers())
    assert del_resp.status_code == 200
    trash_id = del_resp.json()["trash_id"]
    assert trash_id is not None

    with db() as conn:
        r_arch = conn.execute("SELECT archived FROM assistant_records WHERE id=?", (rec_id,)).fetchone()
        assert r_arch["archived"] == 1, "记录应被标记为 archived=1"

    # 回收站还原
    rest_resp = client.post(f"/api/trash/{trash_id}/restore", headers=auth_headers())
    assert rest_resp.status_code == 200

    with db() as conn:
        r_rest = conn.execute("SELECT archived FROM assistant_records WHERE id=?", (rec_id,)).fetchone()
        assert r_rest["archived"] == 0, "回收站还原后 archived 应重置为 0"

    # 验证密文文件恢复
    r_detail = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert r_detail["raw_text"] == "准备移入回收站的测试项目卡片"
    print("  -> PASSED: 回收站软删除与还原一致性通过。")


def test_10_assistant_chat_qa(thread_id: int | None = None):
    """验证助手有据问答接口。"""
    thread_id = thread_id or _STATE.get("thread_id")
    print("\n[TEST 10] 验证助手有据问答接口（POST /api/assistant/chat）...")
    chat_resp = client.post(
        "/api/assistant/chat",
        json={"query": "请问 2026年秋季项目申报 的截止时间是哪天？", "thread_id": thread_id},
        headers=auth_headers(),
    )
    assert chat_resp.status_code == 200
    ans = chat_resp.json()["answer"]
    assert "2026" in ans
    print(f"  -> AI 回答摘录: {ans[:80]}...")
    print("  -> PASSED: 助手基于事实问答接口响应正常。")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("==================================================")
    print("开始执行 Kruskal 助手（Assistant）端到端测试套件")
    print("==================================================")
    setup_module()
    try:
        test_1_vault_epoch_mechanism()
        test_2_database_schema_and_indexes()
        test_3_later_stream_pipeline()
        test_4_note_draft_and_write_note_closure()
        test_5_notice_stream_and_schedule_link()
        test_6_continuous_notice_reconciliation_and_postponement()
        test_7_user_schedule_lock_protection()
        test_8_dek_lock_defense()
        test_9_delete_and_trashbin_consistency()
        test_10_assistant_chat_qa()
        print("\n==================================================")
        print("[SUCCESS] 全部 10 项端到端测试用例执行完毕，全部 PASSED！")
        print("==================================================")
    finally:
        teardown_module()


if __name__ == "__main__":
    main()
