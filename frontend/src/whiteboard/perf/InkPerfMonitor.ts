/**
 * whiteboard/perf/InkPerfMonitor.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——仅开发态性能监视（文档 §8）。
 *
 * 是否启用由构造参数决定（组件按 import.meta.env.DEV 传入）；
 * enabled=false 时全部方法 no-op，不挂定时器、不建 observer。
 *
 * 隐私边界（文档 §8）：**严禁记录坐标值、文字内容、图片数据**。
 * 本类只持有时间戳 / 耗时 / 面积 / 计数等聚合量，且只经 console.debug
 * 前缀 '[wb-perf]' 输出统计值（不发送到服务端）。
 */

import { InkFrameMetric, backingBytes } from '../types'

/** 简单分位数：0-based index = floor(p*(n-1))；调用方保证数组非空。 */
function percentile(arr: number[], p: number): number {
  const a = arr.slice().sort((x, y) => x - y)
  return a[Math.floor(p * (a.length - 1))]
}

/** 毫秒数 → "2.3ms"。 */
function ms(v: number): string {
  return v.toFixed(1) + 'ms'
}

const INPUT_RING_CAP = 512
const SLOW_FRAME_MS = 12
const SUMMARY_INTERVAL_MS = 5000

interface RebuildSample {
  kind: 'static' | 'ink'
  pageIndex: number
  ms: number
}

export class InkPerfMonitor {
  private readonly enabled: boolean
  // 输入事件时间戳（环形缓冲，容量 512；入环顺序即时间顺序）
  private inputRing: number[] = []
  private inputHead = 0
  private inputCount = 0
  // 当前窗口样本
  private latencies: number[] = []
  private frameDurations: number[] = []
  private strokeMsList: number[] = []
  private slowFrames = 0
  private longTaskCount = 0
  private rebuilds: RebuildSample[] = []
  private backingBytes = 0
  private timer: number | null = null
  private longTaskObs: PerformanceObserver | null = null

  constructor(enabled: boolean) {
    this.enabled = enabled
    if (!enabled) return
    // Long Task 计数：整体 try/catch 守卫；不支持（entryTypes 无 longtask 的旧浏览器）→ 记 0
    try {
      this.longTaskObs = new PerformanceObserver((list) => {
        this.longTaskCount += list.getEntries().length
      })
      this.longTaskObs.observe({ entryTypes: ['longtask'] })
    } catch {
      this.longTaskObs = null
    }
    // 每 5s 自动汇总一次（输出并重置窗口样本）
    this.timer = setInterval(() => this.summary(), SUMMARY_INTERVAL_MS)
  }

  /** 记录一个输入事件时间戳（pointer 事件 / 采样到达时调用）。 */
  noteInput(ts: number) {
    if (!this.enabled) return
    this.inputRing[this.inputHead] = ts
    this.inputHead = (this.inputHead + 1) % INPUT_RING_CAP
    if (this.inputCount < INPUT_RING_CAP) this.inputCount += 1
  }

  /** 环形缓冲中最近一个 ≤ ts 的输入时间戳（从最新向旧遍历，第一个命中即止）。 */
  private lastInputAtOrBefore(ts: number): number | null {
    if (!this.inputCount) return null
    for (let i = 0; i < this.inputCount; i++) {
      const idx = (this.inputHead - 1 - i + INPUT_RING_CAP * 2) % INPUT_RING_CAP
      const v = this.inputRing[idx]
      if (v <= ts) return v
    }
    return null
  }

  /** 累计一帧湿墨指标：
   *  - 成对计算输入→renderStart 延迟（取缓冲中最近一个 ≤ renderStart 的输入时间戳）
   *  - 帧总耗时 / strokeMs
   *  - 丢帧（renderEnd - renderStart > 12ms 计数） */
  noteFrame(m: InkFrameMetric) {
    if (!this.enabled) return
    const inputTs = this.lastInputAtOrBefore(m.renderStart)
    if (inputTs !== null) this.latencies.push(m.renderStart - inputTs)
    const dur = m.renderEnd - m.renderStart
    this.frameDurations.push(dur)
    if (dur > SLOW_FRAME_MS) this.slowFrames += 1
    if (m.strokeMs !== undefined) this.strokeMsList.push(m.strokeMs)
  }

