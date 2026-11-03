<template>
  <div
    class="wb" :class="{ readonly }"
    @dragenter.capture="onDragEnter"
    @dragover.capture="onDragOver"
    @dragleave.capture="onDragLeave"
    @drop.capture="onDrop"
  >
    <!-- 左侧竖排工具栏（只读预览不显示） -->
    <div v-if="!readonly" class="wb-rail">
      <div class="rg">
        <button
          v-for="t in tools" :key="t.key" class="rb" :class="{ on: tool === t.key }"
          :title="t.tip" @click="pickTool(t.key)"
        ><span>{{ t.label }}</span></button>
        <button class="rb" title="插入图片（文件选择 / Ctrl+V 粘贴）" @click="filePick.click()"><span>插图</span></button>
        <button v-if="tool === 'select' && selImg" class="rb danger" title="删除选中的图片 (Delete)"
          @click="deleteSelImage"><span>删图</span></button>
      </div>

      <!-- 橡皮模式 -->
      <template v-if="tool === 'eraser'">
        <div class="rs" />
        <div class="rg"><span class="gl">擦除</span>
          <button class="rb" :class="{ on: eraserMode === 'part' }" title="局部擦除：擦过处把笔画切断"
            @click="eraserMode = 'part'"><span>局部</span></button>
          <button class="rb" :class="{ on: eraserMode === 'whole' }" title="整笔删除：擦到即删整条"
            @click="eraserMode = 'whole'"><span>整笔</span></button>
        </div>
      </template>

      <div class="rs" />
      <div class="rg">
        <button class="rb" :class="{ dis: !canUndo }" title="撤销 (Ctrl+Z)" @click="undo"><span>撤销</span></button>
        <button class="rb" :class="{ dis: !canRedo }" title="重做 (Ctrl+Y)" @click="redo"><span>重做</span></button>
        <button class="rb" :class="{ dis: !hasContent }" title="清空本页全部笔迹与图片" @click="clearAll"><span>清空</span></button>
      </div>

      <!-- 笔尖样式（钢笔工具时显示） -->
      <template v-if="tool === 'pen'">
        <div class="rs" />
        <div class="rg"><span class="gl">笔尖</span>
          <button
            v-for="tip in tips" :key="tip.key" class="rb" :class="{ on: tipKey === tip.key }"
            :title="tip.tip" @click="tipKey = tip.key"
          ><span>{{ tip.label }}</span></button>
        </div>
      </template>

      <div class="rs" />
      <div class="rg"><span class="gl">{{ tool === 'hl' ? '荧光色' : '颜色' }}</span>
        <div class="sw">
          <span
            v-for="c in colorList" :key="c" class="dot"
            :style="{ background: c }" :class="{ on: color === c }"
            :title="c" @click="color = c"
          />
          <span
            v-if="tool !== 'hl'" class="dot cus" :class="{ on: color === customHex }"
            title="自定义颜色" @click="openPicker"
          >
            <i v-for="g in 3" :key="g" :style="{ background: CUS_GRAD[g - 1] }" />
          </span>
        </div>
        <input ref="picker" type="color" class="hidden-picker" :value="customHex" @input="onCustom" />
      </div>

      <div class="rs" />
      <div class="rg"><span class="gl">{{ tool === 'eraser' ? '橡皮大小' : '粗细' }}</span>
        <button
          v-for="(w, i) in widthMeta" :key="w.key" class="rb" :class="{ on: widthIdx === i }"
          :title="w.label" @click="widthIdx = i"
        ><span>{{ w.key }}</span></button>
      </div>

      <!-- 页面 -->
      <div class="rs" />
      <div class="rg"><span class="gl">页面 {{ curIdx + 1 }}/{{ pages.length }}</span>
        <div class="grid2">
          <button class="rb xs" :class="{ dis: curIdx === 0 }" title="上一页" @click="goPage(curIdx - 1)"><span>上页</span></button>
          <button class="rb xs" :class="{ dis: curIdx >= pages.length - 1 }" title="下一页" @click="goPage(curIdx + 1)"><span>下页</span></button>
          <button class="rb xs" title="在末尾新增一页" @click="addPage"><span>新页</span></button>
          <button class="rb xs" :class="{ dis: pages.length <= 1 }" title="删除本页" @click="delPage"><span>删页</span></button>
        </div>
      </div>

      <div class="rs" />
      <div class="rg"><span class="gl">缩放 {{ Math.round(sheetScale * 100) }}%</span>
        <button class="rb" title="放大纸面" @click="zoomStep(1.25)"><span>放大</span></button>
        <button class="rb" title="缩小纸面" @click="zoomStep(1 / 1.25)"><span>缩小</span></button>
        <button class="rb" :class="{ on: sheetScale === 1 }" title="复原为适应容器宽度"
          @click="resetView"><span>复原</span></button>
        <button class="rb" title="整张纸一屏完整显示（居中）"
          @click="fitContain"><span>整页</span></button>
      </div>

      <div class="rs" />
      <div class="rg"><span class="gl">加宽纸面</span>
        <button class="rb xs" title="本页左右各加 25% 空白，内容保持居中（PPT/PDF 旁写不下时用）"
          @click="widenPage()"><span>加宽</span></button>
        <button class="rb xs" title="本页左右各减 25%（空白区已有笔迹时会拒绝）"
          @click="widenPage(1 / WIDEN_STEP)"><span>收窄</span></button>
        <button class="rb xs" title="本笔记所有页一起加宽（适合多页 PDF/PPT）"
          @click="widenAllPages()"><span>全部加宽</span></button>
      </div>

      <div class="rs" />
      <div class="rg"><span class="gl">纸张</span>
        <div class="grid2">
          <button
            v-for="p in paperStyles" :key="p.key" class="rb xs" :class="{ on: paperRef.style === p.key }"
            :title="p.tip" @click="setPaperStyle(p.key)"
          ><span>{{ p.label }}</span></button>
        </div>
        <div class="grid2 sqs">
          <span
            v-for="pc in paperColors" :key="pc.key" class="pdot"
            :style="{ background: pc.hex }" :class="{ on: paperRef.color === pc.key }"
            :title="pc.label" @click="setPaperColor(pc.key)"
          />
        </div>
      </div>

      <div class="rs" />
      <div class="rg"><span class="gl">页面比例</span>
        <button
          v-for="r in ratios" :key="r.key" class="rb" :class="{ on: curRatioKey === r.key, dis: ratioLocked }"
          :title="ratioLocked ? '本页已有内容，比例已锁定（新页可在空白时选择）' : r.tip"
          @click="setRatio(r.key)"
        ><span>{{ r.label }}</span></button>
      </div>

      <div class="sp" />
      <label class="touch-toggle" title="默认：触控笔书写、手指平移缩放；开启后可手指直接书写（双指仍可缩放）">
        <input type="checkbox" v-model="allowTouch" /><span>手指书写</span>
      </label>
      <input ref="filePick" type="file" accept="image/*" multiple class="hidden-picker" @change="onFilePick" />
    </div>

    <!-- 纸面区：连续长卷（多页垂直堆叠，原生滚动，可直接在任意页书写） -->
    <div class="wb-stage">
      <div
        ref="scrollEl" class="wb-flow"
        @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"
        @scroll.passive="onFlowScroll"
      >
        <div
          v-for="(pg, i) in pages" :key="i" class="wb-sheet" :class="{ cur: i === curIdx }"
          :style="sheetStyle(i)" :data-idx="i"
        >
          <div v-if="LAYERED" class="wb-layers">
            <canvas :ref="(el: any) => setLayerEl(i, 'static', el as HTMLCanvasElement | null)" class="wb-c" />
            <canvas :ref="(el: any) => setLayerEl(i, 'ink', el as HTMLCanvasElement | null)" class="wb-c" />
            <canvas v-if="!readonly" :ref="(el: any) => setLayerEl(i, 'live', el as HTMLCanvasElement | null)" class="wb-c" />
          </div>
          <canvas v-else :ref="(el: any) => setSheetEl(i, el as HTMLCanvasElement | null)" class="wb-canvas" />
          <div v-if="pages.length > 1" class="wb-pageno">{{ i + 1 }} / {{ pages.length }}</div>
          <div v-if="isEmptyPage(i) && !(i === curIdx && (drawing || cur.length > 1))" class="wb-hint">
            {{ readonly ? '这张纸还没有内容' : '在这页书写 · 上下滚动换页 · 可插图/粘贴图片' }}
          </div>
        </div>
        <div v-if="dragOver && !readonly" class="wb-drop"><span>松开即在当前页插入图片</span></div>
      </div>
      <div v-if="readonly" class="wb-zoom">
        <button title="缩小" @click="zoomSheets(1 / 1.15)">−</button>
        <span class="z-pct">{{ Math.round(sheetScale * 100) }}%</span>
        <button title="放大" @click="zoomSheets(1.15)">＋</button>
        <button class="z-txt" title="适应容器宽度" @click="resetView">宽度</button>
        <button class="z-txt" title="当前页一屏完整显示" @click="fitContain">整页</button>
      </div>
      <div v-if="readonly && pages.length > 1" class="ro-pager">
        <button :class="{ dis: curIdx === 0 }" @click="goPage(curIdx - 1)">上一页</button>
        <span>{{ curIdx + 1 }} / {{ pages.length }}</span>
        <button :class="{ dis: curIdx >= pages.length - 1 }" @click="goPage(curIdx + 1)">下一页</button>
      </div>
      <div v-if="!readonly" class="wb-foot">
        <span class="f1">停笔后约 1.5 秒自动保存 · 连续滚动，可直接在任意页书写</span>
        <span class="f2">{{ penNow }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getStroke } from 'perfect-freehand'
import { USE_LAYERED_RENDERER, USE_WORKER_INK_REBUILD, newStrokeId, DPR_ACTIVE } from '../whiteboard/types'
import { parsePayload as wbParsePayload, serialize as wbSerialize } from '../whiteboard/payload'
import { StrokeBuffer } from '../whiteboard/input/StrokeBuffer'
import { LiveInkRenderer, drawEraserRing, drawImgBox as wbDrawImgBox } from '../whiteboard/renderer/LiveInkRenderer'
import { LayeredPageRenderer } from '../whiteboard/renderer/LayeredPageRenderer'
import { InkPerfMonitor } from '../whiteboard/perf/InkPerfMonitor'

/* ---------------- 类型与常量 ---------------- */

type Tool = 'pen' | 'hl' | 'eraser' | 'select'
type TipKey = 'ball' | 'pen' | 'marker'
type PaperStyle = 'plain' | 'grid' | 'ruled' | 'dots'
type PaperColor = 'white' | 'cream' | 'parchment' | 'kraft'
type EraserMode = 'part' | 'whole'

interface Pt { x: number; y: number; p: number }
interface Stroke {
  tool: Tool
  color: string
  w: number
  tip?: TipKey
  sp?: boolean
  pts: Pt[]
}
/** 图片：x/y/w 为纸面宽的比例；r = 像素高/宽（保持原始宽高比） */
interface ImgEl { id: string; x: number; y: number; w: number; r: number; src: string }
interface PageData {
  page: { w: number; h: number; paper: { style: PaperStyle; color: PaperColor } }
  strokes: Stroke[]
  images: ImgEl[]
}
/** 历史快照：带页号与页宽高（连续长卷下切页、加宽都要能还原） */
interface Hist { idx: number; s: Stroke[]; im: ImgEl[]; pw?: number; ph?: number }

const RATIOS = {
  v: { label: '竖版', w: 1000, h: 1414 },
  h: { label: '横版', w: 1414, h: 1000 },
  sq: { label: '方形', w: 1200, h: 1200 },
} as const
type RatioKey = keyof typeof RATIOS

