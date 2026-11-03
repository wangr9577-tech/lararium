<template>
  <div class="page" v-loading="loading">
    <div v-if="doc" class="view">
      <div class="head">
        <div class="head-main">
          <div class="page-title">{{ doc.meta.title || doc.name }}</div>
          <div class="meta">
            <span class="src-chip">{{ doc.source.name }}</span>
            <span class="path-text" :title="absPath">{{ doc.path }}</span>
            <span class="time">{{ doc.mtime }} · {{ fmtSize(doc.size) }}</span>
            <span v-if="doc.source.readonly" class="ro-chip">只读源</span>
            <el-tag v-for="t in doc.meta.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
          </div>
        </div>
        <div class="ops">
          <el-button @click="backToList">
            <el-icon style="margin-right:4px"><Back /></el-icon>返回列表
          </el-button>
          <el-button @click="copyPath">复制路径</el-button>
          <el-button :loading="snapshotting" @click="saveAsNote">存为博客笔记</el-button>
          <el-button type="primary" @click="goEdit">
            <el-icon style="margin-right:4px"><EditPen /></el-icon>{{ doc.source.readonly ? '编辑（只读源）' : '编辑' }}
          </el-button>
        </div>
      </div>

      <div class="tip glass">
        这是项目目录里的<b>原文件</b>（{{ absPath }}）—— 站内看到的就是 agent 读到的那一份，
        编辑保存即写回原文件，没有第二份副本。
      </div>

      <nav v-if="toc.length > 1" class="toc glass">
        <div class="toc-title">目录</div>
        <a
          v-for="t in toc" :key="t.id" class="toc-item" :class="{ lv3: t.level === 3 }"
          :href="`#${t.id}`" @click.prevent="jumpTo(t.id)"
        >{{ t.text }}</a>
      </nav>

      <article class="article glass doc-article">
        <div v-if="doc.meta.summary" class="lead">{{ doc.meta.summary }}</div>
        <div ref="articleEl" class="markdown-body" v-html="html" />
      </article>
    </div>

    <div v-else-if="!loading" class="miss glass">
      <div class="miss-t">打不开这个文件</div>
      <div class="miss-s">{{ error || '文件不存在，或已被移动/重命名' }}</div>
      <el-button style="margin-top:12px" @click="backToList">返回列表</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 项目文档阅读页（只读渲染；编辑走 /projects/edit）。
 * 正文用与笔记页同一套 renderMd（markdown-it + KaTeX + DOMPurify），
 * 相对路径图片经 /api/fs/blob 带鉴权取回后换 objectURL。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back, EditPen } from '@element-plus/icons-vue'
import { fsApi, fmtSize, type FsDoc } from '../api/fs'
import { renderMd } from '../utils/md'
import { dirOf, hydrateDocImages } from '../utils/docmedia'
import { http } from '../api/client'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const snapshotting = ref(false)
const doc = ref<FsDoc | null>(null)
const error = ref('')
const articleEl = ref<HTMLElement>()
const toc = ref<{ id: string; text: string; level: number }[]>([])
const html = computed(() => renderMd(doc.value?.content || ''))
const absPath = computed(() => (doc.value ? `${doc.value.source.root || '.'}/${doc.value.path}` : ''))

function sid(): string { return typeof route.query.sid === 'string' ? route.query.sid : '' }
function path(): string { return typeof route.query.path === 'string' ? route.query.path : '' }

async function load() {
  loading.value = true
  error.value = ''
  doc.value = null
  toc.value = []
  const s = sid()
  const p = path()
  if (!s || !p) { loading.value = false; error.value = '缺少参数（sid / path）'; return }
  try {
    doc.value = await fsApi.read(s, p)
    await nextTick()
    buildToc()
    await hydrateDocImages(articleEl.value, s, dirOf(p))
  } catch (e: any) {
    const st = e?.response?.status
    const detail = e?.response?.data?.detail
    error.value = typeof detail === 'string'
      ? detail
      : st === 413 ? '文件太大（站内只打开 1MB 以内的 md）' : '读取失败'
  } finally {
    loading.value = false
  }
}

