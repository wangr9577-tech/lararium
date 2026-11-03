"""Kruskal 新增功能端到端自动化测试套件。

涵盖范围：
1. 资产管理器接口（GET /api/assets/scan 与 POST /api/assets/clean）：未引用文件精准识别与安全清理；
2. 日记今日足迹汇总（GET /api/diary/footprint）：日程、记账、笔记动态数据自动汇总与模板生成；
3. 工作台资料反向链接（GET /api/workbench/links/backlinks）：事项与资料双向引用查询与元数据透传；
4. 全局快速收录（POST /api/workbench/captures）：闪念内容、来源及链接极速入库与解密校验；
5. 架构韧性安全测试：未登录 401、DEK 未注入 423 与一键上锁 401 防御闭环。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from starlette.testclient import TestClient

from backend.tests.test_env import TestEnvironment
from app import config, db, vault

env = TestEnvironment(prefix="kruskal_enhancements_test_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def auth_headers() -> dict[str, str]:
    return env.auth_headers()


# ==============================================================================
# 测试 1：资产管理器接口（GET /api/assets/scan 与 POST /api/assets/clean）
# ==============================================================================
def test_1_asset_manager_scan_and_clean():
    """验证资产扫描统计、孤立文件识别及垃圾清理闭环。"""
    headers = auth_headers()

    # 准备目录
    images_dir = config.DATA_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    notes_dir = config.DATA_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # 构造两个资产文件：一个被笔记引用，另一个孤立未引用
    ref_img_name = "ref_img_test_123.png"
    orphan_img_name = "orphan_img_test_456.png"

    vault.write_bytes(images_dir / ref_img_name, b"PNG_TEST_REFERENCED_CONTENT")
    vault.write_bytes(images_dir / orphan_img_name, b"PNG_TEST_ORPHAN_CONTENT")

    # 写入引用该图片的加密笔记
    note_md = f"""---
