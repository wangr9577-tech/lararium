<template>
  <div class="reader" :class="{ focused: focusMode }">
    <!-- 顶部工具条 -->
    <div class="rtool glass">
      <div class="rg">
        <el-radio-group v-model="mode" size="small" @change="onMode">
          <el-radio-button value="scroll">连续</el-radio-button>
          <el-radio-button value="page">单页</el-radio-button>
        </el-radio-group>
        <el-button-group size="small">
          <el-button :icon="ZoomOut" @click="zoomBy(-10)" :disabled="zoomPct <= 50" />
          <span class="zoomv">{{ zoomPct }}%</span>
          <el-button :icon="ZoomIn" @click="zoomBy(10)" :disabled="zoomPct >= 200" />
        </el-button-group>
        <el-button size="small" @click="zoomFit">适配宽度</el-button>
      </div>

      <div class="rg">
        <el-tooltip content="左边英文原文，右边本地模型生成的中文译文（逐页对照）" placement="top">
          <el-radio-group v-model="viewMode" size="small">
            <el-radio-button value="single">原文</el-radio-button>
            <el-radio-button value="dual">中英对照</el-radio-button>
          </el-radio-group>
        </el-tooltip>
        <el-tag v-if="tr.state === 'running' || tr.state === 'queued'" size="small" type="warning" effect="plain">
          {{ tr.state === 'queued' ? '排队翻译中' : `翻译中 ${tr.done}/${tr.pages || '?'} 页` }}
        </el-tag>
        <el-tooltip v-else-if="tr.state === 'ready'" :content="`译文已缓存（${tr.model || '本地模型'}）· 点「重译」可强制重来`" placement="top">
          <el-tag size="small" type="success" effect="plain">译文已就绪</el-tag>
        </el-tooltip>
        <el-tooltip v-else-if="tr.state === 'failed'" :content="tr.error || '翻译失败'" placement="top">
          <el-tag size="small" type="danger" effect="plain">翻译失败</el-tag>
        </el-tooltip>
        <el-button size="small" text :loading="tr.state === 'running'" @click="startTranslate(tr.state === 'ready')">
          {{ tr.state === 'ready' ? '重译' : '翻译' }}
        </el-button>
      </div>

      <div class="rg search">
        <el-input v-model="query" size="small" clearable :disabled="searchSeeking" placeholder="全文搜索…" style="width: 150px" @keyup.enter="doSearch" @clear="clearSearch" />
        <el-button-group size="small" v-if="searchTotal">
          <el-button :disabled="searchSeeking" @click="searchNav(-1)">↑</el-button>
          <span class="zoomv">{{ searchCurrent }}/{{ searchTotal }}</span>
          <el-button :disabled="searchSeeking" @click="searchNav(1)">↓</el-button>
        </el-button-group>
        <el-popover v-if="searchHits.length" placement="bottom-start" :width="420" trigger="click">
          <template #reference><el-button size="small">搜索结果（{{ searchHits.length }}）</el-button></template>
          <div class="search-hit-list">
            <button v-for="(hit, i) in searchHits" :key="`${hit.page}-${hit.offset}`" type="button" :disabled="searchSeeking" @click="jumpSearchHit(hit)">
              <b>第 {{ hit.page }} 页 · {{ i + 1 }}</b><span>{{ hit.context }}</span>
            </button>
          </div>
        </el-popover>
      </div>

      <div class="rg">
        <el-popover placement="bottom-start" :width="320" trigger="click">
          <template #reference><el-button size="small">目录</el-button></template>
          <div class="outline-list">
            <div v-if="!outline.length" class="outline-empty">此 PDF 没有内嵌目录</div>
            <button v-for="(item, i) in outline" :key="i" :style="{ paddingLeft: `${8 + item.depth * 16}px` }" :disabled="!item.dest" @click="goOutline(item.dest)">{{ item.title }}</button>
          </div>
        </el-popover>
        <form class="page-jump" @submit.prevent="jumpToPage">
          <input v-model="pageInput" type="number" min="1" :max="total || 1" aria-label="跳转到页码" />
          <span class="pgv">/ {{ total }}</span>
          <button type="submit" class="page-go">跳转</button>
        </form>
        <el-tooltip content="根据论文文本生成带出处的摘要" placement="top"><el-button size="small" @click="paperAi?.openSummary()">AI 摘要</el-button></el-tooltip>
        <el-dropdown trigger="click" @command="onMoreCommand">
          <el-button size="small">更多 ▾</el-button>
          <template #dropdown><el-dropdown-menu><el-dropdown-item command="note">导出为笔记</el-dropdown-item><el-dropdown-item command="md">下载摘录</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
        <el-button size="small" @click="focusMode = !focusMode">{{ focusMode ? '退出专注' : '专注阅读' }}</el-button>
        <el-button v-if="!dual" size="small" @click="panelOpen = !panelOpen">{{ panelOpen ? '收起面板' : '标注/缩略图' }}</el-button>
      </div>
    </div>

    <div class="reader-body">
      <div class="panes" :class="{ dual }">
        <div class="pane" :style="dual ? { flex: `${dualWidth} 1 0%` } : undefined">
          <div v-if="dual" class="pane-head"><span>英文原文</span><label class="width-adjust">栏宽 <input v-model.number="dualWidth" type="range" min="30" max="70" step="1" aria-label="调整原文栏宽" /> {{ dualWidth }}%</label></div>
          <!-- 官方 pdf.js 视图容器 -->
          <div class="host" :class="{ pubonly: !panelOpen || dual }">
            <div ref="viewerEl" class="viewerhost"><div class="pdfViewer"></div></div>
            <div v-if="loading" class="hint">正在加载 PDF…</div>
            <div v-if="err" class="hint err">{{ err }}</div>
            <div v-if="noTextLayer && !loading" class="scan-tip">此 PDF 无文本层（可能是扫描版），无法划词 / 荧光笔标注。</div>
          </div>
        </div>

        <div v-if="dual" class="pane" :style="{ flex: `${100 - dualWidth} 1 0%` }">
          <div class="pane-head">
            <span>中文翻译</span>
            <span class="tr-meta">{{ trMeta }}</span>
          </div>
          <div class="host">
            <div ref="trViewerEl" class="viewerhost"><div class="pdfViewer"></div></div>
            <!-- 译文没好之前右栏先镜像英文原文，只有顶部一条状态带，不留白 -->
            <div v-if="tr.state !== 'ready'" class="tr-banner" :class="{ warn: tr.state === 'failed' }">
              <template v-if="tr.state === 'running'">
                <el-progress :percentage="trPercent" :stroke-width="6" :show-text="false" class="trbar" />
                <span class="btext">中文翻译生成中 · 第 {{ tr.done }}/{{ tr.pages || '?' }} 页（右侧暂显英文原文）</span>
                <el-button size="small" text :loading="tr.cancelling" @click="cancelTranslate">取消</el-button>
              </template>
              <template v-else-if="tr.state === 'queued'">
                <span class="btext">
                  {{ tr.queue_depth > 1 ? `排队等待翻译（前面还有 ${tr.queue_depth - 1} 篇）` : '马上开始翻译' }} · 右侧暂显英文原文
                </span>
                <el-button size="small" text :loading="tr.cancelling" @click="cancelTranslate">取消</el-button>
              </template>
              <template v-else-if="tr.state === 'failed'">
                <span class="btext">翻译未完成：{{ tr.error || '未知原因' }}</span>
                <el-button size="small" text type="primary" @click="startTranslate(true)">重试</el-button>
              </template>
              <template v-else>
                <span class="btext">{{ tr.ai_enabled ? '还没有中文译文' : 'AI 服务未启用（请先在「设置」里打开模型）' }}</span>
                <el-button v-if="tr.ai_enabled" size="small" text type="primary" @click="startTranslate(false)">开始翻译</el-button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧面板 -->
      <aside v-if="panelOpen && !dual" class="panel glass">
        <div class="ptabs">
          <button :class="{ on: panelTab === 'anno' }" @click="panelTab = 'anno'">标注（{{ highlights.length }}）</button>
          <button :class="{ on: panelTab === 'thumbs' }" @click="panelTab = 'thumbs'; renderThumbs()">缩略图</button>
          <button :class="{ on: panelTab === 'notes' }" @click="panelTab = 'notes'">笔记</button>
        </div>

        <div v-if="panelTab === 'anno'" class="ptab">
          <el-input v-model="hlQuery" size="small" clearable placeholder="搜索标注或备注" />
          <el-select v-model="hlColor" size="small" style="width: 100%; margin-top: 6px" placeholder="全部颜色">
            <el-option label="全部颜色" value="" />
            <el-option v-for="c in colors" :key="c" :label="colorName(c) + '色'" :value="c" />
          </el-select>
          <div class="anno-ops"><el-button size="small" text @click="clearPageHl" :disabled="!pageHl.length">清空本页</el-button></div>
          <div class="hl-list">
            <div v-for="h in sortedHl" :key="h.id" class="hl-item" :style="{ borderLeftColor: h.color }">
              <div class="hl-text">{{ h.text }}</div>
              <div v-if="h.note" class="hl-note">{{ h.note }}</div>
              <div class="hl-foot">
                <span>第 {{ h.page }} 页{{ h.colorName ? ' · ' + h.colorName : '' }}</span>
                <span class="hl-ops">
                  <el-button text size="small" @click="jumpHl(h)">定位</el-button>
                  <el-button text size="small" @click="editHl(h)">备注</el-button>
                  <el-button text size="small" type="danger" @click="delHl(h)">删</el-button>
                </span>
              </div>
            </div>
            <div v-if="!highlights.length" class="hl-empty">选中 PDF 文字，点工具条上的色块即可荧光笔标记。</div>
            <div v-else-if="!sortedHl.length" class="hl-empty">没有符合筛选条件的标注。</div>
          </div>
        </div>

        <div v-else-if="panelTab === 'thumbs'" class="ptab thumbs">
          <div class="thumb-grid">
            <div v-for="p in total" :key="p" class="th-wrap" :class="{ on: p === curPage }" @click="go(p)">
              <canvas class="th" :data-page="p" />
              <span class="th-num">{{ p }}</span>
            </div>
          </div>
        </div>
        <PaperNotes v-else :paper-id="paperId" />
      </aside>
    </div>

    <!-- 备注编辑 -->
    <el-dialog v-model="editOpen" title="标注备注" width="380px">
      <div class="edit-body">
        <div class="q">{{ pending?.text }}</div>
        <div class="ccol">
          <span class="lab">颜色</span>
          <span v-for="c in colors" :key="c" class="dot" :style="{ background: c }"
            :class="{ on: c === pending?.color }" @click="pending && (pending.color = c)" />
        </div>
        <el-input v-model="editNote" type="textarea" :rows="3" placeholder="写点想法…" />
      </div>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
        <el-button type="danger" plain @click="delHl(pending, true)">删除</el-button>
      </template>
    </el-dialog>

    <!-- 划词工具条 -->
    <div v-if="bar.show" class="selbar" :style="{ top: bar.y + 'px', left: bar.x + 'px' }" @mousedown.prevent>
      <span v-for="c in colors" :key="c" class="dot" :style="{ background: c }" :class="{ on: c === color }" @click="addHighlight(c)" />
      <span class="sep" />
      <button class="b" @click="doLookup">翻译 / 释义</button>
      <button class="b" @click="explainSelection">AI 解释</button>
      <button class="b" @click="addVocabRaw">入词本</button>
    </div>

    <div v-if="lk.show" class="lk-card glass" :style="{ top: lk.y + 'px', left: lk.x + 'px' }">
      <div class="lk-head"><b>{{ lk.text }}</b><span v-if="lk.phonetic" class="lk-ph">/{{ lk.phonetic }}/</span>
        <el-button text size="small" @click="lk.show = false">关闭</el-button></div>
      <div v-if="lk.loading" class="hint">查询中…</div>
      <template v-else>
        <div v-if="lk.meanings.length" class="lk-sec"><div v-for="(m, i) in lk.meanings" :key="i" class="lk-meaning">{{ m }}</div></div>
        <div v-if="lk.translate" class="lk-sec"><b>翻译：</b>{{ lk.translate }}</div>
        <div v-if="lk.phrases.length" class="lk-sec"><div v-for="(p, i) in lk.phrases.slice(0, 4)" :key="i" class="lk-phrase">{{ p.key }}：{{ p.value.join('；') }}</div></div>
        <div v-if="!lk.meanings.length && !lk.translate" class="hint">未查到释义，可加入生词本。</div>
        <div class="lk-ops"><el-button size="small" type="primary" @click="addVocab">加入生词本</el-button></div>
      </template>
    </div>
    <PaperAiSummary ref="paperAi" :paper-id="paperId" :title="title" @jump="go" />
  </div>
