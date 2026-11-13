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
        <router-link class="stat stat-link" to="/pomodoro"><div class="stat-top"><span>今日专注</span><span class="stat-symbol">◷</span></div><div class="stat-number">{{ focusToday }}<small>分钟</small></div><div class="stat-hint">去番茄钟专注 ↗</div></router-link>
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
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Notebook, Reading, Calendar, Memo } from '@element-plus/icons-vue'
import { http } from '../api/client'
import type { Entry } from '../components/EntryItem.vue'

const name = ref('主人')
const todayText = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })
const stats = reactive({ notes: 0, papers: 0 })
// 专注明细（计时、时长图、热力图）都搬到「番茄钟」页了，首页只留今天这一个数
const focusToday = ref(0)
const todayItems = ref<Entry[]>([])

const todayStr = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})()

const pendingCount = computed(() => todayItems.value.filter((x) => x.type !== 'event' && !x.done).length)

const quicks = computed(() => [
  { path: '/schedule', title: '日程日历', icon: Memo },
  { path: '/notes', title: '写博客', icon: Notebook },
  { path: '/papers', title: '读论文', icon: Reading },
  { path: '/schedule', title: '写日记', icon: Calendar },
])

async function loadToday() {
  try {
    const r = await http.get<{ items: Entry[] }>(`/schedule/day?date=${todayStr}`)
    todayItems.value = r.items
  } catch { /* ignore */ }
}

async function loadFocus() {
  try {
    const r = await http.get<{ today: { minutes: number } }>('/focus/stats?days=1')
    focusToday.value = r.today.minutes
  } catch { /* ignore */ }
}

onMounted(async () => {
  loadFocus()
  loadToday()
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
.dashboard { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; align-items:stretch; }
.dashboard > * { min-width:0; }
.hero,.overview,.quick-section { grid-column:1 / -1; }
.hero { min-height:240px; display:flex; justify-content:space-between; align-items:end; padding:40px; overflow:hidden; }
.hero-main { max-width:680px; }
.section-kicker,.section-index { color:var(--acc2); font-size:12px; line-height:16px; font-weight:700; letter-spacing:.1em; }
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
.stat-link { color:inherit; transition:background-color .3s cubic-bezier(.22,1,.36,1); }
.stat-link:hover { color:inherit; background:rgba(128,112,150,.13); }
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
@media(max-width:820px) { .hero { padding:24px; min-height:220px; }.hero h1 { font-size:36px; line-height:40px; }.hero-aside { display:none; }.overview { padding:24px; }.stats-grid,.quick-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.section-hint,.overview-date { display:none; } }
@media(max-width:480px) { .hero h1 { font-size:30px; line-height:36px; }.hero-actions { gap:16px; }.stats-grid,.quick-grid { gap:8px; }.quick { min-height:88px; padding:12px; gap:8px; }.quick-icon { width:32px; height:32px; }.quick-arrow { display:none; }.overview { padding:16px; } }
</style>
