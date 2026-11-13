<template>
  <div class="page pomo">
    <!-- 计时器：一段专注 + 一段休息，时长可自己定 -->
    <section class="pomo-hero glass" :class="phase">
      <div class="ring-wrap">
        <svg class="ring" viewBox="0 0 240 240" aria-hidden="true">
          <circle class="track" cx="120" cy="120" r="104" />
          <circle
            class="prog" :class="phase" cx="120" cy="120" r="104"
            :stroke-dasharray="CIRC" :stroke-dashoffset="dashOffset"
          />
        </svg>
        <div class="ring-center">
          <div class="p-phase">
            <el-icon :size="14"><component :is="phase === 'focus' ? AlarmClock : CoffeeCup" /></el-icon>
            <span>{{ phaseText }}</span>
          </div>
          <div class="p-time">{{ clock }}</div>
          <div class="p-status">{{ statusText }}</div>
        </div>
      </div>

      <div class="p-side">
        <h2 class="p-title">番茄钟</h2>
        <p class="p-sub">给自己一段不被打扰的时间。</p>

        <!-- 番茄的名字：记进这条专注记录，饼图按名字算占比 -->
        <div v-show="status !== 'running'" class="mode-select" aria-label="计时模式">
          <el-radio-group v-model="mode" :disabled="status !== 'idle' || phase === 'break' || busy" size="small">
            <el-radio-button value="countdown">倒计时</el-radio-button>
            <el-radio-button value="stopwatch">正计时</el-radio-button>
          </el-radio-group>
          <span class="set-hint">{{ mode === 'stopwatch' ? '自由专注，结束时记录实际时长' : '按设定时长专注和休息' }}</span>
        </div>
        <div v-show="status !== 'running'" class="p-name">
          <el-input v-model="taskName" maxlength="30" clearable class="name-input" placeholder="准备专注什么？（可选）" />
          <el-select v-model="selectedTask" clearable filterable placeholder="关联日程任务（可选）" :disabled="status !== 'idle'" @change="selectTask" style="max-width: 420px">
            <el-option v-for="t in scheduleTasks" :key="t.id" :label="t.title" :value="t.id" />
          </el-select>
          <div v-if="nameChips.length" class="name-chips">
            <span class="set-lab">最近</span>
            <button
              v-for="n in nameChips" :key="n" type="button" class="preset"
              :class="{ on: taskName === n }" @click="taskName = n"
            >{{ n }}</button>
          </div>
        </div>

        <div v-if="awaitingChoice" class="p-btns">
          <el-button type="primary" :loading="busy" @click="completeChoice('break')">开始休息</el-button>
          <el-button :loading="busy" @click="extendFocus">再专注 5 分钟</el-button>
          <el-button :loading="busy" @click="completeChoice('end')">结束并记录</el-button>
        </div>
        <div v-else class="p-btns">
          <el-button v-if="status === 'idle'" type="primary" size="large" round @click="start">
            <el-icon style="margin-right:6px"><VideoPlay /></el-icon>{{ phase === 'focus' ? '开始专注' : '开始休息' }}
          </el-button>
          <el-button v-else-if="status === 'running'" type="primary" size="large" round @click="pause">
            <el-icon style="margin-right:6px"><VideoPause /></el-icon>暂停
          </el-button>
          <el-button v-else type="primary" size="large" round @click="start">
            <el-icon style="margin-right:6px"><VideoPlay /></el-icon>继续
          </el-button>

          <el-button v-if="status !== 'idle' && phase === 'focus'" size="large" round :loading="busy" @click="finish">
            <el-icon style="margin-right:6px"><Check /></el-icon>结束并记录
          </el-button>
          <el-button v-if="status !== 'idle' && phase === 'focus'" class="abandon-btn" text :loading="busy" @click="abandon">放弃本次</el-button>
          <el-button v-if="phase === 'break'" size="large" round @click="skipBreak">跳过休息</el-button>
        </div>

        <div v-if="mode === 'countdown'" v-show="status !== 'running'" class="quick-presets">
          <div class="set-row presets">
            <span class="set-lab">常用</span>
            <button
              v-for="p in presets" :key="`${p.f}-${p.b}`" type="button" class="preset"
              :class="{ on: cfg.focusMin === p.f && cfg.breakMin === p.b }" @click="applyPreset(p)"
            >{{ p.f }} / {{ p.b }}</button>
            <span class="set-hint">{{ status === 'running' ? '修改从下一段生效' : '空格键开始或暂停' }}</span>
          </div>
        </div>
        <details v-if="mode === 'countdown'" v-show="status !== 'running'" class="settings">
          <summary>计时设置</summary>
          <div class="p-set">
          <div class="set-row">
            <span class="set-lab">专注</span>
            <el-input-number v-model="cfg.focusMin" :min="1" :max="180" :step="5" size="small" controls-position="right" class="set-num" />
            <span class="set-unit">分钟</span>
            <span class="set-lab">休息</span>
            <el-input-number v-model="cfg.breakMin" :min="0" :max="120" :step="5" size="small" controls-position="right" class="set-num" />
            <span class="set-unit">分钟</span>
          </div>
          <div class="set-row">
            <span class="set-lab">休息后自动开始专注</span><el-switch v-model="cfg.autoNext" size="small" />
            <span class="set-lab">提前 1 分钟提醒</span><el-switch v-model="cfg.warning" size="small" />
            <span class="set-lab">提示音</span><el-switch v-model="cfg.sound" size="small" />
            <span class="set-lab">桌面通知</span><el-switch v-model="cfg.notify" size="small" @change="onNotifyToggle" />
          </div>
          </div>
        </details>
      </div>
    </section>

    <section class="today-summary glass" aria-label="今日专注概览">
      <div class="today-copy">
        <span class="today-label">今日专注</span>
        <strong>{{ stats.todayMin }} <small>分钟</small></strong>
        <span class="today-tomatoes">完成 {{ tomatoesToday }} 个番茄</span>
      </div>
      <div v-if="cfg.goalMin" class="goal-progress">
        <span>每日目标 {{ stats.todayMin }} / {{ cfg.goalMin }} 分钟</span>
        <el-progress :percentage="Math.min(100, Math.round(stats.todayMin / cfg.goalMin * 100))" :show-text="false" />
      </div>
      <details class="goal-settings">
        <summary>设置每日目标</summary>
        <div><el-input-number v-model="cfg.goalMin" :min="0" :max="1440" :step="15" size="small" /> <span>分钟（0 为关闭）</span></div>
      </details>
    </section>

    <!-- 专注时长 + 最近记录 -->
    <section class="glass rec-card">
      <div class="card-head">
        <div><h3 class="card-title">最近记录</h3><span class="card-tip">{{ recent.length }} 条</span></div>
        <el-button @click="openManual"><el-icon style="margin-right:6px"><EditPen /></el-icon>补记</el-button>
      </div>
      <div class="rec-filters">
        <el-input v-model="recordQuery" clearable placeholder="按名字筛选" />
        <el-date-picker v-model="recordRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" style="max-width: 280px" />
      </div>
      <div v-if="recent.length" class="rec-list">
        <div v-for="r in recent" :key="r.id" class="rec-row">
          <span class="rec-min">{{ r.minutes }} 分</span>
          <el-input
            v-if="editing === r.id" v-model="editName" class="rec-edit" size="small" maxlength="30"
            placeholder="这段专注的名字，留空即「专注」" @keyup.enter="saveRename(r)" @keyup.esc="editing = 0"
          />
          <span v-else class="rec-main">
            <strong :class="{ dim: !recName(r) }">{{ recName(r) || '专注' }}</strong>
            <small>{{ recTime(r) }} · {{ sourceLabel(r.source) }}</small>
          </span>
          <button
            type="button" class="rec-del rec-ren" :title="editing === r.id ? '保存名字' : '修改名字'"
            :aria-label="editing === r.id ? '保存名字' : '修改名字'" @click="openEdit(r)"
          >
            <el-icon :size="14"><Check v-if="editing === r.id" /><EditPen v-else /></el-icon>
          </button>
          <button type="button" class="rec-del" title="删除这条记录" aria-label="删除这条记录" @click="remove(r)">
            <el-icon :size="14"><Delete /></el-icon>
          </button>
        </div>
      </div>
      <div v-else class="rec-empty">还没有专注记录，开始一段专注或补记已有时间。</div>
    </section>

    <section class="statistics-section">
      <button type="button" class="statistics-toggle" :aria-expanded="statsExpanded" @click="statsExpanded = !statsExpanded">
        <span><strong>专注统计</strong><small>趋势、分布与年度热力图</small></span>
        <span aria-hidden="true">{{ statsExpanded ? '收起 −' : '展开 +' }}</span>
      </button>
      <div v-if="statsExpanded" class="statistics-content">
        <div class="secondary-stats glass"><span>近 7 天 <strong>{{ stats.weekMin }}</strong> 分钟</span><span>连续打卡 <strong>{{ streak }}</strong> 天</span></div>
    <section class="glass chart-card">
      <div class="card-head">
        <div><h3 class="card-title">近 14 天专注时长</h3></div>
        <span class="card-tip">单位：分钟</span>
      </div>
      <FocusChart :data="daily" />
    </section>


    <!-- 专注分布：按番茄的名字算占比 -->
    <section class="glass pie-card">
      <div class="card-head">
        <div><h3 class="card-title">专注分布</h3>
          <p class="pie-sum">近 {{ pieDays }} 天 · 共 {{ pieTotal }} 分钟 · {{ pieData.length }} 个名字</p>
        </div>
        <el-radio-group v-model="pieDays" size="small">
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
          <el-radio-button :value="90">近 90 天</el-radio-button>
          <el-radio-button :value="365">近一年</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="pieData.length" class="pie-grid">
        <FocusPie :data="pieData" />
        <ul class="pie-list">
          <li v-for="(it, i) in pieData" :key="it.name" class="pie-row">
            <span class="pl-dot" :style="{ background: pieColor(i) }" />
            <span class="pl-name" :title="it.name">{{ it.name }}</span>
            <span class="pl-bar"><i :style="{ width: share(it.minutes) + '%', background: pieColor(i) }" /></span>
            <span class="pl-num">{{ it.minutes }} 分</span>
            <span class="pl-pct">{{ share(it.minutes) }}%</span>
          </li>
        </ul>
      </div>
      <div v-else class="pie-hint">
        这段时间还没有专注记录。给番茄起个名字（上面计时卡里的输入框），饼图就会按名字告诉你时间都花在了哪儿。
      </div>
    </section>

    <!-- 热力图 -->
    <section class="glass heat-card">
      <div class="card-head">
        <div><h3 class="card-title">年度热力图</h3></div>
        <el-radio-group v-model="hmMode" size="small">
          <el-radio-button value="focus">专注时长</el-radio-button>
          <el-radio-button value="task">任务完成率</el-radio-button>
        </el-radio-group>
      </div>
      <Heatmap v-if="hmMode === 'focus'" :data="yearMap" :demo="false" mode="minutes" :title="hmYear + ' 专注热力图'" tip="按每天专注分钟数着色" />
      <Heatmap v-else :data="taskPercent" :demo="false" mode="percent" title="年度打卡热力图" tip="按每日勾选完成率着色" />
    </section>

      </div>
    </section>

    <el-dialog v-model="editDialog" title="编辑专注记录" width="420px">
      <el-form label-position="top">
        <el-form-item label="日期"><el-date-picker v-model="editRecord.date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="分钟数"><el-input-number v-model="editRecord.minutes" :min="1" :max="1440" /></el-form-item>
        <el-form-item label="名字"><el-input v-model="editRecord.note" maxlength="30" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editDialog = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveEdit">保存</el-button></template>
    </el-dialog>
    <!-- 补记：忘了开计时时用 -->
    <el-dialog v-model="dialog" title="补记专注时长（忘了开计时时用）" width="420px">
      <el-form label-position="top">
        <el-form-item label="日期">
          <el-date-picker v-model="manual.date" type="date" value-format="YYYY-MM-DD"
            :disabled-date="(d: Date) => d.getTime() > Date.now()" style="width: 100%" />
        </el-form-item>
        <el-form-item label="专注分钟数">
          <el-input-number v-model="manual.minutes" :min="1" :max="1440" style="width: 100%" />
        </el-form-item>
        <el-form-item label="名字（可空）">
          <el-input v-model="manual.note" maxlength="30" placeholder="例如「论文精读」，会进饼图" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submitManual">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { clientState } from '../api/clientState'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { AlarmClock, Check, CoffeeCup, Delete, EditPen, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import FocusChart from '../components/FocusChart.vue'
