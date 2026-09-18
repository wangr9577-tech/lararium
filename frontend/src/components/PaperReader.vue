<template>
  <div class="reader">
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

      <div class="rg search">
        <el-input v-model="query" size="small" clearable placeholder="页内搜索…" style="width: 150px" @keyup.enter="doSearch" />
        <el-button-group size="small" v-if="searchResults.length">
          <el-button @click="searchNav(-1)">↑</el-button>
          <span class="zoomv">{{ searchIdx + 1 }}/{{ searchResults.length }}</span>
          <el-button @click="searchNav(1)">↓</el-button>
        </el-button-group>
      </div>

      <div class="rg">
        <span class="pgv">{{ curPage }} / {{ total }}</span>
        <el-tooltip content="导出为笔记（存到笔记库）" placement="top"><el-button size="small" @click="exportNote">导出为笔记</el-button></el-tooltip>
        <el-tooltip content="下载摘录 md" placement="top"><el-button size="small" @click="exportMd">下载摘录</el-button></el-tooltip>
        <el-button size="small" @click="panelOpen = !panelOpen">{{ panelOpen ? '收起面板' : '标注/缩略图' }}</el-button>
      </div>
    </div>

    <div class="reader-body">
      <!-- 官方 pdf.js 视图容器 -->
      <div class="host" :class="{ pubonly: !panelOpen }">
        <div ref="viewerEl" class="viewerhost"><div class="pdfViewer"></div></div>
        <div v-if="loading" class="hint">正在加载 PDF…</div>
        <div v-if="err" class="hint err">{{ err }}</div>
        <div v-if="noTextLayer && !loading" class="scan-tip">此 PDF 无文本层（可能是扫描版），无法划词 / 荧光笔标注。</div>
      </div>

      <!-- 右侧面板 -->
      <aside v-if="panelOpen" class="panel glass">
        <div class="ptabs">
          <button :class="{ on: panelTab === 'anno' }" @click="panelTab = 'anno'">标注（{{ highlights.length }}）</button>
          <button :class="{ on: panelTab === 'thumbs' }" @click="panelTab = 'thumbs'; renderThumbs()">缩略图</button>
        </div>

        <div v-if="panelTab === 'anno'" class="ptab">
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
          </div>
        </div>

        <div v-else class="ptab thumbs">
          <div class="thumb-grid">
            <div v-for="p in total" :key="p" class="th-wrap" :class="{ on: p === curPage }" @click="go(p)">
              <canvas class="th" :data-page="p" />
              <span class="th-num">{{ p }}</span>
            </div>
          </div>
        </div>
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
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { EventBus, PDFViewer, SimpleLinkService, ScrollMode } from 'pdfjs-dist/web/pdf_viewer.mjs'
import 'pdfjs-dist/web/pdf_viewer.css'
import { http } from '../api/client'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

interface Hl { id: string; page: number; rects: any[]; text: string; color: string; note: string; created: string; colorName?: string }

const props = defineProps<{ paperId: string; title?: string }>()
const emit = defineEmits<{ (e: 'pages', n: number): void; (e: 'page', n: number, total: number): void }>()

const colors = ['#fde047', '#f472b6', '#86efac', '#7dd3fc', '#c4b5fd']
const color = ref(colors[0])

const viewerEl = ref<HTMLDivElement>()
const loading = ref(true)
const err = ref('')
const noTextLayer = ref(false)
const total = ref(0)
const curPage = ref(1)
const mode = ref<'page' | 'scroll'>('scroll')
const zoomPct = ref(100)
const panelOpen = ref(true)
const panelTab = ref<'anno' | 'thumbs'>('anno')
const highlights = ref<Hl[]>([])

let pdf: pdfjsLib.PDFDocumentProxy | null = null
let eventBus: InstanceType<typeof EventBus> | null = null
let viewer: InstanceType<typeof PDFViewer> | null = null
let thumbIO: IntersectionObserver | null = null
const posKey = `krs_pp_${props.paperId}`

const bar = reactive({ show: false, x: 0, y: 0 })
const lk = reactive({ show: false, x: 0, y: 0, text: '', phonetic: '', meanings: [] as string[], translate: '', phrases: [] as { key: string; value: string[] }[], loading: false })
let pendingSel: { text: string; rects: any[] } | null = null
const query = ref('')
const searchResults = ref<{ page: number }[]>([])
const searchIdx = ref(0)
let searchIndex: { page: number; item: any }[] | null = null
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
const sortedHl = computed(() => [...highlights.value].sort((a, b) => a.page - b.page))
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
  if (!viewer) return
  viewer.scrollMode = mode.value === 'page' ? ScrollMode.PAGE : ScrollMode.VERTICAL
}
async function go(p: number) {
  if (!pdf || p < 1 || p > total.value) return
  curPage.value = p
  localStorage.setItem(posKey, String(p))
  if (viewer) viewer.currentPageNumber = p
  emit('page', p, total.value)
}
function zoomBy(d: number) {
  if (!viewer) return
  zoomPct.value = Math.max(50, Math.min(200, zoomPct.value + d))
  viewer.currentScaleValue = String(zoomPct.value / 100)
}
function zoomFit() {
  if (!viewer) return
  viewer.currentScaleValue = 'page-width'
  zoomPct.value = 100
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
    pendingSel = { text, rects }
    curPage.value = Number(pageDiv.dataset.pageNumber) || curPage.value
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
      pendingSel = { text, rects: [] }
      doLookup()
    }
  }
}

