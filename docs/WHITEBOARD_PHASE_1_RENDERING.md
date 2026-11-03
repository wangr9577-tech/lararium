# 白板书写体验第一阶段：分层渲染与性能基线

> 状态：实施方案，尚未编码  
> 项目：Kruskal 个人站  
> 目标文件：`frontend/src/components/WhiteboardCanvas.vue` 及新增的 `frontend/src/whiteboard/` 模块  
> 前置条件：保留现有 `v-model`、只读预览、分页、图片、撤销/重做和 PNG 导出行为

## 1. 阶段目标

本阶段只解决一件事：让白板的渲染成本不再随当前页全部历史内容线性增长。

完成后，书写时只更新当前笔迹所在的“湿墨层”，纸张、图片和历史笔迹均使用缓存。内容很多时，笔尖响应不应明显变慢。

### 1.1 成功指标

| 指标 | 目标 |
|---|---|
| 书写期间主线程帧耗时 P95 | `< 12 ms` |
| 书写期间长任务（Long Task） | 单次 `< 50 ms`，连续书写期间为 0 |
| 1000 条历史笔迹页面的书写帧率 | 60 Hz 屏稳定接近 60 FPS；120 Hz 屏尽量接近 120 FPS |
| 单次 `pointer` 事件到湿墨提交的 JS 延迟 P95 | `< 8 ms`，不含显示器扫描延迟 |
| 撤销、重做、缩放后的重建 | 不阻塞下一次落笔；可见页优先 |
| 兼容性 | v1/v2 白板数据正常加载；保存后不丢页、不丢图、不丢笔迹 |

### 1.2 非目标

- 本阶段不接入 AI。
- 本阶段不做字符识别和字形替换。
- 本阶段不追求新的笔刷视觉风格；继续使用 `perfect-freehand`。
- 本阶段不改变笔记 API，也不改变 `NoteEdit.vue` 的 1.5 秒停笔自动保存约定。

## 2. 当前问题

当前 `WhiteboardCanvas.vue` 的书写链路为：

```text
pointermove
  -> cur.push(point)
  -> scheduleRedraw()
  -> requestAnimationFrame
  -> paint(activePage)
  -> 清空整页
  -> 重画纸张
  -> 重画全部图片
  -> 对全部历史笔迹重新调用 perfect-freehand
  -> 重画当前笔迹
```

主要成本：

1. `paint()` 每帧清空整张高 DPI 画布。
2. `drawOne()` 每帧为每条历史笔迹重新创建数组、轮廓和 `Path2D`。
3. 网格纸、PDF/PPT 底图、历史笔迹等静态内容也参与每帧重绘。
4. `devicePixelRatio` 上限为 2.5，一张 A4 页面可能包含数百万像素。
5. 当前书写点放在 Vue `ref` 中，热路径仍受组件响应式状态影响。

## 3. 总体架构

每个可见页面拆成三个视觉层：

```text
wb-sheet
├── staticCanvas  纸张、网格、PDF/PPT/插图
├── inkCanvas     已提交的历史笔迹
└── liveCanvas    当前笔迹、选择框、橡皮指示、预测尾迹
```

### 3.1 各层更新条件

| 层 | 更新条件 | 是否参与每帧书写 |
|---|---|---|
| `staticCanvas` | 页面尺寸、纸张样式、图片内容/位置变化 | 否 |
| `inkCanvas` | 笔迹提交、擦除、撤销、重做、尺寸变化 | 否；落笔结束时增量提交 |
| `liveCanvas` | 当前笔迹、悬停、选择操作 | 是，只画活动页 |

### 3.2 Vue 组件边界

`WhiteboardCanvas.vue` 继续负责：

- 工具栏和 Vue 状态；
- 页面增删、序列化、撤销栈；
- 组件对外 API：`modelValue`、`readonly`、`renderPng()`；
- 生命周期和模块装配。

新增非响应式模块负责高频路径：

