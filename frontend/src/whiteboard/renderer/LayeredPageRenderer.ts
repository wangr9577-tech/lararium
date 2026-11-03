/**
 * whiteboard/renderer/LayeredPageRenderer.ts
 *
 * 白板第一阶段「分层渲染」步骤 3 —— 分层页面渲染器（纯新增文件）。
 *
 * 定位（docs/WHITEBOARD_PHASE_1_RENDERING.md §5/§6/§7）：
 *  每页三个 canvas（static / ink / live）的创建期管理、定级 DPR、
 *  静态层 / ink 层渲染、增量提交、尺寸重建、释放、worker 异步重建与 PNG 导出。
 *  Vue 组件（步骤 4）只做业务编排（输入、历史、选中、保存），不直接操作 canvas backing。
 *
 * 三层职责：
 * | 层       | 内容                                 | 何时重建 |
 * | static   | 纸张底色/横线网格点阵、PDF 底图、普通插图 | 页增删、纸面样式变化、图片拖动结束（传 excludeImgId 跳过被拖图）、尺寸重建 |
 * | ink      | 全部已提交笔迹                         | 全量：撤销/重做/局部橡皮/尺寸重建（paintInk 主线程，或
 * |          |                                      | paintInkWorker 非活动页异步）；增量：新笔结束 commitStroke
 * |          |                                      | （只 fill 该笔一条 path，不清层、不碰 static/live） |
 * | live     | 书写中湿墨、图片拖动预览、橡皮指示       | 组件 + LiveInkRenderer 逐帧管理；本类只负责其 backing
 * |          |                                      | 的定级（setActivePage / resizePage）与释放（release） |
 *
 * 坐标空间：
 *  - static / ink 层一律在「页面固有坐标」（0..page.w × 0..page.h）下绘制，
 *    由 setTransform(dpr*cssW/page.w, 0, 0, dpr*cssH/page.h, 0, 0) 映射到设备像素；
 *  - 笔迹 Path2D 缓存（StrokePathCache）同为页面固有坐标，屏幕与导出共享；
 *  - PNG 导出（renderPngFromCache）同空间 + scale 变换（文档 §6.2：不复用屏幕缓存，
 *    独立离屏 canvas，导出分辨率不受屏幕 DPR 定级影响）。
 *
 * 内存预算与释放（文档 §6）：
 *  - DPR 定级：活动页 DPR_ACTIVE(2.0)、可视非活动页 DPR_VISIBLE(1.5)；
 *    单页 backing（w*h*dpr²*4）超过 BACKING_BUDGET_BYTES(32MB) 时按
 *    2.0→1.5→1.0 依次降档，取能满足预算的最高档（最低档仍超也保持 DPR_MIN）。
 *  - release()：非活动页离开视口时三层 backing 置 1×1（释放 backing store），
 *    CSS 尺寸不变、runtime（cssWidth/cssHeight/dpr）保留、业务数据不动；
 *    重新入视口时 resizePage + 重渲染。解码图片由组件自行释放（imgCache 归组件）。
 *  - backingEstimate() 供 perf.noteBackings() 做内存估算。
 *
 * Worker 异步重建（文档 §7；USE_WORKER_INK_REBUILD flag 或 opts.worker 启用）：
 *  - 只把「非活动页 ink 层全量重建」移入 render.worker.ts；worker 接收轻量结构化
 *    克隆（WStroke），输出整页 ImageBitmap（postMessage transfer，零拷贝）。
 *  - 协议摘要：rebuildInk{reqId,pageIndex,revision,page,cssW,cssH,dpr,strokes}
 *    → inkBitmap{reqId,pageIndex,revision,bitmap} | inkError{...,error}。
 *  - 过期 / 回退规则（主线程 onmessage）：
 *    ① workerInflight.get(page) !== reqId（该页已有更新请求或已被取消）→ 丢弃；
 *    ② msg.revision < runtime.inkRevision + 1（期间发生其他写入，页面修订已前进）→ 丢弃；
 *    ③ 请求发出后页面 css 尺寸 / dpr 已变化（resizePage / setActivePage）→ 丢弃；
 *    ④ inkError / worker.onerror → workerOk=false，本实例永久回退主线程。
 *    任何丢弃 / 失败 → Promise resolve(false)，组件回退主线程 paintInk。
 *  - 同一页 in-flight 不排队：paintInkWorker 新请求直接 resolve(false)。
 *
 * 风格约定：2 空格缩进、无分号、单引号、ES module、不引入新依赖。
 */

