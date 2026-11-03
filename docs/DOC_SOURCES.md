# 项目文档源（外部 md 挂载）

> 面向的问题：博客的笔记是 **AES-256-GCM 加密落盘**的私有内容（agent 读不到），
> 而项目里的 md 是明文（网站看不到）。结果同一份东西要写两遍，且两边必然分叉。
>
> 结论：**不做第二份**。把项目目录挂成「文档源」，网站退化为它的**视图 + 可选编辑器**，
> 唯一真相始终是项目目录里的那个文件 —— git 管它，agent 读它，网页改它。

## 1. 数据模型

- **不新增表**：源配置是一段 JSON，存在 `settings` 表 `key='doc_sources'`：

  ```json
  [{"id":"a1b2c3d4","name":"ocean","root":"ocean","include":["docs/**","README.md"],"readonly":false}]
  ```

  `root` 是**相对 `KRUSKAL_CODE_ROOT`**（默认 `~/workspace`）的路径，
  空串表示工作区根目录本身。`include` 为空 = 该目录下全部 md。
- **不复制、不迁移、不加密搬运**：文件永远待在项目里；网站读的是它，写回也是它。
- 站内的加密笔记体系（`data/notes/`）**与本模块互不写入**：两边各有各的用途，
  需要把外部文档"收进博客体系"时用阅读页的 **「存为博客笔记」**（明确标注是快照，会分叉）。

## 2. 接口（`backend/app/routers/fs.py`，前缀 `/api/fs`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/fs/sources` | 已挂载源 + 每个源的 md 篇数（篇数带 60s 缓存） |
| POST | `/api/fs/sources` | 挂载一个目录（只写配置） |
| PUT | `/api/fs/sources/{sid}` | 改名称/目录/include/只读 |
| DELETE | `/api/fs/sources/{sid}` | **只删挂载配置**，磁盘文件不动 |
| GET | `/api/fs/discover` | 列出候选项目目录（有 md 或有 `.git`），只列不写；2.5s 预算，超时返回已发现部分 |
| GET | `/api/fs/tree?sid=&path=` | 某一层的目录 + md 文件（懒加载，每层 ≤200 项） |
| GET | `/api/fs/file?sid=&path=` | 读 md（≤1MB）：正文 + 标题/标签/摘要 + `sha256`（保存冲突检测用） |
| PUT | `/api/fs/file` | 原子写回：`{sid,path,content,base_sha256}`，指纹不符 → 409 |
| GET | `/api/fs/blob?sid=&path=` | md 内嵌图片只读通道（`<img>` 带不了鉴权头 → 前端取 blob 换 objectURL） |
| GET | `/api/fs/search?q=&sid=` | 跨源/指定源搜文件名 + 正文（命中 ≤50、扫描 ≤4000） |

所有接口都带 `Depends(get_current)`，且被 `/api` 全局鉴权中间件兜住（未登录 401）。

## 3. 安全边界（红线）

1. **白名单根**：源根目录必须 `resolve()` 后落在 `CODE_ROOT` 之内；每次请求重新校验（配置被改/目录被删也兜住）。
2. **越界防护**：拒绝 `..` 段；`resolve()` 后必须仍在该源 root 内 —— **符号链接逃逸一并封死**；
   写回额外拒绝符号链接文件（避免 `os.replace` 打歪目标）。
3. **只挂 md**：`.md/.markdown`，其它扩展名读写一律 400；图片只有 `blob` 通道且限图片扩展名。
4. **噪声目录**：`.git` / `node_modules` / `.venv` / `dist` / `build` / `data` / `tmp` / 缓存目录 / 点开头文件
   在任何深度都跳过；想挂其中的文档，需在 include 规则里**显式写出路径**放行（如 `data/docs/**`）。
5. **限额**：单文件 1MB（读写同限）、目录每层 200 项、树按需懒加载、搜索命中 50 / 扫描 4000 / 深度 8、图片 20MB。
6. **写回是乐观锁**：`base_sha256` 必须等于磁盘当前内容哈希，否则 409 并回传当前指纹 ——
   与 agent 并发编辑时**绝不静默覆盖**；前端给「覆盖（以磁盘版为新基线再写）/ 载入磁盘版 / 另存为博客笔记」三选。
7. **原子写**：同目录 `.名字.krswrite-<rand>` 临时文件 + `os.replace`，权限沿用原文件；失败清理临时文件。
8. **本模块没有任何删除/移动/重命名文件的操作**；「移除源」只删配置行。
9. **不进分享**：外部文档源永远不进 `share` 快照（分享页是加密快照，天然拿不到这里的内容）。

## 4. 前端

| 文件 | 作用 |
|---|---|
| `api/fs.ts` | 接口封装 + 类型 |
| `utils/docmedia.ts` | md 内嵌**相对路径**图片 → 带鉴权 blob URL（`./fig/1.png`、`../a.png` 都支持；绝对路径与 http 外链不处理） |
| `components/FileTree.vue` | 懒加载目录树（只出目录与 md） |
| `views/Projects.vue` | 主页面：源列表 + 目录树 + 文件列表 + 全文搜索 + 源管理 / 发现候选 |
| `views/ProjectDocView.vue` | 阅读页：`renderMd`（与笔记页同一渲染管线）+ 目录 + 复制路径 + 存为博客笔记 |
| `views/ProjectDocEdit.vue` | 编辑页：CodeMirror + 显式保存（Ctrl/⌘+S）+ 冲突三选 + 未保存离开确认 |

路由：`/projects`（导航「工作区」组）、`/projects/doc?sid=&path=`、`/projects/edit?sid=&path=`。

## 5. 非目标 / 后续可做

- **新建 md 文件**：当前 `PUT /api/fs/file` 只改已存在的文件（404 拒绝新建）—— 需要时再加 `POST`，并同样限扩展名与目录。
- **git 状态显示**：本版按需求"保持轻量"未做（不跑 git 子进程）。要显示分支/dirty 时加 `GET /api/fs/git`。
- **与工作台打通**：`workbench_links.target_type` 增 `doc`，让事项能直接挂外部文档。
- 与 git 历史里那版 M8 `fs.py`（代码工作区：浏览代码 + `run` 后台跑命令）的关系：
  那版在工作区里已被删除、前端也从未调用过；本模块**复用 `/api/fs` 前缀但只做文档**。
  若以后要恢复"在线跑脚本"能力，建议另起 `/api/code` 前缀或与本文档源明确合并，避免语义混淆。