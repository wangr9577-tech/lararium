<template>
  <div class="page">
    <!-- 顶栏 -->
    <div class="head glass">
      <div class="nav">
        <el-button text circle @click="move(-1)"><el-icon :size="18"><ArrowLeft /></el-icon></el-button>
        <span class="label grad-text">{{ viewLabel }}</span>
        <el-button text circle @click="move(1)"><el-icon :size="18"><ArrowRight /></el-icon></el-button>
        <el-button size="small" round @click="goToday">今天</el-button>
        <el-tooltip content="节假日数据抓取自公开数据源 timor.tech 并本地缓存；点按钮可强制刷新" placement="bottom">
          <el-button size="small" round :loading="holLoading" @click="refreshHols">刷新节假日</el-button>
        </el-tooltip>
      </div>
      <el-radio-group v-model="view" size="small">
        <el-radio-button value="month">月</el-radio-button>
        <el-radio-button value="week">周</el-radio-button>
      </el-radio-group>
    </div>

    <div class="layout">
      <div class="main glass">
        <CalendarMonth
          v-if="view === 'month'"
          :year="monthYear" :month="monthNo" :items="calendarItems"
          :ann="annByDate" :hols="holByDate"
          @pick="openDay"
        />

        <!-- 周视图 -->
        <div v-else class="week">
          <div v-for="d in weekDays" :key="d.date" class="wcol" :class="{ wtoday: d.isToday }" @click.self="openDay(d.date)">
            <div class="whead">
              <span class="wname">周{{ d.zh }}</span>
              <span class="wnum" :class="{ on: d.isToday }">{{ d.label }}</span>
            </div>
            <div class="witems">
              <EntryItem
                v-for="it in d.items" :key="it.id" :entry="it"
                @toggle="(v: boolean) => onToggle(it, v)"
                @edit="openEdit" @del="onDel"
              />
              <div v-if="!d.items.length" class="wempty" @click="openDay(d.date)">＋ 添加</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 本月计划 + 纪念日 侧栏 -->
      <aside class="side glass">
        <div class="stitle">
          <span>{{ monthNo }} 月计划</span>
          <span class="stip" v-if="monthItems.length">{{ doneCnt }}/{{ monthItems.length }}</span>
          <el-button size="small" circle class="sadd" @click="openAddMonthly">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <p class="sdesc">不绑定具体某天，随本月显示 · 可打勾计入完成</p>
        <div class="slist">
          <EntryItem
            v-for="it in monthItems" :key="it.id" :entry="it"
            @toggle="(v: boolean) => onToggle(it, v)"
            @edit="openEdit" @del="onDel"
          />
          <div v-if="!monthItems.length" class="sempty">还没有本月计划，点右上角 ＋ 添加</div>
        </div>

        <div class="stitle ann-title">
          <span>纪念日 <small class="tiny">每年重复</small></span>
          <el-button size="small" circle class="sadd" @click="openAnnAdd">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div class="slist">
          <div v-for="a in annList" :key="a.id" class="ann-row">
            <span class="astar">★</span>
            <div class="ainfo">
              <div class="aname">{{ a.name }}</div>
              <div class="adate">公历 {{ a.date.slice(5) }} · {{ a.lunar_text || '农历' }}</div>
              <div v-if="a.note" class="anote">{{ a.note }}</div>
            </div>
            <el-button text size="small" @click="openAnnEdit(a)">改</el-button>
            <el-button text size="small" type="danger" @click="delAnn(a)">删</el-button>
          </div>
          <div v-if="!annList.length" class="sempty">还没有纪念日，点 ＋ 添加（如生日：存公历，每年自动标公历与农历两个日子）</div>
        </div>
      </aside>
    </div>

    <!-- 任务表 + 日记：同行分栏（任务表窄、日记宽） -->
    <div class="bottom-grid">
      <TaskPanel ref="taskPanelRef" class="task-zone" @changed="onPanelChanged" />
      <DiaryPanel ref="diaryPanelRef" :initial-date="routeDate" class="diary-zone" @changed="onDiaryChanged" />
    </div>

    <!-- 某天详情抽屉 -->
    <el-drawer v-model="drawer" :title="drawerTitle" size="400px">
      <div v-if="drawerTags.length" class="dtags">
        <el-tag v-for="t in drawerTags" :key="t.text" size="small" :type="t.type" effect="plain">{{ t.text }}</el-tag>
      </div>
      <div class="ddiary">
        <div class="ddiary-info">
          <span class="ddiary-t">该天日记</span>
          <span class="ddiary-s">{{ drawerDiary }}</span>
        </div>
        <el-button size="small" type="primary" plain @click="goDiary(drawerDate)">去写 / 编辑</el-button>
      </div>
      <div class="dlist">
        <EntryItem
          v-for="it in drawerItems" :key="it.id" :entry="it" :checkable="false"
          @edit="openEdit" @del="onDel"
        />
        <div v-if="!drawerItems.length" class="sempty">这一天还没有 DDL / 事件</div>
      </div>
      <div class="dadd">
        <div class="dadd-t">快速添加（日历只放 DDL / 事件提醒，不打勾）</div>
        <el-input v-model="quick.title" placeholder="要提醒什么？" size="small" @keyup.enter="submitQuick" />
        <div class="dadd-row">
          <el-radio-group v-model="quick.type" size="small">
            <el-radio-button value="ddl">DDL</el-radio-button>
            <el-radio-button value="event">事件</el-radio-button>
          </el-radio-group>
          <el-input v-model="quick.time" placeholder="HH:MM" size="small" class="qtime" />
          <el-button type="primary" size="small" :loading="busy" @click="submitQuick">添加</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- 条目添加/编辑 -->
    <el-dialog v-model="formOpen" :title="form.id ? '编辑条目' : '添加条目'" width="440px">
      <el-form label-position="top">
        <el-form-item :label="form.kind === 'monthly' ? '所属月份' : '日期'">
          <el-date-picker
            v-if="form.kind === 'monthly'"
            v-model="form.date" type="month" value-format="YYYY-MM" style="width: 100%"
          />
          <el-date-picker v-else v-model="form.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio-button value="task">任务（计入完成）</el-radio-button>
            <el-radio-button value="ddl">截止 DDL</el-radio-button>
            <el-radio-button value="event">事件（不勾选）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.kind === 'daily'" label="时间（可空）">
          <el-input v-model="form.time_start" placeholder="如 14:30" style="width: 140px" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="内容…" @keyup.enter="submitForm" />
        </el-form-item>
        <el-form-item label="备注（可空）">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 纪念日 添加/编辑 -->
    <el-dialog v-model="annOpen" :title="annForm.id ? '编辑纪念日' : '添加纪念日'" width="420px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="annForm.name" placeholder="如：生日 / 纪念日 / 建站日" />
        </el-form-item>
        <el-form-item label="日期（存公历，如生日填出生公历日期）">
          <el-date-picker v-model="annForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%"
            placeholder="选择公历日期（如出生日期）" />
        </el-form-item>
        <el-form-item label="备注（可空）">
          <el-input v-model="annForm.note" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="annOpen = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="saveAnn">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Plus } from '@element-plus/icons-vue'
