<template>
  <div class="page" :class="{ immersive }" v-loading="loading">
    <div class="edit-head">
      <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon>返回</el-button>
      <span class="doc-title" :title="form.title || '未命名'">{{ form.title.trim() || '未命名' }}</span>
      <div class="fmt-seg" title="正文形式：文本（Markdown）与白板手写二选一">
        <button :class="{ on: form.fmt === 'md' }" @click="pickFmt('md')">文本</button>
        <button :class="{ on: form.fmt === 'ink' }" @click="pickFmt('ink')">白板手写</button>
      </div>
      <el-button v-if="form.fmt === 'ink'" text class="fs-btn" :title="immersive ? '退出全屏' : '全屏书写（隐藏顶栏底栏，纸面吃满屏幕）'" @click="toggleImmersive">
        <el-icon style="margin-right:4px"><FullScreen /></el-icon>{{ immersive ? '退出全屏' : '全屏' }}
      </el-button>
    </div>

    <WhiteboardCanvas v-if="form.fmt === 'ink'" ref="wbRef" v-model="form.content" />
    <template v-else>
      <!-- 博客/笔记（文本）：复用日记的 Vditor 即时渲染（Typora 式不分屏，标题/加粗/公式/表格边打边呈现） -->
      <div class="md-toolbar">
        <el-button size="small" text @click="refOpen = true">
          <el-icon style="margin-right:4px"><Connection /></el-icon>引用文章
        </el-button>
      </div>
      <VditorEditor ref="vdRef" v-model="form.content" :min-height="560" @save="doSave" />
    </template>

    <div class="foot">
      <el-button v-if="form.fmt === 'ink'" @click="exportPng">导出 PNG</el-button>
      <el-button @click="goBack">取消</el-button>
      <el-button type="primary" :loading="saving" @click="doSave">
        <el-icon style="margin-right:4px"><Check /></el-icon>{{ isNew ? '创建' : '保存修改' }}
      </el-button>
    </div>

    <!-- 引用其它文章：选一篇，在光标处插入站内链接 [标题](/notes/id)（有选中文字则包裹为链接文字） -->
    <el-dialog v-model="refOpen" title="引用其它文章" width="560px" @open="onRefOpen">
      <div class="mde-rf-tip">选择一篇文章，将在光标处插入站内引用链接（或包裹当前选中文字），阅读时点击即可跳转</div>
      <el-input v-model="refQ" placeholder="搜索标题 / 摘要 / 标签…" clearable>
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div class="mde-rf-list">
        <button v-for="n in refList" :key="n.id" type="button" class="mde-rf-item" @click="pickRef(n)">
          <span class="mde-rf-type">{{ typeLabel(n.type) }}</span>
          <span class="mde-rf-title">{{ n.title }}</span>
          <span v-if="n.summary" class="mde-rf-sum">{{ n.summary }}</span>
        </button>
        <div v-if="!refList.length" class="mde-rf-empty">没有可引用的文章（已排除当前这篇）</div>
      </div>
      <template #footer>
        <el-button @click="refOpen = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Check, Connection, FullScreen, Search } from '@element-plus/icons-vue'
import { getToken, http } from '../api/client'
import { workbenchApi } from '../api/workbench'
import { assistantApi } from '../api/assistant'
import VditorEditor from '../components/VditorEditor.vue'
import WhiteboardCanvas from '../components/WhiteboardCanvas.vue'

const AUTO_SAVE_MS = 5 * 60 * 1000 // 每 5 分钟自动保存

const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id as string) || '')
const isNew = computed(() => route.path.endsWith('/new') || !id.value)

const loading = ref(true)
const saving = ref(false)
const autoBusy = ref(false)
/** 全屏书写：隐藏顶栏/底栏，纸面吃满屏幕（并尽量进入浏览器全屏） */
const immersive = ref(false)

