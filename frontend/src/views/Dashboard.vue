<template>
  <div class="page dashboard">
    <section class="hero glass" aria-labelledby="welcome-title">
      <div class="hero-main">
        <div class="section-kicker"><span class="kicker-dot"></span> YOUR PERSONAL SPACE <span class="kicker-line"></span> {{ todayText }}</div>
        <h1 id="welcome-title">你好，{{ name }}<span class="hero-dot">.</span></h1>
        <p>留一点时间给思考，也留一点空间给生活。</p>
        <div class="hero-actions">
          <router-link class="primary-link" to="/schedule">查看今日日程 <span aria-hidden="true">↗</span></router-link>
          <router-link class="secondary-link" to="/notes">打开笔记 <span aria-hidden="true">→</span></router-link>
        </div>
      </div>
      <div class="hero-aside" aria-hidden="true"><span>KRUSKAL</span><strong>Make room<br>for your ideas.</strong><span>WORK · STUDY · LIFE</span></div>
    </section>

    <section class="overview glass" aria-label="今日数据概览">
      <div class="overview-title"><div><span class="section-index">01 / OVERVIEW</span><h2>今天的节奏</h2></div><span class="overview-date">{{ todayText }}</span></div>
      <div class="stats-grid">
        <div class="stat"><div class="stat-top"><span>今日待办</span><span class="stat-symbol">↗</span></div><div class="stat-number">{{ pendingCount }}<small>项</small></div><div class="stat-hint">等待完成的事项</div></div>
        <div class="stat"><div class="stat-top"><span>今日专注</span><span class="stat-symbol">◷</span></div><div class="stat-number">{{ focusToday }}<small>分钟</small></div><div class="stat-hint">计时自动统计</div></div>
        <div class="stat"><div class="stat-top"><span>笔记与博客</span><span class="stat-symbol">✳</span></div><div class="stat-number">{{ stats.notes }}<small>篇</small></div><div class="stat-hint">记录与整理</div></div>
        <div class="stat"><div class="stat-top"><span>论文收藏</span><span class="stat-symbol">↗</span></div><div class="stat-number">{{ stats.papers }}<small>篇</small></div><div class="stat-hint">阅读与批注</div></div>
      </div>
    </section>

    <section class="quick-section">
      <div class="section-heading"><div><span class="section-index">02 / SHORTCUTS</span><h2>从这里开始</h2></div><span class="section-hint">选择一个入口，继续今天的事情</span></div>
      <div class="quick-grid">
        <router-link v-for="(q, index) in quicks" :key="q.title" :to="q.path" class="quick glass">
          <span class="quick-icon"><el-icon :size="20"><component :is="q.icon" /></el-icon></span>
          <span class="quick-copy"><small>0{{ index + 1 }}</small><strong>{{ q.title }}</strong></span><span class="quick-arrow" aria-hidden="true">↗</span>
        </router-link>
      </div>
    </section>

    <div class="workspace-heading section-heading"><div><span class="section-index">03 / DAILY NOTES</span><h2>给今天一点秩序</h2></div><span class="section-hint">想法与行动，都从这里开始</span></div>
    <section class="glass plan-card" aria-label="今日安排">
      <div class="card-head"><div><span class="card-overline">NOTES TO SELF</span><h3 class="card-title">今日安排</h3></div><span class="save-state" :class="planState.cls">{{ planState.text }}</span></div>
      <p class="card-description">写下想做的事，内容会自动保存。</p>
      <el-input ref="planRef" v-model="planText" type="textarea" :autosize="{ minRows: 5, maxRows: 18 }" placeholder="从一个想法开始……支持 Markdown" aria-label="今日安排" @input="onPlanInput" @blur="savePlan(false)" />
      <div class="plan-foot"><span class="plan-hint">{{ planSavedAt ? '上次保存 ' + planSavedAt : '随时记录，慢慢整理' }}</span><div><el-button v-if="planState.cls === 'err'" text size="small" @click="savePlan(true)">重试</el-button><el-button text size="small" @click="insertTemplate">插入清单模板 ↗</el-button></div></div>
    </section>

    <section class="glass todo-card" aria-label="今日待办">
      <div class="card-head"><div><span class="card-overline">TODAY'S TASKS</span><h3 class="card-title">今日待办</h3></div><router-link to="/schedule" class="more-link">打开日历 ↗</router-link></div>
      <p class="card-description" v-if="todayItems.length">已完成 {{ todayDone }} 项，仍有 {{ pendingCount }} 项待处理。</p>
      <p class="card-description" v-else>有计划，也给自己留一些余地。</p>
      <div v-if="pendingList.length" class="todo-list"><div v-for="it in pendingList" :key="it.id" class="todo-row" :class="'ty-' + it.type"><el-checkbox :model-value="it.done" @change="(v: boolean) => toggle(it, v)" /><span v-if="it.time_start" class="tt">{{ it.time_start }}</span><span class="ttitle">{{ it.title }}</span><span v-if="it.type === 'ddl'" class="tbadge">DDL</span><span v-if="it.note" class="tnote">{{ it.note }}</span></div></div>
      <div v-else class="todo-empty"><span class="empty-mark">✓</span><div><strong>今天暂时没有待办</strong><p>去日历安排接下来的事。</p></div><router-link to="/schedule">查看日历 ↗</router-link></div>
    </section>

    <div class="focus-heading section-heading"><div><span class="section-index">04 / FOCUS</span><h2>把时间留给重要的事</h2></div><span class="section-hint">每一次专注，都会留下记录</span></div>
    <FocusTimer class="focus-panel" @changed="onFocusChanged" />
    <section class="glass chart-card"><div class="card-head"><div><span class="card-overline">LAST 14 DAYS</span><h3 class="card-title">专注时长</h3></div><span class="card-tip">单位：分钟</span></div><FocusChart :data="focusDaily" /></section>
    <section class="glass heat-card"><div class="card-head"><div><span class="card-overline">YOUR YEAR IN FOCUS</span><h3 class="card-title">年度热力图</h3></div><el-radio-group v-model="hmMode" size="small"><el-radio-button value="focus">专注时长</el-radio-button><el-radio-button value="task">任务完成率</el-radio-button></el-radio-group></div><Heatmap v-if="hmMode === 'focus'" :data="focusYearMap" :demo="false" mode="minutes" :title="hmYear + ' 专注热力图'" tip="按每天专注分钟数着色" /><Heatmap v-else :data="taskPercent" :demo="false" mode="percent" title="年度打卡热力图" tip="按每日勾选完成率着色" /></section>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Notebook, Reading, Calendar, Memo } from '@element-plus/icons-vue'
