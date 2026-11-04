# Lararium (Kruskal) · 个人数字花园与学术工作台

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">简体中文</a>
</p>

Lararium 把白板、笔记、论文阅读、日程与生活记录放在同一个个人空间里，方便学习、研究和整理日常。

## 主要功能

### 🖊️ 白板与课件批注

将 PDF 讲义或 PPTX 课件导入为多页白板笔记，直接在页面上手写、使用荧光笔、插入图片和擦除笔迹；也可以撤销操作，为页面加宽留出自己的笔记空间。

### 📚 笔记整理与论文阅读

用 Markdown 写笔记，插入公式和表格，通过目录分类、跨目录搜索，并可导出 PDF。论文阅读器支持荧光标注、划词查词或翻译，也可以根据 arXiv ID 导入元数据。

### 🤖 智能助手与资料收集

收集通知和资料，搜索、整理事项卡片，追踪相关通知中的截止时间；可从事项查看日程或开始写笔记，也可以围绕已收集的信息提问。AI 功能需要配置模型服务。

### 📅 日程与生活记录

在日历中安排事件和截止日期，勾选任务并查看活动热力图；还可以写日记、记账、整理相册与时光机，以及使用生词本和雅思学习页面。

### 📂 项目文档

在站内浏览、搜索和编辑项目目录中的 Markdown，阅读公式和图片；保存时写回原文件，文件在别处被修改后会提示处理冲突。

## 架构

- 前端：Vue 3 + Vite + Element Plus（TypeScript）
- 后端：FastAPI (Python 3.11, conda env `site`) + SQLite（元数据）
- 内容：笔记正文和其他私有内容保存在数据目录中，正文采用 AES-256-GCM 加密
- 部署：单端口 18080，后端托管前端 dist；仅绑定 127.0.0.1（跨子网/校外走 SSH 隧道或出站隧道，见 deploy/ACCESS.md）

## 快速开始

### Windows 本机

双击 `start.bat` 启动，或用 `start_silent.vbs` 后台启动，然后打开 <http://127.0.0.1:18080/>。Windows 启动脚本设置 `KRUSKAL_LOCAL_NO_PASSWORD=1`，浏览器会自动建立本机会话，无需输入账号或密码。

### Linux / 服务器

```bash
# 1. 后端依赖（一次性）
conda create -y -n site python=3.11 pip
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt

# 2. 前端（一次性）
cd frontend && npm install --registry=https://registry.npmmirror.com && npm run build && cd ..

# 3. 启动
bash backend/start.sh            # 默认 127.0.0.1:18080，可传端口
```

## PDF 导出依赖（笔记阅读页「导出 PDF」，均为用户级安装，无需 sudo）

- pandoc：`conda install -y -n site -c conda-forge pandoc`（本机已装 3.11）
- TinyTeX + xelatex：`~/.TinyTeX`（已装，TeX Live 2026，含 xeCJK/ctex）；若换机器，用官方安装脚本并设国内镜像
- 中文字体：`~/.fonts`（Noto Serif CJK SC / SimHei / SimSun 已放）；渲染用 Noto Serif CJK SC
- 接口：`GET /api/notes/{id}/export`；临时文件在 `data/tmp`，渲染完即清

## 导入依赖（博客页「导入 PPT / 导入 PDF」）