const tools: { key: Tool; label: string; tip: string }[] = [
  { key: 'pen', label: '钢笔', tip: '触控笔压感书写' },
  { key: 'hl', label: '荧光笔', tip: '半透明宽幅标记' },
  { key: 'eraser', label: '橡皮', tip: '局部擦除或整笔删除（仅笔迹）' },
  { key: 'select', label: '选择', tip: '移动 / 缩放 / 删除图片' },
]
const tips: { key: TipKey; label: string; tip: string }[] = [
  { key: 'ball', label: '圆珠', tip: '粗细均匀，适合速记' },
  { key: 'pen', label: '钢笔', tip: '压感笔锋，适合书写' },
  { key: 'marker', label: '马克', tip: '宽幅平头，适合标题' },
]
const PEN_COLORS = ['#1f2937', '#475569', '#7c3aed', '#2563eb', '#0ea5e9', '#059669', '#dc2626', '#ea580c']
const HL_COLORS = ['#fde047', '#a3e635', '#22d3ee', '#f472b6']
const CUS_GRAD = ['#f87171', '#facc15', '#38bdf8']
const widthMeta = [
  { key: '细', label: '细' },
  { key: '中', label: '中' },
  { key: '粗', label: '粗' },
]
const ERASER_R = [16, 26, 40]
const paperStyles: { key: PaperStyle; label: string; tip: string }[] = [
  { key: 'plain', label: '空白', tip: '空白纸' },
  { key: 'grid', label: '网格', tip: '方格纸' },
  { key: 'ruled', label: '横线', tip: '横线纸（笔记纸）' },
  { key: 'dots', label: '点阵', tip: '点阵纸（子弹笔记）' },
]
const paperColors: { key: PaperColor; label: string; hex: string }[] = [
  { key: 'white', label: '白纸', hex: '#ffffff' },
  { key: 'cream', label: '米黄', hex: '#fdf6e3' },
  { key: 'parchment', label: '羊皮', hex: '#f3e8d5' },
  { key: 'kraft', label: '牛皮', hex: '#e8d3ac' },
]
const PAPER_LINE: Record<PaperColor, string> = {
  white: 'rgba(100,116,139,0.45)',
  cream: 'rgba(170,130,80,0.4)',
  parchment: 'rgba(150,110,70,0.42)',
  kraft: 'rgba(120,80,40,0.4)',
}
const PAPER_DOT: Record<PaperColor, string> = {
  white: 'rgba(100,116,139,0.5)',
  cream: 'rgba(170,130,80,0.45)',
  parchment: 'rgba(150,110,70,0.5)',
  kraft: 'rgba(120,80,40,0.5)',
}
const ratios: { key: RatioKey; label: string; tip: string }[] = [
  { key: 'v', label: '竖版', tip: 'A4 竖版（默认）' },
  { key: 'h', label: '横版', tip: 'A4 横版' },
  { key: 'sq', label: '方形', tip: '方形纸面' },
]

const props = withDefaults(defineProps<{ modelValue?: string; readonly?: boolean }>(), {
  modelValue: '',
  readonly: false,
})
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

/* ---------------- 状态 ---------------- */

const cv = ref<HTMLCanvasElement | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
const filePick = ref<HTMLInputElement | null>(null)
const tool = ref<Tool>('pen')
const tipKey = ref<TipKey>('pen')
const eraserMode = ref<EraserMode>('part')
const color = ref(PEN_COLORS[0])
const customHex = ref('#f97316')
const widthIdx = ref(1)
const allowTouch = ref(false)

const pages = ref<PageData[]>([])
const curIdx = ref(0)
const drawing = ref(false)
const cur = ref<{ x: number; y: number; p: number }[]>([])
const undoStack: Hist[] = []
const redoStack: Hist[] = []
const selImg = ref<string | null>(null)
/** 图片拖拽/缩放中 */
let imgOp: null | { id: string; mode: 'move' | 'resize'; hi: number; sx: number; sy: number; ox: number; oy: number; ow: number } = null
/** 图片解码缓存 */
const imgCache = new Map<string, HTMLImageElement>()
const imgLoadQueue = new Set<string>()

let rafId = 0
let lastKind: string = 'mouse'
let hoverPos: { x: number; y: number } | null = null
/** 当前拥有书写/擦除手势的指针；避免其他指针误结束笔迹 */
let inkPointerId: number | null = null
let inkPointerType: string | null = null
let ptrs = new Map<number, { x: number; y: number }>()
let eraseBusy = false
let eraseChanged = false
let lastErase: { x: number; y: number } | null = null
/** 手指平移长卷时的上一个触点/双指中心 */
let touchPan: { x: number; y: number } | null = null
/** 双指捏合缩放：起始距离 / 起始 y / 起始缩放 */
let twoFinger: { d: number; y: number; scale: number } | null = null
/** 本次手势是否发生过缩放（结束时需要全量重绘） */
let gestureZoomed = false

/* ---------------- 连续长卷（多页垂直堆叠）状态 ---------------- */

/** 每页的画布元素（下标=页号；活动页的画布即引擎绘制目标 cv） */
const sheetEls: (HTMLCanvasElement | null)[] = []
/** 纸面宽度（CSS px，已含缩放） */
const sheetW = ref(0)
/** 纸面宽度缩放系数（1=适应容器宽度） */
const sheetScale = ref(1)
/** 长卷内边距与页间距（与 CSS 对应） */
const FLOW_PAD = 12
const SHEET_GAP = 16
/** 每页在长卷内容坐标中的顶部偏移（用于命中判定，避免逐页读布局） */
let sheetTops: number[] = []
/** 当前已渲染（可视区附近）的页号 */
const painted = new Set<number>()
let io: IntersectionObserver | null = null
let scrollRaf = 0

/* ---------------- 分层渲染（LAYERED）非响应式状态 ---------------- */

const LAYERED = USE_LAYERED_RENDERER
/** 每页分层画布（下标=页号）：static/ink 恒有；live 仅编辑模式（只读页不分配湿墨 backing） */
const layerEls: { static: HTMLCanvasElement | null; ink: HTMLCanvasElement | null; live: HTMLCanvasElement | null }[] = []
let renderer: LayeredPageRenderer | null = null
let perf: InkPerfMonitor | null = null
const liveInk = new LiveInkRenderer()
const buffer = new StrokeBuffer()
let lastInputTs = 0
let resizeTimer = 0
let overlayRaf = 0
/** 拖拽/缩放中的图片 id（static 层重建时跳过它，避免旧位置重影） */
let dragExcludeId: string | null = null

/* ---------------- 视图与计算 ---------------- */

const curPage = computed<PageData | null>(() => pages.value[curIdx.value] ?? null)
const paperRef = computed(() => curPage.value?.page.paper ?? { style: 'plain', color: 'white' } as { style: PaperStyle; color: PaperColor })
const curRatioKey = computed<RatioKey | null>(() => {
  const pg = curPage.value
  if (!pg) return 'v'
  const k = Object.keys(RATIOS).find((x) => RATIOS[x as RatioKey].w === pg.page.w && RATIOS[x as RatioKey].h === pg.page.h)
  return (k as RatioKey) || 'v'
})
const ratioLocked = computed(() => {
  const pg = curPage.value
  return !!pg && (pg.strokes.length > 0 || pg.images.length > 0)
})
const hasContent = computed(() => {
  const pg = curPage.value
  return !!pg && (pg.strokes.length > 0 || pg.images.length > 0)
})
const canUndo = computed(() => undoStack.length > 0)
const canRedo = computed(() => redoStack.length > 0)
const colorList = computed(() => (tool.value === 'hl' ? HL_COLORS : PEN_COLORS))
const penNow = computed(() => {
  if (tool.value === 'select') return selImg.value ? '选择图片' : '选择'
  const t = { pen: '钢笔', hl: '荧光笔', eraser: '橡皮' }[tool.value]
  if (tool.value === 'pen') {
    const tip = tipKey.value === 'ball' ? '圆珠' : tipKey.value === 'marker' ? '马克' : '钢笔'
    return `${tip} · ${widthMeta[widthIdx.value]?.key || '中'}`
  }
  return `${t} · ${widthMeta[widthIdx.value]?.key || '中'}`
})

let cssW = 0
let cssH = 0

/* ---------------- 连续长卷：尺寸 / 命中 / 渲染调度 ---------------- */

/** 页高宽比 */
function ratioOf(i: number): number {
  const pg = pages.value[i]
  return pg ? pg.page.h / pg.page.w : RATIOS.v.h / RATIOS.v.w
}

/** 兼容旧调用：当前页高宽比 */
function pageRatio(): number {
  return ratioOf(curIdx.value)
}

/** 该页在长卷中的 CSS 高度 */
function pageCssH(i: number): number {
  return Math.max(80, Math.round(sheetW.value * ratioOf(i)))
}

function sheetStyle(i: number) {
  return { width: `${sheetW.value}px`, height: `${pageCssH(i)}px` }
}

function isEmptyPage(i: number): boolean {
  const pg = pages.value[i]
  return !pg || (pg.strokes.length === 0 && pg.images.length === 0)
}

/** 页画布挂载：活动页的画布同时作为引擎绘制目标 */
function setSheetEl(i: number, el: HTMLCanvasElement | null) {
  sheetEls[i] = el
  if (i === curIdx.value && el) cv.value = el
}

/** 重算各页顶部偏移（长卷内容坐标，命中判定用，避免逐页读布局） */
function rebuildTops() {
  sheetTops = []
  let y = FLOW_PAD
  for (let i = 0; i < pages.value.length; i++) {
    sheetTops.push(y)
    y += pageCssH(i) + SHEET_GAP
  }
}

/** 容器可用宽度（去掉内边距） */
function flowWidth(): number {
  const wrap = scrollEl.value
  return Math.max(240, (wrap ? wrap.clientWidth : 900) - FLOW_PAD * 2)
}

function layout(quick = false) {
  sheetW.value = Math.max(200, Math.round(flowWidth() * sheetScale.value))
  rebuildTops()
  syncActive()
  if (LAYERED) {
    // quick=true（捏合中）：只更新 CSS 尺寸，canvas 随 sheet 自动拉伸；结束后再重建 backing
    if (quick) return
    scheduleBackingRebuild()
    return
  }
  // quick=true：手势进行中只重绘活动页，保证跟手；手势结束后再全量重绘
  if (quick) refreshCanvas(false, true)
  else refreshCanvas(true)
}

/** 活动页画布与 curIdx 对齐 */
function syncActive() {
  const el = sheetEls[curIdx.value]
  if (el) cv.value = el
  syncAmbient()
  if (LAYERED) renderer?.setActiveIndex(curIdx.value)
}

/** 重绘：默认画可视区附近的页；activeOnly=true 只画活动页（书写中的高频路径） */
function refreshCanvas(forceRedraw = false, activeOnly = false) {
  if (activeOnly) {
    paint(curIdx.value, true)
    return
  }
  for (const i of visibleIdx()) paint(i, i === curIdx.value)
  if (forceRedraw) paint(curIdx.value, true)
}

/** 可视区附近的页号（含预渲染余量） */
function visibleIdx(): number[] {
  const wrap = scrollEl.value
  if (!wrap) return [curIdx.value]
  const top = wrap.scrollTop - 800
  const bottom = wrap.scrollTop + wrap.clientHeight + 800
  const out: number[] = []
  for (let i = 0; i < pages.value.length; i++) {
    const t = sheetTops[i] ?? 0
    if (t + pageCssH(i) >= top && t <= bottom) out.push(i)
  }
  if (!out.includes(curIdx.value)) out.push(curIdx.value)
  return out
}

function scrollToSheet(i: number, smooth = true) {
  const wrap = scrollEl.value
  if (!wrap || i < 0 || i >= pages.value.length) return
  const top = Math.max(0, (sheetTops[i] ?? 0) - FLOW_PAD)
  wrap.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' })
}

/** 缩放纸面宽度：anchorY 为视口内锚点（尽量保持该处内容不跳） */
function zoomSheets(factor: number, anchorY?: number) {
  const wrap = scrollEl.value
  const prev = sheetScale.value
  const next = Math.min(3, Math.max(0.4, prev * factor))
  if (Math.abs(next - prev) < 0.001) return
  let total = 1
  let ratio = 0
  if (wrap) {
    total = Math.max(1, (sheetTops[pages.value.length - 1] ?? 0) + pageCssH(pages.value.length - 1))
    const wr = wrap.getBoundingClientRect()
    const y = anchorY === undefined ? wr.top + wr.height / 2 : anchorY
    ratio = (y - wr.top + wrap.scrollTop) / total
  }
  sheetScale.value = next
  layout()
  if (wrap) {
    const total2 = Math.max(1, (sheetTops[pages.value.length - 1] ?? 0) + pageCssH(pages.value.length - 1))
    wrap.scrollTop = Math.max(0, ratio * total2 - (anchorY === undefined && wrap ? wrap.clientHeight / 2 : 0))
  }
}