```text
frontend/src/whiteboard/
├── types.ts
├── payload.ts
├── geometry.ts
├── renderer/
│   ├── LayeredPageRenderer.ts
│   ├── StrokePathCache.ts
│   ├── LiveInkRenderer.ts
│   └── render.worker.ts          # 第二个小步骤再启用
├── input/
│   └── StrokeBuffer.ts
└── perf/
    └── InkPerfMonitor.ts
```

不要一次把整个组件重写。先以适配器方式把 `paint()` 的职责逐步移到 renderer，保持页面/历史操作逻辑不动。

## 4. 数据模型演进

### 4.1 保持读兼容

当前有效格式：

- v1：单页 `{ page, strokes }`
- v2：多页 `{ v: 2, pages }`

第一阶段可以继续写 v2，也可以提前写 v3。推荐引入 v3，但所有新字段均为可选字段，读取 v1/v2 时补默认值。

```ts
interface InkSampleV3 {
  x: number       // 归一化页面坐标
  y: number
  p: number       // 0..1
  t?: number      // 相对该笔起点的毫秒数
  tx?: number     // tiltX，角度
  ty?: number     // tiltY，角度
  tw?: number     // twist，角度
}

interface StrokeV3 {
  id: string
  tool: Tool
  color: string
  w: number
  tip?: TipKey
  sp?: boolean
  pts: InkSampleV3[]
  rev?: number
}
```

第一阶段必须先增加稳定 `stroke.id`。缓存键不能依赖数组下标，因为整笔擦除、撤销和跨页操作都会改变下标。

### 4.2 规范坐标

路径缓存使用页面固有坐标，而不是 CSS 像素：

```text
pageX = normalizedX * page.w
pageY = normalizedY * page.h
pageStrokeWidth = stroke.w * page.w
```

渲染时由 Canvas transform 映射到当前 CSS 尺寸。这样普通缩放无需重新运行 `perfect-freehand`，只需重建位图层或改变展示 transform。

### 4.3 迁移策略

1. 加载 v1/v2 时为缺少 ID 的笔迹生成稳定 ID。
2. 内存中统一转为 v3 类型。
3. 首次内容修改后保存为 v3。
4. `parsePayload()` 必须保留 v1/v2 分支。
5. 后端 `notes.py` 当前只检查 `strokes/pages`，无需修改即可接受 v3。
6. PDF/PPT 导入继续生成 v2，前端加载时透明升级；后续单独改为 v3。

## 5. 渲染器设计

### 5.1 页面运行时对象

```ts
interface PageRenderRuntime {
  pageIndex: number
  staticCanvas: HTMLCanvasElement
  inkCanvas: HTMLCanvasElement
  liveCanvas: HTMLCanvasElement | null
  staticRevision: number
  inkRevision: number
  cssWidth: number
  cssHeight: number
  dpr: number
  disposed: boolean
}
```

只有活动页持有 `liveCanvas` 的完整 backing store。非活动页可以只保留合成后的 `ImageBitmap` 或降低 DPR，以控制长文档内存。

### 5.2 路径缓存

`StrokePathCache` 保存：

```ts
interface CachedStrokePath {
  strokeId: string
  revision: number
  pageWidth: number
  path: Path2D
  bounds: { x: number; y: number; w: number; h: number }
}
```

失效条件：

- 笔迹点或笔刷参数改变；
- 页面固有宽高改变；
- 美化阶段替换了几何；
- 擦除把一笔切成多笔。

CSS 缩放和 DPR 改变不应使矢量路径缓存失效。

### 5.3 湿墨渲染

第一版采用“只重算当前一笔，不重画历史内容”：

1. 新采样加入非响应式 `StrokeBuffer`。
2. 每帧最多运行一次 `perfect-freehand`。
3. 记录上一帧和当前帧笔迹包围盒。
4. 只清理两个包围盒的并集，外扩最大笔宽和抗锯齿余量。
5. 在 `liveCanvas` 重画当前笔迹。

