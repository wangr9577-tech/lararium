/**
 * whiteboard/renderer/LiveInkRenderer.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——湿墨层（liveCanvas）渲染器（文档 §5.3）。
 *
 * 策略：每帧最多一次 perfect-freehand + 脏区清理
 *  1. 新采样只追加进内部点数组（页面固有坐标），绝不触碰历史内容。
 *  2. flushFrame() 每帧至多对全部当前点跑一次 getStroke（last=true，与组件
 *     活动笔迹 drawOne(liveStroke, true) 一致）。
 *  3. 脏区 = 上一帧笔迹包围盒 ∪ 当前笔迹包围盒（页面固有 → CSS 像素），
 *     外扩最大笔宽（CSS 值）+ 2px 抗锯齿余量，再与可见区求交；只 clearRect 该区域。
 *  4. 整笔重画当前笔迹（globalAlpha / fillStyle 由笔迹参数决定）。
 *
 * liveCanvas backing = cssW*dpr × cssH*dpr；begin() 之后 ctx 的 transform 把
 * 页面固有坐标映射到设备像素，CSS 缩放 / DPR 变化不改变页面固有几何，
 * 与路径缓存保持一致（文档 §5.2）。cssW/cssH/dpr 变化时组件需重新 begin()
 * （重建 canvas backing 并重新 setTransform）。
 *
 * 极长单笔（>1500 点）暂不启用「冻结已稳定前缀、只重算最后 48～96 点」的
 * 尾段算法——第一阶段只记录指标（文档 §5.3）；若单笔超 1500 点后 P95 超标
 * 再实现尾段冻结。
 */

import { getStroke } from 'perfect-freehand'
import { Tool, TipKey, PageData, Bounds, InkFrameMetric, StrokeV3, strokeAlpha } from '../types'
import { pageStrokeWidth, unionBounds, growBounds, toCssBounds, intersectCss } from '../geometry'
import { strokeOptsPage } from './StrokePathCache'

/** 当前笔迹参数（不需要 id/pts：id/pts 由组件与 StrokeBuffer 负责）。 */
export type LiveStroke = Omit<StrokeV3, 'id' | 'pts'>

/** 最大笔宽（CSS 值）：base = pageStrokeWidth 换算到 CSS，再按 strokeOptsPage
 *  各分支的 size 系数放大（hl ×3.2 / marker ×2.4 / 其余 ×1）。
 *  用于脏区外扩，保证 clearRect 覆盖上一帧可能画到的最宽边缘。 */
function liveMaxWidthCss(stroke: LiveStroke, pg: PageData, cssW: number): number {
  // pageStrokeWidth 只读 stroke.w，这里按 StrokeV3 结构传入
  const base = (pageStrokeWidth(stroke as StrokeV3, pg) * cssW) / pg.page.w
  if (stroke.tool === 'hl') return base * 3.2
  const tip = stroke.tip || 'pen'
  if (tip === 'marker') return base * 2.4
  return base
}

export class LiveInkRenderer {
  private stroke: LiveStroke | null = null
  private pg: PageData | null = null
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null
  private cssW = 0
  private cssH = 0
  private dpr = 1
  private points: [number, number, number][] = []
  private curBounds: Bounds = { x: 0, y: 0, w: 0, h: 0 }
  private hasCurBounds = false
  private prevFrameCss: Bounds | null = null
  private dirty = false

  /** 开始一笔：取 ctx，设「页面固有 → 设备像素」transform，清空画布，保存引用。
   *  会重建 canvas backing（cssW*dpr × cssH*dpr）；cssW/cssH/dpr 变化时
   *  组件需再次调用本方法。 */
  begin(stroke: LiveStroke, pg: PageData, canvas: HTMLCanvasElement, cssW: number, cssH: number, dpr: number) {
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    this.stroke = { ...stroke }
    this.pg = pg
    this.canvas = canvas
    this.ctx = ctx
    this.cssW = cssW
    this.cssH = cssH
    this.dpr = dpr
    canvas.width = Math.max(1, Math.round(cssW * dpr))
    canvas.height = Math.max(1, Math.round(cssH * dpr))
    // 此后以页面固有坐标绘制
    ctx.setTransform(dpr * cssW / pg.page.w, 0, 0, dpr * cssH / pg.page.h, 0, 0)
    ctx.clearRect(0, 0, pg.page.w, pg.page.h)
    this.points = []
    this.hasCurBounds = false
    this.curBounds = { x: 0, y: 0, w: 0, h: 0 }
    this.prevFrameCss = null
    this.dirty = false
  }

  /** 追加采样（归一化 0..1）：转页面固有坐标存入内部点数组；标脏；
   *  增量更新当前笔迹包围盒（页面固有坐标）。 */
  push(nx: number, ny: number, p: number) {
    if (!this.ctx || !this.pg) return
    const x = nx * this.pg.page.w
    const y = ny * this.pg.page.h
    this.points.push([x, y, p])
    this.dirty = true
    if (!this.hasCurBounds) {
      this.curBounds = { x, y, w: 0, h: 0 }
      this.hasCurBounds = true
    } else {
      const b = this.curBounds
      const x2 = Math.max(b.x + b.w, x)
      const y2 = Math.max(b.y + b.h, y)
      b.x = Math.min(b.x, x)
      b.y = Math.min(b.y, y)
      b.w = x2 - b.x
      b.h = y2 - b.y
    }
  }

