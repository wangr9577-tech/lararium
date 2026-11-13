"""论文中文翻译：分栏切分、原位回写、接口状态机（全离线，LLM 用替身）。

覆盖：
1. 版面切分：双栏不被合成整页块、公式/作者邮箱不送去翻译；
2. 回写：页数与页面尺寸不变、原文被中文替换、公式原样保留；
3. 接口：/translation 的 none → running → ready 状态机、译文下载与删除；
4. 崩溃恢复：遗留的 running 状态会被读成 failed（可重试）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import pymupdf

from backend.tests.test_env import TestEnvironment
from app.services import paper_translate as pt

env = TestEnvironment(prefix="kruskal_paper_trans_")
client = env.client


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def _make_pdf() -> bytes:
    """一页双栏样张：标题 / 摘要 / 左栏正文 / 右栏小节 / 一行公式。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 80), "Attention Is All You Need", fontsize=15, fontname="helv")
    page.insert_text((60, 130), "Abstract", fontsize=11, fontname="times-bold")
    y = 150
    for line in (
        "The dominant sequence transduction models are based on complex",
        "recurrent or convolutional neural networks that include an encoder.",
        "The best performing models also connect the encoder and decoder.",
    ):
        page.insert_text((60, y), line, fontsize=9, fontname="times-roman")
        y += 12
    page.insert_text((60, y + 24), "x = W_q * k + b", fontsize=9, fontname="courier")
    page.insert_text((320, 150), "1 Introduction", fontsize=10, fontname="times-bold")
    page.insert_text((320, 166), "Recurrent neural networks have been firmly established.",
                     fontsize=9, fontname="times-roman")
    page.insert_text((320, 178), "Long short-term memory networks are widely used.",
                     fontsize=9, fontname="times-roman")
    page.insert_text((320, 200), "Contact: someone@example.com", fontsize=9,
                     fontname="times-roman")
    data = doc.tobytes()
    doc.close()
    return data