function zoomStep(factor: number) {
  zoomSheets(factor)
}

/** 整页：把当前页缩到一屏可见 */
function fitContain() {
  const wrap = scrollEl.value
  if (!wrap) return
  const availH = Math.max(240, wrap.clientHeight - 40)
  sheetScale.value = Math.min(1, Math.max(0.4, availH / (flowWidth() * ratioOf(curIdx.value))))
  layout()
  scrollToSheet(curIdx.value, false)
}

function resetView() {
  sheetScale.value = 1
  layout()
}

/** 兼容旧调用：连续长卷下缩放改为纸面宽度缩放（见 zoomSheets） */

/* ---------------- 数据进出（v1 兼容 / v2） ---------------- */

function makePage(w: number, h: number, paper?: { style: PaperStyle; color: PaperColor }): PageData {
  return { page: { w, h, paper: { style: paper?.style || 'plain', color: paper?.color || 'white' } }, strokes: [], images: [] }
}

function serialize(): string {
  // LAYERED：写 v3（笔迹带稳定 id；旧版本读 v3 走 v2 分支并忽略新字段，双向兼容）
  if (LAYERED) return wbSerialize(pages.value as any)
  return JSON.stringify({ v: 2, pages: pages.value } as { v: 2; pages: PageData[] })
}

function pushPayload() {
  emit('update:modelValue', serialize())
}

function parsePayload(raw: string): PageData[] | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw)
    if (o && typeof o === 'object') {
      if (Array.isArray(o.pages)) {
        const list = (o.pages as any[]).filter((p) => p && p.page && p.page.w > 0 && p.page.h > 0)
        if (list.length) {
          return list.map((p) => ({
            page: {
              w: p.page.w, h: p.page.h,
              paper: {
                style: paperStyles.some((x) => x.key === p.page.paper?.style) ? p.page.paper.style : 'plain',
                color: paperColors.some((x) => x.key === p.page.paper?.color) ? p.page.paper.color : 'white',
              },
            },
            strokes: Array.isArray(p.strokes) ? p.strokes : [],
            images: Array.isArray(p.images) ? p.images : [],
          }))
        }
      }
      // v1 单页兼容
      if (Array.isArray(o.strokes) && o.page && o.page.w > 0 && o.page.h > 0) {
        return [makePage(o.page.w, o.page.h, o.page.paper)]
          .map((pg) => ({ ...pg, strokes: o.strokes as Stroke[] }))
      }
    }
  } catch { /* ignore */ }
  return null
}

function loadPayload(raw: string) {
  // LAYERED：用 whiteboard/payload 解析（为缺 id 的 v1/v2 笔迹补稳定 id，路径缓存键依赖 id）
  const list = LAYERED ? wbParsePayload(raw) : parsePayload(raw)
  pages.value = list && list.length ? list : [makePage(RATIOS.v.w, RATIOS.v.h)]
  curIdx.value = 0
  clearHistory()
  selImg.value = null
  nextTick(() => {
    observeAll()
    if (LAYERED) {
      reRegisterAll()
      layout(true)
      rebuildVisibleBacking()
    } else {
      layout()
    }
    scrollToSheet(0, false)
  })
}

/* ---------------- 纸张与页面操作 ---------------- */

function paperDims(): { w: number; h: number } {
  return curPage.value ? { w: curPage.value.page.w, h: curPage.value.page.h } : { w: RATIOS.v.w, h: RATIOS.v.h }
}

function setPaperStyle(st: PaperStyle) {
  const pg = curPage.value
  if (!pg || pg.page.paper.style === st) return
  pg.page.paper.style = st
  pushPayload()
  if (LAYERED) renderer?.paintStatic(curIdx.value)
  else scheduleRedraw()
}

function setPaperColor(c: PaperColor) {
  const pg = curPage.value
  if (!pg || pg.page.paper.color === c) return
  pg.page.paper.color = c
  pushPayload()
  if (LAYERED) renderer?.paintStatic(curIdx.value)
  else scheduleRedraw()
}

function setRatio(k: RatioKey) {
  const pg = curPage.value
  if (!pg || curRatioKey.value === k || ratioLocked.value) {
    if (ratioLocked.value) ElMessage.info('本页已有内容，比例已锁定；可新增一页或在空白页选择方向')
    return
  }
  pg.page.w = RATIOS[k].w
  pg.page.h = RATIOS[k].h
  pushPayload()
  layout()
}

/* ---------------- 纸面左右加宽（给导入的 PPT/PDF 加空白书写区） ---------------- */

const WIDEN_STEP = 1.25   // 每次加宽比例（左右各加 25%）
const PAGE_W_MIN = 400    // 页宽单位下限
const PAGE_W_MAX = 8000   // 页宽单位上限（约 8 屏宽）

/** 保持内容尺寸不变，把该页内容等比缩到中间 1/k 并居中（不可变更新，便于撤销）
 *  返回 false = 收窄时内容已越出中间窗口（空白区写过字），拒绝以免裁掉内容 */
function remapPageWidth(pg: PageData, k: number): boolean {
  const half = (k - 1) / (2 * k)      // 新页中内容区的左边界（归一化）
  if (k < 1) {
    // 收窄：变换后须仍落在 [0,1] 内 → 等价于变换前 x ∈ [lo, hi]
    const lo = -half * k
    const hi = (1 - half) * k
    const inside = (x: number) => x >= lo - 1e-6 && x <= hi + 1e-6
    for (const im of pg.images) {
      if (!inside(im.x) || !inside(im.x + im.w)) return false
    }
    for (const s of pg.strokes) {
      for (const p of s.pts) if (!inside(p.x)) return false
    }
  }
  pg.images = pg.images.map((im) => ({ ...im, x: half + im.x / k, w: im.w / k }))
  pg.strokes = pg.strokes.map((s) => ({
    ...s,
    w: s.w / k,
    pts: s.pts.map((p) => ({ ...p, x: half + p.x / k })),
  }))
  return true
}

/** 单页加宽/收窄（k>1 加宽，k<1 收窄） */
function scalePageWidth(pg: PageData, k: number): boolean {
  const nextW = pg.page.w * k
  if (nextW < PAGE_W_MIN || nextW > PAGE_W_MAX) return false
  if (!remapPageWidth(pg, k)) return false
  pg.page.w = nextW
  return true
}

/** 当前页左右加宽（默认 +25%）；k<1 为收窄 */
function widenPage(k = WIDEN_STEP) {
  const pg = curPage.value
  if (!pg) return
  const up = k > 1
  pushHist()
  if (!scalePageWidth(pg, k)) {
    undoStack.pop() // 未生效：撤回刚压入的快照
    if (!up) ElMessage.warning('空白区已有笔迹，收窄会裁掉它们；请先擦除后再收窄')
    else ElMessage.warning('已达纸面宽度上限')
    return
  }
  pushPayload()
  layout()
  ElMessage.success(up ? '本页左右已加宽，可在两侧空白处书写' : '本页已收窄')
}

/** 本笔记所有页一起加宽（PDF/PPT 多页一次搞定）；收窄不提供批量，避免误裁 */
function widenAllPages(k = WIDEN_STEP) {
  if (!pages.value.length) return
  let done = 0
  for (const pg of pages.value) if (scalePageWidth(pg, k)) done++
  if (!done) {
    ElMessage.warning('全部页均已达纸面宽度上限')
    return
  }
  clearHistory() // 多页同时变更，逐页快照难以一致还原
  pushPayload()
  layout()
  ElMessage.success(`已加宽 ${done} 页（其余页已达上限）`)
}

function addPage() {
  const pg = curPage.value
  const w = pg ? pg.page.w : RATIOS.v.w
  const h = pg ? pg.page.h : RATIOS.v.h
  const paper = pg ? { ...pg.page.paper } : undefined
  pages.value.push(makePage(w, h, paper))
  pushPayload()
  const last = pages.value.length - 1
  ElMessage.success('已新增一页（第 ' + pages.value.length + ' 页）')
  nextTick(() => {
    observeAll()
    layout()
    if (LAYERED) reRegisterAll()
    goPage(last)
  })
}

async function delPage() {
  if (pages.value.length <= 1) return
  try {
    await ElMessageBox.confirm(`确定删除第 ${curIdx.value + 1} 页？该页全部笔迹与图片将不可恢复。`, '删除页面', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch { return }
  const at = curIdx.value
  pages.value.splice(at, 1)
  curIdx.value = Math.max(0, at - 1)
  selImg.value = null
  clearHistory() // 页号已变，历史快照失效
  pushPayload()
  nextTick(() => {
    observeAll()
    layout()
    scrollToSheet(curIdx.value)
    if (LAYERED) {
      renderer?.resetPages(pages.value.length)
      reRegisterAll()
      rebuildVisibleBacking()
    }
  })
}

/** 切到第 i 页（连续长卷：只改活动页 + 滚动定位，不清历史——历史带页号） */
function goPage(i: number, opts: { scroll?: boolean; smooth?: boolean } = {}) {
  if (i < 0 || i >= pages.value.length) return
  const wantScroll = opts.scroll !== false
  if (i === curIdx.value) {
    if (wantScroll) scrollToSheet(i, opts.smooth !== false)
    return
  }
  if (drawing.value || eraseBusy) return
  curIdx.value = i
  cur.value = []
  cancelEraseGesture(false)
  selImg.value = null
  imgOp = null
  hoverPos = null
  syncActive()
  if (LAYERED) {
    refreshPageFull(i)
    scheduleOverlay()
  }
  if (wantScroll) scrollToSheet(i, opts.smooth !== false)
}

/* ---------------- 长卷：引用重建 / 观察器 / 释放 / 滚动同步 ---------------- */

/** 依据当前 DOM 重建每页画布引用（增删页后页号会变） */
function rebuildSheetEls() {
  const wrap = scrollEl.value
  sheetEls.length = 0
  if (!wrap) return
  wrap.querySelectorAll<HTMLCanvasElement>('canvas.wb-canvas').forEach((el, i) => {
    sheetEls[i] = el
  })
  syncActive()
}

/** 观察可视区附近的页：进入 → 渲染并加载图片；离开 → 释放画布与解码图（大文档内存护栏） */
function observeAll() {
  rebuildSheetEls()
  io?.disconnect()
  io = null
  const wrap = scrollEl.value
  if (!wrap || typeof IntersectionObserver === 'undefined') return
  io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      const i = Number((en.target as HTMLElement).dataset.idx)
      if (Number.isNaN(i)) continue
      if (en.isIntersecting) {
        painted.add(i)
        ensurePageImgs(i)
        if (LAYERED && renderer) {
          const r = renderer
          // 活动页定活动档（内部可能 resize 清层）；非活动页确保档位基准在 curIdx
          if (i === curIdx.value) r.setActivePage(i)
          else r.setActiveIndex(curIdx.value)
          const w = sheetW.value
          const h = pageCssH(i)
          // matchSize 命中 ≠ backing 可用：release() 保留 css 尺寸但 backing 已置 1×1
          const released = (layerEls[i]?.static?.width ?? 0) <= 1
          if (!r.matchSize(i, w, h) || released) {
            r.resizePage(i, w, h)
            r.paintStatic(i)
            if (USE_WORKER_INK_REBUILD && i !== curIdx.value && pages.value[i]?.strokes.length > 50) {
              r.paintInkWorker(i).then((ok) => { if (!ok) r.paintInk(i) })
            } else {
              r.paintInk(i)
            }
          } else {
            r.paintStatic(i)
            r.paintInk(i)
          }
        } else {
          paint(i, i === curIdx.value)
        }
      } else if (i !== curIdx.value) {
        painted.delete(i)
        releaseSheet(i)
      }
    }
  }, { root: wrap, rootMargin: '800px 0px' })
  wrap.querySelectorAll<HTMLElement>('.wb-sheet').forEach((el) => io!.observe(el))
}

function releaseSheet(i: number) {
  if (LAYERED) {
    renderer?.release(i)
    dropPageImgs(i)
    return
  }
  const c = sheetEls[i]
  if (c && i !== curIdx.value) {
    const ctx2d = c.getContext('2d')
    ctx2d?.clearRect(0, 0, c.width, c.height)
  }
  dropPageImgs(i)
}

