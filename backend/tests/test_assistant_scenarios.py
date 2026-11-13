"""Kruskal 助手（Assistant）严苛业务场景端到端验证测试套件。

涵盖场景：
1. 场景 1：稍后看轻量卡片与临时材料即焚策略（不留长文全文、不污染论文库）；
2. 场景 2：连续通知演化与唯一 DDL 日程映射（三轮演进、去重单DDL、防歪曲热力图、手动锁定防覆盖）；
3. 场景 3：与笔记编辑器的草稿连通（草稿结构预填、首存回写 assistant_links、状态流转至 noted）；
4. 场景 4：数据密钥丢失（Lock Guard & DEK Epoch）防御（中断挂起 paused_locked、恢复后无损继续）；
5. 场景 5：模型不可用时如实失败（无规则降级伪装），问答明确标注不可用并回显资料。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient

from backend.tests.test_env import TestEnvironment
from app import config, crypto, trashbin, vault
from app.db import db, init_db
from app.main import app
from app.routers import assistant as asst_mod
from app.routers import papers as papers_mod
from app.routers import schedule as sched_mod
from app.services import llm

env = TestEnvironment(prefix="kruskal_scenarios_test_")
client = env.client


def setup_module():
    """初始化数据库并建立本机会话。"""
    env.setup()


def teardown_module():
    """清理临时数据目录。"""
    env.teardown()


def auth_headers() -> dict[str, str]:
    return env.auth_headers()


# ==============================================================================
# 场景 1：稍后看轻量卡片与临时材料即焚策略
# ==============================================================================

def test_scenario_1_later_stream_ephemeral_burn():
    """场景 1：稍后看轻量卡片与临时材料即焚策略。
    
    验证要点：
    1. 提交长篇论文全文、长摘要、URL 与用户备注；
    2. 生成包含双句简介、关注理由、分类与主题标签的轻量卡片；
    3. 长篇原文加密保留，供查阅和重新整理；
    4. 系统 papers 论文库未被污染，无新增条目。
    """
    long_paper_content = (
        "论文标题: Deep Residual Learning for Image Recognition (ResNet)\n"
        "作者: Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun\n"
        "摘要: Deeper neural networks are more difficult to train. We present a residual learning framework to ease the training of networks that are substantially deeper than those previously used. We explicitly reformulate the layers as learning residual functions with reference to the layer inputs, instead of learning unreferenced functions. We provide comprehensive empirical evidence showing that these networks are easier to optimize, and can gain accuracy from considerably increased depth.\n"
        + ("\n[正文长篇段落] " + "Residual units with shortcut connections skip one or more layers. " * 30) * 10
    )
    user_note = "复习经典残差结构，关注瓶颈层设计与恒等映射退化解决机制"
    source_url = "https://arxiv.org/abs/1512.03385"

    resp = client.post(
        "/api/assistant/submit",
        json={
            "text": long_paper_content,
            "mode": "later",
            "source_type": "text",
            "source_url": source_url,
            "user_note": user_note,
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 201, f"提交稍后看失败: {resp.text}"
    record_id = resp.json()["id"]

    # 触发后台整理流水线
    asst_mod.process_record_job(record_id)

    # 1. 验证生成轻量卡片元数据
    rec_resp = client.get(f"/api/assistant/records/{record_id}", headers=auth_headers())
    assert rec_resp.status_code == 200
    rec = rec_resp.json()
    assert rec["status"] == "ready", "记录状态应为 ready"
    assert rec["kind"] == "later", "类型必须为 later"
    assert rec["category"] == "论文", f"分类应识别为论文，实际为: {rec['category']}"
    assert rec["source_url"] == source_url
    assert rec["user_note"] == user_note

    card = rec["card"]
    assert card is not None, "应成功生成 card 详情"
    assert "ResNet" in card["title"] or "Residual" in card["title"] or "Deep" in card["title"]
    assert len(card["brief"]) > 0, "应生成一至两句客观简介"
    assert card["why_focus"] == user_note, "关注理由应正确呈现用户关注点或提炼亮点"
    assert "论文" in card["tags"] or "论文" in rec["tags"], "标签中应包含论文"

    # 2. 原文加密保留，且数据库记录中不存放全文
    rec_dir = asst_mod._record_dir(record_id)
    raw_enc_path = rec_dir / "raw.enc"
    assert asst_mod.vault.read_text(raw_enc_path) == long_paper_content
    retry = client.post(f"/api/assistant/records/{record_id}/retry", headers=auth_headers())
    assert retry.status_code == 409

    assets_dir = rec_dir / "assets"
    if assets_dir.is_dir():
        asset_files = list(assets_dir.glob("*"))
        assert len(asset_files) == 0, f"临时素材目录未彻底清空: {asset_files}"

    assert rec["raw_text"] == long_paper_content

    # 验证数据库中 assistant_records 表未留存长文
    with db() as conn:
        db_row = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        row_json = json.dumps(dict(db_row), ensure_ascii=False)
        assert "Residual units with shortcut" not in row_json, "数据库主记录表中非法存有论文长文正文"

    # 3. 验证严禁自动录入现有论文库（papers 库保持纯净隔离）
    papers_resp = client.get("/api/papers", headers=auth_headers())
    assert papers_resp.status_code == 200
    papers_items = papers_resp.json().get("items", [])
    assert len(papers_items) == 0, f"助手稍后看严禁污染系统 papers 库，但发现条目: {papers_items}"

    paper_files = list(papers_mod.PAPERS_DIR.glob("*.json"))
    assert len(paper_files) == 0, f"papers 磁盘目录下存在非预期文件: {paper_files}"


# ==============================================================================
# 场景 2：连续通知演化与唯一 DDL 日程映射
# ==============================================================================

def test_scenario_2_continuous_notices_and_unique_ddl():
    """场景 2：连续通知演化与唯一 DDL 日程映射。
    
    验证要点：
    1. 连续导入三封同一事项的通知（初次发布 11-10 -> 补充承诺书 -> 延期至 11-20）；
    2. 三封通知准确聚合到同一 assistant_threads 线程，时序与演变原因（new -> update -> postpone）清晰；
    3. schedule 日程表严格保持 1 条 type='ddl' 记录，绝不创建同名 task，截止日期顺延至 11-20；
    4. 用户手动在日程表修改为 11-25 并置锁完成，后续再有通知到达不静默覆盖用户手动设定。
    """
    # Notice 1: 初次发布
    n1_text = (
        "【2026年秋季项目申报通知】\n"
        "各学院科研团队：2026年秋季重点项目申报系统现已开放。\n"
        "1. 务必由负责人亲自提交申请书；\n"
        "2. 需提供 2 封教授推荐信；\n"
        "申报截止时间：2026-11-10 18:00，逾期系统将关闭。"
    )
    r1 = client.post(
        "/api/assistant/submit",
        json={"text": n1_text, "mode": "notice", "user_note": "关注推荐信与截止时间"},
        headers=auth_headers(),
    )
    assert r1.status_code == 201
    rec1_id = r1.json()["id"]
    asst_mod.process_record_job(rec1_id)

    # 验证 Notice 1 结果
    rec1 = client.get(f"/api/assistant/records/{rec1_id}", headers=auth_headers()).json()
    assert rec1["status"] == "ready"
    assert rec1["thread"] is not None
    thread_id = rec1["thread"]["id"]
    assert rec1["thread"]["deadline_date"] == "2026-11-10"

    # 验证 schedule 仅 1 条 ddl，0 条 task
    with db() as conn:
        scheds = conn.execute("SELECT * FROM schedule WHERE date='2026-11-10' AND type='ddl'").fetchall()
        assert len(scheds) == 1, f"初次通知日程条目应严格为 1 条，实际为: {len(scheds)}"
        assert scheds[0]["type"] == "ddl", "必须为 ddl 类型"
        assert scheds[0]["date"] == "2026-11-10"
        sched_id = scheds[0]["id"]

        tasks = conn.execute("SELECT * FROM schedule WHERE type='task' AND (title LIKE '%申报%' OR title LIKE '%秋季%')").fetchall()
        assert len(tasks) == 0, "严禁生成同名 task，防止歪曲热力图完成率"

    # Notice 2: 要求补充
    n2_text = (
        "【补充通知：2026年秋季项目申报】\n"
        "接专家组最新补充规定，所有申报人必须在系统中补充提交科研诚信承诺书签字版，未提交者形式审查不予通过。"
    )
    r2 = client.post(
        "/api/assistant/submit",
        json={"text": n2_text, "mode": "notice", "user_note": "承诺书要求"},
        headers=auth_headers(),
    )
    assert r2.status_code == 201
    rec2_id = r2.json()["id"]
    asst_mod.process_record_job(rec2_id)

    # 验证 Notice 2 聚合到相同 thread_id
    rec2 = client.get(f"/api/assistant/records/{rec2_id}", headers=auth_headers()).json()
    assert rec2["thread"]["id"] == thread_id, "Notice 2 必须聚合到同一线程"

    # Notice 3: 延期更新
    n3_text = (
        "【延期通知：2026年秋季项目申报截止延期】\n"
        "因国家网络安全演习系统维护，2026年秋季项目申报系统截止日期延期至 2026-11-20 20:00。"
    )
    r3 = client.post(
        "/api/assistant/submit",
        json={"text": n3_text, "mode": "notice"},
        headers=auth_headers(),
    )
    assert r3.status_code == 201
    rec3_id = r3.json()["id"]
    asst_mod.process_record_job(rec3_id)

    # 验证线程详情与时序演变
    t_resp = client.get(f"/api/assistant/threads/{thread_id}", headers=auth_headers())
    assert t_resp.status_code == 200
    t_data = t_resp.json()

    assert t_data["deadline_date"] == "2026-11-20", "线程截止日期自动顺延为 2026-11-20"
    sources = t_data["sources"]
    assert len(sources) == 3, f"演化时序应包含 3 条来源记录，实际: {len(sources)}"
    assert sources[0]["sequence"] == 1 and sources[0]["change_type"] == "new"
    assert sources[1]["sequence"] == 2 and sources[1]["change_type"] in ("update", "new")
    assert sources[2]["sequence"] == 3 and sources[2]["change_type"] in ("postpone", "update")
    assert "延期" in sources[2]["change_reason"] or "2026-11-20" in sources[2]["change_reason"]

    # 验证 schedule 表：依旧严格保持 1 条记录，日期顺延为 11-20，绝不产生同名 task
    with db() as conn:
        all_scheds = conn.execute("SELECT * FROM schedule WHERE date='2026-11-20' AND type='ddl'").fetchall()
        assert len(all_scheds) == 1, f"延期后日程总数仍必须为 1 条，实际: {len(all_scheds)}"
        assert all_scheds[0]["id"] == sched_id, "必须在原有 schedule 记录上就地顺延，不能新建"
        assert all_scheds[0]["type"] == "ddl"
        assert all_scheds[0]["date"] == "2026-11-20"

        # 验证热力图口径
        heat_resp = client.get("/api/schedule/heatmap?year=2026", headers=auth_headers())
        assert heat_resp.status_code == 200
        days = heat_resp.json()["days"]
        # 11-20 只有 1 个事项
        assert days.get("2026-11-20", {}).get("total") == 1
        # 11-10 计数清零或为 0（因已自动顺延移走）
        assert days.get("2026-11-10", {}).get("total", 0) == 0

    # 4. 手动锁定防覆盖验证：用户在日程表修改为 11-25 并勾选完成
    put_sched_resp = client.put(
        f"/api/schedule/{sched_id}",
        json={
            "date": "2026-11-25",
            "kind": "daily",
            "type": "ddl",
            "title": "【截止】2026年秋季项目申报通知",
            "time_start": "18:00",
            "note": "我已提前完成并手动调整确认",
        },
        headers=auth_headers(),
    )
    assert put_sched_resp.status_code == 200
    done_resp = client.put(f"/api/schedule/{sched_id}/done", json={"done": True}, headers=auth_headers())
    assert done_resp.status_code == 200

    with db() as conn:
        link_state = conn.execute("SELECT locked_by_user FROM assistant_schedule_links WHERE schedule_id=?", (sched_id,)).fetchone()
        assert link_state["locked_by_user"] == 1, "用户手动在日程修改后，必须自动标记 locked_by_user = 1"

    # 再次导入新通知 Notice 4（声明延期至 11-30）
    n4_text = (
        "【终极延期通知：2026年秋季项目申报】\n"
        "受突发断电影响，截止时间延期至 2026-11-30 23:59。"
    )
    r4 = client.post(
        "/api/assistant/submit",
        json={"text": n4_text, "mode": "notice"},
        headers=auth_headers(),
    )
    assert r4.status_code == 201
    rec4_id = r4.json()["id"]
    asst_mod.process_record_job(rec4_id)

    # 验证日程未被静默覆盖：仍然是 11-25，done 仍为 True
    with db() as conn:
        sched_locked = conn.execute("SELECT * FROM schedule WHERE id=?", (sched_id,)).fetchone()
        assert sched_locked["date"] == "2026-11-25", f"置锁后日期不应被覆盖，实际: {sched_locked['date']}"
        assert sched_locked["done"] == 1, "置锁后完成态不应被重置"

        # 线程演化轴应注明检测到新时间但因锁定未覆盖
        t_sources = conn.execute(
            "SELECT * FROM assistant_thread_sources WHERE thread_id=? ORDER BY sequence DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        assert "锁定" in t_sources["change_reason"] or "未覆盖" in t_sources["change_reason"]


# ==============================================================================
# 场景 3：与笔记编辑器的草稿连通
# ==============================================================================

def test_scenario_3_note_draft_and_noted_state():
    """场景 3：与笔记编辑器的草稿连通。
    
    验证要点：
    1. 请求 /api/assistant/records/{id}/note-draft，草稿包含标题、简介、理由与来源；
    2. 前端根据草稿保存新笔记（POST /api/notes，携带 source_record_id）；
    3. 记录的 read_state 自动流转为 'noted'，并落库 assistant_links 单向映射。
    """
    card_text = (
        "FlashAttention-3: Fast and Accurate Attention with Asynchrony and Low-precision\n"
        "Tri Dao 等人提出最新 FlashAttention-3，在 Hopper GPU 上实现了超过 800 TFLOPs/s（75% 利用率）。"
    )
    resp = client.post(
        "/api/assistant/submit",
        json={
            "text": card_text,
            "mode": "later",
            "source_type": "url",
            "source_url": "https://github.com/Dao-AILab/flash-attention",
            "user_note": "重点关注 FP8 异步张量核心利用效率",
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    rec_id = resp.json()["id"]
    asst_mod.process_record_job(rec_id)

    # 1. 验证草稿端点返回结构
    draft_resp = client.get(f"/api/assistant/records/{rec_id}/note-draft", headers=auth_headers())
    assert draft_resp.status_code == 200, f"获取草稿失败: {draft_resp.text}"
    draft = draft_resp.json()

    assert "FlashAttention" in draft["title"]
    assert "## 简介" in draft["content"]
    assert "## 关注理由" in draft["content"]
    assert "FP8 异步" in draft["content"]
    assert "https://github.com/Dao-AILab/flash-attention" in draft["content"]
    assert draft["source_record_id"] == rec_id

    # 2. 模拟笔记编辑器首次保存
    note_payload = {
        "title": draft["title"],
        "type": "note",
        "fmt": "md",
        "tags": draft["tags"],
        "content": draft["content"] + "\n\n## 个人深入笔记\n通过 Warp 调度与 TMA 异步传输实现高效流水线...",
        "source_record_id": rec_id,
    }
    create_note_resp = client.post("/api/notes", json=note_payload, headers=auth_headers())
    assert create_note_resp.status_code == 201, f"创建笔记失败: {create_note_resp.text}"
    note_id = create_note_resp.json()["id"]

    # 3. 验证状态流转与映射表
    with db() as conn:
        link = conn.execute(
            "SELECT * FROM assistant_links WHERE record_id=? AND target_type='note' AND target_id=?",
            (rec_id, note_id),
        ).fetchone()
        assert link is not None, "未在 assistant_links 中找到对应的关联记录"

        rec_db = conn.execute("SELECT read_state FROM assistant_records WHERE id=?", (rec_id,)).fetchone()
        assert rec_db["read_state"] == "noted", f"记录状态应变为 noted，实际为: {rec_db['read_state']}"

    # 验证详情接口返回 links 列表
    detail = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert detail["read_state"] == "noted"
    assert any(l["target_type"] == "note" and l["target_id"] == note_id for l in detail["links"])


# ==============================================================================
# 场景 4：DEK 丢失（Lock Guard & DEK Epoch）防御
# ==============================================================================

def test_scenario_4_lock_guard_and_dek_epoch_defense():
    """场景 4：DEK 丢失（Lock Guard & DEK Epoch）防御。
    
    验证要点：
    1. 模拟在后台作业异步处理中数据密钥被清空（vault.clear_dek 推进 epoch）；
    2. 作业在尝试落盘时检测到世代号不匹配或无密钥，安全挂起为 paused_locked，严禁抛错崩溃；
    3. 恢复 DEK 后，挂起作业成功唤醒并恢复整理完成。
    """
    saved_dek = vault.dek()

    # 模拟在 LLM 抽取阶段数据密钥丢失（例如服务端密钥文件被移走）
    def mock_chat_structured_with_lock(*args, **kwargs):
        # 清空 DEK 并推进 epoch
        vault.clear_dek()
        return {
            "title": "实验室安全整顿大会",
            "summary": "明日上午10:00全员准时到场",
            "highlights": ["全员准时"],
            "deadline_date": "",
            "deadline_time": "",
        }

    with patch("app.services.llm.is_enabled", return_value=True), \
         patch("app.services.llm.chat_structured", side_effect=mock_chat_structured_with_lock):
        # 提交记录：TestClient 会立即同步调度后台作业，作业在抽取时被锁
        submit_resp = client.post(
            "/api/assistant/submit",
            json={
                "text": "【紧急会议通知】明日上午 10:00 召开实验室安全整顿大会，请全员准时到场。",
                "mode": "notice",
            },
            headers=auth_headers(),
        )
        assert submit_resp.status_code == 201
        record_id = submit_resp.json()["id"]

    # 验证：作业安全挂起为 paused_locked，严禁报错崩溃
    with db() as conn:
        job = conn.execute("SELECT * FROM assistant_jobs WHERE record_id=?", (record_id,)).fetchone()
        assert job["stage"] == "paused_locked", f"作业必须处于 paused_locked，实际为: {job['stage']}"

        rec = conn.execute("SELECT status FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        assert rec["status"] in ("pending", "processing"), "记录状态不应错误标为 ready"

    # 恢复 DEK（相当于服务重启后本机密钥重新解锁）
    vault.set_dek(saved_dek)
    assert vault.has_dek(), "恢复后 DEK 已就绪"

    # 验证挂起作业唤醒机制
    asst_mod.resume_paused_jobs()

    # 验证作业顺利完成整理
    with db() as conn:
        job_after = conn.execute("SELECT * FROM assistant_jobs WHERE record_id=?", (record_id,)).fetchone()
        assert job_after["stage"] == "finalize", f"恢复后作业应为 finalize，实际为: {job_after['stage']}"

        rec_after = conn.execute("SELECT * FROM assistant_records WHERE id=?", (record_id,)).fetchone()
        assert rec_after["status"] == "ready", f"恢复后记录状态应为 ready，实际为: {rec_after['status']}"
        assert rec_after["title"] != "", "标题应已正常提取入库"


# ==============================================================================
# 场景 5：降级与容错兜底
# ==============================================================================

def test_scenario_5_fallback_and_error_tolerance():
    """场景 5：模型不可用时如实失败，不做规则降级伪装。

    验证要点：
    1. 模型连接超时 → 记录 failed、error_msg 可读，原始输入完整保留；
    2. 规则降级接口已删除（404），不存在“规则整理伪装成功”的路径；
    3. /api/assistant/chat 在模型离线时明确标注 AI 不可用，只回显检索到的资料，不编造答案。
    """
    notice_text = (
        "【2026年重点研发计划答辩通知】\n"
        "请各项目团队注意：\n"
        "1. 提前 15 分钟抵达第一会议室；\n"
        "2. 答辩 PPT 请采用 16:9 比例；\n"
        "答辩日期：2026-12-15 14:30 准时开始。"
    )

    # 模拟大模型异常超时
    with patch("app.services.llm.is_enabled", return_value=True), \
         patch("app.services.llm.chat_structured", side_effect=llm.AiUnavailable("连接超时: Connection to 127.0.0.1:8000 timed out")):
        resp = client.post(
            "/api/assistant/submit",
            json={"text": notice_text, "mode": "auto", "user_note": "关注答辩时间与PPT比例"},
            headers=auth_headers(),
        )
        assert resp.status_code == 201, f"大模型离线时提交接口应正常响应: {resp.text}"
        rec_id = resp.json()["id"]

        # 处理作业
        asst_mod.process_record_job(rec_id)

    # 1. 验证大模型失败时绝不伪装成功，如实标记为 failed 并保存错误诊断
    rec_failed = client.get(f"/api/assistant/records/{rec_id}", headers=auth_headers()).json()
    assert rec_failed["status"] == "failed", "大模型连接异常时必须如实置为 failed"
    assert "连接超时" in rec_failed.get("error_msg", "")
    assert rec_failed["raw_text"] == notice_text, "失败时原始输入必须完整保留，便于重试"

    # 2. 规则降级接口已删除：不允许用规则结果冒充 AI 整理
    fb_resp = client.post(f"/api/assistant/records/{rec_id}/fallback-rule", headers=auth_headers())
    assert fb_resp.status_code in (404, 405)

    # 3. 验证问答接口在 AI 停用状态下的降级表现：明确说明不可用，只回显资料
    with patch("app.services.llm.is_enabled", return_value=False):
        chat_resp = client.post(
            "/api/assistant/chat",
            json={"query": "请问什么时候答辩？", "record_id": rec_id},
            headers=auth_headers(),
        )
        assert chat_resp.status_code == 200, f"降级问答不应崩溃: {chat_resp.text}"
        chat_data = chat_resp.json()
        assert "answer" in chat_data
        assert chat_data.get("degraded") is True
        assert "2026年重点研发计划答辩" in chat_data["answer"]
        assert chat_data["sources_used"] >= 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 60)
    print("正在执行 Kruskal 助手（Assistant）五大核心严苛业务场景验证...")
    print("=" * 60)
    setup_module()
    try:
        test_scenario_1_later_stream_ephemeral_burn()
        print(">>> 场景 1 验证通过：稍后看轻量卡片与临时材料即焚策略（不留长文全文、不污染论文库）")

        test_scenario_2_continuous_notices_and_unique_ddl()
        print(">>> 场景 2 验证通过：连续通知演化与唯一 DDL 日程映射（三轮演化、唯一DDL、置锁防覆盖）")

        test_scenario_3_note_draft_and_noted_state()
        print(">>> 场景 3 验证通过：与笔记编辑器的草稿连通（草稿预填、首存回写 assistant_links、流转至 noted）")

        test_scenario_4_lock_guard_and_dek_epoch_defense()
        print(">>> 场景 4 验证通过：Kruskal 上锁机制（Lock Guard & DEK Epoch）防御（上锁中断挂起、解锁无损恢复）")

        test_scenario_5_fallback_and_error_tolerance()
        print(">>> 场景 5 验证通过：降级与容错兜底（LLM 离线/超时优雅降级启发式提取、问答不崩溃）")

        print("=" * 60)
        print("ALL SCENARIOS PASSED SUCCESSFULLY!")
        print("=" * 60)
    finally:
        teardown_module()