  /** 层重建耗时（撤销/重做/擦除/尺寸变化触发的 static/ink 全量重建）。 */
  noteLayerRebuild(kind: 'static' | 'ink', pageIndex: number, ms: number) {
    if (!this.enabled) return
    this.rebuilds.push({ kind, pageIndex, ms })
  }

  /** backing 内存估算：Σ w*h*dpr²*4（w/h 为 CSS 像素）。覆盖式记录当前总字节数。 */
  noteBackings(list: { pageIndex: number; cssW: number; cssH: number; dpr: number }[]) {
    if (!this.enabled) return
    let total = 0
    for (const b of list) total += backingBytes(b.cssW, b.cssH, b.dpr)
    this.backingBytes = total
  }

  /** 汇总输出（'[wb-perf]' 前缀）：
   *  输入→渲染延迟 / 帧总耗时 / strokeMs 的 P50/P95/P99，
   *  longtask 数、>12ms 帧数、层重建、backing 总字节；
   *  无样本时不输出。输出后重置窗口样本。 */
  summary() {
    if (!this.enabled) return
    if (!this.frameDurations.length && !this.latencies.length
      && !this.rebuilds.length && !this.backingBytes) return
    const parts: string[] = []
    if (this.frameDurations.length) {
      const f = this.frameDurations
      parts.push(
        `frame n=${f.length} P50=${ms(percentile(f, 0.5))} P95=${ms(percentile(f, 0.95))} P99=${ms(percentile(f, 0.99))} slow>${SLOW_FRAME_MS}ms=${this.slowFrames}`,
      )
    }
    if (this.latencies.length) {
      const l = this.latencies
      parts.push(
        `input→render n=${l.length} P50=${ms(percentile(l, 0.5))} P95=${ms(percentile(l, 0.95))} P99=${ms(percentile(l, 0.99))}`,
      )
    }
    if (this.strokeMsList.length) {
      const s = this.strokeMsList
      parts.push(`stroke P50=${ms(percentile(s, 0.5))} P95=${ms(percentile(s, 0.95))} P99=${ms(percentile(s, 0.99))}`)
    }
    if (this.rebuilds.length) {
      let inkN = 0
      let inkMax = 0
      let staticN = 0
      let staticMax = 0
      for (const r of this.rebuilds) {
        if (r.kind === 'ink') { inkN += 1; inkMax = Math.max(inkMax, r.ms) }
        else { staticN += 1; staticMax = Math.max(staticMax, r.ms) }
      }
      parts.push(`rebuild ink=${inkN} max=${ms(inkMax)} static=${staticN} max=${ms(staticMax)}`)
    }
    parts.push(`longtask=${this.longTaskCount} backing=${(this.backingBytes / (1024 * 1024)).toFixed(1)}MB`)
    console.debug('[wb-perf]', parts.join(' | '))
    this.resetWindow()
  }

  /** 重置当前窗口样本（自动汇总输出后调用）。 */
  private resetWindow() {
    this.inputRing.length = 0
    this.inputHead = 0
    this.inputCount = 0
    this.latencies = []
    this.frameDurations = []
    this.strokeMsList = []
    this.slowFrames = 0
    this.longTaskCount = 0
    this.rebuilds = []
    this.backingBytes = 0
  }

  /** 清理定时器与 PerformanceObserver（组件卸载时调用）。 */
  dispose() {
    if (this.timer !== null) {
      clearInterval(this.timer)
      this.timer = null
    }
    if (this.longTaskObs) {
      try { this.longTaskObs.disconnect() } catch { /* ignore */ }
      this.longTaskObs = null
    }
  }
}