  /** 一帧湿墨渲染：未标脏返回 null。否则：
   *  renderStart 起表 → 本帧至多一次 getStroke（last=true）→ 中点法重建
   *  Path2D → clearRect 脏区 → globalAlpha=strokeAlpha、fillStyle=color 整笔重填
   *  → 记录 prevFrameCss → 返回 InkFrameMetric。
   *  historicalStrokeCount：该页已提交笔迹数（仅记录进指标，不参与渲染）。 */
  flushFrame(historicalStrokeCount: number, lastInputTs?: number): InkFrameMetric | null {
    if (!this.dirty || !this.ctx || !this.pg || !this.stroke || !this.points.length) return null
    const renderStart = performance.now()
    const ctx = this.ctx
    const pg = this.pg
    const stroke = this.stroke

    const t0 = performance.now()
    const outline = getStroke(this.points, strokeOptsPage(stroke, true, pg.page.w))
    const strokeMs = performance.now() - t0

    const curCss = toCssBounds(this.curBounds, pg, this.cssW, this.cssH)
    const combined = this.prevFrameCss ? unionBounds(this.prevFrameCss, curCss) : curCss
    const dirtyRect = intersectCss(
      growBounds(combined, liveMaxWidthCss(stroke, pg, this.cssW) + 2),
      this.cssW,
      this.cssH,
    )
    ctx.clearRect(dirtyRect.x, dirtyRect.y, dirtyRect.w, dirtyRect.h)

    // strokeAlpha 只读 tool/tip，这里按 StrokeV3 结构传入
    ctx.globalAlpha = strokeAlpha(stroke as StrokeV3)
    ctx.fillStyle = stroke.color
    if (outline.length) {
      // Path2D 构建算法与 buildStrokePath / 组件 drawOne 923-931 行一致
      const path = new Path2D()
      path.moveTo(outline[0][0], outline[0][1])
      for (let i = 1; i < outline.length - 1; i++) {
        const x0 = outline[i - 1][0], y0 = outline[i - 1][1]
        const x1 = outline[i][0], y1 = outline[i][1]
        const x2 = outline[i + 1][0], y2 = outline[i + 1][1]
        path.quadraticCurveTo(x1, y1, (x1 + x2) / 2, (y1 + y2) / 2)
      }
      path.closePath()
      ctx.fill(path)
    }
    ctx.globalAlpha = 1

    this.prevFrameCss = curCss
    this.dirty = false
    return {
      eventTs: lastInputTs ?? renderStart,
      renderStart,
      renderEnd: performance.now(),
      pointCount: this.points.length,
      historicalStrokeCount,
      dirtyArea: dirtyRect.w * dirtyRect.h,
      strokeMs,
    }
  }

  /** 释放引用（points / ctx / canvas 置空）。落笔提交或页面失活后调用。 */
  end() {
    this.points = []
    this.stroke = null
    this.pg = null
    this.canvas = null
    this.ctx = null
    this.hasCurBounds = false
    this.prevFrameCss = null
    this.dirty = false
  }

  /** 全清 live 画布（提交笔迹后调用：该笔改由 ink 层承接展示）。 */
  clearAll() {
    if (!this.ctx || !this.pg) return
    this.ctx.clearRect(0, 0, this.pg.page.w, this.pg.page.h)
    this.prevFrameCss = null
    this.dirty = false
  }
}

/** 橡皮悬停指示：红色圆圈（CSS 像素空间，与组件 1204-1208 行一致）。
 *  例外：自己从 canvas 取 ctx 并 setTransform(dpr,0,0,dpr,0,0)。 */
export function drawEraserRing(canvas: HTMLCanvasElement, dpr: number, x: number, y: number, r: number) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.strokeStyle = 'rgba(220,38,38,.55)'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.stroke()
}

/** 图片选择框（CSS 像素空间，移植组件 drawImgBox 977-999 行；像素坐标 = x*cssW 等）：
 *  选中 = 紫色虚线框 + 4 角白色手柄；未选中 = 细边框。
 *  注意：调用方须先对 ctx 做好 dpr 变换（本函数内部不 setTransform）。 */
export function drawImgBox(
  ctx: CanvasRenderingContext2D,
  img: { x: number; y: number; w: number; r: number },
  cssW: number,
  cssH: number,
  sel: boolean,
) {
  const px = img.x * cssW
  const py = img.y * cssH
  const pw = img.w * cssW
  const ph = pw * img.r
  if (sel) {
    ctx.save()
    ctx.strokeStyle = '#8b5cf6'
    ctx.lineWidth = 1.5
    ctx.setLineDash([5, 4])
    ctx.strokeRect(px - 2, py - 2, pw + 4, ph + 4)
    ctx.setLineDash([])
    const hs = 6
    for (const [hx, hy] of [[px, py], [px + pw, py], [px, py + ph], [px + pw, py + ph]]) {
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(hx - hs, hy - hs, hs * 2, hs * 2)
      ctx.strokeStyle = '#8b5cf6'
      ctx.strokeRect(hx - hs, hy - hs, hs * 2, hs * 2)
    }
    ctx.restore()
  } else {
    ctx.strokeStyle = 'rgba(139,92,246,.5)'
    ctx.lineWidth = 1
    ctx.strokeRect(px, py, pw, ph)
  }
}
