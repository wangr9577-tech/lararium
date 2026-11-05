<template>
  <section class="diary-assistant glass">
    <div class="header"><div><strong>日记助手</strong><p>随时保存文字片段，整理后由你确认写入日记。</p></div><el-date-picker :model-value="date" @change="changeDate" type="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="busy" /></div>
    <p class="privacy">片段保存在你的日记数据中；生成草稿或用途建议时，所选文字和附件会发送给配置的模型服务。请仅上传愿意发送给模型服务的内容。</p>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div v-loading="busy">
      <div class="capture-zone" :class="{ 'drag-active': draggingFiles }" @dragenter.prevent.stop="onDragEnter" @dragover.prevent.stop="onDragOver" @dragleave.prevent.stop="onDragLeave" @drop.prevent.stop="onDrop">
        <el-input v-model="newContent" type="textarea" :rows="3" placeholder="记录此刻的想法，可多次保存" />
        <div class="upload-row">
          <label class="upload-label">拖动文件到这里，或 <span>点击选择文件</span><input type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.md" @change="selectFiles" /></label>
          <span class="muted">图片会交给视觉模型处理；支持图片、PDF、TXT、Markdown，单个不超过 10 MiB，总计不超过 30 MiB。</span>
          <ul v-if="files.length" class="pending-files"><li v-for="(file, i) in files" :key="`${file.name}-${file.size}-${file.lastModified}`"><span>{{ file.name }}（{{ formatSize(file.size) }}）</span><el-button text type="danger" size="small" :aria-label="`移除 ${file.name}`" @click="removeFile(i)">移除</el-button></li></ul>
        </div>
      </div>
      <div class="actions"><el-button type="primary" :disabled="!newContent.trim() &amp;&amp; !files.length" @click="addFragment">保存片段</el-button></div>
      <div v-if="fragments.length" class="fragments">
        <article v-for="fragment in fragments" :key="fragment.id" class="fragment">
          <div class="fragment-head"><el-checkbox :model-value="isSelected(fragment)" @change="toggleFragment(fragment, Boolean($event))">用于生成</el-checkbox><span>{{ fragment.created_at }} <template v-if="fragment.adopted_at">· 已采用（可手动勾选重用）</template><template v-else-if="failedMarks.includes(fragment.id)">· 已写入，标记失败</template></span></div>
          <template v-if="editingId === fragment.id"><el-input v-model="editingContent" type="textarea" :rows="3" /><div class="actions"><el-button size="small" @click="editingId = null">取消</el-button><el-button size="small" type="primary" :disabled="!editingContent.trim()" @click="saveEdit(fragment)">保存修改</el-button></div></template>
          <template v-else><div class="fragment-content">{{ fragment.content }}</div><div v-for="attachment in fragment.attachments || []" :key="attachment.id" class="attachment"><span>{{ attachment.name }} · {{ formatSize(attachment.size) }}</span><el-button size="small" text @click="showAttachment(fragment, attachment)">{{ attachment.mime.startsWith('image/') ? '查看图片' : '下载附件' }}</el-button><img v-if="attachmentUrls[attachment.id] &amp;&amp; attachment.mime.startsWith('image/')" :src="attachmentUrls[attachment.id]" :alt="attachment.name" class="attachment-preview" /></div><div class="actions"><el-button size="small" text @click="edit(fragment)">编辑</el-button><el-button size="small" text @click="moveFragment(fragment)">调整日期</el-button><el-button size="small" text type="danger" @click="deleteFragment(fragment)">删除</el-button></div></template>
        </article>
      </div>
      <p v-else class="muted">这一天还没有片段。</p>
      <el-button :disabled="!selectedIds.length" :loading="generating" @click="generate">生成日记草稿</el-button><el-button :disabled="!selectedIds.length" @click="suggest">建议用途</el-button><div v-if="suggestions.length" class="suggestions"><h3>用途建议</h3><p class="muted">建议仅供参考，日记勾选不会改变；同一片段可以同时用于日记和待办。请逐条检查并确认。</p><div v-for="suggestion in suggestions" :key="suggestion.fragment_id" class="suggestion"><p>片段：{{ fragmentLabel(suggestion.fragment_id) }}<br />建议用于日记：{{ suggestion.diary ? '是' : '否' }}</p><div v-for="(task, index) in suggestion.tasks" :key="index" class="task-suggestion"><el-input v-model="task.title" aria-label="待办标题" :disabled="!!task.idempotencyKey" /><el-date-picker v-model="task.date" type="date" value-format="YYYY-MM-DD" placeholder="选择待办日期" :disabled="!!task.idempotencyKey" /><el-button :disabled="busy || !task.title.trim() || !task.date || task.created" @click="createTask(suggestion, task)">{{ task.created ? '已创建' : task.idempotencyKey ? '重试创建' : '确认创建待办' }}</el-button></div></div></div>
      <div class="schedule"><h3>定时整理草稿</h3><p class="muted">执行时发送所选片段的最新已保存内容及附件给模型（使用服务器本地时间）；服务运行且保险库解锁时执行，过期任务会在服务恢复后补执行。结果只保存为加密草稿，不会自动写入日记。</p><el-date-picker v-model="runAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择服务器本地执行时间" /><el-button :disabled="!selectedIds.length || !runAt || scheduled.status !== 'none'" @click="scheduleDraft">确认安排</el-button><el-button @click="loadScheduled">刷新状态</el-button><el-button v-if="scheduled.status !== 'none'" @click="clearScheduled">取消或清除</el-button><p>状态：{{ scheduleStatus }} <span v-if="scheduled.run_at">（{{ scheduled.run_at }}）</span></p><el-alert v-if="scheduled.error" :title="scheduled.error" type="error" :closable="false" /><el-button v-if="scheduled.status === 'ready'" @click="useScheduled">载入草稿编辑</el-button></div><div v-if="hasDraft" class="draft"><h3>可编辑草稿</h3><p class="muted">草稿尚未写入日记。修改后可预览最终结果。</p><el-input v-model="draft" type="textarea" :rows="8" /><div class="actions"><el-button type="primary" :disabled="!draft.trim()" @click="openPreview">预览并应用</el-button></div></div>
    </div>
    <el-dialog v-model="previewOpen" title="预览日记" width="min(700px, 95vw)" append-to-body>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
      <p>当前日期：{{ date }}。心情和天气将保留。</p>
      <el-radio-group v-model="mode"><el-radio value="append">追加到现有日记</el-radio><el-radio value="replace">替换日记正文</el-radio></el-radio-group>
      <p v-if="mode === 'replace'" class="warning">替换会覆盖现有正文，请仔细检查预览。</p>
      <div class="preview">{{ previewContent || '（空）' }}</div>
      <template #footer><el-button @click="previewOpen = false">返回编辑</el-button><el-button type="primary" :loading="busy" @click="apply">确认写入日记</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, http } from '../api/client'
