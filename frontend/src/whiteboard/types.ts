/**
 * whiteboard/types.ts
 *
 * 白板第一阶段「分层渲染与性能基线」——数据与坐标层（纯新增模块）。
 *
 * 本文件搬运并扩展了 WhiteboardCanvas.vue 中原本内联的类型定义与常量
 * （类型区 179-209 行、常量区 204-254 行、widthFrac 1224-1226 行），
 * 并按 docs/WHITEBOARD_PHASE_1_RENDERING.md §4 引入 v3 数据模型。
 *
 * 风格约定：2 空格缩进、无分号、单引号、ES module、不引入新依赖。
 */

/* ---------------- 基础枚举 ---------------- */

export type Tool = 'pen' | 'hl' | 'eraser' | 'select'
export type TipKey = 'ball' | 'pen' | 'marker'
export type PaperStyle = 'plain' | 'grid' | 'ruled' | 'dots'
export type PaperColor = 'white' | 'cream' | 'parchment' | 'kraft'
export type EraserMode = 'part' | 'whole'
export type RatioKey = 'v' | 'h' | 'sq'

/* ---------------- v3 数据模型 ---------------- */

/** 单个压感采样点。
 *  x/y：归一化页面坐标 0..1
 *  p：  压力 0..1
 *  t：  相对该笔起点的毫秒数（可选）
 *  tx/ty/tw：tiltX / tiltY / twist（角度，可选） */
export interface InkSampleV3 {
  x: number
  y: number
  p: number
  t?: number
  tx?: number
  ty?: number
  tw?: number
}

/** v3 笔迹。
 *  id：  稳定唯一 ID（缓存键不依赖数组下标，见文档 §4.1）
 *  w：  笔宽（纸面宽比例）
 *  tip：笔尖样式
 *  sp：  是否模拟压感
 *  rev：  几何/参数修订号（可选，缓存失效判据之一） */
export interface StrokeV3 {
  id: string
  tool: Tool
  color: string
  w: number
  tip?: TipKey
  sp?: boolean
  pts: InkSampleV3[]
  rev?: number
}

/** 图片元素：x/y/w 为纸面宽比例；r = 像素高/宽（保持原始宽高比）。 */
export interface ImgEl {
  id: string
  x: number
  y: number
  w: number
  r: number
  src: string
}

/** 纸张元信息。 */
export interface PaperMeta {
  style: PaperStyle
  color: PaperColor
}

/** 一页白板数据（内存统一为 v3 类型）。 */
export interface PageData {
  page: { w: number; h: number; paper: PaperMeta }
  strokes: StrokeV3[]
  images: ImgEl[]
}

/* ---------------- 渲染 / 缓存 运行时类型 ---------------- */

/** 轴对齐包围盒（页面固有坐标或 CSS 像素，按使用处而定）。 */
export interface Bounds {
  x: number
  y: number
  w: number
  h: number
}

/** 路径缓存条目（见文档 §5.2）。
 *  revision 用内容签名串（payload.strokeSignature），而非自增号：
 *  点集/笔刷参数/几何任一变化都会改变签名，从而让旧路径失效。
 *  页面固有宽高参与缓存：页面固有坐标变化需重建路径。 */
export interface CachedStrokePath {
  strokeId: string
  revision: string
  pageWidth: number
  pageHeight: number
  path: Path2D
  bounds: Bounds
}

/** 每页渲染运行时（见文档 §5.1）。
 *  只有活动页持有 liveCanvas 的完整 backing store。 */
