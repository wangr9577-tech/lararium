# Kruskal 科研工作台 · 完整路线图（设计文档）

> 目标：在 Kruskal（个人站）基础上扩展为**深度学习 + Agent 方向的科研工作台**，
> 覆盖科研全流程闭环：**读 → 记 → 想 → 算 → 写 → 发**。
> 本文档细化到 **页面 / API / 数据模型** 三级，供实现时直接照做。
> 状态：方案待审核，未开始编码。

---

## 0. 现状盘点（复用基础）

| 已有资产 | 位置 | 可复用点 |
|---|---|---|
| 加密文件基建 | `backend/app/vault.py`（AES-GCM 整文件加解密） | 所有新模块正文存储直接复用 |
| 论文库（PDF+元数据+高亮） | `backend/app/routers/papers.py`，`data/papers/` | 升级为文献库，不重写 |
| 笔记 md→PDF 导出 | `routers/notes.py` + pandoc/TinyTeX | 写作资产导出直接复用 |
| SQLite 元数据库 | `backend/app/db.py`（`_SCHEMA` 常量） | 新表按同一模式追加 |
| 图表库 | 前端依赖 `echarts` | 实验指标曲线直接复用 |
| 登录/鉴权/设置 | `routers/auth.py`、`routers/settings.py` | 所有新路由挂同一鉴权 |
| 生词本复习逻辑 | `routers/vocab.py` | 卡片复习可借鉴其间隔重复思路 |

**本地 AI 底座（已实测可用）**
- vLLM 服务已在 `127.0.0.1:8000` 运行，模型 `qwen3.8-27b`（OpenAI 兼容 API，`/v1/chat/completions` 实测通过）
- 机器 7×RTX 3090；Kruskal 只做本地客户端，数据不出服务器
- 前端划词翻译已存在（免费 API），未来可加「本地 LLM 翻译/解释」选项

**明确不改动（红线）**
- 现有 11 页壳、登录/加密基建、日记/日程/生词本/记账等已有模块的**数据和功能**
- 全部采用**新增 router + 新增页面**方式扩展，向后兼容；不加删改已有表

---

## 1. 总体架构与模块划分

```
┌─────────────────────────── Kruskal 科研工作台 ───────────────────────────┐
│  读 ── M1 文献库（升级） → 高亮/批注 ──┐                                  │
│                                        ├──→ M2 卡片笔记（原子化知识）      │
│  想 ── M3 想法 Backlog ←───────────────┘        │ 双链                   │
│  编 ── M8 代码工作区（浏览 / 编辑 / 运行）──┐    ▼                        │
│  算 ── M4 实验记录本 ←─────────────┴──→ 与 M3/M2/M8 关联                  │
│  写 ── M5 写作资产库（BibTeX/句式/图表）+ 导出                              │
│  发 ── M6 投稿跟踪 + 科研周报                                              │
│  横切 ── M7 AI 本地小模型服务（vLLM qwen3.8-27b，全程可开关）               │
└────────────────────────────────────────────────────────────────────────────┘
```

**分期交付（每期都是可用闭环）**

| 期 | 内容 | 闭环 | 目标（验收） |
|---|---|---|---|
| **P1** | M1 文献库升级 + M2 卡片笔记 + M3 想法 Backlog + **M8 代码工作区（浏览/编辑）** + M7-AI摘要 | 读→记→想 | 上传论文→读→高亮→一键成卡片→挂想法；浏览器直接改代码 |
| **P2** | M4 实验记录本（含指标对比） + **M8 运行能力** + M7-实验润色 | 编→算 | 改代码→后台跑实验→记 run/指标→多 run 曲线对比→写结论 |
| **P3** | M5 写作资产 + M6 投稿跟踪/周报 + M7-润色/草稿 | 写→发 | 实验→素材→投稿→周报闭环 |

每期内部再分实现步骤，见 §9。

---

## 2. M1 文献库全生命周期（升级现有 papers）

