<template>
  <div class="page">
    <div class="page-title">日记</div>
    <div class="page-sub">每天一页，正文加密落盘 —— 写给自己看的</div>

    <div class="layout">
      <!-- 左栏：文字记录 -->
      <div class="left">
        <!-- 轻量日期导航（无大日历表） -->
        <div class="glass nav">
          <div class="nav-row">
            <el-button text circle size="small" @click="moveMonth(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
            <el-date-picker
              :model-value="selDate" type="date" value-format="YYYY-MM-DD" :clearable="false"
              placeholder="选日期" style="width: 140px" size="small" @change="onDateChange"
            />
            <el-button text circle size="small" @click="moveMonth(1)"><el-icon><ArrowRight /></el-icon></el-button>
            <span class="cal-title">{{ curYear }} 年 {{ curMonth }} 月</span>
          </div>
          <div class="recent">
            <div class="rt">本月已写 {{ monthDays.length }} 天</div>
            <div v-if="monthDays.length" class="chips">
              <button v-for="d in [...monthDays].reverse().slice(0, 12)" :key="d" class="dchip"
                :class="{ on: d === selDate }" @click="pickDate(d)">{{ d.slice(8) }} 日</button>
            </div>
            <div v-else class="rn">这个月还没有写日记</div>
          </div>
        </div>

        <!-- 文字记录 -->
        <section class="glass edit">
          <div class="ehead">
            <div class="edate grad-text">{{ prettyDate }}</div>
            <div class="emeta">
              <el-select v-model="form.mood" placeholder="心情" clearable size="small" style="width: 100px" @change="save(false)">
                <el-option v-for="m in moods" :key="m" :label="m" :value="m" />
              </el-select>
              <el-select v-model="form.weather" placeholder="天气" clearable size="small" style="width: 96px" @change="save(false)">
                <el-option v-for="w in weathers" :key="w" :label="w" :value="w" />
              </el-select>
              <span class="saved-hint" :class="{ err: !saveOk }">{{ saveHint }}</span>
              <el-button size="small" @click="trashOpen = true">回收站</el-button>
              <el-button size="small" type="danger" plain @click="clearDay">清空当天</el-button>
            </div>
          </div>
          <VditorEditor v-model="form.content" @save="() => save(true)" />
        </section>
      </div>

      <!-- 右栏：ToList 待办清单 + 时间安排表 -->
      <aside class="side glass">
        <div class="block">
          <div class="btitle">ToList · 今日待办</div>
          <div class="qadd">
            <el-input v-model="quick.title" placeholder="要做什么？" size="small" @keyup.enter="submitQuick" />
            <div class="qadd-row">
              <el-select v-model="quick.type" size="small" style="width: 88px">
                <el-option label="任务" value="task" />
                <el-option label="DDL" value="ddl" />
                <el-option label="事件" value="event" />
              </el-select>
              <el-input v-model="quick.time" placeholder="HH:MM" size="small" class="qtime" @keyup.enter="submitQuick" />
              <el-button type="primary" size="small" :loading="busy" @click="submitQuick">添加</el-button>
            </div>
          </div>
          <div class="blist">
            <EntryItem
              v-for="it in todos" :key="it.id" :entry="it"
              @toggle="(v: boolean) => onToggle(it, v)"
              @edit="openEdit" @del="onDel"
            />
            <div v-if="!todos.length" class="sempty">这一天还没有待办，快添加一条</div>
          </div>
        </div>

        <div class="block">
          <div class="btitle">时间安排</div>
          <div class="tlist">
            <div v-for="it in timeline" :key="it.id" class="trow" :class="`ty-${it.type}`" @click="openEdit(it)">
              <span class="ttime">{{ it.time_start }}</span>
              <span class="ttitle" :class="{ done: it.done }">{{ it.title }}</span>
            </div>
            <div v-if="!timeline.length" class="sempty">这一天还没有带时间的安排</div>
          </div>
          <div class="tsub">按当天日程自动汇总，与「日程」页互通</div>
        </div>
      </aside>
    </div>

    <!-- 待办/安排 添加编辑 -->
    <el-dialog v-model="formOpen" :title="entryForm.id ? '编辑条目' : '添加条目'" width="420px">
      <el-form label-position="top">
        <el-form-item label="类型">
          <el-radio-group v-model="entryForm.type">
            <el-radio-button value="task">任务</el-radio-button>
            <el-radio-button value="ddl">DDL</el-radio-button>
            <el-radio-button value="event">事件</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="时间（可空）">
          <el-input v-model="entryForm.time_start" placeholder="如 14:30" style="width: 140px" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="entryForm.title" placeholder="内容…" @keyup.enter="submitForm" />
        </el-form-item>
        <el-form-item label="备注（可空）">
          <el-input v-model="entryForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <TrashDialog v-model="trashOpen" @restored="() => { loadCalendar(); loadEntry() }" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { http, getToken } from '../api/client'
