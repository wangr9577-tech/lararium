# Lararium 桌面化技术方案（Electron 壳 + 冻结后端 Sidecar）

- 状态：**待评审**（未开工）
- 目标平台：Windows 10/11 x64（Linux/macOS 本版不覆盖，但改动保持平台中立）
- 选型：**Electron 主进程壳 + PyInstaller 冻结的 FastAPI core**；后端继续托管前端 dist，壳加载 `http://127.0.0.1:<port>`
- 笔记导出 PDF：**桌面版走 Electron `webContents.printToPDF`**，Web 版保持现有 pandoc 路径
- 作者：AI 起草，依据 2026-11-07 仓库实际代码逐文件核对

---

## 0. 结论摘要

| 问题 | 回答 |
| :-- | :-- |
| 能不能改成桌面应用 | 能。后端已是"单端口同时托管 API + SPA"的本地服务，前端 API 全用相对路径，桌面化只差**打包 + 外壳 + 数据目录安置**三件事 |
| 前端要不要重写 | **不要**。壳加载后端 serve 的 URL，前端业务代码零改动（只加一个"是否桌面运行"的探测，用于隐藏分享等入口） |
| 主要风险 | PyInstaller 冻结后的路径解析与 hidden imports、杀软误报、数据目录迁移（密钥文件丢了就解不开）、PDF 导出质量降级 |
| 总工作量 | 4–6 人日（P0 地基 1.5d → P1 冻结+壳 1.5d → P2 安装包 1d → 联调测试 1d） |
| 安装包体积 | 压缩包约 85–120MB；装后约 320–400MB（Electron ~200MB + Python runtime ~120MB，主要是 pymupdf） |

---

## 1. 现状可行性评估（逐条对代码）

### 1.1 有利条件