</template>

<script setup lang="ts">
import { clientState } from '../api/clientState'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { EventBus, PDFViewer, SimpleLinkService, PDFLinkService, PDFFindController, ScrollMode } from 'pdfjs-dist/web/pdf_viewer.mjs'
import 'pdfjs-dist/web/pdf_viewer.css'
import { http } from '../api/client'
import PaperNotes from './PaperNotes.vue'
import PaperAiSummary from './PaperAiSummary.vue'

// 后端曾把 .mjs 按 text/plain 下发，浏览器已把该响应连同错误的 MIME 缓存下来；
// 加版本查询串换个缓存键，配合后端 mimetypes 修复，已缓存过的浏览器也能立即恢复。
pdfjsLib.GlobalWorkerOptions.workerSrc = `${PdfWorker}?v=2`

interface Hl { id: string; page: number; rects: any[]; text: string; color: string; note: string; created: string; colorName?: string }

const props = defineProps<{ paperId: string; title?: string }>()
const route = useRoute()
const emit = defineEmits<{ (e: 'pages', n: number): void; (e: 'page', n: number, total: number): void }>()

const colors = ['#fde047', '#f472b6', '#86efac', '#7dd3fc', '#c4b5fd']
const color = ref(colors[0])

const viewerEl = ref<HTMLDivElement>()
const loading = ref(true)
const err = ref('')
const noTextLayer = ref(false)
const total = ref(0)
const curPage = ref(1)
const pageInput = ref('1')
const focusMode = ref(false)
const dualWidth = ref(50)
type OutlineItem = { title: string; dest: any; depth: number }
const outline = ref<OutlineItem[]>([])
const mode = ref<'page' | 'scroll'>('scroll')
const zoomPct = ref(100)
const panelOpen = ref(true)
const panelTab = ref<'anno' | 'thumbs' | 'notes'>('anno')
const highlights = ref<Hl[]>([])

