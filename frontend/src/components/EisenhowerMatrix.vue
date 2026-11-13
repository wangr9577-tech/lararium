<template>
  <div class="glass ezn">
    <div class="ezn-head">
      <span class="ezn-title grad-text">艾森豪威尔矩阵</span>
      <span class="ezn-tip">按重要 / 紧急把要做的事放进四象限 · 矩阵保存在服务端；关联任务的完成状态可同步，名称独立编辑</span>
      <el-button size="small" text @click="clearDone">清除已完成</el-button>
    </div>

    <div class="ezn-grid">
      <!-- 表头：紧急程度 -->
      <div class="ezn-corner">重要 \ 紧急</div>
      <div class="ezn-colh">紧急</div>
      <div class="ezn-colh">不紧急</div>

      <!-- 两行：重要 / 不重要，每行两个象限 -->
      <template v-for="(row, ri) in rows" :key="ri">
        <div class="ezn-rowh">{{ rowLabels[ri] }}</div>
        <div
          v-for="q in row" :key="q.n"
          class="ezn-cell" :class="'q' + q.n"
          @dragover.prevent
          @drop="onDrop(q.n, $event)"
        >
          <div class="qhead">
            <span class="qname">{{ q.name }}</span>
            <span class="qsub">{{ q.sub }}</span>
            <span class="qcnt">{{ quadItems(q.n).length }}</span>
          </div>
          <div class="qbody">
            <div
              v-for="it in quadItems(q.n)" :key="it.id"
              class="qitem" :class="{ done: it.done }" draggable="true"
              @dragstart="onDragStart(it, $event)"
            >
              <span class="qdot" title="点击标记完成 / 取消" @click="toggle(it)"></span>
              <el-input
                v-if="editingId === it.id"
                v-model="editText"
                size="small"
                class="qedit"
                @keyup.enter="commitEdit(it)"
                @blur="commitEdit(it)"
              />
              <span v-else class="qtext" title="点击修改" @click="startEdit(it)">{{ it.text }}<small v-if="it.scheduleId"> · 关联任务</small></span>
              <el-button text circle size="small" class="qdel" @click="remove(it)">
                <el-icon :size="12"><Close /></el-icon>
              </el-button>
            </div>
            <div v-if="!quadItems(q.n).length" class="qempty">{{ q.empty }}</div>
          </div>
          <div class="qadd">
            <el-select v-model="selectedTasks[q.n]" placeholder="从任务添加" size="small" clearable><el-option v-for="task in tasks" :key="task.id" :label="task.title" :value="task.id" /></el-select>
            <el-button size="small" @click="addTask(q.n)">加入</el-button>
          </div>
          <div class="qadd">
            <el-input
              v-model="drafts[q.n]"
              size="small"
              :placeholder="q.ph"
              @keyup.enter="addItem(q.n)"
            />
            <el-button size="small" type="primary" plain :disabled="!drafts[q.n].trim()" @click="addItem(q.n)">添加</el-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { clientState } from '../api/clientState'
