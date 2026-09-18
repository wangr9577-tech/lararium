"""上传读取守门：分块累读到上限即中断，杜绝"先全量进内存再判大小"。

用法：单文件端点传 request 走 Content-Length 快速拒绝；
多文件端点（papers/album 批量）不传 request，仅靠流式上限。
"""
from __future__ import annotations

from fastapi import HTTPException, Request, UploadFile

CHUNK = 1 << 20  # 1MB


async def read_upload(file: UploadFile, limit: int, *,
                      request: Request | None = None, too_big: str = "") -> bytes:
    mb = limit // (1 << 20)
    msg = too_big or f"文件过大（上限 {mb}MB）"
    if request is not None:
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > limit + (8 << 20):  # 余量给表单字段
            raise HTTPException(413, msg)
    buf = bytearray()
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, msg)
    return bytes(buf)
