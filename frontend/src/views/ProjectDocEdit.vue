<template>
  <div class="page" v-loading="loading">
    <div class="head">
      <div class="head-main">
        <div class="page-title">{{ doc?.meta.title || doc?.name || '编辑项目文档' }}</div>
        <div class="meta">
          <span class="src-chip">{{ doc?.source.name }}</span>
          <span class="path-text" :title="absPath">{{ doc?.path }}</span>
          <span class="time">{{ doc?.mtime }} · {{ fmtSize(doc?.size || 0) }}</span>
          <span v-if="dirty" class="dirty">未保存</span>
        </div>
      </div>
      <div class="ops">
        <el-button @click="backToRead">
          <el-icon style="margin-right:4px"><Back /></el-icon>返回阅读
        </el-button>
        <el-button :disabled="!dirty" @click="revert">放弃改动</el-button>
        <el-button
          type="primary" :loading="saving" :disabled="!doc || doc.source.readonly || !dirty"
          @click="doSave()"
        >
          <el-icon style="margin-right:4px"><Check /></el-icon>保存到原文件
        </el-button>
      </div>
    </div>

    <div v-if="doc?.source.readonly" class="banner glass warn">
      这个文档源被标记为<b>只读</b>：网页里不能写回。需要编辑请先在「项目文档 → 管理源」里取消只读。
      也可以点右上角「返回阅读」用「存为博客笔记」留一份站内副本。
    </div>
    <div v-else class="banner glass">
      保存直接写回 <b>{{ absPath }}</b>（同目录原子替换，权限沿用原文件）。
      保存前会比对文件指纹，若期间被 agent 或编辑器改过会提示冲突，<b>不会静默覆盖</b>。快捷键 Ctrl/⌘ + S。
    </div>

    <div class="ed glass">
      <div ref="host" class="cm" />
    </div>

    <!-- 冲突：文件在编辑期间被改动 -->
    <el-dialog v-model="conflictOpen" title="文件已被改动" width="520px">
      <div class="cf-t">
        磁盘上的 <code>{{ doc?.path }}</code> 已经不是打开时的版本（{{ conflictMtime || '刚刚' }} 有改动，可能是 agent 或其它编辑器）。
        你的改动没有被写入。
      </div>
      <div class="cf-ops">
        <el-button type="danger" :loading="saving" @click="overwrite">用我的版本覆盖</el-button>
        <el-button @click="reloadFromDisk">放弃我的改动，载入磁盘版本</el-button>
        <el-button @click="saveAsNoteFromConflict">另存为博客笔记</el-button>
      </div>
      <div class="cf-hint">想两边都保住：先「另存为博客笔记」留一份，再决定覆盖还是载入。</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 项目文档编辑页：CodeMirror 直接编辑原文件，显式保存（不自动保存）。
 * 保存带 base_sha256：后端比对不上返回 409 → 弹出「覆盖 / 放弃 / 另存为博客笔记」三选。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back, Check } from '@element-plus/icons-vue'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { fsApi, fmtSize, type FsDoc } from '../api/fs'
import { dirOf } from '../utils/docmedia'
import { http } from '../api/client'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const doc = ref<FsDoc | null>(null)
const host = ref<HTMLDivElement>()
const dirty = ref(false)
const conflictOpen = ref(false)
const conflictMtime = ref('')
let view: EditorView | null = null
/** 打开/上次保存时的文件指纹：保存时随请求带上，作为乐观锁 */
let baseSha = ''
/** 最近一次从磁盘读到的内容（用于「放弃改动」与脏值判断） */
let cleanText = ''

/** 语法高亮：与笔记编辑器同一套配色（符号在暗色底上要看得清） */
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

const absPath = computed(() => (doc.value ? `${doc.value.source.root || '.'}/${doc.value.path}` : ''))

function sid(): string { return typeof route.query.sid === 'string' ? route.query.sid : '' }
function path(): string { return typeof route.query.path === 'string' ? route.query.path : '' }

function setEditorText(text: string) {
  if (!view) return
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } })
}

async function load() {
  loading.value = true
  const s = sid()
  const p = path()
  if (!s || !p) { loading.value = false; ElMessage.error('缺少参数（sid / path）'); return }
  try {
    const d = await fsApi.read(s, p)
    doc.value = d
    baseSha = d.sha256
    cleanText = d.content
    dirty.value = false
    await nextTick()
    mountEditor(d.content)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '文件读取失败')
    router.replace({ path: '/projects', query: { sid: s, dir: dirOf(p) || undefined } })
  } finally {
    loading.value = false
  }
}

function mountEditor(text: string) {
  view?.destroy()
  view = null
  if (!host.value) return
  const updateListener = EditorView.updateListener.of((u) => {
    if (u.docChanged) dirty.value = u.state.doc.toString() !== cleanText
  })
  const saveKey = keymap.of([{ key: 'Mod-s', run: () => { doSave(); return true } }])
  const state = EditorState.create({
    doc: text,
    extensions: [basicSetup, markdown(), syntaxHighlighting(mdHighlight), saveKey,
                 EditorView.lineWrapping, updateListener],
  })
  view = new EditorView({ state, parent: host.value })
  view.focus()
}