import { http } from '../api/client'
import { normTime } from '../utils/time'
import EntryItem, { type Entry } from '../components/EntryItem.vue'
import CalendarMonth, { type HolInfo } from '../components/CalendarMonth.vue'
import DiaryPanel from '../components/DiaryPanel.vue'
import TaskPanel from '../components/TaskPanel.vue'

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

const view = ref<'month' | 'week'>('month')
const cursor = ref(new Date())
const dailyItems = ref<Entry[]>([])
const monthItems = ref<Entry[]>([])
const busy = ref(false)
const holLoading = ref(false)

const monthYear = computed(() => cursor.value.getFullYear())
const monthNo = computed(() => cursor.value.getMonth() + 1)
const ym = computed(() => `${monthYear.value}-${pad(monthNo.value)}`)
const monthLabel = computed(() => `${monthYear.value} 年 ${monthNo.value} 月`)

/* ---------- 节假日 / 纪念日 ---------- */
interface Ann { id: number; name: string; date: string; note: string; lunar_text: string }
interface Occ { date: string; name: string; kind: 'solar' | 'lunar' }
const annList = ref<Ann[]>([])
const holItems = ref<(HolInfo & { date: string })[]>([])
/** 同年份不重复请求：'ok'=已加载 / 'empty'=该年尚未公布（负缓存）/ 'error'=真故障（允许重试，但只提示一次） */
const holTried = ref<Record<number, 'ok' | 'empty' | 'error'>>({})
/**
 * 提示去重。`holTried` 是组件级状态，每次重新进入日程页都会清零——数据源一抖，
 * 用户每次打开页面都要被弹一次「节假日数据暂不可用」（2026-11 的实际抱怨）。
 * 用 sessionStorage 记住本会话已经为哪些年份提示过：同一会话最多提示一次，
 * 刷新页面后仍安静，关掉标签重开才会再提醒一回。
 */