let pdf: pdfjsLib.PDFDocumentProxy | null = null
let eventBus: InstanceType<typeof EventBus> | null = null
let viewer: InstanceType<typeof PDFViewer> | null = null
let thumbIO: IntersectionObserver | null = null
const posKey = `krs_pp_${props.paperId}`
watch(curPage, (page) => { pageInput.value = String(page) })
watch(() => route.query.page, (value) => {
  const page = Number(value)
  if (pdf && Number.isInteger(page) && page >= 1 && page <= total.value) go(page)
})
watch([dualWidth, focusMode], async () => {
  await nextTick()
  requestAnimationFrame(onWinResize)
})

function jumpToPage() {
  const page = Number(pageInput.value)
  if (!Number.isInteger(page) || page < 1 || page > total.value) {
    ElMessage.warning(`请输入 1 到 ${total.value} 之间的页码`)
    pageInput.value = String(curPage.value)
    return
  }
  go(page)
}
function onMoreCommand(command: string) {
  if (command === 'note') exportNote()
  if (command === 'md') exportMd()
}
function onReaderKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && focusMode.value && !editOpen.value) focusMode.value = false
}
function flattenOutline(items: any[], depth = 0): OutlineItem[] {
  return items.flatMap((item) => [
    { title: item.title || '未命名章节', dest: item.dest, depth },
    ...flattenOutline(item.items || [], depth + 1),
  ])
}
async function goOutline(dest: any) {
  if (!pdf || !dest) return
  try {
    const target = typeof dest === 'string' ? await pdf.getDestination(dest) : dest
    if (!target?.length) throw new Error('无法解析目录位置')
    const index = typeof target[0] === 'number' ? target[0] : await pdf.getPageIndex(target[0])
    if (index < 0 || index >= total.value) throw new Error('目录页码超出范围')
    await go(index + 1)
  } catch { ElMessage.warning('无法定位该目录项') }
}

/* ---------- 中英对照（右侧译文栏） ---------- */
const viewMode = ref<'single' | 'dual'>('single')
const dual = computed(() => viewMode.value === 'dual')
const trViewerEl = ref<HTMLDivElement>()
const tr = reactive({
  state: 'none' as 'none' | 'queued' | 'running' | 'ready' | 'failed',
  pages: 0, done: 0, blocks: 0, translated: 0, failed: 0,
  error: '', model: '', ai_enabled: true, cancelling: false, queue_depth: 0,
})
let trPdf: pdfjsLib.PDFDocumentProxy | null = null
let trViewer: InstanceType<typeof PDFViewer> | null = null
let trBus: InstanceType<typeof EventBus> | null = null
let trPoll: ReturnType<typeof setInterval> | null = null
let syncing = false
// 右栏当前挂着的文档：ready 前是原文镜像，ready 后是译文
let rightDoc: pdfjsLib.PDFDocumentProxy | null = null
let mirrorDoc: pdfjsLib.PDFDocumentProxy | null = null
let origBytes: Uint8Array | null = null

const trPercent = computed(() => {
  if (!tr.pages) return tr.state === 'running' ? 8 : 0
  return Math.max(4, Math.min(100, Math.round((tr.done / tr.pages) * 100)))
})
const trMeta = computed(() => {
  if (tr.state === 'queued') return '排队中'
  if (tr.state === 'running') return `翻译中 ${tr.done}/${tr.pages || '?'} 页`
  if (tr.state === 'ready') return tr.model ? `本地模型 · ${tr.model}` : '已缓存'
  if (tr.state === 'failed') return '失败'
  return ''
})

const bar = reactive({ show: false, x: 0, y: 0 })
const lk = reactive({ show: false, x: 0, y: 0, text: '', phonetic: '', meanings: [] as string[], translate: '', phrases: [] as { key: string; value: string[] }[], loading: false })
let pendingSel: { text: string; rects: any[]; page: number } | null = null
const paperAi = ref<InstanceType<typeof PaperAiSummary>>()
const query = ref('')
const searchTotal = ref(0)
const searchCurrent = ref(0)
const searchSeeking = ref(false)
const searchHits = ref<{ page: number; offset: number; context: string }[]>([])
let findController: InstanceType<typeof PDFFindController> | null = null
let searchBuildVersion = 0
let searchBuildTimer: ReturnType<typeof setTimeout> | undefined
const hlQuery = ref('')
const hlColor = ref('')
const editOpen = ref(false)
const editNote = ref('')
let pending: Hl | null = null

const uid = () => `h${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`
// P2-M1：标注 created 用本地钟面时间（toISOString 是 UTC，早上标注会记成前一天）
const localStamp = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
const colorName = (hex: string) => ({ '#fde047': '黄', '#f472b6': '粉', '#86efac': '绿', '#7dd3fc': '蓝', '#c4b5fd': '紫' } as Record<string, string>)[hex] || ''

/* ---------- 高亮读写 ---------- */
// P0-10：loadHl 失败绝不能"置空后照常全量 PUT"（会把服务端已有全部标注抹掉）。
// 加载失败即置 hlBlocked：saveHl 拒绝保存并提示，直到重新打开、成功加载为止。
const hlBlocked = ref(false)
async function loadHl() {
  hlBlocked.value = false
  try {
    const r = await http.get<{ items: Hl[] }>(`/papers/${props.paperId}/highlights`)
    highlights.value = (r.items || []).map((h) => ({ ...h, colorName: colorName(h.color) }))
  } catch {
    highlights.value = []
    hlBlocked.value = true
    ElMessage.warning('已有标注加载失败，已暂停标注保存以免覆盖服务端标注——请刷新页面重试')
  }
}
async function saveHl() {
  if (hlBlocked.value) {
    ElMessage.error('标注未成功加载，本次保存已取消（防止清空服务端已有标注）。请刷新后重试')
    return
  }
  try { await http.put(`/papers/${props.paperId}/highlights`, { items: highlights.value.map(({ colorName: _c, ...rest }) => rest) }) }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '标注保存失败') }
}
const sortedHl = computed(() => [...highlights.value].filter(h => (!hlColor.value || h.color === hlColor.value) && (!hlQuery.value.trim() || `${h.text} ${h.note || ''}`.toLowerCase().includes(hlQuery.value.trim().toLowerCase()))).sort((a, b) => a.page - b.page))
const pageHl = computed(() => highlights.value.filter((x) => x.page === curPage.value))

