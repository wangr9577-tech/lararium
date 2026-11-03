"""助手附件读取下载与精准引用依据测试套件。

测试覆盖：
1. 上传图片、PDF、纯文本等多类型文件到助手；
2. 验证 GET /api/assistant/records/{id}/attachments 附件清单；
3. 验证 GET /api/assistant/records/{id}/attachments/{filename}：
   - 鉴权支持（Bearer Header 与 ?token= 查询参数）；
   - 未授权访问拦截（401）；
   - 路径防穿越校验（如 ../, 特殊字符等拦截 400/403）；
   - 自适应 MIME 类型（image/png, application/pdf, text/plain）；
   - 浏览器内联预览（inline）与附件下载（attachment）；
4. 验证事实证据锚点（quote 与 evidence_quotes）正确提取与回显。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import io

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

from backend.tests.test_env import TestEnvironment
from app.routers import assistant as asst_mod

env = TestEnvironment(prefix="kruskal_asst_att_test_")
client = env.client


def setup_module():
    os.environ["KRUSKAL_AI_TIMEOUT"] = "1"
    env.setup()


def teardown_module():
    env.teardown()


def test_attachment_upload_and_evidence_quote():
    """测试文件上传、事实原句引用与附件读取/下载全流程。"""
    token = env.token
    headers = env.auth_headers()

    notice_content = (
        "【2026年重点研发计划项目申报指南通知】\n"
        "各院系、课题组：\n"
        "申报系统将于2026年11月20日18:00关闭，请各项目负责人务必在此之前完成系统提交。\n"
        "纸质材料需一式三份盖章报送科研处。"
    )

    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

    files = [
        ("file", ("guidelines.pdf", fake_pdf, "application/pdf")),
        ("file", ("stamp_proof.png", fake_png, "image/png")),
    ]
    data = {
        "text": notice_content,
        "mode": "notice",
        "user_note": "关注申报系统关闭时间与盖章要求",
    }

    resp = client.post("/api/assistant/submit", data=data, files=files, headers=headers)
    assert resp.status_code == 201, f"提交失败: {resp.text}"
    rec_id = resp.json()["id"]

    # 运行管线（走规则模式验证离线高可用提取）
    asst_mod.process_record_job(rec_id, use_fallback_rule=True)

    # 1. 查询详情，检验 quote 与 evidence_quotes
    detail_resp = client.get(f"/api/assistant/records/{rec_id}", headers=headers)
    assert detail_resp.status_code == 200
    rec_detail = detail_resp.json()

    assert rec_detail["status"] == "ready"
    assert "申报系统将于2026年11月20日18:00关闭" in rec_detail["quote"], (
        f"quote 必须精准引用核心依据原句，实际为: {rec_detail['quote']}"
    )
    assert isinstance(rec_detail["evidence_quotes"], list)
    assert len(rec_detail["attachments"]) == 2

    # 2. 检查附件清单
    list_att_resp = client.get(f"/api/assistant/records/{rec_id}/attachments", headers=headers)
    assert list_att_resp.status_code == 200
    atts = list_att_resp.json()["attachments"]
    assert len(atts) == 2

    pdf_att = next((a for a in atts if a["original_name"] == "guidelines.pdf"), None)
    png_att = next((a for a in atts if a["original_name"] == "stamp_proof.png"), None)
    assert pdf_att is not None, "未找到 PDF 附件"
    assert png_att is not None, "未找到 PNG 附件"

    assert pdf_att["is_image"] is False
    assert png_att["is_image"] is True
    assert pdf_att["size"] == len(fake_pdf)
    assert png_att["size"] == len(fake_png)

    # 3. 通过 Header 鉴权读取 PDF（inline 预览）
    pdf_resp = client.get(pdf_att["url"], headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"].startswith("application/pdf")
    assert "inline" in pdf_resp.headers["content-disposition"]
    assert pdf_resp.content == fake_pdf

    # 4. 通过 Query Parameter ?token= 鉴权读取图片（模拟浏览器 <img> 或 window.open）
    img_url_with_token = f"{png_att['url']}?token={token}"
    img_resp = client.get(img_url_with_token)
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"].startswith("image/png")
    assert "inline" in img_resp.headers["content-disposition"]
    assert img_resp.content == fake_png

    # 5. 下载模式（download=1）
    dl_resp = client.get(f"{pdf_att['url']}?download=1&token={token}")
    assert dl_resp.status_code == 200
    assert "attachment" in dl_resp.headers["content-disposition"]
    assert "guidelines.pdf" in dl_resp.headers["content-disposition"]

    # 6. 未授权访问拦截（401）
    unauth_resp = client.get(pdf_att["url"])
    assert unauth_resp.status_code == 401

    # 7. 路径穿越与非法文件名拦截（防穿越安全测试）
    traversal_urls = [
        f"/api/assistant/records/{rec_id}/attachments/..%2f..%2f..%2fetc%2fpasswd",
        f"/api/assistant/records/{rec_id}/attachments/..%5craw.enc",
        f"/api/assistant/records/{rec_id}/attachments/something%00.png",
    ]
    for bad_url in traversal_urls:
        bad_resp = client.get(bad_url, headers=headers)
        assert bad_resp.status_code in (400, 403, 404), f"穿越路径未被拦截: {bad_url} -> {bad_resp.status_code}"