import VditorEditor from '../components/VditorEditor.vue'
import EntryItem, { type Entry } from '../components/EntryItem.vue'
import TrashDialog from '../components/TrashDialog.vue'

const trashOpen = ref(false) // P2-L1：日记删除进回收站，本页直接可恢复

const route = useRoute()

const pad = (n: number) => String(n).padStart(2, '0')
const fmtDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const moods = ['平静', '开心', '低落', '焦虑', '疲惫', '充实', '其他']
const weathers = ['晴', '多云', '阴', '雨', '雪', '雷雨']

const cur = ref(new Date()) // 导航所在月
const selDate = ref(fmtDate(new Date()))
const monthDays = ref<string[]>([])
const form = reactive({ mood: '', weather: '', content: '' })
const updatedAt = ref('')
const saveHint = ref('就绪')
const saveOk = ref(true)
let loadingEntry = false
let dirty = false
let saveTimer: ReturnType<typeof setTimeout> | undefined
let lastSaved = ''
// P0-6：正文打字也要自动保存（原只有心情/天气 @change 与 Ctrl+S 会存，切日期必丢稿）。
// suppressContentWatch 屏蔽"加载/清空时代码赋值 form.content"触发的伪改动（watcher 回调
// 在微任务里执行，那时 loadingEntry 已被复位，故必须显式抑制 + nextTick 后再放开）。
let suppressContentWatch = false
watch(() => form.content, () => {
  if (suppressContentWatch) return
  save(false)
})

const curYear = computed(() => cur.value.getFullYear())
const curMonth = computed(() => cur.value.getMonth() + 1)
const prettyDate = computed(() => {
  const [y, m, d] = selDate.value.split('-').map(Number)
  return `${y} 年 ${m} 月 ${d} 日`
})

/* ---------- 右栏：当天日程（与「日程」页互通） ---------- */
const dayItems = ref<Entry[]>([])
const busy = ref(false)
const todos = computed(() => dayItems.value.filter((it) => it.type !== 'event'))
const timeline = computed(() =>
  [...dayItems.value].filter((it) => it.time_start).sort((a, b) => a.time_start.localeCompare(b.time_start))
)

async function loadSchedule() {
  try {
    const r = await http.get<{ items: Entry[] }>(`/schedule/day?date=${selDate.value}`)
    dayItems.value = r.items
  } catch { /* 401/423 跳登录 */ }
}

const quick = reactive({ title: '', type: 'task', time: '' })

async function submitQuick() {
  if (!quick.title.trim()) return
  busy.value = true
  try {
    await http.post('/schedule', {
      date: selDate.value, kind: 'daily', type: quick.type,
      title: quick.title.trim(), time_start: quick.time.trim(), note: '',
    })
    quick.title = ''
    quick.time = ''
    await loadSchedule()
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '添加失败')
    }
  } finally { busy.value = false }
}

const formOpen = ref(false)
const entryForm = reactive({ id: null as number | null, type: 'task', title: '', time_start: '', note: '' })

