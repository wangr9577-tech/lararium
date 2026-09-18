"""SQLite 访问：线程本地连接 + 上下文自动提交/回滚。

内容正文（日记/笔记等）走文件系统（后续功能期加密落盘），
这里只存结构化、低敏元数据：用户/会话/设置/日程任务。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from . import config

_local = threading.local()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens(
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    date TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(date);
CREATE TABLE IF NOT EXISTS focus(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start TEXT NOT NULL,
    end TEXT,
    minutes INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_focus_start ON focus(start);
CREATE TABLE IF NOT EXISTS schedule(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'daily',
    type TEXT NOT NULL DEFAULT 'task',
    title TEXT NOT NULL,
    time_start TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedule_date ON schedule(date);
CREATE TABLE IF NOT EXISTS vocab(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    meaning TEXT NOT NULL DEFAULT '',
    sentence TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    added TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS anniversaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'expense',
    amount INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger(date);
CREATE TABLE IF NOT EXISTS ielts_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ielts_section ON ielts_items(section);
CREATE TABLE IF NOT EXISTS ielts_plan_done(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week TEXT NOT NULL,
    slot TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ielts_plan_ws ON ielts_plan_done(week, slot);
CREATE TABLE IF NOT EXISTS notes_folders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    parent TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
-- 子文件夹：目录以全路径（parent/name，如 'A/B'）标识，同 module 内 (module, path) 唯一，
-- 允许不同父目录下重名（A/词汇 与 B/词汇）。老库的 (module, name) 唯一索引
-- 由 init_db 迁移切换（后端已按 path 写入）。
CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_folders_mp ON notes_folders(module, path);

-- ============ 科研工作台新增表（P1/P2/P3，全部新增，不动旧表） ============
CREATE TABLE IF NOT EXISTS cards(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    paper_id TEXT NOT NULL DEFAULT '',
    ref_type TEXT NOT NULL DEFAULT '',      -- highlight | idea | manual
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS card_links(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,              -- card | paper
    target_id TEXT NOT NULL,
    UNIQUE(card_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS ideas(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'backlog',   -- backlog/active/done/dropped
    priority TEXT NOT NULL DEFAULT 'medium',  -- high/medium/low
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_links(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,                -- paper/card/experiment
    target_id TEXT NOT NULL,
    UNIQUE(idea_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS experiments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',    -- active/paused/done/archived/failed
    code_path TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    conclusion TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    git_commit TEXT NOT NULL DEFAULT '',
    env_info TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    log_path TEXT NOT NULL DEFAULT '',
    ckpt_path TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(experiment_id, name)
);
CREATE TABLE IF NOT EXISTS bib_entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bib_key TEXT NOT NULL,
    entry_type TEXT NOT NULL DEFAULT 'misc',
    fields_json TEXT NOT NULL DEFAULT '{}',
    paper_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snippets(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    use_for TEXT NOT NULL DEFAULT '',         -- intro/related/limitation/other
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS figures(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    run_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    venue TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',     -- draft/submitted/under_review/major/minor/accepted/rejected
    deadline TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    events_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def db():
    conn = _conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    config.ensure_layout()
    with db() as conn:
        conn.executescript(_SCHEMA)
        # vocab 复习字段迁移（老库补列）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab)")}
        for name, decl in (
            ("box", "INTEGER NOT NULL DEFAULT 0"),
            ("reviews", "INTEGER NOT NULL DEFAULT 0"),
            ("next_due", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE vocab ADD COLUMN {name} {decl}")
        # notes_folders 子文件夹迁移（老库补 parent/path 列，幂等）：
        #   parent=父目录全路径（''=顶层），path=自身全路径（顶层=名字）。
        nf_cols = {r[1] for r in conn.execute("PRAGMA table_info(notes_folders)")}
        for name, decl in (
            ("parent", "TEXT NOT NULL DEFAULT ''"),
            ("path", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in nf_cols:
                conn.execute(f"ALTER TABLE notes_folders ADD COLUMN {name} {decl}")
        # 回填既有目录 path=全路径（只填空值，幂等；已写入的 path 不会被覆盖）
        conn.execute(
            "UPDATE notes_folders SET path = CASE WHEN parent = '' THEN name "
            "ELSE parent || '/' || name END WHERE path = ''"
        )
        # 索引切换（幂等）：后端现按全路径标识目录，唯一约束须基于 (module, path)
        # —— 老库的 (module, name) 唯一索引删除（否则不同父目录下重名会撞约束），
        # 数据模型期建的 (module, path) 非唯一索引重建为唯一。
        conn.execute("DROP INDEX IF EXISTS idx_notes_folders_mn")
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_notes_folders_mp'"
        ).fetchone()
        if row is None or "UNIQUE" not in (row["sql"] or "").upper():
            conn.execute("DROP INDEX IF EXISTS idx_notes_folders_mp")
            conn.execute(
                "CREATE UNIQUE INDEX idx_notes_folders_mp ON notes_folders(module, path)"
            )
