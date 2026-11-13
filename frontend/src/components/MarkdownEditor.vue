<template>
  <div ref="rootEl" class="mde glass">
    <!-- 富文本式工具栏：按钮把 Markdown 语法插入光标处 -->
    <div class="tb">
      <template v-for="(g, i) in toolbar" :key="g ? g.action : `sep${i}`">
        <button v-if="g" class="tb-btn" type="button" :title="g.label" @click="run(g.action)">{{ g.label }}</button>
        <span v-else class="tb-sep" />
      </template>
      <span class="tb-spacer" />
      <span class="tb-count">{{ words }} 字</span>
      <template v-if="preview">
        <span class="tb-sep" />
        <button class="tb-btn seg" type="button" :class="{ on: mode === 'side' }" title="左右分栏" @click="mode = 'side'">左右</button>
        <button class="tb-btn seg" type="button" :class="{ on: mode === 'vertical' }" title="上写下属" @click="mode = 'vertical'">上下</button>
        <button
          v-if="mode === 'side'" class="tb-btn seg" type="button"
          :class="{ on: follow }" title="右栏跟随左栏滚动"
          @click="follow = !follow"
        >跟随</button>
      </template>
      <button
        class="tb-btn acc" type="button" @click="preview = !preview"
        :class="{ on: preview }"
      >{{ preview ? '返回编辑' : '预览' }}</button>
    </div>

    <div class="body" :class="{ split: preview, vertical: preview && mode === 'vertical' }">
      <div ref="host" class="cm" />
      <div v-if="preview" ref="prevEl" class="prev markdown-body" v-html="html" @click="onPrevClick" />
    </div>

    <!-- 引用其它文章：选一篇，在光标处插入站内链接 [标题](/notes/id) -->
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

    <!-- 插入图片：上传本地（也可截图 Ctrl+V / 拖入编辑区）或填外链 -->
    <el-dialog v-model="imgOpen" title="插入图片" width="460px">
      <div class="mde-rf-tip">最快的方式：<b>截图后 Ctrl+V 粘贴</b>，或把图片文件<b>拖进编辑区</b>，自动上传为站内图片。</div>
      <div class="img-row">
        <el-button type="primary" plain @click="pickImgFile">上传本地图片</el-button>
        <span class="img-hint">jpg / png / webp / gif，单张 ≤20MB</span>
        <input ref="imgInput" type="file" accept="image/*" multiple style="display:none" @change="onImgFiles" />
      </div>
      <div class="img-row" style="margin-top:10px">
        <el-input v-model="imgUrl" placeholder="或填外链图片地址 https://…" clearable style="flex:1">
          <template #prefix><el-icon><Link /></el-icon></template>
        </el-input>
        <el-button type="primary" :disabled="!imgUrl.trim()" @click="insertImgUrl">插入</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { clientState } from '../api/clientState'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Link, Search } from '@element-plus/icons-vue'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { renderMd } from '../utils/md'
import { hydrateImages } from '../utils/media'
import { http } from '../api/client'

/**
 * Markdown 编辑区高亮（替换 basicSetup 自带的 defaultHighlightStyle fallback）。
 * 原默认配色的语法符号（# * ` > - 等）tag=processingInstruction（meta 的子 tag），
 * 颜色 #404740 在暗黑主题的深色编辑器上几乎看不清。这里统一按主题变量重上色：
 * 符号、链接、行内代码、注释各自可读；正文不设色、随主题文字色。
 */
const mdHighlight = HighlightStyle.define([
  { tag: t.heading, fontWeight: 'bold' },
  { tag: t.emphasis, fontStyle: 'italic' },
  { tag: t.strong, fontWeight: 'bold' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: t.link, textDecoration: 'underline' },
  { tag: [t.meta, t.processingInstruction], color: 'var(--mde-mark)' },
  { tag: [t.url, t.string, t.character, t.contentSeparator], color: 'var(--mde-link)' },
  { tag: t.monospace, color: 'var(--mde-code)' },
  { tag: t.comment, color: 'var(--mde-cmt)' },
  { tag: t.invalid, color: '#ef4444' },
])

const props = defineProps<{ modelValue: string; excludeId?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'save'): void }>()

