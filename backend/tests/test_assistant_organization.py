"""Regression tests for assistant classification, structured output and grouped notices."""
from unittest.mock import patch
import json

from backend.tests.test_env import TestEnvironment
from app.db import db
from app.services import llm

env = TestEnvironment(prefix="kruskal_organization_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def candidate_named(messages, title):
    content = messages[0]["content"]
    candidates = json.loads(content.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
    match = next((item for item in candidates if item["title"] == title), None)
    return {"same_event": bool(match), "thread_id": match["id"] if match else None}


def test_structured_output_retry_preserves_original_message():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "请分类"}, image]}]
    with patch.object(llm, "chat", side_effect=["<think>思考中</think>", '说明： {"kind":"later"}']) as chat:
        assert llm.chat_structured(messages) == {"kind": "later"}
    assert chat.call_count == 2
    assert image in chat.call_args.args[0][1]["content"]


def test_possible_candidate_is_rechecked_by_model():
    from app.routers.assistant import _choose_candidate
    replies = [
        {"same_event": False, "thread_id": None, "possible_thread_id": 7},
        {"same_event": True, "thread_id": 7, "possible_thread_id": None},
    ]
    with patch.object(llm, "chat_structured", side_effect=replies) as model:
        result = _choose_candidate([{"id": 7, "title": "记录"}], "待分析内容")
    assert result["same_event"] is True and result["thread_id"] == 7
    assert model.call_count == 2


def test_negative_candidate_is_rechecked_without_code_deciding():
    from app.routers.assistant import _choose_candidate
    replies = [
        {"same_event": False, "thread_id": None, "possible_thread_id": None},
        {"same_event": True, "thread_id": 12, "possible_thread_id": None},
    ]
    with patch.object(llm, "chat_structured", side_effect=replies) as model:
        result = _choose_candidate([{"id": 12, "title": "来源"}], "待分析内容")
    assert result["thread_id"] == 12 and model.call_count == 2


def test_negative_candidate_is_not_forced_to_merge():
    from app.routers.assistant import _choose_candidate
    reply = {"same_event": False, "thread_id": None, "possible_thread_id": None}
    with patch.object(llm, "chat_structured", return_value=reply) as model:
        result = _choose_candidate([{"id": 12, "title": "来源"}], "待分析内容")
    assert result["same_event"] is False and model.call_count == 2


def test_automatic_classification_and_notice_cards():
    def model(messages, system_prompt="", **kwargs):
        if "信息分流器" in system_prompt:
            text = str(messages)
            return {"kind": "later" if "论文" in text else "notice", "reason": "测试"}
        if "事务性通知信息提取专家" in system_prompt:
            return {"title": "会议报名", "summary": "准备报名材料", "highlights": ["填写表格"],
                    "deadline_date": "", "deadline_time": "", "event_keywords": ["会议报名"]}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "change_reason": "补充表格",
                    "summary": "准备报名材料并填写表格", "highlights": ["填写表格"],
                    "deadline_date": "", "deadline_time": ""}
        if "知识整理助手" in system_prompt:
            return {"title": "会议中的多智能体论文", "brief": "研究多智能体。", "category": "论文", "tags": ["多智能体"]}
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None} if "论文" in str(messages) else candidate_named(messages, "会议报名")
        raise AssertionError(system_prompt)

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = []
        for text in ("会议报名通知：准备材料", "会议报名通知：补充填写表格", "论文：会议中的多智能体研究"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "auto"}, headers=env.auth_headers())
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        notice = client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()
        assert notice["total"] == 1
        assert len(notice["items"]) == 1
        assert "填写表格" in notice["items"][0]["summary"]
        detail = client.get(f"/api/assistant/records/{ids[2]}", headers=env.auth_headers()).json()
        assert detail["kind"] == "later"
        thread_id = notice["items"][0]["thread"]["id"]
        thread = client.get(f"/api/assistant/threads/{thread_id}", headers=env.auth_headers()).json()
        assert len(thread["sources"]) == 2
        assert client.patch(f"/api/assistant/records/{ids[1]}", json={"archived": 1}, headers=env.auth_headers()).status_code == 200
        assert client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["total"] == 0
        assert client.patch(f"/api/assistant/records/{ids[1]}", json={"archived": 0}, headers=env.auth_headers()).status_code == 200
        assert client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["total"] == 1