import FocusPie from '../components/FocusPie.vue'
import Heatmap from '../components/Heatmap.vue'
import { http } from '../api/client'
import { site } from '../stores/site'
import { pieColor } from '../utils/chartColors'

type Phase = 'focus' | 'break'
type Status = 'idle' | 'running' | 'paused'
type TimerMode = 'countdown' | 'stopwatch'

interface Rec { id: number; start: string; end: string | null; minutes: number; note: string; source: string; schedule_id: number | null }
interface Slice { name: string; minutes: number; sessions: number }

const CFG_KEY = 'krs_pomo_cfg'
const STATE_KEY = 'krs_pomo_state'
const LOG_KEY = 'krs_pomo_log'
const NAME_KEY = 'krs_pomo_name'
const NAMES_KEY = 'krs_pomo_names'
const CIRC = 2 * Math.PI * 104

const presets = [{ f: 25, b: 5 }, { f: 50, b: 10 }, { f: 15, b: 3 }, { f: 45, b: 15 }]

/* ---------------- 配置（记住上次的设置） ---------------- */
const cfg = reactive({ focusMin: 25, breakMin: 5, autoNext: true, sound: true, notify: false, warning: false, goalMin: 0 })
loadCfg()

function loadCfg() {
  try {
    const raw = JSON.parse(clientState.getItem(CFG_KEY) || 'null')
    if (raw && typeof raw === 'object') {
      cfg.focusMin = clamp(Math.round(Number(raw.focusMin) || 25), 1, 180)
      cfg.breakMin = clamp(Math.round(Number(raw.breakMin ?? 5)), 0, 120)
      cfg.autoNext = raw.autoNext !== false
      cfg.sound = raw.sound !== false
      cfg.notify = raw.notify === true
      cfg.warning = raw.warning === true
      cfg.goalMin = clamp(Number(raw.goalMin) || 0, 0, 1440)
    }
  } catch { /* 用默认值 */ }
}