### 2.1 功能
- 元数据补全：`doi`、`arxiv_id`、`year`、`venue`、`authors`、`abstract`、`keywords`
- 阅读状态扩展：`想读/在读/精读/读完/搁置`（现为 想读/在读/读完）
- 论文间关联：`related`（相关工作/引用链），列表互跳
- 一键导入元数据：输入 arXiv id 或 DOI → 自动拉取（arXiv API / doi.org，走服务器网络）
- 高亮 → 一键生成卡片（调用 M2 接口）
- 列表增强：状态/标签/分类筛选、搜索（标题+作者+标签）

### 2.2 页面（前端）
| 文件 | 说明 |
|---|---|
| `frontend/src/views/Papers.vue` | **改造**：加筛选/搜索/详情侧栏/元数据编辑表单/关联管理 |
| `frontend/src/components/PaperReader.vue` | **增强**：工具栏加「高亮→生成卡片」「AI 摘要」 |

### 2.3 API（后端 `routers/papers.py` 扩展）
| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/papers` | 已有，返回结构加 meta 新字段 |
| `POST` | `/api/papers` | 已有（上传 PDF），form 增加抽象字段 |
| `PUT` | `/api/papers/{id}` | **新增**：更新元数据（含 doi/arxiv_id/authors/abstract/keywords） |
| `POST` | `/api/papers/import-meta` | **新增**：`{source:"arxiv"|"doi", id}` → 拉元数据写回 |
| `POST` | `/api/papers/{id}/related` | **新增**：`{related_id}` 建立双向关联 |
| `POST` | `/api/papers/{id}/to-card` | **新增**：`{hl_id?, text}` → 调 M2 建卡片，返回 card_id |

### 2.4 数据模型（沿用加密 JSON，与现有 papers 一致）
`data/papers/<id>.json` 元数据扩展：
```jsonc
{
  "title": "...", "author": "...",
  "doi": "", "arxiv_id": "", "year": "", "venue": "",
  "authors": [], "abstract": "", "keywords": [],
  "status": "在读",            // 想读/在读/精读/读完/搁置
  "tags": [], "category": "", "subcategory": "",
  "related_ids": [],          // 论文关联
  "page_count": 0, "link": "", "note": ""
}
```
> 兼容：旧文件缺字段 → 前端读时默认空值（`_load_meta` 已做 `{**m, "id": id}` 合并，缺字段不炸）。

---

## 3. M2 卡片笔记（原子化知识库）

### 3.1 功能
- 卡片 = 一个原子想法/摘录/自己的话，正文 Markdown，可含公式（katex 已有）
- 来源：论文高亮一键生成 / 手动新建 / 从想法转化
- 标签系统（多标签） + **双链**（卡片↔卡片、卡片↔论文）
- 列表：标签筛选、全文搜索、按来源论文分组
- 复习：卡片标记 `reviewed_at`，参考在研（可选，P2 后做）

### 3.2 页面
| 文件 | 说明 |
|---|---|
| `frontend/src/views/Cards.vue` | 卡片流列表 + 标签筛选 + 新建入口 |
| `frontend/src/views/CardEdit.vue` | 编辑/双链面板（复用 `MarkdownEditor.vue`） |
| `frontend/src/views/CardView.vue` | 阅读页：渲染 md + 展示双链 + 关联论文跳转 |

### 3.3 API
| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/cards` | 列表，query：`tag`/`q`/`paper_id` |
| `POST` | `/api/cards` | 新建 `{title, content, tags[], paper_id?, ref_type?}` |
| `PUT` | `/api/cards/{id}` | 更新 |
| `DELETE` | `/api/cards/{id}` | 删除（仅本模块数据） |
| `POST` | `/api/cards/{id}/links` | 双链：`{target_type:"card"|"paper", target_id}` |
| `GET` | `/api/cards/{id}` | 详情（含双向链接列表） |

### 3.4 数据模型
- 元数据索引：SQLite 新表（`db.py` 追加）
```sql
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
```
- 正文：`data/cards/<card_id>.md`（vault 加密），标题/tags/关联走 SQLite
- 文件目录：`config.SUBDIRS` 增加 `"cards"`

