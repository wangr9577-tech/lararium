/**
 * whiteboard/renderer/render.worker.ts
 *
 * 白板第一阶段「分层渲染」步骤 5 —— 非活动页 ink 层全量重建 Worker（纯新增文件）。
 *
 * 定位（docs/WHITEBOARD_PHASE_1_RENDERING.md §7 / P1.6）：
 *  - 只用于「非活动页 ink 层全量重建」：把撤销/擦除/切页触发的整页 ink 重绘
 *    挪出书写热路径，Worker 输出整页位图，主线程回贴到 ink 层。
 *  - 主线程按 { pageIndex, revision } 丢弃过期结果：同一页的旧 revision 结果
 *    直接丢弃，不会覆盖新页面。
 *  - 该功能由 USE_WORKER_INK_REBUILD flag（../types）控制，默认关闭；
 *    flag 为 false 时主线程走原主线程重建路径，本文件不参与。
 *
 * 主线程创建方式（供步骤 3 LayeredPageRenderer 使用）：
 *
 *   new Worker(new URL('./render.worker.ts', import.meta.url), { type: 'module' })
 *
 * 消息协议（全部 in 消息带 reqId，供主线程去重 / 丢弃过期结果）：
 *
 *   in  { kind: 'ping' }
 *     → out { kind: 'pong' }
 *
 *   in  { kind: 'rebuildInk',
 *         reqId: number, pageIndex: number, revision: number,
 *         page: { w: number; h: number },  // 页面固有宽高
 *         cssW: number, cssH: number, dpr: number,
 *         strokes: WStroke[] }             // 归一化坐标的轻量结构化克隆数据
 *     → out { kind: 'inkBitmap', reqId, pageIndex, revision, bitmap: ImageBitmap }
 *         （bitmap 经 postMessage(msg, [bitmap]) transfer，零拷贝移交所有权；
 *           本协议不使用 event.ports / MessagePort 通道）
 *     或  { kind: 'inkError', reqId, pageIndex, revision, error: string }
 *         （OffscreenCanvas 2D 上下文不可用，或绘制过程抛异常）
 *
 * 约定（文档 §7）：
 *  - 只传轻量结构化克隆数据（WStroke），不传 Path2D（不可靠跨线程）或
 *    base64 图片字符串；
 *  - Worker 内部直接绘制并 transferToImageBitmap()，不返回路径对象；
 *  - Worker 内不引用任何 DOM（document / window）。
 *
 * 绘制逻辑与 WhiteboardCanvas.vue 的 strokeOpts / drawOne 视觉等价：
 *  已提交笔迹一律 last=false；outline 中点法 Path2D（首点 moveTo、
 *  其余 quadraticCurveTo 中点、closePath）；
 *  globalAlpha = tool==='hl' ? 0.32 : tip==='marker' ? 0.92 : 1。
 *
 * 风格约定：2 空格缩进、无分号、单引号、不引入新 npm 依赖。
 */

import { getStroke } from 'perfect-freehand'
import { strokeAlpha } from '../types'
import type { Tool, TipKey, StrokeV3 } from '../types'
import { strokeOptsPage } from './StrokePathCache'

/* ---------------- 消息协议类型 ---------------- */

/** 传给 worker 的轻量笔迹：pts 为归一化坐标 0..1，worker 内换算页面固有坐标。
 *  由 StrokeV3 投影而来（只取 x/y/p），可安全结构化克隆。 */
export interface WStroke {
  id: string
  tool: Tool
  color: string
  w: number
  tip?: TipKey
  sp?: boolean
  bv?: 1
  sensitivity?: number
  opacity?: number
  pts: { x: number; y: number; p: number }[]
}

/** 主线程 → worker：非活动页 ink 层全量重建请求。 */
export interface RebuildInkRequest {
  kind: 'rebuildInk'
  /** 请求 ID：主线程用它去重 / 丢弃过期结果。 */
  reqId: number
  pageIndex: number
  /** 页内 ink 层修订号；旧 revision 的结果由主线程直接丢弃。 */
  revision: number
  /** 页面固有宽高（点坐标与笔宽换算基准）。 */
  page: { w: number; h: number }
  cssW: number
  cssH: number
  dpr: number
  strokes: WStroke[]
}

/** worker → 主线程：ping 响应（握手 / 探活）。 */
export interface PongMessage {
  kind: 'pong'
}