function rectPx(r: any, w: number, h: number) {
  if (typeof r.fx === 'number') return { x: r.fx * w, y: r.fy * h, w: r.fw * w, h: r.fh * h }
  return { x: r.x || 0, y: r.y || 0, w: r.w || 0, h: r.h || 0 }
}

function pageEl(page: number): HTMLElement | null {
  return viewerEl.value?.querySelector(`.page[data-page-number="${page}"]`) as HTMLElement | null
}

function drawHl(page: number) {
  const el = pageEl(page)
  if (!el) return
  let layer = el.querySelector(':scope > .hllayer') as HTMLElement | null
  if (!layer) {
    layer = document.createElement('div')
    layer.className = 'hllayer'
    el.appendChild(layer)
  }
  layer.querySelectorAll('div').forEach((n) => n.remove())
  const rect = el.getBoundingClientRect()
  for (const h of highlights.value) {
    if (h.page !== page) continue
    for (const r of h.rects) {
      const p = rectPx(r, rect.width, rect.height)
      const d = document.createElement('div')
      d.style.cssText = `position:absolute;left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${Math.max(4, p.h)}px;background:${h.color};opacity:0.45;pointer-events:none;border-radius:2px`
      layer.appendChild(d)
    }
  }
}

/* ---------- 导航/缩放（官方 viewer） ---------- */
function onMode() {
  const scrollMode = mode.value === 'page' ? ScrollMode.PAGE : ScrollMode.VERTICAL
  if (viewer) viewer.scrollMode = scrollMode
  if (trViewer) trViewer.scrollMode = scrollMode
}
async function go(p: number) {
  if (!pdf || p < 1 || p > total.value) return
  curPage.value = p
  clientState.setItem(posKey, String(p))
  if (viewer && viewer.currentPageNumber !== p) {
    syncing = true
    try { viewer.currentPageNumber = p } finally { syncing = false }
  }
  syncTrPage(p)
  emit('page', p, total.value)
}
function syncTrPage(p: number) {
  if (!trViewer || syncing) return
  syncing = true
  try { trViewer.currentPageNumber = p } catch { /* 译文还没加载完 */ }
  finally { syncing = false }
}
function zoomBy(d: number) {
  zoomPct.value = Math.max(50, Math.min(200, zoomPct.value + d))
  const v = String(zoomPct.value / 100)
  if (viewer) viewer.currentScaleValue = v
  if (trViewer) trViewer.currentScaleValue = v
}
function zoomFit() {
  zoomPct.value = 100
  fitWidth(viewer, viewerEl.value)
  fitWidth(trViewer, trViewerEl.value)
}

/** 按容器宽度重算缩放。
 *  pdf.js 的 'page-width' 是"缓存值"：容器宽度变了（单栏↔双栏）它不会重算，
 *  所以这里自己量容器宽度、按第 1 页的原始宽度算出倍率再套上去。 */
async function fitWidth(v: InstanceType<typeof PDFViewer> | null, host: HTMLElement | null) {
  if (!v || !host) return
  const width = host.clientWidth - 2
  const doc = v.pdfDocument
  if (!doc || width <= 0) {
    if (v) v.currentScaleValue = 'page-width'
    return
  }
  try {
    const page = await doc.getPage(1)
    const vp = page.getViewport({ scale: 1 })
    if (vp.width > 0) v.currentScaleValue = String(width / vp.width)
  } catch {
    v.currentScaleValue = 'page-width'
  }
}

/* ---------- 划词（官方文本层） ---------- */
function onDocMouseUp(ev: MouseEvent) {
  const t = ev.target as HTMLElement
  if (t?.closest?.('.selbar') || t?.closest?.('.lk-card')) return
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) { hideUi(); return }
  const pageDiv = t?.closest?.('.page') as HTMLElement | null
  if (!pageDiv) { hideUi(); return }
  const text = sel.toString().trim().replace(/\s+/g, ' ')
  if (!text || text.length > 600) return
  try {
    const range = sel.getRangeAt(0)
    const pr = pageDiv.getBoundingClientRect()
    const rects: any[] = []
    for (const r of Array.from(range.getClientRects())) {
      if (r.width < 1 || r.height < 1) continue
      rects.push({ fx: (r.left - pr.left) / pr.width, fy: (r.top - pr.top) / pr.height, fw: r.width / pr.width, fh: r.height / pr.height })
      if (rects.length > 60) break
    }
    if (!rects.length) return
    const selectedPage = Number(pageDiv.dataset.pageNumber) || curPage.value
    pendingSel = { text, rects, page: selectedPage }
    curPage.value = selectedPage
    const first = range.getClientRects()[0]
    bar.x = Math.min(first.left, window.innerWidth - 300)
    bar.y = first.bottom + 8
    bar.show = true
    lk.show = false
  } catch { hideUi() }
}
function hideUi() { bar.show = false; pendingSel = null }
function onDocDown(ev: MouseEvent) {
  const t = ev.target as HTMLElement
  if (!t.closest('.selbar') && !t.closest('.lk-card')) hideUi()
}
function onDblClick(ev: MouseEvent) {
  const t = ev.target as HTMLElement
  const pageDiv = t?.closest?.('.page') as HTMLElement | null
  const sel = window.getSelection()
  if (pageDiv && sel && !sel.isCollapsed) {
    const text = sel.toString().trim().slice(0, 120)
    if (text) {
      const fr = sel.getRangeAt(0).getClientRects()[0]
      if (fr) { bar.x = Math.min(fr.left, window.innerWidth - 300); bar.y = fr.bottom + 8 }
      lk.show = false
      pendingSel = { text, rects: [], page: Number(pageDiv.dataset.pageNumber) || curPage.value }
      doLookup()
    }
  }
}

