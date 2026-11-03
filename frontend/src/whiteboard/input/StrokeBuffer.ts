/**
 * whiteboard/input/StrokeBuffer.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——非响应式当前笔迹缓冲（文档 §2.5 / §5.3）。
 *
 * 替代组件热路径（pointermove）里把当前笔迹采样写进 Vue ref 的旧做法：
 * 纯 TS 类，不 import Vue，采样追加没有响应式代理开销。
 * 坐标为归一化页面坐标 0..1；t 为相对该笔起点的毫秒数（t0 = performance.now()）。
 */

import { InkSampleV3, Bounds } from '../types'

export class StrokeBuffer {
  private pts: InkSampleV3[] = []
  private t0 = 0
  private minX = Infinity
  private minY = Infinity
  private maxX = -Infinity
  private maxY = -Infinity

  /** 记录首采样（归一化 0..1）并起表 t0 = performance.now()。
   *  先 reset() 防御性清空，重复 begin 不会残留上一笔状态。 */
  begin(nx: number, ny: number, p: number) {
    this.reset()
    this.t0 = performance.now()
    this.pts.push({ x: nx, y: ny, p, t: 0 })
    this.minX = this.maxX = nx
    this.minY = this.maxY = ny
  }

  /** 追加采样；t = performance.now() - t0；倾斜角（tx/ty/tw）可选写入。
   *  增量维护 min/max 包围（归一化坐标）。 */
  push(nx: number, ny: number, p: number, tilt?: { tx?: number; ty?: number; tw?: number }) {
    const s: InkSampleV3 = { x: nx, y: ny, p, t: performance.now() - this.t0 }
    if (tilt) {
      if (typeof tilt.tx === 'number') s.tx = tilt.tx
      if (typeof tilt.ty === 'number') s.ty = tilt.ty
      if (typeof tilt.tw === 'number') s.tw = tilt.tw
    }
    this.pts.push(s)
    if (nx < this.minX) this.minX = nx
    if (nx > this.maxX) this.maxX = nx
    if (ny < this.minY) this.minY = ny
    if (ny > this.maxY) this.maxY = ny
  }

  /** 当前采样数。 */
  get length(): number {
    return this.pts.length
  }

  /** 末采样（空则 null）。 */
  last(): InkSampleV3 | null {
    return this.pts.length ? this.pts[this.pts.length - 1] : null
  }

  /** 返回 pts 的浅拷贝（提交笔迹 / 构建 StrokeV3 时用，外部可安全修改）。 */
  toSamples(): InkSampleV3[] {
    return this.pts.slice()
  }

  /** 采样 min/max 包围盒（归一化坐标，不外扩）；空缓冲返回零盒。 */
  boundsNormalized(): Bounds {
    if (!this.pts.length) return { x: 0, y: 0, w: 0, h: 0 }
    return { x: this.minX, y: this.minY, w: this.maxX - this.minX, h: this.maxY - this.minY }
  }

  /** 清空。 */
  reset() {
    this.pts = []
    this.t0 = 0
    this.minX = Infinity
    this.minY = Infinity
    this.maxX = -Infinity
    this.maxY = -Infinity
  }
}