interface Attachment { id: string; name: string; mime: string; size: number }
interface TaskSuggestion { title: string; date: string; created?: boolean; idempotencyKey?: string }
interface Suggestion { fragment_id: string; diary: boolean; tasks: TaskSuggestion[] }
interface Fragment { attachments?: Attachment[]; id: string; content: string; included: boolean; created_at: string; updated_at: string; adopted_at?: string }
interface Diary { content: string; mood: string; weather: string; updated: string; version: string }
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` }
const date = ref(today()), fragments = ref<Fragment[]>([]), diary = ref<Diary | null>(null)
const newContent = ref(''), editingId = ref<string | null>(null), editingContent = ref(''), draft = ref(''), hasDraft = ref(false)
const files = ref<File[]>([]), attachmentUrls = ref<Record<string, string>>({})
const suggestions = ref<Suggestion[]>([]), suggestionVersions = ref<Record<string, string>>({})
type Scheduled = { status: 'none' | 'queued' | 'ready' | 'failed'; run_at?: string; content?: string; fragment_ids?: string[]; fragment_versions?: Record<string, string>; error?: string }
const scheduled = ref<Scheduled>({ status: 'none' }), runAt = ref('')
const scheduleStatus = computed(() => ({ none: '未安排', queued: '等待执行', ready: '草稿已生成', failed: '生成失败' }[scheduled.value.status]))
const draggingFiles = ref(false)
let dragDepth = 0
const draftIds = ref<string[]>([])
const draftVersions = ref<Record<string, string>>({})
const reuseIds = ref<string[]>([]), failedMarks = ref<string[]>([])
const busy = ref(false), generating = ref(false), error = ref(''), previewOpen = ref(false), mode = ref<'append' | 'replace'>('append')
function isSelected(f: Fragment) { return f.included && (!(f.adopted_at || failedMarks.value.includes(f.id)) || reuseIds.value.includes(f.id)) }
const selectedIds = computed(() => fragments.value.filter(isSelected).map(f => f.id))
const previewContent = computed(() => mode.value === 'replace' ? draft.value : [diary.value?.content?.trimEnd(), draft.value].filter(Boolean).join('\n\n'))
function message(e: any) { return typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : e?.message || '操作失败，请重试' }
async function loadScheduled() { try { scheduled.value = await http.get<Scheduled>('/diary-tools/' + date.value + '/scheduled-draft') } catch(e) { error.value = '读取定时草稿状态失败：' + message(e) } }
async function scheduleDraft() { try { await ElMessageBox.confirm('将在指定时间把所选已保存片段发送给模型并保存草稿。继续吗？', '确认定时整理', { type: 'warning', confirmButtonText: '安排' }) } catch { return } busy.value = true; error.value = ''; try { scheduled.value = await http.post<Scheduled>('/diary-tools/' + date.value + '/scheduled-draft', { fragment_ids: selectedIds.value, run_at: runAt.value }) } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function clearScheduled() { try { await ElMessageBox.confirm('取消安排或清除已生成的定时草稿？', '确认清除', { type: 'warning' }) } catch { return } busy.value = true; error.value = ''; try { await http.del('/diary-tools/' + date.value + '/scheduled-draft'); scheduled.value = { status: 'none' } } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function useScheduled() { if (!scheduled.value.content || !scheduled.value.fragment_ids || !scheduled.value.fragment_versions) { error.value = '定时草稿数据不完整，请刷新状态'; return } if (hasDraft.value) { try { await ElMessageBox.confirm('载入会覆盖当前草稿，请先复制需要保留的内容。', '载入草稿', { type: 'warning' }) } catch { return } } draft.value = scheduled.value.content; draftIds.value = [...scheduled.value.fragment_ids]; draftVersions.value = { ...scheduled.value.fragment_versions }; hasDraft.value = true }
async function load() { busy.value = true; error.value = ''; try { const r = await http.get<{fragments: Fragment[]; diary: Diary}>(`/diary-assistant/${date.value}`); fragments.value = r.fragments; diary.value = r.diary; await loadScheduled() } catch(e) { fragments.value = []; diary.value = null; error.value = message(e) } finally { busy.value = false } }
async function changeDate(next: string) { if (!next || next === date.value) return; if (newContent.value.trim() || files.value.length || editingId.value || hasDraft.value || suggestions.value.some(s => s.tasks.some(t => t.idempotencyKey && !t.created))) { try { await ElMessageBox.confirm('切换日期会清除尚未保存的输入、草稿及待办重试标识；请先保存内容并确认待办结果。', '切换日期', { type: 'warning', confirmButtonText: '确认切换' }) } catch { return } } clearAttachmentUrls(); files.value = []; scheduled.value = { status: 'none' }; suggestions.value = []; suggestionVersions.value = {}; date.value = next; reuseIds.value = []; failedMarks.value = []; newContent.value = ''; editingId.value = null; draft.value = ''; draftIds.value = []; hasDraft.value = false; previewOpen.value = false; await load() }
onMounted(load)
function addFiles(incoming: File[]) {
  const allowed = /\.(png|jpe?g|webp|gif|pdf|txt|md)$/i
  const unsupported = incoming.filter(file => !allowed.test(file.name))
  const combined = [...files.value]
  for (const file of incoming.filter(file => allowed.test(file.name))) {
    if (!combined.some(existing => existing.name === file.name && existing.size === file.size && existing.lastModified === file.lastModified)) combined.push(file)
  }
  if (combined.length > 10 || combined.some(file => file.size > 10 * 1024 * 1024) || combined.reduce((sum, file) => sum + file.size, 0) > 30 * 1024 * 1024) {
    error.value = '最多选择 10 个文件；单个不超过 10 MiB，总计不超过 30 MiB。'
    return
  }
  files.value = combined
  error.value = unsupported.length ? `不支持这些文件：${unsupported.map(file => file.name).join('、')}` : ''
}
function selectFiles(event: Event) { const input = event.target as HTMLInputElement; addFiles(Array.from(input.files || [])); input.value = '' }
function removeFile(index: number) { files.value = files.value.filter((_, i) => i !== index) }
function onDragEnter(event: DragEvent) { if (!event.dataTransfer?.types.includes('Files')) return; dragDepth++; draggingFiles.value = true }
function onDragOver(event: DragEvent) { if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy' }
function onDragLeave() { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) draggingFiles.value = false }
function onDrop(event: DragEvent) { dragDepth = 0; draggingFiles.value = false; if (!busy.value) addFiles(Array.from(event.dataTransfer?.files || [])) }
function formatSize(size: number) { return size < 1024 * 1024 ? Math.ceil(size / 1024) + ' KiB' : (size / 1024 / 1024).toFixed(1) + ' MiB' }
function clearAttachmentUrls() { Object.values(attachmentUrls.value).forEach(URL.revokeObjectURL); attachmentUrls.value = {} }
onBeforeUnmount(clearAttachmentUrls)
async function showAttachment(fragment: Fragment, attachment: Attachment) { try { const blob = await http.blob('/diary-assistant/' + date.value + '/fragments/' + fragment.id + '/attachments/' + attachment.id); const url = URL.createObjectURL(blob); if (attachment.mime.startsWith('image/')) { if (attachmentUrls.value[attachment.id]) URL.revokeObjectURL(attachmentUrls.value[attachment.id]); attachmentUrls.value = { ...attachmentUrls.value, [attachment.id]: url } } else { const link = document.createElement('a'); link.href = url; link.download = attachment.name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) } } catch(e) { error.value = message(e) } }
async function addFragment() { if (files.value.some(f => f.size > 10 * 1024 * 1024) || files.value.reduce((n, f) => n + f.size, 0) > 30 * 1024 * 1024) { error.value = '附件超过大小限制'; return } busy.value = true; error.value = ''; try { let f: Fragment; if (files.value.length) { const data = new FormData(); data.append('content', newContent.value); files.value.forEach(file => data.append('files', file)); f = await http.post<Fragment>('/diary-assistant/' + date.value + '/fragments/upload', data) } else f = await http.post<Fragment>('/diary-assistant/' + date.value + '/fragments', { content: newContent.value }); fragments.value.push(f); newContent.value = ''; files.value = []; const input = document.querySelector<HTMLInputElement>('.diary-assistant input[type=file]'); if (input) input.value = '' } catch(e) { error.value = message(e) } finally { busy.value = false } }
function fragmentLabel(id: string) { const f = fragments.value.find(item => item.id === id); return f ? (f.content.slice(0, 100) || f.attachments?.map(a => a.name).join('、') || id) : id }
async function suggest() { if (suggestions.value.some(s => s.tasks.some(t => t.idempotencyKey && !t.created))) { try { await ElMessageBox.confirm('存在结果未知的待办请求。重新生成会丢失重试标识，可能重复创建；请优先重试并确认结果。', '重新生成建议', { type: 'warning', confirmButtonText: '仍然重新生成' }) } catch { return } } busy.value = true; error.value = ''; try { const r = await api.post<{suggestions: Suggestion[]; fragment_versions: Record<string, string>}>('/diary-tools/' + date.value + '/suggest', { fragment_ids: selectedIds.value }, { timeout: 120000 }); suggestions.value = r.data.suggestions.map(s => ({ ...s, tasks: s.tasks.map(t => ({ ...t, date: '' })) })); suggestionVersions.value = r.data.fragment_versions } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function createTask(suggestion: Suggestion, task: TaskSuggestion) { try { await ElMessageBox.confirm('创建待办“' + task.title + '”，日期 ' + task.date + '？', '确认创建待办', { type: 'warning', confirmButtonText: '创建' }) } catch { return } if (!task.idempotencyKey) { if (!globalThis.crypto?.randomUUID) { error.value = '当前环境无法安全生成待办标识，请在安全环境中打开应用'; return } task.idempotencyKey = globalThis.crypto.randomUUID() } busy.value = true; error.value = ''; try { await http.post('/diary-tools/' + date.value + '/tasks', { fragment_id: suggestion.fragment_id, fragment_version: suggestionVersions.value[suggestion.fragment_id], title: task.title, date: task.date, idempotency_key: task.idempotencyKey }); task.created = true; ElMessage.success('待办已创建') } catch(e) { error.value = message(e) + '；如果结果未知，可点击重试，同一建议会使用原请求标识。' } finally { busy.value = false } }
function edit(f: Fragment) { editingId.value = f.id; editingContent.value = f.content }
async function saveEdit(f: Fragment) { await update(f, { content: editingContent.value }); if (!error.value) editingId.value = null }
async function toggleFragment(f: Fragment, included: boolean) {
  if (f.adopted_at || failedMarks.value.includes(f.id)) {
    if (included && !f.included) { await update(f, { included: true }); if (error.value) return }
    reuseIds.value = included ? [...new Set([...reuseIds.value, f.id])] : reuseIds.value.filter(id => id !== f.id)
  } else await update(f, { included })
}
async function update(f: Fragment, changes: Partial<Fragment>) { busy.value = true; error.value = ''; try { const updated = await http.patch<Fragment>(`/diary-assistant/${date.value}/fragments/${f.id}`, changes); fragments.value = fragments.value.map(x => x.id === f.id ? updated : x) } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function moveFragment(f: Fragment) { let target: string; try { const result = await ElMessageBox.prompt('输入目标日期（YYYY-MM-DD）。移动后相关草稿需要重新生成。', '调整片段日期', { inputPattern: /^\d{4}-\d{2}-\d{2}$/, inputErrorMessage: '请输入 YYYY-MM-DD 格式的日期', inputValue: date.value }); target = result.value } catch { return } if (target === date.value) return; busy.value = true; error.value = ''; try { await http.post('/diary-assistant/' + date.value + '/fragments/' + f.id + '/move', { date: target }); fragments.value = fragments.value.filter(x => x.id !== f.id); suggestions.value = []; ElMessage.success('片段已移动到 ' + target) } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function deleteFragment(f: Fragment) { try { await ElMessageBox.confirm('删除这个片段？此操作无法撤销。', '删除片段', { type: 'warning' }) } catch { return } busy.value = true; error.value = ''; try { await http.del(`/diary-assistant/${date.value}/fragments/${f.id}`); fragments.value = fragments.value.filter(x => x.id !== f.id) } catch(e) { error.value = message(e) } finally { busy.value = false } }
async function generate() { if (hasDraft.value) { try { await ElMessageBox.confirm('重新生成会覆盖当前草稿，请先复制需要保留的内容。', '重新生成草稿', { type: 'warning', confirmButtonText: '继续生成' }) } catch { return } } generating.value = true; busy.value = true; error.value = ''; try { const r = await api.post<{content: string; fragment_versions: Record<string, string>}>(`/diary-assistant/${date.value}/draft`, { fragment_ids: selectedIds.value }, { timeout: 120000 }); draft.value = r.data.content; draftIds.value = [...selectedIds.value]; draftVersions.value = r.data.fragment_versions; hasDraft.value = true } catch(e) { error.value = message(e) } finally { busy.value = false; generating.value = false } }
async function openPreview() { if (!diary.value) return; previewOpen.value = true }
async function apply() { if (!diary.value) return; busy.value = true; error.value = ''; try { diary.value = await http.post<Diary & {adoption_mark_failed_ids?: string[]}>(`/diary-assistant/${date.value}/apply`, { content: draft.value, mode: mode.value, expected_version: diary.value.version, fragment_ids: draftIds.value, fragment_versions: draftVersions.value }); previewOpen.value = false; window.dispatchEvent(new CustomEvent('diary-assistant-applied', { detail: { date: date.value } })); const failed = (diary.value as Diary & { adoption_mark_failed_ids?: string[] }).adoption_mark_failed_ids || []; failedMarks.value = failed; fragments.value = fragments.value.map(f => draftIds.value.includes(f.id) && !failed.includes(f.id) ? { ...f, adopted_at: new Date().toISOString() } : f); reuseIds.value = []; draft.value = ''; draftIds.value = []; draftVersions.value = {}; hasDraft.value = false; if (failed.length) { error.value = `日记已写入，但 ${failed.length} 个片段的采用标记保存失败；请核对后再重用。`; ElMessage.warning(error.value) } else ElMessage.success('已写入日记') } catch(e: any) { if (e?.response?.status === 409) { previewOpen.value = false; error.value = '日记或片段已在别处修改，草稿仍保留。请核对最新内容；片段更改时需重新生成草稿。'; try { const r = await http.get<{diary: Diary; fragments: Fragment[]}>(`/diary-assistant/${date.value}`); diary.value = r.diary; fragments.value = r.fragments } catch { diary.value = null; error.value += ' 读取最新日记失败，请重新打开页面。' } } else error.value = message(e) } finally { busy.value = false } }
</script>
<style scoped>
.diary-assistant { padding: 18px; margin-bottom: 16px; } .header { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:center; } .header strong { font-size: 18px; } .header p,.muted { color:var(--el-text-color-secondary); font-size:13px; } .privacy { font-size:12px; color:var(--el-text-color-secondary); line-height:1.6; } .actions { display:flex; justify-content:flex-end; gap:6px; margin:8px 0; } .fragments { display:grid; gap:8px; margin:12px 0; } .fragment { border:1px solid var(--el-border-color-light); border-radius:10px; padding:10px; } .fragment-head { display:flex; justify-content:space-between; align-items:center; color:var(--el-text-color-secondary); font-size:12px; } .fragment-content,.preview { white-space:pre-wrap; overflow-wrap:anywhere; } .draft { margin-top:16px; } .preview { margin-top:14px; padding:12px; max-height:45vh; overflow:auto; border:1px solid var(--el-border-color); border-radius:8px; } .warning { color:var(--el-color-danger); } .schedule, .upload-row { margin-top:14px; } .capture-zone { border:1px dashed transparent; border-radius:10px; padding:4px; transition:border-color .15s, background .15s; } .capture-zone.drag-active { border-color:var(--el-color-primary); background:var(--el-color-primary-light-9); } .upload-label { display:block; padding:12px; border:1px dashed var(--el-border-color); border-radius:8px; cursor:pointer; color:var(--el-text-color-regular); } .upload-label span { color:var(--el-color-primary); } .upload-label input { position:absolute; width:1px; height:1px; opacity:0; } .upload-label:focus-within { outline:2px solid var(--el-color-primary); outline-offset:2px; } .upload-row > .muted { display:block; margin-top:6px; } .pending-files { list-style:none; margin:8px 0 0; padding:0; } .pending-files li { display:flex; justify-content:space-between; align-items:center; gap:8px; overflow-wrap:anywhere; } .attachment-preview { display:block; max-width:100%; max-height:240px; object-fit:contain; } .suggestion { border-top:1px solid var(--el-border-color-light); padding:8px 0; } .task-suggestion { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; } .task-suggestion .el-input { max-width:300px; }
</style>