async function toggleImmersive() {
  immersive.value = !immersive.value
  try {
    if (immersive.value && !document.fullscreenElement) await document.documentElement.requestFullscreen()
    else if (!immersive.value && document.fullscreenElement) await document.exitFullscreen()
  } catch { /* 浏览器拒绝全屏时仅使用紧凑布局 */ }
}

function onFsChange() {
  if (!document.fullscreenElement) immersive.value = false
}
const form = reactive({ title: '', type: 'blog', fmt: 'md', folder: '', parent: '', summary: '', content: '' })
const tagsText = ref('')
/** 白板画布组件实例（导出 PNG 用） */
const wbRef = ref<InstanceType<typeof WhiteboardCanvas> | null>(null)
/** 新建页被自动保存首次建档后的笔记 id：继续停在编辑态，之后自动保存走 PUT */
const autoId = ref('')
/** 最近一次成功保存时间（HH:MM:SS），顶栏展示 */
const lastSavedAt = ref('')
/** 工作台来源事项 id（/notes/new?source_item_id=<id>）：首次建档成功后自动关联一次 */
const sourceItemId = String(route.query.source_item_id || '')
/** 助手来源记录 id（/notes/new?source_record_id=<id>）：初始化拉取草稿，首次建档成功后自动关联 */
const sourceRecordId = String(route.query.source_record_id || '')
/** 已为该笔记建立过关联的笔记 id（按 id 记忆，保证「只关联一次」而不误伤用户手动移除） */
const linkedFor = ref('')
const linkedRecordFor = ref('')

/** 来源查询参数：带来源时透传，返回/转阅读页都不丢来源（避免空 query 键） */
function sourceQ(): Record<string, string> {
  const q: Record<string, string> = {}
  if (sourceItemId) q.source_item_id = sourceItemId
  if (sourceRecordId) q.source_record_id = sourceRecordId
  return q
}

/** 最近一次成功保存时的字段快照，用于判定「是否有改动」 */
const saved = reactive({ title: '', type: 'blog', fmt: 'md', folder: '', parent: '', summary: '', content: '', tagsKey: '' })
let timer: ReturnType<typeof setInterval> | undefined
/** 白板「停笔即存」：内容变化后 1.5 秒无新笔迹则自动保存一次 */
let inkTimer: ReturnType<typeof setTimeout> | undefined
function scheduleInkSave() {
  clearTimeout(inkTimer)
  inkTimer = setTimeout(() => { tryAutoSave() }, 1500)
}
watch(() => form.content, () => {
  if (form.fmt === 'ink') scheduleInkSave()
})

/* ---------------- 改动判定与快照 ---------------- */

function parseTags(): string[] {
  return tagsText.value.split(/[,，]/).map((t) => t.trim()).filter(Boolean)
}

/** 与服务器归一化一致：标题留空按「未命名」计 */
function norm() {
  return {
    title: form.title.trim() || '未命名',
    type: form.type,
    fmt: form.fmt,
    folder: form.folder || '',
    parent: form.parent || '',
    summary: form.summary.trim(),
    tagsKey: parseTags().join(','),
    content: form.content,
  }
}

function isDirty(): boolean {
  const n = norm()
  return n.title !== saved.title || n.type !== saved.type || n.fmt !== saved.fmt || n.folder !== saved.folder
    || n.parent !== saved.parent || n.summary !== saved.summary || n.tagsKey !== saved.tagsKey || n.content !== saved.content
}

function markSaved(updatedText?: string) {
  Object.assign(saved, norm())
  if (updatedText) {
    const s = String(updatedText)
    lastSavedAt.value = s.includes(':') ? s.slice(11, 19) : s
  }
}

function payloadRaw() {
  return { title: form.title.trim(), type: form.type, fmt: form.fmt, folder: form.folder || '', parent: form.parent || '', summary: form.summary.trim(), content: form.content, tags: parseTags() }
}

/* ---------------- 正文形式：文本 / 白板手写（互斥，切换需确认） ---------------- */

/** 空白白板页的初始笔迹 JSON（默认竖版 A4 比例） */
function emptyInkPayload(): string {
  return JSON.stringify({ v: 1, page: { w: 1000, h: 1414 }, strokes: [] })
}

