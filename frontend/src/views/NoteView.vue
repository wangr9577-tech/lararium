<template>
  <div class="page" v-loading="loading">
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
          <el-button @click="$router.push('/notes')">返回列表</el-button>
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
    </div>
    <div v-else-if="!loading" class="miss">笔记不存在或已被删除</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Download, Plus } from '@element-plus/icons-vue'
import { http } from '../api/client'
import { renderMd } from '../utils/md'
import { hydrateImages } from '../utils/media'
import ShareDialog from '../components/ShareDialog.vue'
import WhiteboardCanvas from '../components/WhiteboardCanvas.vue'

interface Note { id: string; title: string; type: string; fmt?: string; ppt?: string; pdf?: string; parent?: string; tags: string[]; summary: string; created: string; updated: string; content: string }
interface SubNote { id: string; title: string; summary: string; fmt?: string; updated: string }

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const pdfLoading = ref(false)
const note = ref<Note | null>(null)
const wbRef = ref<InstanceType<typeof WhiteboardCanvas> | null>(null)
const articleEl = ref<HTMLElement>()
const subs = ref<SubNote[]>([])
const html = computed(() => renderMd(note.value?.content || ''))
const isInk = computed(() => note.value?.fmt === 'ink')

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
    ? `确定删除这篇笔记？其下 ${subCnt} 个子页将一并删除，不可恢复。`
    : '确定删除这篇笔记？删除后不可恢复。'
  try {
    await ElMessageBox.confirm(tip, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/notes/${note.value!.id}`)
    ElMessage.success('已删除')
    router.push('/notes')
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
    hydrateImages(articleEl.value) // 站内图片 → 带鉴权 blob URL
    if (!r.parent) loadSubs() // 顶层笔记同时加载子页列表
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

onMounted(() => {
  loadTitleMap() // 静默，不阻塞正文
  load()
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
</style>

<style>
.article .markdown-body { font-size: 15px; line-height: 1.9; color: #334155; }
html.theme-dark .article .markdown-body { color: #e2e8f0; }
.article .markdown-body h1 { font-size: 1.8em; margin: 1em 0 0.5em; padding-bottom: 8px; border-bottom: 2px solid rgba(167, 139, 250, 0.3); }
.article .markdown-body h2 { font-size: 1.45em; margin: 1em 0 0.45em; padding-left: 10px; border-left: 4px solid var(--acc2); }
.article .markdown-body h3 { font-size: 1.2em; margin: 0.9em 0 0.4em; }
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