import {
  PAPER_COLORS, PAPER_LINE, PAPER_DOT,
  DPR_ACTIVE, DPR_VISIBLE, DPR_MIN, BACKING_BUDGET_BYTES, USE_WORKER_INK_REBUILD,
  strokeAlpha, backingBytes,
} from '../types'
import type { PageData, StrokeV3, PaperMeta, PageRenderRuntime } from '../types'
import { StrokePathCache } from './StrokePathCache'
import type { InkPerfMonitor } from '../perf/InkPerfMonitor'
import type { WStroke, RebuildInkRequest, WorkerOutMessage } from './render.worker'

export interface LayeredPageRendererOpts {
  /** 组件的 pages 访问器（每帧读取，避免持有过期快照）。 */
  getPages(): PageData[]
  /** 只读模式：不分配 live 层。 */
  readonly?: boolean
  /** 组件图片解码缓存访问器（src → 已解码 HTMLImageElement；未解码返回 null）。 */
  getImg?(src: string): HTMLImageElement | null
  /** 是否启用 worker 异步重建（默认 USE_WORKER_INK_REBUILD）。 */
  worker?: boolean
  perf?: InkPerfMonitor
}

export class LayeredPageRenderer {
  private readonly opts: LayeredPageRendererOpts
  private readonly useWorker: boolean
  /** pageIndex → 页面运行时。 */
  private runtimes = new Map<number, PageRenderRuntime>()
  /** 笔迹 Path2D 缓存（页面固有坐标，屏幕/导出共享）。 */
  private cache = new StrokePathCache()
  /** 活动页下标（-1 = 无）。 */
  private activeIndex = -1
  private worker: Worker | null = null
  private workerOk = true
  private reqSeq = 0
  /** pageIndex → 最新 reqId（在途标记；命中即视为该页已有 worker 请求）。 */
  private workerInflight = new Map<number, number>()
  /** worker reqId → 待决 Promise 的 resolver（收到 inkBitmap/inkError 时定案）。 */
  private workerResolvers = new Map<number, (ok: boolean) => void>()
  /** worker reqId → 发出时刻的请求快照（回收时校验尺寸 / dpr 是否仍一致）。 */
  private workerReqs = new Map<number, RebuildInkRequest>()

  constructor(opts: LayeredPageRendererOpts) {
    this.opts = opts
    this.useWorker = opts.worker ?? USE_WORKER_INK_REBUILD
  }

  /* ---------------- 页面运行时管理 ---------------- */

  /** 建立 / 更新第 i 页 runtime（canvas 引用来自组件模板）。
   *  重新注册时修订号归零、disposed 清除、css/dpr 置 0 ——
   *  调用方必须随后 resizePage + paintStatic / paintInk 重建三层。 */
  registerPage(i: number, c: { static: HTMLCanvasElement; ink: HTMLCanvasElement; live: HTMLCanvasElement | null }): void {
    this.runtimes.set(i, {
      pageIndex: i,
      staticCanvas: c.static,
      inkCanvas: c.ink,
      liveCanvas: c.live,
      staticRevision: 0,
      inkRevision: 0,
      cssWidth: 0,
      cssHeight: 0,
      dpr: 0,
      disposed: false,
    })
    // 新页面上任何旧的在途 worker 请求（页序变化残留）已无效
    this.cancelWorkerForPage(i)
  }

  /** 移除第 i 页：runtime 置 disposed 并删除；在途 worker 请求以 false 定案。 */
  dropPage(i: number): void {
    const rt = this.runtimes.get(i)
    if (rt) rt.disposed = true
    this.runtimes.delete(i)
    this.cancelWorkerForPage(i)
    if (this.activeIndex === i) this.activeIndex = -1
  }

