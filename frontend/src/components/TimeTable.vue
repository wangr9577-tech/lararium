<template>
  <div class="tt glass" id="timetable-panel">
    <div class="tt-head">
      <div class="tt-title">
        <span class="tt-icon"><el-icon :size="15"><Clock /></el-icon></span>
        <span class="tt-name grad-text">24h 时间表</span>
        <span class="tt-count" v-if="filledCnt">已填 {{ filledCnt }} / 72</span>
      </div>
      <div class="tt-nav">
        <button class="tt-arrow" aria-label="前一天" @click="move(-1)"><el-icon :size="14"><ArrowLeft /></el-icon></button>
        <span class="tt-date" :class="{ today: isToday }">{{ dateLabel }}</span>
        <button class="tt-arrow" aria-label="后一天" @click="move(1)"><el-icon :size="14"><ArrowRight /></el-icon></button>
        <button class="tt-mini" :disabled="isToday" @click="goToday">今天</button>
        <button class="tt-mini danger" :disabled="!filledCnt" @click="clearDay">清空</button>
      </div>
    </div>

    <div class="tt-task-add">
      <el-select v-model="taskId" placeholder="选择当天任务" clearable filterable style="width: 220px"><el-option v-for="task in tasks" :key="task.id" :label="task.title" :value="task.id" /></el-select>
      <el-time-picker v-model="taskTime" value-format="HH:mm" format="HH:mm" placeholder="安排时间" style="width: 130px" />
      <el-button @click="placeTask">填入时间表</el-button><span>复制任务名称，之后与任务独立编辑</span>
    </div>
    <div class="tt-body" ref="bodyEl">
      <!-- 一张连续的「纸」：20 分钟一条细行线，整点一条粗线并标时刻 -->
      <div class="tt-paper" :style="{ '--row': ROW + 'px' }">
        <div
          v-for="t in slots" :key="t" class="tt-row"
          :class="{ hour: t % 60 === 0, first: t === 0 }"
        >
          <span class="tt-hr" v-if="t % 60 === 0">{{ pad(t / 60) }}:00</span>
          <span class="tt-hr tt-hr-min" v-else>:{{ pad(t % 60) }}</span>
          <input
            v-if="editing === t"
            ref="editInput"
            v-model="editText"
            class="tt-input"
            :placeholder="fmt(t) + ' – ' + fmt(t + STEP)"
            maxlength="120"
            @keyup.enter="commit"
            @keyup.esc="cancel"
            @blur="commit"
          />
          <div
            v-else
            class="tt-fill"
            :title="cellText(t)"
            @click="startEdit(t)"
          >{{ cellText(t) }}</div>
        </div>
        <!-- 当前时刻红线（仅今天） -->
        <div v-if="isToday" class="tt-now" :style="{ top: paperPad + nowMin * (ROW / STEP) + 'px' }">
          <i></i>
        </div>
      </div>
    </div>
    <div class="tt-foot">点格子写字 · 回车保存 · 清空即删除</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Clock } from '@element-plus/icons-vue'
import { http } from '../api/client'

/**
 * 24h 每日时间表：固定 20 分钟一格（72 格），一张连续的白纸，点格子自己填。
 * 存储只认格子起始分钟；渲染 [t, t+20) 内落点的所有条目——早年用 30 分钟
 * 行距写入的非 20 整倍数条目（如 7:30）也会归入所在格显示，不丢字。
 */
const props = withDefaults(defineProps<{ tasks?: { id: number; title: string }[] }>(), { tasks: () => [] })
const emit = defineEmits<{ (e: 'date-change', date: string): void }>()
const taskId = ref<number>()
const taskTime = ref('')
async function placeTask() {
  const task = props.tasks.find(t => t.id === taskId.value)
  if (!task || !taskTime.value) return ElMessage.warning('请选择任务和时间')
  const [h, m] = taskTime.value.split(':').map(Number)
  const t = Math.floor((h * 60 + m) / STEP) * STEP
  if (cellText(t)) return ElMessage.warning('该时间格已有内容，请先手动调整，避免覆盖')
  try { await http.put('/timetable/slot', { date: date.value, slot_min: t, text: task.title, span: STEP }); await load(); ElMessage.success('已填入时间表') }
  catch { ElMessage.error('保存失败') }
}
const STEP = 20
const ROW = 30            // 一格行高（px），与样式中 --row 一致
const PAD = 10            // 纸面内边距（px），用于红线定位
const paperPad = PAD
const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const fmt = (m: number) => `${pad(Math.floor(m / 60) % 24)}:${pad(m % 60)}`
const todayStr = iso(new Date())