def test_screenshot_transcription_is_available_to_automatic_classifier():
    seen = []
    def model(messages, system_prompt="", **kwargs):
        if "附件文字识别助手" in system_prompt:
            assert any(part.get("type") == "image_url" for part in messages[0]["content"])
            return {"text": "截图中的项目介绍"}
        if "信息分流器" in system_prompt:
            seen.append(messages)
            return {"kind": "later"}
        return {"title": "截图中的项目", "brief": "一个项目简介。", "category": "项目", "tags": []}
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        resp = client.post("/api/assistant/submit", data={"mode": "auto"},
                           files={"file": ("screen.png", b"fake-image", "image/png")}, headers=env.auth_headers())
    assert resp.status_code == 201
    assert seen and "截图中的项目介绍" in seen[0][0]["content"]


def test_old_notice_cannot_silently_move_deadline():
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            date = "2026-11-15" if "旧通知" in str(messages) else "2026-11-20"
            return {"title": "独立项目材料截止测试", "summary": "提交材料", "highlights": [],
                    "deadline_date": date, "deadline_time": "", "event_keywords": []}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "提交材料",
                    "deadline_date": "2026-11-15", "deadline_time": ""}
        if "判断新通知是否" in system_prompt:
            return candidate_named(messages, "独立项目材料截止测试")
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        for text in ("独立项目通知：截止2026年11月20日", "独立项目旧通知：截止2026年11月15日"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers())
            assert resp.status_code == 201
        detail = client.get(f"/api/assistant/records/{resp.json()['id']}", headers=env.auth_headers()).json()
        assert detail["thread"]["deadline_date"] == "2026-11-20"
        assert detail["thread"]["has_conflict"]


def test_deadline_update_uses_model_evidence_not_keyword_list():
    text = "新的有效期限为2026-12-22，原期限作废。"
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            new = text in str(messages)
            return {"title": "测试资料提交", "summary": "提交资料", "deadline_date": "2026-12-22" if new else "2026-12-15"}
        if "判断新通知是否" in system_prompt:
            return candidate_named(messages, "测试资料提交")
        if "通知版本研判" in system_prompt:
            return {"change_type": "update", "summary": "提交资料", "deadline_date": "2026-12-22",
                    "deadline_relation": "same_task_change", "deadline_change_quote": text}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        for raw in ("测试资料提交，2026-12-15截止。", text):
            response = client.post("/api/assistant/submit", json={"text": raw, "mode": "notice"}, headers=env.auth_headers())
        detail = client.get(f"/api/assistant/records/{response.json()['id']}", headers=env.auth_headers()).json()
    assert detail["thread"]["deadline_date"] == "2026-12-22"


def test_different_titles_can_match_same_notice_thread():
    import json
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            title = "开题报告安排" if "第一次" in str(messages) else "研究计划材料补充"
            return {"title": title, "summary": "同一研究计划", "highlights": [],
                    "deadline_date": "", "deadline_time": "", "event_keywords": []}
        if "判断新通知是否" in system_prompt:
            text = messages[0]["content"]
            candidates = json.loads(text.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
            match = next((c for c in candidates if c["title"] == "开题报告安排"), None)
            return {"same_event": bool(match), "thread_id": match["id"] if match else None}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "开题报告及材料补充",
                    "deadline_date": "", "deadline_time": ""}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = []
        for text in ("第一次：研究计划开题报告", "第二次：研究计划需要补充材料"):
            resp = client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers())
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        first = client.get(f"/api/assistant/records/{ids[0]}", headers=env.auth_headers()).json()
        second = client.get(f"/api/assistant/records/{ids[1]}", headers=env.auth_headers()).json()
        assert first["thread"]["id"] == second["thread"]["id"]


