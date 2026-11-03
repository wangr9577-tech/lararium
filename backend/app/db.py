"""SQLite 访问：线程本地连接 + 上下文自动提交/回滚。

内容正文（日记/笔记等）走文件系统（后续功能期加密落盘），
这里只存结构化、低敏元数据：用户/会话/设置/日程任务。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

_local = threading.local()

# ledger 表单独抽成常量：init_db 里做 kind 约束迁移时要复用同一份 DDL
# （老库要么没 CHECK，要么是早期只允许 income/expense 的版本——见 init_db）。
_LEDGER_DDL = """CREATE TABLE IF NOT EXISTS ledger(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    -- CHECK 只对新建库生效（老库命中本语句是 no-op，SQLite 也加不了表级约束）：
    -- API 层已校验，这里再兜一层，防坏数据落库污染余额统计。
    -- repay=还款（钱包欠款功能）：冲减渠道欠款，同时减少现金余额。
    kind TEXT NOT NULL DEFAULT 'expense' CHECK(kind IN ('income', 'expense', 'repay')),
    amount INTEGER NOT NULL CHECK(amount > 0),
    category TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
"""

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
""" + _LEDGER_DDL + """
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

-- ============ 工作台（事项树 + 随手收集 + 相关资料链接，全部新增，不动旧表） ============
-- 正文一律走 vault 加密文件（data/workbench/…），这里只存索引与低敏元数据：
--   items.summary = 当前思路的短摘要（列表页要显示，不读正文即可渲染，与笔记列表
--   的 frontmatter 元数据同级；正文全文仍然只在加密文件里）。
CREATE TABLE IF NOT EXISTS workbench_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,                          -- NULL=主事项；一层子事项
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,            -- 同级显示顺序（小在前）
    archived INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',           -- 当前思路摘要（保存时由正文截取）
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wb_items_parent ON workbench_items(parent_id, archived, sort);
CREATE TABLE IF NOT EXISTS workbench_entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,                   -- 所属事项（必填）
    created_at TEXT NOT NULL,                   -- 小记时间（按时间追加）
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wb_entries_item ON workbench_entries(item_id, created_at);
CREATE TABLE IF NOT EXISTS workbench_captures(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,                            -- NULL=未归类收集箱
    source TEXT NOT NULL DEFAULT '',            -- 来源名（AI 对话 / 小红书…，可空）
    url TEXT NOT NULL DEFAULT '',               -- 原链接（可空，允许小红书等长串）
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wb_captures_item ON workbench_captures(item_id, archived, created_at);
-- 相关资料：事项 → 现有论文/博客笔记的链接（只存入口，不复制正文）
CREATE TABLE IF NOT EXISTS workbench_links(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,                  -- note | paper
    target_id TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(item_id, target_type, target_id)     -- 同一事项内同一资料只出现一次（幂等）
);
CREATE INDEX IF NOT EXISTS idx_wb_links_item ON workbench_links(item_id, sort);
CREATE INDEX IF NOT EXISTS idx_wb_links_target ON workbench_links(target_type, target_id);

-- ============ 助手模块（通知聚合 + 稍后看 + 日程/工作台/笔记联动） ============
CREATE TABLE IF NOT EXISTS assistant_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER,                     -- 关联原 workbench_captures.id（若由收集箱发起）
    wb_item_id INTEGER,                     -- 关联工作台事项 id
    kind TEXT NOT NULL DEFAULT 'later' CHECK(kind IN ('notice', 'later')),
    title TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',   -- text / image / file / url
    source_url TEXT NOT NULL DEFAULT '',
    user_note TEXT NOT NULL DEFAULT '',     -- 用户输入的备注/意图指令
    category TEXT NOT NULL DEFAULT '',      -- 论文 / 项目 / 教程 / 视频 / 工具 / 事务 / 其他
    tags TEXT NOT NULL DEFAULT '[]',        -- JSON 数组，AI 建议与用户标签
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'ready', 'failed')),
    read_state TEXT NOT NULL DEFAULT 'unread' CHECK(read_state IN ('unread', 'read', 'noted')),
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asst_rec_kind_arch ON assistant_records(kind, archived, created_at);

CREATE TABLE IF NOT EXISTS assistant_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,                    -- 事项聚合名称
    summary TEXT NOT NULL DEFAULT '',       -- 当前最新事实摘要
    highlights TEXT NOT NULL DEFAULT '[]',  -- 注意事项/材料清单 (JSON)
    latest_change TEXT NOT NULL DEFAULT '', -- 与上一版相比的最新变动
    deadline_date TEXT NOT NULL DEFAULT '', -- 有效 DDL 日期 (YYYY-MM-DD)
    deadline_time TEXT NOT NULL DEFAULT '', -- 有效 DDL 时间 (HH:MM)
    has_conflict INTEGER NOT NULL DEFAULT 0,-- 是否存在未决冲突
    wb_item_id INTEGER,                     -- 可选：关联工作台事项 id
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asst_threads_status ON assistant_threads(status, deadline_date);

CREATE TABLE IF NOT EXISTS assistant_thread_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES assistant_threads(id) ON DELETE CASCADE,
    record_id INTEGER NOT NULL REFERENCES assistant_records(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL DEFAULT 0,    -- 该线程内的到达序号
    change_type TEXT NOT NULL DEFAULT 'new' CHECK(change_type IN ('new', 'update', 'postpone', 'cancel', 'conflict')),
    change_reason TEXT NOT NULL DEFAULT '', -- AI 判定变更依据
    received_at TEXT NOT NULL,              -- 实际通知发生/导入时间
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asst_ts_thread ON assistant_thread_sources(thread_id, sequence);

CREATE TABLE IF NOT EXISTS assistant_schedule_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER REFERENCES assistant_threads(id) ON DELETE CASCADE,
    record_id INTEGER REFERENCES assistant_records(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES schedule(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'ddl' CHECK(role IN ('ddl', 'task', 'event')),
    locked_by_user INTEGER NOT NULL DEFAULT 0,  -- 用户是否手动修改过（锁定防覆盖）
    user_dismissed INTEGER NOT NULL DEFAULT 0,  -- 用户在日程页删除过（标记后重试不再生成）
    created_at TEXT NOT NULL,
    UNIQUE(thread_id, schedule_id)
);

CREATE TABLE IF NOT EXISTS assistant_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES assistant_records(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'pending',  -- pending / parsing / extract / reconcile / finalize / failed / paused_locked
    retry_count INTEGER NOT NULL DEFAULT 0,
    dek_epoch INTEGER NOT NULL DEFAULT 0,   -- 发起时的密钥世代号，用于上锁防御
    error_msg TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asst_jobs_stage ON assistant_jobs(stage, updated_at);

CREATE TABLE IF NOT EXISTS assistant_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES assistant_records(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK(target_type IN ('note', 'workbench_item')),
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(record_id, target_type, target_id)
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


def close_conn() -> None:
    """关闭并清理当前线程的数据库连接，用于测试套件隔离与资源清理。"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


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
        # ledger kind 约束迁移（幂等，纯搬运不删数据）：
        # 新库/新定义允许 'repay'（钱包欠款功能的还款记录），但早期建库留下的
        # CHECK(kind IN ('income','expense')) 会让插入还款记录直接 IntegrityError。
        # 检测到旧约束就重建表：RENAME → 建新表 → 逐行原样搬 → 删旧表 → 重建索引。
        lrow = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone()
        lddl = (lrow["sql"] or "") if lrow else ""
        if "CHECK" in lddl.upper() and "repay" not in lddl:
            conn.execute("ALTER TABLE ledger RENAME TO ledger_pre_repay")
            conn.execute(_LEDGER_DDL.replace("IF NOT EXISTS ", "", 1))
            conn.execute(
                "INSERT INTO ledger(id, date, kind, amount, category, note, created) "
                "SELECT id, date, kind, amount, category, note, created FROM ledger_pre_repay")
            conn.execute("DROP TABLE ledger_pre_repay")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger(date)")
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
        # assistant_records 补 wb_item_id 列
        asst_cols = {r[1] for r in conn.execute("PRAGMA table_info(assistant_records)")}
        if "wb_item_id" not in asst_cols:
            conn.execute("ALTER TABLE assistant_records ADD COLUMN wb_item_id INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_asst_rec_wb ON assistant_records(wb_item_id)")
    # P2-L5：文件级双保险——数据目录已是 700，库文件与 WAL 附属再收紧为仅属主可读写。
    # 放在 init_db 尾部随每次启动幂等执行（WAL 附属文件重建后的默认权限也会被拧回来）。
    for suffix in ("", "-wal", "-shm"):
        try:
            p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if p.is_file():
                os.chmod(p, 0o600)
        except OSError:
            pass  # NFS 等场景 chmod 被拒不致命，目录 700 仍是第一道闸