const router = useRouter()

const host = ref<HTMLDivElement>()
const prevEl = ref<HTMLDivElement>()
const rootEl = ref<HTMLDivElement>()
const preview = ref(false)
/** 预览布局：side=左右分栏；vertical=上写下看（偏好记忆） */
const mode = ref<'side' | 'vertical'>((clientState.getItem('krs_md_mode') as 'side' | 'vertical' | null) || 'side')
/** 左右分栏时右栏跟随左栏滚动（默认关，点「跟随」开启后记忆） */
const follow = ref(clientState.getItem('krs_md_follow') === '1')
let view: EditorView | null = null
let local = false
let rafId = 0

watch(mode, (m) => clientState.setItem('krs_md_mode', m))
watch(follow, (f) => clientState.setItem('krs_md_follow', f ? '1' : '0'))

/* 编辑区滚动 → 预览区按比例跟随（仅左右分栏且开启跟随时） */
function onEditScroll() {
  if (!preview.value || mode.value !== 'side' || !follow.value) return
  const src = view?.scrollDOM
  const dst = prevEl.value
  if (!src || !dst) return
  cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => {
    const sh = src.scrollHeight - src.clientHeight
    const dh = dst.scrollHeight - dst.clientHeight
    if (sh > 0 && dh > 0) dst.scrollTop = (src.scrollTop / sh) * dh
  })
}

const html = computed(() => renderMd(props.modelValue))
const words = computed(() => (props.modelValue.trim() ? props.modelValue.trim().length : 0))

/* 预览：内容或预览态变化后，把站内图片换为带鉴权 blob URL 显示 */
watch([html, preview], () => {
  if (!preview.value) return
  nextTick(() => hydrateImages(prevEl.value))
})

/* ---------------- 工具栏动作 ---------------- */

const toolbar: ({ label: string; action: string } | null)[] = [
  { label: 'H1', action: 'h1' }, { label: 'H2', action: 'h2' }, { label: 'H3', action: 'h3' },
  null,
  { label: 'B', action: 'bold' }, { label: 'I', action: 'italic' }, { label: 'S', action: 'strike' },
  { label: '`', action: 'code' }, { label: '公式', action: 'formula' },
  null,
  { label: '引用', action: 'quote' }, { label: '列表', action: 'ul' }, { label: '1.', action: 'ol' },
  { label: '待办', action: 'task' }, { label: '分割', action: 'hr' },
  null,
  { label: '链接', action: 'link' }, { label: '引用', action: 'ref' }, { label: '图片', action: 'image' }, { label: '表格', action: 'table' },
  { label: '代码', action: 'codeblock' },
]

/* ---------------- 引用其它文章（站内链接 [标题](/notes/id)，点选插入） ---------------- */

interface RefNote { id: string; title: string; type: string; summary: string; tags: string[] }

const refOpen = ref(false)
const refQ = ref('')
const refCandidates = ref<RefNote[]>([])

const refList = computed(() => {
  const q = refQ.value.trim().toLowerCase()
  return refCandidates.value.filter((n) => {
    if (props.excludeId && n.id === props.excludeId) return false // 不引用自己
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

/** 选中文章：在光标处插入 [显示文字](/notes/id)；有选中文字则用选中文字 */
function pickRef(n: RefNote) {
  if (!view) return
  const { from, to } = view.state.selection.main
  const sel = view.state.sliceDoc(from, to).trim()
  // 链接文字防破坏 Markdown 语法：去掉方括号/圆括号
  const text = (sel || n.title).replace(/[[\]()]/g, '') || '文章'
  const insert = `[${text}](/notes/${n.id})`
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + insert.length },
  })
  refOpen.value = false
  view.focus()
}

/* ---------------- 图片：粘贴 / 拖拽 / 上传 / 外链（上传到站内，正文加密同库） ---------------- */

const imgOpen = ref(false)
const imgUrl = ref('')
const imgInput = ref<HTMLInputElement | null>(null)
let uploadMsg: { close: () => void } | null = null

/** 粘贴：剪贴板里只有图片文件（如截图）时接管为上传；有文本（含网页复制图文）放行默认粘贴 */
function onPaste(e: ClipboardEvent) {
  const dt = e.clipboardData
  if (!dt || !view) return
  const types = Array.from(dt.types || [])
  if (types.includes('text/plain') || types.includes('text/html')) return
  const files = Array.from(dt.items || [])
    .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
    .map((it) => it.getAsFile())
    .filter((f): f is File => !!f)
  if (!files.length) return
  e.preventDefault()
  handleFiles(files)
}

/** 拖拽：允许文件拖入，并接管图片文件的 drop */
function onDragOver(e: DragEvent) {
  if (Array.from(e.dataTransfer?.types || []).includes('Files')) {
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  }
}

function onDrop(e: DragEvent) {
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => f.type.startsWith('image/'))
  if (!files.length) return
  e.preventDefault()
  handleFiles(files)
}