  /** 全量重建 map 骨架（页增删 / 换文档后调用）：
   *  全部 runtime 置 disposed、清除在途 worker 请求（resolve false）、清空路径缓存
   *  （页下标整体错位，旧缓存键不再可靠）。
   *  count 为新页数（供调用方/日志对账）；骨架由组件随后逐页
   *  registerPage(i, canvases) 重建，再 resizePage + 层重建。 */
  resetPages(count: number): void {
    for (const rt of this.runtimes.values()) rt.disposed = true
    this.runtimes.clear()
    this.activeIndex = -1
    for (const resolve of this.workerResolvers.values()) resolve(false)
    this.workerResolvers.clear()
    this.workerInflight.clear()
    this.workerReqs.clear()
    this.cache.clear()
    void count
  }

  /** 仅标记活动页下标（不触碰 backing）。 */
  setActiveIndex(i: number): void {
    this.activeIndex = i
  }

  /* ---------------- DPR 定级与尺寸 ---------------- */

  /** 定级：活动页 DPR_ACTIVE(2.0)，其余可视页 DPR_VISIBLE(1.5)。 */
  tierDpr(i: number): number {
    return i === this.activeIndex ? DPR_ACTIVE : DPR_VISIBLE
  }

  /** 核心定级 + 尺寸重建：
   *  dpr 取定级值；若 backingBytes(cssW,cssH,dpr) 超 BACKING_BUDGET_BYTES，
   *  按 2.0→1.5→1.0 降档取满足预算的最高档（最低档仍超也保持 DPR_MIN，
   *  不改变导出分辨率）。
   *  对 static / ink（以及存在时 live）设 width/height = round(css*dpr)。
   *  canvas 的 CSS 尺寸由组件 .wb-layers（inset:0 + width/height 100%）控制，
   *  此处不改 style —— 捏合缩放期间 sheet CSS 尺寸变化时 canvas 会随之拉伸
   *  （略糊），手势结束后按最终尺寸重建 backing 恢复清晰（文档 §5.6）。
   *  注意：canvas.width 赋值会清空层内容 ——
   *  调用方必须随后 paintStatic / paintInk（或 paintInkWorker）重渲染。
   *  返回实际生效的 dpr。 */
  resizePage(i: number, cssW: number, cssH: number): number {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed || cssW <= 0 || cssH <= 0) return rt ? rt.dpr : 0
    const order = [DPR_ACTIVE, DPR_VISIBLE, DPR_MIN]
    let dpr = this.tierDpr(i)
    for (const t of order) {
      if (t > dpr) continue // 不高于当前档位上调
      if (backingBytes(cssW, cssH, t) <= BACKING_BUDGET_BYTES) { dpr = t; break }
    }
    // 全部档位都超预算（极端大页）：保持最低档
    if (backingBytes(cssW, cssH, dpr) > BACKING_BUDGET_BYTES) dpr = DPR_MIN
    const bw = Math.round(cssW * dpr)
    const bh = Math.round(cssH * dpr)
    for (const cv of [rt.staticCanvas, rt.inkCanvas, rt.liveCanvas]) {
      if (!cv) continue
      cv.width = bw
      cv.height = bh
      // 注意：不设置 canvas.style —— CSS 尺寸由 .wb-layers（100%）控制，
      // 这样捏合缩放期间 backing 不动、canvas 随 sheet CSS 拉伸（文档 §5.6）。
    }
    rt.cssWidth = cssW
    rt.cssHeight = cssH
    rt.dpr = dpr
    return dpr
  }

  /** CSS 尺寸是否已与 runtime 一致（避免 pointerdown / 滚动等高频路径重复
   *  分配 backing）。只比 CSS 宽高：dpr 档位由上一次 resizePage 定档，
   *  同 CSS 尺寸下 backing 仍然有效（含超预算降档后的结果）。 */
  matchSize(i: number, cssW: number, cssH: number): boolean {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed) return false
    return rt.cssWidth === cssW && rt.cssHeight === cssH
  }

  /** 页面固有坐标 → 设备像素 transform（static/ink 共用）。未 resize 过返回 false。 */
  private setNativeTransform(ctx: CanvasRenderingContext2D, rt: PageRenderRuntime, pg: PageData): boolean {
    if (rt.cssWidth <= 0 || rt.cssHeight <= 0 || pg.page.w <= 0 || pg.page.h <= 0) return false
    ctx.setTransform((rt.dpr * rt.cssWidth) / pg.page.w, 0, 0, (rt.dpr * rt.cssHeight) / pg.page.h, 0, 0)
    return true
  }

  /* ---------------- 静态层 ---------------- */

  /** 静态层全量：纸底 + 网格/横线/点阵 + 图片（跳过 excludeImgId 与未解码图）。
   *  尺寸重建 / 纸面样式变化 / 图片拖动结束（传被拖图 id 跳过）时调用。 */
  paintStatic(i: number, excludeImgId?: string): void {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed) return
    const pg = this.opts.getPages()[i]
    if (!pg) return
    const ctx = rt.staticCanvas.getContext('2d')
    if (!ctx || !this.setNativeTransform(ctx, rt, pg)) return
    const t0 = performance.now()
    const { w, h } = pg.page
    ctx.clearRect(0, 0, w, h)
    this.drawPaperPage(ctx, w, h, pg.page.paper)
    for (const im of pg.images) {
      if (im.id === excludeImgId) continue
      const el = this.opts.getImg ? this.opts.getImg(im.src) : null
      if (!el || !el.complete || el.naturalWidth === 0) continue
      const pw = im.w * w
      ctx.drawImage(el, im.x * w, im.y * h, pw, pw * im.r)
    }
    rt.staticRevision += 1
    this.opts.perf?.noteLayerRebuild('static', i, performance.now() - t0)
  }

  /** 纸张绘制（页面固有坐标版，组件 drawPaper 856-894 行的移植）：
   *  底色 fillRect；grid 双线网 step=w/16；dots 点阵 step=w/16（点径 2.5 页面单位）；
   *  ruled 行距 h/26 + 红色横线 + 左侧竖线 mx=w*0.07；线宽统一 1.5 页面单位；
   *  颜色用 PAPER_LINE / PAPER_DOT / 纸色 hex（与组件同尺寸下视觉一致）。 */
  private drawPaperPage(ctx: CanvasRenderingContext2D, w: number, h: number, paper: PaperMeta): void {
    if (w <= 0 || h <= 0) return
    const hex = (PAPER_COLORS.find((p) => p.key === paper.color) || PAPER_COLORS[0]).hex
    ctx.fillStyle = hex
    ctx.fillRect(0, 0, w, h)
    const st = paper.style
    if (st === 'plain') return
    ctx.save()
    if (st === 'grid' || st === 'dots') {
      const step = w / 16
      if (st === 'grid') {
        ctx.strokeStyle = PAPER_LINE[paper.color]
        ctx.lineWidth = 1.5
        ctx.beginPath()
        for (let x = step; x < w; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, h) }
        for (let y = step; y < h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
        ctx.stroke()
      } else {
        ctx.fillStyle = PAPER_DOT[paper.color]
        for (let x = step / 2; x < w; x += step) {
          for (let y = step / 2; y < h; y += step) {
            ctx.fillRect(x - 1.25, y - 1.25, 2.5, 2.5)
          }
        }
      }
    } else {
      const row = h / 26
      ctx.strokeStyle = 'rgba(200, 90, 90, 0.4)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      for (let y = row; y < h; y += row) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
      ctx.stroke()
      ctx.strokeStyle = PAPER_LINE[paper.color]
      const mx = w * 0.07
      ctx.beginPath()
      ctx.moveTo(mx, 0)
      ctx.lineTo(mx, h)
      ctx.stroke()
    }
    ctx.restore()
  }

  /* ---------------- ink 层 ---------------- */

  /** ink 层全量重建（整页已提交笔迹）：先清层，再逐笔 fill 缓存 path。
   *  空笔迹页只清层。inkRevision++；perf 记录重建耗时。 */
  paintInk(i: number): void {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed) return
    const pg = this.opts.getPages()[i]
    if (!pg) return
    const ctx = rt.inkCanvas.getContext('2d')
    if (!ctx || !this.setNativeTransform(ctx, rt, pg)) return
    const t0 = performance.now()
    const { w, h } = pg.page
    ctx.clearRect(0, 0, w, h)
    for (const s of pg.strokes) {
      const c = this.cache.getOrBuild(s, pg)
      ctx.globalAlpha = strokeAlpha(s)
      ctx.fillStyle = s.color
      ctx.fill(c.path)
    }
    ctx.globalAlpha = 1
    rt.inkRevision += 1
    this.opts.perf?.noteLayerRebuild('ink', i, performance.now() - t0)
  }

  /** 增量提交（落笔结束时调用）：只把这一笔的 path fill 到 ink 层。
   *  不清层、不碰 static/live。仅对活动页调用（非活动页 backing 可能已释放）。
   *  调用方（组件）负责本调用之后的 live 层脏区清理与 pushPayload/保存流程。 */
  commitStroke(i: number, stroke: StrokeV3): void {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed) return
    const pg = this.opts.getPages()[i]
    if (!pg) return
    const ctx = rt.inkCanvas.getContext('2d')
    if (!ctx || !this.setNativeTransform(ctx, rt, pg)) return
    const c = this.cache.getOrBuild(stroke, pg)
    ctx.globalAlpha = strokeAlpha(stroke)
    ctx.fillStyle = stroke.color
    ctx.fill(c.path)
    ctx.globalAlpha = 1
    rt.inkRevision += 1
  }

  /** 使某笔的路径缓存失效（内容/参数变化后调用；局部橡皮把一笔切成多笔时，
   *  按新 id 逐个失效旧 id 的场景由组件处理）。 */
  invalidateStroke(id: string): void {
    this.cache.invalidate(id)
  }

  /** 使整页路径缓存失效（页面固有尺寸变化 / 美化替换几何等）。 */
  invalidatePage(i: number): void {
    const pg = this.opts.getPages()[i]
    if (!pg) return
    this.cache.invalidateMany(pg.strokes.map((s) => s.id))
  }

  /* ---------------- 活动页 / 释放 / 内存估算 ---------------- */

  /** 切换活动页：
   *  ① activeIndex = i（此后 resizePage 按活动档 DPR_ACTIVE 定级）；
   *  ② 若 live canvas 存在（非只读），把三层 backing resize 到活动档
   *     （live 用活动页 dpr，与 static/ink 同步）。
   *  注意：backing 赋值会清空层内容 —— 调用方随后必须重渲染本页
   *  （paintStatic + paintInk / paintInkWorker）；旧活动页如离开视口再 release()。 */
  setActivePage(i: number): void {
    this.activeIndex = i
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed || !rt.liveCanvas) return
    if (rt.cssWidth > 0 && rt.cssHeight > 0) {
      this.resizePage(i, rt.cssWidth, rt.cssHeight)
    }
  }

  /** 非活动页离开视口：三层 backing 置 1×1，释放 GPU backing store。
   *  业务数据（strokes/images）不动，runtime（cssWidth/cssHeight/dpr）保留，
   *  CSS 尺寸不变（元素仍占位）；重新入视口时 resizePage + 重渲染。
   *  解码图片（组件 imgCache）由组件另行释放。 */
  release(i: number): void {
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed) return
    for (const cv of [rt.staticCanvas, rt.inkCanvas, rt.liveCanvas]) {
      if (!cv) continue
      cv.width = 1
      cv.height = 1
    }
  }

  /** backing store 内存估算（Σ w*h*dpr²*4，仅未 disposed 页），供 perf.noteBackings。 */
  backingEstimate(): { pageIndex: number; cssW: number; cssH: number; dpr: number }[] {
    const out: { pageIndex: number; cssW: number; cssH: number; dpr: number }[] = []
    for (const rt of this.runtimes.values()) {
      if (rt.disposed) continue
      out.push({ pageIndex: rt.pageIndex, cssW: rt.cssWidth, cssH: rt.cssHeight, dpr: rt.dpr })
    }
    return out
  }

  /* ---------------- PNG 导出 ---------------- */

  /** 导出 PNG（文档 §6.2：不复用屏幕缓存）：
   *  独立离屏 canvas，尺寸 round(page.w*scale) × round(page.h*scale)，
   *  页面固有坐标 + scale transform：底纸 → 图片（getImg 解码，im.x*page.w 换算）
   *  → 逐笔 cache.getOrBuild 后 fill（last=false，与屏幕一致）。
   *  无笔迹 / 无图也出底纸。返回 toDataURL('image/png')。 */
  renderPngFromCache(pg: PageData, scale = 2): string {
    const out = document.createElement('canvas')
    out.width = Math.round(pg.page.w * scale)
    out.height = Math.round(pg.page.h * scale)
    const ctx = out.getContext('2d')
    if (!ctx) return ''
    const { w, h } = pg.page
    ctx.setTransform(scale, 0, 0, scale, 0, 0)
    this.drawPaperPage(ctx, w, h, pg.page.paper)
    for (const im of pg.images) {
      const el = this.opts.getImg ? this.opts.getImg(im.src) : null
      if (!el || !el.complete || el.naturalWidth === 0) continue
      const pw = im.w * w
      ctx.drawImage(el, im.x * w, im.y * h, pw, pw * im.r)
    }
    for (const s of pg.strokes) {
      const c = this.cache.getOrBuild(s, pg)
      ctx.globalAlpha = strokeAlpha(s)
      ctx.fillStyle = s.color
      ctx.fill(c.path)
    }
    ctx.globalAlpha = 1
    return out.toDataURL('image/png')
  }

  /* ---------------- worker 异步重建 ---------------- */

  /** 非活动页 ink 层全量重建（worker 异步）。返回 Promise<boolean>：
   *  true = worker 完成并已回贴；false = 调用方应回退主线程 paintInk
   *  （flag/worker 不可用、前置不满足、同页 in-flight、结果过期、worker 报错）。
   *  前置：i 为非活动页、runtime 未 disposed、已 resize 过（cssWidth>0）。
   *  同一页 in-flight 时新请求不排队，直接 resolve(false)。 */
  paintInkWorker(i: number): Promise<boolean> {
    if (!this.useWorker || !this.workerOk) return Promise.resolve(false)
    if (i === this.activeIndex) return Promise.resolve(false)
    const rt = this.runtimes.get(i)
    if (!rt || rt.disposed || rt.cssWidth <= 0 || rt.cssHeight <= 0) return Promise.resolve(false)
    if (this.workerInflight.has(i)) return Promise.resolve(false)
    const pg = this.opts.getPages()[i]
    if (!pg) return Promise.resolve(false)

    const w = this.ensureWorker()
    if (!w) return Promise.resolve(false)

    const reqId = ++this.reqSeq
    const req: RebuildInkRequest = {
      kind: 'rebuildInk',
      reqId,
      pageIndex: i,
      revision: rt.inkRevision + 1, // 期望修订号（主线程回收时按 runtime.inkRevision+1 校验）
      page: { w: pg.page.w, h: pg.page.h },
      cssW: rt.cssWidth,
      cssH: rt.cssHeight,
      dpr: rt.dpr,
      strokes: pg.strokes.map<WStroke>((s) => ({
        id: s.id, tool: s.tool, color: s.color, w: s.w, tip: s.tip, sp: s.sp,
        pts: s.pts.map((p) => ({ x: p.x, y: p.y, p: p.p })),
      })),
    }
    this.workerInflight.set(i, reqId)
    this.workerReqs.set(reqId, req)
    const promise = new Promise<boolean>((resolve) => {
      this.workerResolvers.set(reqId, resolve)
    })
    try {
      w.postMessage(req)
    } catch {
      // 结构化克隆失败（理论上不会：WStroke 是纯数据）→ 回退主线程
      this.cancelWorkerForPage(i)
      return Promise.resolve(false)
    }
    return promise
  }

  /** 懒加载 worker（首次使用时创建，onmessage 统一分发）。失败返回 null。 */
  private ensureWorker(): Worker | null {
    if (this.worker) return this.worker
    try {
      const w = new Worker(new URL('./render.worker.ts', import.meta.url), { type: 'module' })
      w.onmessage = (e: MessageEvent) => {
        this.onWorkerMessage(e.data as WorkerOutMessage)
      }
      w.onerror = (e: ErrorEvent) => {
        // worker 脚本加载失败 / 未捕获异常：本实例永久回退主线程
        this.workerOk = false
        console.warn('[whiteboard] render worker unavailable, falling back to main thread', e.message)
        for (const resolve of this.workerResolvers.values()) resolve(false)
        this.workerResolvers.clear()
        this.workerInflight.clear()
        this.workerReqs.clear()
      }
      this.worker = w
      return w
    } catch {
      this.workerOk = false
      return null
    }
  }

  /** 丢弃某页在途 worker 请求（页面删除 / 重注册时），resolver 以 false 定案。 */
  private cancelWorkerForPage(i: number): void {
    const reqId = this.workerInflight.get(i)
    if (reqId === undefined) return
    this.workerInflight.delete(i)
    const resolve = this.workerResolvers.get(reqId)
    this.workerResolvers.delete(reqId)
    this.workerReqs.delete(reqId)
    resolve(false)
  }

  /** worker 消息分发（协议见文件头；过期判定见规则 ①②③）。 */
  private onWorkerMessage(msg: WorkerOutMessage): void {
    if (!msg || typeof msg !== 'object') return
    if (msg.kind === 'pong') return

    if (msg.kind === 'inkError') {
      // 规则 ④：worker 侧失败 → 永久回退主线程
      this.workerOk = false
      const resolve = this.workerResolvers.get(msg.reqId)
      this.workerResolvers.delete(msg.reqId)
      this.workerReqs.delete(msg.reqId)
      if (msg.pageIndex >= 0 && this.workerInflight.get(msg.pageIndex) === msg.reqId) {
        this.workerInflight.delete(msg.pageIndex)
      }
      if (resolve) resolve(false)
      return
    }

    // kind === 'inkBitmap'
    const req = this.workerReqs.get(msg.reqId)
    const resolve = this.workerResolvers.get(msg.reqId)
    const rt = this.runtimes.get(msg.pageIndex)
    const inflight = this.workerInflight.get(msg.pageIndex)
    const stale =
      !req || !rt || rt.disposed ||
      inflight !== msg.reqId ||                  // ① 该页已有更新请求（或已被取消）
      msg.revision < rt.inkRevision + 1 ||       // ② 页面修订已被其他写入推进
      rt.cssWidth !== req.cssW ||                // ③ 请求发出后页面尺寸/档位已变
      rt.cssHeight !== req.cssH ||
      rt.dpr !== req.dpr
    if (stale) {
      msg.bitmap.close()
      this.workerResolvers.delete(msg.reqId)
      this.workerReqs.delete(msg.reqId)
      if (resolve) resolve(false)
      return
    }

    // 命中：ink canvas 当前 backing 与请求尺寸不一致（如 release 后的 1×1）→
    // 先按 req 的 css/dpr 重设 backing，再以恒等变换贴满位图
    const canvas = rt.inkCanvas
    const bw = Math.round(req.cssW * req.dpr)
    const bh = Math.round(req.cssH * req.dpr)
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw
      canvas.height = bh
    }
    this.workerResolvers.delete(msg.reqId)
    this.workerReqs.delete(msg.reqId)
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      msg.bitmap.close()
      if (resolve) resolve(false)
      return
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.drawImage(msg.bitmap, 0, 0, canvas.width, canvas.height)
    msg.bitmap.close()
    rt.inkRevision = msg.revision
    this.workerInflight.delete(msg.pageIndex)
    if (resolve) resolve(true)
  }

  /* ---------------- 销毁 ---------------- */

  /** 组件卸载：terminate worker、全部 runtime 置 disposed、清空路径缓存。 */
  dispose(): void {
    if (this.worker) {
      try { this.worker.terminate() } catch { /* ignore */ }
      this.worker = null
    }
    this.workerOk = false
    for (const resolve of this.workerResolvers.values()) resolve(false)
    this.workerResolvers.clear()
    this.workerInflight.clear()
    this.workerReqs.clear()
    for (const rt of this.runtimes.values()) rt.disposed = true
    this.cache.clear()
  }
}