function openEdit(entry: Entry) {
  Object.assign(entryForm, { id: entry.id, type: entry.type, title: entry.title, time_start: entry.time_start, note: entry.note })
  formOpen.value = true
}

async function submitForm() {
  if (!entryForm.title.trim()) return ElMessage.warning('请填写标题')
  busy.value = true
  const body = {
    date: selDate.value, kind: 'daily', type: entryForm.type,
    title: entryForm.title.trim(), time_start: entryForm.time_start.trim(), note: entryForm.note.trim(),
  }
  try {
    if (entryForm.id) await http.put(`/schedule/${entryForm.id}`, body)
    else await http.post('/schedule', body)
    formOpen.value = false
    await loadSchedule()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { busy.value = false }
}

async function onToggle(entry: Entry, done: boolean) {
  try {
    await http.put(`/schedule/${entry.id}/done`, { done })
    await loadSchedule()
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
    await loadSchedule()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

/* ---------- 日记 ---------- */
async function loadCalendar() {
  try {
    const r = await http.get<{ days: string[] }>(`/diary/calendar?month=${curYear.value}-${pad(curMonth.value)}`)
    monthDays.value = r.days
  } catch { /* 401/423 跳登录 */ }
}

async function setDate(date: string) {
  if (date === selDate.value) return
  await flush()
  const [y, m] = date.split('-').map(Number)
  cur.value = new Date(y, m - 1, 1) // 导航定位到该月
  selDate.value = date
  await Promise.all([loadEntry(), loadSchedule()])
}

async function pickDate(date: string) {
  await setDate(date)
}

async function onDateChange(v: string | null) {
  if (!v) return
  await setDate(v)
}

async function loadEntry() {
  loadingEntry = true
  suppressContentWatch = true
  try {
    const r = await http.get<{ mood: string; weather: string; content: string; updated: string }>(`/diary/${selDate.value}`)
    form.mood = r.mood
    form.weather = r.weather
    form.content = r.content
    updatedAt.value = r.updated
    dirty = false
    lastSaved = r.updated
    saveHint.value = r.updated ? `已保存于 ${r.updated.slice(11, 16)}` : '空'
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '读取失败')
    }
  } finally {
    loadingEntry = false
    // watcher 回调在微任务里执行：nextTick 后再放开抑制，避免"加载即误存"
    await nextTick()
    suppressContentWatch = false
  }
}

async function save(manual: boolean) {
  if (loadingEntry) return
  dirty = true
  if (manual) {
    clearTimeout(saveTimer)
    await doSave()
    return
  }
  saveOk.value = true
  saveHint.value = '保存中…'
  clearTimeout(saveTimer)
  saveTimer = setTimeout(doSave, 900)
}

async function doSave() {
  dirty = true
  try {
    const r = await http.put<{ updated: string }>(`/diary/${selDate.value}`, { ...form })
    updatedAt.value = r.updated
    saveOk.value = true
    saveHint.value = `已保存 ${r.updated.slice(11, 16)}`
    dirty = false
    lastSaved = r.updated
    const day = selDate.value
    if (!monthDays.value.includes(day)) {
      monthDays.value.push(day)
      monthDays.value.sort()
    }
  } catch (e: any) {
    saveOk.value = false
    saveHint.value = '保存失败，重试中…'
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '保存失败')
    }
  }
}

async function flush() {
  clearTimeout(saveTimer)
  if (dirty && !loadingEntry) {
    await doSave()
  }
}

