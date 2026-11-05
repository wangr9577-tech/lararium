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
import zipfile

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
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Application guidelines")
    fake_pdf = doc.tobytes()
    doc.close()

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

    # 运行管线（模型返回带证据原句的卡片）
    from unittest.mock import patch
    card = {
        "title": "2026年重点研发计划项目申报",
        "summary": "申报系统将于2026年11月20日18:00关闭，需在此之前完成系统提交，并报送盖章纸质材料。",
        "highlights": ["完成系统提交", "纸质材料一式三份盖章报送科研处"],
        "deadline_date": "2026-11-20",
        "deadline_time": "18:00",
        "event_keywords": ["项目申报", "申报系统"],
        "quote": "申报系统将于2026年11月20日18:00关闭，请各项目负责人务必在此之前完成系统提交。",
        "evidence_quotes": ["纸质材料需一式三份盖章报送科研处。"],
    }
    def respond(*args, **kwargs):
        if kwargs.get("system_prompt") == asst_mod.assistant_prompts.ATTACHMENT_TRANSCRIPTION_PROMPT:
            return {"text": "印章文字"}
        return card
    with patch.object(asst_mod.llm, "is_enabled", return_value=True), \
         patch.object(asst_mod.llm, "chat_structured", side_effect=respond):
        asst_mod.process_record_job(rec_id)

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


def test_attachment_processing_does_not_append_again(monkeypatch):
    monkeypatch.setattr(asst_mod, "process_record_job", lambda record_id: None)
    response = client.post("/api/assistant/submit", data={"text": "用户原文", "mode": "later"},
                           files={"file": ("note.txt", b"unique-attachment-content", "text/plain")},
                           headers=env.auth_headers())
    assert response.status_code == 201
    record_id = response.json()["id"]
    path = asst_mod._record_dir(record_id) / "raw.enc"
    before = asst_mod.vault.read_text(path)
    assert "unique-attachment-content" not in before
    monkeypatch.setattr(asst_mod.llm, "chat_structured", lambda *args, **kwargs: None)
    asst_mod._process_record_job(record_id)
    after = asst_mod.vault.read_text(path)
    assert after.count("unique-attachment-content") == 1
    asst_mod._process_record_job(record_id)
    assert asst_mod.vault.read_text(path) == after


def test_image_agent_transcribes_before_summary_and_caches(monkeypatch):
    monkeypatch.setattr(asst_mod, "process_record_job", lambda record_id: None)
    response = client.post("/api/assistant/submit", data={"text": "请整理", "mode": "notice"},
                           files={"file": ("notice.png", b"image-bytes", "image/png")},
                           headers=env.auth_headers())
    record_id = response.json()["id"]
    calls = []
    def transcribe(*args, **kwargs):
        assert kwargs["system_prompt"] == asst_mod.assistant_prompts.ATTACHMENT_TRANSCRIPTION_PROMPT
        calls.append("ocr")
        return {"text": "图片原文第一行\n图片原文第二行"}
    def summarize(record_id, rec, raw_text, images, job, candidate_hint=None):
        calls.append("summary")
        assert "图片原文第一行\n图片原文第二行" in raw_text
        assert "notice.png" in raw_text
        assert images == []
    monkeypatch.setattr(asst_mod.llm, "chat_structured", transcribe)
    monkeypatch.setattr(asst_mod, "_handle_notice_pipeline", summarize)
    asst_mod._process_record_job(record_id)
    asst_mod._process_record_job(record_id)
    assert calls == ["ocr", "summary", "summary"]


