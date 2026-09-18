# Kruskal · 个人网站

二次元风格的本地个人站：日程打卡 + 热力图 / 笔记博客(md→PDF) / 论文阅读(荧光笔+划词翻译) / 日记 / 时光机 / 生词本 / 学术个人页（含 KAUST 直博申请时间线）。

> 状态：**第一期骨架已跑通**（登录 + 11 个页面壳 + 设置真存取 + 加密基建）。功能按路线图逐期填充。

## 架构

- 前端：Vue 3 + Vite + Element Plus（TypeScript）
- 后端：FastAPI (Python 3.11, conda env `site`) + SQLite（元数据）
- 内容：Markdown 文件为唯一真相，**正文 AES-256-GCM 加密落盘**（`backend/data/`，独立 git 仓库）
- 部署：单端口 18080，后端托管前端 dist；仅绑定 127.0.0.1（跨子网/校外走 SSH 隧道或出站隧道，见 deploy/ACCESS.md）

## 快速开始

```bash
# 1. 后端依赖（一次性）
conda create -y -n site python=3.11 pip
/mnt/data_server/home/stu_wr/miniconda3/envs/site/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt

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

## 访问方式（SSH 隧道）

服务仅绑定 `127.0.0.1:18080`，跨子网/校外一律走隧道（无需对服务器开任何端口）：

```bash
# 在你自己的电脑上执行（保持窗口开着）：
ssh -N -L 18080:127.0.0.1:18080 stu_wr@192.168.2.222
# 然后浏览器打开 http://127.0.0.1:18080
```

> 校园网跨子网直连不可达、公网访问（Cloudflare/Tailscale 等出站隧道）的方案见 `deploy/ACCESS.md`。

初始账号 `admin`，初始密码见 `backend/data/initial_password.txt`，登录后立即在 **设置 → 账户安全** 中修改（改密会自动重新加密数据密钥）。

## 页面路线图

| 期 | 内容 |
|---|---|
| [完成] 骨架 | 登录鉴权、11 页壳、主题(明/暗)、设置(翻译源/LLM 渠道/改密)、热力图演示、数据加密基建、git 化与迁移脚本 |
| F1 | 首页：日程 CRUD + 打勾 + 真实热力图（每日完成%） |
| F2 | 日记：正文加密读写 |
| [完成] F3 | 笔记编辑器（富文本工具栏 + 预览）+ md→PDF 导出（pandoc + TinyTeX/xelatex）+ 目录/子文件夹 + PPT/PDF 导入（渲染为多页白板笔记，可直接手写标注） |
| F4 | 论文库/阅读器：上传、文本层荧光笔标注、划词词典 + 免费翻译 API |
| ~~F5~~ | AI 写作助手：已按用户决定移除（曾考虑直连 DSH，用户选择不做） |
| F6 | 学术个人页可编辑 + 投稿跟踪 + 学术 CV 生成 + 只读分享 |
| F7 | 时光机 + 相册 + 生词本复习 + 二次元皮肤完善（看板娘等） |

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
- 删除可救：笔记/相册/论文的删除先进 `data/trash/` 回收站，站内「回收站」可恢复或永久删除
- 运行时：`/api` 全局鉴权中间件兜底（新路由漏写 `Depends` 也不裸奔）+ CSP 响应头（`KRUSKAL_CSP=0` 可关）+ Markdown 渲染 DOMPurify 净化；上传流式限量，会话 token 过期即清、每用户封顶 20
- 生产启动用 `bash backend/start.sh`（默认不开 `--reload`；开发热更才加 `KRUSKAL_DEV=1`）
- 密码忘记 = 数据不可恢复（加密密钥由主密码派生），务必定期备份
- 翻译走免费 API（有道/百度/MyMemory，可在设置切换），不占 LLM；LLM 仅用于写作助手