function addHighlight(c: string) {
  if (!pendingSel) return
  highlights.value.push({ id: uid(), page: curPage.value, rects: pendingSel.rects, text: pendingSel.text, color: c, note: '', created: localStamp(), colorName: colorName(c) })
  bar.show = false
  pendingSel = null
  saveHl()
  drawHl(curPage.value)
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

/* ---------- 搜索（定位到页） ---------- */
async function buildIndex() {
  if (searchIndex || !pdf) return
  searchIndex = []
  for (let p = 1; p <= total.value; p++) {
    const pg = await pdf.getPage(p)
    const tc = await pg.getTextContent()
    for (const it of tc.items as any[]) if (it.str && it.str.trim()) searchIndex.push({ page: p, item: it })
  }
}
async function doSearch() {
  const q = query.value.trim().toLowerCase()
  if (!q) return
  await buildIndex()
  const pages: number[] = []
  for (const r of searchIndex || []) {
    if (r.item.str.toLowerCase().includes(q) && pages[pages.length - 1] !== r.page) pages.push(r.page)
  }
  searchResults.value = pages.map((p) => ({ page: p }))
  searchIdx.value = 0
  if (searchResults.value.length) { go(searchResults.value[0].page); ElMessage.info(`找到 ${searchResults.value.length} 页包含匹配`) }
  else ElMessage.info('未找到匹配')
}
function searchNav(dir: number) {
  if (!searchResults.value.length) return
  searchIdx.value = (searchIdx.value + dir + searchResults.value.length) % searchResults.value.length
  go(searchResults.value[searchIdx.value].page)
}

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
  const lines = [`# ${props.title || '文献'} · 荧光笔摘录`, '']
  for (const h of [...highlights.value].sort((a, b) => a.page - b.page)) {
    lines.push(`- P${h.page} [${colorName(h.color)}] ${h.text}${h.note ? `\n  - 备注：${h.note}` : ''}`)
  }
  return lines.join('\n')
}
async function exportNote() {
  if (!highlights.value.length) return ElMessage.warning('还没有标注')
  const md = buildMd()
  try {
    const r = await http.post<{ id: string }>('/notes', { title: `${props.title || '文献'} · 荧光笔摘录`, type: 'note', tags: ['论文', '摘录'], summary: '由论文阅读器一键生成', content: md })
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
    pdf = await pdfjsLib.getDocument({ data: buf }).promise
    total.value = pdf.numPages
    emit('pages', total.value)

    eventBus = new EventBus()
    viewer = new PDFViewer({
      container: viewerEl.value!,
      eventBus,
      linkService: new SimpleLinkService(),
      removePageBorders: true,
    })
    viewer.setDocument(pdf)
    eventBus.on('pagechanging', (evt: any) => {
      curPage.value = evt.pageNumber
      localStorage.setItem(posKey, String(evt.pageNumber))
      emit('page', evt.pageNumber, total.value)
    })
    eventBus.on('textlayerrendered', (evt: any) => { drawHl(evt.pageNumber) })
    const saved = Number(localStorage.getItem(posKey) || 1)
    curPage.value = Math.min(Math.max(1, saved), total.value)
    onMode()
    if (saved > 1) viewer.currentPageNumber = curPage.value
    // 布局稳定后强制按实际宽度排版（防半屏/窄窗初始测量为 0）
    requestAnimationFrame(() => { requestAnimationFrame(() => { if (viewer) viewer.currentScaleValue = 'page-width' }) })
    setTimeout(() => { if (viewer && zoomPct.value === 100) viewer.currentScaleValue = 'page-width' }, 500)
  } catch (e: any) {
    err.value = e?.message || 'PDF 加载失败'
  } finally { loading.value = false }
  window.addEventListener('resize', onWinResizeDebounced)
  document.addEventListener('mouseup', onDocMouseUp)
  document.addEventListener('pointerup', onDocMouseUp)
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('dblclick', onDblClick)
  renderThumbs()
})

function onWinResize() {
  if (viewer && zoomPct.value === 100) viewer.currentScaleValue = 'page-width'
}
// P2-M2：防抖处理器必须具名——此前注册匿名函数、卸载却 remove 具名 onWinResize，
// 引用对不上导致每次打开阅读器都永久泄漏一个 resize 监听器。
function onWinResizeDebounced() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(onWinResize, 200)
}
let resizeTimer: ReturnType<typeof setTimeout> | undefined

onBeforeUnmount(() => {
  clearTimeout(resizeTimer)
  window.removeEventListener('resize', onWinResizeDebounced)
  document.removeEventListener('mouseup', onDocMouseUp)
  document.removeEventListener('pointerup', onDocMouseUp)
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('dblclick', onDblClick)
  thumbIO?.disconnect()
  viewer?.destroy()
  viewer = null
  pdf?.destroy().catch(() => {})
  pdf = null
})
</script>

<style scoped>
.reader { display: flex; flex-direction: column; gap: 12px; }
.rtool { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 8px 14px; }
.rg { display: flex; align-items: center; gap: 8px; }
.zoomv { font-size: 12px; color: var(--txt2); min-width: 40px; text-align: center; }
.pgv { font-size: 13px; font-weight: 700; }
.reader-body { display: flex; gap: 14px; align-items: flex-start; }
.host { flex: 1; min-width: 0; position: relative; height: calc(100vh - 220px); border-radius: 12px; background: rgba(30, 41, 59, 0.06); padding: 8px; overflow: hidden; }
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
  .panel { width: 100%; max-height: none; }
  .host { flex: none; height: calc(100vh - 250px); min-height: 320px; }
}
</style>

<style>
.viewerhost .hllayer { position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 2; }
.viewerhost .page { position: relative; }
</style>