function addHighlight(c: string) {
  if (!pendingSel) return
  const selectedPage = pendingSel.page
  highlights.value.push({ id: uid(), page: pendingSel.page, rects: pendingSel.rects, text: pendingSel.text, color: c, note: '', created: localStamp(), colorName: colorName(c) })
  bar.show = false
  pendingSel = null
  saveHl()
  drawHl(selectedPage)
}
function delHl(h: Hl | null, fromEdit = false) {
  if (!h) return
  highlights.value = highlights.value.filter((x) => x.id !== h.id)
  saveHl()
  if (fromEdit) editOpen.value = false
  drawHl(h.page)
}
function jumpHl(h: Hl) { go(h.page) }
function editHl(h: Hl) { pending = h; editNote.value = h.note || ''; editOpen.value = true }
function saveEdit() {
  if (!pending) return
  pending.note = editNote.value
  pending.colorName = colorName(pending.color)
  saveHl()
  pending = null
  editOpen.value = false
  drawHl(curPage.value)
}
function clearPageHl() {
  highlights.value = highlights.value.filter((x) => x.page !== curPage.value)
  saveHl()
  drawHl(curPage.value)
}

/* ---------- PDF.js 全文搜索：跨文本片段匹配、逐处高亮及定位 ---------- */
function dispatchFind(type: string, backwards = false) {
  eventBus?.dispatch('find', { source: null, type, query: query.value.trim(), caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: backwards, matchDiacritics: false })
}
function doSearch() {
  if (!query.value.trim()) return clearSearch()
  clearTimeout(searchBuildTimer)
  searchCurrent.value = 0
  searchTotal.value = 0
  searchHits.value = []
  searchBuildVersion++
  dispatchFind('')
}
function searchNav(dir: number) { if (searchTotal.value) dispatchFind('again', dir < 0) }
function clearSearch() {
  searchBuildVersion++
  clearTimeout(searchBuildTimer)
  searchHits.value = []
  searchCurrent.value = searchTotal.value = 0
  eventBus?.dispatch('findbarclose', { source: null })
}
async function buildSearchContexts() {
  const doc = pdf
  const controller = findController
  const version = ++searchBuildVersion
  if (!doc || !controller || !controller.highlightMatches || !query.value.trim()) return
  const hits: { page: number; offset: number; context: string }[] = []
  for (let page = 1; page <= doc.numPages; page++) {
    const offsets = controller.pageMatches[page - 1] || []
    if (!offsets.length) continue
    const content = await (await doc.getPage(page)).getTextContent({ disableNormalization: true })
    if (version !== searchBuildVersion) return
    const text = content.items.map((item: any) => item.str || '').join('')
    for (let i = 0; i < offsets.length; i++) {
      const start = offsets[i]
      const end = start + (controller.pageMatchesLength[page - 1]?.[i] || 1)
      hits.push({ page, offset: start, context: `${start > 45 ? '…' : ''}${text.slice(Math.max(0, start - 45), Math.min(text.length, end + 45)).replace(/\s+/g, ' ')}${end + 45 < text.length ? '…' : ''}` })
    }
  }
  if (version === searchBuildVersion) searchHits.value = hits
}
async function jumpSearchHit(hit: { page: number; offset: number }) {
  const bus = eventBus
  const controller = findController
  if (!bus || !controller || searchSeeking.value) return
  const matches = controller.pageMatches
  const targetPage = hit.page - 1
  const targetMatch = matches[targetPage]?.indexOf(hit.offset) ?? -1
  const selected = controller.selected
  if (targetMatch < 0 || selected.pageIdx < 0 || selected.matchIdx < 0) return
  const absolute = (page: number, index: number) => matches.slice(0, page).reduce((n, group) => n + (group?.length || 0), index)
  const total = matches.reduce((n, group) => n + (group?.length || 0), 0)
  const from = absolute(selected.pageIdx, selected.matchIdx)
  const to = absolute(targetPage, targetMatch)
  if (!total) return
  if (from === to) {
    const scrollSelected = () => pageEl(hit.page)?.querySelector('.textLayer .highlight.selected')?.scrollIntoView({ block: 'center', inline: 'nearest' })
    const onText = (evt: any) => { if (evt.pageNumber === hit.page) { bus.off('textlayerrendered', onText); requestAnimationFrame(scrollSelected) } }
    bus.on('textlayerrendered', onText)
    setTimeout(() => bus.off('textlayerrendered', onText), 5000)
    await go(hit.page)
    scrollSelected()
    return
  }
  const forward = (to - from + total) % total
  const backward = (from - to + total) % total
  const backwards = backward < forward
  const steps = backwards ? backward : forward
  searchSeeking.value = true
  try {
    for (let i = 0; i < steps; i++) {
      if (eventBus !== bus || findController !== controller) return
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { bus.off('updatefindcontrolstate', done); reject(new Error('timeout')) }, 5000)
        const done = (evt: any) => {
          if (evt.state === 3) return // PDF.js 仍在查找
          bus.off('updatefindcontrolstate', done)
          clearTimeout(timer)
          resolve()
        }
        bus.on('updatefindcontrolstate', done)
        dispatchFind('again', backwards)
      })
    }
  } catch { ElMessage.warning('定位搜索结果失败，请重试。') }
  finally { searchSeeking.value = false }
}

/* ---------- 中英对照：译文加载 / 状态轮询 / 双栏同步 ---------- */
async function refreshTranslation(autoStart: boolean) {
  try {
    const st = await http.get<any>(`/papers/${props.paperId}/translation`)
    applyStatus(st)
    if (st.state === 'ready') {
      await showDual()
    } else if (st.state === 'running' || st.state === 'queued') {
      startPolling()
    } else if (autoStart && st.ai_enabled !== false) {
      await startTranslate(false)   // 没有译文（且不在队列里）→ 立即排队
    }
  } catch { /* 没译文/接口异常都不影响读原文 */ }
}

/** 切到双栏；已经处于双栏时直接（重新）挂载译文视图。 */
async function showDual() {
  if (viewMode.value !== 'dual') viewMode.value = 'dual'
  else await mountTrViewer()
}

function applyStatus(st: any) {
  if (!st || typeof st !== 'object') return
  tr.state = st.state || 'none'
  tr.pages = st.pages || 0
  tr.done = st.done || 0
  tr.blocks = st.blocks || 0
  tr.translated = st.translated || 0
  tr.failed = st.failed || 0
  tr.error = st.error || ''
  tr.model = st.model || ''
  if (st.queue_depth !== undefined) tr.queue_depth = st.queue_depth || 0
  if (st.ai_enabled !== undefined) tr.ai_enabled = !!st.ai_enabled
  if (tr.state !== 'running') tr.cancelling = false
}

async function cancelTranslate() {
  try {
    const st = await http.post<any>(`/papers/${props.paperId}/translation/cancel`, {})
    applyStatus(st)
    tr.cancelling = true
    ElMessage.info('已请求停止：当前页译完就停')
  } catch {
    ElMessage.warning('取消失败，请稍后重试')
  }
}

async function startTranslate(force: boolean) {
  try {
    const st = await http.post<any>(`/papers/${props.paperId}/translation`, { force })
    applyStatus(st)
    startPolling()
    if (st.state === 'failed') ElMessage.error(st.error || '翻译启动失败')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '翻译启动失败'
    ElMessage.error(msg)
    tr.state = 'failed'
    tr.error = msg
  }
}