function buildToc() {
  if (!articleEl.value) return
  const heads = articleEl.value.querySelectorAll('h1, h2, h3')
  const list: { id: string; text: string; level: number }[] = []
  heads.forEach((h, i) => {
    const text = (h.textContent || '').trim()
    if (!text) return
    h.id = `toc-${i + 1}`
    list.push({ id: h.id, text, level: Number(h.tagName.slice(1)) })
  })
  toc.value = list
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function goEdit() {
  router.push({ path: '/projects/edit', query: { sid: sid(), path: path() } })
}

function backToList() {
  const s = sid()
  router.push({ path: '/projects', query: s ? { sid: s, dir: dirOf(path()) || undefined } : {} })
}

async function copyPath() {
  try {
    await navigator.clipboard.writeText(absPath.value)
    ElMessage.success('已复制路径（可直接粘贴给 agent / 编辑器）')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

/** 存为博客笔记：复制一份进笔记体系（加密落盘）——是快照，会与源文件分叉 */
async function saveAsNote() {
  const d = doc.value
  if (!d) return
  try {
    await ElMessageBox.confirm(
      '会把这篇文章复制成一份博客笔记（站内加密保存）。\n\n注意：这是**快照**，之后源文件再改不会同步过来 —— 需要持续同步的内容请直接在「编辑」里改原文件。',
      '存为博客笔记', { type: 'info', confirmButtonText: '存一份', cancelButtonText: '取消' },
    )
  } catch { return }
  snapshotting.value = true
  try {
    const r = await http.post<{ id: string }>('/notes', {
      title: d.meta.title || d.name.replace(/\.(md|markdown)$/i, ''),
      type: 'note',
      fmt: 'md',
      module: '',
      folder: '',
      parent: '',
      tags: d.meta.tags,
      summary: d.meta.summary || '',
      content: `> 来自项目文档 \`${absPath.value}\`（${d.mtime} 的快照）\n\n${d.content}`,
    })
    ElMessage.success('已存为博客笔记')
    router.push(`/notes/${r.id}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    snapshotting.value = false
  }
}

watch(() => [route.query.sid, route.query.path], load, { immediate: true })
</script>

<style scoped>
.head { display: flex; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.head-main { min-width: 0; flex: 1; }
.head .page-title { margin-bottom: 8px; }
.meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--txt2); }
.src-chip {
  padding: 1px 8px; border-radius: 8px; font-weight: 600;
  background: rgba(139, 92, 246, 0.16); color: var(--acc2);
}
.path-text {
  font-family: Consolas, monospace; font-size: 12px; max-width: 420px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ro-chip { padding: 1px 7px; border-radius: 8px; background: rgba(245, 158, 11, 0.18); color: #b45309; }
html.theme-dark .ro-chip { color: #fbbf24; }
.ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.tip {
  margin: 14px 0 0; padding: 10px 14px; font-size: 12px; color: var(--txt2); line-height: 1.7;
}
.tip b { color: var(--txt3); word-break: break-all; }

.toc { margin: 14px 0 0; padding: 12px 16px; max-height: 240px; overflow: auto; }
.toc-title { font-size: 12px; font-weight: 700; color: var(--txt2); margin-bottom: 6px; }
.toc-item {
  display: block; font-size: 13px; color: var(--txt3); text-decoration: none;
  padding: 3px 0; border-bottom: 1px dashed transparent;
}
.toc-item:hover { color: var(--acc2); }
.toc-item.lv3 { padding-left: 16px; font-size: 12px; opacity: 0.88; }

.article { margin-top: 14px; padding: 22px 26px 30px; }
.lead {
  font-size: 14px; color: var(--txt2); line-height: 1.8; padding: 10px 14px; margin-bottom: 14px;
  border-left: 4px solid var(--acc2); background: rgba(139, 92, 246, 0.08); border-radius: 0 10px 10px 0;
}

.miss { margin-top: 40px; padding: 30px; text-align: center; }
.miss-t { font-size: 16px; font-weight: 700; }
.miss-s { font-size: 13px; color: var(--txt2); margin-top: 8px; }

/* 正文排版：与笔记阅读页同一套观感（.doc-article 下作用，不影响其它页面） */
.doc-article .markdown-body { font-size: 15px; line-height: 1.9; color: #334155; }
html.theme-dark .doc-article .markdown-body { color: #e2e8f0; }
.doc-article .markdown-body h1 { font-size: 1.8em; margin: 1em 0 0.5em; padding-bottom: 8px; border-bottom: 2px solid rgba(167, 139, 250, 0.3); }
.doc-article .markdown-body h2 { font-size: 1.45em; margin: 1em 0 0.45em; padding-left: 10px; border-left: 4px solid var(--acc2); }
.doc-article .markdown-body h3 { font-size: 1.2em; margin: 0.9em 0 0.4em; }
.doc-article .markdown-body h1, .doc-article .markdown-body h2, .doc-article .markdown-body h3 { scroll-margin-top: 12px; }
.doc-article .markdown-body p { margin: 0.65em 0; }
.doc-article .markdown-body code { background: rgba(139, 92, 246, 0.12); padding: 1px 7px; border-radius: 6px; font-family: Consolas, monospace; font-size: 0.92em; }
.doc-article .markdown-body pre { background: rgba(15, 23, 42, 0.92); color: #e2e8f0; padding: 14px 18px; border-radius: 12px; overflow-x: auto; }
.doc-article .markdown-body pre code { background: transparent; color: inherit; padding: 0; }
.doc-article .markdown-body blockquote { margin: 0.8em 0; padding: 6px 16px; color: var(--txt3); border-left: 4px solid var(--acc3); background: rgba(56, 189, 248, 0.07); border-radius: 0 10px 10px 0; }
html.theme-dark .doc-article .markdown-body blockquote { color: var(--txt2); }
.doc-article .markdown-body a { color: var(--acc2); }
.doc-article .markdown-body img { max-width: 100%; border-radius: 10px; }
.doc-article .markdown-body table { border-collapse: collapse; margin: 0.8em 0; }
.doc-article .markdown-body th, .doc-article .markdown-body td { border: 1px solid rgba(148, 163, 184, 0.45); padding: 6px 14px; }
.doc-article .markdown-body th { background: rgba(167, 139, 250, 0.12); }
.doc-article .markdown-body ul, .doc-article .markdown-body ol { padding-left: 1.7em; margin: 0.6em 0; }
.doc-article .markdown-body li { margin: 0.2em 0; }
.doc-article .markdown-body li:has(> input[type="checkbox"]) { list-style: none; margin-left: -1.2em; }
.doc-article .markdown-body hr { border: none; border-top: 2px dashed rgba(148, 163, 184, 0.4); margin: 1.4em 0; }
.doc-article .markdown-body .katex-display { overflow-x: auto; overflow-y: hidden; }
</style>