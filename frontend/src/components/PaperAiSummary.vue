<template>
  <el-dialog v-model="visible" :title="kind === 'summary' ? 'AI 论文摘要' : 'AI 选区解释'" width="min(760px, 95vw)">
    <div v-if="loading">正在分析论文文本，请稍候…</div>
    <template v-else-if="result">
      <p class="coverage">{{ coverageText }}。仅分析 PDF 文本层，图表、公式和扫描页可能未被读取；AI 解释与引用的关联仍需人工核对。</p>
      <div v-if="kind === 'summary'">
        <div v-for="(item, i) in result.items" :key="i" class="result-item">
          <strong>{{ item.section }}</strong><p>{{ item.text }}</p>
          <div v-for="source in item.sources" :key="source.id" class="source">
            <el-button text size="small" type="primary" @click="jump(source.page)">第 {{ source.page }} 页</el-button>
            <span>{{ source.quote }}</span>
          </div>
        </div>
        <div class="edit-title">编辑摘要笔记</div>
        <el-input v-model="note" type="textarea" :rows="12" />
      </div>
      <div v-else>
        <div class="source"><el-button text size="small" type="primary" @click="jump(result.page)">第 {{ result.page }} 页</el-button>{{ result.quote }}</div>
        <p class="answer">{{ result.answer }}</p>
      </div>
    </template>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button v-if="kind === 'summary' && result" type="primary" :loading="saving" @click="save">保存为可编辑笔记</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, http } from '../api/client'

interface Source { id: string; page: number; quote: string }
interface Item { section: string; text: string; sources: Source[] }
interface Result { items?: Item[]; answer?: string; page?: number; quote?: string; coverage: { total_pages: number; text_pages?: number; included_pages: number[]; truncated_pages?: number[]; partial_page?: boolean } }
const props = defineProps<{ paperId: string; title?: string }>()
const emit = defineEmits<{ (e: 'jump', page: number): void }>()
const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const kind = ref<'summary' | 'explain'>('summary')
const result = ref<Result | null>(null)
const note = ref('')
const error = ref('')
const coverageText = computed(() => {
  const c = result.value?.coverage
  if (!c) return ''
  if (kind.value === 'explain') return `全文共 ${c.total_pages} 页，分析第 ${c.included_pages.join('、')} 页${c.partial_page ? '的部分文本' : '文本'}`
  return `全文共 ${c.total_pages} 页，其中 ${c.text_pages} 页有文本；本次输入第 ${c.included_pages.join('、')} 页${c.truncated_pages?.length ? `；未完整输入的有文本页：${c.truncated_pages.join('、')}` : ''}`
})
function jump(page?: number) { if (page) { visible.value = false; emit('jump', page) } }
async function run(mode: 'summary' | 'explain', page = 1, selection = '') {
  kind.value = mode; visible.value = true; loading.value = true; result.value = null; error.value = ''
  try {
    const { data } = await api.post(`/ai/paper-${mode}`, { paper_id: props.paperId, page, selection }, { timeout: mode === 'summary' ? 660000 : 180000 })
    if (!data.ok) throw new Error(data.reason || 'AI 服务不可用')
    result.value = data
    if (mode === 'summary') {
      const link = `/papers/${encodeURIComponent(props.paperId)}`
      const lines = [`# ${props.title || '论文'} · AI 摘要`, '', `[返回论文](${link})`, '', coverageText.value, '', '> AI 生成内容与证据关联需要人工核对。', '']
      for (const item of data.items as Item[]) {
        lines.push(`## ${item.section}`, '', item.text, '')
        for (const s of item.sources) lines.push(`- [第 ${s.page} 页](${link}?page=${s.page})：${s.quote}`)
        lines.push('')
      }
      note.value = lines.join('\n')
    }
  } catch (e: any) { error.value = e?.response?.data?.detail || e?.message || 'AI 服务不可用' }
  finally { loading.value = false }
}
async function save() {
  saving.value = true
  try {
    const r = await http.post<{ id: string }>('/notes', { title: `${props.title || '论文'} · AI 摘要`, type: 'note', tags: ['论文', 'AI摘要', `paper:${props.paperId}`], summary: '论文 AI 摘要，引用需人工核对', content: note.value })
    ElMessage.success('已保存为笔记，可继续编辑')
    window.open(`/notes/${encodeURIComponent(r.id)}`, '_blank', 'noopener')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}
defineExpose({ openSummary: () => run('summary'), explain: (page: number, text: string) => run('explain', page, text) })
</script>

<style scoped>
.coverage { color: var(--txt2); font-size: 12px; line-height: 1.6; }
.result-item { border-top: 1px solid var(--el-border-color); padding: 10px 0; }
.result-item p { margin: 6px 0; white-space: pre-wrap; }
.source { font-size: 12px; color: var(--txt2); line-height: 1.5; overflow-wrap: anywhere; }
.edit-title { margin: 16px 0 8px; font-weight: 600; }
.answer { white-space: pre-wrap; line-height: 1.7; }
.error { color: var(--el-color-danger); }
</style>