---

## 4. M3 研究想法 Backlog

### 4.1 功能
- 想法条目：标题 + 一句话描述 + 正文（md）
- 状态机：`backlog(待办) / active(进行中) / done(完成) / dropped(放弃)`
- 优先级：高/中/低
- 与论文/卡片/实验双向关联（`link`）

### 4.2 页面
| 文件 | 说明 |
|---|---|
| `frontend/src/views/Ideas.vue` | 看板式列表（按状态分列），新建/编辑抽屉 |
| `frontend/src/views/IdeaEdit.vue` | 编辑：正文 + 关联选择器 |

### 4.3 API
| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/ideas` | 列表，query：`status` |
| `POST` | `/api/ideas` | 新建 |
| `PUT` | `/api/ideas/{id}` | 更新（含状态流转） |
| `DELETE` | `/api/ideas/{id}` | 删除 |
| `POST` | `/api/ideas/{id}/links` | 关联 `{target_type:"paper"|"card"|"experiment", target_id}` |

### 4.4 数据模型
```sql
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
```
- 正文：`data/ideas/<idea_id>.md`（vault 加密）
- 目录：`config.SUBDIRS` 增加 `"ideas"`

---

## 5. M4 实验记录本（DL + Agent 实验管理，核心模块）

### 5.1 设计原则
- **只做记录，不托管产物**：checkpoint/日志/数据集等大文件**留在原处**，
  实验库仅存**绝对路径引用** + 哈希/大小快照 —— 严守「用户数据只读、不复制」红线
- 一次实验 = 一个 `experiment`；可包含多次 `run`（不同 seed/配置）
- 每个 run 记录：配置快照（JSON）、git commit、环境（conda env / Python 版本 / CUDA）、
  指标序列、日志路径、checkpoint 路径、说明
- 指标支持曲线对比：同一实验多 run 曲线叠加（echarts）

### 5.2 页面
| 文件 | 说明 |
|---|---|
| `frontend/src/views/Experiments.vue` | 实验列表（状态/时间排序）+ 图表对比入口 |
| `frontend/src/views/ExperimentDetail.vue` | 详情：目标/假设/结论 + runs 表格 + 曲线对比 |
| `frontend/src/views/ExperimentEdit.vue` | 新建/编辑：表单 + 配置 JSON 编辑器（code-mirror JSON 已有依赖） |
| `frontend/src/components/RunChart.vue` | **新组件**：多 run 指标曲线叠加（echarts） |

### 5.3 API
| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/experiments` | 列表 |
| `POST` | `/api/experiments` | 新建 |
| `GET` | `/api/experiments/{id}` | 详情（含 runs） |
| `PUT` | `/api/experiments/{id}` | 更新（含结论） |
| `DELETE` | `/api/experiments/{id}` | 删除（仅删记录 JSON，不碰产物文件） |
| `POST` | `/api/experiments/{id}/runs` | 新建 run：`{name, config, git_commit, env, metrics[], log_path, ckpt_path}` |
| `PUT` | `/api/experiments/runs/{rid}` | 更新 run |
| `DELETE` | `/api/experiments/runs/{rid}` | 删除 run |
| `GET` | `/api/experiments/{id}/compare?run_ids=a,b` | 返回多 run 指标序列用于叠加 |

### 5.4 数据模型
- SQLite 表：
```sql
CREATE TABLE IF NOT EXISTS experiments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',    -- active/paused/done/archived/failed
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
    env_info TEXT NOT NULL DEFAULT '',        -- conda env / python / cuda
    metrics_json TEXT NOT NULL DEFAULT '{}',  -- 序列 {step: {metric: value}}
    log_path TEXT NOT NULL DEFAULT '',
    ckpt_path TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(experiment_id, name)
);
```
- 指标 `metrics_json` 结构：`{"accuracy": {"0": 0.1, "100": 0.55, ...}, "loss": {...}}`，
  个人实验规模（≤数千 step）单表够用；超大序列时升级为 `data/experiments/<id>/runs/<rid>.jsonl`（加密）