def test_notice_preserves_tasks_and_source_when_split():
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            second = "推荐信" in str(messages)
            title = "提交推荐信" if second else "提交申请表"
            quote = title + ("，截止2026-11-15。" if second else "，截止2026-11-10。")
            return {"title": "测试项目任务", "summary": title, "highlights": [],
                    "tasks": [{"title": title, "deadline_date": "2026-11-15" if second else "2026-11-10",
                               "deadline_time": "", "kind": "deadline", "quote": quote}]}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "提交申请表和推荐信"}
        if "判断新通知是否" in system_prompt:
            return candidate_named(messages, "测试项目任务")
        raise AssertionError(system_prompt)

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        first = client.post("/api/assistant/submit", json={"text": "提交申请表，截止2026-11-10。", "mode": "notice"}, headers=env.auth_headers()).json()
        second = client.post("/api/assistant/submit", json={"text": "提交推荐信，截止2026-11-15。", "mode": "notice"}, headers=env.auth_headers()).json()
    detail = client.get(f"/api/assistant/records/{second['id']}", headers=env.auth_headers()).json()
    thread = detail["thread"]
    assert [(t["title"], t["deadline_date"]) for t in thread["tasks"]] == [
        ("提交申请表", "2026-11-10"), ("提交推荐信", "2026-11-15")]
    assert thread["tasks"][0]["source_record_ids"] == [first["id"]]
    assert thread["tasks"][1]["quote"] == "提交推荐信，截止2026-11-15。"
    rows = client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["items"]
    messages = next(row for row in rows if row["id"] == second["id"])["thread"]["source_messages"]
    assert [message["record_id"] for message in messages] == [first["id"], second["id"]]
    assert messages[0]["summary"] == "提交申请表"
    assert messages[1]["summary"] == "提交推荐信"
    assert messages[1]["evidence_quotes"] == ["提交推荐信，截止2026-11-15。"]
    result = client.post(f"/api/assistant/threads/{thread['id']}/split-source", json={"record_id": second["id"]}, headers=env.auth_headers())
    assert result.status_code == 200
    original = client.get(f"/api/assistant/records/{first['id']}", headers=env.auth_headers()).json()
    separated = client.get(f"/api/assistant/records/{second['id']}", headers=env.auth_headers()).json()
    assert [t["title"] for t in original["thread"]["tasks"]] == ["提交申请表"]
    assert [t["title"] for t in separated["thread"]["tasks"]] == ["提交推荐信"]


def test_legacy_merged_summary_is_not_presented_as_one_source():
    from app import vault
    from app.routers.assistant import _record_dir
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            return {"title": "示例资料", "summary": "原始摘要", "highlights": []}
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None}
        if "只根据当前提供的一段信息" in system_prompt:
            return {"summary": "本段的独立整理。"}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        record_id = client.post("/api/assistant/submit", json={"text": "本段的原始内容。", "mode": "notice"}, headers=env.auth_headers()).json()["id"]
        path = _record_dir(record_id) / "card.enc"
        card = vault.read_json(path)
        card.pop("source_summary", None)
        card["summary"] = "包括其他来源的合并摘要"
        card["change_type"] = "update"
        vault.write_json(path, card)
        rows = client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["items"]
        message = next(row for row in rows if row["id"] == record_id)["thread"]["source_messages"][0]
        assert message["needs_summary"] is True and not message["summary"]
        assert client.post(f"/api/assistant/records/{record_id}/source-summary", headers=env.auth_headers()).status_code == 200
        rows = client.get("/api/assistant/records?scope=notice", headers=env.auth_headers()).json()["items"]
        message = next(row for row in rows if row["id"] == record_id)["thread"]["source_messages"][0]
        assert message["summary"] == "本段的独立整理。" and message["needs_summary"] is False
        assert client.patch(f"/api/assistant/records/{record_id}", json={"archived": 1}, headers=env.auth_headers()).status_code == 200


def test_manual_merge_undo_and_task_schedule_edit():
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            is_b = "乙项目" in str(messages)
            title = "乙项目" if is_b else "甲项目"
            date = "2026-12-12" if is_b else "2026-12-10"
            return {"title": title, "summary": title, "highlights": [], "deadline_date": date,
                    "tasks": [{"title": "提交" + title, "deadline_date": date, "deadline_time": "", "kind": "deadline"}]}
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": False, "change_type": "new"}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = [client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers()).json()["id"]
               for text in ("甲项目提交截止2026-12-10", "乙项目提交截止2026-12-12")]
    details = [client.get(f"/api/assistant/records/{i}", headers=env.auth_headers()).json() for i in ids]
    target, source = (d["thread"]["id"] for d in details)
    assert target != source
    response = client.post(f"/api/assistant/threads/{target}/merge", json={"source_thread_id": source}, headers=env.auth_headers())
    assert response.status_code == 200, response.text
    merge_id = response.json()["merge_id"]
    detail = client.get(f"/api/assistant/records/{ids[0]}", headers=env.auth_headers()).json()
    assert len(detail["thread"]["tasks"]) == 2
    task = detail["thread"]["tasks"][0]
    response = client.patch(f"/api/assistant/threads/{target}/tasks/{task['id']}", json={"done": True, "deadline_date": "2026-12-11"}, headers=env.auth_headers())
    assert response.status_code == 200, response.text
    with db() as conn:
        row = conn.execute("SELECT s.* FROM schedule s JOIN assistant_schedule_links sl ON sl.schedule_id=s.id WHERE sl.task_id=?", (task["id"],)).fetchone()
        assert row["done"] == 1 and row["date"] == "2026-12-11"
    response = client.post(f"/api/assistant/merges/{merge_id}/undo", headers=env.auth_headers())
    assert response.status_code == 200, response.text
    details = [client.get(f"/api/assistant/records/{i}", headers=env.auth_headers()).json() for i in ids]
    assert [d["thread"]["id"] for d in details] == [target, source]
    assert details[0]["thread"]["tasks"][0]["done"] is True