function inkHasContent(raw: string): boolean {
  if (!raw.trim()) return false
  try {
    const o = JSON.parse(raw)
    const pages = Array.isArray(o?.pages) ? o.pages : [o]
    return pages.some((page: any) =>
      (Array.isArray(page?.strokes) && page.strokes.length > 0) ||
      (Array.isArray(page?.images) && page.images.length > 0))
  } catch {
    return true
  }
}

async function pickFmt(next: 'md' | 'ink') {
  if (next === form.fmt) return
  if (next === 'ink') {
    // 文本 → 白板：现有文本将被清空（白板存不了 Markdown）
    if (form.content.trim()) {
      try {
        await ElMessageBox.confirm(
          '切换为「白板手写」将清空当前文本正文，且不可恢复。确定切换吗？',
          '切换正文形式', { type: 'warning', confirmButtonText: '切换并清空', cancelButtonText: '取消' })
      } catch { return }
      form.content = ''
    }
    form.fmt = 'ink'
    form.content = form.content || emptyInkPayload()
    ElMessage.success('已切换为白板手写：用触控笔或鼠标在白色纸面上书写')
  } else {
    // 白板 → 文本：现有笔迹将被清空
    if (inkHasContent(form.content)) {
      try {
        await ElMessageBox.confirm(
          '切换为「文本」将清空当前白板内容，且不可恢复。确定切换吗？',
          '切换正文形式', { type: 'warning', confirmButtonText: '切换并清空', cancelButtonText: '取消' })
      } catch { return }
    }
    form.content = ''
    form.fmt = 'md'
    ElMessage.success('已切换为文本笔记')
  }
}

/** 白板笔记导出为 PNG（画布按页面比例离屏渲染） */
function exportPng() {
  const png = wbRef.value?.renderPng()
  if (!png) return ElMessage.warning('画布尚未就绪')
  const a = document.createElement('a')
  a.href = png
  a.download = `${form.title.trim().replace(/[\\/:*?"<>|]/g, '_') || '未命名'}.png`
  a.click()
  ElMessage.success('已导出 PNG 图片')
}

/* ---------------- 引用其它文章（站内链接 [标题](/notes/id)，光标处插入） ---------------- */

/** Vditor 编辑器实例（引用文章对话框用它 insertMD 插入 / getSelectionText 取选中文字） */
const vdRef = ref<InstanceType<typeof VditorEditor> | null>(null)

interface RefNote { id: string; title: string; type: string; summary: string; tags: string[] }

const refOpen = ref(false)
const refQ = ref('')
const refCandidates = ref<RefNote[]>([])

const refList = computed(() => {
  const q = refQ.value.trim().toLowerCase()
  return refCandidates.value.filter((n) => {
    if (id.value && n.id === id.value) return false // 不引用自己
    if (!q) return true
    return `${n.title} ${n.summary} ${n.tags.join(' ')}`.toLowerCase().includes(q)
  })
})