import Heatmap from '../components/Heatmap.vue'
import FocusTimer from '../components/FocusTimer.vue'
import FocusChart from '../components/FocusChart.vue'
import { http } from '../api/client'
import { dayNoteApi } from '../api/workbench'
import type { Entry } from '../components/EntryItem.vue'

const name = ref(localStorage.getItem('krs_user') || '主人')
const todayText = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })
const stats = reactive({ notes: 0, papers: 0 })
const hmMode = ref<'focus' | 'task'>('focus')
const hmYear = new Date().getFullYear()
const focusToday = ref(0)
const focusDaily = ref<{ date: string; minutes: number }[]>([])
const focusYearMap = ref<Record<string, number>>({})
const taskPercent = ref<Record<string, number>>({})
const todayItems = ref<Entry[]>([])

const todayStr = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})()

const pendingList = computed(() => todayItems.value.filter((x) => x.type !== 'event' && !x.done))
const pendingCount = computed(() => pendingList.value.length)
const todayDone = computed(() => todayItems.value.filter((x) => x.type !== 'event' && x.done).length)

const quicks = computed(() => [
  { path: '/schedule', title: '日程日历', icon: Memo },
  { path: '/notes', title: '写博客', icon: Notebook },
  { path: '/papers', title: '读论文', icon: Reading },
  { path: '/schedule', title: '写日记', icon: Calendar },
])

