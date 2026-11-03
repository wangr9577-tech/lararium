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
# 本地私有配置文件：存储用户在前端填写的私有设置（AI 渠道、API 密钥、个人配置等），
# 独立于代码文件落盘在 DATA_DIR 中，受 .gitignore 绝对忽略，严禁上传到 Git
LOCAL_SETTINGS_PATH = DATA_DIR / "local_settings.json"
KEYWRAP_PATH = DATA_DIR / ".kek"                # 数据密钥包裹文件（由主密码派生密钥加密）
KEYWRAP_JOURNAL = DATA_DIR / ".kek.journal"     # 改密两阶段日志：记新包裹，DB 提交成功后才 rename 覆盖
INIT_PW_FILE = DATA_DIR / "initial_password.txt"

# ---- 免密自动解锁（可选，默认关闭，见 app/autokey.py）----
# 包裹文件跟数据一起走（它是 .kek 之外的另一道锁，单独拿到解不开）；
# 本机密钥默认落在 DATA_DIR **之外**，因此不会被 deploy/backup.sh 打进备份包：
# 拷走备份 = 拿到 .kek 与 .kek.auto 两道都解不开的密文，仍需主密码或本机密钥。
AUTOKEY_WRAP = DATA_DIR / ".kek.auto"
AUTOKEY_KEY = Path(os.environ.get("KRUSKAL_AUTOKEY", str(REPO_ROOT / "backend" / ".autokey")))

ADMIN_USERNAME = "admin"
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
_default_code_root = Path(os.environ.get("KRUSKAL_CODE_ROOT",
                                        Path.home() / "workspace"))
CODE_ROOT = _default_code_root if _default_code_root.exists() else REPO_ROOT

# ---- 项目文档源（外部 md 挂载，见 routers/fs.py）----
# 唯一真相留在项目目录里（明文 / git 管 / agent 可读），网站只当它的视图 + 可选编辑器，
# 从根上避免「博客一份、项目一份」的分叉。只允许 CODE_ROOT 之内的目录做源。
DOC_EXTS = (".md", ".markdown")          # 只挂 md 文档（其它格式一律不挂）
DOC_MAX_BYTES = 1 << 20                  # 单文件读写上限 1MB
DOC_LIST_MAX = 200                       # 目录树每层最多返回条目（防爆列表）
DOC_SEARCH_MAX = 50                      # 搜索命中上限
DOC_SEARCH_SCAN_MAX = 4000               # 单次搜索最多扫描的文件数
DOC_SCAN_MAX_DEPTH = 8                   # 扫描（搜索/发现）最大目录深度
DOC_IMG_MAX_BYTES = 20 << 20             # md 内嵌图片（只读）上限 20MB
DOC_IMG_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
               "avif": "image/avif"}
# 噪声目录：任何深度都跳过（不进列表、不进搜索、不可读写）。
# 想挂其中的文档，在该源的 include 规则里显式写一条（如 "data/docs/**"）即可放行。
DOC_HIDE_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
                 "env", ".tox", "dist", "build", ".next", ".nuxt", ".cache", ".idea",
                 ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                 "site-packages", "data", "tmp", ".e2e-shots", ".agent-teams"}

# AI 服务（M7）：本地 / SSH 隧道 OpenAI 兼容端点（如 xmu-qwen）
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
    global DATA_DIR, DB_PATH, KEYWRAP_PATH, KEYWRAP_JOURNAL, INIT_PW_FILE, TMP_DIR
    global AUTOKEY_WRAP, AUTOKEY_KEY, LOCAL_SETTINGS_PATH
    DATA_DIR = Path(new_data_dir)
    DB_PATH = DATA_DIR / "site.db"
    LOCAL_SETTINGS_PATH = DATA_DIR / "local_settings.json"
    KEYWRAP_PATH = DATA_DIR / ".kek"
    KEYWRAP_JOURNAL = DATA_DIR / ".kek.journal"
    INIT_PW_FILE = DATA_DIR / "initial_password.txt"
    TMP_DIR = DATA_DIR / "tmp"
    # 测试隔离：沙箱里两个文件都收进临时数据目录，绝不碰真实主机上的 backend/.autokey
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