/** 逐张上传并插入正文；一批共用一条 loading 提示 */
async function handleFiles(files: File[]) {
  if (!files.length || uploadMsg) return
  uploadMsg = ElMessage({ message: '上传图片…', type: 'info', duration: 0 })
  let ok = 0
  try {
    for (const f of files) {
      const fd = new FormData()
      fd.append('file', f)
      const r = await http.post<{ url: string }>('/notes/images', fd)
      insertImageMarkdown(r.url, f.name)
      ok++
    }
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '图片上传失败，请重试')
    }
  } finally {
    if (uploadMsg) { uploadMsg.close(); uploadMsg = null }
    if (ok) ElMessage.success(`已插入 ${ok} 张图片`)
  }
}

/** 光标处插入 ![描述](站内图片url) */
function insertImageMarkdown(url: string, fileName: string) {
  if (!view) return
  let alt = (fileName || '').replace(/\.[a-z0-9]+$/i, '').trim() || `图片 ${new Date().toLocaleTimeString('zh-CN', { hour12: false }).slice(0, 5)}`
  alt = alt.replace(/[[\]]/g, '').slice(0, 30) || '图片'
  const { from } = view.state.selection.main
  const insert = `\n\n![${alt}](${url})\n\n`
  view.dispatch({ changes: { from, insert }, selection: { anchor: from + insert.length } })
}

function pickImgFile() {
  imgInput.value?.click()
}

async function onImgFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  imgOpen.value = false
  if (files.length) handleFiles(files)
}

/** 外链图片：插入 ![图片](https://...) */
function insertImgUrl() {
  const url = imgUrl.value.trim()
  if (!/^https?:\/\//i.test(url)) return ElMessage.warning('外链需以 http(s):// 开头')
  if (!view) return
  const { from } = view.state.selection.main
  const insert = `\n\n![图片](${url})\n\n`
  view.dispatch({ changes: { from, insert }, selection: { anchor: from + insert.length } })
  imgUrl.value = ''
  imgOpen.value = false
  view.focus()
}

function run(action: string) {
  if (!view) return
  const fns: Record<string, () => void> = {
    h1: () => linePrefix('# '),
    h2: () => linePrefix('## '),
    h3: () => linePrefix('### '),
    bold: () => wrap('**', '**', '加粗'),
    italic: () => wrap('*', '*', '斜体'),
    strike: () => wrap('~~', '~~', '删除线'),
    code: () => wrap('`', '`', 'code'),
    formula: () => wrap('$', '$', '公式'),
    quote: () => linePrefix('> '),
    ul: () => linePrefix('- '),
    ol: () => linePrefix('1. '),
    task: () => linePrefix('- [ ] '),
    hr: () => insertBlock('\n\n---\n\n'),
    codeblock: () => insertBlock('\n\n```\n代码\n```\n\n'),
    table: () => insertBlock('\n\n| 列1 | 列2 |\n| --- | --- |\n| 内容 | 内容 |\n\n'),
    ref: () => { refOpen.value = true },
    link: () => {
      const url = window.prompt('链接地址', 'https://')
      if (url) wrap('[', `](${url})`, '链接文字')
    },
    image: () => { imgOpen.value = true },
  }
  fns[action]?.()
  view?.focus()
}

/* 选区包裹 */
function wrap(prefix: string, suffix: string, placeholder: string) {
  if (!view) return
  const { from, to } = view.state.selection.main
  const sel = view.state.sliceDoc(from, to) || placeholder
  const insert = prefix + sel + suffix
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + prefix.length, head: from + prefix.length + sel.length },
  })
}