const HOL_NOTIFIED_KEY = 'krs_hol_notified'
function holNotified(year: number): boolean {
  try { return (sessionStorage.getItem(HOL_NOTIFIED_KEY) || '').split(',').includes(String(year)) } catch { return false }
}
function markHolNotified(year: number) {
  try {
    const s = new Set((sessionStorage.getItem(HOL_NOTIFIED_KEY) || '').split(',').filter(Boolean))
    s.add(String(year))
    sessionStorage.setItem(HOL_NOTIFIED_KEY, [...s].join(','))
  } catch { /* 无痕模式下 sessionStorage 可能不可用，忽略 */ }
}
const annByDate = ref<Record<string, { name: string; kind: 'solar' | 'lunar' }[]>>({})
const holByDate = ref<Record<string, HolInfo>>({})
const occCache = ref<Record<number, Occ[]>>({})

const weekDays = computed(() => {
  const d = new Date(cursor.value)
  const mon = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
  const zh = ['一', '二', '三', '四', '五', '六', '日']
  const tStr = iso(new Date())
  return Array.from({ length: 7 }, (_, i) => {
    const day = new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + i)
    const date = iso(day)
    return { date, zh: zh[i], label: `${day.getMonth() + 1}/${day.getDate()}`, isToday: date === tStr, items: byDate.value[date] || [] }
  })
})
const viewLabel = computed(() => {
  if (view.value === 'month') return monthLabel.value
  const ds = weekDays.value
  return `${ds[0].label} – ${ds[6].label}`
})

const byDate = computed<Record<string, Entry[]>>(() => {
  const m: Record<string, Entry[]> = {}
  for (const it of dailyItems.value) (m[it.date] ||= []).push(it)
  return m
})
/** 日历只承担「DDL / 事件」提醒：月视图数据源过滤掉任务（任务在下方任务表打勾） */
const calendarItems = computed(() => dailyItems.value.filter((it) => it.type !== 'task'))
const doneCnt = computed(() => monthItems.value.filter((x) => x.done).length)

async function loadAnn() {
  try {
    const r = await http.get<{ items: Ann[] }>('/anniversaries')
    annList.value = r.items
  } catch (e) { console.warn('[schedule] 纪念日标记加载失败', e) }
}

async function loadOcc(force = false) {
  const year = monthYear.value
  if (!force && occCache.value[year]) { syncMarks(); return }
  try {
    const r = await http.get<{ items: Occ[] }>(`/anniversaries/occ?year=${year}`)
    occCache.value = { ...occCache.value, [year]: r.items }
    syncMarks()
  } catch (e) { console.warn('[schedule] 纪念日标记加载失败', e) }
}

async function loadHols() {
  // 加载当前视图涉及的所有年份（月视图=当年；周视图跨年/抽屉跨月时可能多一年）
  const years = [...new Set(markDates().map((d) => Number(d.slice(0, 4))))]
  for (const year of years) {
    // 同年份不重复请求：已加载('ok')或已确认未公布('empty')直接跳过；'error' 允许再试但只提示一次
    if (holTried.value[year] === 'ok' || holTried.value[year] === 'empty') continue
    holLoading.value = true
    try {
      const r = await http.get<{ items: (HolInfo & { date: string })[]; available?: boolean; message?: string }>(`/holiday/${year}`)
      if (r.available === false) {
        // 该年放假安排尚未公布（后端已负缓存）：不是故障，日历照常可用
        holTried.value = { ...holTried.value, [year]: 'empty' }
        if (!holNotified(year)) {
          markHolNotified(year)
          ElMessage.info(`${year} 年放假安排尚未公布，暂不显示节假日标记`)
        }
        continue
      }
      holTried.value = { ...holTried.value, [year]: 'ok' }
      holItems.value = holItems.value.filter((h) => h.date.slice(0, 4) !== String(year)).concat(r.items || [])
      syncMarks()
    } catch (e: any) {
      holTried.value = { ...holTried.value, [year]: 'error' }
      if (!holNotified(year)) {
        markHolNotified(year)
        ElMessage.warning(`${e?.response?.data?.detail || '节假日数据暂不可用'}——不影响日程本身的使用，可点「刷新节假日」重试`)
      }
    } finally {
      holLoading.value = false
    }
  }
}