/** 滚动时同步活动页（=最靠近视口中心的一页），书写/擦除中不动 */
function onFlowScroll() {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    if (drawing.value || eraseBusy || imgOp) return
    const wrap = scrollEl.value
    if (!wrap) return
    const center = wrap.scrollTop + wrap.clientHeight / 2
    let best = curIdx.value
    let bestD = Infinity
    for (let i = 0; i < pages.value.length; i++) {
      const mid = (sheetTops[i] ?? 0) + pageCssH(i) / 2
      const d = Math.abs(mid - center)
      if (d < bestD) {
        bestD = d
        best = i
      }
    }
    if (best !== curIdx.value) {
      curIdx.value = best
      hoverPos = null
      selImg.value = null
      syncActive()
      if (LAYERED) {
        refreshPageFull(best)
        scheduleOverlay()
      }
    }
  })
}

function clearHistory() {
  undoStack.length = 0
  redoStack.length = 0
}

/* ---------------- 历史（按当前页；图片与笔迹同栈线性撤销） ---------------- */

function snap(): Hist {
  const pg = curPage.value
  return {
    idx: curIdx.value,
    s: pg ? pg.strokes.slice() : [],
    im: pg ? pg.images.map((m) => ({ ...m })) : [],
    pw: pg?.page.w,
    ph: pg?.page.h,
  }
}

function pushHist() {
  undoStack.push(snap())
  if (undoStack.length > 80) undoStack.shift()
  redoStack.length = 0
}

/** 应用快照到它所属的页（跨页撤销时强制切页，避免把 A 页快照写到 B 页） */
function applyHist(h: Hist) {
  const pg = pages.value[h.idx]
  if (!pg) return
  let switched = false
  if (h.idx !== curIdx.value) {
    drawing.value = false
    eraseBusy = false
    cur.value = []
    imgOp = null
    selImg.value = null
    curIdx.value = h.idx
    syncActive()
    scrollToSheet(h.idx)
    switched = true
  }
  // 应用前记录页固有尺寸（加宽/比例变更的快照还原后需要重建 backing）
  const oldW = pg.page.w
  const oldH = pg.page.h
  pg.strokes = h.s
  pg.images = h.im
  if (h.pw) pg.page.w = h.pw
  if (h.ph) pg.page.h = h.ph
  selImg.value = null
  pushPayload()
  rebuildTops()
  if (LAYERED && renderer) {
    renderer.setActiveIndex(h.idx)
    if ((h.pw && h.pw !== oldW) || (h.ph && h.ph !== oldH)) {
      layout() // 页固有尺寸变化：防抖重建可见页 backing
    } else if (switched) {
      refreshPageFull(h.idx) // 跨页撤销：新活动页全量重建
    } else {
      renderer.paintInk(h.idx)
    }
    scheduleOverlay()
  } else {
    paint(h.idx, true)
  }
}

function undo() {
  if (!undoStack.length) return
  redoStack.push(snap())
  applyHist(undoStack.pop()!)
}

function redo() {
  if (!redoStack.length) return
  undoStack.push(snap())
  applyHist(redoStack.pop()!)
}

/* ---------------- 纸张绘制 ---------------- */

function drawPaper(ctx: CanvasRenderingContext2D, w: number, h: number, paper: { style: PaperStyle; color: PaperColor }) {
  const hex = (paperColors.find((p) => p.key === paper.color) || paperColors[0]).hex
  ctx.fillStyle = hex
  ctx.fillRect(0, 0, w, h)
  const st = paper.style
  if (st === 'plain') return
  ctx.save()
  if (st === 'grid' || st === 'dots') {
    const step = Math.max(14, w / 16)
    if (st === 'grid') {
      ctx.strokeStyle = PAPER_LINE[paper.color]
      ctx.lineWidth = 1
      ctx.beginPath()
      for (let x = step; x < w; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, h) }
      for (let y = step; y < h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
      ctx.stroke()
    } else {
      ctx.fillStyle = PAPER_DOT[paper.color]
      for (let x = step / 2; x < w; x += step) {
        for (let y = step / 2; y < h; y += step) {
          ctx.fillRect(x - 0.75, y - 0.75, 1.5, 1.5)
        }
      }
    }
  } else {
    const row = Math.max(18, h / 26)
    ctx.strokeStyle = 'rgba(200, 90, 90, 0.4)'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let y = row; y < h; y += row) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
    ctx.stroke()
    ctx.strokeStyle = PAPER_LINE[paper.color]
    const mx = Math.max(20, w * 0.07)
    ctx.beginPath()
    ctx.moveTo(mx, 0); ctx.lineTo(mx, h)
    ctx.stroke()
  }
  ctx.restore()
}

/* ---------------- 笔迹渲染 ---------------- */

