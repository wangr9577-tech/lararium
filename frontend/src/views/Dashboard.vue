<template>
  <div class="page">
    <div class="hello glass">
      <div>
        <div class="hi">こんにちは，{{ name }} さん</div>
        <div class="sub">{{ todayText }} · 今天也要元气满满呀</div>
      </div>
      <div class="hello-right">
        <span v-for="t in ['日程打卡', '写笔记', '读论文', '记日记']" :key="t" class="chip">{{ t }}</span>
      </div>
    </div>

    <div class="grid">
      <div class="stat glass">
        <div class="stat-num grad-text">{{ pendingCount }}</div>
        <div class="stat-lab">今日待办</div>
        <div class="stat-hint">未完成 task/ddl</div>
      </div>
      <div class="stat glass">
        <div class="stat-num grad-text">{{ focusToday }}<small class="sm">分</small></div>
        <div class="stat-lab">今日专注</div>
        <div class="stat-hint">计时自动统计</div>
      </div>
      <div class="stat glass">
        <div class="stat-num grad-text">{{ stats.notes }}</div>
        <div class="stat-lab">笔记 · 博客</div>
        <div class="stat-hint">正文加密存储</div>
      </div>
      <div class="stat glass">
        <div class="stat-num grad-text">{{ stats.papers }}</div>
        <div class="stat-lab">论文在读</div>
        <div class="stat-hint">F4 荧光笔阅读器</div>
      </div>
    </div>

    <!-- 今日待办 -->
    <div class="glass todo-card">
      <div class="card-head">
        <span class="card-title">今日待办</span>
        <span class="card-tip" v-if="todayItems.length">已完成 {{ todayDone }}/{{ todayItems.length }}</span>
        <router-link to="/schedule" class="more-link">去日历 ›</router-link>
      </div>
      <div v-if="pendingList.length" class="todo-list">
        <div v-for="it in pendingList" :key="it.id" class="todo-row" :class="`ty-${it.type}`">
          <el-checkbox :model-value="it.done" @change="(v: boolean) => toggle(it, v)" />
          <span v-if="it.time_start" class="tt">{{ it.time_start }}</span>
          <span class="ttitle">{{ it.title }}</span>
          <span v-if="it.type === 'ddl'" class="tbadge">DDL</span>
          <span class="tnote" v-if="it.note">{{ it.note }}</span>
        </div>
      </div>
      <div v-else class="todo-empty">
        今日没有待办 —— <router-link to="/schedule">去日历安排</router-link>      </div>
    </div>

    <FocusTimer @changed="onFocusChanged" />

    <div class="glass chart-card">
      <div class="card-head">
        <span class="card-title">近 14 天专注时长</span>
        <span class="card-tip">完成一段专注或补记后自动更新</span>
      </div>
      <FocusChart :data="focusDaily" />
    </div>

    <div class="glass heat-card">
      <div class="card-head">
        <span class="card-title">年度热力图</span>
        <el-radio-group v-model="hmMode" size="small">
          <el-radio-button value="focus">专注时长</el-radio-button>
          <el-radio-button value="task">任务完成率</el-radio-button>
        </el-radio-group>
      </div>
      <Heatmap
        v-if="hmMode === 'focus'"
        :data="focusYearMap" :demo="false" mode="minutes"
        :title="`${hmYear} 专注热力图`" tip="按每天专注分钟数着色"
      />
      <Heatmap
        v-else :data="taskPercent" :demo="false" mode="percent"
        title="年度打卡热力图" tip="按每日勾选完成率着色"
      />
    </div>

    <div class="glass quick-card">
      <div class="qc-title">快捷入口</div>
      <div class="quick-grid">
        <router-link v-for="q in quicks" :key="q.path" :to="q.path" class="quick">
          <el-icon :size="20" color="#fff"><component :is="q.icon" /></el-icon>
          <span>{{ q.title }}</span>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Notebook, Reading, Calendar, Memo } from '@element-plus/icons-vue'
import Heatmap from '../components/Heatmap.vue'
import FocusTimer from '../components/FocusTimer.vue'
import FocusChart from '../components/FocusChart.vue'
import { http } from '../api/client'
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
  { path: '/diary', title: '写日记', icon: Calendar },
])

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
  try {
    const [n, p] = await Promise.all([
      http.get<{ items: unknown[] }>('/notes'),
      http.get<{ items: unknown[] }>('/papers'),
    ])
    stats.notes = n.items.length
    stats.papers = p.items.length
  } catch { /* 保持 0 */ }
})
</script>

<style scoped>
.sm { font-size: 13px; margin-left: 2px; }
.hello { display: flex; align-items: center; justify-content: space-between; padding: 20px 26px; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.hi { font-size: 20px; font-weight: 800; }
.sub { color: var(--txt2); font-size: 13px; margin-top: 4px; }
.hello-right { display: flex; gap: 8px; flex-wrap: wrap; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; margin-bottom: 16px; }
.stat { padding: 18px 20px; }
.stat-num { font-size: 30px; font-weight: 900; }
.stat-lab { font-size: 14px; font-weight: 600; margin-top: 2px; }
.stat-hint { font-size: 12px; color: var(--txt2); margin-top: 6px; }

.todo-card, .chart-card, .heat-card, .quick-card { padding: 18px 22px; margin-bottom: 16px; }
.card-head { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.card-title { font-size: 15px; font-weight: 700; }
.card-tip { font-size: 12px; color: var(--txt2); }
.more-link { margin-left: auto; font-size: 13px; color: var(--acc2); }
.todo-list { display: grid; }
.todo-row {
  display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 10px; font-size: 14px;
  border-left: 3px solid var(--c);
}
.ty-task { --c: #a78bfa; }
.ty-ddl { --c: #f43f5e; }
.ty-event { --c: #0ea5e9; }
.todo-row:nth-child(odd) { background: rgba(148, 163, 184, 0.06); }
.tt { color: var(--c); font-size: 12px; font-weight: 700; }
.ttitle { font-weight: 500; }
.tbadge { font-size: 10px; background: #f43f5e; color: #fff; border-radius: 5px; padding: 0 6px; }
.tnote { color: var(--txt2); font-size: 12px; margin-left: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
.todo-empty { color: var(--txt2); font-size: 13.5px; padding: 10px 2px; }
.todo-empty a { color: var(--acc2); }

.chart-card .card-head { margin-bottom: 4px; }
.qc-title { font-size: 15px; font-weight: 700; margin-bottom: 14px; }
.quick-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.quick {
  display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-radius: 14px;
  background: var(--acc-grad); color: #fff; font-weight: 600; font-size: 14px;
  box-shadow: 0 8px 20px rgba(139, 92, 246, 0.25); transition: transform .15s;
}
.quick:hover { transform: translateY(-3px); color: #fff; }
</style>