极长单笔仍可能随点数增长。第一阶段先记录指标；若单笔超过 1500 点后 P95 超标，再实现“冻结已稳定前缀，只重算最后 48～96 点”的尾段算法。

### 5.4 笔迹提交

`pointerup` 时：

1. 生成最终 Stroke 数据。
2. 生成并缓存最终 `Path2D`。
3. 直接把该路径增量绘制到 `inkCanvas`。
4. 清空 `liveCanvas` 对应脏区。
5. 更新页面 ink revision。
6. 触发一次 `update:modelValue`，由现有 1.5 秒逻辑自动保存。

撤销、重做、局部橡皮会触发 ink 层重建，不要求增量修补所有复杂情况。

### 5.5 静态层

静态层包含：

- 纸张底色；
- 横线、网格、点阵；
- PDF/PPT 页面图；
- 普通插图。

图片移动期间可以在 `liveCanvas` 显示预览；拖动结束后才重建 static 层，避免每个移动事件重绘底图。

### 5.6 缩放

捏合缩放分成两段：

- 手势进行中：只改变页面容器的 CSS transform/尺寸，不调整 canvas backing store。
- 手势结束：按最终尺寸重建可见页 backing store，优先活动页，然后空闲时补相邻页。

这样不会在每个双指移动事件中重复分配大画布。

## 6. 内存管理

三个全尺寸高 DPI canvas 同时存在会快速占用数百 MB，必须设置预算。

### 6.1 建议策略

- 活动页：static + ink + live，DPR 上限 2.0。
- 可视但非活动页：static + ink，必要时合成为一个 bitmap。
- 预加载页：单个合成 bitmap，DPR 上限 1.5。
- 远离视口页：释放 backing store 和解码图片，仅保留业务数据。
- `IntersectionObserver` 继续作为分配/释放入口。
- 单页 backing store 超过 32MB 时自动降低该页 DPR，不改变导出分辨率。

### 6.2 导出

`renderPng()` 不复用屏幕缓存。它应在独立离屏 canvas 中按目标导出尺寸依次绘制 static 内容和所有缓存路径，避免屏幕 DPR 策略降低导出质量。

## 7. Worker 分工

第一小步不要立刻把所有绘制放入 Worker，以免同时引入分层和线程通信两个变量。

建议顺序：

1. 主线程完成三层架构和路径缓存。
2. 性能基准通过后，把“非活动页 ink 层全量重建”移到 `render.worker.ts`。
3. Worker 接收结构化克隆后的轻量笔迹数据，输出 `ImageBitmap`。
4. 图片底图仍由主线程 `createImageBitmap()` 解码后传入，避免复制 base64 字符串。
5. 所有请求携带 `{ pageIndex, revision }`；旧 revision 的结果直接丢弃。

`Path2D` 不能可靠地跨 Worker 传输，因此 Worker 内部直接绘制并返回位图，不返回路径对象。

## 8. 性能观测

新增仅开发环境启用的 `InkPerfMonitor`：

```ts
interface InkFrameMetric {
  eventTs: number
  renderStart: number
  renderEnd: number
  pointCount: number
  historicalStrokeCount: number
  dirtyArea: number
}
```

记录并在控制台汇总：

- 输入到渲染调用延迟 P50/P95/P99；
- 每帧 `perfect-freehand` 耗时；
- ink/static 层重建耗时；
- backing store 内存估算；
- 丢帧和 Long Task 数量。

不要记录坐标、文字内容或图片数据到服务端日志。

## 9. 文件级改动清单

