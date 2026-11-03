<template>
  <div class="page" v-loading="loading">
    <!-- 顶部阅读进度条：随滚动填充 -->
    <div class="read-progress" :style="{ width: progress + '%' }" />
    <div v-if="note" class="view">
      <div class="head">
        <div>
          <div class="page-title">{{ note.title }}</div>
          <div class="meta">
            <span class="chip">{{ typeLabel(note.type) }}</span>
            <span v-if="note.ppt" class="chip ppt">PPT</span>
            <span v-if="note.pdf" class="chip pdf">PDF</span>
            <el-tag v-for="t in note.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
            <span class="time">更新于 {{ note.updated }}</span>
          </div>
        </div>
        <div class="ops">
          <el-button :title="backTitle" @click="router.push(backTarget)">{{ backLabel }}</el-button>
          <template v-if="isInk">
            <el-button type="success" plain @click="exportPng">
              <el-icon style="margin-right:4px"><Download /></el-icon>导出 PNG
            </el-button>
          </template>
          <template v-else>
            <ShareDialog target="note" :ref="note.id" button-text="分享" type="success" plain />
            <el-button type="primary" plain :loading="pdfLoading" @click="exportPdf">
              <el-icon style="margin-right:4px"><Download /></el-icon>导出 PDF
            </el-button>
          </template>
          <el-button type="primary" @click="$router.push(`/notes/${note.id}/edit`)">
            <el-icon style="margin-right:4px"><EditPen /></el-icon>编辑
          </el-button>
          <el-button type="danger" plain @click="remove">删除</el-button>
        </div>
      </div>
      <!-- 目录（仅 Markdown 笔记、且标题多于 1 个时显示） -->
      <nav v-if="!isInk && toc.length > 1" class="toc glass">
        <div class="toc-title">目录</div>
        <a
          v-for="(t, i) in toc"
          :key="t.id"
          class="toc-item"
          :class="{ 'lv3': t.level === 3 }"
          :href="`#${t.id}`"
          @click.prevent="jumpTo(t.id)"
        >{{ t.text }}</a>
      </nav>
      <article class="article glass">
        <div v-if="note.summary" class="lead">{{ note.summary }}</div>
        <WhiteboardCanvas v-if="isInk" ref="wbRef" :model-value="note.content" readonly />
        <div v-else ref="articleEl" class="markdown-body" v-html="html" @click="onArticleClick" />
      </article>

      <!-- 子页面（顶层笔记可挂子页，像雅思模块的「我的子页」） -->
      <div v-if="!note.parent" class="subpanel glass">
        <div class="sp-head">
          <span class="sp-title">子页面</span>
          <span class="sp-count">{{ subs.length }}</span>
          <el-button type="primary" size="small" class="sp-new" @click="newSub">
            <el-icon style="margin-right: 4px"><Plus /></el-icon>新建子页
          </el-button>
        </div>
        <div v-if="subs.length" class="sp-list">
          <div v-for="s in subs" :key="s.id" class="sp-card" @click="$router.push(`/notes/${s.id}`)">
            <span class="sp-name">
              {{ s.title }}
              <span v-if="s.fmt === 'ink'" class="sp-ink">白板</span>
            </span>
            <span class="sp-sum">{{ s.summary || '（无摘要）' }}</span>
            <span class="sp-time">{{ s.updated?.slice(5, 16) }}</span>
          </div>
        </div>
        <div v-else class="sp-empty">还没有子页 —— 点「新建子页」，在这篇笔记下面挂子页面</div>
      </div>

      <!-- 上一篇 / 下一篇（按列表顺序：顶层=更新时间倒序；子页=同一父页的子页顺序） -->
      <div v-if="prevNote || nextNote" class="pn">
        <button type="button" class="pn-item" :class="{ off: !prevNote }" :disabled="!prevNote"
          @click="prevNote && goNote(prevNote.id)">
          <span class="pn-k">← 上一篇</span>
          <span class="pn-t">{{ prevNote ? prevNote.title : '没有更新的文章' }}</span>
          <span class="pn-s">{{ prevNote?.summary || '' }}</span>
        </button>
        <button type="button" class="pn-item pn-r" :class="{ off: !nextNote }" :disabled="!nextNote"
          @click="nextNote && goNote(nextNote.id)">
          <span class="pn-k">下一篇 →</span>
          <span class="pn-t">{{ nextNote ? nextNote.title : '没有更早的文章' }}</span>
          <span class="pn-s">{{ nextNote?.summary || '' }}</span>
        </button>
      </div>
    </div>
    <div v-else-if="!loading" class="miss">笔记不存在或已被删除</div>

    <!-- 回到顶部：滚动超过 400px 出现 -->
    <button v-if="showTop" class="to-top" title="回到顶部" @click="toTop">
      <el-icon><ArrowUp /></el-icon>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw, type RouteLocationRaw } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Download, Plus, ArrowUp } from '@element-plus/icons-vue'