function startPolling() {
  if (trPoll) return
  trPoll = setInterval(async () => {
    try {
      const st = await http.get<any>(`/papers/${props.paperId}/translation`)
      applyStatus(st)
      if (st.state !== 'running' && st.state !== 'queued') {
        stopPolling()
        if (st.state === 'ready') {
          await showDual()
          ElMessage.success('中文译文已生成')
        } else if (st.state === 'failed') {
          ElMessage.error(st.error || '翻译失败')
        }
      }
    } catch { /* 网络抖动：下一轮再试 */ }
  }, 2500)
}
function stopPolling() {
  if (trPoll) { clearInterval(trPoll); trPoll = null }
}

async function loadTranslatedDoc(): Promise<pdfjsLib.PDFDocumentProxy | null> {
  if (trPdf) return trPdf
  try {
    const blob = await http.blob(`/papers/${props.paperId}/translation/file`)
    trPdf = await pdfjsLib.getDocument({ data: await blob.arrayBuffer() }).promise
    return trPdf
  } catch {
    trPdf = null
    return null
  }
}

/** 译文还没好时，右栏镜像同一篇英文原文，避免盯着空白 */
async function loadMirrorDoc(): Promise<pdfjsLib.PDFDocumentProxy | null> {
  if (mirrorDoc) return mirrorDoc
  if (!origBytes) return null
  try {
    // getDocument 会把 ArrayBuffer 转移给 worker，这里每次传副本，保住 origBytes
    mirrorDoc = await pdfjsLib.getDocument({ data: origBytes.slice() }).promise
    return mirrorDoc
  } catch {
    mirrorDoc = null
    return null
  }
}

/** 把右栏挂到「该显示的文档」上：ready → 译文，否则 → 原文镜像。 */
async function mountTrViewer() {
  await nextTick()
  const host = trViewerEl.value
  if (!host) return
  let doc = tr.state === 'ready' ? await loadTranslatedDoc() : null
  if (tr.state === 'ready' && !doc) {
    // 状态说就绪但取不到译文（缓存被清/接口异常）：回退显示原文并给出重试入口
    tr.state = 'failed'
    tr.error = '译文文件读取失败，请点重试'
  }
  if (!doc) doc = await loadMirrorDoc()
  if (!doc) return
  if (!trViewer) {
    trBus = new EventBus()
    trViewer = new PDFViewer({
      container: host,
      eventBus: trBus,
      linkService: new SimpleLinkService(),
      removePageBorders: true,
    })
    trViewer.setDocument(doc)
    trViewer.scrollMode = mode.value === 'page' ? ScrollMode.PAGE : ScrollMode.VERTICAL
    rightDoc = doc
    trBus.on('pagesinit', () => {
      // 换文档（原文镜像 ↔ 译文）后把页码/缩放还原到当前阅读位置
      if (!trViewer) return
      trViewer.currentPageNumber = curPage.value
      trViewer.currentScaleValue = zoomPct.value === 100 ? 'page-width' : String(zoomPct.value / 100)
    })
    trBus.on('pagechanging', (evt: any) => {
      if (syncing) return
      const p = evt.pageNumber
      syncing = true
      try {
        curPage.value = p
        if (viewer && viewer.currentPageNumber !== p) viewer.currentPageNumber = p
      } finally { syncing = false }
      clientState.setItem(posKey, String(p))
      emit('page', p, total.value)
    })
  } else if (rightDoc !== doc) {
    trViewer.setDocument(doc)      // 译文就绪：原地换文档，页码/缩放不动
    rightDoc = doc
  }
  trViewer.currentPageNumber = curPage.value
  if (zoomPct.value === 100) {
    await fitWidth(trViewer, trViewerEl.value)
  } else {
    trViewer.currentScaleValue = String(zoomPct.value / 100)
  }
}

function destroyTrViewer() {
  try { trViewer?.destroy() } catch { /* ignore */ }
  trViewer = null
  trBus = null
  rightDoc = null
}

watch(dual, async (on) => {
  if (on) {
    await mountTrViewer()
  } else {
    destroyTrViewer()
  }
  // 分栏/合栏后左右栏宽度都变了，按宽度重新适配一次（否则左栏会保持旧的大字号）
  await nextTick()
  if (!on && panelOpen.value && panelTab.value === 'thumbs') renderThumbs()
  requestAnimationFrame(() => {
    if (zoomPct.value === 100) {
      fitWidth(viewer, viewerEl.value)
      fitWidth(trViewer, trViewerEl.value)
    }
  })
})

// 译文就绪（或状态变化）时，右栏从"原文镜像"换成"译文"，不用关掉重开
watch(() => tr.state, async (s) => {
  if (!dual.value) return
  if (s === 'ready') await mountTrViewer()
})

/* ---------- 缩略图 ---------- */
async function renderThumbs() {
  if (panelTab.value !== 'thumbs') return
  nextTick(() => {
    thumbIO?.disconnect()
    thumbIO = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        const cv = e.target as HTMLCanvasElement
        const p = Number(cv.dataset.page)
        if (e.isIntersecting && !cv.dataset.ok) {
          pdf!.getPage(p).then(async (pg) => {
            const vp = pg.getViewport({ scale: 0.12 })
            cv.width = vp.width; cv.height = vp.height
            await pg.render({ canvasContext: cv.getContext('2d')!, viewport: vp }).promise
            cv.dataset.ok = '1'
          }).catch(() => {})
        }
      })
    }, { rootMargin: '300px' })
    document.querySelectorAll('.thumb-grid canvas.th').forEach((cv) => thumbIO!.observe(cv))
  })
}

/* ---------- 导出 ---------- */
function buildMd() {
  const source = `/papers/${encodeURIComponent(props.paperId)}`
  const lines = [`# ${props.title || '文献'} · 荧光笔摘录`, '', `[返回论文](${source})`, '']
  for (const h of [...highlights.value].sort((a, b) => a.page - b.page)) {
    lines.push(`- [P${h.page}](${source}?page=${h.page}) [${colorName(h.color)}] ${h.text}${h.note ? `\n  - 备注：${h.note}` : ''}`)
  }
  return lines.join('\n')
}

function explainSelection() {
  if (!pendingSel) return
  const { page, text } = pendingSel
  hideUi()
  paperAi.value?.explain(page, text)
}

async function exportNote() {
  if (!highlights.value.length) return ElMessage.warning('还没有标注')
  const md = buildMd()
  try {
    const r = await http.post<{ id: string }>('/notes', { title: `${props.title || '文献'} · 荧光笔摘录`, type: 'note', tags: ['论文', '摘录', `paper:${props.paperId}`], summary: '由论文阅读器一键生成', content: md })
    ElMessage.success('已导出为笔记')
    window.open(`/notes/${r.id}`, '_blank')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '导出失败') }
}
function exportMd() {
  if (!highlights.value.length) return ElMessage.warning('还没有标注')
  const blob = new Blob([buildMd()], { type: 'text/markdown;charset=utf-8' })
  const u = URL.createObjectURL(blob); const a = document.createElement('a')
  a.href = u; a.download = `${props.title || '文献'}-摘录.md`; a.click(); URL.revokeObjectURL(u)
}