function typeLabel(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

/** 打开引用面板时按需加载文章列表（默认列表：普通博客/笔记，不含雅思子页） */
async function onRefOpen() {
  if (refCandidates.value.length) return
  try {
    const r = await http.get<{ items: RefNote[] }>('/notes?module=')
    refCandidates.value = r.items || []
  } catch { /* 401/423 忽略 */ }
}

/** 选中文章：光标处插入 [文字](/notes/id)；有选中文字则用选中文字（insertMD 会先删除选中） */
function pickRef(n: RefNote) {
  if (!vdRef.value) return
  const sel = (vdRef.value.getSelectionText() || '').trim()
  // 链接文字防破坏 Markdown 语法：去掉方括号/圆括号
  const text = sel.replace(/[[\]()]/g, '') || n.title || '文章'
  vdRef.value.insertMD(`[${text}](/notes/${n.id})`)
  refOpen.value = false
}

/* ---------------- 工作台来源事项：建档后自动加入「相关资料」 ---------------- */

/** 首次创建成功后把笔记链接到来源事项；幂等（后端 UNIQUE + INSERT OR IGNORE），
 *  失败只提示可重试，绝不误报成功、绝不阻塞保存流程。
 *  retry=true 为重试路径：跳过「是否已关联」查询，直接再试一次（最多重试一次，避免连环弹窗）。 */
async function linkSourceItem(noteId: string, retry = false) {
  if (!sourceItemId || !noteId) return
  if (linkedFor.value === noteId) return // 这条笔记本次已关联过：自动保存与手动保存抢跑也只关联一次
  const sid = Number(sourceItemId)
  if (!Number.isInteger(sid) || sid <= 0) return
  try {
    if (!retry) {
      // 先查状态：用户可能已手动移除过关联，移除后不再自动重建
      const st = await workbenchApi.noteLinkStatus(sid, noteId)
      if (st?.linked) { linkedFor.value = noteId; return }
    }
    await workbenchApi.addLink(sid, 'note', noteId)
    linkedFor.value = noteId
    ElMessage.success('已加入来源事项的相关资料')
  } catch {
    // 失败不设 linkedFor：之后任意一次保存都会自动重试；也不抛出，保证笔记保存/跳转不被阻塞
    ElMessage.warning({
      message: '笔记已保存，但加入来源事项的相关资料失败，可在事项里重新关联',
      duration: 6000,
    })
    if (retry) return // 已重试过一次，不再连环提示
    try {
      await ElMessageBox.confirm('要重试关联吗？', '关联失败', {
        confirmButtonText: '重试', cancelButtonText: '稍后再说', type: 'warning',
      })
    } catch { return }
    await linkSourceItem(noteId, true)
  }
}

/** 首次创建成功后把笔记关联到来源助手记录（幂等） */
async function linkSourceRecord(noteId: string) {
  if (!sourceRecordId || !noteId) return
  if (linkedRecordFor.value === noteId) return
  try {
    await assistantApi.linkRecord(sourceRecordId, { target_type: 'note', target_id: noteId })
    linkedRecordFor.value = noteId
    ElMessage.success('已自动关联助手记录')
  } catch {
    // 允许静默失败，避免打断笔记主流程
  }
}

/* ---------------- 自动保存 ---------------- */

/** 有改动则保存一次；返回 true=无事/成功，false=保存失败 */
async function tryAutoSave(): Promise<boolean> {
  if (autoBusy.value || !isDirty()) return true
  const rawTitle = form.title.trim()
  if (!rawTitle && !form.content.trim()) return true // 完全空白不建档
  // 白板尚无任何笔迹且无标题：不自动建档（避免误切换就产生空笔记）
  if (!rawTitle && form.fmt === 'ink' && !inkHasContent(form.content)) return true
  autoBusy.value = true
  const body = { ...payloadRaw(), title: rawTitle || '未命名' }
  try {
    if (isNew.value && !autoId.value) {
      // 新建页首次自动保存 = 自动建档（标题空则暂名「未命名」），之后停在编辑态续存
      const r = await http.post<{ id: string; updated: string }>('/notes', body)
      autoId.value = r.id
      markSaved(r.updated)
      await linkSourceItem(r.id) // 来自工作台：首次建档后自动加入来源事项的相关资料（幂等）
      await linkSourceRecord(r.id) // 来自助手：自动建立关联
    } else {
      const target = autoId.value || id.value
      if (!target) return true
      const r = await http.put<{ updated: string }>(`/notes/${target}`, body)
      markSaved(r.updated)
    }
    return true
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error('自动保存失败：' + (e?.response?.data?.detail || '请检查网络后手动保存'))
    }
    return false
  } finally {
    autoBusy.value = false
  }
}

