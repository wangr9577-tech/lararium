<template>
  <div class="page" v-loading="loading">
    <div class="sub-head">
      <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon>取消</el-button>
      <span class="sub-name">{{ isNew ? '新建 markdown 子页' : '编辑子页' }}</span>
      <span class="save-hint" title="也可用 Ctrl+S 或右下角按钮手动保存">
        每 5 分钟自动保存 · 上次 {{ lastSavedAt || '—' }}
      </span>
    </div>

    <div class="glass form">
      <div class="f-title">
        <el-input v-model="form.title" placeholder="子页标题，如：口语话题库 / 错题本" size="large" />
      </div>
      <div class="f-folder">
        <span class="ff-label">目录</span>
        <el-select v-model="form.folder" style="width: 260px">
          <el-option label="未分类" value="" />
          <el-option v-for="f in dirs" :key="dirPath(f)" :label="dirLabel(f)" :value="dirPath(f)" />
        </el-select>
      </div>
    </div>

    <MarkdownEditor v-model="form.content" @save="doSave" />

    <div class="foot">
      <el-button @click="goBack">取消</el-button>
      <el-button type="primary" :loading="saving" @click="doSave">
        {{ isNew ? '创建子页' : '保存修改' }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getToken, http } from '../../api/client'
import MarkdownEditor from '../../components/MarkdownEditor.vue'

const AUTO_SAVE_MS = 5 * 60 * 1000

const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id || ''))
const isNew = computed(() => route.path.endsWith('/new') || !id.value)

const loading = ref(true)
const saving = ref(false)
const autoBusy = ref(false)
const form = reactive({ title: '', folder: '', content: '' })
/** 目录：path=自身全路径（顶层=名字），parent=父目录全路径（''=顶层）；兼容期后端未返回 path 时回落到 name */
const dirs = ref<{ name: string; path?: string; parent?: string; count: number }[]>([])
/** 目录全路径（兼容：后端尚未返回 path 时回落到 name） */
function dirPath(f: { name: string; path?: string; parent?: string }): string {
  return f.path || f.name
}
/** 层级展示名：顶层=自身名；子级=「父路径 / 名」 */
function dirLabel(f: { name: string; path?: string; parent?: string }): string {
  return f.parent ? `${f.parent} / ${f.name}` : f.name
}
const autoId = ref('') // 新建页自动建档后的笔记 id
const lastSavedAt = ref('')
const saved = reactive({ title: '', folder: '', content: '' })
let timer: ReturnType<typeof setInterval> | undefined

function norm() {
  return { title: form.title.trim() || '未命名', folder: form.folder || '', content: form.content }
}
function isDirty(): boolean {
  const n = norm()
  return n.title !== saved.title || n.folder !== saved.folder || n.content !== saved.content
}
function markSaved(updatedText?: string) {
  Object.assign(saved, norm())
  if (updatedText) {
    const s = String(updatedText)
    lastSavedAt.value = s.includes(':') ? s.slice(11, 19) : s
  }
}
function payloadRaw() {
  return { title: form.title.trim(), type: 'note', module: 'ielts', folder: form.folder || '', tags: [] as string[], summary: '', content: form.content }
}
function targetId() {
  return autoId.value || id.value
}

/** 有改动则保存一次；返回 true=无事/成功，false=失败 */
async function tryAutoSave(): Promise<boolean> {
  if (autoBusy.value || !isDirty()) return true
  const rawTitle = form.title.trim()
  if (!rawTitle && !form.content.trim()) return true
  autoBusy.value = true
  const body = { ...payloadRaw(), title: rawTitle || '未命名' }
  try {
    if (isNew.value && !autoId.value) {
      const r = await http.post<{ id: string; updated: string }>('/notes', body)
      autoId.value = r.id
      markSaved(r.updated)
    } else {
      const target = targetId()
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
  if (autoBusy.value || !isDirty()) return
  const rawTitle = form.title.trim()
  if (!rawTitle && !form.content.trim()) return
  const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` }
  const body = JSON.stringify({ ...payloadRaw(), title: rawTitle || '未命名' })
  const isFirst = isNew.value && !autoId.value
  const target = targetId()
  if (isFirst) {
    fetch('/api/notes', { method: 'POST', headers, body, keepalive: true }).catch(() => {})
  } else if (target) {
    fetch(`/api/notes/${target}`, { method: 'PUT', headers, body, keepalive: true }).catch(() => {})
  }
}

async function doSave() {
  // 允许"暂时不命名"：标题留空按「未命名」创建（之后在雅思主页改名）
  const body = { ...payloadRaw(), title: form.title.trim() || '未命名' }
  saving.value = true
  try {
    if (isNew.value && !autoId.value) {
      const r = await http.post<{ id: string; updated: string }>('/notes', body)
      autoId.value = r.id
      markSaved(r.updated)
      ElMessage.success('子页已创建')
      router.replace('/ielts')
    } else {
      const target = targetId()
      if (!target) return
      const r = await http.put<{ updated: string }>(`/notes/${target}`, body)
      markSaved(r.updated)
      ElMessage.success('已保存')
      router.replace(`/ielts/doc/${target}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function goBack() {
  if (isNew.value) router.push('/ielts')
  else router.push(`/ielts/doc/${id.value}`)
}

onBeforeRouteLeave(async () => {
  // P0：保存失败不再静默放行（与 NoteEdit 同型丢稿修复）
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
  try {
    const r = await http.get<{ items: { name: string; count: number }[] }>('/notes/folders?module=ielts')
    dirs.value = r.items
  } catch { /* ignore */ }
  if (isNew.value) {
    const q = String(route.query.title || '').trim()
    if (q) form.title = q
    markSaved()
    loading.value = false
    timer = setInterval(() => { tryAutoSave() }, AUTO_SAVE_MS)
    return
  }
  try {
    const n = await http.get<any>(`/notes/${id.value}`)
    if ((n.module || '') !== 'ielts') {
      ElMessage.warning('这不是雅思模块的子页')
      router.replace('/ielts')
      return
    }
    form.title = n.title
    form.folder = n.folder || ''
    form.content = n.content
    markSaved(n.updated)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
    router.replace('/ielts')
  } finally {
    loading.value = false
    timer = setInterval(() => { tryAutoSave() }, AUTO_SAVE_MS)
  }
})

onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('pagehide', onPageHide)
})
</script>

<style scoped>
.page { max-width: 1500px; }
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.sub-name { font-size: 16px; font-weight: 800; }
.save-hint { margin-left: auto; color: var(--txt2); font-size: 12px; white-space: nowrap; }
.form { padding: 14px 18px; margin-bottom: 14px; max-width: 1000px; }
.f-folder { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.ff-label { font-size: 12.5px; color: var(--txt2); flex: none; }
.foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
</style>