async function refreshHols() {
  const year = monthYear.value
  holLoading.value = true
  try {
    const r = await http.get<{ items: (HolInfo & { date: string })[]; available?: boolean; stale?: boolean }>(`/holiday/${year}?refresh=1`)
    if (r.available === false) {
      // 未公布：刷新无意义，友好提示即可
      holTried.value = { ...holTried.value, [year]: 'empty' }
      ElMessage.info('该年度放假安排尚未公布，无需刷新')
      return
    }
    if (r.stale === true) {
      // 数据源真故障：后端已回退旧缓存
      ElMessage.warning('数据源暂时不可用，已保留上次缓存')
      return
    }
    holTried.value = { ...holTried.value, [year]: 'ok' }
    holItems.value = holItems.value.filter((h) => h.date.slice(0, 4) !== String(year)).concat(r.items || [])
    syncMarks()
    ElMessage.success('节假日已更新')
  } catch (e: any) {
    holTried.value = { ...holTried.value, [year]: 'error' }
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  } finally {
    holLoading.value = false
  }
}

/** 当前需要标记的全部日期：当前月所有日期 + 周视图 7 天（可能跨月/跨年）+ 抽屉所选日期 */
function markDates(): string[] {
  const set = new Set<string>()
  const daysIn = new Date(monthYear.value, monthNo.value, 0).getDate()
  for (let d = 1; d <= daysIn; d++) set.add(`${ym.value}-${pad(d)}`)
  for (const d of weekDays.value) set.add(d.date)
  if (drawerDate.value) set.add(drawerDate.value)
  return [...set]
}

/** 确保 dates 涉及的每个年份都有 occ 数据（force 或已缓存则跳过），失败静默忽略；完成后重算标记 */
async function ensureOccFor(dates: string[], force = false): Promise<void> {
  const years = [...new Set(dates.map((d) => Number(d.slice(0, 4))))]
  for (const year of years) {
    if (!force && occCache.value[year]) continue
    try {
      const r = await http.get<{ items: Occ[] }>(`/anniversaries/occ?year=${year}`)
      occCache.value = { ...occCache.value, [year]: r.items }
    } catch { /* ignore */ }
  }
  syncMarks()
}

function syncMarks() {
  // 标记范围：markDates()（当前月 + 周视图 7 天 + 抽屉所选日），覆盖跨月/跨年
  const ann: Record<string, { name: string; kind: 'solar' | 'lunar' }[]> = {}
  const hol: Record<string, HolInfo> = {}
  for (const date of markDates()) {
    const occ = occCache.value[Number(date.slice(0, 4))] || []
    const hits = occ.filter((o) => o.date === date)
    if (hits.length) ann[date] = hits.map((h) => ({ name: h.name, kind: h.kind }))
    const hi = holItems.value.find((h) => h.date === date)
    if (hi) hol[date] = { name: hi.name, is_off: hi.is_off, is_workday: hi.is_workday }
  }
  annByDate.value = ann
  holByDate.value = hol
}

/* ---------- 数据加载 ---------- */
/** 真故障提示去重：只提示一次，成功加载后复位 */
let loadErrShown = false
async function reload() {
  try {
    if (view.value === 'month') {
      const from = `${ym.value}-01`
      const to = `${ym.value}-${pad(new Date(monthYear.value, monthNo.value, 0).getDate())}`
      const [r, mr] = await Promise.all([
        http.get<{ items: Entry[] }>(`/schedule/range?from=${from}&to=${to}`),
        http.get<{ items: Entry[] }>(`/schedule/monthly?month=${ym.value}`),
      ])
      dailyItems.value = r.items
      monthItems.value = mr.items
    } else {
      // 周视图同样要拉本月计划：否则侧栏「本月计划」保留的是旧月份数据（错月）
      const from = weekDays.value[0].date
      const to = weekDays.value[6].date
      const [r, mr] = await Promise.all([
        http.get<{ items: Entry[] }>(`/schedule/range?from=${from}&to=${to}`),
        http.get<{ items: Entry[] }>(`/schedule/monthly?month=${ym.value}`),
      ])
      dailyItems.value = r.items
      monthItems.value = mr.items
    }
    syncMarks()
    loadErrShown = false
  } catch (e: any) {
    const st = e?.response?.status
    if (st !== 401 && st !== 423 && !loadErrShown) {
      loadErrShown = true
      ElMessage.error(e?.response?.data?.detail || '日程数据加载失败，请刷新重试')
    }
  }
}

