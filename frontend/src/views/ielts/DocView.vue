<template>
  <div class="page" v-loading="loading">
    <div class="sub-head">
      <el-button text @click="$router.push('/ielts')"><el-icon><ArrowLeft /></el-icon>雅思主页</el-button>
      <el-button type="primary" size="small" @click="$router.push(`/ielts/doc/${id}/edit`)">编辑</el-button>
      <el-button type="danger" plain size="small" :loading="delBusy" @click="remove">删除</el-button>
    </div>

    <div v-if="doc" class="doc">
      <div class="doc-head glass">
        <div class="doc-title">{{ doc.title }}</div>
        <div class="doc-meta">创建 {{ shortTime(doc.created) }} · 更新 {{ shortTime(doc.updated) }}</div>
      </div>
      <article class="doc-body glass">
        <div ref="bodyEl" class="markdown-body" v-html="html" @click="onArticleClick" />
      </article>
    </div>
    <div v-else-if="!loading" class="miss">子页不存在或已被删除</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { http } from '../../api/client'
import { renderMd } from '../../utils/md'
import { hydrateImages } from '../../utils/media'

interface DocNote { id: string; title: string; module: string; summary: string; created: string; updated: string; content: string }

const route = useRoute()
const router = useRouter()
const id = String(route.params.id || '')
const loading = ref(true)
const delBusy = ref(false)
const doc = ref<DocNote | null>(null)
const bodyEl = ref<HTMLDivElement>()
const html = computed(() => renderMd(doc.value?.content || ''))

function shortTime(t: string) {
  return t ? t.slice(0, 16) : ''
}

/** 正文点击：站内笔记引用链接走 SPA 跳转 */
function onArticleClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('a')
  if (!a) return
  const href = a.getAttribute('href') || ''
  if (href.startsWith('/notes/')) {
    e.preventDefault()
    router.push(href)
  }
}

async function remove() {
  try {
    await ElMessageBox.confirm(`删除子页「${doc.value?.title}」？删除后不可恢复。`, '确认删除', { type: 'warning' })
  } catch { return }
  delBusy.value = true
  try {
    await http.del(`/notes/${id}`)
    ElMessage.success('已删除')
    router.push('/ielts')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    delBusy.value = false
  }
}

onMounted(async () => {
  try {
    const n = await http.get<DocNote>(`/notes/${id}`)
    if ((n.module || '') !== 'ielts') {
      ElMessage.warning('这不是雅思模块的子页')
      router.replace('/ielts')
      return
    }
    doc.value = n
    await nextTick()
    hydrateImages(bodyEl.value) // 站内图片 → 带鉴权 blob URL
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '加载失败')
    }
    router.replace('/ielts')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page { max-width: 1400px; }
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sub-head .el-button:first-child { margin-right: auto; }

.doc-head { padding: 18px 26px; margin-bottom: 12px; border-radius: 16px; }
.doc-title { font-size: 21px; font-weight: 800; }
.doc-meta { font-size: 12px; color: var(--txt2); margin-top: 6px; }

.doc-body { padding: 26px 34px; border-radius: 16px; }
.miss { text-align: center; color: var(--txt2); padding: 60px 0; }
</style>

<style>
/* md 子页正文渲染样式（非 scoped） */
.doc .markdown-body { font-size: 15px; line-height: 1.9; color: #334155; }
html.theme-dark .doc .markdown-body { color: #e2e8f0; }
.doc .markdown-body h1 { font-size: 1.8em; margin: 1em 0 0.5em; padding-bottom: 8px; border-bottom: 2px solid rgba(167, 139, 250, 0.3); }
.doc .markdown-body h2 { font-size: 1.45em; margin: 1em 0 0.45em; padding-left: 10px; border-left: 4px solid var(--acc2); }
.doc .markdown-body h3 { font-size: 1.2em; margin: 0.9em 0 0.4em; }
.doc .markdown-body p { margin: 0.65em 0; }
.doc .markdown-body code { background: rgba(139, 92, 246, 0.12); padding: 1px 7px; border-radius: 6px; font-family: Consolas, monospace; font-size: 0.92em; }
.doc .markdown-body pre { background: rgba(15, 23, 42, 0.92); color: #e2e8f0; padding: 14px 18px; border-radius: 12px; overflow-x: auto; }
.doc .markdown-body pre code { background: transparent; color: inherit; padding: 0; }
.doc .markdown-body blockquote { margin: 0.8em 0; padding: 6px 16px; color: var(--txt3); border-left: 4px solid var(--acc3); background: rgba(56, 189, 248, 0.07); border-radius: 0 10px 10px 0; }
html.theme-dark .doc .markdown-body blockquote { color: var(--txt2); }
.doc .markdown-body a { color: var(--acc2); }
.doc .markdown-body img { max-width: 100%; border-radius: 10px; }
.doc .markdown-body table { border-collapse: collapse; margin: 0.8em 0; }
.doc .markdown-body th, .doc .markdown-body td { border: 1px solid rgba(148, 163, 184, 0.45); padding: 6px 14px; }
.doc .markdown-body th { background: rgba(167, 139, 250, 0.12); }
.doc .markdown-body ul, .doc .markdown-body ol { padding-left: 1.7em; margin: 0.6em 0; }
.doc .markdown-body li { margin: 0.25em 0; }
.doc .markdown-body hr { border: none; border-top: 2px dashed rgba(148, 163, 184, 0.4); margin: 1.4em 0; }
.doc .markdown-body .katex-display { overflow-x: auto; overflow-y: hidden; }
</style>