/* 行首前缀（可重复切换） */
function linePrefix(prefix: string) {
  if (!view) return
  const { from } = view.state.selection.main
  const line = view.state.doc.lineAt(from)
  const text = line.text
  if (text.startsWith(prefix)) {
    view.dispatch({ changes: { from: line.from, to: line.from + prefix.length, insert: '' } })
  } else {
    view.dispatch({ changes: { from: line.from, insert: prefix } })
  }
}

/* 在光标处插入块 */
function insertBlock(text: string) {
  if (!view) return
  const { from, to } = view.state.selection.main
  view.dispatch({
    changes: { from, to, insert: text },
    selection: { anchor: from + text.length },
  })
}

/* 预览区点击：站内笔记链接走 SPA 跳转，不整页刷新 */
function onPrevClick(e: MouseEvent) {
  e.stopPropagation()
  const a = (e.target as HTMLElement).closest('a')
  if (!a) return
  const href = a.getAttribute('href') || ''
  if (href.startsWith('/notes/')) {
    e.preventDefault()
    router.push(href)
  }
}

/* ---------------- CodeMirror ---------------- */

/* 编辑内容变化 → 回传 v-model（必须放进 extensions，否则输入永不更新模型/预览/字数） */
const updateListener = EditorView.updateListener.of((u) => {
  if (!u.docChanged) return
  local = true
  emit('update:modelValue', u.state.doc.toString())
  local = false
})

onMounted(() => {
  rootEl.value?.addEventListener('paste', onPaste)
  rootEl.value?.addEventListener('dragover', onDragOver)
  rootEl.value?.addEventListener('drop', onDrop)
  if (!host.value) return
  const saveKeymap = keymap.of([{ key: 'Mod-s', run: () => { emit('save'); return true } }])
  const state = EditorState.create({
    doc: props.modelValue,
    extensions: [basicSetup, markdown(), syntaxHighlighting(mdHighlight), saveKeymap, EditorView.lineWrapping, updateListener],
  })
  view = new EditorView({ state, parent: host.value })
  view.dispatch({ selection: { anchor: state.doc.length } })
  view.focus()
  view.scrollDOM.addEventListener('scroll', onEditScroll)
})

watch(
  () => props.modelValue,
  (v) => {
    if (!view || local || v === view.state.doc.toString()) return
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } })
  },
)

onBeforeUnmount(() => {
  rootEl.value?.removeEventListener('paste', onPaste)
  rootEl.value?.removeEventListener('dragover', onDragOver)
  rootEl.value?.removeEventListener('drop', onDrop)
  cancelAnimationFrame(rafId)
  view?.destroy()
  view = null
})
</script>