function move(dir: number) {
  const c = new Date(cursor.value)
  if (view.value === 'month') { c.setDate(1); c.setMonth(c.getMonth() + dir) }
  else c.setDate(c.getDate() + dir * 7)
  cursor.value = c
}

function goToday() {
  const d = new Date()
  if (view.value === 'week') {
    cursor.value = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
  } else {
    cursor.value = d
  }
}

watch([view, ym, () => weekDays.value[0].date], () => {
  reload()
  loadHols()
  ensureOccFor(markDates())
})
watch([monthYear, monthNo], () => syncMarks())

/* ---------- 某天抽屉 ---------- */
const route = useRoute()
const drawer = ref(false)
const drawerDate = ref('')
/** 由 ?date=YYYY-MM-DD 深链定位（时光机/首页入口），空=今天 */
const routeDate = computed(() => {
  const q = route.query.date
  return typeof q === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(q) ? q : ''
})
const diaryPanelRef = ref<InstanceType<typeof DiaryPanel> | null>(null)
const taskPanelRef = ref<InstanceType<typeof TaskPanel> | null>(null)
const drawerDiary = ref('')
const drawerTitle = computed(() => {
  if (!drawerDate.value) return ''
  const [y, m, d] = drawerDate.value.split('-').map(Number)
  return `${y} 年 ${m} 月 ${d} 日 · 安排`
})
const drawerItems = computed(() => (byDate.value[drawerDate.value] || []).filter((it) => it.type !== 'task'))
const drawerTags = computed(() => {
  const tags: { text: string; type: 'success' | 'danger' | 'info' }[] = []
  const an = annByDate.value[drawerDate.value]
  if (an?.length) tags.push({ text: `纪念日：${an.map((a) => `${a.name}${a.kind === 'lunar' ? '（农历）' : '（公历）'}`).join('、')}`, type: 'danger' })
  const ho = holByDate.value[drawerDate.value]
  if (ho) tags.push({ text: ho.is_workday ? '调休上班' : `节假日：${ho.name}`, type: ho.is_off ? 'danger' : 'info' })
  return tags
})
const quick = reactive({ title: '', type: 'ddl', time: '' })

watch(drawerDate, () => syncMarks())

/** ?date= 深链去重：onMounted 首次定位与后续 query 变化共用，避免重复打开同一个日期 */
let lastDeepLink = ''
// ?date= 在页面已挂载时变化（同路由内跳转/再次点击同一入口）：同样定位日历并打开该天抽屉
watch(routeDate, (d) => {
  // query 清空时一并重置去重标记：否则「?date=X → 清空 → 再回同一 ?date=X」会被误判为重复而跳过
  if (!d) { lastDeepLink = ''; return }
  if (d === lastDeepLink) return
  lastDeepLink = d
  const [y, m] = d.split('-').map(Number)
  cursor.value = new Date(y, m - 1, 1)
  void openDay(d)
  void diaryPanelRef.value?.setDate(d)
})

/** 抽屉「该天日记」状态：先按乐观值显示，读回后校正；抽屉联动与日记面板保存后可复用 */
async function refreshDrawerDiary(date: string) {
  if (!date) return
  drawerDiary.value = '已写' // 先按乐观值，读回后校正
  try {
    const r = await http.get<{ content: string }>(`/diary/${date}`)
    drawerDiary.value = r.content.trim() ? '已写' : '未写'
  } catch { drawerDiary.value = '未写' }
}

async function openDay(date: string) {
  drawerDate.value = date
  drawer.value = true
  // 抽屉可能落在非当前月的日期（周视图跨月/深链）：确保该年 occ 数据并立即重算标记
  await ensureOccFor([date])
  syncMarks()
  // 常驻任务表联动到该天（写要做的事 + 打勾）
  void taskPanelRef.value?.setDate(date)
  void refreshDrawerDiary(date)
}

