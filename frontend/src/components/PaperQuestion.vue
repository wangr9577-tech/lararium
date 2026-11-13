<template>
  <el-drawer :model-value="modelValue" title="论文问答与对比" size="min(720px, 100%)" @update:model-value="emit('update:modelValue', $event)">
    <div class="qa">
      <p class="help">从选中的论文提取原文片段回答；引用可打开对应页。最多选择 4 篇。</p>
      <el-select v-model="selected" multiple filterable :multiple-limit="4" placeholder="选择论文" style="width: 100%" :loading="loadingPapers">
        <el-option v-for="p in papers" :key="p.id" :label="p.title || '未命名论文'" :value="p.id" />
      </el-select>
      <el-input v-model="question" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="例如：比较这些论文使用的数据、方法和各自局限。" />
      <div class="actions"><el-button type="primary" :loading="loading" :disabled="!selected.length || !question.trim()" @click="ask">{{ selected.length > 1 ? '比较论文' : '提问' }}</el-button></div>
      <template v-if="result">
        <el-alert v-if="result.reason" :title="result.reason" type="warning" :closable="false" show-icon />
        <div v-if="result.claims.length" class="answer">
          <h3>回答</h3>
          <div v-for="(claim, i) in result.claims" :key="i" class="claim">
            <div>{{ claim.text }}</div>
            <details v-for="ref in claim.citations" :key="ref.id" class="citation">
              <summary>{{ ref.title }} · 第 {{ ref.page }} 页</summary>
              <p>{{ ref.text }}</p>
              <a :href="`/papers/${encodeURIComponent(ref.paper_id)}?page=${ref.page}`" target="_blank" rel="noopener">打开原文对应页 ↗</a>
            </details>
          </div>
          <p v-if="result.uncertainty" class="help">不确定与限制：{{ result.uncertainty }}</p>
          <p class="help">引用指向提供给模型的原文片段，不能自动证明每条回答都被原文支持；请展开核对。</p>
        </div>
        <div v-if="result.coverage.length" class="coverage">
          <h3>本次使用范围</h3>
          <div v-for="c in result.coverage" :key="c.paper_id" class="coverage-item">
            <strong>{{ c.title }}</strong>
            <div>PDF 共 {{ c.total_pages }} 页；检查 {{ c.scanned_pages }} 页，其中 {{ c.text_pages }} 页提取到文字。</div>
            <div>送入模型：{{ c.sent_chunks }} 个片段<span v-if="c.sent_pages.length">，第 {{ c.sent_pages.join('、') }} 页</span>。
              {{ c.selection === 'sample' ? '问题与原文无词面匹配，使用均匀抽样。' : c.selection === 'keyword' ? '按关键词匹配选取。' : '没有可用片段。' }}</div>
            <div v-if="c.truncated_pages.length">以下页面文字过长，仅提取前部分：{{ c.truncated_pages.join('、') }}。</div>
            <div v-if="c.failed_pages.length">以下页面提取失败：{{ c.failed_pages.join('、') }}。</div>
            <div v-if="c.scanned_pages < c.total_pages">超过 {{ c.scanned_pages }} 页的部分未检查。</div>
          </div>
          <p class="help">仅基于已送入模型的片段；关键词检索可能遗漏相关内容，中文问题未必匹配英文原文。扫描页、图表和公式可能无法提取。</p>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, http } from '../api/client'

interface Paper { id: string; title: string }
interface Reference { id: string; paper_id: string; title: string; page: number; text: string }
interface Coverage { paper_id: string; title: string; total_pages: number; scanned_pages: number; text_pages: number; sent_pages: number[]; sent_chunks: number; selection: string; truncated_pages: number[]; failed_pages: number[] }
interface Result { ok: boolean; reason?: string; uncertainty?: string; claims: { text: string; citations: Reference[] }[]; coverage: Coverage[] }
const props = defineProps<{ modelValue: boolean; paperId: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
const selected = ref<string[]>([props.paperId])
const papers = ref<Paper[]>([])
const question = ref('')
const loading = ref(false)
const loadingPapers = ref(false)
const result = ref<Result | null>(null)

watch(() => props.modelValue, async (open) => {
  if (!open) return
  loadingPapers.value = true
  try {
    const response = await http.get<{ items: Paper[] }>('/papers')
    papers.value = response.items
    if (!selected.value.length) selected.value = [props.paperId]
  } catch {
    papers.value = [{ id: props.paperId, title: '当前论文' }]
  } finally { loadingPapers.value = false }
})

async function ask() {
  if (loading.value) return
  result.value = null
  loading.value = true
  try {
    const response = await api.post<Result>('/ai/paper-question', { paper_ids: selected.value, question: question.value.trim() }, { timeout: 240000 })
    result.value = response.data
  } catch (e: any) {
    result.value = { ok: false, reason: e?.response?.data?.detail || '请求失败，请检查 AI 服务后重试。', claims: [], coverage: [] }
  } finally { loading.value = false }
}
</script>

<style scoped>
.qa { display: flex; flex-direction: column; gap: 14px; }
.help { color: var(--txt2); font-size: 12px; line-height: 1.6; margin: 0; }
.actions { display: flex; justify-content: flex-end; }
h3 { font-size: 15px; margin: 4px 0 10px; }
.claim, .coverage-item { padding: 10px 0; border-top: 1px solid var(--border); line-height: 1.6; }
.citation { margin: 8px 0; padding: 8px 10px; background: var(--bg2, #f5f6f8); border-radius: 6px; font-size: 12px; overflow-wrap: anywhere; }
.citation summary { cursor: pointer; font-weight: 600; }
.citation p { white-space: pre-wrap; }
.coverage-item { font-size: 12px; }
</style>