title: 测试资产引用的笔记
fmt: md
---
这里引用了测试图片：
![测试图片](/api/notes/images/{ref_img_name})
"""
    vault.write_text(notes_dir / "note_asset_ref.md", note_md)

    # 扫描资产：验证识别情况
    r_scan = client.get("/api/assets/scan", headers=headers)
    assert r_scan.status_code == 200, f"资产扫描失败: {r_scan.text}"
    scan_data = r_scan.json()
    assert scan_data["total_files"] >= 2
    assert scan_data["unreferenced_count"] >= 1

    unref_names = [f["filename"] for f in scan_data["unreferenced_files"]]
    assert orphan_img_name in unref_names, "孤立文件未被正确识别"
    ref_names = [f["filename"] for f in scan_data["referenced_files"]]
    assert ref_img_name in ref_names, "被引用的文件未正确识别为 referenced"

    # 执行清理孤立资产
    r_clean = client.post(
        "/api/assets/clean",
        json={"filenames": [orphan_img_name], "permanent": False},
        headers=headers,
    )
    assert r_clean.status_code == 200, f"资产清理失败: {r_clean.text}"
    clean_data = r_clean.json()
    assert clean_data["cleaned_count"] >= 1
    assert any(orphan_img_name in p for p in clean_data["cleaned_files"])

    # 再次扫描：孤立文件已被清理
    r_rescan = client.get("/api/assets/scan", headers=headers)
    assert r_rescan.status_code == 200
    rescan_data = r_rescan.json()
    assert orphan_img_name not in [f["filename"] for f in rescan_data["unreferenced_files"]]


# ==============================================================================
# 测试 2：日记今日足迹汇总（GET /api/diary/footprint）
# ==============================================================================
def test_2_diary_today_footprint():
    """验证日程、记账、笔记动态跨模块自动汇聚。"""
    headers = auth_headers()
    target_date = "2026-11-02"

    with db.db() as conn:
        # 1. 注入日程
        conn.execute(
            "INSERT INTO schedule(title, kind, type, date, time_start, done, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("重点实验室答辩", "daily", "task", target_date, "09:00", 1, "2026-11-02 08:00:00"),
        )
        # 2. 注入记账（单位分）
        conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) VALUES(?,?,?,?,?,?)",
            (target_date, "expense", 4800, "科研用书", "购买算法设计书籍", "2026-11-02 12:00:00"),
        )
        conn.execute(
            "INSERT INTO ledger(date, kind, amount, category, note, created) VALUES(?,?,?,?,?,?)",
            (target_date, "income", 120000, "科研津贴", "导师发放项目津贴", "2026-11-02 15:00:00"),
        )

    # 3. 创建一篇今日笔记
    r_note = client.post(
        "/api/notes",
        json={
            "title": "今日科研算法推演笔记",
            "type": "note",
            "folder": "科研",
            "tags": ["算法", "图论"],
            "content": "# 今日算法笔记正文",
        },
        headers=headers,
    )
    assert r_note.status_code == 201

    # 请求今日足迹接口
    r_fp = client.get(f"/api/diary/footprint?date={target_date}", headers=headers)
    assert r_fp.status_code == 200, f"获取足迹失败: {r_fp.text}"
    fp = r_fp.json()

    assert fp["date"] == target_date
    # 验证日程
    assert fp["schedule"]["total"] >= 1
    assert any("重点实验室答辩" in item["title"] for item in fp["schedule"]["items"])
    # 验证记账（元单位）
    assert fp["ledger"]["total_expense"] == 48.0
    assert fp["ledger"]["total_income"] == 1200.0
    # 验证模板生成
    template = fp["template"]
    assert "今日足迹自动汇总" in template
    assert "重点实验室答辩" in template
    assert "48" in template


# ==============================================================================
# 测试 3：工作台资料反向链接（GET /api/workbench/links/backlinks）
# ==============================================================================
def test_3_workbench_backlinks():
    """验证工作台事项对笔记、论文反向引用的正确检索。"""
    headers = auth_headers()

    # 1. 创建工作台主事项
    r_item = client.post(
        "/api/workbench/items",
        json={"title": "国家自然科学基金申报推进", "summary": "申报书撰写"},
        headers=headers,
    )
    assert r_item.status_code == 201
    item_id = r_item.json()["id"]

    # 2. 创建真实笔记
    r_note = client.post(
        "/api/notes",
        json={
            "title": "NSFC 重点项目背景文献综述",
            "type": "note",
            "folder": "基金",
            "tags": ["NSFC"],
            "content": "综述正文内容",
        },
        headers=headers,
    )
    assert r_note.status_code == 201
    note_id = r_note.json()["id"]

    # 3. 在工作台关联该笔记
    r_link = client.post(
        f"/api/workbench/items/{item_id}/links",
        json={"target_type": "note", "target_id": note_id},
        headers=headers,
    )
    assert r_link.status_code == 201

    # 4. 验证反向链接查询 (Backlinks)
    r_back = client.get(
        f"/api/workbench/links/backlinks?target_type=note&target_id={note_id}",
        headers=headers,
    )
    assert r_back.status_code == 200, f"反向链接查询失败: {r_back.text}"
    back_data = r_back.json()
    assert len(back_data["items"]) >= 1
    linked_item = next(it for it in back_data["items"] if it["id"] == item_id)
    assert linked_item["title"] == "国家自然科学基金申报推进"


# ==============================================================================
# 测试 4：全局快速收录（POST /api/workbench/captures）
# ==============================================================================
def test_4_global_quick_capture():
    """验证全局闪念内容、来源及链接极速入库与解密校验。"""
    headers = auth_headers()

    capture_body = {
        "text": "发现一种新的图注意力稀疏化优化技巧 #科研灵感 #稀疏注意力",
        "source": "arXiv速递",
        "url": "https://arxiv.org/abs/2611.99999",
        "user_note": "需要应用到图聚类模块中",
        "item_id": None,
    }
    r_cap = client.post("/api/workbench/captures", json=capture_body, headers=headers)
    assert r_cap.status_code == 201, f"收录失败: {r_cap.text}"
    cap_resp = r_cap.json()
    cid = cap_resp["id"]
    assert cid > 0
    assert cap_resp["source"] == "arXiv速递"

    # 查询单条详情并验证正文正确解密
    r_detail = client.get(f"/api/workbench/captures/{cid}", headers=headers)
    assert r_detail.status_code == 200
    detail = r_detail.json()
    assert "发现一种新的图注意力稀疏化优化技巧" in detail["text"]
    assert "附注: 需要应用到图聚类模块中" in detail["text"]

    # 验证在收集箱列表中能查到
    r_inbox = client.get("/api/workbench/captures?scope=inbox", headers=headers)
    assert r_inbox.status_code == 200
    assert any(c["id"] == cid for c in r_inbox.json()["items"])


# ==============================================================================
# 测试 5：安全测试（未登录 401 与 DEK 未注入 423）
# ==============================================================================
def test_5_security_and_dek_lock_defense():
    """验证敏感接口在未认证状态下返回 401，DEK 未解锁/锁定状态下严格返回 423。"""
    # 1. 未携带 Token 的匿名请求一律 401
    assert client.get("/api/assets/scan").status_code == 401
    assert client.get("/api/diary/footprint").status_code == 401
    assert client.get("/api/workbench/links/backlinks").status_code == 401
    assert client.post("/api/workbench/captures", json={"text": "测试"}).status_code == 401
    assert client.get("/api/notes").status_code == 401

    headers = auth_headers()

    # 2. 模拟内存中 DEK 丢失/未注入状态（Token 有效但未解密数据密钥）
    saved_dek = vault.dek()
    vault.clear_dek()
    assert not vault.has_dek(), "DEK 必须从内存中清空"

    # 3. DEK 未注入状态下访问加密敏感资源一律拦截为 423 Locked
    assert client.get("/api/assets/scan", headers=headers).status_code == 423
    assert client.post("/api/workbench/captures", json={"text": "上锁测试"}, headers=headers).status_code == 423
    assert client.post("/api/workbench/items", json={"title": "上锁事项"}, headers=headers).status_code == 423

    # 4. 恢复 DEK 后接口恢复正常访问
    vault.set_dek(saved_dek)
    assert vault.has_dek()
    assert client.get("/api/assets/scan", headers=headers).status_code == 200

    # 5. 调用 /api/auth/lock 彻底锁定撤销 token
    r_lock = client.post("/api/auth/lock", headers=headers)
    assert r_lock.status_code == 200
    assert not vault.has_dek()
    # 撤销后再次携带原 token 访问敏感接口返回 401
    assert client.get("/api/assets/scan", headers=headers).status_code == 401

    # 6. 重新登录，恢复 Token 与 DEK
    r_relogin = client.post(
        "/api/auth/login",
        json={"username": config.ADMIN_USERNAME, "password": env.admin_pw},
    )
    assert r_relogin.status_code == 200
    assert vault.has_dek(), "重新登录后 DEK 必须成功注入"


if __name__ == "__main__":
    setup_module()
    try:
        test_1_asset_manager_scan_and_clean()
        test_2_diary_today_footprint()
        test_3_workbench_backlinks()
        test_4_global_quick_capture()
        test_5_security_and_dek_lock_defense()
        print("ALL NEW ENHANCEMENTS TESTS PASSED!")
    finally:
        teardown_module()