function saveCfg() {
  try { clientState.setItem(CFG_KEY, JSON.stringify({ ...cfg })) } catch { /* ignore */ }
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v))
}

/** 本地日期（不能用 toISOString：UTC 会让凌晨的番茄记到前一天） */
function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function applyPreset(p: { f: number; b: number }) {
  cfg.focusMin = p.f
  cfg.breakMin = p.b
}

async function onNotifyToggle(v: boolean | string | number) {
  if (!v) return
  if (!('Notification' in window)) {
    cfg.notify = false
    ElMessage.warning('当前浏览器不支持桌面通知')
    return
  }
  if (Notification.permission !== 'granted') {
    const p = await Notification.requestPermission()
    if (p !== 'granted') {
      cfg.notify = false
      ElMessage.warning('没有拿到通知权限')
    }
  }
}

/* ---------------- 番茄的名字（存进记录的 note，饼图按它聚合） ---------------- */
const taskName = ref('')
const nameChips = ref<string[]>([])
const taskRoute = useRoute()
const useTaskId = taskRoute.query.task
const selectedTask = ref<number | undefined>()
const pendingTask = ref<number | null>(null)
const scheduleTasks = ref<{ id: number; title: string; type: string; done: boolean }[]>([])
async function loadTasks() {
  try { const taskDate = typeof taskRoute.query.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(taskRoute.query.date) ? taskRoute.query.date : todayStr.value; const result = await http.get<{ items: typeof scheduleTasks.value }>(`/schedule/day?date=${taskDate}`); scheduleTasks.value = result.items.filter(t => t.type !== 'event') } catch { scheduleTasks.value = [] }
}
function selectTask(id: number | undefined) { const task = scheduleTasks.value.find(t => t.id === id); if (task) taskName.value = task.title.slice(0, 30) }
const pendingName = ref('') // 本段专注开始时的名字：中途改名不影响正在跑的这一段

function loadNames() {
  try {
    taskName.value = String(clientState.getItem(NAME_KEY) || '')
    const raw = JSON.parse(clientState.getItem(NAMES_KEY) || '[]')
    nameChips.value = Array.isArray(raw) ? raw.filter((n: unknown) => typeof n === 'string' && n).slice(0, 8) : []
  } catch { nameChips.value = [] }
}

function saveName() {
  try { clientState.setItem(NAME_KEY, taskName.value) } catch { /* ignore */ }
}

function rememberName(n: string) {
  const v = n.trim()
  if (!v) return
  nameChips.value = [v, ...nameChips.value.filter((x) => x !== v)].slice(0, 8)
  try { clientState.setItem(NAMES_KEY, JSON.stringify(nameChips.value)) } catch { /* ignore */ }
}

/* ---------------- 计时状态机 ---------------- */
const statsExpanded = ref(false)
const mode = ref<TimerMode>('countdown')
const phase = ref<Phase>('focus')
const status = ref<Status>('idle')
const totalSec = ref(cfg.focusMin * 60)
const remainSec = ref(cfg.focusMin * 60)
const busy = ref(false)
const elapsedSec = ref(0)
let elapsedBase = 0
let runningSince = 0
let endsAt = 0 // 运行中的结束时间戳（ms）
let ending = false // 一段刚跑完、正在落记录
let ticker: ReturnType<typeof setInterval> | undefined
let leaving = false
const awaitingChoice = ref(false)
let warned = false
let originalSec = cfg.focusMin * 60

const phaseText = computed(() => (phase.value === 'focus' ? '专注' : '休息'))
const statusText = computed(() => {
  const nm = phase.value === 'focus' && pendingName.value ? ` · ${pendingName.value}` : ''
  if (status.value === 'running') return phase.value === 'focus' ? `专注中${nm}` : '休息中…'
  if (status.value === 'paused') return (mode.value === 'countdown' && remainSec.value <= 0 ? '时间已到' : '已暂停') + nm
  return phase.value === 'focus' ? '准备开始' : '休息一下'
})
const clock = computed(() => {
  const s = Math.max(0, (mode.value === 'stopwatch' && phase.value === 'focus' ? Math.floor(elapsedSec.value) : Math.ceil(remainSec.value)))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})