/* ---------- 查询 / 词本 ---------- */
async function doLookup() {
  if (!pendingSel) return
  Object.assign(lk, { show: true, loading: true, text: pendingSel.text, phonetic: '', meanings: [], translate: '', phrases: [], x: bar.x, y: bar.y + 40 })
  bar.show = false
  try {
    const r = await http.post<{ phonetic: string; meanings: string[]; translate: string; phrases: { key: string; value: string[] }[] }>('/translate/lookup', { text: pendingSel.text })
    lk.phonetic = r.phonetic || ''; lk.meanings = r.meanings || []; lk.translate = r.translate || ''; lk.phrases = r.phrases || []
  } catch { ElMessage.error('查询失败，请稍后重试') } finally { lk.loading = false }
}
async function addVocabRaw() { if (pendingSel) { await postVocab(pendingSel.text, ''); hideUi() } }
async function addVocab() { await postVocab(lk.text, lk.meanings.slice(0, 3).join('；') || lk.translate.slice(0, 300)); lk.show = false }
async function postVocab(word: string, meaning: string) {
  try {
    const text = pendingSel?.text || lk.text || ''
    await http.post('/vocab', { word: word.slice(0, 120), meaning: meaning.slice(0, 600), sentence: text.slice(0, 600), source: props.title || props.paperId })
    ElMessage.success('已加入生词本')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '加入失败') }
}

/* ---------- 生命周期 ---------- */
onMounted(async () => {
  await loadHl()
  try {
    const blob = await http.blob(`/papers/${props.paperId}/file`)
    const buf = await blob.arrayBuffer()
    // pdf.js 会把 ArrayBuffer 转移给 worker（此后 buf 不可用），先留一份给右栏镜像
    origBytes = new Uint8Array(buf.slice(0))
    pdf = await pdfjsLib.getDocument({ data: buf }).promise
    total.value = pdf.numPages
    emit('pages', total.value)
    try { outline.value = flattenOutline(await pdf.getOutline() || []) } catch { outline.value = [] }

    eventBus = new EventBus()
    const linkService = new PDFLinkService({ eventBus })
    findController = new PDFFindController({ eventBus, linkService, updateMatchesCountOnProgress: false })
    viewer = new PDFViewer({
      container: viewerEl.value!,
      eventBus,
      linkService,
      findController,
      removePageBorders: true,
    })
    linkService.setViewer(viewer)
    linkService.setDocument(pdf)
    const updateFindCount = (evt: any) => {
      searchCurrent.value = evt.matchesCount?.current || 0
      searchTotal.value = evt.matchesCount?.total || 0
      clearTimeout(searchBuildTimer)
      searchBuildTimer = setTimeout(() => { void buildSearchContexts() }, 150)
    }
    eventBus.on('updatefindmatchescount', updateFindCount)
    eventBus.on('updatefindcontrolstate', (evt: any) => {
      updateFindCount(evt)
      if (evt.state === 1 && query.value.trim()) ElMessage.info('未找到匹配')
    })
    viewer.setDocument(pdf)
    eventBus.on('pagechanging', (evt: any) => {
      curPage.value = evt.pageNumber
      clientState.setItem(posKey, String(evt.pageNumber))
      emit('page', evt.pageNumber, total.value)
    })
    eventBus.on('textlayerrendered', (evt: any) => { drawHl(evt.pageNumber) })
    const requested = Number(route.query.page)
    const saved = Number.isInteger(requested) && requested >= 1 && requested <= total.value
      ? requested : Number(clientState.getItem(posKey) || 1)
    curPage.value = Math.min(Math.max(1, saved), total.value)
    onMode()
    if (saved > 1) viewer.currentPageNumber = curPage.value
    // 布局稳定后强制按实际宽度排版（防半屏/窄窗初始测量为 0）
    requestAnimationFrame(() => { requestAnimationFrame(() => { fitWidth(viewer, viewerEl.value) }) })
    setTimeout(() => { if (zoomPct.value === 100) fitWidth(viewer, viewerEl.value) }, 500)
    // 打开论文即扫描译文：有就直接展示，没有就自动开始翻译
    await refreshTranslation(true)
  } catch (e: any) {
    err.value = e?.message || 'PDF 加载失败'
  } finally { loading.value = false }
  window.addEventListener('resize', onWinResizeDebounced)
  document.addEventListener('mouseup', onDocMouseUp)
  document.addEventListener('pointerup', onDocMouseUp)
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('dblclick', onDblClick)
  document.addEventListener('keydown', onReaderKeydown)
  renderThumbs()
})

function onWinResize() {
  if (zoomPct.value !== 100) return
  fitWidth(viewer, viewerEl.value)
  fitWidth(trViewer, trViewerEl.value)
}
// P2-M2：防抖处理器必须具名——此前注册匿名函数、卸载却 remove 具名 onWinResize，
// 引用对不上导致每次打开阅读器都永久泄漏一个 resize 监听器。
function onWinResizeDebounced() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(onWinResize, 200)
}
let resizeTimer: ReturnType<typeof setTimeout> | undefined

onBeforeUnmount(() => {
  searchBuildVersion++
  clearTimeout(searchBuildTimer)
  findController = null
  clearTimeout(resizeTimer)
  stopPolling()
  window.removeEventListener('resize', onWinResizeDebounced)
  document.removeEventListener('mouseup', onDocMouseUp)
  document.removeEventListener('pointerup', onDocMouseUp)
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('dblclick', onDblClick)
  document.removeEventListener('keydown', onReaderKeydown)
  thumbIO?.disconnect()
  destroyTrViewer()
  trPdf?.destroy().catch(() => {})
  trPdf = null
  mirrorDoc?.destroy().catch(() => {})
  mirrorDoc = null
  origBytes = null
  viewer?.destroy()
  viewer = null
  pdf?.destroy().catch(() => {})
  pdf = null
})
</script>

