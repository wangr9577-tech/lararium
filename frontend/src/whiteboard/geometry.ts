/**
 * whiteboard/geometry.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——页面固有坐标换算与脏矩形计算。
 *
 * 关键约定（文档 §4.2）：路径缓存使用「页面固有坐标」（pageX = nx * page.w），
 * 而不是 CSS 像素。CSS 缩放与 DPR 变化都不改变页面固有坐标，因此矢量路径缓存
 * 跨缩放/跨 DPR 有效；只有页面固有宽高变化才需要重建路径。
 */

import { PageData, StrokeV3, Bounds } from './types'

/** 归一化页面坐标 (0..1) → 页面固有坐标。 */
export function pagePoint(nx: number, ny: number, pg: PageData): { x: number; y: number } {
  return { x: nx * pg.page.w, y: ny * pg.page.h }
}

/** 笔迹在页面固有坐标下的笔宽 = stroke.w * page.w。 */
export function pageStrokeWidth(stroke: StrokeV3, pg: PageData): number {
  return stroke.w * pg.page.w
}

/** 笔迹在页面固有坐标下的包围盒：
 *  扫描所有采样点取 min/max，四边各外扩 (pageStrokeWidth/2 + page.w * 0.002)
 *  （抗锯齿余量），再夹到 [0,page.w]×[0,page.h]。
 *  空笔迹返回 {x:0,y:0,w:0,h:0}。 */
export function strokeBoundsInPage(stroke: StrokeV3, pg: PageData): Bounds {
  const pts = Array.isArray(stroke.pts) ? stroke.pts : []
  if (!pts.length) return { x: 0, y: 0, w: 0, h: 0 }
  const pw = pg.page.w
  const ph = pg.page.h
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of pts) {
    const x = p.x * pw
    const y = p.y * ph
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  const pad = pageStrokeWidth(stroke, pg) / 2 + pw * 0.002
  minX -= pad
  minY -= pad
  maxX += pad
  maxY += pad
  // 夹到页面范围
  minX = Math.max(0, Math.min(minX, pw))
  minY = Math.max(0, Math.min(minY, ph))
  maxX = Math.max(0, Math.min(maxX, pw))
  maxY = Math.max(0, Math.min(maxY, ph))
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

/** 两个包围盒的并集。 */
export function unionBounds(a: Bounds, b: Bounds): Bounds {
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const x2 = Math.max(a.x + a.w, b.x + b.w)
  const y2 = Math.max(a.y + a.h, b.y + b.h)
  return { x, y, w: x2 - x, h: y2 - y }
}

/** 包围盒四边各外扩 m（m 可为负以收缩）。 */
export function growBounds(b: Bounds, m: number): Bounds {
  return { x: b.x - m, y: b.y - m, w: b.w + 2 * m, h: b.h + 2 * m }
}

/** 页面固有坐标包围盒 → CSS 像素包围盒。 */
export function toCssBounds(b: Bounds, pg: PageData, cssW: number, cssH: number): Bounds {
  const pw = pg.page.w
  const ph = pg.page.h
  return {
    x: (b.x * cssW) / pw,
    y: (b.y * cssH) / ph,
    w: (b.w * cssW) / pw,
    h: (b.h * cssH) / ph,
  }
}

/** 与画布可见区 [0,cssW]×[0,cssH] 求交；无交集返回 {x:0,y:0,w:0,h:0}。 */
export function intersectCss(b: Bounds, cssW: number, cssH: number): Bounds {
  const x0 = Math.max(0, b.x)
  const y0 = Math.max(0, b.y)
  const x1 = Math.min(cssW, b.x + b.w)
  const y1 = Math.min(cssH, b.y + b.h)
  if (x1 <= x0 || y1 <= y0) return { x: 0, y: 0, w: 0, h: 0 }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

/** 湿墨层清区用脏矩形：
 *  strokeBoundsInPage → toCssBounds → intersectCss（含抗锯齿余量，含在可见区内）。 */
export function dirtyRectForStroke(stroke: StrokeV3, pg: PageData, cssW: number, cssH: number): Bounds {
  return intersectCss(toCssBounds(strokeBoundsInPage(stroke, pg), pg, cssW, cssH), cssW, cssH)
}
