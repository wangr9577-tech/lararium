<template>
  <el-dialog
    :model-value="modelValue"
    title="关联相关资料"
    width="680px"
    @update:model-value="emit('update:modelValue', $event)"
    @open="load"
  >
    <div class="rmp-tip">
      关联只是在事项里建立双向软链接入口：不会修改、也不会复制资料本身的内容，资料正文仍在「笔记·博客 / 论文阅读 / 项目文档」里维护。
    </div>

    <div class="rmp-filter-row">
      <el-radio-group v-model="activeKind" size="small" @change="onKindChange">
        <el-radio-button label="all">全部资料</el-radio-button>
        <el-radio-button label="note">笔记·博客</el-radio-button>
        <el-radio-button label="paper">论文阅读</el-radio-button>
        <el-radio-button label="doc">项目文档</el-radio-button>
      </el-radio-group>
      <el-input v-model="q" placeholder="搜索标题 / 摘要 / 作者 / 路径…" clearable class="rmp-search-input" @input="onInput" @clear="onInput">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <div v-loading="loading" class="rmp-list">
      <div v-for="c in list" :key="rowKey(c)" class="rmp-item">
        <span class="rmp-type" :class="'type-' + c.target_type">{{ kindLabel(c.kind) }}</span>
        <span class="rmp-title" :title="c.title">{{ c.title }}</span>
        <span v-if="subText(c)" class="rmp-sum" :title="subText(c)">{{ subText(c) }}</span>
        <span class="rmp-act">
          <el-tag v-if="isLinked(c)" size="small" type="info" effect="plain">已关联</el-tag>
          <el-button
            size="small"
            :type="isLinked(c) ? 'default' : 'primary'"
            :disabled="isLinked(c)"
            :loading="busyKey === rowKey(c)"
            @click="link(c)"
          >关联</el-button>
        </span>
      </div>
      <div v-if="!loading && !list.length" class="rmp-empty">
        没有找到可关联的资料
        <span class="rmp-empty-hint">在「笔记·博客」、「论文阅读」或挂载的项目文档里存在资料后，即可在此检索并双向软链接</span>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { kindLabel, workbenchApi, type WbCandidate } from '../api/workbench'

const props = defineProps<{ modelValue: boolean; itemId: number; kind?: 'all' | 'note' | 'paper' | 'doc' | 'project_doc' | string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'changed'): void }>()

const activeKind = ref<string>('all')
const q = ref('')
const list = ref<WbCandidate[]>([])
const loading = ref(false)
/** 已关联到本事项的资料键（target_type:target_id） */
const linkedKeys = ref<Set<string>>(new Set())
/** 正在提交关联的资料键（转圈） */
const busyKey = ref('')
/** 请求序号：搜索是异步的，只接受最后一次发出的响应（防乱序覆盖） */
let seq = 0
let debounce: ReturnType<typeof setTimeout> | undefined

const rowKey = (c: WbCandidate) => `${c.target_type}:${c.target_id}`
const isLinked = (c: WbCandidate) => linkedKeys.value.has(rowKey(c))
/** 行内灰色摘要：优先摘要，其次作者 / 目录 */
function subText(c: WbCandidate): string {
  return (c.summary || '').trim() || (c.author || '').trim() || (c.folder || '').trim()
}

/** 拉候选资料（q 由后端过滤）；过期响应直接丢弃 */
async function fetchList() {
  const my = ++seq
  loading.value = true
  try {
    const k = activeKind.value || 'all'
    const r = await workbenchApi.selector(q.value.trim(), k, 40)
    if (my !== seq) return
    list.value = r.items || []
  } catch (e: any) {
    if (my !== seq) return
    list.value = []
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '资料加载失败，请稍后重试')
    }
  } finally {
    if (my === seq) loading.value = false
  }
}

/** 已关联清单：用于把已关联的候选标出来（按 target_type + target_id 匹配） */
async function fetchLinks() {
  if (!props.itemId) return
  try {
    const r = await workbenchApi.listLinks(props.itemId)
    linkedKeys.value = new Set(
      (r.items || []).map((l) => `${l.target_type}:${l.target_id}`),
    )
  } catch { /* 401/423 由拦截器接管；其余错误不打断选择 */ }
}

/** 打开对话框：重置搜索词并刷新候选 + 已关联清单 */
async function load() {
  q.value = ''
  busyKey.value = ''
  activeKind.value = props.kind || 'all'
  await Promise.all([fetchList(), fetchLinks()])
}

function onKindChange() {
  fetchList()
}

/** 搜索防抖 250ms 后再查后端 */
function onInput() {
  clearTimeout(debounce)
  debounce = setTimeout(() => { fetchList() }, 250)
}

/** 关联候选：后端幂等（created=false 表示早就关联过）；成功即通知父组件刷新，对话框保持打开以便连续关联 */
async function link(c: WbCandidate) {
  const k = rowKey(c)
  if (isLinked(c) || busyKey.value === k) return
  busyKey.value = k
  try {
    const r = await workbenchApi.addLink(props.itemId, c.target_type, c.target_id)
    linkedKeys.value = new Set(linkedKeys.value).add(k)
    if (r?.created) ElMessage.success('已关联')
    else ElMessage.info('这个资料已经关联过了')
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '关联失败，请稍后重试')
  } finally {
    busyKey.value = ''
  }
}

onBeforeUnmount(() => { clearTimeout(debounce) })
</script>

<style scoped>
.rmp-tip { color: var(--txt2); font-size: 12px; line-height: 1.6; margin: 2px 0 10px; }
.rmp-filter-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.rmp-search-input { flex: 1; min-width: 220px; }
</style>

<style>
/* 关联资料选择器：对话框内容 teleport 到 body，行样式须放非 scoped 块（沿用站内既有约定） */
.rmp-list { display: grid; gap: 6px; max-height: 48vh; overflow-y: auto; margin-top: 10px; min-height: 120px; }
.rmp-item {
  display: flex; align-items: center; gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 10px;
  padding: 8px 12px; transition: border-color .15s, background .15s;
}
.rmp-item:hover { border-color: var(--acc2); background: rgba(139, 92, 246, 0.08); }
.rmp-type {
  flex: none; font-size: 11px; padding: 2px 8px; border-radius: 999px;
  font-weight: 500;
}
.rmp-type.type-note { background: rgba(167, 139, 250, 0.16); color: #8b5cf6; }
.rmp-type.type-paper { background: rgba(59, 130, 246, 0.16); color: #3b82f6; }
.rmp-type.type-doc, .rmp-type.type-project_doc { background: rgba(245, 158, 11, 0.16); color: #f59e0b; }

.rmp-title {
  flex: none; max-width: 42%; font-weight: 600; font-size: 13.5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rmp-sum {
  min-width: 0; flex: 1; color: var(--txt3); font-size: 12px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
html.theme-dark .rmp-sum { color: var(--txt2); }
.rmp-act { flex: none; margin-left: auto; display: inline-flex; align-items: center; gap: 8px; }
.rmp-empty { color: var(--txt2); font-size: 13px; text-align: center; padding: 24px 0 20px; }
.rmp-empty-hint { display: block; color: var(--txt3); font-size: 11.5px; margin-top: 6px; }
html.theme-dark .rmp-empty-hint { color: var(--txt2); }
</style>