<style scoped>
.search-hit-list { max-height: 50vh; overflow: auto; }
.search-hit-list button { display: flex; flex-direction: column; gap: 4px; width: 100%; padding: 8px; border: 0; border-bottom: 1px solid var(--el-border-color-lighter); background: transparent; text-align: left; cursor: pointer; color: var(--el-text-color-regular); }
.search-hit-list button:hover { background: var(--el-fill-color-light); }
.search-hit-list b { color: var(--el-color-primary); }
.search-hit-list span { overflow-wrap: anywhere; }
.reader { display: flex; flex-direction: column; gap: 12px; }
.reader.focused { position: fixed; inset: 0; z-index: 100; padding: 12px; background: var(--bg, #f5f7fa); overflow: auto; }
.focused .reader-body { flex: 1; min-height: 0; align-items: stretch; }
.focused .panes { align-items: stretch; }
.focused .pane { display: flex; flex-direction: column; }
.focused .host, .focused .panes.dual .host { flex: 1; height: auto; min-height: 320px; }
.rtool { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 8px 14px; }
.rg { display: flex; align-items: center; gap: 8px; }
.page-jump { display: flex; align-items: center; gap: 4px; }
.page-jump input { width: 52px; border: 1px solid var(--el-border-color); border-radius: 4px; padding: 3px 4px; font: inherit; }
.page-go { border: 0; background: transparent; color: var(--el-color-primary); cursor: pointer; }
.outline-list { max-height: 55vh; overflow: auto; }
.outline-list button { display: block; width: 100%; padding: 6px 8px; border: 0; background: transparent; text-align: left; cursor: pointer; font: inherit; }
.outline-list button:hover:not(:disabled) { background: var(--el-fill-color-light); }
.outline-list button:disabled, .outline-empty { color: var(--txt3); }
.width-adjust { display: inline-flex; align-items: center; gap: 4px; font-weight: 400; white-space: nowrap; }
.width-adjust input { width: 75px; }
.zoomv { font-size: 12px; color: var(--txt2); min-width: 40px; text-align: center; }
.pgv { font-size: 13px; font-weight: 700; }
.reader-body { display: flex; gap: 14px; align-items: flex-start; }
.panes { flex: 1; min-width: 0; display: flex; gap: 12px; align-items: flex-start; }
.pane { flex: 1; min-width: 0; }
.pane-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 6px 4px; font-size: 12px; font-weight: 700; color: var(--txt2); }
.tr-meta { font-weight: 400; font-size: 11px; color: var(--txt3); }
.host { position: relative; min-width: 0; height: calc(100vh - 220px); border-radius: 12px; background: rgba(30, 41, 59, 0.06); padding: 8px; overflow: hidden; }
.panes.dual .host { height: calc(100vh - 262px); }
.tr-banner { position: absolute; top: 8px; left: 8px; right: 8px; z-index: 6; display: flex; align-items: center; gap: 10px; padding: 5px 10px; border-radius: 8px; background: rgba(15, 23, 42, 0.82); color: #e2e8f0; font-size: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.18); }
.tr-banner.warn { background: rgba(127, 29, 29, 0.86); }
.tr-banner .btext { flex: 1; min-width: 0; line-height: 1.45; }
.tr-banner .trbar { width: 92px; flex: none; }
.tr-banner :deep(.el-button) { color: #e2e8f0; padding: 2px 6px; }
.tr-banner :deep(.el-button:hover) { color: #fff; }
.viewerhost { position: absolute; inset: 8px; overflow: auto; }
.panel { width: 280px; flex: none; padding: 12px; max-height: calc(100vh - 200px); overflow: auto; }
.ptabs { display: flex; gap: 6px; margin-bottom: 10px; }
.ptabs button { flex: 1; border: none; background: transparent; color: var(--txt2); padding: 6px 0; cursor: pointer; border-bottom: 2px solid transparent; font-family: inherit; font-size: 13px; }
.ptabs button.on { color: var(--acc2); border-bottom-color: var(--acc2); font-weight: 700; }
.ptab { display: grid; gap: 8px; }
.anno-ops { display: flex; justify-content: flex-end; }
.hl-list { display: grid; gap: 8px; }
.hl-item { border-left: 4px solid; background: rgba(148, 163, 184, 0.08); border-radius: 8px; padding: 6px 10px; font-size: 12.5px; }
.hl-text { line-height: 1.6; }
.hl-note { margin-top: 4px; color: var(--txt3); font-size: 12px; border-top: 1px dashed rgba(148,163,184,.2); padding-top: 4px; }
.hl-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 5px; color: var(--txt2); font-size: 11px; }
.hl-empty { color: var(--txt2); font-size: 12.5px; line-height: 1.8; }
.thumb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 6px; }
.th-wrap { position: relative; cursor: pointer; border: 2px solid transparent; border-radius: 6px; background: #fff; }
.th-wrap.on { border-color: var(--acc2); }
.th { display: block; width: 100%; }
.th-num { position: absolute; bottom: 0; right: 0; font-size: 10px; background: rgba(15,23,42,.6); color: #fff; padding: 0 4px; border-radius: 4px 0 0 0; }
.hint { color: var(--txt2); padding: 30px; font-size: 14px; position: relative; z-index: 5; }
.err { color: #f43f5e; }
.scan-tip { color: #b45309; background: rgba(251, 191, 36, 0.12); padding: 4px 10px; border-radius: 8px; font-size: 12px; margin: 0 auto 8px; position: relative; z-index: 5; }
.edit-body { display: grid; gap: 12px; }
.q { font-style: italic; color: var(--txt3); }
.ccol { display: flex; align-items: center; gap: 8px; }
.ccol .lab { font-size: 12px; color: var(--txt2); }
.selbar { position: fixed; z-index: 60; display: flex; align-items: center; gap: 5px; background: rgba(15, 23, 42, 0.92); padding: 5px 8px; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.3); }
.dot { width: 16px; height: 16px; border-radius: 50%; cursor: pointer; border: 2px solid transparent; }
.dot.on { border-color: #fff; }
.sep { width: 1px; height: 16px; background: rgba(148,163,184,.4); margin: 0 2px; }
.b { background: none; border: none; color: #e2e8f0; cursor: pointer; font-size: 12px; padding: 2px 6px; font-family: inherit; }
.b:hover { color: #c4b5fd; }
.lk-card { position: fixed; z-index: 60; width: 360px; padding: 12px 14px; }
.lk-head { display: flex; align-items: center; gap: 8px; }
.lk-ph { color: var(--txt2); font-size: 12px; }
.lk-sec { margin-top: 8px; }
.lk-meaning { font-size: 13.5px; line-height: 1.6; padding: 2px 0; }
.lk-phrase { font-size: 12.5px; color: var(--txt3); padding: 2px 0; }
.lk-ops { margin-top: 10px; display: flex; justify-content: flex-end; }
@media (max-width: 900px) {
  .reader-body { flex-direction: column; align-items: stretch; }
  .panes { flex-direction: column; align-items: stretch; width: 100%; }
  .panes.dual .pane { flex: none !important; }
  .width-adjust { display: none; }
  .focused .reader-body, .focused .panes { display: block; }
  .focused .host, .focused .panes.dual .host { height: 65vh; }
  .panes.dual .host { height: calc(100vh - 300px); }
  .panel { width: 100%; max-height: none; }
  .host { height: calc(100vh - 250px); min-height: 320px; }
}
</style>

<style>
.viewerhost .hllayer { position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 2; }
.viewerhost .page { position: relative; }
</style>