import { http } from '../api/client'
import { renderMd } from '../utils/md'
import { hydrateImages } from '../utils/media'
import ShareDialog from '../components/ShareDialog.vue'
import WhiteboardCanvas from '../components/WhiteboardCanvas.vue'

interface Note { id: string; title: string; type: string; fmt?: string; ppt?: string; pdf?: string; folder?: string; parent?: string; tags: string[]; summary: string; created: string; updated: string; content: string }
interface SubNote { id: string; title: string; summary: string; fmt?: string; updated: string }

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const pdfLoading = ref(false)
const note = ref<Note | null>(null)
const wbRef = ref<InstanceType<typeof WhiteboardCanvas> | null>(null)
const articleEl = ref<HTMLElement>()
/** 真实滚动容器（AppShell 的 .content；window 永远不滚动，scrollY 恒为 0） */
const host = ref<HTMLElement | null>(null)
const subs = ref<SubNote[]>([])
const html = computed(() => renderMd(note.value?.content || ''))
const isInk = computed(() => note.value?.fmt === 'ink')

/* ---------------- 返回列表：回到「最邻近一层」，不直接跳根目录 ---------------- */

/** 「返回列表」目标：
 *  · 普通文章 → 其所属目录（folder 全路径，如 'A/B'）；folder 为空=未分类 → 根视图
 *    （未分类文章本来就只在根视图显示，根视图即它最近的一层）；
 *  · 子页（parent 非空）→ 父文章页（子页只出现在父页的「子页面」面板里，目录列表不显示它）。
 *  进入阅读页时携带的 type/tag/q 筛选一并带回，返回后仍是同一筛选视图。 */
const backTarget = computed<RouteLocationRaw>(() => {
  const query: LocationQueryRaw = {}
  for (const k of ['type', 'tag', 'q'] as const) {
    const v = route.query[k]
    if (typeof v === 'string' && v) query[k] = v
  }
  const cur = note.value
  if (cur?.parent) return { path: `/notes/${cur.parent}`, query } // 子页：回父页
  if (cur?.folder) query.dir = cur.folder // 回到该文章所在的最邻近目录
  return { path: '/notes', query }
})
/** 按钮文案：子页回父页，用「返回上级」更准确 */
const backLabel = computed(() => (note.value?.parent ? '返回上级' : '返回列表'))
/** 悬停提示：明确回到哪一层 */
const backTitle = computed(() => {
  if (note.value?.parent) return '返回所属父文章'
  const f = note.value?.folder
  return f ? `返回「${f}」列表` : '返回未分类列表'
})

/** 篇间跳转（上一篇/下一篇）：带上当前 query（筛选态），换篇后「返回列表」语义不变 */
function goNote(id: string) {
  router.push({ path: `/notes/${id}`, query: route.query })
}

/* ---------------- 长文阅读体验：目录(TOC) / 顶部阅读进度条 / 回到顶部 ---------------- */

/** 目录条目（h1/h2/h3），id 用稳定英文锚点，不用中文 */
const toc = ref<{ id: string; text: string; level: number }[]>([])
/** 阅读进度（0-100），驱动顶部进度条宽度 */
const progress = ref(0)
/** 是否显示「回到顶部」按钮（滚动超过 400px 才出现） */
const showTop = ref(false)