const progress = computed(() => (mode.value === 'stopwatch' && phase.value === 'focus' ? 0 : totalSec.value > 0 ? clamp((totalSec.value - remainSec.value) / totalSec.value, 0, 1) : 0))
const dashOffset = computed(() => CIRC * (1 - progress.value))

function secFor(p: Phase) {
  return Math.max(0, Math.round((p === 'focus' ? cfg.focusMin : cfg.breakMin) * 60))
}

/** 切到某一段：autoStart = 直接跑起来 */
function setPhase(p: Phase, autoStart = false) {
  phase.value = p
  awaitingChoice.value = false
  warned = false
  if (p === 'focus') pendingTask.value = selectedTask.value ?? null
  if (p === 'focus') pendingName.value = taskName.value.trim() // 这一段专注用开始时的名字
  totalSec.value = secFor(p)
  remainSec.value = totalSec.value
  originalSec = totalSec.value
  elapsedSec.value = 0
  elapsedBase = 0
  runningSince = 0
  if (autoStart && (totalSec.value > 0 || (mode.value === 'stopwatch' && p === 'focus'))) {
    status.value = 'running'
    if (mode.value === 'stopwatch' && p === 'focus') runningSince = Date.now()
    else endsAt = Date.now() + totalSec.value * 1000
  } else {
    status.value = 'idle'
    endsAt = 0
  }
  saveState()
  syncTitle()
}

function start() {
  ensureAudio()
  if (ending || status.value === 'running') return // 空格键/回车重复触发时不重置倒计时
  if (status.value === 'paused') {
    if (mode.value === 'countdown' && remainSec.value <= 0) { // 离开期间走完了：交给用户决定记还是弃，不能点一下就白得一个番茄
      ElMessage.info('这一段时间已经走完，用「结束并记录」记账，或放弃本次')
      return
    }
    status.value = 'running'
    if (mode.value === 'stopwatch' && phase.value === 'focus') {
      elapsedBase = elapsedSec.value
      runningSince = Date.now()
    } else endsAt = Date.now() + Math.max(1, remainSec.value) * 1000
    saveState()
    syncTitle()
    return
  }
  if (secFor(phase.value) <= 0) { // 休息设成 0 分钟时不打转，直接回专注
    setPhase('focus')
    ElMessage.info('休息时长是 0 分钟，直接回到专注')
    return
  }
  setPhase(phase.value, true)
  ElMessage.success(phase.value === 'focus' ? (mode.value === 'stopwatch' ? '正计时已开始' : `专注 ${cfg.focusMin} 分钟，加油`) : `休息 ${cfg.breakMin} 分钟`)
}

function pause() {
  if (status.value !== 'running') return
  if (mode.value === 'stopwatch' && phase.value === 'focus') {
    elapsedSec.value = elapsedBase + (Date.now() - runningSince) / 1000
    elapsedBase = elapsedSec.value
    runningSince = 0
  } else remainSec.value = Math.max(0, (endsAt - Date.now()) / 1000)
  status.value = 'paused'
  endsAt = 0
  saveState()
  syncTitle()
}

async function finish() {
  if (busy.value || ending) return
  if (status.value === 'running') pause()
  if (phase.value === 'break') {
    setPhase('focus')
    ElMessage.info('休息结束，回到专注')
    return
  }
  const mins = Math.floor((mode.value === 'stopwatch' ? elapsedSec.value : totalSec.value - remainSec.value) / 60)
  if (mins < 1) {
    setPhase('focus')
    ElMessage.warning('不足 1 分钟，本次不记录')
    return
  }
  busy.value = true
  // 走完整个番茄才计数；提前结束只记实际分钟数
  const saved = await recordFocus(mins, pendingName.value, mode.value, pendingTask.value)
  busy.value = false
  if (!saved) return
  if (mode.value === 'countdown' && totalSec.value - remainSec.value >= originalSec) bumpTomato()
  ElMessage.success(`已记录专注 ${mins} 分钟`)
  setPhase('focus')
}

async function abandon() {
  try {
    await ElMessageBox.confirm('放弃本次专注？不会写入专注记录。', '放弃本次', {
      confirmButtonText: '放弃', cancelButtonText: '继续专注', type: 'warning',
    })
  } catch { return }
  setPhase('focus')
  ElMessage.info('已放弃本次专注')
}

function skipBreak() {
  if (ending) return
  setPhase('focus')
  ElMessage.info('跳过休息，直接进入下一个番茄')
}

/** 一段跑完：先停表再落记录，避免 await 期间 tick 再触发一次（否则重复记番茄） */
async function onPhaseEnd() {
  if (ending) return
  ending = true
  if (phase.value === 'focus') {
    status.value = 'paused'
    endsAt = 0
    remainSec.value = 0
    awaitingChoice.value = true
    beep('focus')
    notify('专注时间已到', '选择休息、继续 5 分钟或结束并记录')
    saveState()
    syncTitle()
  } else {
    beep('break')
    notify('休息结束', '回到桌前，开始下一段专注')
    setPhase('focus', cfg.autoNext)
  }
  ending = false
}

function extendFocus() {
  awaitingChoice.value = false
  totalSec.value += 300
  remainSec.value = 300
  endsAt = Date.now() + 300000
  status.value = 'running'
  warned = false
  saveState()
}

async function completeChoice(choice: 'break' | 'end') {
  if (busy.value) return
  busy.value = true
  const saved = await recordFocus(Math.floor(totalSec.value / 60), pendingName.value, 'countdown', pendingTask.value)
  busy.value = false
  if (!saved) return
  bumpTomato()
  ElMessage.success('已记录本次专注')
  if (choice === 'break' && cfg.breakMin > 0) setPhase('break', true)
  else setPhase('focus')
}

function tick() {
  const d = isoDay(new Date())
  if (d !== todayStr.value) todayStr.value = d // 跨零点：番茄记到今天名下
  if (status.value !== 'running') return
  if (mode.value === 'stopwatch' && phase.value === 'focus') {
    if (runningSince) elapsedSec.value = elapsedBase + (Date.now() - runningSince) / 1000
    syncTitle()
    return
  }
  if (!endsAt) return
  remainSec.value = Math.max(0, (endsAt - Date.now()) / 1000)
  syncTitle()
  if (phase.value === 'focus' && cfg.warning && !warned && remainSec.value > 0 && remainSec.value <= 60) {
    warned = true; beep('break'); notify('专注即将结束', '还剩 1 分钟'); ElMessage.info('专注还剩 1 分钟'); saveState()
  }
  if (remainSec.value <= 0) void onPhaseEnd()
}