def test_image_agent_failure_stops_summary(monkeypatch):
    monkeypatch.setattr(asst_mod, "process_record_job", lambda record_id: None)
    response = client.post("/api/assistant/submit", data={"mode": "notice"},
                           files={"file": ("unreadable.png", b"image-bytes", "image/png")},
                           headers=env.auth_headers())
    record_id = response.json()["id"]
    monkeypatch.setattr(asst_mod.llm, "chat_structured", lambda *args, **kwargs: {"text": ""})
    monkeypatch.setattr(asst_mod, "_handle_notice_pipeline", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not summarize")))
    asst_mod._process_record_job(record_id)
    detail = client.get(f"/api/assistant/records/{record_id}", headers=env.auth_headers()).json()
    assert detail["status"] == "failed"
    assert "没有识别到可用文字" in detail["error_msg"]


def test_scanned_pdf_is_transcribed_by_page(monkeypatch):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    pdf = doc.tobytes()
    doc.close()
    seen = []
    def transcribe(messages, **kwargs):
        seen.append(messages)
        return {"text": "扫描页中的文字"}
    monkeypatch.setattr(asst_mod.llm, "chat_structured", transcribe)
    result = asst_mod.attachment_agent.convert("scan.pdf", pdf, asst_mod._extract_text_from_file_bytes)
    assert "第 1 页" in result and "扫描页中的文字" in result
    assert seen[0][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def _sample_docx():
    output = io.BytesIO()
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>第一段正文</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p>'
           '</w:tc></w:tr></w:tbl></w:body></w:document>')
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_docx_old_upload_is_extracted_on_retry(monkeypatch):
    from unittest.mock import patch
    with patch.object(asst_mod, "process_record_job"), patch.object(asst_mod, "_extract_text_from_file_bytes", return_value=""):
        response = client.post("/api/assistant/submit", data={"text": "用户问题", "mode": "notice"},
                               files={"file": ("rules.docx", _sample_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                               headers=env.auth_headers())
    assert response.status_code == 201
    record_id = response.json()["id"]
    seen = []
    def capture(record_id, rec, raw_text, images, job, candidate_hint=None):
        seen.append(raw_text)
    monkeypatch.setattr(asst_mod, "_handle_notice_pipeline", capture)
    asst_mod._process_record_job(record_id)
    asst_mod._process_record_job(record_id)
    assert len(seen) == 2
    assert "第一段正文\n表格内容" in seen[0]
    assert seen[1].count("第一段正文") == 1
    assert asst_mod.vault.read_text(asst_mod._record_dir(record_id) / "raw.enc") == seen[1]


def test_unreadable_attachment_fails_visibly_and_is_retained(monkeypatch):
    monkeypatch.setattr(asst_mod, "process_record_job", lambda record_id: None)
    response = client.post("/api/assistant/submit", data={"text": "用户问题", "mode": "notice"},
                           files={"file": ("broken.docx", b"invalid", "application/octet-stream")},
                           headers=env.auth_headers())
    record_id = response.json()["id"]
    asst_mod._process_record_job(record_id)
    detail = client.get(f"/api/assistant/records/{record_id}", headers=env.auth_headers()).json()
    assert detail["status"] == "failed"
    assert "broken.docx" in detail["error_msg"]
    assert len(detail["attachments"]) == 1


def test_attachment_limits_and_active_content(monkeypatch):
    monkeypatch.setattr(asst_mod, "process_record_job", lambda record_id: None)
    monkeypatch.setattr(asst_mod, "MAX_FILE_BYTES", 8)
    monkeypatch.setattr(asst_mod, "MAX_UPLOAD_BYTES", 12)
    headers = env.auth_headers()
    response = client.post("/api/assistant/submit", files={"file": ("big.txt", b"123456789")}, headers=headers)
    assert response.status_code == 413
    response = client.post("/api/assistant/submit", files=[("file", ("a.txt", b"1234567")), ("file", ("b.txt", b"1234567"))], headers=headers)
    assert response.status_code == 413
    response = client.post("/api/assistant/submit", files={"file": ("x.svg", b"<svg/>")}, headers=headers)
    assert response.status_code == 201
    record_id = response.json()["id"]
    attachment = client.get(f"/api/assistant/records/{record_id}/attachments", headers=headers).json()["attachments"][0]
    result = client.get(attachment["url"], headers=headers)
    assert result.headers["content-disposition"].startswith("attachment;")
    assert result.headers["x-content-type-options"] == "nosniff"


def test_streamed_request_without_content_length_is_limited(monkeypatch):
    monkeypatch.setattr(asst_mod, "MAX_UPLOAD_BYTES", 12)
    headers = {**env.auth_headers(), "content-type": "application/json"}
    def body():
        yield b'{"text":"'
        yield b'a' * (1024 * 1024 + 100)
        yield b'"}'
    response = client.post("/api/assistant/submit", content=body(), headers=headers)
    assert response.status_code == 413