| # | 现状 | 位置 | 对桌面化的意义 |
| :-- | :-- | :-- | :-- |
| 1 | FastAPI 单端口托管 API + dist，SPA 兜底路由 | [main.py:152-198](../backend/app/main.py#L152-L198) | 壳只要打开一个 URL 即得到完整应用；无需 CORS、无需改前端路由 |
| 2 | 默认只绑回环 `127.0.0.1` | [config.py:18](../backend/app/config.py#L18)、[start.ps1:7-9](../start.ps1#L7-L9) | 已是"本机应用"模型，桌面化后不必引入 HTTPS |
| 3 | 前端 API base 是相对路径 `/api`，无硬编码域名/端口 | [client.ts:13](../frontend/src/api/client.ts#L13)、[vite.config.ts:9](../frontend/vite.config.ts#L9)（仅 dev 代理） | **端口可以随机化**而前端一行不用改 |
| 4 | 本机会话：Bearer token 存 localStorage，由 `/api/auth/local-session` 自动换取（没有登录界面） | [client.ts:9-24](../frontend/src/api/client.ts#L9-L24)、[main.ts:38-44](../frontend/src/main.ts#L38-L44) | 桌面版直接复用，不需要任何登录/账号逻辑 |
| 5 | 已有 PWA manifest（`display: standalone`）+ 纯透传 SW | [manifest.json](../frontend/public/manifest.json)、[sw.js](../frontend/public/sw.js) | 过渡期可先用浏览器"安装应用"；SW 不缓存，不会造成桌面版内容过期 |
| 6 | 后端依赖仅 7 个包，外呼全用标准库 `urllib` | [requirements.txt](../backend/requirements.txt) | PyInstaller 依赖面小，冻结难度低 |
| 7 | 缺 dist / 缺资源目录时是优雅降级，不崩 | [main.py:154](../backend/app/main.py#L154)、[main.py:169-179](../backend/app/main.py#L169-L179) | 少一类"资源没带上直接起不来"的故障 |
| 8 | CSP 已允许 `worker-src blob:` / `script-src 'wasm-unsafe-eval'` | [main.py:110-112](../backend/app/main.py#L110-L112) | 白板 OffscreenCanvas worker、pdfjs worker 在 Electron Chromium 里能正常跑 |
| 9 | 已有本地启动/自启脚本 | [start.ps1](../start.ps1)、[start_silent.vbs](../start_silent.vbs)、[enable_autostart.bat](../enable_autostart.bat) | 桌面版的启动逻辑可直接继承，Web 版不受影响 |

### 1.2 必须先解决的障碍

| # | 障碍 | 位置 | 严重度 |
| :-- | :-- | :-- | :-- |
| A | `REPO_ROOT = Path(__file__).resolve().parents[2]` 在冻结后指向临时解包目录，`DIST_DIR`/`DATA_DIR`/`AUTOKEY_KEY` 全部错位 | [config.py:10-21](../backend/app/config.py#L10-L21)、[config.py:35](../backend/app/config.py#L35) | 阻断 |
| B | 数据目录默认在代码树内 `backend/data`；装到 `Program Files` 后不可写，且升级会覆盖 | [config.py:13](../backend/app/config.py#L13) | 阻断 |
| C | 端口写死 18080，桌面应用不能假设端口空闲 | [config.py:19](../backend/app/config.py#L19) | 高 |
| D | `runner.py` 用了 POSIX 语义：`start_new_session=True`、`os.killpg(os.getpgid(...))`。Windows 上启动任务即 `AttributeError`（**现存 bug，与桌面化无关**） | [runner.py:83-86](../backend/app/services/runner.py#L83-L86)、[runner.py:153](../backend/app/services/runner.py#L153) | 高 |
| E | 导出 PDF 依赖 pandoc + `~/.TinyTeX/bin/x86_64-linux/xelatex`（Linux 路径），Windows 桌面机上必然 503 | [notes.py:685-711](../backend/app/routers/notes.py#L685-L711) | 中（本方案改道） |
| F | 分享链接用 `location.origin` 拼接，桌面版得到 `http://127.0.0.1:<随机端口>` 这类无意义链接 | [ShareDialog.vue:66-77](../frontend/src/components/ShareDialog.vue#L66-L77)、[share.py](../backend/app/routers/share.py) | 中 |
| G | `settings.py` 第 74 行用了 `os.chmod` 但**本文件没有 `import os`**；该行被外层 `except Exception: pass` 吞掉，导致 `local_settings.json` 的落盘同步静默失效（**现存 bug**） | [settings.py:66-78](../backend/app/routers/settings.py#L66-L78) | 中 |
| H | `CODE_ROOT` 默认 `~/workspace`，桌面版应让用户自选"代码工作区根目录" | [config.py:52-54](../backend/app/config.py#L52-L54) | 中 |
| I | 多处 `os.chmod(0o600/0o700)` 在 Windows 上语义近似 no-op，"同机其他用户不可读"这道闸在桌面机上不成立 | [config.py:93](../backend/app/config.py#L93)、[vault.py:37](../backend/app/vault.py#L37)、[db.py:492](../backend/app/db.py#L492) | 低（建议改 ACL） |

---

## 2. 选型与备选方案

### 2.1 采用：Electron 壳 + PyInstaller sidecar

理由：
1. **前端零改动**。壳加载 `http://127.0.0.1:<port>`，同源、安全上下文、CSP、blob worker、`crypto.subtle` 全部天然成立。
2. **后端零重写**。FastAPI 继续是真相源，桌面版与 Web 版共用同一份后端代码，避免分叉维护。
3. **PDF 导出有解**。Electron `printToPDF` 能保留 KaTeX/高亮排版，不需要随包携带 LaTeX（见 §5）。
4. 团队只有 JS/Python 经验即可推进，无 Rust 依赖；本机已有 Node + pnpm 环境。

代价：安装包 ~100MB、装后 ~350MB、常驻内存多一个 Chromium（~150MB）。个人工作站应用可接受。

### 2.2 被否决的方案

| 方案 | 否决原因 |
| :-- | :-- |
| 壳用 `file://` 打开 `dist/index.html` | 相对 `/api` 解析成 `file:///api`（[client.ts:13](../frontend/src/api/client.ts#L13)）；CSP `default-src 'self'` 与 `frame-ancestors` 语义变化；非安全上下文风险。要修就得动前端 + 后端加 CORS，收益为负 |
| Tauri + sidecar | 体积小一个数量级，但需要 Rust 工具链；Windows 走 WebView2，剪贴板/下载/`printToPDF` 等价能力要写 Rust command，白板与论文阅读的兼容性验证成本更高 |
| 纯 PWA 安装 | 最省事，但没有安装器、没有图标资产独立性、要求用户自行启动服务、无系统集成（托盘/单实例/文件关联）。可作为**过渡态**保留 |
| 后端只打 exe + `msedge --app` | 半天能拿到"无地址栏窗口"，但依赖用户机器装了 Edge、窗口/图标/生命周期不受控、无法做崩溃自愈。适合自用应急 |
| 把业务逻辑改写进 Electron 主进程（去 Python） | 等于重写：40+ 个 router、加密层、SQLite schema、pymupdf 处理链，成本数月且不划算 |

---

## 3. 目标架构与仓库结构

```text
┌──────────────────────────────────────────────────────────┐
│ Electron Main（desktop/main.ts）                          │
│  · 单实例锁 · 启动/守护 core · 就绪探测                    │
│  · BrowserWindow 加载 http://127.0.0.1:<port>             │
│  · 托盘 + 关闭窗口最小化到托盘 · 退出即杀 core              │
│  · printToPDF 导出 · 外链走系统浏览器 · 崩溃重启(退避)      │
└───────────────┬──────────────────────────────────────────┘
                │ spawn（stdio 读 "KRUSKAL_LISTENING <url>"）
                │ env: KRUSKAL_DATA_DIR / KRUSKAL_DESKTOP=1 / KRUSKAL_PORT
                ▼
┌──────────────────────────────────────────────────────────┐
│ lararium-core.exe（PyInstaller one-dir，冻结的同一份 app）  │
│  FastAPI 127.0.0.1:<随机可用端口>                          │
│  托管 resources/frontend/dist（asarUnpack 外，随 core 走） │
│  SQLite + 加密 vault → %APPDATA%\Lararium\data            │
└──────────────────────────────────────────────────────────┘
```

新增目录（现有 `frontend/` `backend/` 结构不动）：

```text
desktop/
  package.json              # electron + electron-builder，独立于 frontend 的依赖树
  electron-builder.yml      # NSIS 目标、asarUnpack、安装器图标
  main.ts                   # 主进程：生命周期/守护/打印（约 200 行）
  preload.ts                # 仅暴露最小桌面能力桥
  build/                    # icon.ico、installer.nsh
  resources/                # 构建产物注入：lararium-core/（PyInstaller dist）、frontend-dist/
scripts/
  build-desktop.ps1         # 一键：vite build → pyinstaller → electron-builder
  make-icon.ps1             # icon-512.png → icon.ico
backend/
  desktop_entry.py          # 冻结入口：选端口→建 app→serve，打印就绪行（见 §4.3）
  lararium-core.spec        # PyInstaller spec（datas / hidden imports / upx 关闭）
docs/
  DESKTOP_ELECTRON_PLAN.md  # 本文档
```

---

## 4. 改动清单

每项给出：**问题 → 改法 → 验收**。P0 全部完成后，Web 版行为必须与今天完全一致（新增分支均由 `KRUSKAL_DESKTOP`/环境变量门控）。

### 4.1 [P0] `config.py`：冻结安全的路径层

**问题**：见 §1.2 A/B/C/H。

**改法**：引入 `app/runtime_paths.py`，由它统一产出三类路径，`config.py` 只做转发，保持所有下游 `config.DATA_DIR` 引用不变。

```python
# backend/app/runtime_paths.py（新增）
import sys
from pathlib import Path

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def bundle_root() -> Path:
    """只读资源根：冻结后是 _MEIPASS，开发态是仓库根。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]

def dist_dir() -> Path:
    """前端产物：桌面版随 core 打包，开发态仍是 frontend/dist。"""
    if is_frozen():
        return bundle_root() / "frontend-dist"
    return bundle_root() / "frontend" / "dist"

def user_data_root() -> Path:
    """可写数据根（桌面态默认 %APPDATA%\\Lararium）。"""
    import os
    override = os.environ.get("KRUSKAL_DATA_DIR")
    if override:
        return Path(override)
    if is_frozen():
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Lararium" / "data"
    return bundle_root() / "backend" / "data"

def autokey_dir() -> Path:
    """本机密钥目录：桌面态与数据同盘但独立文件，便于备份策略区分。"""
    return user_data_root().parent

def is_desktop() -> bool:
    import os
    return os.environ.get("KRUSKAL_DESKTOP") == "1"
```

`config.py` 对应替换：

| 现在 | 改为 |
| :-- | :-- |
| [config.py:10](../backend/app/config.py#L10) `REPO_ROOT = ...parents[2]` | `REPO_ROOT = runtime_paths.bundle_root()` |
| [config.py:13](../backend/app/config.py#L13) `DATA_DIR` | `runtime_paths.user_data_root()` |
| [config.py:21](../backend/app/config.py#L21) `DIST_DIR` | `runtime_paths.dist_dir()` |
| [config.py:35](../backend/app/config.py#L35) `AUTOKEY_KEY` | 冻结态落 `runtime_paths.autokey_dir() / ".autokey"` |
| [config.py:52-54](../backend/app/config.py#L52-L54) `CODE_ROOT` | 冻结态优先读 `local_settings.json` 里用户选的 `codeRoot`，回退 `~/Documents/LarariumProjects` |

注意：`main.py` 在**导入期**就调用 `init_db()` / `ensure_local_user()`（[main.py:61-72](../backend/app/main.py#L61-L72)），所以 `KRUSKAL_DATA_DIR` 必须在 `import app.main` 之前设置好——桌面入口正是这么做的（§4.3）。

**验收**：
- 开发态 `uvicorn app.main:app` 起得来的 DB、密钥、笔记与今天同一份（路径未变）。
- 设 `KRUSKAL_DATA_DIR=<tmp>` 后跑 `backend/tests`（`rebind_data_dir` 已支持，[config.py:98-157](../backend/app/config.py#L98-L157)），全绿。
- 冻结后的 core 在新机器上首启，`%APPDATA%\Lararium\data` 被建出且含 `site.db`。

### 4.2 [P0] 数据目录迁移与备份策略

**问题**：老用户数据在 `E:\kruskal\backend\data`，桌面版读写 `%APPDATA%\Lararium\data`，不迁移等于"数据丢了"。`.kek` / `.kek.auto` / `backend/.autokey` 三者任一缺失都可能让密文不可解（README「Passwordless local keys」一节已明确此风险）。

**改法**：新增 `backend/app/migrate_desktop.py`：
1. 触发条件：桌面态首启 且 目标数据目录不存在 且 源目录（打包时通过 `KRUSKAL_LEGACY_DATA_DIR` 传入，或由设置页手动选择）存在 `site.db`。
2. 执行：先整体复制到 `<目标>.migrating`，逐项校验（`site.db` 可读、`.kek`/`.autokey` 齐全、抽一个 vault 文件能解密），成功后 `os.replace` 落位，失败则回滚并保留源目录。
3. 迁移完成后写 `<目标>/MIGRATED_FROM.txt` 记录来源与时间，**绝不删除源目录**。
4. 顺带把 `os.chmod` 那道"同机隔离"闸在 Windows 上换成有效实现：新增小工具用 `icacls <path> /inheritance:r /grant:r "%USERNAME%:F"`（失败仅告警，不阻断）。把 [config.py:93](../backend/app/config.py#L93)、[vault.py:37](../backend/app/vault.py#L37)、[db.py:492](../backend/app/db.py#L492)、[auth.py:55](../backend/app/auth.py#L55)、[autokey.py:45](../backend/app/autokey.py#L45) 的权限设置统一走这一个工具。

**验收**：把现有 `backend/data` 指给迁移器跑一遍，桌面 core 能读出全部笔记/日记；故意破坏 `.autokey` 时迁移器中止且不留下半成品目录。

### 4.3 [P0] 端口协商 + 冻结入口

**问题**：桌面应用不能写死 18080（[config.py:19](../backend/app/config.py#L19)），且 PyInstaller 里 `uvicorn` CLI 不可用（依赖 `import_string` 动态导入与信号处理）。

**改法**：新增 `backend/desktop_entry.py`，冻结时作为唯一入口：

```python
"""PyInstaller 入口：选端口 → 建 app → 打印就绪行 → serve。"""
import os, socket, sys
from pathlib import Path

def pick_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def main() -> int:
    port = int(os.environ.get("KRUSKAL_PORT") or pick_port())
    os.environ["KRUSKAL_HOST"] = "127.0.0.1"
    os.environ["KRUSKAL_DESKTOP"] = "1"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    from app.main import app          # 导入期完成 init_db / ensure_local_user
    import uvicorn

    # uvicorn 内部是 import 字符串，冻结后必须直接传 app 对象
    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            loop="asyncio", access_log=False)
    server = uvicorn.Server(config)
    print(f"KRUSKAL_LISTENING http://127.0.0.1:{port}", flush=True)
    try:
        server.run()
    finally:
        (Path.home() / ".lararium-port").unlink(missing_ok=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

要点：
- **就绪握手**用 stdout 行 `KRUSKAL_LISTENING <url>`，壳据此 `loadURL`；同时兜底轮询 `/healthz`（已存在，[main.py:147-149](../backend/app/main.py#L147-L149)）。
- `access_log=False`：桌面版不需要访问日志污染用户目录。
- 冻结后 `uvicorn.Config(loop="asyncio")` 显式指定事件循环，避开 `loop="auto"` 的动态导入。
- 保留 `KRUSKAL_PORT` 覆盖能力，便于调试与"希望端口固定"的场景。

**验收**：连续启动 3 次能拿到 3 个不同端口且不冲突；`curl http://127.0.0.1:<port>/healthz` 返回 `{"ok":true,...}`；被占用端口时不报错退出。

### 4.4 [P0] `runner.py` 的 Windows 进程组

**问题**：`start_new_session=True` 在 Windows 被忽略，`os.killpg(os.getpgid(pid), 9)` 抛 `AttributeError`（[runner.py:83-86](../backend/app/services/runner.py#L83-L86)、[runner.py:146-159](../backend/app/services/runner.py#L146-L159)）。也就是说 **Lab 页"跑脚本/训练命令"在 Windows 上现在就是坏的**——桌面化前必须修，否则桌面上的实验台更不能用。

**改法**：

```python
# start()
kwargs = {}
if os.name == "nt":
    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    kwargs["start_new_session"] = True
task["proc"] = subprocess.Popen(cmd, cwd=str(wd), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **kwargs)

# _kill()
if os.name == "nt":
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True)
else:
    os.killpg(os.getpgid(proc.pid), 9)
```

`_pump` 的 `iter(proc.stdout.readline, b"")` 保持不变；Windows 下 `proc.wait()` 在 taskkill 后正常返回，`exit_code` 记为 `-9` 的现有语义沿用。

**验收**：桌面/开发态各起一个 `python -c "import time;time.sleep(60)"` 任务，点"终止"后进程树消失（用 `Get-Process python` 确认无残留）。

### 4.5 [P0] 桌面版 PDF 导出改道 PrintToPDF

**问题**：见 §1.2 E。随包携带 pandoc + 便携 LaTeX 会让安装包涨到数百 MB～1GB，且首次编译慢；而桌面壳自带 Chromium 打印，能保住 KaTeX/代码高亮排版（与用户"在浏览器里另存为 PDF"效果一致，通常比 LaTeX 更符合预期）。

**改法（后端，小改）**：
1. 新增只读打印路由 `GET /api/notes/{id}/print`，返回一份**自包含 HTML**：正文由后端把已解密的 md 渲染（复用现有渲染路径与站内图片接口），CSS 内联 KaTeX 与高亮样式，`<base>` 指向本站以让图片/字体同源加载。
   - 该路由走 `/api/` 前缀，因此**自动被全局鉴权中间件保护**（[main.py:115-129](../backend/app/main.py#L115-L129)），无需新写鉴权逻辑；壳里通过带 Bearer 的请求拿 HTML 再喂给隐藏窗口，不放宽白名单 `_PUBLIC_API`。
   - 白板（`fmt == "ink"`）笔记继续按现状拒绝 PDF，提示走 PNG（与 [notes.py:704-705](../backend/app/routers/notes.py#L704-L705) 一致）。
2. `_pandoc()` / `_tinytex_bin()` 保留给 Web 版；错误提示改成平台正确的建议（[notes.py:708](../backend/app/routers/notes.py#L708) 现在写的是 conda 命令，[notes.py:696](../backend/app/routers/notes.py#L696) 写死 Linux 路径），并在 `KRUSKAL_DESKTOP=1` 时直接返回 501 + `"桌面版请用「导出 PDF」按钮"`。

**改法（前端，小改）**：
1. `window.lararium` 桥（由 preload 暴露，非桌面态为 `undefined`）：`exportPdf(url, filename)` / `saveBlob(filename, blob)` / `isDesktop`。
2. [NoteView.vue:306-311](../frontend/src/views/NoteView.vue#L306-L311) 与 [PaperReader.vue:428-429](../frontend/src/components/PaperReader.vue#L428-L429) 的导出逻辑加分支：桌面态调 `window.lararium.exportPdf('/api/notes/<id>/print', '标题.pdf')`，否则保持现有 `a.download`。
3. 桌面态隐藏分享入口（§4.6），并把 `a.download` 类下载统一改走原生"另存为"对话框（更符合桌面习惯，且绕开 Chromium 对匿名 blob 下载的沙箱差异）。

**验收**：含公式、代码块、内嵌图片的笔记导出后 PDF 里三者都在；PDF 文件名取笔记标题并清洗非法字符；Web 版行为不变。

### 4.6 [P0/P1] 分享入口与桌面标识

**问题**：桌面版 `location.origin` 是随机回环地址，分享链接对外无意义（[ShareDialog.vue:66-77](../frontend/src/components/ShareDialog.vue#L66-L77)）。

**改法**：
1. 后端 `/api/site` 或新增 `/api/desktop-info` 在 `KRUSKAL_DESKTOP=1` 时返回 `{desktop: true, publicBase: <local_settings 里可选配置的公网基址>}`。
2. 前端在设置里增加"公网访问基址"输入项（走现有 key-value 设置存储，[settings.py:41-79](../backend/app/routers/settings.py#L41-L79)）：填了才显示"生成分享链接"，未填则分享入口显示为"桌面版需先配置公网基址"。
3. 桌面版把 `window.open(外链)` 交系统浏览器：在 `App.vue` 或壳的 `setWindowOpenHandler` 里统一拦截非本站 `http(s)` 链接（壳侧拦截即可，前端零改动，见 §5）。

**验收**：桌面版未配置公网基址时不会产生 127.0.0.1 分享链接；点击论文/arXiv 外链跳系统默认浏览器。

### 4.7 [P0] 顺手修的现存 bug

| 位置 | 问题 | 改法 |
| :-- | :-- | :-- |
| [settings.py:74](../backend/app/routers/settings.py#L74) | 使用 `os.chmod` 但本文件未 `import os`；异常被外层 `except Exception: pass` 吞掉，导致 `local_settings.json` 的同步写入**从未生效** | 文件头加 `import os`；并把 `chmod` 与写文件分离 try，写失败要 `logging.warning` 而不是彻底静默 |
| [notes.py:708](../backend/app/routers/notes.py#L708) | 503 文案给的是 conda 命令，Windows/桌面语境误导 | 按平台与 `KRUSKAL_DESKTOP` 输出正确建议 |
| [config.py:93](../backend/app/config.py#L93) 等 5 处 `chmod` | Windows 上无效 | 统一走 §4.2 的 `icacls` 工具 |

这三处都属于"改了更安全、不改也不影响 Web 版"的低风险修正。

---

## 5. Electron 壳设计

`desktop/main.ts` 职责边界：只做**生命周期、系统集成、打印**，不碰业务。

### 5.1 启动与守护

```ts
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) app.quit()

async function startCore(): Promise<string> {
  const exe = path.join(process.resourcesPath, 'lararium-core', 'lararium-core.exe')
  const env = {
    ...process.env,
    KRUSKAL_DATA_DIR: app.getPath('userData') + '/data',
    KRUSKAL_DESKTOP: '1',
    KRUSKAL_LEGACY_DATA_DIR: app.getPath('documents') + '/Lararium/legacy-data',
    KRUSKAL_CODE_ROOT: await readCodeRootPref(),
    PYTHONIOENCODING: 'utf-8',
  }
  child = spawn(exe, [], { env, windowsHide: true })
  return waitForListeningLine(child, 30_000)   // 兜底：轮询 /healthz
}
```

- **就绪**：读 stdout 的 `KRUSKAL_LISTENING <url>`；30s 超时或 core 退出 → 弹窗给"重试 / 打开日志"。
- **崩溃重启**：core 非 0 退出且非用户主动 quit 时，按 1s/3s/9s 退避重启，连续 5 次失败停止并提示（日志落 `%APPDATA%\Lararium\logs\core-<date>.log`）。
- **退出**：`before-quit` 里 `child.kill()`（Windows 用 `taskkill /T /F /PID`，复用 §4.4 的经验），确保不遗留孤儿 core 占端口。
- **窗口**：关闭按钮默认最小化到托盘（可在设置里改成"直接退出"）；托盘菜单：打开主窗口 / 暂停后台任务 / 退出。

### 5.2 安全与体验细节

| 项 | 处理 |
| :-- | :-- |
| `webPreferences` | `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`；业务页面拿不到 Node 能力 |
| `preload.ts` 暴露面 | 仅 `isDesktop`、`exportPdf(url, name)`、`saveBlob(name, blob)`、`appInfo()`，其余一律不给 |
| 外链 | `setWindowOpenHandler` 对非 `127.0.0.1:<ourPort>` 的 http(s) 走 `shell.openExternal` 并 `deny` |
| 后端 CSP | 不改（[main.py:110-112](../backend/app/main.py#L110-L112)）。加载同源 `http://` 时 Electron 不强制升级 https，白板 worker / pdfjs worker 均正常 |
| Service Worker | `sw.js` 是纯透传（[sw.js](../frontend/public/sw.js)），Electron 里注册无副作用；若想更干净，可在 `KRUSKAL_DESKTOP` 时不注入注册脚本（前端一行 if，可选） |
| 缩放/多屏 | `zoomFactor` 跟随系统 DPI；窗口尺寸持久化到 `<userData>/window.json` |
| 打印 | `printToPDF({ printBackground: true, preferCSSPageSize: true })`；隐藏 `BrowserWindow({show:false})` 加载打印路由，`did-finish-load` + KaTeX 渲染完成信号后再打印 |
| 快捷键 | `Ctrl+Shift+I` 仅开发包开放；生产包禁用菜单里的 DevTools |

### 5.3 前端需要知道的唯一"桌面开关"

```ts
// frontend/src/utils/desktop.ts（新增，5 行）
export const desktop = (window as any).lararium?.isDesktop === true
```

只在三处使用：导出 PDF 分支、下载改原生另存为、隐藏分享/公网相关文案。**不做任何"桌面版专用页面"**，避免两套 UI。

---

## 6. 后端打包（PyInstaller）

`backend/lararium-core.spec` 关键设置：

| 项 | 值 / 说明 |
| :-- | :-- |
| `mode` | **one-dir**（不是 one-file）：启动快、杀软误报少、便于日志定位；体积差别不大 |
| `datas` | `frontend/dist` → `frontend-dist`（供 `DIST_DIR`，[main.py:152-166](../backend/app/main.py#L152-L166)）；`backend/app` 若有非 py 资源一并带上 |
| `hiddenimports` | `uvicorn.logging`、`uvicorn.loops.asyncio`、`uvicorn.protocols.http.h11_impl`、`uvicorn.protocols.websockets.wsproto_impl`、`uvicorn.lifespan.on`；`pymupdf`、`pptx` 模板数据用 `collect_data_files('pptx')`、`collect_data_files('pymupdf')`、`collect_data_files('lunardate')` |
| `collect_submodules` | `app.routers`（40+ 个 router 目前是显式 import，可不必，但保险） |
| `upx` | **False**：UPX 压缩过的 exe 是杀软误报高发因素 |
| `icon` | 由 [icon-512.png](../frontend/public/icons/icon-512.png) 生成的 `icon.ico` |
| `console` | Windows 下 `console=False`，但 `desktop_entry` 的就绪行走 stdout —— 壳用 `windowsHide` + 管道仍然读得到；若验证读不到，退化方案是 core 把 URL 写到 `<userData>/core.port` 文件，壳轮询该文件 |
| 体积预估 | 解压后 ~120MB（pymupdf ~40MB、cryptography ~10MB、pptx/PIL ~20MB、python311.dll 等） |

**构建脚本** `scripts/build-desktop.ps1`（顺序）：
1. `pnpm -C frontend build`（[vite.config.ts](../frontend/vite.config.ts) 已配好分包）
2. 复制 `frontend/dist` → `desktop/resources/frontend-dist`
3. `pyinstaller backend/lararium-core.spec` → `desktop/resources/lararium-core/`
4. `pnpm -C desktop build`（electron-builder 出 NSIS）
5. 产物 `desktop/dist/Lararium Setup <ver>.exe`

---

## 7. 安装包与分发

| 项 | 方案 |
| :-- | :-- |
| 安装器 | electron-builder **NSIS**（oneClick: false，允许选目录，per-user 安装避免 UAC） |
| 图标 | 复用 [icon-512.png](../frontend/public/icons/icon-512.png)，`scripts/make-icon.ps1` 生成 16/32/48/256 多尺寸 `icon.ico` |
| 应用标识 | `id: com.lararium.desktop`；`productName: Lararium`（注意 [manifest.json](../frontend/public/manifest.json) 现在叫 "Kruskal"，是否统一改名待你定，见 §11） |
| 开机自启 | electron-builder `launchOnStartup` 选项 + 设置页开关（替代现有 [enable_autostart.bat](../enable_autostart.bat) 的注册表方式） |
| 代码签名 | 个人使用可跳过，代价是 SmartScreen"未知发布者"提示；有证书则配 `win.signtoolOptions` |
| 自动更新 | 本版不做（`electron-updater` + 静态 JSON 源即可，留 P3） |
| 卸载 | NSIS 卸载器**默认保留** `%APPDATA%\Lararium`（数据），显式勾选才删；卸载前弹二次确认 |
| 备份 | 沿用 [deploy/backup.sh](../deploy/backup.sh) 思路做一个"导出备份 zip"按钮（P3） |

---

## 8. 分阶段实施与验收

| 阶段 | 内容 | 人日 | 验收标准 |
| :-- | :-- | :-- | :-- |
| **P0 地基** | §4.1 路径层、§4.2 迁移+ACL、§4.3 端口/冻结入口、§4.4 runner Windows、§4.5 打印路由、§4.7 现存 bug | 1.5 | ① `uvicorn app.main:app` 起服务，Web 版全功能回归通过；② `python desktop_entry.py` 在随机端口起得来，`/healthz` OK；③ 迁移器把 `backend/data` 完整搬到临时目录并解密成功；④ Lab 跑脚本+终止在 Windows 正常 |
| **P1 冻结 + 壳** | spec 文件、`desktop/` 壳（窗口/托盘/守护/单实例/printToPDF/外链） | 1.5 | 双击 `lararium-core.exe` + `electron .` 能进主界面；杀 core 进程后壳自动重启并恢复会话；笔记导出 PDF 含公式与图片 |
| **P2 安装包** | electron-builder NSIS、图标、自启、日志、崩溃提示、README 章节 | 1 | 在**没装 Python/Node** 的干净 Win11 虚机里：安装 → 桌面图标 → 双击进入 → 首次启动把旧数据迁进来 → 卸载后数据仍在 |
| **P3 打磨**（可选） | 迁移向导 UI、原生另存为全覆盖、备份导出、自动更新、设置页"桌面"分区 | 1–2 | 视取舍 |
| 联调回归 | §9 全部功能逐页点一遍 + 白板压测 | 1 | 见 §9 表 |

**回滚**：所有新增逻辑都由 `is_frozen()` / `KRUSKAL_DESKTOP` 门控；删掉 `desktop/` 与 `lararium-core.spec`、还原 `config.py` 的 5 行路径取值，即回到今天的纯 Web 形态。

---

## 9. 功能在桌面版的兼容性核查表（回归清单）

| 功能 | 依赖点 | 桌面版结论 |
| :-- | :-- | :-- |
| 白板手写 | OffscreenCanvas worker（blob）、`worker-src blob:` CSP（[main.py:L111](../backend/app/main.py#L111)）、[render.worker.ts](../frontend/src/whiteboard/renderer/render.worker.ts) | ✅ 预期无需改动，需压测笔迹延迟 |
| 论文阅读 | pdfjs worker、`script-src 'wasm-unsafe-eval'` | ✅ 同源加载，无需改动 |
| Markdown/公式 | Vditor 本地资源（`/vditor/*` 由后端托管，[main.py:158-160](../backend/app/main.py#L158-L160)）、KaTeX 字体 | ✅ dist 打进包即可，无 CDN 依赖 |
| 图片/附件下载 | `a.download` + `URL.createObjectURL`（[AssetManager.vue:578-582](../frontend/src/components/AssetManager.vue#L578-L582)、[Album.vue:225-228](../frontend/src/views/Album.vue#L225-L228) 等 8 处） | ⚠️ 建议改原生"另存为"，功能本身可用 |
| 剪贴板 | `navigator.clipboard.writeText`（[ShareDialog.vue:104](../frontend/src/components/ShareDialog.vue#L104)、[Settings.vue:766](../frontend/src/views/Settings.vue#L766) 等 5 处） | ✅ 安全上下文（http://127.0.0.1 算 secure context）可用 |
| 导出 PDF | pandoc + Linux TinyTeX（[notes.py:685-711](../backend/app/routers/notes.py#L685-L711)） | 🔁 桌面改 PrintToPDF（§4.5） |
| 实验室跑脚本 | POSIX 进程组（[runner.py:153](../backend/app/services/runner.py#L153)） | 🔧 先修 §4.4 才可用 |
| 分享链接 | `location.origin`（[ShareDialog.vue:66](../frontend/src/components/ShareDialog.vue#L66)） | ⚠️ 需公网基址配置，否则隐藏入口 |
| 翻译 / 节假日 / arXiv / LLM | 外网 `urllib`（[translate.py:62](../backend/app/routers/translate.py#L62)、[holiday.py:47](../backend/app/routers/holiday.py#L47)、[papers.py:242-267](../backend/app/routers/papers.py#L242-L267)、[llm.py:190](../backend/app/services/llm.py#L190)） | ✅ 但断网时要有明确离线提示 |
| 上传大文件 | 流式上限（[upload.py:13-29](../backend/app/upload.py#L13-L29)） | ✅ 无改动 |
| 本机密钥 | `.autokey` 与 `.kek.auto` 都在数据目录（[config.py:22-27](../backend/app/config.py#L22-L27)） | 🔧 桌面态密钥文件落 `%APPDATA%\\Lararium\\`，迁移器负责一起搬 |

---

## 10. 风险与对策

| # | 风险 | 概率 | 影响 | 对策 |
| :-- | :-- | :-- | :-- | :-- |
| 1 | PyInstaller 漏收 `uvicorn`/`pymupdf` 动态导入 | 高 | core 起不来 | 就绪握手 + 明确错误弹窗；spec 用 `collect_all`，构建后自动跑一次 `--selftest` 冒烟（起服务→`/healthz`→退出）纳入构建脚本 |
| 2 | 杀软/SmartScreen 拦截未签名 exe | 高 | 装不上/被删 | one-dir + `upx=False` + 不打包 `.bat`；README 写白名单指引；有条件就买代码签名证书 |
| 3 | 迁移失败导致 vault 不可解 | 低但致命 | 数据丢失 | §4.2：只复制不移动、抽解校验后才落位、失败回滚、源目录永不动、迁移前自动备份 `.kek*` 三件套 |
| 4 | PrintToPDF 与 LaTeX 排版不一致（分页、字体） | 中 | 观感差异 | 打印路由单独写一套 `@page` CSS；保留 Web 版 pandoc 通道；不追求与 LaTeX 一致，只求"和浏览器打印一致" |
| 5 | 随机端口让会话 token 的 localStorage origin 变化 | 中 | 每次换端口都要重新换票 | 固定端口优先（默认 18080，被占再随机）；前端启动时会自动向 `/api/auth/local-session` 换票（[client.ts:9-24](../frontend/src/api/client.ts#L9-L24)），换端口后刷新即可恢复 |
| 6 | Electron 体积/内存 | 确定 | ~350MB / +150MB 常驻 | 接受；若日后不可接受，壳换 Tauri，sidecar 与 §4 改动全部可复用 |
| 7 | 桌面版成为唯一运行方式 | 低 | 换机需要搬数据目录 | 迁移器只复制不移动，迁移前自动备份 `.kek*` 与 `.autokey`；文档明确数据目录就是唯一真相 |
| 8 | `init_db()`/`ensure_local_user()` 在导入期执行（[main.py:56-57](../backend/app/main.py#L56-L57)），冻结后异常没有日志出口 | 中 | 崩溃看不见原因 | core 启动最早期把 `logging` 定向到 `<userData>/logs/`，并在壳里 tail 最近 200 行进错误弹窗 |
| 9 | 白板/论文在 Chromium 版本升级后的行为漂移 | 低 | 手写延迟或渲染差异 | Electron 版本锁 `~` 范围，升级走一次回归 |

---

## 11. 需要你拍板的开放问题

1. **应用名**：桌面版叫 `Lararium` 还是沿用 `Kruskal`？（现在 [manifest.json](../frontend/public/manifest.json) 与代码内部命名是 Kruskal，README 已改 Lararium，`kruskal-frontend`、`KRUSKAL_*` 环境变量仍为旧名。建议：桌面产品名 Lararium，环境变量与代码标识暂不改，避免大范围重命名风险。）
2. **数据目录策略**：默认 `%APPDATA%\Lararium\data`（推荐，卸载不丢数据），还是允许"便携模式"把数据放在 exe 旁边（便于 U 盘携带）？后者要多写一层便携检测。
3. **端口策略**：固定 18080 优先、冲突再随机（利于 token 与书签稳定，推荐），还是始终随机（更安全）？
4. **是否要"开机自启 + 关窗进托盘"**：个人工作站通常要，但会常驻内存；先默认开还是默认关？
5. **白板 PNG 导出与打印的关系**：白板笔记现在只能导出 PNG（[notes.py:704-705](../backend/app/routers/notes.py#L704-L705)）。桌面版是否要把"白板 PNG 拼成 PDF"也做进壳（约 0.5d）？
6. **代码签名**：是否有证书/愿意买？没有的话我在文档里补一段 SmartScreen 绕过说明。

---

## 12. 附录：P0 最小改动面预览（供评审一眼看完）

```text
新增  backend/app/runtime_paths.py        ~50 行   冻结安全的路径来源
改    backend/app/config.py                ~15 行   5 处路径取值改走 runtime_paths（行为开发态等价）
新增  backend/desktop_entry.py            ~45 行   冻结入口 + 端口协商 + 就绪握手
新增  backend/app/migrate_desktop.py      ~90 行   数据目录迁移（复制+校验+回滚）
新增  backend/app/winperm.py              ~40 行   Windows ACL 等价 0600（icacls）
改    backend/app/services/runner.py      ~15 行   Windows 进程组：CREATE_NEW_PROCESS_GROUP + taskkill
改    backend/app/routers/settings.py      ~6 行   补 import os；写失败不再全静默
改    backend/app/routers/notes.py        ~60 行   新增 /print 打印路由；desktop 时 PDF 通道改道+文案修正
新增  frontend/src/utils/desktop.ts        ~5 行   window.lararium 探测
改    frontend/src/views/NoteView.vue      ~8 行   导出 PDF 桌面分支
改    frontend/src/components/ShareDialog.vue ~6 行  未配置公网基址时不生成链接
```

P0 合计：新增 ~230 行，改动 ~110 行，**不动任何业务逻辑与数据库结构**。