watch(mode, () => { if (status.value === 'idle') setPhase('focus') })

/* 空闲时改时长，当前待命的倒计时跟着变；计时中改的下一段生效 */
watch([() => cfg.focusMin, () => cfg.breakMin], () => {
  saveCfg()
  if (status.value === 'idle') {
    totalSec.value = secFor(phase.value)
    remainSec.value = totalSec.value
    saveState()
    syncTitle()
  }
})
watch(() => cfg.autoNext, saveCfg)
watch(() => cfg.sound, saveCfg)
watch(() => cfg.notify, saveCfg)
watch(() => cfg.warning, saveCfg)
watch(() => cfg.goalMin, saveCfg)
watch(taskName, saveName)

/* ---------------- 刷新/恢复：关页面、切页面都不丢番茄 ---------------- */
function saveState() {
  try {
    clientState.setItem(STATE_KEY, JSON.stringify({
      mode: mode.value, phase: phase.value, status: status.value, totalSec: totalSec.value, awaitingChoice: awaitingChoice.value, warned, originalSec, task: pendingTask.value,
      elapsedSec: status.value === 'running' ? elapsedBase : elapsedSec.value, runningSince,
      remainSec: Math.ceil(remainSec.value), endsAt, name: pendingName.value,
    }))
  } catch { /* ignore */ }
}

function restoreState() {
  let s: { mode?: TimerMode; phase?: Phase; status?: Status; totalSec?: number; remainSec?: number; endsAt?: number; name?: string; elapsedSec?: number; runningSince?: number; awaitingChoice?: boolean; warned?: boolean; originalSec?: number; task?: number | null } | null = null
  try { s = JSON.parse(clientState.getItem(STATE_KEY) || 'null') } catch { s = null }
  if (!s || (s.phase !== 'focus' && s.phase !== 'break')) { setPhase('focus'); return }

  mode.value = s.mode === 'stopwatch' ? 'stopwatch' : 'countdown'
  pendingTask.value = s.task ?? null
  warned = s.warned === true
  originalSec = Number(s.originalSec) || Number(s.totalSec) || secFor('focus')
  awaitingChoice.value = s.awaitingChoice === true
  if (mode.value === 'stopwatch' && s.phase === 'focus' && (s.status === 'running' || s.status === 'paused')) {
    phase.value = 'focus'
    pendingName.value = typeof s.name === 'string' ? s.name : taskName.value.trim()
    elapsedBase = Math.max(0, Number(s.elapsedSec) || 0)
    runningSince = s.status === 'running' ? Number(s.runningSince) || Date.now() : 0
    elapsedSec.value = elapsedBase + (runningSince ? Math.max(0, Date.now() - runningSince) / 1000 : 0)
    status.value = s.status
    syncTitle()
    return
  }

  // 进行中的那一段沿用它开始时的名字；下面的 setPhase 分支会按输入框重新取
  pendingName.value = typeof s.name === 'string' ? s.name : taskName.value.trim()
  const p = s.phase
  const total = Math.max(0, Math.round(Number(s.totalSec) || secFor(p)))
  if (s.status === 'running' && s.endsAt) {
    const rem = Math.floor((Number(s.endsAt) - Date.now()) / 1000)
    if (rem > 0) { // 还在跑：接着倒数
      phase.value = p
      totalSec.value = total
      remainSec.value = rem
      status.value = 'running'
      endsAt = Number(s.endsAt)
      syncTitle()
      return
    }
    if (p === 'focus') { // 专注时间已到但人不在这页：交给用户决定记不记
      phase.value = p
      totalSec.value = total
      remainSec.value = 0
      status.value = 'paused'
      endsAt = 0
      awaitingChoice.value = true
      ElMessage.info('专注时间已到，请选择下一步')
      saveState()
      syncTitle()
      return
    }
    setPhase('focus') // 休息在离开时结束了，直接回到专注待命
    return
  }
  if (s.status === 'paused') {
    phase.value = p
    totalSec.value = total
    remainSec.value = clamp(Math.round(Number(s.remainSec) || 0), 0, total)
    status.value = 'paused'
    endsAt = 0
    syncTitle()
    return
  }
  setPhase(p)
}

/* ---------------- 今日番茄（本机记数，分钟数走服务端） ---------------- */
const pomolog = ref<Record<string, number>>({})
const todayStr = ref(isoDay(new Date()))
const tomatoesToday = computed(() => pomolog.value[todayStr.value] || 0)

function loadLog() {
  try {
    const raw = JSON.parse(clientState.getItem(LOG_KEY) || 'null')
    if (raw && typeof raw === 'object') pomolog.value = raw
  } catch { pomolog.value = {} }
}

function bumpTomato() {
  const d = todayStr.value
  pomolog.value = { ...pomolog.value, [d]: (pomolog.value[d] || 0) + 1 }
  try { clientState.setItem(LOG_KEY, JSON.stringify(pomolog.value)) } catch { /* ignore */ }
}

/* ---------------- 服务端数据：专注时长 / 热力图 / 最近记录 ---------------- */
const hmYear = new Date().getFullYear()
const hmMode = ref<'focus' | 'task'>('focus')
const stats = reactive({ todayMin: 0, weekMin: 0 })
const daily = ref<{ date: string; minutes: number }[]>([])
const recent = ref<Rec[]>([])
const recordQuery = ref('')
const recordRange = ref<string[] | null>(null)
let recordRequest = 0
async function loadRecords() {
  const request = ++recordRequest
  const params = new URLSearchParams({ q: recordQuery.value, from_date: recordRange.value?.[0] || '', to_date: recordRange.value?.[1] || '' })
  try { const res = await http.get<{ items: Rec[] }>(`/focus/records?${params}`); if (request === recordRequest) recent.value = res.items } catch { /* API interceptor reports errors */ }
}
watch([recordQuery, recordRange], loadRecords)
function sourceLabel(source: string) { return ({ countdown: '倒计时', stopwatch: '正计时', manual: '补记', unknown: '历史记录' } as Record<string,string>)[source] || '历史记录' }
const yearMap = ref<Record<string, number>>({})
const taskPercent = ref<Record<string, number>>({})