function currentText(): string {
  return view?.state.doc.toString() ?? ''
}

function revert() {
  ElMessageBox.confirm('放弃本次改动，回到磁盘上的版本？', '放弃改动', {
    type: 'warning', confirmButtonText: '放弃', cancelButtonText: '继续编辑',
  }).then(() => {
    setEditorText(cleanText)
    dirty.value = false
    ElMessage.info('已回到磁盘版本')
  }).catch(() => { /* 用户取消 */ })
}

async function doSave(force = false) {
  if (!doc.value || !view) return
  if (doc.value.source.readonly) { ElMessage.warning('该源为只读'); return }
  const text = currentText()
  saving.value = true
  try {
    const r = await fsApi.save({
      sid: doc.value.sid, path: doc.value.path, content: text, base_sha256: baseSha,
    })
    baseSha = r.sha256
    cleanText = text
    dirty.value = false
    doc.value.mtime = r.mtime
    doc.value.size = r.size
    conflictOpen.value = false
    ElMessage.success(force ? '已覆盖保存到原文件' : '已保存到原文件')
  } catch (e: any) {
    const st = e?.response?.status
    const detail = e?.response?.data?.detail
    if (st === 409) {
      const info = typeof detail === 'object' && detail ? detail : {}
      baseSha = info.current_sha256 || ''
      conflictMtime.value = info.current_mtime || ''
      conflictOpen.value = true
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : '保存失败')
    }
  } finally {
    saving.value = false
  }
}

/** 冲突时选择「覆盖」：用磁盘当前版本作为新的基线，再写一次（若期间又变了会再次 409） */
function overwrite() {
  conflictOpen.value = false
  doSave(true)
}

async function reloadFromDisk() {
  const d = doc.value
  if (!d) return
  try {
    const fresh = await fsApi.read(d.sid, d.path)
    doc.value = fresh
    baseSha = fresh.sha256
    cleanText = fresh.content
    setEditorText(fresh.content)
    dirty.value = false
    conflictOpen.value = false
    ElMessage.info('已载入磁盘上的最新版本')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '载入失败')
  }
}

/** 冲突时把编辑器里的内容存成博客笔记（两边都保住） */
async function saveAsNoteFromConflict() {
  const d = doc.value
  if (!d) return
  try {
    const r = await http.post<{ id: string }>('/notes', {
      title: `${d.meta.title || d.name}（冲突副本）`,
      type: 'note', fmt: 'md', module: '', folder: '', parent: '',
      tags: d.meta.tags,
      summary: `来自项目文档 ${absPath.value} 的冲突副本（${new Date().toLocaleString()}）`,
      content: `> 项目文档 \`${absPath.value}\` 的站内副本（保存时检测到磁盘已被改动）\n\n${currentText()}`,
    })
    conflictOpen.value = false
    ElMessage.success('已存为博客笔记')
    router.push(`/notes/${r.id}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

function backToRead() {
  if (!doc.value) { router.push('/projects'); return }
  router.push({ path: '/projects/doc', query: { sid: doc.value.sid, path: doc.value.path } })
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的改动，确定离开？', '未保存', {
      type: 'warning', confirmButtonText: '离开', cancelButtonText: '留下',
    })
    return true
  } catch {
    return false
  }
})

onMounted(load)
onBeforeUnmount(() => { view?.destroy(); view = null })
</script>

<style scoped>
.head { display: flex; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.head-main { min-width: 0; flex: 1; }
.head .page-title { margin-bottom: 8px; }
.meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--txt2); }
.src-chip { padding: 1px 8px; border-radius: 8px; font-weight: 600; background: rgba(139, 92, 246, 0.16); color: var(--acc2); }
.path-text { font-family: Consolas, monospace; font-size: 12px; max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dirty { padding: 1px 7px; border-radius: 8px; background: rgba(239, 68, 68, 0.16); color: #dc2626; }
html.theme-dark .dirty { color: #fca5a5; }
.ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.banner { margin: 14px 0 0; padding: 10px 14px; font-size: 12px; line-height: 1.75; color: var(--txt2); }
.banner b { color: var(--txt3); word-break: break-all; }
.banner.warn { border-left: 4px solid #f59e0b; }

.ed { margin-top: 12px; padding: 6px 4px; height: 62vh; min-height: 380px; overflow: hidden; }
.cm { height: 100%; overflow: hidden; }
.cm :deep(.cm-editor) { height: 100%; }
.cm :deep(.cm-scroller) { overflow-y: auto; font-family: 'JetBrains Mono', Consolas, monospace; font-size: 13.5px; line-height: 1.7; }

.cf-t { font-size: 13px; line-height: 1.85; color: var(--txt3); }
.cf-t code { background: rgba(139, 92, 246, 0.12); padding: 0 5px; border-radius: 4px; font-family: Consolas, monospace; font-size: 12px; }
.cf-ops { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.cf-ops :deep(.el-button) { margin-left: 0 !important; }
.cf-hint { margin-top: 10px; font-size: 12px; color: var(--txt2); }
</style>