### 5.5 与 M3/M2 关联
- `POST /api/ideas/{id}/links` 支持 `target_type="experiment"`
- 实验创建表单可选绑定 idea（从想法发起实验）和论文（相关工作）

---

## 6. M5 写作资产库 + M6 投稿跟踪/周报（P3）

### 6.1 M5 写作资产
| 子模块 | 功能 | 页面 | 数据 |
|---|---|---|---|
| BibTeX | 从论文库自动生成/手动编辑引用条目 | `Writing.vue`（tab: BibTeX） | SQLite `bib_entries(key, entry_type, fields_json, paper_id)` |
| 句式库 | 常用学术句段（可标注用途：intro/related/limitation） | `Writing.vue`（tab: Snippets） | SQLite `snippets(id, title, content, tags)` |
| 图资产 | 实验产物图引用 + caption + 关联 run | `Writing.vue`（tab: Figures） | SQLite `figures(id, title, caption, file_path, run_id, created_at)`（只存路径引用） |

API：`/api/writing/bib`、`/api/writing/snippets`、`/api/writing/figures` 各一套 CRUD。
> BibTeX 自动生成：后端读论文库元数据（title/authors/year/venue/doi）→ 拼 bibtex 字符串，可手动修正后落库。

### 6.2 M6 投稿跟踪 + 周报
- 投稿：`Submissions.vue`，状态机 `draft→submitted→under_review→(major|minor|accepted|rejected)`
  - SQLite `submissions(id, title, venue, status, deadline, submitted_at, notes, events_json)`
- 周报：`Report.vue`，从 M2/M3/M4 聚合本周新增（卡片/想法/实验）生成 Markdown，
  可选调 M7 本地模型起草总结 → 用户编辑 → 落为笔记（复用 notes 导出 md→PDF）

API：`/api/submissions` CRUD；`GET /api/reports/weekly`

---

## 7. M8 代码工作区（浏览 + 编辑 + 运行）

> 机器学习的代码本身就是核心科研资产。本模块提供浏览器内的代码体验：
> 目录树浏览 → 在线编辑 → 一键后台运行并看日志，全程不复制、不迁移用户代码。

### 7.1 功能
- **文件树浏览**：白名单根目录（`config.py` 新增 `CODE_ROOT`，默认
  `/mnt/data_server/home/stu_wr/deepseek-workspace`），隐藏 `.git`/`node_modules`/`__pycache__`，
  深度/条目限制防爆列表
- **在线编辑**：CodeMirror + `@codemirror/lang-python`（轻量，与现有编辑器体系一致；
  **不上 Monaco**——包大且刷新体验重）
- **保存写回真实文件**：用户点击保存才写盘（非自动），原样保存在用户自己目录
- **Git 信息**：文件/目录旁显示分支、最近提交、dirty 状态
- **运行（用户已确认纳入）**：一键后台跑脚本/训练命令，日志流式输出到页面；
  默认超时 + kill 接口 + 并发上限
- **与 M4 打通**：`experiments.code_path` 记录代码目录，实验详情可跳转工作区对应目录

### 7.2 页面
| 文件 | 说明 |
|---|---|
| `frontend/src/views/Code.vue` | 工作区主页面：左文件树 + 右编辑器 + 底部输出面板 |
| `frontend/src/components/FileTree.vue` | 目录树组件（基于 Element Plus Tree） |