| 文件 | 改动 |
|---|---|
| `frontend/src/components/WhiteboardCanvas.vue` | 模板改为分层 canvas；业务状态调用 renderer；删除书写热路径中的整页 `paint()` |
| `frontend/src/whiteboard/types.ts` | v3 类型、运行时类型 |
| `frontend/src/whiteboard/payload.ts` | v1/v2/v3 解析与迁移 |
| `frontend/src/whiteboard/renderer/LayeredPageRenderer.ts` | 页面层创建、尺寸、缓存、重建和释放 |
| `frontend/src/whiteboard/renderer/StrokePathCache.ts` | `perfect-freehand` 结果和边界缓存 |
| `frontend/src/whiteboard/renderer/LiveInkRenderer.ts` | 当前笔迹和脏矩形更新 |
| `frontend/src/whiteboard/renderer/render.worker.ts` | 非活动页异步重建，第二小步启用 |
| `frontend/src/whiteboard/input/StrokeBuffer.ts` | 非响应式当前笔迹缓冲 |
| `frontend/src/whiteboard/perf/InkPerfMonitor.ts` | 开发态指标 |

## 10. 实施步骤

### P1.1 建立基准

- 准备 10、100、500、1000 条笔迹的固定测试页。
- 记录当前版本的帧耗时、内存和输入延迟。
- 增加开发态性能采样，不改变行为。

### P1.2 引入数据和路径缓存

- 增加 Stroke ID。
- 把轮廓生成统一为页面固有坐标。
- 增加 `StrokePathCache`。
- 暂时仍由旧 `paint()` 使用缓存，验证输出一致。

### P1.3 拆分三层

- 改页面 DOM。
- static/ink/live 分别渲染。
- 保持选择、橡皮、图片操作和只读模式可用。

### P1.4 增量湿墨

- 当前笔迹只画 live 层。
- 落笔结束增量提交 ink 层。
- 撤销、擦除等复杂操作走 ink 全量重建。

### P1.5 缩放与内存

- 捏合期间仅 CSS 变换。
- 手势结束重建 backing store。
- 可视区外释放资源。

### P1.6 Worker

- 只迁移非活动页和撤销后的全量重建。
- 保留关闭 Worker 的 feature flag。

## 11. 测试方案

### 11.1 单元测试

- v1/v2/v3 payload 互相兼容。
- stroke ID 稳定且不重复。
- 缓存命中与所有失效条件。
- 页面坐标到 CSS 坐标的缩放误差。
- 脏矩形包含完整笔迹边缘。
- Worker revision 过期结果不会覆盖新页面。

### 11.2 浏览器自动化

- 合成 1000 条历史笔迹后连续输入 10 秒。
- 书写、撤销、重做、局部擦除、整笔擦除。
- 多页滚动、切页、捏合缩放后继续书写。
- PDF/PPT 底图页和普通空白页。
- readonly 页面不创建 live backing store。
- PNG 导出与屏幕内容一致。

### 11.3 真机测试

- Chromium + Windows Ink 触控笔。
- Android Chromium + 主动笔。
- iPad Safari + Apple Pencil。
- 鼠标和触控板回归。
- 低刷新率和高刷新率屏幕各一次。

真机测试必须使用高速摄像或浏览器时间戳进行前后对比，不能只凭主观感觉判断。

## 12. 发布与回滚

增加临时 feature flag：

```ts
const USE_LAYERED_RENDERER = true
```

发布步骤：

1. 内部默认开启新 renderer。
2. 旧 renderer 保留一个版本周期，仅用于紧急回滚。
3. 保存格式继续可被旧版本读取；v3 新字段必须允许旧版本忽略。
4. 观察一周无数据损坏后删除旧热路径。

回滚只切换 renderer，不回退已经保存的数据。

## 13. 验收清单

- [ ] 1000 条历史笔迹时继续书写无明显随内容增长的延迟。
- [ ] 书写帧不再调用纸张、图片和全部历史笔迹的全量绘制。
- [ ] 单笔提交后湿墨与干墨之间没有闪烁、重影或空白帧。
- [ ] 撤销、重做、擦除、缩放、分页和导出全部通过。
- [ ] v1/v2 数据加载并保存后内容一致。
- [ ] 远离视口页面释放 backing store。
- [ ] 生产构建通过，无新增控制台异常。
- [ ] 新 renderer 可通过单一开关回滚。