const streak = computed(() => {
  const map = yearMap.value
  const d = new Date()
  if (!(map[isoDay(d)] > 0)) d.setDate(d.getDate() - 1) // 今天还没专注不算断
  let n = 0
  while (map[isoDay(d)] > 0) { n++; d.setDate(d.getDate() - 1) }
  return n
})

/** 补录/番茄在库里是「整天」一行，展示时只给日期 */
function recTime(r: Rec) {
  if (!r.start) return ''
  return r.start.endsWith('00:00:00') ? r.start.slice(0, 10) : `${r.start.slice(0, 10)} ${r.start.slice(11, 16)}`
}

/** 早期自动写入的「番茄钟 N 分钟」不是名字（分钟数左边那列已经有了），显示成「专注」 */
const LEGACY_NOTE = /^番茄钟\s*\d+\s*分钟/
function recName(r: Rec) {
  const n = (r.note || '').trim()
  return LEGACY_NOTE.test(n) ? '' : n
}

/* ---------------- 专注分布（饼图按名字算占比） ---------------- */
const pieDays = ref(30)
const pieData = ref<Slice[]>([])
const pieTotal = computed(() => pieData.value.reduce((a, d) => a + d.minutes, 0))

function share(m: number) {
  return pieTotal.value > 0 ? Math.max(1, Math.round((m / pieTotal.value) * 100)) : 0
}

async function loadPie() {
  try {
    const res = await http.get<{ items: Slice[] }>(`/focus/breakdown?days=${pieDays.value}`)
    const items = (res.items || []).filter((i) => i.minutes > 0)
    // 饼图切太碎就没法看了：留前 9 名，其余并进「其他」
    const top = items.slice(0, 9)
    const rest = items.slice(9)
    if (rest.length) {
      top.push({
        name: `其他（${rest.length} 项）`,
        minutes: rest.reduce((a, i) => a + i.minutes, 0),
        sessions: rest.reduce((a, i) => a + i.sessions, 0),
      })
    }
    pieData.value = top
  } catch { /* 401/423 由拦截器处理 */ }
}

watch(pieDays, loadPie)

async function loadAll() {
  try {
    const [st, hm, tk] = await Promise.all([
      http.get<{
        today: { minutes: number }
        daily: { date: string; minutes: number }[]
        recent: Rec[]
      }>('/focus/stats?days=14'),
      http.get<{ days: Record<string, number> }>(`/focus/heatmap?year=${hmYear}`),
      http.get<{ days: Record<string, { done: number; total: number }> }>(`/schedule/heatmap?year=${hmYear}`),
    ])
    stats.todayMin = st.today.minutes
    stats.weekMin = st.daily.slice(-7).reduce((a, d) => a + d.minutes, 0)
    daily.value = st.daily
    void loadRecords()
    yearMap.value = hm.days
    const map: Record<string, number> = {}
    for (const [d, v] of Object.entries(tk.days)) map[d] = v.total ? Math.round((v.done / v.total) * 100) : 0
    taskPercent.value = map
  } catch { /* 401/423 由拦截器处理 */ }
  void loadPie()
}

/** 番茄完成 → 记一行当天的专注分钟数，名字（可空）写进 note */
async function recordFocus(minutes: number, name: string, source: TimerMode, scheduleId: number | null) {
  try {
    await http.post('/focus/manual', { date: isoDay(new Date()), minutes, note: name, source, schedule_id: scheduleId })
    rememberName(name)
    await loadAll()
    return true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '专注记录保存失败，请重试')
    return false
  }
}

/* ---------------- 编辑记录 ---------------- */
const editDialog = ref(false)
const editRecord = reactive({ id: 0, date: '', minutes: 1, note: '' })
function openEdit(r: Rec) {
  editRecord.id = r.id; editRecord.date = r.start.slice(0, 10); editRecord.minutes = r.minutes; editRecord.note = recName(r)
  editDialog.value = true
}
async function saveEdit() {
  if (!editRecord.date) { ElMessage.warning('请选择日期'); return }
  busy.value = true
  try {
    await http.patch(`/focus/${editRecord.id}`, { date: editRecord.date, minutes: editRecord.minutes, note: editRecord.note.trim() })
    editDialog.value = false; await loadAll(); ElMessage.success('记录已更新')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { busy.value = false }
}

/* ---------------- 改名字 ---------------- */
const editing = ref(0)
const editName = ref('')

async function startRename(r: Rec) {
  editing.value = r.id
  editName.value = recName(r)
  await nextTick()
  const input = document.querySelector<HTMLInputElement>('.rec-edit input')
  input?.focus()
  input?.select()
}

async function saveRename(r: Rec) {
  if (editing.value !== r.id) return
  const name = editName.value.trim()
  editing.value = 0
  if (name === recName(r)) return
  try {
    await http.patch<Rec>(`/focus/${r.id}`, { note: name })
    rememberName(name)
    await loadAll()
    ElMessage.success(name ? `已改名为「${name}」` : '已清空名字')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '改名失败')
  }
}