def test_historical_task_extraction_is_idempotent_and_respects_dismissal():
    def model(messages, system_prompt="", **kwargs):
        if "事务性通知信息提取专家" in system_prompt:
            result = {"title": "历史材料事项", "summary": "提交表格", "highlights": [], "deadline_date": "2026-12-20"}
            if "历史通知提取待办" in str(messages):
                result["tasks"] = [{"title": "提交表格", "deadline_date": "2026-12-20", "deadline_time": "", "quote": "提交表格。"}]
            return result
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": False, "change_type": "new"}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        rec_id = client.post("/api/assistant/submit", json={"text": "历史材料事项：提交表格。截止2026-12-20", "mode": "notice"}, headers=env.auth_headers()).json()["id"]
        detail = client.get(f"/api/assistant/records/{rec_id}", headers=env.auth_headers()).json()
        thread_id = detail["thread"]["id"]
        response = client.post(f"/api/assistant/threads/{thread_id}/extract-missing-tasks", headers=env.auth_headers())
        assert response.status_code == 200 and response.json()["processed"] == 1
        task = client.get(f"/api/assistant/records/{rec_id}", headers=env.auth_headers()).json()["thread"]["tasks"][0]
        with db() as conn:
            links = conn.execute("SELECT * FROM assistant_schedule_links WHERE thread_id=?", (thread_id,)).fetchall()
            assert len(links) == 1 and links[0]["task_id"] == task["id"]
            schedule_id = links[0]["schedule_id"]
        assert client.delete(f"/api/schedule/{schedule_id}", headers=env.auth_headers()).status_code == 200
        response = client.patch(f"/api/assistant/threads/{thread_id}/tasks/{task['id']}", json={"done": True}, headers=env.auth_headers())
        assert response.status_code == 200
        with db() as conn:
            link = conn.execute("SELECT * FROM assistant_schedule_links WHERE thread_id=? AND task_id=?", (thread_id, task["id"])).fetchone()
            assert link["user_dismissed"] == 1 and link["schedule_id"] is None
        assert client.post(f"/api/assistant/threads/{thread_id}/extract-missing-tasks", headers=env.auth_headers()).json()["processed"] == 0