function strokeOpts(stroke: Stroke, last: boolean) {
  const size = Math.max(1, stroke.w * cssW)
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

function drawOne(stroke: Stroke, last: boolean, ctxOverride?: CanvasRenderingContext2D) {
  const ctx2d = ctxOverride || cv.value?.getContext('2d')
  if (!ctx2d || !stroke.pts.length) return
  const raw: [number, number, number][] = stroke.pts.map((p) => [p.x * cssW, p.y * cssH, p.p])
  const outline = getStroke(raw, strokeOpts(stroke, last) as any)
  if (!outline.length) return
  const path = new Path2D()
  path.moveTo(outline[0][0], outline[0][1])
  for (let i = 1; i < outline.length - 1; i++) {
    const x0 = outline[i - 1][0], y0 = outline[i - 1][1]
    const x1 = outline[i][0], y1 = outline[i][1]
    const x2 = outline[i + 1][0], y2 = outline[i + 1][1]
    path.quadraticCurveTo(x1, y1, (x1 + x2) / 2, (y1 + y2) / 2)
  }
  path.closePath()
  ctx2d.globalAlpha = stroke.tool === 'hl' ? 0.32 : stroke.tip === 'marker' ? 0.92 : 1
  ctx2d.fillStyle = stroke.color
  ctx2d.fill(path)
  ctx2d.globalAlpha = 1
}

/* ---------------- 图片：加载 / 布局 / 绘制 ---------------- */

function imgPixel(img: ImgEl): { px: number; py: number; pw: number; ph: number } {
  const pw = img.w * cssW
  return { px: img.x * cssW, py: img.y * cssH, pw, ph: pw * img.r }
}

/** 按页加载图片（连续长卷下只加载可视区附近的页，避免大文档解码爆内存） */
function ensurePageImgs(i: number) {
  const pg = pages.value[i]
  if (!pg) return
  for (const im of pg.images) {
    if (imgCache.has(im.src) || imgLoadQueue.has(im.src)) continue
    imgLoadQueue.add(im.src)
    const el = new Image()
    el.onload = () => {
      imgCache.set(im.src, el)
      imgLoadQueue.delete(im.src)
      if (LAYERED) {
        if (i === curIdx.value && dragExcludeId) renderer?.paintStatic(i, dragExcludeId)
        else renderer?.paintStatic(i)
      } else {
        paint(i, i === curIdx.value)
      }
    }
    el.onerror = () => imgLoadQueue.delete(im.src)
    el.src = im.src
  }
}

/** 释放某页的解码图片（该页离开可视区且不再渲染时调用） */
function dropPageImgs(i: number) {
  const pg = pages.value[i]
  if (!pg) return
  for (const im of pg.images) imgCache.delete(im.src)
}

function drawImg(ctx2d: CanvasRenderingContext2D, img: ImgEl) {
  const el = imgCache.get(img.src)
  if (!el || !el.complete || el.naturalWidth === 0) return
  const { px, py, pw, ph } = imgPixel(img)
  ctx2d.drawImage(el, px, py, pw, ph)
}

function drawImgBox(ctx2d: CanvasRenderingContext2D, img: ImgEl, sel: boolean) {
  const { px, py, pw, ph } = imgPixel(img)
  if (sel) {
    ctx2d.save()
    ctx2d.strokeStyle = '#8b5cf6'
    ctx2d.lineWidth = 1.5
    ctx2d.setLineDash([5, 4])
    ctx2d.strokeRect(px - 2, py - 2, pw + 4, ph + 4)
    ctx2d.setLineDash([])
    const hs = 6
    for (const [hx, hy] of [[px, py], [px + pw, py], [px, py + ph], [px + pw, py + ph]]) {
      ctx2d.fillStyle = '#ffffff'
      ctx2d.fillRect(hx - hs, hy - hs, hs * 2, hs * 2)
      ctx2d.strokeStyle = '#8b5cf6'
      ctx2d.strokeRect(hx - hs, hy - hs, hs * 2, hs * 2)
    }
    ctx2d.restore()
  } else {
    ctx2d.strokeStyle = 'rgba(139,92,246,.5)'
    ctx2d.lineWidth = 1
    ctx2d.strokeRect(px, py, pw, ph)
  }
}

function imgHitAt(lx: number, ly: number): string | null {
  const pg = curPage.value
  if (!pg) return null
  for (let i = pg.images.length - 1; i >= 0; i--) {
    const { px, py, pw, ph } = imgPixel(pg.images[i])
    if (lx >= px && lx <= px + pw && ly >= py && ly <= py + ph) return pg.images[i].id
  }
  return null
}

/** 命中手柄：返回 [角序号] 或 -1；角序 0=左上 1=右上 2=左下 3=右下 */
function handleHitAt(lx: number, ly: number): number {
  const pg = curPage.value
  if (!pg) return -1
  const im = pg.images.find((m) => m.id === selImg.value)
  if (!im) return -1
  const { px, py, pw, ph } = imgPixel(im)
  const cs = [[px, py], [px + pw, py], [px, py + ph], [px + pw, py + ph]]
  for (let i = 0; i < 4; i++) {
    if (Math.hypot(lx - cs[i][0], ly - cs[i][1]) <= 10) return i
  }
  return -1
}

function selectedImg(): ImgEl | null {
  const pg = curPage.value
  if (!pg || !selImg.value) return null
  return pg.images.find((m) => m.id === selImg.value) || null
}

function clampImg(img: ImgEl) {
  const { pw, ph } = imgPixel(img)
  const hFrac = ph / cssH
  img.x = Math.min(Math.max(0, img.x), Math.max(0, 1 - img.w))
  img.y = Math.min(Math.max(0, img.y), Math.max(0, 1 - hFrac))
}

/* ---------------- 图片：插入 / 删除 / 拖拽 ---------------- */

function insertImageData(src: string, naturalW: number, naturalH: number) {
  const pg = curPage.value
  if (!pg || naturalW <= 0) return
  const aspect = pg.page.w / pg.page.h
  const r = naturalH / naturalW
  const w = Math.max(0.15, Math.min(0.9, 0.85 / (aspect * r)))
  pushHist()
  const img: ImgEl = { id: 'img' + Date.now() + Math.floor(Math.random() * 999), x: (1 - w) / 2, y: 0, w, r, src }
  img.y = Math.max(0, (1 - (img.w * cssW * img.r) / cssH) / 2)
  pg.images.push(img)
  selImg.value = img.id
  ensurePageImgs(curIdx.value)
  pushPayload()
  if (LAYERED) {
    renderer?.paintStatic(curIdx.value)
    scheduleOverlay()
  } else {
    scheduleRedraw()
  }
}

function insertImageFile(file: File, yOff = 0, at?: { fx: number; fy: number }) {
  if (!file || !/^image\//.test(file.type)) return
  const reader = new FileReader()
  reader.onload = () => {
    const src = String(reader.result)
    const el = new Image()
    el.onload = () => {
      const pg = curPage.value
      if (!pg) return
      const aspect = pg.page.w / pg.page.h
      const r = el.naturalHeight / el.naturalWidth
      const w = Math.max(0.15, Math.min(0.9, 0.85 / (aspect * r)))
      pushHist()
      const img: ImgEl = { id: 'img' + Date.now() + Math.floor(Math.random() * 999), x: (1 - w) / 2, y: 0, w, r, src }
      const imgH = (img.w * cssW * img.r) / cssH
      if (at) img.x = Math.min(Math.max(0, at.fx - img.w / 2), Math.max(0, 1 - img.w)) // 图片以落点为中心
      const baseY = at ? at.fy - imgH / 2 : (1 - imgH) / 2
      img.y = Math.min(Math.max(0, baseY + yOff), Math.max(0, 1 - imgH))
      pg.images.push(img)
      selImg.value = img.id
      ensurePageImgs(curIdx.value)
      pushPayload()
      if (LAYERED) {
        renderer?.paintStatic(curIdx.value)
        scheduleOverlay()
      } else {
        scheduleRedraw()
      }
    }
    el.src = src
  }
  reader.readAsDataURL(file)
}

function onFilePick(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (files) {
    let yOff = 0
    for (const f of Array.from(files)) {
      insertImageFile(f, yOff)
      yOff += 0.05
    }
  }
  ;(e.target as HTMLInputElement).value = ''
}

function deleteSelImage() {
  const pg = curPage.value
  if (!pg || !selImg.value) return
  const im = pg.images.find((m) => m.id === selImg.value)
  if (!im) return
  pushHist()
  pg.images = pg.images.filter((m) => m.id !== selImg.value)
  selImg.value = null
  pushPayload()
  if (LAYERED) {
    renderer?.paintStatic(curIdx.value)
    scheduleOverlay()
  } else {
    scheduleRedraw()
  }
}

function startImgOp(lx: number, ly: number, pointerId: number): boolean {
  const pg = curPage.value
  if (!pg) return false
  const hi = handleHitAt(lx, ly)
  if (hi >= 0) {
    const im = selectedImg()!
    imgOp = { id: im.id, mode: 'resize', hi, sx: lx, sy: ly, ox: im.x, oy: im.y, ow: im.w }
    try { captureEl()?.setPointerCapture(pointerId) } catch { /* ignore */ }
    if (LAYERED) {
      dragExcludeId = im.id
      renderer?.paintStatic(curIdx.value, im.id)
      scheduleOverlay()
    } else {
      scheduleRedraw()
    }
    return true
  }
  const id = imgHitAt(lx, ly)
  if (id) {
    const im = pg.images.find((m) => m.id === id)!
    selImg.value = id
    imgOp = { id, mode: 'move', hi: -1, sx: lx, sy: ly, ox: im.x, oy: im.y, ow: im.w }
    try { captureEl()?.setPointerCapture(pointerId) } catch { /* ignore */ }
    if (LAYERED) {
      dragExcludeId = id
      renderer?.paintStatic(curIdx.value, id)
      scheduleOverlay()
    } else {
      scheduleRedraw()
    }
    return true
  }
  return false
}

function moveImgOp(lx: number, ly: number) {
  const pg = curPage.value
  if (!pg || !imgOp) return
  const im = pg.images.find((m) => m.id === imgOp!.id)
  if (!im) { imgOp = null; return }
  const op = imgOp
  if (op.mode === 'move') {
    im.x = op.ox + (lx - op.sx) / cssW
    im.y = op.oy + (ly - op.sy) / cssH
  } else {
    // 等比缩放：以对角为锚点，从起始像素矩形推算
    const r = im.r
    const x0px = op.ox * cssW
    const y0px = op.oy * cssH
    const w0px = op.ow * cssW
    const h0px = w0px * r
    const left = op.hi === 0 || op.hi === 2
    const top = op.hi === 0 || op.hi === 1
    const dx = lx - op.sx
    let wpx = left ? w0px - dx : w0px + dx
    wpx = Math.min(Math.max(24, wpx), cssW * 0.98)
    const hpx = wpx * r
    const xpx = left ? x0px + (w0px - wpx) : x0px
    const ypx = top ? y0px + (h0px - hpx) : y0px
    im.x = Math.min(Math.max(0, xpx / cssW), Math.max(0, 1 - wpx / cssW))
    im.w = wpx / cssW
    im.y = Math.min(Math.max(0, ypx / cssH), Math.max(0, 1 - hpx / cssH))
  }
  clampImg(im)
  if (LAYERED) scheduleOverlay()
  else scheduleRedraw()
}

/* ---------------- 主渲染 ---------------- */

/** 渲染第 i 页到它的画布；live=true 时叠加书写中的实时笔迹 / 橡皮指示（仅活动页） */
function paint(i: number, live = false) {
  const canvas = sheetEls[i]
  const pg = pages.value[i]
  if (!canvas || !pg) return
  const w = sheetW.value
  const h = pageCssH(i)
  if (w <= 0 || h <= 0) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
  const pw = Math.round(w * dpr)
  const ph = Math.round(h * dpr)
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw
    canvas.height = ph
  }
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  const ctx2d = canvas.getContext('2d')
  if (!ctx2d) return
  // 绘制函数以 cssW/cssH 为「当前页像素尺寸」：本页渲染期间临时切换
  cssW = w
  cssH = h
  ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx2d.clearRect(0, 0, w, h)
  drawPaper(ctx2d, w, h, pg.page.paper)
  for (const im of pg.images) {
    drawImg(ctx2d, im)
    if (live && !props.readonly && im.id === selImg.value) {
      const el = imgCache.get(im.src)
      if (el && el.complete) drawImgBox(ctx2d, im, true)
    }
  }
  for (const s of pg.strokes) drawOne(s, false)
  if (live && cur.value.length > 1 && (tool.value === 'pen' || tool.value === 'hl')) {
    const liveStroke: Stroke = {
      tool: tool.value, color: color.value, tip: tool.value === 'pen' ? tipKey.value : undefined,
      sp: tool.value === 'pen' && lastKind !== 'pen',
      w: widthFrac(), pts: cur.value.map((p) => ({ x: p.x / w, y: p.y / h, p: p.p })),
    }
    drawOne(liveStroke, true)
  }
  if (live && tool.value === 'eraser' && hoverPos && !eraseBusy) {
    ctx2d.strokeStyle = 'rgba(220,38,38,.55)'
    ctx2d.lineWidth = 1.5
    ctx2d.beginPath()
    ctx2d.arc(hoverPos.x, hoverPos.y, eraserR(), 0, Math.PI * 2)
    ctx2d.stroke()
  }
  // 绘制期间 cssW/cssH 为本页尺寸，绘制结束统一恢复为「活动页尺寸」
  syncAmbient()
}

/** 维持全局 cssW/cssH = 活动页像素尺寸（事件处理与笔迹归一化依赖它） */
function syncAmbient() {
  cssW = sheetW.value
  cssH = pageCssH(curIdx.value)
}

function redraw() {
  paint(curIdx.value, true)
}

function widthFrac(): number {
  return [0.0016, 0.0026, 0.0042][widthIdx.value] ?? 0.0026
}

function eraserR(): number {
  return ERASER_R[widthIdx.value] ?? ERASER_R[1]
}

function scheduleRedraw() {
  if (rafId) return
  rafId = requestAnimationFrame(() => { rafId = 0; if (LAYERED) liveFrame(); else redraw() })
}

/* ---------------- 分层渲染（LAYERED）：层管理 / 湿墨 / 覆盖层 ---------------- */

/** 分层画布挂载：存元素；static+ink 齐备时向 renderer 注册该页
 *  （重新注册会重置 runtime，调用方需随后 resize+paint 重建） */
function setLayerEl(i: number, layer: 'static' | 'ink' | 'live', el: HTMLCanvasElement | null) {
  if (!layerEls[i]) layerEls[i] = { static: null, ink: null, live: null }
  layerEls[i][layer] = el
  const s = layerEls[i]
  if (s.static && s.ink) renderer?.registerPage(i, { static: s.static, ink: s.ink, live: s.live })
}

/** 全部页重新注册（页增删后；新页的 ref 回调通常已注册，这里兜底） */
function reRegisterAll() {
  for (let i = 0; i < pages.value.length; i++) {
    const s = layerEls[i]
    if (s && s.static && s.ink) renderer?.registerPage(i, { static: s.static, ink: s.ink, live: s.live })
  }
}

/** 湿墨层 DPR 上限（活动页档位） */
function liveDpr(): number {
  return Math.min(window.devicePixelRatio || 1, DPR_ACTIVE)
}

/** 命中判定用元素（LAYERED 用 static 层；否则旧单画布） */
function hitEl(i: number): HTMLCanvasElement | null {
  return LAYERED ? (layerEls[i]?.static ?? null) : (sheetEls[i] ?? null)
}

/** setPointerCapture 目标（LAYERED 用长卷容器；否则活动页画布） */
function captureEl(): Element | null {
  return LAYERED ? (scrollEl.value ?? null) : (cv.value ?? null)
}

/** 该页三层全量重建：定级 → resize → 画。
 *  注意 setActivePage 内部可能 resize 并清空层（renderer 契约：调用后调用方必须重渲染），
 *  因此必须放在 paint 之前 */
function refreshPageFull(i: number) {
  if (!renderer) return
  if (i === curIdx.value) renderer.setActivePage(i)
  renderer.resizePage(i, sheetW.value, pageCssH(i))
  renderer.paintStatic(i)
  renderer.paintInk(i)
}

/** 重建可见页 backing（活动页优先）。
 *  matchSize 命中只避免重复分配 backing；backing 有效与否都要重画两层
 *  （resizePage / setActivePage 的清层副作用）。release() 只置 1×1 backing 不改
 *  css 尺寸，故 matchSize 命中不代表 backing 可用，需要时重新 resizePage */
function rebuildVisibleBacking() {
  if (!renderer) return
  renderer.setActiveIndex(curIdx.value)
  const order = [curIdx.value, ...visibleIdx().filter((x) => x !== curIdx.value)]
  for (const i of order) {
    if (i === curIdx.value) renderer.setActivePage(i)
    if (!renderer.matchSize(i, sheetW.value, pageCssH(i))) renderer.resizePage(i, sheetW.value, pageCssH(i))
    renderer.paintStatic(i)
    renderer.paintInk(i)
  }
  perf?.noteBackings(renderer.backingEstimate())
}

/** 防抖 backing 重建：手势/滚轮高频缩放期间只改 CSS，结束后再重建 */
function scheduleBackingRebuild(delay = 150) {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => {
    resizeTimer = 0
    rebuildVisibleBacking()
  }, delay)
}

/** 一帧湿墨（scheduleRedraw 的 LAYERED 高频路径；LiveInkRenderer 内部每帧至多一次 getStroke） */
function liveFrame() {
  const m = liveInk.flushFrame(pages.value[curIdx.value]?.strokes.length ?? 0, lastInputTs)
  if (m) perf?.noteFrame(m)
}

function scheduleOverlay() {
  if (overlayRaf) return
  overlayRaf = requestAnimationFrame(() => {
    overlayRaf = 0
    drawLiveOverlay()
  })
}

/** 覆盖层（LAYERED）：图片拖拽/缩放预览 → 橡皮悬停圈 → 图片选中框。
 *  drawing.value 为 true 时直接返回（绝不能清湿墨） */
function drawLiveOverlay() {
  if (drawing.value) return
  const i = curIdx.value
  const canvas = layerEls[i]?.live
  const pg = pages.value[i]
  const w = sheetW.value
  const h = pageCssH(i)
  if (!canvas || !pg || w <= 0 || h <= 0) return
  const ctx2d = canvas.getContext('2d')
  if (!ctx2d) return
  const dpr = liveDpr()
  const bw = Math.round(w * dpr)
  const bh = Math.round(h * dpr)
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw
    canvas.height = bh
  }
  ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx2d.clearRect(0, 0, w, h)
  if (imgOp) {
    const im = pg.images.find((m) => m.id === imgOp!.id)
    if (im) {
      const el = imgCache.get(im.src)
      if (el && el.complete && el.naturalWidth > 0) {
        const iw = im.w * w
        ctx2d.drawImage(el, im.x * w, im.y * h, iw, iw * im.r)
      }
      wbDrawImgBox(ctx2d, im, w, h, true)
    }
    return
  }
  if (tool.value === 'eraser' && hoverPos && !eraseBusy) {
    drawEraserRing(canvas, dpr, hoverPos.x, hoverPos.y, eraserR())
    return
  }
  if (tool.value === 'select' && selImg.value) {
    const im = pg.images.find((m) => m.id === selImg.value)
    if (im) wbDrawImgBox(ctx2d, im, w, h, true)
  }
}