/** worker → 主线程：ink 层位图（bitmap 经 transfer 移交，只能使用一次）。 */
export interface InkBitmapMessage {
  kind: 'inkBitmap'
  reqId: number
  pageIndex: number
  revision: number
  bitmap: ImageBitmap
}

/** worker → 主线程：重建失败（OffscreenCanvas 不支持或绘制异常）。 */
export interface InkErrorMessage {
  kind: 'inkError'
  reqId: number
  pageIndex: number
  revision: number
  error: string
}

export type WorkerInMessage = { kind: 'ping' } | RebuildInkRequest
export type WorkerOutMessage = PongMessage | InkBitmapMessage | InkErrorMessage

/* ---------------- 工具 ---------------- */

/** DOM lib 下 self 被推导为 Window，其 postMessage(message, targetOrigin, transfer?)
 *  与 WorkerGlobalScope.postMessage(message, transfer) 签名不同。
 *  运行时本模块运行在 worker 内，这里按 worker 侧签名调用（transfer 列表移交所有权）。 */
function workerPost(message: unknown, transfer: Transferable[] = []): void {
  ;(self as unknown as Worker).postMessage(message, transfer)
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/* ---------------- 处理逻辑 ---------------- */

/** 重建整页 ink 层并回传 ImageBitmap（已提交笔迹一律 last=false）。 */
function handleRebuildInk(msg: RebuildInkRequest): void {
  const { reqId, pageIndex, revision, page, cssW, cssH, dpr, strokes } = msg
  const fail = (error: unknown) => {
    workerPost({ kind: 'inkError', reqId, pageIndex, revision, error: errorMessage(error) })
  }
  try {
    const canvas = new OffscreenCanvas(Math.round(cssW * dpr), Math.round(cssH * dpr))
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      fail('OffscreenCanvas 2d context unavailable')
      return
    }
    // 此后为页面固有坐标：归一化 → page 单位 → backing store（dpr*css 像素）
    ctx.setTransform((dpr * cssW) / page.w, 0, 0, (dpr * cssH) / page.h, 0, 0)

    for (const stroke of strokes) {
      if (!stroke.pts.length) continue
      // 归一化坐标 → 页面固有坐标（与组件 drawOne 的 x*cssW 换算等价：
      // 笔宽走 strokeOptsPage(stroke, false, page.w)，再乘 setTransform 缩放）
      const points: [number, number, number][] = stroke.pts.map(
        (p) => [p.x * page.w, p.y * page.h, p.p],
      )
      const opts = strokeOptsPage(stroke, stroke.bv === 1, page.w)
      const outline = getStroke(points, opts as any)
      if (!outline.length) continue
      // 中点法 Path2D（与组件 drawOne 一致）
      const path = new Path2D()
      path.moveTo(outline[0][0], outline[0][1])
      for (let i = 1; i < outline.length - 1; i++) {
        const x0 = outline[i - 1][0], y0 = outline[i - 1][1]
        const x1 = outline[i][0], y1 = outline[i][1]
        const x2 = outline[i + 1][0], y2 = outline[i + 1][1]
        path.quadraticCurveTo(x1, y1, (x1 + x2) / 2, (y1 + y2) / 2)
      }
      path.closePath()
      ctx.globalAlpha = strokeAlpha(stroke as StrokeV3)
      ctx.fillStyle = stroke.color
      ctx.fill(path)
      ctx.globalAlpha = 1
    }

    // 移交位图所有权（transfer 后 canvas 不可再用）
    const bitmap = canvas.transferToImageBitmap()
    workerPost(
      { kind: 'inkBitmap', reqId, pageIndex, revision, bitmap },
      [bitmap],
    )
  } catch (e) {
    fail(e)
  }
}

/* ---------------- 入口 ---------------- */

self.onmessage = (event: MessageEvent) => {
  const msg = event.data as WorkerInMessage
  if (!msg || typeof msg !== 'object') return
  try {
    if (msg.kind === 'ping') {
      workerPost({ kind: 'pong' })
      return
    }
    if (msg.kind === 'rebuildInk') {
      handleRebuildInk(msg)
      return
    }
    // 未知 kind 静默忽略（保持协议可扩展）
  } catch (e) {
    // rebuildInk 内部已有 try/catch，这里是双保险
    const m = msg as Partial<RebuildInkRequest>
    workerPost({
      kind: 'inkError',
      reqId: m.reqId ?? -1,
      pageIndex: m.pageIndex ?? -1,
      revision: m.revision ?? -1,
      error: errorMessage(e),
    })
  }
}