async function remove(r: Rec) {
  try {
    await ElMessageBox.confirm(`删除这条记录（${r.minutes} 分钟 · ${recName(r) || '专注'}）？`, '删除记录', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  editing.value = 0
  try {
    await http.del(`/focus/${r.id}`)
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

/* ---------------- 补记 ---------------- */
const dialog = ref(false)
const manual = reactive({ date: todayStr.value, minutes: 30, note: '' })

function openManual() {
  manual.date = todayStr.value
  manual.minutes = cfg.focusMin
  manual.note = ''
  dialog.value = true
}

async function submitManual() {
  if (!manual.date) { ElMessage.warning('选一个日期'); return }
  busy.value = true
  try {
    await http.post('/focus/manual', { date: manual.date, minutes: manual.minutes, note: manual.note })
    ElMessage.success('已补记')
    dialog.value = false
    rememberName(manual.note)
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '补记失败')
  } finally { busy.value = false }
}

/* ---------------- 提示音 / 通知 / 标题 ---------------- */
let ac: AudioContext | null = null

function ensureAudio() {
  try {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return
    if (!ac) ac = new Ctor()
    if (ac.state === 'suspended') void ac.resume()
  } catch { /* 没有音频也照样计时 */ }
}

function beep(kind: 'focus' | 'break') {
  if (!cfg.sound) return
  try {
    ensureAudio()
    if (!ac) return
    const notes = kind === 'focus' ? [659, 880, 1046] : [880, 659, 523]
    notes.forEach((f, i) => {
      const t0 = ac!.currentTime + i * 0.22
      const osc = ac!.createOscillator()
      const gain = ac!.createGain()
      osc.type = 'sine'
      osc.frequency.value = f
      gain.gain.setValueAtTime(0.0001, t0)
      gain.gain.exponentialRampToValueAtTime(0.2, t0 + 0.03)
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.2)
      osc.connect(gain).connect(ac!.destination)
      osc.start(t0)
      osc.stop(t0 + 0.22)
    })
  } catch { /* ignore */ }
}

function notify(title: string, body: string) {
  if (!cfg.notify) return
  try {
    if ('Notification' in window && Notification.permission === 'granted') new Notification(title, { body })
  } catch { /* ignore */ }
}

function syncTitle() {
  if (leaving) return
  document.title = status.value === 'running' ? `${clock.value} · ${phaseText.value}中 · ${site.name}` : `番茄钟 · ${site.name}`
}

function onKeydown(e: KeyboardEvent) {
  if (dialog.value || editDialog.value || awaitingChoice.value) return
  const t = e.target as HTMLElement | null
  // 输入框里、以及本来就能被空格触发的按钮/链接上，不抢空格
  if (t && (/^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(t.tagName) || t.isContentEditable || t.closest('.el-popper'))) return
  if (e.code === 'Space') {
    e.preventDefault()
    if (status.value === 'running') pause()
    else start()
  }
}

onMounted(() => {
  loadLog()
  loadNames()
  restoreState()
  loadAll()
  void loadTasks().then(() => {
    const id = Number(useTaskId)
    if (status.value === 'idle' && scheduleTasks.value.some(t => t.id === id)) { selectedTask.value = id; selectTask(id) }
  })
  ticker = setInterval(tick, 200)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('pagehide', saveState)
})

onBeforeUnmount(() => {
  leaving = true
  clearInterval(ticker)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pagehide', saveState)
  saveState()
  // 标题交给路由的 afterEach：这里再写一次会把新页面的标题盖掉
})
</script>

<style scoped>
.pomo { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; align-items: stretch; }
.pomo > * { min-width: 0; }
.pomo-hero, .today-summary, .statistics-section { grid-column: 1 / -1; }

/* ---- 计时卡 ---- */
.pomo-hero { display: flex; align-items: center; gap: clamp(32px, 5vw, 72px); padding: 36px clamp(24px, 5vw, 56px); }
.ring-wrap { position: relative; width: 260px; height: 260px; flex: none; }
.ring { width: 100%; height: 100%; transform: rotate(-90deg); }
.track { fill: none; stroke: rgba(150, 130, 190, 0.2); stroke-width: 12; }
.prog { fill: none; stroke-width: 12; stroke-linecap: round; transition: stroke-dashoffset .25s linear, stroke .3s ease; }
.prog.focus { stroke: var(--acc2); }
.prog.break { stroke: #3fbd9d; }
html.theme-dark .prog.break { stroke: #5eead4; }
.ring-center { position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; text-align: center; }
.p-phase { display: flex; align-items: center; gap: 6px; color: var(--txt2); font-size: 12px; line-height: 16px; letter-spacing: .08em; }
.p-time { margin: 4px 0; font-size: 46px; line-height: 1; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -.02em; }
.p-status { color: var(--txt2); font-size: 12px; line-height: 16px; max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.p-side { flex: 1; min-width: 260px; }
.section-index { color: var(--acc2); font-size: 12px; line-height: 16px; font-weight: 700; letter-spacing: .1em; }
.p-title { margin: 0; font-size: 24px; line-height: 32px; font-weight: 700; }
.p-sub { margin: 4px 0 18px; color: var(--txt2); font-size: 12px; line-height: 20px; max-width: 520px; }
.p-btns { display: flex; flex-wrap: wrap; gap: 8px; }
.p-btns :deep(.el-button + .el-button) { margin-left: 0; }
.mode-select { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.mode-select .set-hint { margin-left: 0; }
.quick-presets { margin-top: 18px; }
.settings { margin-top: 14px; color: var(--txt2); font-size: 13px; }
.settings summary { cursor: pointer; width: fit-content; padding: 4px 0; }
.settings summary:hover { color: var(--acc2); }
.p-btns :deep(.abandon-btn) { color: var(--txt2); }
.p-name { margin-bottom: 18px; display: grid; gap: 10px; max-width: 560px; }
.name-input { max-width: 420px; }
.name-chips { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.p-set { margin-top: 8px; padding-top: 12px; border-top: 1px solid rgba(128, 128, 128, 0.16); display: grid; gap: 12px; }
.set-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.set-lab { color: var(--txt2); font-size: 12px; line-height: 16px; }
.set-unit { color: var(--txt2); font-size: 12px; line-height: 16px; margin-right: 8px; }
.set-num { width: 92px; }
.presets { gap: 6px; }
.preset { padding: 4px 10px; border: 1px solid rgba(128, 112, 150, 0.28); border-radius: 999px; background: transparent; color: inherit; cursor: pointer; font-size: 12px; line-height: 16px; transition: background-color .3s cubic-bezier(.22, 1, .36, 1), color .3s cubic-bezier(.22, 1, .36, 1); }
.preset:hover { background: rgba(119, 87, 181, 0.1); }
.preset.on { background: rgba(119, 87, 181, 0.16); color: var(--acc2); border-color: transparent; font-weight: 700; }
html.theme-dark .preset.on { color: #e0d3fa; background: rgba(226, 207, 255, 0.16); }
.set-hint { margin-left: auto; color: var(--txt2); font-size: 12px; line-height: 16px; }

/* ---- 统计 ---- */
.today-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 16px 30px; padding: 18px 24px; }
.today-copy { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; }
.today-label { color: var(--txt2); font-size: 13px; }
.today-copy strong { color: var(--acc2); font-size: 25px; font-variant-numeric: tabular-nums; }
.today-copy strong small { font-size: 12px; font-weight: 500; }
.today-tomatoes, .goal-progress, .goal-settings { color: var(--txt2); font-size: 12px; }
.goal-progress { flex: 1; min-width: 150px; display: grid; gap: 7px; }
.goal-settings { margin-left: auto; }
.goal-settings summary { cursor: pointer; }
.goal-settings > div { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.statistics-section { min-width: 0; }
.statistics-toggle { display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 12px; padding: 18px 24px; border: 1px solid rgba(128, 112, 150, .15); border-radius: 12px; background: var(--card, #fff); color: inherit; cursor: pointer; text-align: left; }
.statistics-toggle > span:first-child { display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px; }
.statistics-toggle strong { font-size: 18px; }
.statistics-toggle small, .statistics-toggle > span:last-child { color: var(--txt2); font-size: 12px; }
.statistics-content { display: grid; gap: 16px; margin-top: 16px; }
.secondary-stats { display: flex; flex-wrap: wrap; gap: 12px 28px; padding: 16px 24px; color: var(--txt2); font-size: 13px; }
.secondary-stats strong { color: var(--acc2); font-size: 18px; }
.rec-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.rec-filters > :first-child { max-width: 180px; }
.stats-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.stat { padding: 16px; }
.stat .num { font-size: 30px; line-height: 36px; font-weight: 700; color: var(--acc2); font-variant-numeric: tabular-nums; }
.stat .num small { margin-left: 4px; color: var(--txt2); font-size: 12px; font-weight: 500; }
.stat .lab { margin-top: 4px; color: var(--txt2); font-size: 12px; line-height: 16px; }

/* ---- 卡片通用 ---- */
.chart-card, .rec-card, .heat-card { padding: 24px; }
.chart-card { grid-column: span 7; }
.rec-card { grid-column: 1 / -1; }
.pie-card { grid-column: 1 / -1; padding: 24px; }
.pie-card .card-head { align-items: center; }
.pie-sum { margin: 6px 0 0; color: var(--txt2); font-size: 12px; line-height: 16px; }
.pie-grid { display: grid; grid-template-columns: minmax(260px, 380px) minmax(0, 1fr); gap: 28px; align-items: center; margin-top: 8px; }
.pie-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; max-height: 268px; overflow-y: auto; }
.pie-row { display: flex; align-items: center; gap: 10px; font-size: 12px; line-height: 16px; }
.pl-dot { flex: none; width: 9px; height: 9px; border-radius: 50%; }
.pl-name { flex: 0 0 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-bar { flex: 1; min-width: 40px; height: 6px; border-radius: 999px; background: rgba(128, 112, 150, 0.14); overflow: hidden; }
.pl-bar i { display: block; height: 100%; border-radius: 999px; transition: width .3s cubic-bezier(.22, 1, .36, 1); }
.pl-num { flex: none; width: 56px; text-align: right; color: var(--acc2); font-weight: 700; font-variant-numeric: tabular-nums; }
.pl-pct { flex: none; width: 38px; text-align: right; color: var(--txt2); font-variant-numeric: tabular-nums; }
.pie-hint { margin-top: 16px; min-height: 96px; display: grid; place-content: center; text-align: center; padding: 24px; border: 1px dashed rgba(150, 140, 160, 0.35); border-radius: 8px; color: var(--txt2); font-size: 12px; line-height: 20px; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.card-overline { color: var(--acc2); font-size: 12px; line-height: 16px; font-weight: 700; letter-spacing: .1em; }
.card-title { margin: 0; font-size: 20px; line-height: 28px; font-weight: 700; }
.card-tip { padding-top: 4px; color: var(--txt2); font-size: 12px; line-height: 20px; }
.heat-card .card-head { margin-bottom: 24px; align-items: center; }

/* ---- 最近记录 ---- */
.rec-list { display: grid; gap: 8px; margin-top: 16px; max-height: 300px; overflow-y: auto; }
.rec-row { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 8px; background: rgba(128, 112, 150, 0.07); }
.rec-min { flex: none; width: 52px; color: var(--acc2); font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.rec-main { display: grid; gap: 2px; min-width: 0; flex: 1; }
.rec-main strong { font-size: 14px; line-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rec-main small { color: var(--txt2); font-size: 12px; line-height: 16px; }
.rec-main strong.dim { color: var(--txt2); font-weight: 500; }
.rec-edit { flex: 1; min-width: 0; }
.rec-ren:hover { background: rgba(119, 87, 181, 0.14); color: var(--acc2); }
.rec-del { flex: none; width: 28px; height: 28px; display: grid; place-items: center; border: none; border-radius: 8px; background: transparent; color: var(--txt2); cursor: pointer; transition: background-color .3s cubic-bezier(.22, 1, .36, 1), color .3s cubic-bezier(.22, 1, .36, 1); }
.rec-del:hover { background: rgba(239, 143, 155, 0.16); color: #ef8f9b; }
.rec-empty { margin-top: 16px; min-height: 136px; display: grid; place-content: center; text-align: center; padding: 24px; border: 1px dashed rgba(150, 140, 160, 0.35); border-radius: 8px; color: var(--txt2); font-size: 12px; line-height: 20px; }

@media (max-width: 1100px) { .chart-card, .rec-card { grid-column: 1 / -1; } }
@media (max-width: 820px) {
  .pomo-hero { flex-direction: column; align-items: stretch; gap: 20px; padding: 20px; }
  .ring-wrap { width: 200px; height: 200px; margin: 0 auto; }
  .p-time { font-size: 40px; }
  .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .set-hint { display: none; }
  .name-input { max-width: none; }
  .pie-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .pl-name { flex-basis: 96px; }
}
@media (max-width: 480px) {
  .chart-card, .rec-card, .heat-card, .pie-card { padding: 16px; }
  .today-summary { padding: 16px; }
  .goal-settings { margin-left: 0; width: 100%; }
  .statistics-toggle { padding: 16px; }
  .rec-filters > :first-child { max-width: none; }
  .p-btns :deep(.el-button:not(.abandon-btn)) { flex: 1; }
  .p-side { min-width: 0; }
  .mode-select { align-items: flex-start; flex-direction: column; }
  .mode-select .set-hint { display: block; }
  .heat-card .card-head { flex-wrap: wrap; }
  .pie-card .card-head { flex-wrap: wrap; }
}
</style>