- PDF：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pymupdf`（本机已装 1.28，纯 wheel 无需 poppler/gs）
- PPT：`python-pptx`（见 `backend/requirements.txt`，本机已装）
- 接口：`POST /api/pdf/import`、`POST /api/ppt/import`；两者都把文档逐页渲染成整页底图，
  生成一篇 `fmt=ink` 的多页白板笔记（可在任意页手写/荧光笔/插图），**服务器不保留原始文件**；
  PDF 渲染 DPI 120、页数上限 80、图像总量上限 30MB（见 `backend/app/routers/pdf.py` 常量）

## 项目文档（把其它项目的 md 挂进来看/改）

解决的问题：博客侧的笔记是**加密落盘**的（agent 读不了），项目侧的 md 是明文（网站看不见），
于是同一份东西要维护两份。做法是**不做第二份**——把项目目录挂成「文档源」，网站只当它的视图 + 可选编辑器：

- 入口：左侧导航 **项目文档**（`/projects`）；右上角「发现项目」扫描工作区候选，或「挂载目录」手填
- 只挂 md（`.md/.markdown`）：浏览、按标题/正文搜索、阅读（KaTeX 公式 + 相对路径图片）、
  编辑并**原子写回原文件**（显式保存，Ctrl/⌘+S）；文件留在原处，git 与 agent 读的都是同一份
- 挂载根只能是 `KRUSKAL_CODE_ROOT`（默认 `~/workspace`）之内的目录；源配置存在 `settings` 表，**不建表**
- 保存带文件指纹（`base_sha256`）：期间被 agent / 编辑器改过 → 409 冲突，弹「覆盖 / 载入磁盘版 / 另存为博客笔记」，**绝不静默覆盖**
- 源可标记**只读**；「移除源」只删挂载配置，**磁盘上的文件一个都不动**
- 细节与安全边界见 `docs/DOC_SOURCES.md`

## 访问方式（SSH 隧道）

服务仅绑定 `127.0.0.1:18080`，跨子网/校外一律走隧道（无需对服务器开任何端口）：

```bash
# 在你自己的电脑上执行（保持窗口开着）：
ssh -N -L 18080:127.0.0.1:18080 <user>@<server-ip>
# 然后浏览器打开 http://127.0.0.1:18080
```

> 校园网跨子网直连不可达、公网访问（Cloudflare/Tailscale 等出站隧道）的方案见 `deploy/ACCESS.md`。

上述 SSH 隧道用于独立的服务器实例。服务器默认仍使用密码登录；首次创建账户时，初始账号为 `admin`，初始密码见该服务器数据目录中的 `initial_password.txt`。本机免密码设置不会改变服务器的账户或数据，两边的内容也不会自动同步。

## 页面路线图

| 期 | 内容 |
|---|---|
| [完成] 骨架 | 本机免密码访问、服务器登录鉴权、11 页壳、主题(明/暗)、设置、真实热力图、数据加密基建、git 化与迁移脚本 |
| [完成] F1 | 首页：日程 CRUD + 打勾 + 真实热力图（每日完成%） |
| [完成] F2 | 日记：正文加密读写 + 心情/天气 + 自动保存与关页补存 + 删除进回收站 |
| [完成] F3 | 笔记编辑器（富文本工具栏 + 预览）+ md→PDF 导出（pandoc + TinyTeX/xelatex）+ 目录/子文件夹 + PPT/PDF 导入（渲染为多页白板笔记，可直接手写标注） |
| [完成] F4 | 论文库/阅读器：上传、文本层荧光笔标注、划词词典 + 免费翻译 API |
| [完成] F5 | 智能助手 (Assistant) 与本地 AI 核心：通知聚合演进与唯一有效 DDL 追踪 / 稍后看文献卡片抽取 / 笔记智能起草 / 有据追溯智能问答 / 论文摘要、润色与周报生成（支持本地 OpenAI 兼容服务与 vLLM/Ollama，失败静默降级不阻断主链路） |
| [完成] F6 | 学术个人页可编辑 + 投稿跟踪 + 学术 CV 生成 + 只读分享（快照加密，可撤销） |
| [部分] F7 | 时光机 ✅ + 相册 ✅ + 生词本复习(间隔重现) ✅ + 记账 ✅ + IELTS 备考 ✅；二次元皮肤（看板娘）未做——预留的 pixi 依赖已按决策移除，做时再加 |

## 开发

```bash
# 后端热更
cd backend && /path/to/site/bin/python -m uvicorn app.main:app --app-dir backend --reload --port 18080
# 前端热更（vite dev 5173，/api 代理到 18080）
cd frontend && npm run dev
```

## 数据与安全

- 默认数据目录为 `backend/data/`，可通过 `KRUSKAL_DATA_DIR` 指定。Windows 本机免密码模式下，备份和迁移时必须一并保留隐藏文件 `.autokey` 和 `.kek.auto`；丢失密钥可能导致正文无法解密。
- 备份：`deploy/backup.sh` 使用 SQLite 一致性快照，生成带独立备份口令的加密归档和校验文件；`deploy/restore.sh` 校验并还原，旧数据目录保留为 `data.bak-*`。本机免密码模式的密钥也在数据目录内，会随此备份一起打包；备份口令仍需妥善保存。复制运行中的数据目录时应确保 SQLite 快照一致。
- 删除可救：笔记/相册/论文/日记的删除先进 `data/trash/` 回收站，站内「回收站」可恢复或永久删除
- 运行时：`/api` 全局鉴权中间件兜底（新路由漏写 `Depends` 也不裸奔）+ 登录防爆破限流（10 分钟 10 败 → 429）+ CSP 响应头（`KRUSKAL_CSP=0` 可关）+ Markdown 渲染 DOMPurify 净化；生产关闭 `/docs`（`KRUSKAL_DEV=1` 才开）；上传流式限量，会话 token 过期即清、每用户封顶 20；sqlite 库文件 0600
- 生产启动用 `bash backend/start.sh`（默认不开 `--reload`；开发热更才加 `KRUSKAL_DEV=1`）
- Windows 本机免密码模式下，正文仍用 AES-256-GCM 加密，但 `.autokey` 和 `.kek.auto` 同处数据目录，能读取二者和数据的人可以解密。应保护本机账户、数据目录和备份；该模式仅供本机使用，不要对外暴露服务。原有密码模式及其可选的自动解锁仍适用于其他部署，不能把已有密码库直接切换成免密码模式而不先迁移密钥。
- 翻译走免费 API（有道/百度/MyMemory，可在设置切换），不占 LLM；本地/远程 LLM 可选接入用于 AI 助手与论文总结，支持 OpenAI 兼容 API、vLLM 与 Ollama，且具备无模型时的纯启发式规则优雅降级。
