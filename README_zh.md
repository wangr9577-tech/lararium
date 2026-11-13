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

## 架构

- 前端：Vue 3 + Vite + Element Plus（TypeScript）
- 后端：FastAPI (Python 3.11, conda env `site`) + SQLite（元数据）
- 内容：笔记正文和其他私有内容保存在数据目录中，正文采用 AES-256-GCM 加密
- 部署：单端口 18080，后端托管前端 dist；仅绑定 127.0.0.1（单机应用，不对外提供服务）

## 快速开始

### Windows 本机

双击 `start.bat` 启动，或用 `start_silent.vbs` 后台启动，然后打开 <http://127.0.0.1:18080/>。这是单机单人应用，没有登录：浏览器会自动建立本机会话。

### Linux / 其他机器

```bash
# 1. 后端依赖（一次性）
conda create -y -n site python=3.11 pip
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt

# 2. 前端（一次性）
cd frontend && npm install --registry=https://registry.npmmirror.com && npm run build && cd ..

# 3. 启动（只监听本机回环）
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
  生成一篇 `fmt=ink` 的多页白板笔记（可在任意页手写/荧光笔/插图），**后端不保留原始文件**；
  PDF 渲染 DPI 120、页数上限 80、图像总量上限 30MB（见 `backend/app/routers/pdf.py` 常量）

## 访问方式

服务仅绑定 `127.0.0.1:18080`，请在本机浏览器打开 <http://127.0.0.1:18080/>。

> 本应用没有登录与账号体系，**不要**通过 SSH 隧道、Cloudflare、Tailscale 或其他方式暴露到本机以外：任何能打开该地址的人都能直接读写你的数据。

## 页面路线图

| 期 | 内容 |
|---|---|
| [完成] 骨架 | 本机免登录会话、11 页壳、主题(明/暗)、设置、真实热力图、数据加密基建、git 化与迁移脚本 |
| [完成] F1 | 首页：日程 CRUD + 打勾 + 真实热力图（每日完成%） |
| [完成] F2 | 日记：正文加密读写 + 心情/天气 + 自动保存与关页补存 + 删除进回收站 |
| [完成] F3 | 笔记编辑器（富文本工具栏 + 预览）+ md→PDF 导出（pandoc + TinyTeX/xelatex）+ 目录/子文件夹 + PPT/PDF 导入（渲染为多页白板笔记，可直接手写标注） |
| [完成] F4 | 论文库/阅读器：上传、文本层荧光笔标注、划词词典 + 免费翻译 API |
| [完成] F5 | 智能助手 (Assistant) 与本地 AI 核心：通知聚合演进与唯一有效 DDL 追踪 / 稍后看文献卡片抽取 / 笔记智能起草 / 有据追溯智能问答（流式） / 论文摘要、润色与周报生成（支持本地 OpenAI 兼容服务与 vLLM/Ollama；模型失败如实报错可重试，不做规则降级） |
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

- 默认数据目录为 `backend/data/`，可通过 `KRUSKAL_DATA_DIR` 指定。备份和迁移时必须一并保留隐藏文件 `.autokey` 和 `.kek.auto`；丢失密钥会导致正文无法解密。
- 备份：`deploy/backup.sh` 使用 SQLite 一致性快照，生成带独立备份口令的加密归档和校验文件；`deploy/restore.sh` 校验并还原，旧数据目录保留为 `data.bak-*`。本机密钥也在数据目录内，会随备份一起打包；备份口令仍需妥善保存。复制运行中的数据目录时应确保 SQLite 快照一致。
- 删除可救：笔记/相册/论文/日记的删除先进 `data/trash/` 回收站，站内「回收站」可恢复或永久删除
- 运行时：`/api` 全局鉴权中间件兜底（新路由漏写 `Depends` 也不裸奔）+ CSP 响应头（`KRUSKAL_CSP=0` 可关）+ Markdown 渲染 DOMPurify 净化；生产关闭 `/docs`（`KRUSKAL_DEV=1` 才开）；上传流式限量，会话 token 过期即清、每用户封顶 20；sqlite 库文件 0600
- 生产启动用 `bash backend/start.sh`（默认不开 `--reload`；开发热更才加 `KRUSKAL_DEV=1`）
- 正文仍用 AES-256-GCM 加密，但 `.autokey` 和 `.kek.auto` 同处数据目录，能读取二者和数据的人可以解密。应保护本机账户、数据目录和备份；**本应用没有登录，仅供本机使用，不要对外暴露服务**。
- 翻译走免费 API（有道/百度/MyMemory，可在设置切换），不占 LLM；本地/远程 LLM 可选接入用于 AI 助手与论文总结，支持 OpenAI 兼容 API、vLLM 与 Ollama。助手**不做无模型的规则降级**：模型不可用时如实标记失败并保留原始输入，可重试；问答支持流式输出。