import { reactive, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { http } from '../api/client'

const emit = defineEmits<{ (e: 'changed'): void }>()
const props = withDefaults(defineProps<{ tasks?: { id: number; title: string }[] }>(), { tasks: () => [] })
const selectedTasks = reactive<Record<number, number | undefined>>({})
function addTask(q: 1 | 2 | 3 | 4) {
  const task = props.tasks.find(t => t.id === selectedTasks[q])
  if (!task) return ElMessage.warning('请选择任务')
  if (items.value.some(it => it.scheduleId === task.id)) return ElMessage.warning('该任务已在矩阵中')
  items.value.push({ id: `e${Date.now()}${Math.random().toString(36).slice(2, 6)}`, q, text: task.title, done: !!(task as any).done, scheduleId: task.id })
  persist()
  selectedTasks[q] = undefined
}
/** 四象限条目：矩阵条目保存在服务端 */
interface EzItem { id: string; q: 1 | 2 | 3 | 4; text: string; done: boolean; scheduleId?: number }

// 固定键不包含日期，沿用原键以保留已有矩阵数据。
const STORE_KEY = 'krs_ei…ower'

const quads = [
  { n: 1 as const, name: '马上做', sub: '重要且紧急 · 先处理', ph: '马上要做的事…', empty: '把火烧眉毛又重要的事放这里' },
  { n: 2 as const, name: '做计划', sub: '重要不紧急 · 排期推进', ph: '计划推进的事…', empty: '重要但不着急的事，安排到具体日子' },
  { n: 3 as const, name: '委托 / 从简', sub: '紧急不重要 · 快办或交出去', ph: '可委托或快办的事…', empty: '被打断的事，能委托就委托' },
  { n: 4 as const, name: '少做 / 删除', sub: '不重要不紧急 · 能省则省', ph: '想削减的事…', empty: '刷手机之类的，写下来反而就戒掉了' },
]
/** 行布局：[重要行 = Q1 Q2] / [不重要行 = Q3 Q4]，与上方「紧急 / 不紧急」表头对应 */
const rows = [[quads[0], quads[1]], [quads[2], quads[3]]]
const rowLabels = ['重要', '不重要']

function load(): EzItem[] {
  try {
    const raw = clientState.getItem(STORE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr)
      ? arr.filter((x: any) => x && typeof x.text === 'string' && [1, 2, 3, 4].includes(x.q)).map((x: any) => ({ id: String(x.id), q: x.q, text: String(x.text), done: !!x.done, scheduleId: Number.isInteger(x.scheduleId) ? x.scheduleId : undefined }))
      : []
  } catch { return [] }
}

const items = ref<EzItem[]>(load())
watch(() => props.tasks, tasks => {
  let changed = false
  for (const it of items.value) {
    const task = tasks.find(t => t.id === it.scheduleId) as (typeof tasks[number] & { done?: boolean }) | undefined
    if (task && typeof task.done === 'boolean' && task.done !== it.done) { it.done = task.done; changed = true }
  }
  if (changed) persist()
}, { immediate: true, deep: true })

function persist() {
  try { clientState.setItem(STORE_KEY, JSON.stringify(items.value)) } catch {
    ElMessage.error('矩阵保存失败，请检查服务连接')
  }
}

const drafts = reactive<Record<1 | 2 | 3 | 4, string>>({ 1: '', 2: '', 3: '', 4: '' })

function quadItems(q: 1 | 2 | 3 | 4) {
  return items.value.filter((it) => it.q === q)
}

function addItem(q: 1 | 2 | 3 | 4) {
  const text = drafts[q].trim()
  if (!text) return
  items.value.push({ id: `e${Date.now()}${Math.random().toString(36).slice(2, 6)}`, q, text, done: false })
  drafts[q] = ''
  persist()
}

async function toggle(it: EzItem) {
  if (it.scheduleId) {
    try { await http.put(`/schedule/${it.scheduleId}/done`, { done: !it.done }); emit('changed') }
    catch { return ElMessage.error('更新关联任务失败，请检查任务是否仍存在') }
  }
  it.done = !it.done; persist()
}

function remove(it: EzItem) {
  items.value = items.value.filter((x) => x.id !== it.id)
  persist()
}

function clearDone() {
  items.value = items.value.filter((x) => !x.done)
  persist()
}

/* 点击文本行内编辑（回车 / 失焦提交，清空则删除该条） */
const editingId = ref('')
const editText = ref('')

function startEdit(it: EzItem) {
  editingId.value = it.id
  editText.value = it.text
}

function commitEdit(it: EzItem) {
  if (editingId.value !== it.id) return
  editingId.value = ''
  const text = editText.value.trim()
  if (!text) remove(it)
  else if (text !== it.text) { it.text = text; persist() }
}

/* 条目可在象限之间拖拽挪动 */
let dragId = ''

function onDragStart(it: EzItem, ev: DragEvent) {
  dragId = it.id
  ev.dataTransfer?.setData('text/plain', it.id)
}

function onDrop(q: 1 | 2 | 3 | 4, ev: DragEvent) {
  const id = ev.dataTransfer?.getData('text/plain') || dragId
  const it = items.value.find((x) => x.id === id)
  if (it && it.q !== q) { it.q = q; persist() }
  dragId = ''
}
</script>

<style scoped>
.ezn { padding: 14px 16px 16px; }
.ezn-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.ezn-title { font-size: 16px; font-weight: 800; }
.ezn-tip { font-size: 11.5px; color: var(--txt2); }
.ezn-head .el-button { margin-left: auto; }

.ezn-grid { display: grid; grid-template-columns: 56px 1fr 1fr; gap: 6px; }
.ezn-corner { font-size: 10.5px; color: var(--txt2); display: flex; align-items: flex-end; padding-bottom: 4px; }
.ezn-colh, .ezn-rowh { display: grid; place-items: center; font-size: 12.5px; font-weight: 700; color: var(--txt2); letter-spacing: 2px; }

.ezn-cell { border-radius: 12px; padding: 10px 12px; border: 1px solid transparent; min-height: 170px; display: flex; flex-direction: column; }
/* 四象限配色：重要紧急=红 重要不紧急=紫 紧急不重要=橙 都不=灰 */
.q1 { background: rgba(245, 108, 108, 0.07); border-color: rgba(245, 108, 108, 0.28); }
.q2 { background: rgba(167, 139, 250, 0.07); border-color: rgba(167, 139, 250, 0.28); }
.q3 { background: rgba(230, 162, 60, 0.07); border-color: rgba(230, 162, 60, 0.28); }
.q4 { background: rgba(148, 163, 184, 0.07); border-color: rgba(148, 163, 184, 0.25); }

.qhead { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.qname { font-size: 14px; font-weight: 800; }
.q1 .qname { color: var(--el-color-danger); }
.q2 .qname { color: var(--acc2, #a78bfa); }
.q3 .qname { color: var(--el-color-warning); }
.q4 .qname { color: var(--txt2); }
.qsub { font-size: 11px; color: var(--txt2); }
.qcnt { margin-left: auto; font-size: 11px; color: #fff; background: rgba(148, 163, 184, 0.5); border-radius: 999px; padding: 0 7px; }

.qbody { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.qitem { display: flex; align-items: center; gap: 6px; padding: 3px 6px; border-radius: 7px; background: rgba(255, 255, 255, 0.05); border: 1px solid transparent; cursor: grab; }
.qitem:hover { border-color: rgba(148, 163, 184, 0.3); }
.qitem.done { opacity: 0.5; }
.qitem.done .qtext { text-decoration: line-through; color: var(--txt2); }
.qdot { width: 12px; height: 12px; flex: none; border-radius: 50%; border: 1.5px solid var(--txt2); cursor: pointer; }
.q1 .qdot { border-color: var(--el-color-danger); }
.q2 .qdot { border-color: var(--acc2, #a78bfa); }
.q3 .qdot { border-color: var(--el-color-warning); }
.qitem.done .qdot { background: var(--txt2); }
.qtext { flex: 1; min-width: 0; font-size: 13px; overflow-wrap: anywhere; cursor: text; }
.qedit { flex: 1; }
.qdel { opacity: 0; transition: opacity 0.15s; }
.qitem:hover .qdel { opacity: 1; }
.qempty { font-size: 12px; color: var(--txt2); padding: 10px 2px; line-height: 1.6; }

.qadd { display: flex; gap: 6px; margin-top: 8px; }
.qadd .el-input { flex: 1; }

@media (max-width: 900px) {
  .ezn-grid { grid-template-columns: 40px 1fr; }
}
</style>
