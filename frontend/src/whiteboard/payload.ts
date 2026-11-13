/**
 * whiteboard/payload.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——v1/v2/v3 解析、迁移与序列化。
 *
 * 兼容性说明（文档 §4.3 / §12）：
 *  - v3 相对 v2 只新增「可选」字段：顶层 v:3、stroke.id、采样点 t/tilt、stroke.rev。
 *    旧前端读 v3 时会走下面的 v2 分支（对象有 pages 数组），并忽略新字段，
 *    因此双向兼容；后端 notes.py 只校验 pages 为数组，无需修改即可接受 v3。
 *  - parsePayload 必须保留 v1/v2 分支，读取时补默认值。
 */

import {
  PageData,
  StrokeV3,
  InkSampleV3,
  PaperMeta,
  PaperStyle,
  PaperColor,
  Tool,
  TipKey,
  PAPER_STYLES,
  PAPER_COLORS,
  newStrokeId,
} from './types'

/** 合法工具集 / 笔尖集（用于字段净化时的取值校验）。 */
const TOOL_SET: Tool[] = ['pen', 'hl', 'eraser', 'select']
const TIP_SET: TipKey[] = ['ball', 'pen', 'marker']

/** 从任意来源提取合法纸张元信息，非法/缺失回落 plain/white。 */
function paperFrom(src: any): PaperMeta {
  const style = (src && src.style) as PaperStyle
  const color = (src && src.color) as PaperColor
  return {
    style: PAPER_STYLES.some((x) => x.key === style) ? style : 'plain',
    color: PAPER_COLORS.some((x) => x.key === color) ? color : 'white',
  }
}

/** 净化单条笔迹：
 *  - tool 非法 → 'pen'
 *  - color 非 string → '#1f2937'
 *  - w 非 number 或 ≤0 → 0.0026
 *  - tip 非法 → 删除
 *  - pts 过滤掉 x/y/p 任一为非有限数字的采样，p 夹到 0..1
 *  - t/tilt(tx/ty/tw) 为可选，仅在有合法有限值时保留
 *  - sp(boolean)、bv(已支持的笔刷版本)、rev(有限 number) 为合法时原样保留
 *  假定入参经 ensureStrokeIds 处理过（id 已存在、对象非空）。 */
function sanitizeStroke(s: StrokeV3): StrokeV3 {
  const tool: Tool = TOOL_SET.includes(s.tool) ? s.tool : 'pen'
  const color = typeof s.color === 'string' ? s.color : '#1f2937'
  const w = typeof s.w === 'number' && Number.isFinite(s.w) && s.w > 0 ? s.w : 0.0026

  let tip: TipKey | undefined
  if (TIP_SET.includes(s.tip as TipKey)) tip = s.tip

  const pts: InkSampleV3[] = []
  if (Array.isArray(s.pts)) {
    for (const raw of s.pts) {
      if (!raw) continue
      const x = raw.x
      const y = raw.y
      const p = raw.p
      if (typeof x !== 'number' || !Number.isFinite(x)) continue
      if (typeof y !== 'number' || !Number.isFinite(y)) continue
      if (typeof p !== 'number' || !Number.isFinite(p)) continue
      const sample: InkSampleV3 = { x, y, p: Math.min(1, Math.max(0, p)) }
      if (typeof raw.t === 'number' && Number.isFinite(raw.t)) sample.t = raw.t
      if (typeof raw.tx === 'number' && Number.isFinite(raw.tx)) sample.tx = raw.tx
      if (typeof raw.ty === 'number' && Number.isFinite(raw.ty)) sample.ty = raw.ty
      if (typeof raw.tw === 'number' && Number.isFinite(raw.tw)) sample.tw = raw.tw
      pts.push(sample)
    }
  }

  const out: StrokeV3 = { id: s.id, tool, color, w, pts }
  if (tip !== undefined) out.tip = tip
  if (typeof s.sp === 'boolean') out.sp = s.sp
  if (s.bv === 1) out.bv = 1
  if (typeof s.sensitivity === 'number' && Number.isFinite(s.sensitivity)) out.sensitivity = Math.max(0, Math.min(1, s.sensitivity))
  if (typeof s.opacity === 'number' && Number.isFinite(s.opacity)) out.opacity = Math.max(0.1, Math.min(1, s.opacity))
  if (typeof s.rev === 'number' && Number.isFinite(s.rev)) out.rev = s.rev
  return out
}