/** 从正文构建目录：取 h1/h2/h3，赋稳定 id，跳过空标题 */
function buildToc() {
  if (!articleEl.value) { toc.value = []; return }
  const heads = articleEl.value.querySelectorAll('h1, h2, h3')
  const list: { id: string; text: string; level: number }[] = []
  heads.forEach((h, index) => {
    const text = (h.textContent || '').trim()
    if (!text) return
    h.id = `toc-${index + 1}`
    list.push({ id: h.id, text, level: Number(h.tagName.slice(1)) })
  })
  toc.value = list
}

/** 目录点击平滑滚动到对应标题（视觉留白改由 CSS scroll-margin-top 处理；嵌套滚动下 window.scrollBy 无效） */
function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 回到顶部：对真实滚动容器生效（拿不到再回退 window） */
function toTop() {
  if (host.value) host.value.scrollTo({ top: 0, behavior: 'smooth' })
  else window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 滚动：更新阅读进度条宽度 + 控制「回到顶部」显隐（有容器用容器计算，否则回退 window） */
function onScroll() {
  if (host.value) {
    const el = host.value
    const max = el.scrollHeight - el.clientHeight
    progress.value = max > 0 ? Math.min(100, Math.max(0, (el.scrollTop / max) * 100)) : 0
    showTop.value = el.scrollTop > 400
    return
  }
  const max = document.documentElement.scrollHeight - window.innerHeight
  progress.value = max > 0 ? Math.min(100, Math.max(0, (window.scrollY / max) * 100)) : 0
  showTop.value = window.scrollY > 400
}

/** 把 scroll 监听绑定到真实滚动容器（.content）；articleEl 就绪后调用，换篇笔记需重新绑定 */
function attachScroll() {
  detachScroll()
  host.value = (articleEl.value?.closest('.content') as HTMLElement | null)
  const target: HTMLElement | Window = host.value || window
  target.addEventListener('scroll', onScroll, { passive: true })
  onScroll() // 绑定后立即校准一次
}

/** 解绑 scroll 监听（attachScroll 的逆操作） */
function detachScroll() {
  const target: HTMLElement | Window = host.value || window
  target.removeEventListener('scroll', onScroll)
}

/* ---------------- 子页面（父页面笔记挂载的 md 子页） ---------------- */

async function loadSubs() {
  const id = note.value?.id
  if (!id || note.value?.parent) { subs.value = []; return }
  try {
    const r = await http.get<{ items: SubNote[] }>(`/notes?parent=${id}`)
    subs.value = r.items
  } catch { subs.value = [] }
}

/** 新建子页：命名窗口（可留空=未命名，之后在子页阅读/列表改名） */
async function newSub() {
  if (!note.value) return
  let title = ''
  try {
    const r = await ElMessageBox.prompt('子页标题（可留空，之后可改名）', '新建子页', {
      confirmButtonText: '创建', cancelButtonText: '取消', inputValue: '',
    })
    title = (r.value || '').trim()
  } catch { return }
  router.push(title
    ? `/notes/new?parent=${note.value.id}&title=${encodeURIComponent(title)}`
    : `/notes/new?parent=${note.value.id}`)
}

/** 相邻文章候选：顶层笔记=全部顶层笔记（后端按文件更新时间倒序）；子页=同一父页下的子页列表 */
const siblings = ref<{ id: string; title: string; summary: string }[]>([])
const navIdx = computed(() => siblings.value.findIndex((s) => s.id === note.value?.id))
/** 上一篇=列表里更靠前（更新）的一篇；下一篇=更靠后（更旧）的一篇 */
const prevNote = computed(() => (navIdx.value > 0 ? siblings.value[navIdx.value - 1] : null))
const nextNote = computed(() => (navIdx.value >= 0 && navIdx.value < siblings.value.length - 1 ? siblings.value[navIdx.value + 1] : null))

/** 加载相邻文章列表（顶层与子页都调；401/423 或异常时静默，不阻断正文） */
async function loadSiblings() {
  const cur = note.value
  if (!cur) { siblings.value = []; return }
  try {
    // 顶层笔记：/notes?module= 返回全部顶层普通笔记（后端已按更新时间倒序）；子页：其父页下的子页列表
    const url = cur.parent ? `/notes?parent=${encodeURIComponent(cur.parent)}` : '/notes?module='
    const r = await http.get<{ items: { id: string; title: string; summary: string }[] }>(url)
    siblings.value = r.items || []
  } catch { siblings.value = [] } // 401/423 或异常时静默，不阻断正文
}

/* ---------------- 站内引用：点击跳转 + 悬停显示目标文章标题 ---------------- */

/** id → 标题 映射（用于给站内引用链接补 title 提示），后台静默加载 */
let titleMap: Record<string, string> = {}

async function loadTitleMap() {
  try {
    const r = await http.get<{ items: { id: string; title: string }[] }>('/notes?module=')
    titleMap = Object.fromEntries((r.items || []).map((n) => [n.id, n.title]))
  } catch { /* 401/423 忽略，无提示也不影响跳转 */ }
}

/** 渲染完成后给站内链接补 title 属性（悬停显示目标文章标题） */
function fillInternalTitles() {
  if (!articleEl.value) return
  articleEl.value.querySelectorAll<HTMLAnchorElement>('a[href^="/notes/"]').forEach((a) => {
    const id = (a.getAttribute('href') || '').replace(/^\/notes\//, '').trim()
    const t = id ? titleMap[id] : ''
    if (t) a.setAttribute('title', `阅读：《${t}》`)
  })
}

/** 正文点击：站内 /notes/... 链接走 SPA 跳转，不整页刷新 */
function onArticleClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('a')
  if (!a) return
  const href = a.getAttribute('href') || ''
  if (href.startsWith('/notes/')) {
    e.preventDefault()
    router.push(href)
  }
}

async function exportPdf() {
  if (!note.value) return
  pdfLoading.value = true
  try {
    const blob = await http.blob(`/notes/${note.value.id}/export`)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${note.value.title.replace(/[\\/:*?"<>|]/g, '_') || note.value.id}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    if (e?.response?.status === 503) ElMessage.error('服务端 PDF 工具未就绪（pandoc / TinyTeX）')
    else ElMessage.error(e?.response?.data?.detail || '导出失败，请稍后重试')
  } finally {
    pdfLoading.value = false
  }
}

function typeLabel(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

/** 白板笔记导出 PNG（离屏渲染整页） */
function exportPng() {
  if (!note.value) return
  const png = wbRef.value?.renderPng()
  if (!png) return ElMessage.warning('画布尚未就绪')
  const a = document.createElement('a')
  a.href = png
  a.download = `${note.value.title.replace(/[\\/:*?"<>|]/g, '_') || note.value.id}.png`
  a.click()
  ElMessage.success('已导出 PNG 图片')
}

async function remove() {
  const subCnt = subs.value.length
  const tip = subCnt
    ? `确定删除这篇笔记？其下 ${subCnt} 个子页将一并删除（进回收站，可随时恢复）。`
    : '确定删除这篇笔记？删除后进入回收站，可随时恢复。'
  try {
    await ElMessageBox.confirm(tip, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/notes/${note.value!.id}`)
    ElMessage.success('已移入回收站（可在回收站恢复）')
    router.push(backTarget.value) // 删除后回到该笔记原本所在的那一层（同「返回列表」语义）
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function load() {
  loading.value = true
  try {
    const r = await http.get<Note>(`/notes/${route.params.id}`)
    note.value = r
    document.title = `${r.title} · 阅读`
    await nextTick()
    fillInternalTitles()
    buildToc() // 正文渲染完成后构建目录
    attachScroll() // articleEl 已存在：重新绑定到正确的滚动容器并校准
    hydrateImages(articleEl.value) // 站内图片 → 带鉴权 blob URL
    if (!r.parent) loadSubs() // 顶层笔记同时加载子页列表
    loadSiblings() // 顶层与子页都加载「上一篇/下一篇」候选列表
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '加载失败')
    }
  } finally {
    loading.value = false
  }
}

// 阅读页内互相跳转（SPA）时按路由参数重载文章
watch(() => route.params.id, load)

// 正文变化（如换篇笔记、内容重渲染）后重建目录
watch(html, async () => { await nextTick(); buildToc() })

onMounted(() => {
  loadTitleMap() // 静默，不阻塞正文
  load()
  attachScroll() // 初始绑定（此时 articleEl 可能还没渲染，回退 window；load 成功后会重新绑定到 .content）
})

onBeforeUnmount(() => {
  detachScroll()
})
</script>

<style scoped>
/* 阅读页放宽：正文限宽加大、页面容器加宽，缩小两侧留白 */
.page { max-width: 1760px; }
/* 阅读页铺满：白板/PDF/PPT 多页要看全，不再压到 1200px */
.view { max-width: none; margin: 0 auto; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.time { font-size: 12px; color: var(--txt2); margin-left: 4px; }
.chip.ppt {
  background: linear-gradient(135deg, rgba(251, 146, 60, 0.18), rgba(220, 38, 38, 0.14));
  color: #ea580c; border: 1px solid rgba(251, 146, 60, 0.45); font-weight: 700;
}
.chip.pdf {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(99, 102, 241, 0.14));
  color: #2563eb; border: 1px solid rgba(59, 130, 246, 0.45); font-weight: 700;
}
.ops { display: flex; gap: 8px; }
.article { padding: 34px 44px; }
/* 白板类笔记（PPT/PDF/手写）：收窄内边距，把宽度让给纸面 */
.article:has(> .wb) { padding: 18px 18px 22px; }

/* ---------- 子页面面板 ---------- */
.subpanel { margin-top: 20px; padding: 18px 22px; border-radius: 14px; }
.sp-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sp-title { font-size: 15px; font-weight: 700; color: var(--txt1); }
.sp-count {
  font-size: 12px; color: var(--acc2); background: rgba(139, 92, 246, 0.14);
  border-radius: 10px; padding: 1px 9px; font-weight: 700;
}
.sp-new { margin-left: auto; }
.sp-list { display: flex; flex-direction: column; gap: 8px; }
.sp-card {
  display: flex; align-items: center; gap: 12px;
  background: rgba(148, 163, 184, 0.07); border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px; padding: 10px 14px; cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.sp-card:hover { border-color: rgba(139, 92, 246, 0.55); background: rgba(139, 92, 246, 0.08); }
.sp-name { font-weight: 600; color: var(--txt1); min-width: 120px; display: inline-flex; align-items: center; gap: 6px; }
.sp-ink {
  font-size: 11px; color: #ea580c; border: 1px solid rgba(234, 88, 12, 0.5);
  border-radius: 5px; padding: 0 5px; font-weight: 600; transform: scale(0.92);
}
.sp-sum { flex: 1; color: var(--txt2); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp-time { color: var(--txt3); font-size: 12px; flex-shrink: 0; }
.sp-empty { color: var(--txt3); font-size: 13px; padding: 8px 2px; }
.lead {
  color: var(--txt3); border-left: 4px solid var(--acc3); background: rgba(56, 189, 248, 0.08);
  padding: 8px 14px; border-radius: 0 10px 10px 0; margin-bottom: 18px; font-size: 14px;
}
html.theme-dark .lead { color: var(--txt2); }
.miss { text-align: center; color: var(--txt2); padding: 60px 0; }

/* ---------- 目录（TOC） ---------- */
.toc { padding: 12px 16px; margin-bottom: 14px; border-radius: 14px; }
.toc-title { font-size: 12.5px; font-weight: 700; color: var(--txt3); margin-bottom: 6px; }
.toc-item {
  display: block; font-size: 13px; color: var(--txt2); text-decoration: none;
  padding: 2px 0; border-left: 2px solid transparent; padding-left: 8px;
  transition: color 0.15s, border-color 0.15s;
}
.toc-item:hover { color: var(--acc2); border-left-color: var(--acc2); }
.toc-item.lv3 { padding-left: 22px; font-size: 12.5px; }

/* ---------- 顶部阅读进度条 ---------- */
.read-progress {
  position: fixed; top: 0; left: 0; height: 3px; z-index: 2000;
  background: var(--acc-grad); transition: width 0.1s linear;
}

/* ---------- 回到顶部 ---------- */
.to-top {
  position: fixed; right: 26px; bottom: 30px; z-index: 2000;
  width: 40px; height: 40px; border-radius: 50%; border: none; cursor: pointer;
  color: #fff; background: var(--acc-grad); box-shadow: 0 8px 22px rgba(139, 92, 246, 0.35);
  display: grid; place-items: center; font-size: 17px;
}

/* ---------- 上一篇 / 下一篇 ---------- */
.pn { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.pn-item {
  display: grid; gap: 4px; text-align: left; padding: 14px 18px; border-radius: 14px;
  cursor: pointer; font-family: inherit; color: var(--txt1);
  border: 1px solid rgba(148, 163, 184, 0.22); background: rgba(148, 163, 184, 0.06);
  transition: border-color 0.15s, transform 0.15s;
}
.pn-item:hover:not(.off) { border-color: var(--acc2); transform: translateY(-2px); }
.pn-item.off { opacity: 0.55; cursor: default; }
.pn-r { text-align: right; }
.pn-k { font-size: 12px; color: var(--txt3); }
.pn-t { font-size: 14.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pn-s { font-size: 12.5px; color: var(--txt2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 700px) { .pn { grid-template-columns: 1fr; } }
</style>

<style>
.article .markdown-body { font-size: 15px; line-height: 1.9; color: #334155; }
html.theme-dark .article .markdown-body { color: #e2e8f0; }
.article .markdown-body h1 { font-size: 1.8em; margin: 1em 0 0.5em; padding-bottom: 8px; border-bottom: 2px solid rgba(167, 139, 250, 0.3); }
.article .markdown-body h2 { font-size: 1.45em; margin: 1em 0 0.45em; padding-left: 10px; border-left: 4px solid var(--acc2); }
.article .markdown-body h3 { font-size: 1.2em; margin: 0.9em 0 0.4em; }
/* 目录跳转时给正文标题留滚动留白（嵌套滚动容器下 window.scrollBy 无效，改用 CSS） */
.article .markdown-body h1, .article .markdown-body h2, .article .markdown-body h3 { scroll-margin-top: 12px; }
.article .markdown-body p { margin: 0.65em 0; }
.article .markdown-body code { background: rgba(139, 92, 246, 0.12); padding: 1px 7px; border-radius: 6px; font-family: Consolas, monospace; font-size: 0.92em; }
.article .markdown-body pre { background: rgba(15, 23, 42, 0.92); color: #e2e8f0; padding: 14px 18px; border-radius: 12px; overflow-x: auto; }
.article .markdown-body pre code { background: transparent; color: inherit; padding: 0; }
.article .markdown-body blockquote { margin: 0.8em 0; padding: 6px 16px; color: var(--txt3); border-left: 4px solid var(--acc3); background: rgba(56, 189, 248, 0.07); border-radius: 0 10px 10px 0; }
html.theme-dark .article .markdown-body blockquote { color: var(--txt2); }
.article .markdown-body a { color: var(--acc2); }
/* 站内引用链接（/notes/...）：虚线下划线 + 加粗，区分站外普通链接 */
.article .markdown-body a[href^="/notes/"] {
  text-decoration: none;
  border-bottom: 1.5px dashed rgba(139, 92, 246, 0.55);
  padding-bottom: 1px;
  font-weight: 600;
}
.article .markdown-body a[href^="/notes/"]:hover { border-bottom-style: solid; }
.article .markdown-body img { max-width: 100%; border-radius: 10px; }
.article .markdown-body table { border-collapse: collapse; margin: 0.8em 0; }
.article .markdown-body th, .article .markdown-body td { border: 1px solid rgba(148, 163, 184, 0.45); padding: 6px 14px; }
.article .markdown-body th { background: rgba(167, 139, 250, 0.12); }
.article .markdown-body ul, .article .markdown-body ol { padding-left: 1.7em; margin: 0.6em 0; }
.article .markdown-body hr { border: none; border-top: 2px dashed rgba(148, 163, 184, 0.4); margin: 1.4em 0; }
.article .markdown-body .katex-display { overflow-x: auto; overflow-y: hidden; }
</style>