### 7.3 API（后端新增 `routers/fs.py`）
| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/fs/tree?path=` | 目录树（深度≤4、条目≤200，隐藏 .git/node_modules） |
| `GET` | `/api/fs/file?path=` | 读文件（≤1MB），附 git 分支/commit |
| `PUT` | `/api/fs/file` | 保存 `{path, content}` 写回真实文件 |
| `GET` | `/api/fs/git?path=` | 仓库状态（分支/最近提交/dirty） |
| `POST` | `/api/fs/run` | 启动后台任务 `{workdir, cmd[], env?, timeout?}` |
| `GET` | `/api/fs/run/{rid}/log` | 拉取任务日志（轮询，含 running/done/killed） |
| `POST` | `/api/fs/run/{rid}/kill` | 终止任务 |
| `GET` | `/api/fs/run` | 活动任务列表 |

### 7.4 数据模型
- **不新增表**：文件系统即真相，代码留原处（不复制、不落库、不额外加密）
- M4 `experiments` 表新增 `code_path` 字段（该表 P2 才首次创建，直接纳入建表 DDL，无迁移）

### 7.5 安全与红线（重点）
- 路径白名单：所有路径 `resolve()` 后必须位于 `CODE_ROOT` 内，防 `../` 穿越到系统目录
- **浏览默认只读**；写入必须用户主动点击保存；自动化测试绝不触碰真实代码目录
- 单文件 ≤1MB；目录树深度 ≤4、条目 ≤200
- 运行任务：默认超时 30min、并发上限 2、kill 接口保底；任务日志保留在 `data/tmp/runs/`（不落 SQLite）
- 沿用现有登录鉴权，仅绑定 127.0.0.1

### 7.6 分期
- **P1**：浏览 + 编辑 + git 信息（tree/file/git 三接口 + 前端两组件）
- **P2**：运行能力（run/log/kill + 输出面板 + 并发/超时管控）

---

## 8. M7 AI 本地小模型服务（横切，全程可开关）

### 8.1 架构
- 后端新增 `backend/app/services/llm.py`：OpenAI 兼容客户端（`httpx` 或 `openai` sdk），
  base_url 由设置读取（默认 `http://127.0.0.1:8000/v1`），model=`qwen3.8-27b`
- 设置页新增「AI 服务」区块：`ai_enabled`（默认关）、`ai_endpoint`、`ai_model`、`ai_timeout`
- 所有 AI 调用**失败静默降级**（返回错误标记，前端提示「AI 服务不可用」，不影响主功能）
- **安全红线**：只连 `127.0.0.1`，任何内容不出服务器

### 8.2 功能点（按分期）
| 期 | 功能 | API | 说明 |
|---|---|---|---|
| P1 | 论文摘要 | `POST /api/ai/summarize {paper_id}` | PyMuPDF 抽文本前 N 页 → LLM 摘要（需装 `pymupdf` 到 site env，清华镜像） |
| P1 | 划词解释（增强翻译） | 复用 `translate` 路由加 source=`llm` | 可选，非必须 |
| P2 | 实验/结论润色 | `POST /api/ai/polish {text, kind}` | 帮写 experimental 段落/结论 |
| P3 | 周报起草 | `POST /api/ai/report-draft {items[]}` | 聚合条目 → 起草周报 |

> P1 只做「摘要」一项，验证 vLLM 链路；其余按需求追加，避免过度设计。

### 8.3 PDF 文本抽取（依赖变更）
```bash
/mnt/data_server/home/stu_wr/miniconda3/envs/site/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pymupdf
```
扫描版 PDF（无文本层）→ 返回 `text_available=false`，前端提示无法摘要。

---

## 9. 实施步骤清单（按 P1 → P2 → P3）

### P1（读→记→想闭环 + 代码工作区 + AI 摘要）
1. 后端：`config.py` SUBDIRS 加 `cards`/`ideas`，新增 `CODE_ROOT` 配置；`db.py` 追加 cards/card_links/ideas/idea_links 表
2. 后端：新建 `routers/cards.py`、`routers/ideas.py`（CRUD + 双链）；注册进 `main.py`
3. 后端：扩展 `routers/papers.py`（meta 更新、import-meta、related、to-card）
4. 后端：新建 `routers/fs.py`（tree/file/git，含路径白名单校验）；注册进 `main.py`
5. 后端：新建 `services/llm.py` + `services/pdf_text.py` + `routers/ai.py`（仅 summarize）
6. 后端：`routers/settings.py` 增加 AI 配置字段
7. 前端：`router/index.ts` 注册 `/cards`、`/ideas`、`/code`；`AppShell.vue` 加导航入口
8. 前端：`Cards.vue`/`CardEdit.vue`/`CardView.vue`、`Ideas.vue`/`IdeaEdit.vue`、`Code.vue`/`FileTree.vue`；依赖加 `@codemirror/lang-python`
9. 前端：`Papers.vue` 改造（筛选/详情/元数据编辑）、`PaperReader.vue` 加「AI 摘要」「高亮→卡片」
10. 前端：`Settings.vue` 加 AI 配置区块