const date = ref(todayStr)
const dateLabel = computed(() => {
  const [y, m, d] = date.value.split('-').map(Number)
  const zh = ['日', '一', '二', '三', '四', '五', '六']
  const wd = zh[new Date(y, m - 1, d).getDay()]
  return `${y} 年 ${m} 月 ${d} 日 · 周${wd}`
})
const isToday = computed(() => date.value === todayStr)
const slots = Array.from({ length: 1440 / STEP }, (_, i) => i * STEP)

/* ---------- 数据 ---------- */
const entries = ref<Record<number, string>>({})

async function load() {
  try {
    const r = await http.get<{ items: { slot_min: number; text: string }[] }>(
      `/timetable/day?date=${date.value}`)
    const m: Record<number, string> = {}
    for (const it of r.items) m[it.slot_min] = it.text
    entries.value = m
  } catch (e: any) {
    const st = e?.response?.status
    if (st !== 401 && st !== 423) ElMessage.error(e?.response?.data?.detail || '时间表加载失败')
  }
}
watch(date, load)
load()

/** 该格显示的文字：起始分钟落在 [t, t+20) 的条目 */
function cellText(t: number): string {
  return Object.entries(entries.value)
    .filter(([k]) => Number(k) >= t && Number(k) < t + STEP)
    .map(([, v]) => v)
    .join(' · ')
}
const filledCnt = computed(() => Object.values(entries.value).filter(Boolean).length)

/* ---------- 行内编辑 ---------- */
const editing = ref<number | null>(null)
const editText = ref('')
const editInput = ref<HTMLInputElement | HTMLInputElement[] | null>(null)
let cancelled = false

async function startEdit(t: number) {
  if (editing.value === t) return
  cancelled = false
  editing.value = t
  editText.value = cellText(t)
  await nextTick()
  const el = Array.isArray(editInput.value) ? editInput.value[0] : editInput.value
  el?.focus()
}

function cancel() {
  cancelled = true
  editing.value = null
}

async function commit() {
  if (editing.value === null) return
  const t = editing.value
  if (cancelled) { cancelled = false; editing.value = null; return }
  const text = editText.value.trim()
  if (text === cellText(t)) { editing.value = null; return }
  // 乐观更新：清掉本格 [t, t+20) 的旧条目，写新起点
  const m: Record<number, string> = {}
  for (const [k, v] of Object.entries(entries.value)) {
    const kNum = Number(k)
    if (kNum >= t && kNum < t + STEP) continue
    m[kNum] = v
  }
  if (text) m[t] = text
  entries.value = m
  editing.value = null
  try {
    await http.put('/timetable/slot', { date: date.value, slot_min: t, text, span: STEP })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
    await load()
  }
}

