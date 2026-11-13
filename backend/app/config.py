"""Kruskal 配置：全部路径基于仓库根相对解析，支持环境变量覆盖，便于迁移。

迁移/备份时只需带走 DATA_DIR 一个目录。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def _configured_path(value: str) -> Path:
    """Resolve relative configuration paths against the project, not the launch cwd."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path

# 数据目录：所有用户内容（笔记/日记/论文/相册/密钥包裹）都在这里
DATA_DIR = _configured_path(os.environ.get("KRUSKAL_DATA_DIR", "backend/data"))

# 单机应用：只监听本机回环，不做对外服务
HOST = os.environ.get("KRUSKAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("KRUSKAL_PORT", "18080"))

DIST_DIR = REPO_ROOT / "frontend" / "dist"
DB_PATH = DATA_DIR / "site.db"
# 本地私有配置文件：存储用户在前端填写的私有设置（AI 渠道、API 密钥、个人配置等），
# 独立于代码文件落盘在 DATA_DIR 中，受 .gitignore 绝对忽略，严禁上传到 Git
LOCAL_SETTINGS_PATH = DATA_DIR / "local_settings.json"
# 旧版密码模式的密钥包裹：只在启动时用于识别「已有加密数据」并拒绝覆盖（见 main.py）
KEYWRAP_PATH = DATA_DIR / ".kek"

# ---- 本机数据密钥：包裹与密钥都随数据目录走，启动时自动解锁（见 app/autokey.py）----
AUTOKEY_WRAP = DATA_DIR / ".kek.auto"
AUTOKEY_KEY = DATA_DIR / ".autokey"

ADMIN_USERNAME = "admin"  # 本机唯一用户（沿用旧库里的用户名）
TOKEN_TTL_DAYS = 30

# 内容子目录（正文 md / 资源均存于 DATA_DIR，正文按功能期实现加密）
# trash = 回收站：删除先进这里，显式永久删除才物理删
SUBDIRS = ["notes", "diary", "papers", "uploads", "album", "share", "tmp", "holidays", "trash",
           "cards", "ideas", "experiments", "writing",
           # 工作台：事项当前思路 / 小记 / 收集片段（均 AES-GCM 加密落盘）
           "workbench",
           # 首页「今日安排」随手记（一份固定的加密 md，data/daynote/note.md；不按天归档）
           "daynote",
           # 助手：通知原文、提取卡片、附件证据与事实快照
           "assistant"]

# 代码工作区白名单根目录（M8）：浏览器里只能看/改这个目录树，防路径穿越
_default_code_root = _configured_path(os.environ.get("KRUSKAL_CODE_ROOT",
                                                    str(Path.home() / "workspace")))
CODE_ROOT = _default_code_root if _default_code_root.exists() else REPO_ROOT

# AI 服务（M7）：本地 / SSH 隧道 OpenAI 兼容端点（如 ollama / vllm / remote-tunnel）
AI_PROVIDER = os.environ.get("KRUSKAL_AI_PROVIDER", "ollama")
AI_ENDPOINT = os.environ.get("KRUSKAL_AI_ENDPOINT", "http://127.0.0.1:11434/v1")
AI_MODEL = os.environ.get("KRUSKAL_AI_MODEL", "qwen2.5:7b")
AI_API_KEY = os.environ.get("KRUSKAL_AI_API_KEY", "")
AI_TIMEOUT = int(os.environ.get("KRUSKAL_AI_TIMEOUT", "60"))
AI_TUNNEL_HINT = os.environ.get("KRUSKAL_AI_TUNNEL_HINT", "")

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


def rebind_data_dir(new_data_dir: Path | str) -> None:
    """动态重定向数据目录（支持测试隔离、沙箱迁移与多套件级联测试）。"""
    global DATA_DIR, DB_PATH, KEYWRAP_PATH, TMP_DIR
    global AUTOKEY_WRAP, AUTOKEY_KEY, LOCAL_SETTINGS_PATH
    DATA_DIR = Path(new_data_dir)
    DB_PATH = DATA_DIR / "site.db"
    LOCAL_SETTINGS_PATH = DATA_DIR / "local_settings.json"
    KEYWRAP_PATH = DATA_DIR / ".kek"
    TMP_DIR = DATA_DIR / "tmp"
    # 沙箱里密钥都收进临时数据目录，绝不碰真实主机上的密钥
    AUTOKEY_WRAP = DATA_DIR / ".kek.auto"
    AUTOKEY_KEY = DATA_DIR / ".autokey"
    ensure_layout()

    import sys
    for mod_name, mod in list(sys.modules.items()):
        if not mod or not mod_name.startswith("app"):
            continue
        if hasattr(mod, "TRASH_DIR"):
            mod.TRASH_DIR = DATA_DIR / "trash"
        if hasattr(mod, "NOTES_DIR"):
            mod.NOTES_DIR = DATA_DIR / "notes"
        if hasattr(mod, "IMAGES_DIR"):
            mod.IMAGES_DIR = DATA_DIR / "images"
        if hasattr(mod, "DIARY_DIR"):
            mod.DIARY_DIR = DATA_DIR / "diary"
        if hasattr(mod, "PAPERS_DIR"):
            mod.PAPERS_DIR = DATA_DIR / "papers"
        if hasattr(mod, "WB_DIR"):
            mod.WB_DIR = DATA_DIR / "workbench"
        if hasattr(mod, "CAPTURES_DIR"):
            mod.CAPTURES_DIR = DATA_DIR / "workbench" / "captures"
        if hasattr(mod, "ALBUM_DIR"):
            mod.ALBUM_DIR = DATA_DIR / "album"
        if hasattr(mod, "CARDS_DIR"):
            mod.CARDS_DIR = DATA_DIR / "cards"
        if hasattr(mod, "DAYNOTE_DIR"):
            mod.DAYNOTE_DIR = DATA_DIR / "daynote"
        if hasattr(mod, "NOTE_PATH"):
            mod.NOTE_PATH = DATA_DIR / "daynote" / "note.md"
        if hasattr(mod, "INDEX_PATH"):
            mod.INDEX_PATH = DATA_DIR / "album" / "_index.json"
        if hasattr(mod, "MAP_PATH"):
            mod.MAP_PATH = DATA_DIR / "share" / "_map.json"
        if hasattr(mod, "HOLIDAY_DIR"):
            mod.HOLIDAY_DIR = DATA_DIR / "holidays"
        if hasattr(mod, "IDEAS_DIR"):
            mod.IDEAS_DIR = DATA_DIR / "ideas"
        if hasattr(mod, "SHARE_DIR"):
            mod.SHARE_DIR = DATA_DIR / "share"
        if hasattr(mod, "ASST_DIR"):
            mod.ASST_DIR = DATA_DIR / "assistant"
        if hasattr(mod, "RECORDS_DIR"):
            mod.RECORDS_DIR = DATA_DIR / "assistant" / "records"
        if hasattr(mod, "THREADS_DIR"):
            mod.THREADS_DIR = DATA_DIR / "assistant" / "threads"
        if hasattr(mod, "RUNS_DIR"):
            mod.RUNS_DIR = DATA_DIR / "tmp" / "runs"