### P2（编→算闭环）
1. 后端：`db.py` 追加 experiments/experiment_runs 表（含 code_path）；新建 `routers/experiments.py`
2. 后端：`routers/fs.py` 加 run/log/kill + `services/runner.py`（后台任务、超时、并发上限 2）
3. 前端：`Experiments.vue`/`ExperimentDetail.vue`/`ExperimentEdit.vue` + `RunChart.vue`
4. 前端：`Code.vue` 加底部输出面板（任务日志流）；实验详情加「打开代码目录」入口
5. 后端：`routers/ai.py` 加 `/polish`；`Settings` 复用
6. 前端：实验详情页加「润色结论」按钮

### P3（写→发）
1. 后端：`db.py` 追加 bib_entries/snippets/figures/submissions；新建 `routers/writing.py`、`routers/submissions.py`、`routers/reports.py`
2. 前端：`Writing.vue`、`Submissions.vue`、`Report.vue` + 路由/导航
3. 后端：`routers/ai.py` 加 `/report-draft`
4. 端到端联调：实验→图资产→投稿→周报

---

## 10. 影响面与风险

### 影响面（本次扩展全部**新增**）
- 后端改动文件：`config.py`（加目录 + CODE_ROOT）、`db.py`（加表）、`main.py`（注册路由）、`settings.py`（加字段）
- 后端新增文件：`routers/{cards,ideas,experiments,writing,submissions,reports,ai,fs}.py`、`services/{llm,pdf_text,runner}.py`
- 前端改造：`AppShell.vue`（导航）、`router/index.ts`（路由）、`Papers.vue`、`PaperReader.vue`、`Settings.vue`
- 前端新增：8 个 view（Cards/CardEdit/CardView/Ideas/IdeaEdit/Code/Experiments/ExperimentDetail/ExperimentEdit…）+ `FileTree.vue` + `RunChart.vue`
- 依赖：`site` 环境追加 `pymupdf`；前端追加 `@codemirror/lang-python`（均走国内镜像）

### 风险与对策
| 风险 | 对策 |
|---|---|
| SQLite 表结构变更破坏旧库 | 全部 `CREATE TABLE IF NOT EXISTS`，不动旧表旧列 |
| 元数据字段扩展破坏旧文件 | 读取时缺字段给默认值（`_load_meta` 已兼容） |
| 大 run 指标撑爆单表 | 超限升级 jsonl 加密文件（设计已留口） |
| 扫描版 PDF 无法摘要 | `text_available=false` 优雅降级 |
| vLLM 未启动/被占用 | `ai_enabled` 默认关，调用失败提示、不阻塞主功能 |
| AI 内容出错 | 所有产出为「草稿」，人工确认后入库（周报/结论均如此） |
| 代码工作区路径穿越 | 白名单根 `resolve()` 前缀校验，越界 403 |
| 在线编辑误改用户代码 | 默认只读 + 用户主动点保存才写盘 + 单文件 ≤1MB |
| 后台任务失控占资源 | 默认超时 30min + 并发上限 2 + kill 接口 + 日志留存 tmp |

### 测试红线（沿用项目约定）
- 自动化测试只创建带「示例/演示/TS_测试」前缀的**临时数据**，用完仅删本会话亲手创建并记录了 id 的条目
- 绝不删除/修改用户已有论文、笔记、实验产物文件；实验路由删除仅删自身 JSON 记录

---

## 11. 工作量预估（供排期）

| 期 | 后端 | 前端 | 合计（人日） |
|---|---|---|---|
| P1 | 5~6 | 5~6 | ~11 |
| P2 | 4~5 | 4~5 | ~9 |
| P3 | 4 | 3~4 | ~7 |