"""Kruskal 配置：全部路径基于仓库根相对解析，支持环境变量覆盖，便于迁移。

迁移/备份时只需带走 DATA_DIR 一个目录。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 数据目录：所有用户内容（笔记/日记/论文/相册/说说/密钥包裹）都在这里
DATA_DIR = Path(os.environ.get("KRUSKAL_DATA_DIR", str(REPO_ROOT / "backend" / "data")))

# 仅绑定本机回环：跨子网/校外访问一律走 SSH 隧道或出站隧道（详见 deploy/ACCESS.md）
# 如需临时放开，用环境变量 KRUSKAL_HOST=0.0.0.0 覆盖
HOST = os.environ.get("KRUSKAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("KRUSKAL_PORT", "18080"))

DIST_DIR = REPO_ROOT / "frontend" / "dist"
DB_PATH = DATA_DIR / "site.db"
KEYWRAP_PATH = DATA_DIR / ".kek"                # 数据密钥包裹文件（由主密码派生密钥加密）
KEYWRAP_JOURNAL = DATA_DIR / ".kek.journal"     # 改密两阶段日志：记新包裹，DB 提交成功后才 rename 覆盖
INIT_PW_FILE = DATA_DIR / "initial_password.txt"

ADMIN_USERNAME = "admin"
TOKEN_TTL_DAYS = 30

# 内容子目录（正文 md / 资源均存于 DATA_DIR，正文按功能期实现加密）
# trash = 回收站：删除先进这里，显式永久删除才物理删
SUBDIRS = ["notes", "diary", "papers", "uploads", "album", "share", "tmp", "holidays", "trash",
           "cards", "ideas", "experiments", "writing"]

# 代码工作区白名单根目录（M8）：浏览器里只能看/改这个目录树，防路径穿越
CODE_ROOT = Path(os.environ.get("KRUSKAL_CODE_ROOT",
                                "/mnt/data_server/home/stu_wr/deepseek-workspace"))
# AI 服务（M7）：本地 vLLM（OpenAI 兼容），默认 127.0.0.1 上的 vLLM
AI_ENDPOINT = os.environ.get("KRUSKAL_AI_ENDPOINT", "http://127.0.0.1:8000/v1")
AI_MODEL = os.environ.get("KRUSKAL_AI_MODEL", "qwen3.8-27b")
AI_TIMEOUT = int(os.environ.get("KRUSKAL_AI_TIMEOUT", "120"))

# PDF 导出临时目录（md→PDF 渲染用，用完即清）
TMP_DIR = DATA_DIR / "tmp"


def ensure_layout() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (DATA_DIR / name).mkdir(exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)  # 同机其他普通用户不可读
    except OSError:
        pass  # NFS 等场景 chmod 可能被拒，加密层兜底
