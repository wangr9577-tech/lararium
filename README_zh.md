# Lararium (Kruskal) · 个人数据主权数字花园与学术工作台

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">简体中文</a>
</p>

二次元风格的本地个人站：日程打卡 + 热力图 / 笔记博客(md→PDF) / 论文阅读(荧光笔+划词翻译) / 日记 / 时光机 / 生词本 / 学术个人页（含重要里程碑时间线）。

> 状态：**功能期基本收口**——骨架 + F1~F4、F6、F7 大部已落地并过 P0/P1/P2 三轮安全/正确性修复；剩余为打磨项（二次元皮肤等）。

## 架构

- 前端：Vue 3 + Vite + Element Plus（TypeScript）
- 后端：FastAPI (Python 3.11, conda env `site`) + SQLite（元数据）
- 内容：Markdown 文件为唯一真相，**正文 AES-256-GCM 加密落盘**（`backend/data/`，独立 git 仓库）
- 部署：单端口 18080，后端托管前端 dist；仅绑定 127.0.0.1（跨子网/校外走 SSH 隧道或出站隧道，见 deploy/ACCESS.md）

## 快速开始

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

初始账号 `admin`，初始密码见 `backend/data/initial_password.txt`，登录后立即在 **设置 → 账户安全** 中修改（改密会自动重新加密数据密钥）。

## 页面路线图

| 期 | 内容 |
|---|---|
| [完成] 骨架 | 登录鉴权、11 页壳、主题(明/暗)、设置(翻译源/LLM 渠道/改密)、真实热力图、数据加密基建、git 化与迁移脚本 |
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

- 全部数据在 `backend/data/`（一个目录即全部），拷贝即迁移，见 `deploy/MIGRATION.md`
- 备份：`deploy/backup.sh`（sqlite 一致性快照 + openssl 口令加密 `.tar.gz.enc` + `.sha256`；备份口令独立于主密码），还原：`deploy/restore.sh`（校验→解密→换入，旧 data 自动保留为 `data.bak-*`）
- 删除可救：笔记/相册/论文/日记的删除先进 `data/trash/` 回收站，站内「回收站」可恢复或永久删除
- 运行时：`/api` 全局鉴权中间件兜底（新路由漏写 `Depends` 也不裸奔）+ 登录防爆破限流（10 分钟 10 败 → 429）+ CSP 响应头（`KRUSKAL_CSP=0` 可关）+ Markdown 渲染 DOMPurify 净化；生产关闭 `/docs`（`KRUSKAL_DEV=1` 才开）；上传流式限量，会话 token 过期即清、每用户封顶 20；sqlite 库文件 0600
- 生产启动用 `bash backend/start.sh`（默认不开 `--reload`；开发热更才加 `KRUSKAL_DEV=1`）
- 密码忘记 = 数据不可恢复（加密密钥由主密码派生），务必定期备份
- 免密自动解锁（可选，默认关闭）：DEK 只在进程内存里，所以每次重启服务器都要重新输主密码。`设置 → 账户安全` 打开「本机免密解锁」后，启动时用本机密钥自动恢复 DEK，无需人工输入——**加密本身不变**，改的只是"每次都要人输密码"。`.kek.auto` 随数据一起备份，本机密钥 `backend/.autokey`（0600、已 gitignore、**不在备份包里**，可用 `KRUSKAL_AUTOKEY` 换位置）分处备份边界两侧，单独拷走任何一边都解不开。边界要说清：开启后防线从「主密码」降为「文件权限 + 备份口令」——仍挡住同机其他普通用户（`data/` 是 0700），**不挡** root 与恶意进程；换机器、重装、从备份还原到新机器仍需主密码。设置里关闭或点「一键上锁」都会立即撤销免密（`backend/tests/test_auto_unlock.py` 覆盖，含"上锁后重启不得自动解锁"）。
- 翻译走免费 API（有道/百度/MyMemory，可在设置切换），不占 LLM；本地/远程 LLM 可选接入用于 AI 助手与论文总结，支持 OpenAI 兼容 API、vLLM 与 Ollama，且具备无模型时的纯启发式规则优雅降级。