/* ---------------- 今日安排：随手的 Markdown 小本子 ----------------
   固定一份（data/daynote/note.md，加密落盘），不按天归档、不自动清空。
   防抖 1.2s 自动保存 + 失焦立即保存 + 离开页面前兜底，失败绝不清空输入框。 */
const planText = ref('')
const planRef = ref<any>(null)
const planSavedAt = ref('')
const planState = ref<{ cls: 'ok' | 'err' | 'busy'; text: string }>({ cls: 'ok', text: '已保存' })
let planTimer: ReturnType<typeof setTimeout> | undefined
let planDirty = false
let planSaving = false

function fmtHHMM(d = new Date()) {
  return d.toTimeString().slice(0, 5)
}

function onPlanInput() {
  planDirty = true
  planState.value = { cls: 'busy', text: '保存中…' }
  clearTimeout(planTimer)
  planTimer = setTimeout(() => { savePlan(false) }, 1200)
}

async function savePlan(force = false): Promise<boolean> {
  clearTimeout(planTimer)
  if (!force && !planDirty) return true
  if (planSaving) return true
  planSaving = true
  planState.value = { cls: 'busy', text: '保存中…' }
  try {
    const r = await dayNoteApi.put(planText.value)
    planDirty = false
    planSavedAt.value = (r.updated || '').slice(11, 16) || fmtHHMM()
    planState.value = { cls: 'ok', text: '已保存' }
    return true
  } catch (e: any) {
    // 保存失败保留屏幕上的内容，等重试
    planState.value = { cls: 'err', text: `保存失败：${e?.response?.data?.detail || '请检查网络后重试'}` }
    return false
  } finally {
    planSaving = false
  }
}

/** 一键插入一份清单骨架，懒得手打时用 */
function insertTemplate() {
  const tpl = '- [ ] \n- [ ] \n- [ ] \n'
  if (!planText.value.trim()) {
    planText.value = tpl
  } else {
    planText.value = `${planText.value.replace(/\s*$/, '')}\n${tpl}`
  }
  onPlanInput()
}

function onPlanPageHide() {
  if (!planDirty) return
  try {
    const token = localStorage.getItem('krs_token') || ''
    fetch('/api/daynote', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ content: planText.value }),
      keepalive: true,
    }).catch(() => {})
  } catch { /* ignore */ }
}

async function toggle(it: Entry, done: boolean) {
  try {
    await http.put(`/schedule/${it.id}/done`, { done })
    await loadToday()
    await loadTaskHeat()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function loadToday() {
  try {
    const r = await http.get<{ items: Entry[] }>(`/schedule/day?date=${todayStr}`)
    todayItems.value = r.items
  } catch { /* ignore */ }
}

async function loadTaskHeat() {
  try {
    const r = await http.get<{ days: Record<string, { done: number; total: number }> }>(`/schedule/heatmap?year=${hmYear}`)
    const map: Record<string, number> = {}
    for (const [d, v] of Object.entries(r.days)) {
      map[d] = v.total ? Math.round((v.done / v.total) * 100) : 0
    }
    taskPercent.value = map
  } catch { /* ignore */ }
}

async function loadFocus() {
  try {
    const [stats7, hm] = await Promise.all([
      http.get<{ today: { minutes: number }; daily: { date: string; minutes: number }[] }>('/focus/stats?days=14'),
      http.get<{ days: Record<string, number> }>(`/focus/heatmap?year=${hmYear}`),
    ])
    focusToday.value = stats7.today.minutes
    focusDaily.value = stats7.daily
    focusYearMap.value = hm.days
  } catch { /* ignore */ }
}

function onFocusChanged() {
  loadFocus()
}

onMounted(async () => {
  loadFocus()
  loadToday()
  loadTaskHeat()
  loadPlan()
  window.addEventListener('pagehide', onPlanPageHide)
  try {
    const [n, p] = await Promise.all([
      http.get<{ items: unknown[] }>('/notes'),
      http.get<{ items: unknown[] }>('/papers'),
    ])
    stats.notes = n.items.length
    stats.papers = p.items.length
  } catch { /* 保持 0 */ }
})

/** 读「今日安排」本体；失败不打扰（可能只是还没解锁），用户照样能写，保存时会提示 */
async function loadPlan() {
  try {
    const r = await dayNoteApi.get()
    planText.value = r.content || ''
    planSavedAt.value = (r.updated || '').slice(11, 16)
    planDirty = false
    planState.value = { cls: 'ok', text: r.content ? '已保存' : '还没写' }
  } catch { /* ignore */ }
}

onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPlanPageHide)
  clearTimeout(planTimer)
  void savePlan(true)   // 离开首页前兜底落盘
})
</script>