/** 打断当前书写手势（双指落下 / 触控笔落下时清触摸笔迹） */
function abortInkGesture() {
  if (!drawing.value) return
  drawing.value = false
  cur.value = []
  if (LAYERED) {
    buffer.reset()
    liveInk.clearAll()
    liveInk.end()
  }
  scheduleRedraw()
}

/** LAYERED 落笔：StrokeBuffer 起笔 + 湿墨层 begin（backing 与 CSS 尺寸不一致先重建） */
function beginInkStroke(p: { x: number; y: number }, pressure: number, kind: string) {
  if (!LAYERED || !renderer) return
  const i = curIdx.value
  const w = sheetW.value
  const h = pageCssH(i)
  const pg = pages.value[i]
  if (!pg || !layerEls[i]?.live) return
  // setActivePage 可能内部 resize 并清空层（renderer 契约）→ 其后两层必须重画
  renderer.setActivePage(i)
  if (!renderer.matchSize(i, w, h)) renderer.resizePage(i, w, h)
  renderer.paintStatic(i)
  renderer.paintInk(i)
  lastKind = kind
  buffer.begin(p.x / w, p.y / h, pressure)
  liveInk.begin(
    { tool: tool.value, color: color.value, w: widthFrac(), tip: tool.value === 'pen' ? tipKey.value : undefined, sp: tool.value === 'pen' && lastKind !== 'pen' },
    pg as any, layerEls[i].live, w, h, liveDpr(),
  )
  lastInputTs = performance.now()
  perf?.noteInput(lastInputTs)
  drawing.value = true
}

/** LAYERED 移动加点：归一化采样进 buffer + 湿墨层（<1px 去抖） */
function pushInkPoint(p: { x: number; y: number }, pressure: number) {
  if (!LAYERED) return
  const i = curIdx.value
  const w = sheetW.value
  const h = pageCssH(i)
  const last = buffer.last()
  if (last && Math.hypot(p.x - last.x * w, p.y - last.y * h) < 1) return
  const nx = p.x / w
  const ny = p.y / h
  buffer.push(nx, ny, pressure)
  liveInk.push(nx, ny, pressure)
  lastInputTs = performance.now()
  perf?.noteInput(lastInputTs)
  followPen(p.y)
  scheduleRedraw()
}

/** LAYERED 落笔提交：构建带 id 的 v3 笔迹 → 增量提交 ink 层 → 清湿墨层 */
function commitInkStroke() {
  drawing.value = false
  const pg = curPage.value
  if (!pg || buffer.length < 2) {
    buffer.reset()
    liveInk.clearAll()
    liveInk.end()
    return
  }
  pushHist()
  const stroke: any = {
    id: newStrokeId(),
    tool: tool.value,
    color: color.value,
    tip: tool.value === 'pen' ? tipKey.value : undefined,
    sp: tool.value === 'pen' && lastKind !== 'pen',
    w: widthFrac(),
    pts: buffer.toSamples().map((s) => ({ ...s, x: Math.round(s.x * 10000) / 10000, y: Math.round(s.y * 10000) / 10000, p: Math.round(s.p * 100) / 100 })),
  }
  buffer.reset()
  pg.strokes.push(stroke)
  pushPayload()
  renderer?.commitStroke(curIdx.value, stroke)
  liveInk.clearAll()
  liveInk.end()
}

/** 开发态测试钩子：确定性生成 n 条随机游走笔迹（性能基线测量用；仅 DEV 生效） */
function fillDevStrokes(n: number, pageIdx = 0) {
  if (!import.meta.env.DEV) return
  const pg = pages.value[pageIdx]
  if (!pg) return
  let seed = 42
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0
    return seed / 4294967296
  }
  for (let k = 0; k < n; k++) {
    const count = 40 + Math.floor(rnd() * 81)
    const pts: { x: number; y: number; p: number }[] = []
    let x = 0.03 + rnd() * 0.94
    let y = 0.03 + rnd() * 0.94
    const p0 = Math.round((0.4 + rnd() * 0.6) * 100) / 100
    for (let j = 0; j < count; j++) {
      x = Math.min(0.97, Math.max(0.03, x + (rnd() - 0.5) * 0.08))
      y = Math.min(0.97, Math.max(0.03, y + (rnd() - 0.5) * 0.08))
      pts.push({ x: Math.round(x * 10000) / 10000, y: Math.round(y * 10000) / 10000, p: p0 })
    }
    pg.strokes.push({
      id: newStrokeId(),
      tool: 'pen',
      color: PEN_COLORS[k % PEN_COLORS.length],
      w: 0.0026,
      tip: 'pen',
      pts,
    } as any)
  }
  pushPayload()
  if (LAYERED) {
    renderer?.invalidatePage(pageIdx)
    renderer?.paintInk(pageIdx)
  } else {
    paint(pageIdx, true)
  }
}

/* ---------------- 指针：坐标与事件分派 ---------------- */

/** 指针 y 落在第几页（长卷内按「页顶偏移 + 页高」判定，不逐页读布局） */
function sheetAt(clientY: number): number {
  const wrap = scrollEl.value
  if (!wrap) return curIdx.value
  const y = clientY - wrap.getBoundingClientRect().top + wrap.scrollTop
  for (let i = 0; i < pages.value.length; i++) {
    const top = sheetTops[i] ?? 0
    if (y < top + pageCssH(i) + SHEET_GAP / 2) return Math.max(0, i)
  }
  return Math.max(0, pages.value.length - 1)
}

/** 指针 → 页内坐标；activate=true（按下时）把命中页设为活动页 —— 点哪页就在哪页写 */
function canvasLocal(clientX: number, clientY: number, activate = false): { x: number; y: number } {
  const idx = sheetAt(clientY)
  if (activate && idx !== curIdx.value && !drawing.value && !eraseBusy) {
    goPage(idx, { scroll: false })
  }
  const el = hitEl(curIdx.value) ?? hitEl(idx)
  if (!el) return { x: 0, y: 0 }
  const r = el.getBoundingClientRect()
  return { x: clientX - r.left, y: clientY - r.top }
}

function toLocal(e: PointerEvent): { x: number; y: number } {
  return canvasLocal(e.clientX, e.clientY)
}

function onDown(e: PointerEvent) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  // 所有直接触摸手势均由白板接管：这样浏览器不会把触控笔书写取消为原生滚动。
  if (e.pointerType === 'touch') {
    onTouchDown(e)
    return
  }
  if (props.readonly) return

  if (e.pointerType === 'pen') {
    e.preventDefault()
    // 触控笔优先：清掉仍在屏幕上的手指/掌触状态，后续 touch 事件在落笔期间会被忽略。
    if (inkPointerType === 'touch') {
      if (drawing.value) {
        abortInkGesture()
      } else if (eraseBusy) {
        endEraseGesture()
      }
      inkPointerId = null
      inkPointerType = null
    }
    ptrs.clear()
    touchPan = null
    twoFinger = null
  }

  const p = canvasLocal(e.clientX, e.clientY, true)
  // 选择工具：优先处理图片（命中即进入拖拽/缩放）
  if (tool.value === 'select') {
    if (startImgOp(p.x, p.y, e.pointerId)) return
    selImg.value = null
    scheduleRedraw()
    return
  }
  if (inkPointerId !== null && inkPointerId !== e.pointerId) return
  lastKind = e.pointerType
  inkPointerId = e.pointerId
  inkPointerType = e.pointerType || 'mouse'
  try { scrollEl.value?.setPointerCapture(e.pointerId) } catch { /* ignore */ }
  if (tool.value === 'eraser') {
    beginEraseGesture(p)
    return
  }
  if (LAYERED) {
    hoverPos = null
    beginInkStroke(p, e.pressure && e.pointerType === 'pen' ? e.pressure : 0.5, e.pointerType || 'mouse')
    return
  }
  drawing.value = true
  cur.value = [{ x: p.x, y: p.y, p: e.pressure && e.pointerType === 'pen' ? e.pressure : 0.5 }]
  hoverPos = null
}

/** 手指：默认单指平移、双指平移缩放；开启「手指书写」后单指书写 */
function onTouchDown(e: PointerEvent) {
  const wrap = scrollEl.value
  if (!wrap) return
  e.preventDefault()
  // 触控笔落下期间的触摸通常是手掌，不能让它打断笔迹。
  if (inkPointerType === 'pen') return
  const p = { x: e.clientX, y: e.clientY }
  ptrs.set(e.pointerId, p)
  try { wrap.setPointerCapture(e.pointerId) } catch { /* ignore */ }

  // 双指：捏合缩放 + 平移滚动。若第一指正在书写，则放弃未完成笔迹。
  if (ptrs.size >= 2) {
    const list = [...ptrs.values()]
    twoFinger = {
      d: Math.max(1, Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y)),
      y: avgTouchY(),
      scale: sheetScale.value,
    }
    touchPan = {
      x: list.reduce((a, b) => a + b.x, 0) / list.length,
      y: avgTouchY(),
    }
    if (inkPointerType === 'touch' && drawing.value) {
      abortInkGesture()
    } else if (inkPointerType === 'touch' && eraseBusy) {
      endEraseGesture()
    }
    if (inkPointerType === 'touch') {
      inkPointerId = null
      inkPointerType = null
    }
    return
  }

  // 默认单指平移；只读、选择工具也始终平移。
  const wantInk = allowTouch.value && ptrs.size === 1 && tool.value !== 'select'
  if (props.readonly || !wantInk) {
    touchPan = p
    return
  }
  if (drawing.value || eraseBusy || inkPointerId !== null) return
  const lp = canvasLocal(e.clientX, e.clientY, true)
  lastKind = 'touch'
  inkPointerId = e.pointerId
  inkPointerType = 'touch'
  if (tool.value === 'eraser') {
    beginEraseGesture(lp)
    return
  }
  if (LAYERED) {
    hoverPos = null
    beginInkStroke(lp, 0.5, 'touch')
    return
  }
  drawing.value = true
  cur.value = [{ x: lp.x, y: lp.y, p: 0.5 }]
  hoverPos = null
}

/** 双指平均 y（用于双指滚动） */
function avgTouchY(): number {
  const list = [...ptrs.values()]
  return list.reduce((a, b) => a + b.y, 0) / Math.max(1, list.length)
}

function onMove(e: PointerEvent) {
  if (e.pointerType === 'touch') {
    onTouchMove(e)
    return
  }
  if (props.readonly) return
  if (inkPointerId !== null && e.pointerId !== inkPointerId) return
  const lp = canvasLocal(e.clientX, e.clientY)
  if (imgOp) {
    moveImgOp(lp.x, lp.y)
    return
  }
  const p = toLocal(e)
  if (tool.value === 'eraser') {
    if (eraseBusy && lastErase) {
      applyEraseSegment(lastErase, p)
      lastErase = p
    } else {
      hoverPos = p
      if (LAYERED) scheduleOverlay()
      else redraw()
    }
    return
  }
  if (!drawing.value) return
  if (LAYERED) {
    pushInkPoint(p, e.pressure && e.pointerType === 'pen' ? e.pressure : 0.5)
    return
  }
  const pts = cur.value
  const last = pts[pts.length - 1]
  const d = Math.hypot(p.x - last.x, p.y - last.y)
  if (d < 1) return
  pts.push({ x: p.x, y: p.y, p: e.pressure && e.pointerType === 'pen' ? e.pressure : 0.5 })
  followPen(p.y)
  scheduleRedraw()
}