export interface PageRenderRuntime {
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

/** 单帧湿墨渲染指标（见文档 §8；开发态 InkPerfMonitor 使用）。 */
export interface InkFrameMetric {
  eventTs: number
  renderStart: number
  renderEnd: number
  pointCount: number
  historicalStrokeCount: number
  dirtyArea: number
  strokeMs?: number
}

/* ---------------- 常量（自组件搬运，值保持不变） ---------------- */

/** 页面比例。 */
export const RATIOS: Record<RatioKey, { label: string; w: number; h: number }> = {
  v: { label: '竖版', w: 1000, h: 1414 },
  h: { label: '横版', w: 1414, h: 1000 },
  sq: { label: '方形', w: 1200, h: 1200 },
}

/** 工具栏（组件 211-216 行）。 */
export const TOOLS: { key: Tool; label: string; tip: string }[] = [
  { key: 'pen', label: '钢笔', tip: '触控笔压感书写' },
  { key: 'hl', label: '荧光笔', tip: '半透明宽幅标记' },
  { key: 'eraser', label: '橡皮', tip: '局部擦除或整笔删除（仅笔迹）' },
  { key: 'select', label: '选择', tip: '移动 / 缩放 / 删除图片' },
]

/** 笔尖样式（组件 217-221 行）。 */
export const TIPS: { key: TipKey; label: string; tip: string }[] = [
  { key: 'ball', label: '圆珠', tip: '粗细均匀，适合速记' },
  { key: 'pen', label: '钢笔', tip: '压感笔锋，适合书写' },
  { key: 'marker', label: '马克', tip: '宽幅平头，适合标题' },
]

/** 颜色（组件 222-224 行）。 */
export const PEN_COLORS = ['#1f2937', '#475569', '#7c3aed', '#2563eb', '#0ea5e9', '#059669', '#dc2626', '#ea580c']
export const HL_COLORS = ['#fde047', '#a3e635', '#22d3ee', '#f472b6']
export const CUS_GRAD = ['#f87171', '#facc15', '#38bdf8']

/** 笔宽：细 / 中 / 粗（纸面宽比例，与组件 widthFrac 1224-1226 行一致）。 */
export const WIDTH_FRACTIONS = [0.0016, 0.0026, 0.0042]

/** 橡皮半径（像素，随粗细档）。 */
export const ERASER_R = [16, 26, 40]

/** 纸张样式（组件 231-236 行）。 */
export const PAPER_STYLES: { key: PaperStyle; label: string; tip: string }[] = [
  { key: 'plain', label: '空白', tip: '空白纸' },
  { key: 'grid', label: '网格', tip: '方格纸' },
  { key: 'ruled', label: '横线', tip: '横线纸（笔记纸）' },
  { key: 'dots', label: '点阵', tip: '点阵纸（子弹笔记）' },
]

/** 纸张底色（含 hex，组件 237-242 行）。 */
export const PAPER_COLORS: { key: PaperColor; label: string; hex: string }[] = [
  { key: 'white', label: '白纸', hex: '#ffffff' },
  { key: 'cream', label: '米黄', hex: '#fdf6e3' },
  { key: 'parchment', label: '羊皮', hex: '#f3e8d5' },
  { key: 'kraft', label: '牛皮', hex: '#e8d3ac' },
]

/** 横线/网格纸线条颜色（按纸色，组件 243-248 行）。 */
export const PAPER_LINE: Record<PaperColor, string> = {
  white: 'rgba(100,116,139,0.45)',
  cream: 'rgba(170,130,80,0.4)',
  parchment: 'rgba(150,110,70,0.42)',
  kraft: 'rgba(120,80,40,0.4)',
}

/** 点阵纸圆点颜色（按纸色，组件 249-254 行）。 */
export const PAPER_DOT: Record<PaperColor, string> = {
  white: 'rgba(100,116,139,0.5)',
  cream: 'rgba(170,130,80,0.45)',
  parchment: 'rgba(150,110,70,0.5)',
  kraft: 'rgba(120,80,40,0.5)',
}

/* ---------------- 内存 / DPR 预算（文档 §6） ---------------- */

/** 活动页 DPR 上限（static + ink + live）。 */
export const DPR_ACTIVE = 2.0
/** 可视但非活动页 DPR 上限。 */
export const DPR_VISIBLE = 1.5
/** 最低 DPR。 */
export const DPR_MIN = 1.0
/** 单页 backing store 内存预算（字节）：超过则自动降低该页 DPR。 */
export const BACKING_BUDGET_BYTES = 32 * 1024 * 1024

/* ---------------- feature flag（文档 §12 回滚开关） ---------------- */

/** 是否启用分层渲染器。
 *  回滚：置为 false 走旧 paint() 全量重绘路径（保留一个版本周期用于紧急回滚）。 */
export const USE_LAYERED_RENDERER = true

/** 是否把「非活动页 ink 层全量重建」放入 render.worker.ts。
 *  第二小步（P1.6）再启用；回滚：置为 false 回到主线程重建。 */
export const USE_WORKER_INK_REBUILD = false

/* ---------------- 工厂 / 工具函数 ---------------- */

let strokeIdCounter = 0

/** 生成 6 位 base36 随机串（长度恒为 6，保证同毫秒内仍不重复）。 */
function randBase36(n: number): string {
  let s = ''
  while (s.length < n) s += Math.floor(Math.random() * 36).toString(36)
  return s
}

/** 稳定唯一笔迹 ID：
 *  's' + Date.now().toString(36) + '-' + 自增序号(base36) + '-' + 6 位随机 base36。
 *  模块内维护计数器，同毫秒下序号递增，确保不重复（缓存键见文档 §4.1）。 */
export function newStrokeId(): string {
  strokeIdCounter += 1
  return 's' + Date.now().toString(36) + '-' + strokeIdCounter.toString(36) + '-' + randBase36(6)
}

/** 新建一页（paper 缺省 plain/white，与组件 makePage 506 行一致）。 */
export function makePage(w: number, h: number, paper?: PaperMeta): PageData {
  return {
    page: { w, h, paper: { style: paper?.style || 'plain', color: paper?.color || 'white' } },
    strokes: [],
    images: [],
  }
}

/** 笔迹填充不透明度（与组件 drawOne 932 行一致）：
 *  hl → 0.32；tip==='marker' → 0.92；其余 → 1。 */
export function strokeAlpha(stroke: StrokeV3): number {
  if (stroke.tool === 'hl') return 0.32
  if (stroke.tip === 'marker') return 0.92
  return 1
}

/** backing store 字节数估算：wPx*dpr * hPx*dpr * 4（32bit/像素）。 */
export function backingBytes(wPx: number, hPx: number, dpr: number): number {
  return wPx * dpr * hPx * dpr * 4
}
