"""Kruskal 智能助手全功能深度审计与可用性审查套件。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.tests.test_env import TestEnvironment
from app import vault

env = TestEnvironment(prefix="kruskal_audit_full_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_full_audit():
    print("\n" + "=" * 60)
    print("开始全面审查 Kruskal 智能助手所有功能与安全边界")
    print("=" * 60)

    # 1. 本机会话与数据密钥
    token = env.token
    assert token, "未能建立本机会话"
    headers = {"Authorization": f"Bearer {token}"}
    assert vault.has_dek(), "本机会话应已解锁数据密钥"
    print("[AUDIT 1/9] 本机会话与 DEK 内存解锁机制 -> 验证通过")

    # 2. 检查初始状态（无 mock 数据污染）
    r_list = client.get("/api/assistant/records?scope=all", headers=headers)
    assert r_list.status_code == 200
    assert len(r_list.json()["items"]) == 0, "发现残留数据"
    print("[AUDIT 2/9] 真实数据库初态审查（0 条记录，无任何 mock 假数据） -> 验证通过")

    # 3. 通知事项流：录入、提取、建档与日程单条 DDL 绑定
    n1 = (
        "【2026年高校重点实验室开放课题申报通知】\n"
        "各学院：2026年重点研究计划申报工作已启动，系统截止时间为2026-11-10 17:00。\n"
        "申报人需提交依托单位公章及2封专家推荐信。"
    )
    r1 = client.post("/api/assistant/submit", headers=headers, json={
        "text": n1,
        "mode": "notice",
        "source_url": "https://univ.edu.cn/notice/2026-01",
        "user_note": "帮我追踪截止时间和材料"
    })
    assert r1.status_code == 201
    rec1_id = r1.json()["id"]

    rec1 = client.get(f"/api/assistant/records/{rec1_id}", headers=headers).json()
    assert rec1["kind"] == "notice"
    assert rec1["thread"] is not None
    tid = rec1["thread"]["id"]
    assert rec1["thread"]["deadline_date"] == "2026-11-10"

    # 检查 schedule 表：严格只有 1 条 ddl，没有多余同名 task
    r_sched = client.get("/api/schedule/day?date=2026-11-10", headers=headers)
    items = r_sched.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "ddl"
    print("[AUDIT 3/9] 通知事项录入、要点提取与唯一 DDL 日程绑定（防虚增任务） -> 验证通过")

    # 4. 连续通知自动聚合与版本演化研判
    n2 = (
        "【2026年高校重点实验室开放课题申报延期通知】\n"
        "各学院：因申报系统维护，申报截止时间由11-10顺延至2026-11-20 18:00。\n"
        "特此补充说明。"
    )
    r2 = client.post("/api/assistant/submit", headers=headers, json={
        "text": n2,
        "mode": "notice",
        "user_note": "关注顺延"
    })
    assert r2.status_code == 201

    # 验证归并进同一 thread
    t_info = client.get(f"/api/assistant/threads/{tid}", headers=headers).json()
    assert t_info["deadline_date"] == "2026-11-20"
    assert len(t_info["sources"]) == 2
    # 验证旧日程清零，新日程迁移至 11-20
    assert len(client.get("/api/schedule/day?date=2026-11-10", headers=headers).json()["items"]) == 0
    assert len(client.get("/api/schedule/day?date=2026-11-20", headers=headers).json()["items"]) == 1
    print("[AUDIT 4/9] 连续通知自动聚合识别、时间轴演进与日程顺延同步 -> 验证通过")

    # 5. 用户在日程页手动修改后锁定防覆盖
    sched_id = client.get("/api/schedule/day?date=2026-11-20", headers=headers).json()["items"][0]["id"]
    client.put(f"/api/schedule/{sched_id}", headers=headers, json={
        "date": "2026-11-25",
        "kind": "daily",
        "type": "ddl",
        "title": "人工手动改期锁定",
        "time_start": "12:00",
        "note": "人工确认时间"
    })
    # 模拟导入再次推迟到 11-30 的第 3 封通知
    n3 = "【2026年高校重点实验室开放课题申报时间再调整】截止时间改为2026-11-30。"
    client.post("/api/assistant/submit", headers=headers, json={"text": n3, "mode": "notice"})
    # 验证用户的 11-25 未被覆盖
    sched_locked = client.get("/api/schedule/day?date=2026-11-25", headers=headers).json()["items"]
    assert len(sched_locked) == 1
    assert sched_locked[0]["title"] == "人工手动改期锁定"
    print("[AUDIT 5/9] 日程人工修改置锁防覆盖保护（locked_by_user 生效） -> 验证通过")

    # 6. 稍后看轻量卡片与临时论文即焚清理策略
    p_text = "Graph Transformer Attention Networks\n" + ("Transformer self-attention matrix layer..." * 200)
    r_p = client.post("/api/assistant/submit", headers=headers, json={
        "text": p_text,
        "mode": "later",
        "source_url": "https://arxiv.org/abs/2611.12345",
        "user_note": "关注图注意力机制"
    })
    assert r_p.status_code == 201
    p_id = r_p.json()["id"]

    rec_p = client.get(f"/api/assistant/records/{p_id}", headers=headers).json()
    assert rec_p["kind"] == "later"
    assert rec_p["card"] is not None
    # 验证论文即焚：raw_text 已被物理清空
    assert not rec_p["raw_text"]
    # 验证没有污染 papers 库
    papers = client.get("/api/papers", headers=headers).json().get("papers", [])
    assert len(papers) == 0
    print("[AUDIT 6/9] 稍后看轻量卡片提炼与临时长文即焚清理（绝不污染论文库） -> 验证通过")

    # 7. 一键写笔记联动与状态流转
    draft = client.get(f"/api/assistant/records/{p_id}/note-draft", headers=headers).json()
    assert "Graph Transformer" in draft["title"]
    r_note = client.post("/api/notes", headers=headers, json={
        "title": draft["title"],
        "content": draft["content"],
        "type": "blog",
        "source_record_id": p_id
    })
    assert r_note.status_code == 201
    # 验证状态变更为 noted
    assert client.get(f"/api/assistant/records/{p_id}", headers=headers).json()["read_state"] == "noted"
    print("[AUDIT 7/9] 一键写笔记、草稿预填与状态流转至 noted 双向映射 -> 验证通过")

    # 8. 有据问答检索
    chat_resp = client.post("/api/assistant/chat", headers=headers, json={
        "query": "重点实验室申报现在的截止时间是什么时候？"
    }).json()
    assert "2026-11-25" in chat_resp["answer"] or "2026-11-20" in chat_resp["answer"]
    print("[AUDIT 8/9] 助手事实库检索与有据问答接口响应 -> 验证通过")

    # 9. 数据密钥缺失时保护加密资源，恢复后继续可用
    saved_dek = vault.dek()
    vault.clear_dek()
    assert not vault.has_dek()
    assert client.get("/api/assets/scan", headers=headers).status_code == 423
    vault.set_dek(saved_dek)
    assert vault.has_dek()
    assert client.get("/api/assets/scan", headers=headers).status_code == 200
    print("[AUDIT 9/9] DEK 缺失时加密资源被拦截、恢复后可继续访问 -> 验证通过")

    print("\n" + "=" * 60)
    print("【审查结果】全部 9 大维度核心功能与安全边界 100% 审查通过！")
    print("=" * 60)


if __name__ == "__main__":
    setup_module()
    try:
        test_full_audit()
    finally:
        teardown_module()