<style scoped>
.mde { display: flex; flex-direction: column; border-radius: 16px; overflow: hidden; }
.tb {
  display: flex; align-items: center; gap: 3px; flex-wrap: wrap;
  padding: 8px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.3);
}
html.theme-dark .tb { background: rgba(30, 41, 59, 0.28); }
.tb-btn {
  border: none; background: transparent; cursor: pointer;
  min-width: 28px; height: 26px; padding: 0 7px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; color: #475569; font-family: inherit;
}
html.theme-dark .tb-btn { color: #cbd5e1; }
.tb-btn:hover { background: rgba(139, 92, 246, 0.14); color: var(--acc2); }
.tb-btn.acc { background: rgba(139, 92, 246, 0.12); color: var(--acc2); }
.tb-btn.acc.on { background: var(--acc-grad); color: #fff; }
/* 预览布局小按钮 */
.tb-btn.seg { min-width: auto; padding: 0 6px; font-size: 11px; height: 22px; color: var(--txt3); }
html.theme-dark .tb-btn.seg { color: var(--txt2); }
.tb-btn.seg.on { background: rgba(139, 92, 246, 0.16); color: var(--acc2); font-weight: 700; }
.tb-sep { width: 1px; height: 18px; background: rgba(148, 163, 184, 0.3); margin: 0 3px; }
.tb-spacer { flex: 1; }
.tb-count { font-size: 11px; color: var(--txt2); margin-right: 6px; }

.body { display: flex; min-height: var(--mde-min, 420px); }
/* 左右分栏：固定可视高度，编辑与预览各自内部滚动（跟随才有效） */
.body.split:not(.vertical) { height: 60vh; min-height: 420px; }
.body.split:not(.vertical) .cm { width: 50%; height: 100%; overflow: hidden; border-right: 1px solid rgba(148, 163, 184, 0.2); }
.body.split:not(.vertical) .prev { height: 100%; }
.body .cm { flex: 1; overflow: hidden; }
/* 上下布局：上写下看，顺序对照 */
.body.vertical { flex-direction: column; min-height: 0; }
.body.vertical .cm { flex: none; width: auto; height: 46vh; border-right: none; border-bottom: 1px solid rgba(148, 163, 184, 0.2); }
.body.vertical .prev { flex: none; height: 46vh; }
@media (max-width: 600px) {
  .body.vertical .cm, .body.vertical .prev { height: 40vh; }
}
.prev {
  flex: 1; overflow: auto; padding: 16px 20px;
  font-size: 14.5px; line-height: 1.85; color: #334155;
}
html.theme-dark .prev { color: #e2e8f0; }
</style>

<style>
/* 预览区 markdown 样式（非 scoped，供渲染内容使用） */
.markdown-body h1 { font-size: 1.7em; margin: 0.9em 0 0.45em; }
.markdown-body h2 { font-size: 1.4em; margin: 0.9em 0 0.4em; padding-left: 8px; border-left: 4px solid var(--acc2); }
.markdown-body h3 { font-size: 1.18em; margin: 0.8em 0 0.35em; }
.markdown-body p { margin: 0.55em 0; }
.markdown-body code {
  background: rgba(139, 92, 246, 0.12); padding: 1px 6px; border-radius: 6px;
  font-family: 'JetBrains Mono', Consolas, monospace; font-size: 0.92em;
}
.markdown-body pre {
  background: rgba(15, 23, 42, 0.9); color: #e2e8f0; padding: 12px 16px;
  border-radius: 12px; overflow-x: auto;
}
.markdown-body pre code { background: transparent; color: inherit; padding: 0; }
.markdown-body blockquote {
  margin: 0.6em 0; padding: 6px 14px; color: var(--txt3);
  border-left: 4px solid var(--acc3); background: rgba(56, 189, 248, 0.07);
  border-radius: 0 10px 10px 0;
}
html.theme-dark .markdown-body blockquote { color: var(--txt2); }
.markdown-body a { color: var(--acc2); text-decoration: underline; }
.markdown-body ul, .markdown-body ol { padding-left: 1.6em; margin: 0.5em 0; }
.markdown-body li { margin: 0.2em 0; }
.markdown-body li:has(> input[type="checkbox"]) { list-style: none; margin-left: -1.2em; }
.markdown-body table { border-collapse: collapse; margin: 0.7em 0; }
.markdown-body th, .markdown-body td { border: 1px solid rgba(148, 163, 184, 0.4); padding: 5px 12px; }
.markdown-body th { background: rgba(167, 139, 250, 0.12); }
.markdown-body hr { border: none; border-top: 2px dashed rgba(148, 163, 184, 0.4); margin: 1.2em 0; }
.markdown-body img { max-width: 100%; border-radius: 12px; }

/* CodeMirror：容器固定高度时由内部滚动层滚动（分栏跟随的基础） */
.mde .cm-editor { height: 100%; }
.mde .cm-scroller { overflow-y: auto; }

/* 引用其它文章：选文章对话框（teleport 到 body，需非 scoped 样式） */
.mde-rf-tip { color: var(--txt2); font-size: 12px; margin: 2px 0 10px; }
.mde-rf-tip code { background: rgba(139, 92, 246, 0.12); padding: 0 5px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11.5px; }
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

/* 插入图片对话框 */
.img-row { display: flex; align-items: center; gap: 10px; }
.img-hint { font-size: 12px; color: var(--txt2); }
</style>