/** 缺 id 的笔迹按顺序补 newStrokeId()；已有 id 的原样保留（稳定）。
 *  对空/非对象条目补一条合法空笔迹，保证输出始终是可用的 StrokeV3 数组。 */
export function ensureStrokeIds(strokes: StrokeV3[]): StrokeV3[] {
  if (!Array.isArray(strokes)) return []
  return strokes.map((s) => {
    if (!s || typeof s !== 'object') {
      return { id: newStrokeId(), tool: 'pen' as Tool, color: '#1f2937', w: 0.0026, pts: [] }
    }
    return s.id && typeof s.id === 'string' ? s : { ...s, id: newStrokeId() }
  })
}

/** 整页净化：补 ID → 逐条净化笔迹；paper 已在调用方按来源校验。 */
function sanitizePage(pg: PageData): PageData {
  const strokes = ensureStrokeIds(pg.strokes).map((s) => sanitizeStroke(s))
  return { page: pg.page, strokes, images: pg.images }
}

/** 解析白板 payload（v1 单页 / v2 多页 / v3 多页）。
 *  - v2/v3：对象有 pages 数组 → 过滤 page.w>0 && page.h>0 的页。
 *  - v1：对象有 strokes 数组且 page.w>0 && page.h>0 → 单页。
 *  - 非法/空 → null。
 *  所有分支最后都补 stroke ID 并逐条净化字段。 */
export function parsePayload(raw: string): PageData[] | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw)
    if (o && typeof o === 'object') {
      // v2 / v3：多页
      if (Array.isArray(o.pages)) {
        const list = (o.pages as any[]).filter((p) => p && p.page && p.page.w > 0 && p.page.h > 0)
        if (list.length) {
          return list.map((p) =>
            sanitizePage({
              page: { w: p.page.w, h: p.page.h, paper: paperFrom(p.page.paper) },
              strokes: Array.isArray(p.strokes) ? p.strokes : [],
              images: Array.isArray(p.images) ? p.images : [],
            })
          )
        }
      }
      // v1：单页兼容
      if (Array.isArray(o.strokes) && o.page && o.page.w > 0 && o.page.h > 0) {
        return [
          sanitizePage({
            page: { w: o.page.w, h: o.page.h, paper: paperFrom(o.page.paper) },
            strokes: o.strokes,
            images: Array.isArray(o.images) ? o.images : [],
          }),
        ]
      }
    }
  } catch { /* ignore */ }
  return null
}

/** 序列化为 v3：{ v: 3, pages }。 */
export function serialize(pages: PageData[]): string {
  return JSON.stringify({ v: 3, pages })
}

/** 笔迹内容签名（供路径缓存判失效，见文档 §5.2）：
 *  [tool,color,w,tip,sp,pts.length, 首点x/y/p, 末点x/y/p, rev ?? 0] join('|')。
 *  空笔迹返回 'empty'。
 *  点集或笔刷参数任一变化都会改变签名，使旧 Path2D 缓存失效。 */
export function strokeSignature(stroke: StrokeV3): string {
  const pts = Array.isArray(stroke.pts) ? stroke.pts : []
  if (!pts.length) return 'empty'
  const first = pts[0]
  const last = pts[pts.length - 1]
  return [
    stroke.tool,
    stroke.color,
    stroke.w,
    stroke.tip,
    stroke.sp,
    stroke.bv,
    stroke.sensitivity,
    pts.length,
    first.x,
    first.y,
    first.p,
    last.x,
    last.y,
    last.p,
    stroke.rev ?? 0,
  ].join('|')
}