function onPageHide() {
  // 浏览器直接关标签/切走：尽力用 keepalive 补一次保存（最坏丢 ≤5 分钟）
  if (autoBusy.value || !isDirty()) return
  const rawTitle = form.title.trim()
  if (!rawTitle && !form.content.trim()) return
  const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` }
  const body = JSON.stringify({ ...payloadRaw(), title: rawTitle || '未命名' })
  const target = autoId.value || id.value
  const url = isNew.value && !autoId.value ? '/api/notes' : target ? `/api/notes/${target}` : ''
  if (!url) return
  fetch(url, { method: isNew.value && !autoId.value ? 'POST' : 'PUT', headers, body, keepalive: true }).catch(() => {})
}

/* ---------------- 手动保存（按钮 / Ctrl+S） ---------------- */

async function doSave() {
  // 允许"暂时不命名"：标题留空按「未命名」创建（可在列表改名）
  const body = { ...payloadRaw(), title: form.title.trim() || '未命名' }
  saving.value = true
  try {
    if (isNew.value && !autoId.value) {
      const r = await http.post<{ id: string; updated: string }>('/notes', body)
      autoId.value = r.id
      markSaved(r.updated)
      ElMessage.success('创建成功')
      await linkSourceItem(r.id) // 来自工作台：自动加入来源事项的相关资料（先等提示，再跳转，避免反馈被卸载吞掉）
      await linkSourceRecord(r.id) // 来自助手：自动建立关联
      router.replace({ path: `/notes/${r.id}`, query: sourceQ() })
    } else {
      const target = autoId.value || id.value
      if (!target) return
      const r = await http.put<{ updated: string }>(`/notes/${target}`, body)
      markSaved(r.updated)
      ElMessage.success('已保存')
      if (isNew.value && autoId.value) router.replace({ path: `/notes/${target}`, query: sourceQ() }) // 自动建档过的草稿，点创建=去阅读页
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function goBack() {
  if (id.value && !isNew.value) router.push({ path: `/notes/${id.value}`, query: sourceQ() })
  else router.push('/notes')
}

/* 离开编辑页时若有改动先补存一次；保存失败不再放行（P0：防静默丢稿，让用户选择去留） */
onBeforeRouteLeave(async () => {
  if (await tryAutoSave()) return true
  try {
    await ElMessageBox.confirm('自动保存失败，离开可能丢失本次修改。仍要放弃并离开吗？', '保存失败', {
      confirmButtonText: '放弃并离开', cancelButtonText: '留下重试', type: 'warning',
    })
    return true
  } catch {
    return false
  }
})

onMounted(async () => {
  window.addEventListener('pagehide', onPageHide)
  document.addEventListener('fullscreenchange', onFsChange)
  if (isNew.value) {
    // 新建：从「命名窗口」带入的标题（可空 → 未命名，在列表改名）
    // 子页：/notes/new?parent=<父id> 挂到父页面下；功能A：?folder=<目录id> 新建即入当前目录
    const q = String(route.query.title || '').trim()
    if (q) form.title = q
    if (route.query.parent !== undefined) form.parent = String(route.query.parent)
    if (route.query.folder !== undefined) form.folder = String(route.query.folder)

    // 来自助手：若存在 source_record_id，调用 /api/assistant/records/{id}/note-draft 预填草稿
    if (sourceRecordId) {
      try {
        const draft = await assistantApi.getNoteDraft(sourceRecordId)
        if (draft.title && !form.title) form.title = draft.title
        if (draft.content) form.content = draft.content
        if (draft.summary && !form.summary) form.summary = draft.summary
        if (draft.tags?.length && !tagsText.value) tagsText.value = draft.tags.join(', ')
        ElMessage.info('已载入助手整理的笔记草稿')
      } catch { /* ignore */ }
    }

    markSaved() // 以当前表单为基准，此后有输入才算改动
    loading.value = false
    timer = setInterval(() => { tryAutoSave() }, AUTO_SAVE_MS)
    return
  }
  try {
    const n = await http.get<any>(`/notes/${id.value}`)
    form.title = n.title
    form.type = n.type
    form.fmt = n.fmt === 'ink' ? 'ink' : 'md'
    form.folder = n.folder || ''
    form.parent = n.parent || '' // 子页编辑保持挂载关系，否则会被置回顶层
    form.summary = n.summary
    form.content = n.content
    tagsText.value = n.tags.join(', ')
    markSaved(n.updated)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
    router.push('/notes')
  } finally {
    loading.value = false
    timer = setInterval(() => { tryAutoSave() }, AUTO_SAVE_MS)
  }
})

onBeforeUnmount(() => {
  clearInterval(timer)
  clearTimeout(inkTimer)
  window.removeEventListener('pagehide', onPageHide)
  document.removeEventListener('fullscreenchange', onFsChange)
})
</script>

<style scoped>
/* 博客编辑属两栏读写，内容区放宽；单栏正文起点更高（正文区最小高度由编辑器 CSS 变量接管） */
.page { max-width: 1760px; --mde-min: max(420px, calc(100vh - 205px)); }
/* 白板编辑区撑满视口剩余高度，工作区更大；纸面宽度随容器铺满（组件内已去掉 1100px 上限） */
.page .wb { height: calc(100vh - 150px); }
.page .wb.readonly { height: auto; }
/* 全屏书写：隐藏顶栏底栏，纸面吃满屏幕 */
.page.immersive { max-width: none; padding: 6px 10px 8px; }
.page.immersive .edit-head,
.page.immersive .foot { display: none; }
.page.immersive .wb { height: calc(100vh - 14px); }
.fs-btn { flex: none; }
.edit-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.doc-title {
  font-size: 13.5px; font-weight: 600; color: var(--txt2); max-width: 40vw;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
html.theme-dark .doc-title { color: #cbd5e1; }
.save-hint { margin-left: auto; color: var(--txt2); font-size: 12px; white-space: nowrap; }

.fmt-seg {
  flex: none; display: inline-flex; gap: 2px; padding: 2px;
  border-radius: 10px; background: rgba(148, 163, 184, 0.14);
}
.fmt-seg button {
  border: none; cursor: pointer; font-family: inherit; font-size: 12.5px;
  padding: 4px 11px; border-radius: 8px; color: var(--txt3, #94a3b8);
  background: transparent;
}
html.theme-dark .fmt-seg button { color: #cbd5e1; }
.fmt-seg button.on { background: var(--acc-grad, linear-gradient(135deg, #8b5cf6, #6366f1)); color: #fff; font-weight: 600; }
.foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }

/* 文本编辑器（Vditor 即时渲染）上方工具条：引用按钮 + 提示 */
.md-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.md-toolbar-hint { font-size: 11.5px; color: var(--txt3); }
html.theme-dark .md-toolbar-hint { color: var(--txt2); }
</style>

<style>
/* 引用其它文章：选文章对话框（teleport 到 body，需非 scoped 样式；样式自 MarkdownEditor 搬入） */
.mde-rf-tip { color: var(--txt2); font-size: 12px; margin: 2px 0 10px; }
.mde-rf-list { max-height: 44vh; overflow-y: auto; display: grid; gap: 6px; margin-top: 10px; }
.mde-rf-item {
  display: flex; align-items: baseline; gap: 8px; width: 100%; text-align: left;
  border: 1px solid rgba(148, 163, 184, 0.22); background: transparent; border-radius: 10px;
  padding: 8px 12px; cursor: pointer; font-family: inherit; color: var(--txt1);
  transition: border-color .15s, background .15s;
}
html.theme-dark .mde-rf-item { color: #cbd5e1; }
.mde-rf-item:hover { border-color: var(--acc2); background: rgba(139, 92, 246, 0.08); }
.mde-rf-type {
  flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: rgba(167, 139, 250, 0.14); color: var(--acc2);
}
.mde-rf-title { font-weight: 600; font-size: 13.5px; flex: none; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mde-rf-sum { color: var(--txt3); font-size: 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
html.theme-dark .mde-rf-sum { color: var(--txt2); }
.mde-rf-empty { color: var(--txt2); font-size: 13px; text-align: center; padding: 24px 0; }
</style>
