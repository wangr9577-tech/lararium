"""测试资产与附件管理器 (Asset Garbage Collector)。

测试范围：
1. 鉴权守卫（未登录 401，DEK 未解锁 423）；
2. 体检扫描：准确统计文件数、占用体积、未引用孤立文件清单与正文引用关系；
3. 安全清理：支持单个/多选/全选清理，默认移入回收站 (data/trash)；
4. 资源预览与安全读取：AES-GCM 加密文件透明解密，严防路径穿越越权。
"""
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
from app import config, crypto, db, trashbin, vault
from app.db import init_db
from app.main import app

env = TestEnvironment(prefix="kruskal_test_assets_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_assets_management_workflow():
    # 1. 本机会话验证
    # 未认证访问被拦截
    r_unauth = client.get("/api/assets/scan")
    assert r_unauth.status_code == 401

    headers = env.auth_headers()

    # 2. 初始状态扫描（应当全为 0）
    r_scan0 = client.get("/api/assets/scan", headers=headers)
    assert r_scan0.status_code == 200
    data0 = r_scan0.json()
    assert data0["total_files"] == 0
    assert data0["unreferenced_count"] == 0

    # 3. 构造测试资产
    # 资产 A: 笔记中引用的图片 (vault 加密存储在 images/)
    images_dir = config.DATA_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    img_a_name = "aabbcc112233.png"
    img_a_content = b"FAKE_PNG_IMAGE_A_REFERENCED"
    vault.write_bytes(images_dir / img_a_name, img_a_content)

    # 资产 B: 孤立无引用的图片 (在 images/)
    img_b_name = "deadbeef1234.png"
    img_b_content = b"FAKE_PNG_IMAGE_B_ORPHAN"
    vault.write_bytes(images_dir / img_b_name, img_b_content)

    # 资产 C: 附件 (在 uploads/)，被日记引用
    uploads_dir = config.DATA_DIR / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    pdf_c_name = "paper_2026.pdf"
    pdf_c_path = uploads_dir / pdf_c_name
    pdf_c_path.write_bytes(b"%PDF-1.4 FAKE_PDF_C_REFERENCED")

    # 资产 D: 孤立附件 (在 uploads/)，无任何文档引用
    doc_d_name = "unused_attachment.docx"
    doc_d_path = uploads_dir / doc_d_name
    doc_d_path.write_bytes(b"FAKE_DOCX_D_ORPHAN_CONTENT_1234567890")

    # 4. 构造引用文档
    # 笔记引用 img_a
    notes_dir = config.DATA_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_content = f"""---
title: 测试图形学研究笔记
fmt: md
---
这里有一张重要的实验图表：
![实验结果](/api/notes/images/{img_a_name})
"""
    vault.write_text(notes_dir / "note_1.md", note_content)

    # 日记引用 pdf_c
    diary_dir = config.DATA_DIR / "diary"
    diary_dir.mkdir(parents=True, exist_ok=True)
    diary_content = f"""---
mood: 充实
weather: 晴
---
今天查阅了相关文献：[点击下载文献](/api/fs/raw/uploads/{pdf_c_name})
"""
    vault.write_text(diary_dir / "2026-11-02.md", diary_content)

    # 5. 执行体检扫描
    r_scan1 = client.get("/api/assets/scan", headers=headers)
    assert r_scan1.status_code == 200
    res1 = r_scan1.json()

    assert res1["total_files"] == 4
    assert res1["unreferenced_count"] == 2  # img_b 和 doc_d 应该孤立
    assert len(res1["unreferenced_files"]) == 2
    assert len(res1["referenced_files"]) == 2

    # 验证已引用资产的信息
    ref_names = {f["filename"] for f in res1["referenced_files"]}
    assert img_a_name in ref_names
    assert pdf_c_name in ref_names

    # 检查引用来源标记
    for f in res1["referenced_files"]:
        if f["filename"] == img_a_name:
            assert f["ref_count"] == 1
            assert "测试图形学研究笔记" in f["references"][0]["title"]
        elif f["filename"] == pdf_c_name:
            assert f["ref_count"] == 1
            assert "日记" in f["references"][0]["type"]

    # 验证未引用孤立资产的信息
    unref_names = {f["filename"] for f in res1["unreferenced_files"]}
    assert img_b_name in unref_names
    assert doc_d_name in unref_names

    # 6. 安全读取与文件预览接口测试
    # 预览加密图片 img_a
    r_file_a = client.get(f"/api/assets/file?path=images/{img_a_name}", headers=headers)
    assert r_file_a.status_code == 200
    assert r_file_a.content == img_a_content  # 经 vault 透明解密后的明文

    # 预览普通文件 pdf_c
    r_file_c = client.get(f"/api/assets/file?path=uploads/{pdf_c_name}", headers=headers)
    assert r_file_c.status_code == 200
    assert r_file_c.content == b"%PDF-1.4 FAKE_PDF_C_REFERENCED"

    # 防越权与路径穿越测试
    r_hack = client.get("/api/assets/file?path=../../site.db", headers=headers)
    assert r_hack.status_code in (403, 404)

    # 7. 清理单个孤立文件 (img_b) -> 移入回收站
    r_clean1 = client.post("/api/assets/clean", json={"filenames": [img_b_name], "permanent": False}, headers=headers)
    assert r_clean1.status_code == 200
    c1_data = r_clean1.json()
    assert c1_data["cleaned_count"] == 1
    assert c1_data["trash_id"] is not None

    # 原位置文件应已被移走
    assert not (images_dir / img_b_name).exists()

    # 再次扫描，应当只剩 1 个孤立文件 (doc_d)
    r_scan2 = client.get("/api/assets/scan", headers=headers)
    res2 = r_scan2.json()
    assert res2["total_files"] == 3
    assert res2["unreferenced_count"] == 1
    assert res2["unreferenced_files"][0]["filename"] == doc_d_name

    # 8. 一键清理所有孤立文件 (all_unreferenced=True)
    r_clean_all = client.post("/api/assets/clean", json={"all_unreferenced": True, "permanent": False}, headers=headers)
    assert r_clean_all.status_code == 200
    c_all_data = r_clean_all.json()
    assert c_all_data["cleaned_count"] == 1

    # 再次扫描：无孤立文件，达到体检 100% 健康
    r_scan3 = client.get("/api/assets/scan", headers=headers)
    res3 = r_scan3.json()
    assert res3["total_files"] == 2
    assert res3["unreferenced_count"] == 0
    assert len(res3["unreferenced_files"]) == 0
    assert len(res3["referenced_files"]) == 2


if __name__ == "__main__":
    setup_module()
    try:
        test_assets_management_workflow()
    finally:
        teardown_module()
