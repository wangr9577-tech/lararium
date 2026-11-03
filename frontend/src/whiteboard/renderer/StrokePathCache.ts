/**
 * whiteboard/renderer/StrokePathCache.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——已提交笔迹的 perfect-freehand 轮廓缓存。
 *
 * 坐标空间（文档 §4.2）：本缓存内所有 Path2D 均在「页面固有坐标」下构建：
 *   pageX = nx * page.w，pageY = ny * page.h，size = stroke.w * page.w。
 * 渲染时由 canvas transform 映射到当前 CSS 尺寸，因此普通缩放无需重新跑
 * perfect-freehand，只需重建位图层或改变展示 transform。
 *
 * 失效规则（文档 §5.2）：
 *  - 笔迹内容/参数变化（strokeSignature 变化）→ 失效
 *  - 页面固有宽高（page.w / page.h）变化 → 失效
 *  - CSS 缩放与 DPR 变化 **不得** 使缓存失效（它们只是 canvas 的展示变换，
 *    不改变页面固有几何）。
 */

import { getStroke, StrokeOptions } from 'perfect-freehand'
import { StrokeV3, PageData, CachedStrokePath } from '../types'
import { strokeSignature } from '../payload'
import { strokeBoundsInPage } from '../geometry'

/** 选项生成所依赖的笔刷参数子集（StrokeV3 结构子类型：完整 StrokeV3
 *  与湿墨层的 LiveStroke 都可传入）。 */
export type BrushParams = Pick<StrokeV3, 'tool' | 'w' | 'tip' | 'sp'>

/**
 * 页面固有坐标下的 perfect-freehand 选项（从组件 strokeOpts 898-915 行移植，
 * size 基准从 `stroke.w * cssW` 换成 `stroke.w * pageW`，其余参数逐字保留）。
 *
 * 纯函数：无 DOM 依赖，worker（render.worker.ts）也会 import 它。
 */
export function strokeOptsPage(stroke: BrushParams, last: boolean, pageW: number): StrokeOptions {
  const size = Math.max(1, stroke.w * pageW)
  if (stroke.tool === 'hl') {
    return { size: size * 3.2, thinning: 0, smoothing: 0.55, streamline: 0.45,
      simulatePressure: true, last, start: { cap: true }, end: { cap: true } }
  }
  const tip = stroke.tip || 'pen'
  if (tip === 'ball') {
    return { size, thinning: 0.12, smoothing: 0.5, streamline: 0.42,
      simulatePressure: true, last }
  }
  if (tip === 'marker') {
    return { size: size * 2.4, thinning: 0, smoothing: 0.5, streamline: 0.5,
      simulatePressure: true, last, start: { cap: true }, end: { cap: true } }
  }
  return { size, thinning: 0.55, smoothing: 0.5, streamline: 0.5,
    simulatePressure: stroke.sp === true, last, end: { taper: 0.4 } }
}

/**
 * 在页面固有坐标下构建一条笔迹的 Path2D（从组件 drawOne 917-936 行移植）：
 *  - points = stroke.pts.map(p => [p.x*page.w, p.y*page.h, p.p])
 *  - outline = getStroke(points, strokeOptsPage(stroke, last, page.w))
 *  - Path2D：首点 moveTo，其余 quadraticCurveTo 中点法，closePath
 *  - 空笔迹 / 空 outline 返回空 path
 */
export function buildStrokePath(stroke: StrokeV3, pg: PageData, last: boolean): { path: Path2D } {
  const path = new Path2D()
  const pts = Array.isArray(stroke.pts) ? stroke.pts : []
  if (!pts.length) return { path }
  const pageW = pg.page.w
  const pageH = pg.page.h
  const raw: [number, number, number][] = pts.map((p) => [p.x * pageW, p.y * pageH, p.p])
  const outline = getStroke(raw, strokeOptsPage(stroke, last, pageW))
  if (!outline.length) return { path }
  path.moveTo(outline[0][0], outline[0][1])
  for (let i = 1; i < outline.length - 1; i++) {
    const x0 = outline[i - 1][0], y0 = outline[i - 1][1]
    const x1 = outline[i][0], y1 = outline[i][1]
    const x2 = outline[i + 1][0], y2 = outline[i + 1][1]
    path.quadraticCurveTo(x1, y1, (x1 + x2) / 2, (y1 + y2) / 2)
  }
  path.closePath()
  return { path }
}

/** LRU 上限（文档 §5.2）。 */
const MAX_CACHE_ENTRIES = 2000

/**
 * 已提交笔迹的 Path2D 缓存（LRU，页面固有坐标）。
 *
 *  - 已提交笔迹一律以 last=false 构建（与组件历史笔迹渲染 drawOne(s, false)
 *    一致，保证湿→干视觉一致；湿墨 last=true 由 LiveInkRenderer 单独处理）。
 *  - 命中条件：entry.revision === strokeSignature(stroke) 且页面固有宽高一致；
 *    命中则刷新 LRU 位置并返回。
 *  - LRU 上限 2000 条：利用 Map 插入序，超限时淘汰最早插入的 key。
 */
export class StrokePathCache {
  private map = new Map<string, CachedStrokePath>()

  /** 获取或构建某笔迹的路径缓存条目（last=false）。 */
  getOrBuild(stroke: StrokeV3, pg: PageData): CachedStrokePath {
    const sig = strokeSignature(stroke)
    const existing = this.map.get(stroke.id)
    if (existing && existing.revision === sig
      && existing.pageWidth === pg.page.w && existing.pageHeight === pg.page.h) {
      // LRU 刷新：删除后重新插入（Map 保持插入序，最新访问位于尾部）
      this.map.delete(stroke.id)
      this.map.set(stroke.id, existing)
      return existing
    }
    const { path } = buildStrokePath(stroke, pg, false)
    const entry: CachedStrokePath = {
      strokeId: stroke.id,
      revision: sig,
      pageWidth: pg.page.w,
      pageHeight: pg.page.h,
      path,
      bounds: strokeBoundsInPage(stroke, pg),
    }
    this.map.set(stroke.id, entry)
    while (this.map.size > MAX_CACHE_ENTRIES) {
      const oldest = this.map.keys().next().value
      if (oldest === undefined) break
      this.map.delete(oldest)
    }
    return entry
  }

  /** 使某条笔迹的缓存失效（内容/参数变化、擦除切笔、撤销等）。 */
  invalidate(strokeId: string) {
    this.map.delete(strokeId)
  }

  /** 批量失效。 */
  invalidateMany(ids: string[]) {
    for (const id of ids) this.map.delete(id)
  }

  /** 清空全部（页面删除 / 换文档 / 页面固有尺寸变化时）。 */
  clear() {
    this.map.clear()
  }

  /** 当前缓存条目数。 */
  get size(): number {
    return this.map.size
  }
}