def test_rejected_title_candidate_falls_back_to_other_thread():
    import json
    def model(messages, system_prompt="", **kwargs):
        text = str(messages)
        if "事务性通知信息提取专家" in system_prompt:
            title = "星河项目报名" if "第一条" in text or "第三条" in text else "星河计划材料"
            return {"title": title, "summary": "不同批次材料", "highlights": [], "event_keywords": []}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": "既有事实】标题: 星河计划材料" in text and "第三条" in text,
                    "change_type": "update", "summary": "材料补充"}
        if "判断新通知是否" in system_prompt:
            content = messages[0]["content"]
            candidates = json.loads(content.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
            match = next((c for c in candidates if c["title"] == "星河计划材料"), None) if "第三条" in content else None
            return {"same_event": bool(match), "thread_id": match["id"] if match else None}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = [client.post("/api/assistant/submit", json={"text": text, "mode": "notice"}, headers=env.auth_headers()).json()["id"]
               for text in ("第一条：星河项目报名甲批", "第二条：星河计划材料乙批", "第三条：星河计划乙批补充")]
    details = [client.get(f"/api/assistant/records/{i}", headers=env.auth_headers()).json() for i in ids]
    assert details[0]["thread"]["id"] != details[1]["thread"]["id"]
    assert details[2]["thread"]["id"] == details[1]["thread"]["id"]


def test_same_task_different_dates_are_flagged():
    from app.routers.assistant import _combine_source_tasks
    tasks = _combine_source_tasks([
        {"id": "a", "title": "提交申请表", "deadline_date": "2026-11-10", "deadline_time": "", "source_record_ids": [1]},
        {"id": "b", "title": "提交申请表", "deadline_date": "2026-11-20", "deadline_time": "", "source_record_ids": [2]},
        {"id": "c", "title": "上传推荐信", "deadline_date": "2026-11-15", "deadline_time": "", "source_record_ids": [2]},
    ])
    assert [task["date_conflict"] for task in tasks] == [True, True, False]


def test_later_classification_can_join_existing_exam_with_model_confirmation():
    import json
    def model(messages, system_prompt="", **kwargs):
        text = str(messages)
        if "信息分流器" in system_prompt:
            return {"kind": "later" if "题型" in text else "notice"}
        if "判断新通知是否" in system_prompt:
            content = messages[0]["content"]
            candidates = json.loads(content.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
            match = next((c for c in candidates if c["title"] == "概率统计期中考试"), None)
            return {"same_event": bool(match), "thread_id": match["id"] if match else None}
        if "事务性通知信息提取专家" in system_prompt:
            return {"title": "概率统计期中考试题型" if "题型" in text else "概率统计期中考试", "summary": "考试说明", "highlights": []}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": True, "change_type": "update", "summary": "考试时间和题型"}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = [client.post("/api/assistant/submit", json={"text": text, "mode": "auto"}, headers=env.auth_headers()).json()["id"]
               for text in ("概率统计期中考试：11月5日考试。", "概率统计期中考试：题型与作业类似。")]
    records = [client.get(f"/api/assistant/records/{i}", headers=env.auth_headers()).json() for i in ids]
    assert records[1]["kind"] == "notice"
    assert records[0]["thread"]["id"] == records[1]["thread"]["id"]


def test_manual_merge_legacy_later_and_undo_restores_kind():
    """旧版稍后看遗留线程可以并入通知，撤销时恢复原分类。"""
    from app.routers.assistant import merge_threads, undo_manual_merge, MergeThreadIn, now_iso, _thread_dir
    from app import vault
    with db() as conn:
        ids = []
        for kind in ("notice", "later"):
            t = conn.execute("INSERT INTO assistant_threads(title,created_at,updated_at) VALUES(?,?,?)", ("测试事项" + kind, now_iso(), now_iso())).lastrowid
            r = conn.execute("INSERT INTO assistant_records(kind,title,created_at,updated_at) VALUES(?,?,?,?)", (kind, "测试记录" + kind, now_iso(), now_iso())).lastrowid
            conn.execute("INSERT INTO assistant_thread_sources(thread_id,record_id,received_at,created_at) VALUES(?,?,?,?)", (t, r, now_iso(), now_iso()))
            ids.append((t, r))
    for thread_id, _ in ids:
        directory = _thread_dir(thread_id)
        directory.mkdir(parents=True, exist_ok=True)
        vault.write_json(directory / "facts.enc", {"summary": "测试", "tasks": []})
    result = merge_threads(ids[0][0], MergeThreadIn(source_thread_id=ids[1][0]), _user={})
    with db() as conn:
        assert conn.execute("SELECT kind FROM assistant_records WHERE id=?", (ids[1][1],)).fetchone()["kind"] == "notice"
    undo_manual_merge(result["merge_id"], _user={})
    with db() as conn:
        assert conn.execute("SELECT kind FROM assistant_records WHERE id=?", (ids[1][1],)).fetchone()["kind"] == "later"
    detail = client.get(f"/api/assistant/records/{ids[1][1]}", headers=env.auth_headers()).json()
    assert detail["thread"] is None


def test_earlier_auto_later_supplement_joins_later_notice():
    import json
    def model(messages, system_prompt="", **kwargs):
        text = str(messages)
        if "信息分流器" in system_prompt:
            return {"kind": "later" if "题型" in text else "notice"}
        if "知识整理助手" in system_prompt:
            return {"title": "计量经济学期末考试题型", "brief": "计算题型说明"}
        if "事务性通知信息提取专家" in system_prompt:
            return {"title": "计量经济学期末考试", "summary": "考试安排", "highlights": []}
        if "判断新通知是否" in system_prompt:
            content = messages[0]["content"]
            candidates = json.loads(content.split("候选事项：", 1)[1].split("\n新通知：", 1)[0])
            match = next((c for c in candidates if "计量经济学期末考试" in c["title"]), None)
            return {"same_event": bool(match), "thread_id": match["id"] if match else None}
        if "通知版本研判" in system_prompt:
            return {"is_same_event": False, "change_type": "new"}
        raise AssertionError(system_prompt)
    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        ids = [client.post("/api/assistant/submit", json={"text": text, "mode": "auto"}, headers=env.auth_headers()).json()["id"]
               for text in ("计量经济学期末考试题型包括计算题。", "计量经济学期末考试：12月5日举行。")]
    records = [client.get(f"/api/assistant/records/{i}", headers=env.auth_headers()).json() for i in ids]
    assert records[0]["kind"] == "notice"
    assert records[0]["thread"]["id"] == records[1]["thread"]["id"]


def test_auto_later_never_creates_ddl_even_if_model_returns_a_date():
    """auto 分流为 later 后：只用 LATER_PROMPT 抽卡，且绝不为知识资料创建 DDL 日程。"""
    prompts = []

    def model(messages, system_prompt="", **kwargs):
        if "信息分流器" in system_prompt:
            return {"kind": "later", "reason": "教程资料，无需要执行的事项"}
        if "判断新通知是否" in system_prompt:
            return {"same_event": False, "thread_id": None}
        prompts.append(system_prompt)
        # 故意违规返回截止日期，验证后端仍会为 later 清空 DDL
        return {
            "title": "会议投稿准备教程",
            "brief": "介绍如何准备会议投稿材料。",
            "why_focus": "以后写论文时参考",
            "category": "教程",
            "tags": ["投稿"],
            "deadline_date": "2026-12-01",
            "deadline_time": "09:00",
        }

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        resp = client.post(
            "/api/assistant/submit",
            json={"text": "教程：如何准备会议投稿，文中出现日期仅作排版示例。", "mode": "auto"},
            headers=env.auth_headers(),
        )
        assert resp.status_code == 201
        rec_id = resp.json()["id"]

    detail = client.get(f"/api/assistant/records/{rec_id}", headers=env.auth_headers()).json()
    assert detail["kind"] == "later", "分流为 later 后不应被正文里的日期改判为通知"
    assert detail["status"] == "ready"
    assert detail["card"]["deadline_date"] == ""
    assert prompts and "知识整理助手" in prompts[0], "later 流应使用 LATER_PROMPT 抽取"
    with db() as conn:
        sched = conn.execute("SELECT * FROM schedule WHERE date='2026-12-01'").fetchone()
    assert sched is None, "稍后看绝不允许创建 DDL 日程"


def test_later_extraction_requires_brief_and_parses_real_json():
    """不 mock chat_structured，让 required_keys 与 JSON 解析真实生效：LATER_PROMPT 只产出 brief 也必须通过。"""
    import json

    def fake_chat(messages, max_tokens=1500, temperature=0.3):
        return json.dumps({
            "title": "待读论文",
            "brief": "一篇讲多智能体的论文。",
            "why_focus": "以后做实验参考",
            "category": "论文",
            "tags": ["多智能体"],
        }, ensure_ascii=False)

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat", side_effect=fake_chat):
        resp = client.post(
            "/api/assistant/submit",
            json={"text": "arxiv 论文：多智能体协作综述", "mode": "later", "source_url": "https://arxiv.org/abs/0000.0001"},
            headers=env.auth_headers(),
        )
        assert resp.status_code == 201
        rec_id = resp.json()["id"]

    detail = client.get(f"/api/assistant/records/{rec_id}", headers=env.auth_headers()).json()
    assert detail["status"] == "ready", f"真实 JSON 解析路径不应失败: {detail.get('error_msg')}"
    assert detail["kind"] == "later"
    assert detail["card"]["brief"] == "一篇讲多智能体的论文。"
    assert detail["category"] == "论文"


def test_auto_classification_failure_is_reported_not_disguised():
    """分流模型失败时如实 failed 并保留原文，不再用关键词规则冒充分流结果。"""
    def model(messages, system_prompt="", **kwargs):
        raise llm.AiUnavailable("分类模型超时")

    with patch.object(llm, "is_enabled", return_value=True), patch.object(llm, "chat_structured", side_effect=model):
        resp = client.post(
            "/api/assistant/submit",
            json={"text": "通知：请于周五前提交报名材料。", "mode": "auto"},
            headers=env.auth_headers(),
        )
        assert resp.status_code == 201
        rec_id = resp.json()["id"]

    detail = client.get(f"/api/assistant/records/{rec_id}", headers=env.auth_headers()).json()
    assert detail["status"] == "failed", "分流失败必须如实标记 failed"
    assert "分类模型超时" in detail["error_msg"]
    assert detail["raw_text"], "失败时原始输入必须保留，便于重试"