function onTouchMove(e: PointerEvent) {
  if (!ptrs.has(e.pointerId)) return
  e.preventDefault()
  const p = { x: e.clientX, y: e.clientY }
  ptrs.set(e.pointerId, p)

  // 双指：捏合缩放 + 平移滚动
  if (ptrs.size >= 2 && twoFinger) {
    const list = [...ptrs.values()]
    const d = Math.max(1, Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y))
    const x = list.reduce((a, b) => a + b.x, 0) / list.length
    const y = list.reduce((a, b) => a + b.y, 0) / list.length
    const next = Math.min(3, Math.max(0.4, twoFinger.scale * (d / twoFinger.d)))
    if (Math.abs(next - sheetScale.value) > 0.005) {
      const wrap = scrollEl.value
      const prev = sheetScale.value
      // 以双指中心为锚点：缩放前后该处内容保持在原位，避免视图乱跳
      let anchor: { cy: number; content: number; top: number } | null = null
      if (wrap) {
        const wr = wrap.getBoundingClientRect()
        anchor = { cy: y, content: wrap.scrollTop + (y - wr.top), top: wr.top }
      }
      sheetScale.value = next
      layout(true) // 手势中只重绘活动页，保证跟手
      if (wrap && anchor) {
        wrap.scrollTop = Math.max(0, anchor.content * (next / prev) - (anchor.cy - anchor.top))
      }
      gestureZoomed = true
    }
    if (touchPan) {
      const wrap = scrollEl.value
      if (wrap) {
        wrap.scrollLeft -= (x - touchPan.x)
        wrap.scrollTop -= (y - touchPan.y)
      }
      touchPan.x = x
      touchPan.y = y
    }
    return
  }

  if (inkPointerId === e.pointerId && inkPointerType === 'touch' && (drawing.value || eraseBusy) && ptrs.size === 1) {
    const lp = canvasLocal(e.clientX, e.clientY)
    if (tool.value === 'eraser' && eraseBusy && lastErase) {
      applyEraseSegment(lastErase, lp)
      lastErase = lp
    } else if (drawing.value && tool.value !== 'eraser' && tool.value !== 'select') {
      if (LAYERED) {
        pushInkPoint(lp, 0.5)
      } else {
        const pts = cur.value
        const last = pts[pts.length - 1]
        if (Math.hypot(lp.x - last.x, lp.y - last.y) >= 1) {
          pts.push({ x: lp.x, y: lp.y, p: 0.5 })
          scheduleRedraw()
        }
      }
    }
    return
  }
  // touch-action:none 下由白板实现单指双向平移，避免浏览器抢走触控笔事件。
  if (ptrs.size === 1 && touchPan) {
    const wrap = scrollEl.value
    if (wrap) {
      wrap.scrollLeft -= (p.x - touchPan.x)
      wrap.scrollTop -= (p.y - touchPan.y)
    }
    touchPan = p
  }
}