/** 日记面板保存后：抽屉里「该天日记」的已写/未写状态同步刷新（抽屉没开就不用拉） */
function onDiaryChanged() { if (drawer.value) void refreshDrawerDiary(drawerDate.value) }

/** 任务表 / 日记面板增删改后：重载日历数据，抽屉开着时同步刷新日记状态 */
async function onPanelChanged() { await reload(); if (drawer.value) void refreshDrawerDiary(drawerDate.value) }

/** 抽屉「去写/编辑」：切到日记区该日期并滚动定位 */
function goDiary(date: string) {
  drawer.value = false
  void diaryPanelRef.value?.setDate(date)
  document.getElementById('diary-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function submitQuick() {
  if (!quick.title.trim()) return
  // 抽屉快速添加（kind='daily'）的时间先归一化：全角冒号/9:5 → 09:05；非法格式直接提示不发请求
  const t = normTime(quick.time)
  if (quick.time.trim() && !t) return ElMessage.warning('时间格式应为 HH:MM，如 14:30')
  busy.value = true
  try {
    await http.post('/schedule', {
      date: drawerDate.value, kind: 'daily', type: quick.type,
      title: quick.title.trim(), time_start: t, note: '',
    })
    quick.title = ''
    quick.time = ''
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally { busy.value = false }
}

/* ---------- 条目统一表单 ---------- */
const formOpen = ref(false)
const form = reactive({ id: null as number | null, kind: 'daily' as 'daily' | 'monthly', date: '', type: 'task', title: '', time_start: '', note: '' })

function openAddMonthly() {
  Object.assign(form, { id: null, kind: 'monthly', date: ym.value, type: 'task', title: '', time_start: '', note: '' })
  formOpen.value = true
}

function openEdit(entry: Entry) {
  Object.assign(form, {
    id: entry.id, kind: entry.kind, date: entry.date, type: entry.type,
    title: entry.title, time_start: entry.time_start, note: entry.note,
  })
  formOpen.value = true
}

async function submitForm() {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  // 与抽屉快速添加同口径：daily 的时间先归一化（全角冒号 / 9:5 → 09:05），非法直接提示不发请求
  const t = form.kind === 'daily' ? normTime(form.time_start) : ''
  if (form.kind === 'daily' && form.time_start.trim() && !t) return ElMessage.warning('时间格式应为 HH:MM，如 14:30')
  busy.value = true
  const body = {
    date: form.date, kind: form.kind, type: form.type,
    title: form.title.trim(), time_start: t, note: form.note.trim(),
  }
  try {
    if (form.id) await http.put(`/schedule/${form.id}`, body)
    else await http.post('/schedule', body)
    formOpen.value = false
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { busy.value = false }
}

async function onToggle(entry: Entry, done: boolean) {
  try {
    await http.put(`/schedule/${entry.id}/done`, { done })
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function onDel(entry: Entry) {
  try {
    await ElMessageBox.confirm(`删除「${entry.title}」？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/schedule/${entry.id}`)
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

/* ---------- 纪念日 CRUD ---------- */
const annOpen = ref(false)
const annForm = reactive({ id: null as number | null, name: '', date: '', note: '' })

function openAnnAdd() {
  Object.assign(annForm, { id: null, name: '', date: iso(new Date()), note: '' })
  annOpen.value = true
}

function openAnnEdit(a: Ann) {
  Object.assign(annForm, { id: a.id, name: a.name, date: a.date, note: a.note })
  annOpen.value = true
}

async function saveAnn() {
  if (!annForm.name.trim() || !annForm.date) return ElMessage.warning('请填写名称与日期')
  busy.value = true
  const body = { name: annForm.name.trim(), date: annForm.date, note: annForm.note.trim() }
  try {
    if (annForm.id) await http.put(`/anniversaries/${annForm.id}`, body)
    else await http.post('/anniversaries', body)
    annOpen.value = false
    ElMessage.success('已保存')
    await loadAnn()
    await loadOcc(true) // 纪念日变更后失效当前年 occ 缓存，日历 ★ 标记立即刷新
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { busy.value = false }
}

async function delAnn(a: Ann) {
  try {
    await ElMessageBox.confirm(`删除纪念日「${a.name}」？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/anniversaries/${a.id}`)
    await loadAnn()
    await loadOcc(true) // 纪念日删除后失效当前年 occ 缓存，日历 ★ 标记立即刷新
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

reload()
loadAnn()
loadOcc()
loadHols()

// ?date= 深链：日历定位到该月并打开该天抽屉（时光机/首页跳日记的落点）
onMounted(() => {
  if (routeDate.value) {
    lastDeepLink = routeDate.value
    const [y, m] = routeDate.value.split('-').map(Number)
    cursor.value = new Date(y, m - 1, 1)
    void openDay(routeDate.value)
    void diaryPanelRef.value?.setDate(routeDate.value)
  }
})
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; padding: 10px 18px; margin-bottom: 14px; flex-wrap: wrap; gap: 10px; }
.nav { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; }
.label { font-size: 19px; font-weight: 800; margin: 0 8px; min-width: 150px; text-align: center; }

.layout { display: flex; gap: 14px; align-items: flex-start; }
.main { flex: 1; min-width: 0; padding: 14px; }
.side { width: 300px; flex: none; padding: 16px 18px; max-height: 700px; overflow: auto; }

.stitle { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 800; margin-top: 6px; }
.ann-title { margin-top: 18px; border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 12px; }
.tiny { font-size: 11px; color: var(--txt2); font-weight: 400; }
.stip { font-size: 12px; color: #fff; background: var(--acc-grad); border-radius: 999px; padding: 0 8px; }
.sadd { margin-left: auto; }
.sdesc { color: var(--txt2); font-size: 12px; margin: 6px 0 12px; }
.slist { display: grid; gap: 6px; }
.sempty { color: var(--txt2); font-size: 12.5px; padding: 14px 4px; line-height: 1.7; }
.ann-row { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 10px; background: rgba(236, 72, 153, 0.07); border: 1px solid rgba(236, 72, 153, 0.16); font-size: 12.5px; }
.astar { color: #ec4899; font-size: 12px; }
.ainfo { flex: 1; min-width: 0; }
.aname { font-weight: 600; }
.adate { color: #ec4899; font-size: 11px; }
.anote { color: var(--txt2); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; min-height: 560px; }
.wcol { border-radius: 10px; padding: 8px 6px; cursor: pointer; background: rgba(148, 163, 184, 0.05); border: 1px solid transparent; min-height: 100%; }
.wcol:hover { border-color: rgba(167, 139, 250, 0.3); }
.wcol.wtoday { border-color: var(--acc2); background: rgba(167, 139, 250, 0.07); }
.whead { text-align: center; margin-bottom: 8px; }
.wname { font-size: 11px; color: var(--txt2); margin-right: 6px; }
.wnum { font-size: 16px; font-weight: 700; }
.wnum.on { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: var(--acc-grad); color: #fff; }
.witems { display: grid; gap: 4px; }
.wempty { font-size: 12px; color: var(--txt2); text-align: center; padding: 16px 0; }

.dtags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.ddiary {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 7px 10px; border-radius: 10px; margin-bottom: 12px; font-size: 12.5px;
  background: rgba(167, 139, 250, 0.08); border: 1px dashed rgba(167, 139, 250, 0.3);
}
.ddiary-t { font-weight: 700; }
.ddiary-s { color: var(--txt2); font-size: 11.5px; margin-left: 8px; }
/* 任务表 + 日记 同行分栏（任务表窄、日记宽） */
.bottom-grid { display: flex; gap: 14px; margin-top: 14px; align-items: flex-start; }
.task-zone { width: 340px; flex: none; }
.diary-zone { flex: 1; min-width: 0; }
.dlist { display: grid; gap: 6px; margin-bottom: 18px; }
.dadd { border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 12px; display: grid; gap: 8px; }
.dadd-t { font-size: 13px; font-weight: 700; }
.dadd-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.qtime { width: 90px; }

@media (max-width: 1100px) {
  .layout { flex-direction: column; }
  /* 列方向下 flex:1 会让宽度退回按内容收缩（半页/窄窗翻月会越缩越小），这里强制铺满 */
  .main { width: 100%; flex: 0 0 auto; }
  .side { width: 100%; max-height: none; }
  .bottom-grid { flex-direction: column; }
  .task-zone { width: 100%; }
  .week { grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .wcol { min-width: 0; }
}
</style>