<style scoped>
.dashboard { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; align-items:stretch; }
.dashboard > * { min-width:0; }
.hero,.overview,.quick-section,.workspace-heading,.focus-heading,.heat-card { grid-column:1 / -1; }
.hero { min-height:240px; display:flex; justify-content:space-between; align-items:end; padding:40px; overflow:hidden; }
.hero-main { max-width:680px; }
.section-kicker,.section-index,.card-overline { color:var(--acc2); font-size:12px; line-height:16px; font-weight:700; letter-spacing:.1em; }
.section-kicker { display:flex; align-items:center; flex-wrap:wrap; gap:12px; color:var(--txt2); }
.kicker-dot { width:8px; height:8px; border-radius:50%; background:#d99abd; }
.kicker-line { width:24px; height:1px; background:currentColor; opacity:.45; }
.hero h1 { margin:24px 0 8px; color:inherit; font-size:48px; line-height:1; font-weight:700; letter-spacing:-.03em; }
.hero-dot { color:#d696ba; }
.hero p { margin:0; color:var(--txt2); font-size:16px; line-height:24px; }
.hero-actions { display:flex; align-items:center; gap:24px; margin-top:24px; }
.primary-link { display:inline-flex; align-items:center; gap:24px; padding:12px 16px; border-radius:8px; background:#7959b7; color:#fff; font-size:14px; font-weight:700; }
.primary-link:hover { color:#fff; background:#6949a4; }
.secondary-link { color:inherit; font-size:14px; font-weight:600; }
.primary-link,.secondary-link,.quick { transition:transform .5s cubic-bezier(.22,1,.36,1), background-color .3s cubic-bezier(.22,1,.36,1); }
.primary-link:hover,.quick:hover { transform:translateY(-2px); }
.primary-link:active,.quick:active { transform:scale(.98); }
.hero-aside { align-self:stretch; display:flex; flex-direction:column; justify-content:space-between; align-items:flex-end; text-align:right; color:var(--txt2); font-size:12px; line-height:16px; letter-spacing:.12em; }
.hero-aside strong { color:inherit; font-size:24px; line-height:32px; font-weight:600; letter-spacing:-.02em; opacity:.8; }
.overview { padding:24px 32px; }
.overview-title,.section-heading { display:flex; justify-content:space-between; align-items:end; gap:16px; }
.overview h2,.section-heading h2 { margin:8px 0 0; font-size:20px; line-height:28px; font-weight:700; }
.overview-date,.section-hint { color:var(--txt2); font-size:12px; line-height:16px; }
.stats-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:24px; }
.stat { padding:16px; border-radius:8px; background:rgba(128,112,150,.07); }
.stat-top { display:flex; justify-content:space-between; gap:8px; color:var(--txt2); font-size:14px; line-height:20px; }
.stat-symbol { color:var(--acc2); }
.stat-number { margin-top:12px; font-size:30px; line-height:36px; font-weight:700; font-variant-numeric:tabular-nums; }
.stat-number small { margin-left:4px; color:var(--txt2); font-size:12px; font-weight:500; }
.stat-hint { margin-top:4px; color:var(--txt2); font-size:12px; line-height:16px; }
.quick-section { padding-top:16px; }
.quick-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin-top:16px; }
.quick { min-height:104px; display:flex; align-items:center; gap:16px; padding:16px; color:inherit; }
.quick:hover { color:inherit; }
.quick-icon { width:40px; height:40px; display:grid; place-items:center; flex:none; border-radius:8px; background:rgba(150,115,195,.15); color:var(--acc2); }
.quick-copy { display:grid; gap:4px; }
.quick-copy small { color:var(--txt2); font-size:12px; line-height:16px; }
.quick-copy strong { font-size:14px; line-height:20px; }
.quick-arrow { margin-left:auto; color:var(--txt2); font-size:18px; }
.workspace-heading,.focus-heading { padding-top:24px; }
.plan-card,.todo-card { grid-column:span 6; padding:24px; }
.card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.card-title { margin:8px 0 0; font-size:20px; line-height:28px; font-weight:700; }
.card-tip,.card-description,.save-state,.plan-hint { color:var(--txt2); font-size:12px; line-height:20px; }
.card-description { margin:8px 0 16px; }
.save-state { padding-top:4px; text-align:right; }
.save-state.ok { color:#86b8a0; }.save-state.err { color:#ef8f9b; }.save-state.busy { color:var(--acc2); }
.plan-card :deep(.el-textarea__inner) { min-height:136px !important; padding:16px; border-radius:8px; font-size:14px; line-height:24px; }
.plan-foot { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; margin-top:12px; }
.more-link { color:var(--acc2); font-size:12px; line-height:20px; white-space:nowrap; }
.todo-list { display:grid; gap:8px; }
.todo-row { display:flex; align-items:center; gap:8px; padding:8px 12px; border-radius:8px; background:rgba(128,112,150,.07); font-size:14px; }
.tt { color:var(--acc2); font-size:12px; }.ttitle { font-weight:600; }.tbadge { padding:2px 4px; border-radius:4px; background:#a9536d; color:#fff; font-size:12px; }.tnote { margin-left:auto; color:var(--txt2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.todo-empty { min-height:136px; display:flex; align-items:center; gap:16px; padding:24px; border:1px dashed rgba(150,140,160,.35); border-radius:8px; }
.empty-mark { width:40px; height:40px; flex:none; display:grid; place-items:center; border-radius:50%; background:rgba(160,130,200,.14); color:var(--acc2); }
.todo-empty strong { font-size:14px; }.todo-empty p { margin:4px 0 0; color:var(--txt2); font-size:12px; }.todo-empty a { margin-left:auto; font-size:12px; white-space:nowrap; }
.focus-panel,.chart-card { grid-column:span 6; }.chart-card,.heat-card { padding:24px; }.chart-card .card-tip { padding-top:4px; }.heat-card .card-head { margin-bottom:24px; align-items:center; }
@media(max-width:1100px) { .focus-panel,.chart-card { grid-column:1 / -1; } }
@media(max-width:820px) { .hero { padding:24px; min-height:220px; }.hero h1 { font-size:36px; line-height:40px; }.hero-aside { display:none; }.overview { padding:24px; }.stats-grid,.quick-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.plan-card,.todo-card { grid-column:1 / -1; }.section-hint,.overview-date { display:none; } }
@media(max-width:480px) { .hero h1 { font-size:30px; line-height:36px; }.hero-actions { gap:16px; }.stats-grid,.quick-grid { gap:8px; }.quick { min-height:88px; padding:12px; gap:8px; }.quick-icon { width:32px; height:32px; }.quick-arrow { display:none; }.overview,.plan-card,.todo-card,.chart-card,.heat-card { padding:16px; }.todo-empty { padding:16px; }.todo-empty a { display:none; }.heat-card .card-head { flex-wrap:wrap; } }
</style>