def _cjk(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def test_page_units_split_columns_and_skip_math():
    doc = pymupdf.open(stream=_make_pdf(), filetype="pdf")
    units = pt.page_units(doc[0])
    texts = [u["text"] for u in units]

    assert any(u["bbox"][0] >= 300 for u in units), "右栏应当被单独切成块"
    assert all((u["bbox"][2] - u["bbox"][0]) < 400 for u in units), "双栏不应合成整页宽块"
    assert not any("W_q" in t for t in texts), "公式行不该送去翻译"
    assert not any("@example.com" in t for t in texts), "作者/联系邮箱不该送去翻译"
    assert any("sequence transduction" in t for t in texts)


def test_translate_pdf_rewrites_text_and_keeps_layout(monkeypatch):
    def fake_batch(items):
        return {i: "这是中文译文" for i, _t in items}

    monkeypatch.setattr(pt, "_translate_batch", fake_batch)
    monkeypatch.setattr(pt, "_translate_one", lambda text: "这是中文译文")

    src = _make_pdf()
    out = pt.translate_pdf(src)
    assert len(out) < 3 * 1024 * 1024, "字体未 subset 会让一页样张涨到数 MB"

    d = pymupdf.open(stream=out, filetype="pdf")
    try:
        assert d.page_count == 1
        page = d[0]
        assert round(page.rect.width) == 595
        assert round(page.rect.height) == 842
        text = page.get_text("text")
        assert _cjk(text) >= 10, "译文里应当有中文"
        assert "sequence transduction" not in text, "英文原文应当被擦除"
        assert "W_q" in text, "公式应当原样保留"
        assert "@example.com" in text, "邮箱行应当原样保留"
    finally:
        d.close()


def test_api_translation_lifecycle(monkeypatch):
    headers = env.auth_headers()
    r = client.post(
        "/api/papers",
        files={"files": ("trans-test.pdf", _make_pdf(), "application/pdf")},
        data={"title": "翻译测试论文", "auto_translate": "0"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["items"][0]["id"]

    st = client.get(f"/api/papers/{pid}/translation", headers=headers).json()
    assert st["state"] == "none"

    monkeypatch.setattr(pt, "_translate_batch",
                        lambda items: {i: "这是中文译文" for i, _t in items})
    monkeypatch.setattr(pt, "_translate_one", lambda text: "这是中文译文")

    r = client.post(f"/api/papers/{pid}/translation", json={"force": False}, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["state"] in ("running", "ready")

    for _ in range(200):
        st = client.get(f"/api/papers/{pid}/translation", headers=headers).json()
        if st["state"] in ("ready", "failed"):
            break
        time.sleep(0.1)
    assert st["state"] == "ready", st

    f = client.get(f"/api/papers/{pid}/translation/file", headers=headers)
    assert f.status_code == 200
    assert f.content[:4] == b"%PDF"
    assert _cjk(pymupdf.open(stream=f.content, filetype="pdf")[0].get_text("text")) >= 10

    assert client.delete(f"/api/papers/{pid}/translation", headers=headers).status_code == 200
    assert client.get(f"/api/papers/{pid}/translation", headers=headers).json()["state"] == "none"

    assert client.delete(f"/api/papers/{pid}", headers=headers).status_code == 200


def test_upload_triggers_translation_and_saves(monkeypatch):
    """上传即翻译：不打开论文、不点「翻译」，入库后自动排队跑完并落盘。"""
    headers = env.auth_headers()
    monkeypatch.setattr(pt, "_translate_batch",
                        lambda items: {i: "上传后自动翻译" for i, _t in items})
    monkeypatch.setattr(pt, "_translate_one", lambda text: "上传后自动翻译")

    r = client.post(
        "/api/papers",
        files={"files": ("auto-trans.pdf", _make_pdf(), "application/pdf")},
        data={"title": "上传即翻译"},   # 默认 auto_translate=1
        headers=headers,
    )
    assert r.status_code == 201, r.text
    item = r.json()["items"][0]
    pid = item["id"]
    assert item["trans_state"] in ("queued", "running", "ready")

    for _ in range(200):
        st = client.get(f"/api/papers/{pid}/translation", headers=headers).json()
        if st["state"] in ("ready", "failed"):
            break
        time.sleep(0.1)
    assert st["state"] == "ready", st

    # 列表里能直接看到「已译」状态（不用点进去）
    listed = client.get("/api/papers", headers=headers).json()["items"]
    assert next(p for p in listed if p["id"] == pid)["trans_state"] == "ready"

    f = client.get(f"/api/papers/{pid}/translation/file", headers=headers)
    assert f.status_code == 200 and f.content[:4] == b"%PDF"

    assert client.delete(f"/api/papers/{pid}", headers=headers).status_code == 200


def test_batch_upload_is_serialized(monkeypatch):
    """一次传多篇：全部排队，逐个跑完（并发 > 1 会抢本地模型）。"""
    headers = env.auth_headers()
    seen: list[str] = []

    def fake_batch(items):
        seen.append("x")
        return {i: "批量译文" for i, _t in items}

    monkeypatch.setattr(pt, "_translate_batch", fake_batch)
    monkeypatch.setattr(pt, "_translate_one", lambda text: "批量译文")

    files = [("files", (f"batch-{i}.pdf", _make_pdf(), "application/pdf")) for i in range(3)]
    r = client.post("/api/papers", files=files, data={"title": ""}, headers=headers)
    assert r.status_code == 201, r.text
    pids = [it["id"] for it in r.json()["items"]]
    assert len(pids) == 3

    for _ in range(300):
        states = [client.get(f"/api/papers/{p}/translation", headers=headers).json()["state"]
                  for p in pids]
        if all(s in ("ready", "failed") for s in states):
            break
        time.sleep(0.1)
    assert states == ["ready", "ready", "ready"], states

    for p in pids:
        assert client.delete(f"/api/papers/{p}", headers=headers).status_code == 200


def test_stale_running_status_becomes_failed():
    headers = env.auth_headers()
    r = client.post(
        "/api/papers",
        files={"files": ("stale-test.pdf", _make_pdf(), "application/pdf")},
        data={"title": "中断状态测试", "auto_translate": "0"},
        headers=headers,
    )
    pid = r.json()["items"][0]["id"]
    pt._save(pid, {"state": "running", "pages": 3, "done": 1, "updated": pt._now()})

    st = client.get(f"/api/papers/{pid}/translation", headers=headers).json()
    assert st["state"] == "failed"
    assert "中断" in st["error"]

    assert client.delete(f"/api/papers/{pid}", headers=headers).status_code == 200