function onUp(e: PointerEvent) {
  // 触摸先处理（只读页也要正确收尾双指手势）
  if (e.pointerType === 'touch') {
    if (!ptrs.has(e.pointerId)) return
    e.preventDefault()
    const wasInk = inkPointerId === e.pointerId && inkPointerType === 'touch'
    ptrs.delete(e.pointerId)
    try { scrollEl.value?.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
    if (wasInk) {
      if (drawing.value) finishInkStroke()
      else if (eraseBusy) endEraseGesture()
      inkPointerId = null
      inkPointerType = null
    }
    if (ptrs.size === 0) {
      touchPan = null
      twoFinger = null
      if (gestureZoomed) {
        gestureZoomed = false
        if (LAYERED) rebuildVisibleBacking() // 手势结束：按最终 CSS 尺寸立即重建 backing
        else layout() // 手势结束：全量重绘可视页
      }
    } else if (ptrs.size === 1) {
      twoFinger = null
      const rest = [...ptrs.values()][0]
      touchPan = { x: rest.x, y: rest.y }
    }
    return
  }
  if (props.readonly) return
  if (inkPointerId !== null && e.pointerId !== inkPointerId) return
  // 图片操作收尾
  if (imgOp) {
    imgOp = null
    pushPayload()
    if (LAYERED) {
      dragExcludeId = null
      renderer?.paintStatic(curIdx.value)
      scheduleOverlay()
    }
    return
  }
  if (tool.value === 'eraser') {
    if (eraseBusy) endEraseGesture()
    else {
      hoverPos = null
      if (LAYERED) scheduleOverlay()
      else redraw()
    }
  } else if (drawing.value) {
    finishInkStroke()
  }
  if (inkPointerId === e.pointerId) {
    inkPointerId = null
    inkPointerType = null
    try { scrollEl.value?.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
  }
}

function finishInkStroke() {
  if (LAYERED) {
    commitInkStroke()
    return
  }
  drawing.value = false
  const pts = cur.value
  cur.value = []
  if (pts.length < 2) return
  const pg = curPage.value
  if (!pg) return
  pushHist()
  pg.strokes.push({
    tool: tool.value as Tool,
    color: color.value,
    tip: tool.value === 'pen' ? tipKey.value : undefined,
    sp: tool.value === 'pen' && lastKind !== 'pen',
    w: widthFrac(),
    pts: pts.map((p) => ({ x: Math.round(p.x / cssW * 10000) / 10000, y: Math.round(p.y / cssH * 10000) / 10000, p: Math.round(p.p * 100) / 100 })),
  })
  pushPayload()
  scheduleRedraw()
}

/** 笔尖接近长卷可视底部时自动上滚（连续书写无需手动翻页） */
function followPen(localY: number) {
  const wrap = scrollEl.value
  const el = hitEl(curIdx.value)
  if (!wrap || !el) return
  const r = el.getBoundingClientRect()
  const wr = wrap.getBoundingClientRect()
  const gap = wr.bottom - (r.top + localY)
  if (gap < 90) wrap.scrollTop += (90 - gap)
}

/* ---------------- 橡皮 ---------------- */

function beginEraseGesture(p: { x: number; y: number }) {
  eraseBusy = true
  eraseChanged = false
  lastErase = p
  pushHist()
  hoverPos = null
  if (tool.value === 'eraser') applyEraseSegment(p, p)
}

function cancelEraseGesture(pop: boolean) {
  eraseBusy = false
  eraseChanged = false
  lastErase = null
  if (pop) undoStack.pop()
}

function endEraseGesture() {
  eraseBusy = false
  lastErase = null
  hoverPos = null
  if (eraseChanged) {
    pushPayload()
    if (LAYERED) scheduleOverlay()
    else redraw()
  } else {
    undoStack.pop() // 没擦到任何东西：撤销快照
  }
}

function applyEraseSegment(a: { x: number; y: number }, b: { x: number; y: number }) {
  const pg = curPage.value
  if (!pg) return
  const r = eraserR()
  let next: Stroke[]
  if (eraserMode.value === 'whole') {
    next = pg.strokes.filter((s) => !strokeHit(s, a, b, r))
  } else {
    next = []
    for (const s of pg.strokes) {
      next.push(...cutStroke(s, a, b, r))
    }
  }
  const changed = next.length !== pg.strokes.length || totalPts(next) !== totalPts(pg.strokes)
  if (!changed) return
  pg.strokes = next
  eraseChanged = true
  if (LAYERED) {
    renderer?.invalidatePage(curIdx.value)
    renderer?.paintInk(curIdx.value)
  } else {
    scheduleRedraw()
  }
}

function totalPts(list: Stroke[]): number {
  let n = 0
  for (const s of list) n += s.pts.length
  return n
}

function ptDistToSeg(p: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }): number {
  const dx = b.x - a.x, dy = b.y - a.y
  const L2 = dx * dx + dy * dy
  if (L2 === 0) return Math.hypot(p.x - a.x, p.y - a.y)
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

function segsIntersect(ax: number, ay: number, bx: number, by: number,
  cx: number, cy: number, dx: number, dy: number): boolean {
  const d1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  const d2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
  const d3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
  const d4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
}

function segDistToSeg(ax: number, ay: number, bx: number, by: number,
  cx: number, cy: number, dx: number, dy: number): number {
  if (segsIntersect(ax, ay, bx, by, cx, cy, dx, dy)) return 0
  const pa = { x: ax, y: ay }, pb = { x: bx, y: by }
  const pc = { x: cx, y: cy }, pd = { x: dx, y: dy }
  return Math.min(
    ptDistToSeg(pc, pa, pb), ptDistToSeg(pd, pa, pb),
    ptDistToSeg(pa, pc, pd), ptDistToSeg(pb, pc, pd),
  )
}

function strokeHit(s: Stroke, a: { x: number; y: number }, b: { x: number; y: number }, r: number): boolean {
  const ax = a.x, ay = a.y, bx = b.x, by = b.y
  for (let i = 1; i < s.pts.length; i++) {
    const p1 = s.pts[i - 1], p2 = s.pts[i]
    if (segDistToSeg(p1.x * cssW, p1.y * cssH, p2.x * cssW, p2.y * cssH, ax, ay, bx, by) < r) return true
  }
  return false
}

function cutStroke(s: Stroke, a: { x: number; y: number }, b: { x: number; y: number }, r: number): Stroke[] {
  const n = s.pts.length
  if (n < 2) return []
  const ax = a.x, ay = a.y, bx = b.x, by = b.y
  const keep = new Array<boolean>(n).fill(true)
  for (let i = 0; i < n; i++) {
    const px = s.pts[i].x * cssW, py = s.pts[i].y * cssH
    if (ptDistToSeg({ x: px, y: py }, a, b) < r) keep[i] = false
  }
  for (let i = 1; i < n; i++) {
    const p1 = s.pts[i - 1], p2 = s.pts[i]
    if (segDistToSeg(p1.x * cssW, p1.y * cssH, p2.x * cssW, p2.y * cssH, ax, ay, bx, by) < r) {
      keep[i - 1] = false
      keep[i] = false
    }
  }
  if (keep.every((k) => k)) return [s]
  if (keep.every((k) => !k)) return []
  const out: Stroke[] = []
  let run: Pt[] = []
  const flush = () => {
    if (run.length >= 2) out.push({ ...s, pts: run.map((p) => ({ ...p })) })
    run = []
  }
  s.pts.forEach((pt, i) => {
    if (keep[i]) run.push(pt)
    else flush()
  })
  flush()
  return out
}

/* ---------------- 工具切换等 ---------------- */

function clearAll() {
  const pg = curPage.value
  if (!pg || (!pg.strokes.length && !pg.images.length)) return
  void ElMessageBox.confirm('确定清空本页的全部笔迹与图片？此操作不可恢复。', '清空本页', { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' })
    .then(() => {
      pushHist()
      pg.strokes = []
      pg.images = []
      selImg.value = null
      pushPayload()
      if (LAYERED) {
        renderer?.invalidatePage(curIdx.value)
        renderer?.paintStatic(curIdx.value)
        renderer?.paintInk(curIdx.value)
        scheduleOverlay()
      } else {
        scheduleRedraw()
      }
    })
    .catch(() => {})
}

function pickTool(t: Tool) {
  tool.value = t
  hoverPos = null
  if (t === 'hl' && !HL_COLORS.includes(color.value) && color.value !== customHex.value) {
    color.value = HL_COLORS[0]
  } else if (t !== 'hl' && !PEN_COLORS.includes(color.value) && color.value !== customHex.value) {
    color.value = PEN_COLORS[0]
  }
  if (t !== 'select') selImg.value = null
  if (LAYERED) scheduleOverlay()
}

function openPicker() {
  picker.value?.click()
}

function onCustom(e: Event) {
  const hex = (e.target as HTMLInputElement).value
  customHex.value = hex
  color.value = hex
}

/* ---------------- 粘贴图片 / 键盘 ---------------- */

function onPaste(e: ClipboardEvent) {
  if (props.readonly) return
  const el = e.target as HTMLElement
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
  const items = e.clipboardData?.items
  if (!items) return
  for (const it of items) {
    if (it.type.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) {
        e.preventDefault()
        insertImageFile(f)
      }
      return
    }
  }
}

/* ---------------- 拖入图片（从桌面/网页把图片拖到纸面） ---------------- */
const dragOver = ref(false)
let wbDragDepth = 0

/** 拖拽里是否含文件（白板内元素拖拽不含 Files，需要放行） */
function hasDropFiles(e: DragEvent): boolean {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')
}
function onDragEnter(e: DragEvent) {
  if (props.readonly || !hasDropFiles(e)) return
  wbDragDepth++
  dragOver.value = true
}
function onDragOver(e: DragEvent) {
  if (props.readonly || !hasDropFiles(e)) return
  e.preventDefault() // 不 preventDefault 不会触发 drop
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  dragOver.value = true
}
function onDragLeave() {
  wbDragDepth = Math.max(0, wbDragDepth - 1)
  if (!wbDragDepth) dragOver.value = false
}
/** 松开：把图片插到落点所在页、以落点为中心（多张向下错开 0.05，与「插图」按钮一致） */
function onDrop(e: DragEvent) {
  wbDragDepth = 0
  dragOver.value = false
  if (props.readonly || !hasDropFiles(e)) return
  const el = e.target as HTMLElement
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return // 输入框内不接管
  e.preventDefault()
  e.stopPropagation()
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => /^image\//.test(f.type))
  if (!files.length) {
    ElMessage.warning('仅支持图片（jpg / png / webp / gif）')
    return
  }
  // 落点 → 该页的宽高比例坐标：hitEl(命中页) 的 rect 与 canvasLocal 用的是同一基准
  const idx = sheetAt(e.clientY)
  const hit = hitEl(idx)
  const rect = hit ? hit.getBoundingClientRect() : null
  const lp = canvasLocal(e.clientX, e.clientY, true) // activate=true：点哪页就插到哪页
  const at = rect && rect.width > 0 && rect.height > 0 ? { fx: lp.x / rect.width, fy: lp.y / rect.height } : undefined
  files.forEach((f, i) => insertImageFile(f, i * 0.05, at))
}

function onKey(e: KeyboardEvent) {
  if (props.readonly) return
  const el = e.target as HTMLElement
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
  if (selImg.value && (e.key === 'Delete' || e.key === 'Backspace')) {
    e.preventDefault()
    deleteSelImage()
    return
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo() }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo() }
}

/* ---------------- 滚轮 ---------------- */

function onWheel(e: WheelEvent) {
  // 连续长卷：普通滚轮/触控板 = 原生滚动换页；仅 Ctrl/⌘ + 滚轮 = 缩放纸面宽度
  if (!(e.ctrlKey || e.metaKey)) return
  e.preventDefault()
  zoomSheets(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientY)
}

/* ---------------- 导出 PNG（当前页 / 指定页） ---------------- */

function renderPng(pageIdx?: number): string {
  // LAYERED：走 renderer 独立离屏导出（页面固有坐标 + scale，不受屏幕 DPR 定级影响）
  if (LAYERED && renderer) {
    const pg = pageIdx === undefined ? curPage.value : pages.value[pageIdx]
    if (pg) return renderer.renderPngFromCache(pg, 2)
  }
  const pg = pageIdx === undefined ? curPage.value : pages.value[pageIdx]
  if (!pg) return ''
  const s = 2
  const out = document.createElement('canvas')
  out.width = Math.round(pg.page.w * s)
  out.height = Math.round(pg.page.h * s)
  const outCtx = out.getContext('2d')!
  const saved = { w: cssW, h: cssH }
  cssW = out.width
  cssH = out.height
  outCtx.setTransform(1, 0, 0, 1, 0, 0)
  drawPaper(outCtx, cssW, cssH, pg.page.paper)
  for (const im of pg.images) drawImg(outCtx, im)
  for (const st of pg.strokes) drawOne(st, false, outCtx)
  cssW = saved.w
  cssH = saved.h
  return out.toDataURL('image/png')
}

defineExpose({ renderPng, fillDevStrokes })

/* ---------------- 生命周期 ---------------- */

onMounted(() => {
  perf = new InkPerfMonitor(import.meta.env.DEV)
  if (LAYERED) {
    renderer = new LayeredPageRenderer({
      getPages: () => pages.value as any,
      readonly: props.readonly,
      getImg: (src) => imgCache.get(src) ?? null,
      worker: USE_WORKER_INK_REBUILD,
      perf,
    })
  }
  loadPayload(props.modelValue)
  window.addEventListener('resize', layout)
  window.addEventListener('keydown', onKey)
  window.addEventListener('paste', onPaste)
  scrollEl.value?.addEventListener('wheel', onWheel, { passive: false })
})

onBeforeUnmount(() => {
  perf?.dispose()
  renderer?.dispose()
  if (resizeTimer) clearTimeout(resizeTimer)
  if (overlayRaf) cancelAnimationFrame(overlayRaf)
  if (rafId) cancelAnimationFrame(rafId)
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  io?.disconnect()
  io = null
  window.removeEventListener('resize', layout)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('paste', onPaste)
  scrollEl.value?.removeEventListener('wheel', onWheel)
})
</script>

<style scoped>
.wb { display: flex; gap: 10px; align-items: stretch; min-width: 0; }
.wb.readonly { display: block; }

/* ---------- 左侧竖排工具栏 ---------- */
.wb-rail {
  flex: none; width: 92px; max-height: calc(100vh - 210px); overflow-y: auto;
  display: flex; flex-direction: column; gap: 6px;
  padding: 10px 8px; border-radius: 14px;
  background: rgba(148, 163, 184, 0.08);
}
.rg { display: flex; flex-direction: column; gap: 4px; align-items: stretch; }
.rs { flex: none; height: 1px; margin: 2px 4px; background: rgba(148, 163, 184, 0.25); }
.gl { font-size: 11px; color: var(--txt3, #94a3b8); padding: 1px 4px 2px; letter-spacing: 1px; }
html.theme-dark .gl { color: #8b97ab; }
.rb {
  border: none; cursor: pointer; font-family: inherit; font-size: 12.5px;
  padding: 5px 4px; border-radius: 9px; color: var(--txt2, #64748b);
  background: transparent; text-align: center; line-height: 1.3;
}
html.theme-dark .rb { color: #cbd5e1; }
.rb:hover { background: rgba(167, 139, 250, 0.2); }
.rb.on { background: var(--acc-grad, linear-gradient(135deg, #8b5cf6, #6366f1)); color: #fff; font-weight: 600; }
.rb.dis { opacity: 0.35; cursor: not-allowed; }
.rb.danger { color: #dc2626; }
.rb.xs { font-size: 11px; padding: 4px 2px; }

/* 颜色 */
.sw { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px; padding: 2px; }
.dot {
  width: 100%; aspect-ratio: 1; border-radius: 8px; cursor: pointer;
  border: 2px solid transparent; box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.35);
}
.dot.on { border-color: #fff; box-shadow: 0 0 0 2px #8b5cf6; }
.dot.cus { display: grid; place-items: center; overflow: hidden; gap: 0; }
.dot.cus i { display: block; width: 100%; height: 33.3%; }
.hidden-picker { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }

/* 纸张 */
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.grid2 .rb { font-size: 11px; padding: 4px 2px; }
.grid2.sqs { margin-top: 6px; gap: 6px; padding: 0 4px; }
.pdot {
  width: 100%; aspect-ratio: 1; border-radius: 7px; cursor: pointer;
  border: 2px solid transparent; box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.4);
}
.pdot.on { border-color: #fff; box-shadow: 0 0 0 2px #8b5cf6; }

.sp { flex: 1; }
.touch-toggle {
  display: flex; align-items: center; justify-content: center; gap: 4px;
  font-size: 11px; color: var(--txt3, #94a3b8); cursor: pointer; user-select: none;
  padding: 6px 2px;
}
html.theme-dark .touch-toggle { color: #94a3b8; }
.touch-toggle input { accent-color: #8b5cf6; }

/* ---------- 纸面：连续长卷（多页垂直堆叠，原生滚动） ---------- */
.wb-stage { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; }
/* 只读页浮动缩放条（阅读页无左侧工具栏） */
.wb-zoom {
  position: absolute; right: 14px; bottom: 12px; z-index: 6;
  display: flex; align-items: center; gap: 4px; padding: 4px 6px;
  border-radius: 999px; border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 8px 24px rgba(30, 20, 80, 0.18);
}
html.theme-dark .wb-zoom { background: rgba(24, 29, 44, 0.94); }
.wb-zoom button {
  border: none; cursor: pointer; font-family: inherit; font-size: 16px; line-height: 1;
  min-width: 34px; height: 34px; border-radius: 999px; color: var(--txt1, #1e293b);
  background: rgba(148, 163, 184, 0.16);
}
.wb-zoom button:hover { background: rgba(167, 139, 250, 0.24); color: var(--acc2, #7c3aed); }
.wb-zoom .z-txt { font-size: 12px; padding: 0 10px; min-width: 0; }
.wb-zoom .z-pct {
  font-size: 12px; color: var(--txt2, #64748b); min-width: 44px; text-align: center;
  font-variant-numeric: tabular-nums;
}
.wb-flow {
  position: relative; flex: 1; min-height: 360px;
  max-height: calc(100vh - 150px);
  overflow: auto; overscroll-behavior: contain;
  /* 直接触摸全部交给 Pointer Events：笔写、单指平移、双指缩放才能可靠区分。
     鼠标滚轮和触控板滚动不受 touch-action 影响。 */
  touch-action: none;
  padding: 12px;
  border-radius: 14px; background: rgba(148, 163, 184, 0.08);
  scrollbar-width: thin;
}
/* 拖入图片提示浮层（覆盖纸面区域） */
.wb-drop {
  position: absolute; inset: 8px; z-index: 30; border-radius: 14px;
  display: grid; place-items: center; pointer-events: none;
  border: 2px dashed rgba(167, 139, 250, 0.75);
  background: rgba(167, 139, 250, 0.1);
  color: var(--txt1); font-weight: 700; font-size: 15px;
}
html.theme-dark .wb-drop { background: rgba(139, 92, 246, 0.18); color: #e6ecf7; }
.wb-flow::-webkit-scrollbar { width: 10px; height: 10px; }
.wb-flow::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.45); border-radius: 999px;
}
.wb-flow::-webkit-scrollbar-track { background: transparent; }
.wb.readonly .wb-flow {
  max-height: calc(100vh - 150px); min-height: 320px;
  background: rgba(148, 163, 184, 0.06);
}
.wb-sheet {
  position: relative; margin: 0 auto 16px;
  background: #fff; border-radius: 8px;
  box-shadow: 0 10px 34px rgba(30, 20, 80, 0.22);
}
.wb-sheet:last-child { margin-bottom: 0; }
.wb.readonly .wb-sheet { box-shadow: 0 4px 18px rgba(30, 20, 80, 0.16); }
.wb-canvas {
  display: block; border-radius: 8px;
  touch-action: none; cursor: crosshair;
}
.wb.readonly .wb-canvas { cursor: default; }
/* 分层渲染（LAYERED）：三层 canvas 绝对定位叠满 sheet，CSS 尺寸 100% 随 sheet 拉伸 */
.wb-layers { position: absolute; inset: 0; cursor: crosshair; touch-action: none; }
.wb.readonly .wb-layers { cursor: default; }
.wb-layers .wb-c { position: absolute; inset: 0; width: 100%; height: 100%; }
.wb-pageno {
  position: absolute; right: 8px; bottom: 6px; z-index: 2; pointer-events: none;
  font-size: 11px; color: #94a3b8; background: rgba(255, 255, 255, 0.78);
  border-radius: 999px; padding: 1px 7px; font-variant-numeric: tabular-nums;
}
html.theme-dark .wb-pageno { color: #cbd5e1; background: rgba(15, 23, 42, 0.6); }
.wb-hint {
  position: absolute; inset: 0; display: grid; place-items: center;
  pointer-events: none; color: #a8b3c5; font-size: 14px; letter-spacing: 1px;
  text-align: center; padding: 0 24px;
}
html.theme-dark .wb-hint { color: #7c8aa3; }
.ro-pager {
  display: inline-flex; align-items: center; gap: 10px; margin: 10px auto 0;
  padding: 5px 12px; border-radius: 999px;
  background: rgba(148, 163, 184, 0.12); font-size: 12.5px; color: var(--txt2, #64748b);
}
html.theme-dark .ro-pager { color: #cbd5e1; }
.ro-pager button {
  border: none; cursor: pointer; font-family: inherit; font-size: 12.5px;
  padding: 3px 10px; border-radius: 999px; color: var(--txt2, #64748b);
  background: rgba(148, 163, 184, 0.18);
}
html.theme-dark .ro-pager button { color: #cbd5e1; }
.ro-pager button.dis { opacity: 0.35; cursor: not-allowed; }
.wb-foot {
  display: flex; align-items: center; gap: 12px;
  font-size: 11.5px; color: var(--txt3, #94a3b8); padding: 6px 4px 0;
}
html.theme-dark .wb-foot { color: #8b97ab; }
.wb-foot .f2 { margin-left: auto; color: var(--txt2, #64748b); }
html.theme-dark .wb-foot .f2 { color: #aab6c8; }
</style>