async function clearDay() {
  if (!form.content && !form.mood) return
  try {
    await ElMessageBox.confirm('清空这一天的日记内容？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/diary/${selDate.value}`)
    monthDays.value = monthDays.value.filter((d) => d !== selDate.value)
    suppressContentWatch = true
    dirty = false
    form.content = ''
    form.mood = ''
    form.weather = ''
    saveHint.value = '空'
    ElMessage.success('已移入回收站，可在「回收站」恢复')
    await nextTick()
    suppressContentWatch = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

function moveMonth(dir: number) {
  const d = new Date(cur.value)
  d.setDate(1)
  d.setMonth(d.getMonth() + dir)
  cur.value = d
}

watch([curYear, curMonth], () => {
  loadCalendar()
  // 不在当前月则不自动跳，只刷新月列表
})

// P2-M3：直接关标签/切后台时 axios 异步请求会被掐——对齐 NoteEdit，
// 用 fetch keepalive 把当天未落盘的日记尽力补发一次（浏览器允许 ≤64KB 同步排队）。
function onPageHide() {
  clearTimeout(saveTimer)
  if (!dirty || loadingEntry) return
  fetch(`/api/diary/${selDate.value}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify({ ...form }),
    keepalive: true,
  }).catch(() => { /* 关页阶段无法再提示 */ })
}

onMounted(() => {
  window.addEventListener('pagehide', onPageHide)
  const qd = typeof route.query.date === 'string' ? route.query.date : ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(qd)) {
    selDate.value = qd
    const [y, m] = qd.split('-').map(Number)
    cur.value = new Date(y, m - 1, 1) // 导航定位到该月
  }
  loadCalendar()
  loadEntry()
  loadSchedule()
})

onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPageHide)
  clearTimeout(saveTimer)
  if (dirty) doSave().catch(() => {})
})
</script>

<style scoped>
.layout { display: flex; gap: 14px; align-items: stretch; }
.left { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.side { width: 330px; flex: none; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.edit { flex: 1; padding: 14px 16px; min-height: 480px; }

/* 轻量日期导航 */
.nav { padding: 14px 16px; }
.nav-row { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.cal-title { font-weight: 700; font-size: 15px; margin-left: 4px; }
.recent { border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 10px; }
.rt { font-size: 12px; color: var(--txt2); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.dchip {
  border: 1px solid rgba(148, 163, 184, 0.3); background: transparent; color: var(--txt3);
  border-radius: 999px; padding: 2px 10px; font-size: 12px; cursor: pointer; font-family: inherit;
}
html.theme-dark .dchip { color: #cbd5e1; }
.dchip.on { background: var(--acc-grad); color: #fff; border-color: transparent; }
.rn { font-size: 12px; color: var(--txt2); }

/* 右栏 */
.block { display: flex; flex-direction: column; gap: 8px; }
.block + .block { border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 14px; }
.btitle { font-size: 15px; font-weight: 800; }
.qadd { display: flex; flex-direction: column; gap: 6px; }
.qadd-row { display: flex; align-items: center; gap: 6px; }
.qtime { width: 82px; }
.blist { display: flex; flex-direction: column; gap: 4px; }
.sempty { color: var(--txt2); font-size: 12.5px; padding: 10px 2px; line-height: 1.7; }
.tlist { display: flex; flex-direction: column; gap: 3px; max-height: 260px; overflow: auto; }
.trow {
  display: flex; align-items: center; gap: 8px; padding: 5px 8px;
  border-left: 3px solid var(--c); border-radius: 7px; font-size: 13px; cursor: pointer;
}
.ty-task { --c: #a78bfa; background: rgba(167, 139, 250, 0.07); }
.ty-ddl { --c: #f43f5e; background: rgba(244, 63, 94, 0.06); }
.ty-event { --c: #0ea5e9; background: rgba(14, 165, 233, 0.06); }
.ttime { font-size: 11.5px; font-weight: 600; color: var(--c); font-variant-numeric: tabular-nums; flex: none; width: 44px; }
.ttitle { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ttitle.done { text-decoration: line-through; color: var(--txt2); }
.tsub { font-size: 11px; color: var(--txt2); }

/* 编辑器头部 */
.ehead { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.edate { font-size: 19px; font-weight: 800; }
.emeta { display: flex; align-items: center; gap: 8px; margin-left: auto; flex-wrap: wrap; }
.saved-hint { font-size: 12px; color: var(--txt2); }
.saved-hint.err { color: #f43f5e; }

@media (max-width: 1024px) {
  .layout { flex-direction: column; }
  .side { width: 100%; }
}
</style>