async function clearDay() {
  try {
    await ElMessageBox.confirm(`清空 ${dateLabel.value} 的全部格子？`, '确认清空', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/timetable/day?date=${date.value}`)
    entries.value = {}
    ElMessage.success('已清空')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '清空失败')
  }
}

/* ---------- 导航与当前时刻 ---------- */
function move(dir: number) {
  const [y, m, d] = date.value.split('-').map(Number)
  date.value = iso(new Date(y, m - 1, d + dir))
  emit('date-change', date.value)
}
function goToday() { setDate(todayStr); emit('date-change', todayStr) }
function setDate(d: string) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) date.value = d
}
defineExpose({ setDate })

const nowMin = ref(new Date().getHours() * 60 + new Date().getMinutes())
let timer: number | undefined
const bodyEl = ref<HTMLElement | null>(null)

function scrollToNow() {
  if (!bodyEl.value) return
  const top = PAD + (isToday.value ? nowMin.value : 8 * 60) * (ROW / STEP)
  bodyEl.value.scrollTop = Math.max(0, top - bodyEl.value.clientHeight / 3)
}
onMounted(() => {
  timer = window.setInterval(() => {
    const n = new Date()
    nowMin.value = n.getHours() * 60 + n.getMinutes()
  }, 60_000)
  void nextTick(scrollToNow)
})
watch(date, () => void nextTick(scrollToNow))
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.tt { padding: 18px 20px 12px; }
.tt-task-add { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:12px 0; font-size:12px; color:var(--txt2); }

/* ---- 头 ---- */
.tt-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.tt-title { display: flex; align-items: center; gap: 10px; }
.tt-icon { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 8px;
  background: var(--acc-grad); color: #fff; }
.tt-name { font-size: 16px; font-weight: 800; }
.tt-count { font-size: 11.5px; color: var(--txt2); background: rgba(167, 139, 250, 0.12);
  border: 1px solid rgba(167, 139, 250, 0.22); border-radius: 999px; padding: 1px 9px; }
.tt-nav { display: flex; align-items: center; gap: 4px; }
.tt-arrow { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%;
  border: none; background: transparent; color: var(--txt2); cursor: pointer; transition: background .15s, color .15s; }
.tt-arrow:hover { background: rgba(167, 139, 250, 0.16); color: var(--acc2); }
.tt-date { font-size: 14px; font-weight: 700; min-width: 168px; text-align: center; letter-spacing: .5px; }
.tt-date.today { background: var(--acc-grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.tt-mini { font-size: 12px; padding: 3px 11px; border-radius: 999px; cursor: pointer;
  border: 1px solid rgba(167, 139, 250, 0.35); background: transparent; color: var(--txt2); transition: all .15s; }
.tt-mini:hover:not(:disabled) { border-color: var(--acc2); color: var(--acc2); background: rgba(167, 139, 250, 0.08); }
.tt-mini.danger { border-color: rgba(244, 114, 182, 0.4); }
.tt-mini.danger:hover:not(:disabled) { border-color: var(--acc1); color: var(--acc1); background: rgba(236, 72, 153, 0.07); }
.tt-mini:disabled { opacity: .45; cursor: default; }

/* ---- 主体：一张连续的白纸，行线即格子 ---- */
.tt-body { max-height: 640px; overflow: auto; margin-top: 14px; padding: 2px 6px 2px 2px; }
.tt-paper {
  position: relative;
  background: #fff;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow: 0 8px 28px rgba(30, 41, 59, 0.12), inset 0 0 0 0 transparent;
  padding: 10px 14px 10px 0;
  overflow: hidden;
}

.tt-row {
  display: grid;
  grid-template-columns: 64px 1fr;
  align-items: center;
  height: var(--row);
  border-top: 1px dashed rgba(148, 163, 184, 0.3);
}
.tt-row.first { border-top: none; }
.tt-row.hour { border-top: 1.5px solid rgba(100, 116, 139, 0.45); }

.tt-hr { font-size: 12px; font-weight: 700; color: #475569; font-variant-numeric: tabular-nums;
  text-align: right; padding-right: 14px; letter-spacing: .5px; user-select: none; }
.tt-hr-min { font-size: 10px; font-weight: 500; color: #b3bdc9; }

.tt-fill { min-height: 100%; display: flex; align-items: center; padding: 0 10px; border-radius: 8px;
  font-size: 12.5px; line-height: 1.5; color: #1e293b; cursor: text; word-break: break-all;
  transition: background .12s; overflow: hidden; }
.tt-fill:hover { background: rgba(139, 92, 246, 0.07); }
.tt-fill:not(:empty) { font-weight: 600; }
/* 空格子悬停时给一点「可写」暗示 */
.tt-fill:empty::after { content: ''; }
.tt-fill:empty:hover::after { content: '＋ 填写'; color: #b6c0cf; font-size: 11.5px; }

.tt-input { width: 100%; height: calc(var(--row) - 8px); border-radius: 8px; padding: 0 10px; margin: 0 2px;
  font-size: 12.5px; color: #1e293b; background: #f5f3ff; outline: none;
  border: 1.5px solid #a78bfa; box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.14); }

/* 当前时刻红线 */
.tt-now { position: absolute; left: 0; right: 0; z-index: 3; pointer-events: none; }
.tt-now::after { content: ''; position: absolute; left: 78px; right: 0; top: -0.75px; height: 1.5px;
  background: linear-gradient(90deg, #f43f5e, rgba(244, 63, 94, 0.15)); }
.tt-now i { position: absolute; left: 72px; top: -3.5px; width: 8px; height: 8px; border-radius: 50%;
  background: #f43f5e; box-shadow: 0 0 8px rgba(244, 63, 94, 0.65); }

.tt-foot { text-align: right; font-size: 11px; color: var(--txt2); opacity: .75; padding: 8px 4px 0; }

@media (max-width: 1100px) {
  .tt-body { max-height: 520px; }
  .tt-date { min-width: 0; }
}
</style>
