<template>
  <div class="glass task-panel">
    <!-- 顶部：日期切换 -->
    <div class="thead">
      <el-button text circle size="small" @click="move(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
      <span class="ttitle grad-text">{{ prettyDate }}</span>
      <el-button text circle size="small" @click="move(1)"><el-icon><ArrowRight /></el-icon></el-button>
      <el-button size="small" round @click="goToday">今天</el-button>
    </div>

    <!-- 快速添加：只加「任务」 -->
    <div class="qadd">
      <div class="qadd-row">
        <el-input v-model="quick.title" placeholder="要做什么？" size="small" @keyup.enter="submitQuick" />
        <el-input v-model="quick.time" placeholder="HH:MM" size="small" class="qtime" @keyup.enter="submitQuick" />
        <el-button type="primary" size="small" :loading="busy" @click="submitQuick">添加</el-button>
      </div>
      <div class="qhint">任务只在这里记录并打勾，不会出现在日历上</div>
    </div>

    <!-- 今日/近期截止 (DDL) 区域 -->
    <div v-if="allDdls.length" class="ddl-section">
      <div class="ddl-head">
        <span class="btitle ddl-title">今日 / 近期截止 (DDL)</span>
        <button type="button" class="asst-jump-btn" @click="router.push('/assistant')">
          <span>助手视图</span>
          <el-icon :size="12"><ArrowRight /></el-icon>
        </button>
      </div>
      <div class="blist ddl-list">
        <div
          v-for="it in allDdls"
          :key="it.id"
          class="ddl-item"
          :class="{ done: it.done }"
          @click="onDdlClick(it)"
        >
          <div class="ddl-left">
            <span class="ddl-badge">DDL</span>
            <span v-if="it.time_start" class="ddl-time">{{ it.time_start }}</span>
            <span class="ddl-name" :class="{ 'done-text': it.done }">{{ it.title }}</span>
          </div>
          <div class="ddl-ops" @click.stop>
            <el-checkbox
              v-if="it.isSchedule && it.rawEntry"
              :model-value="it.done"
              size="small"
              @change="(v: any) => onToggle(it.rawEntry!, v)"
            />
            <el-tooltip content="前往助手查看" placement="top">
              <el-button text circle size="small" @click="router.push('/assistant')">
                <el-icon><ChatLineRound /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>
      </div>
    </div>

    <!-- 任务列表（可打勾） -->
    <div class="btitle">当天任务</div>
    <div class="blist">
      <div v-for="it in todos" :key="it.id">
      <EntryItem
        :entry="it"
        @toggle="(v: boolean) => onToggle(it, v)"
        @edit="entry => emit('edit-entry', entry)" @del="entry => emit('delete-entry', entry)"
      />
      <el-button text size="small" @click="router.push({ path: '/pomodoro', query: { task: String(it.id), date: it.date } })">开始专注</el-button>
      </div>
      <div v-if="!todos.length" class="sempty">这一天还没有任务，快添加一条</div>
    </div>

    <!-- 添加/编辑弹窗（只含任务字段） -->
    <el-dialog v-model="formOpen" :title="entryForm.id ? '编辑任务' : '添加任务'" width="420px">
      <el-form label-position="top">
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
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, ChatLineRound } from '@element-plus/icons-vue'
import { http } from '../api/client'
import { assistantApi, type AssistantRecord } from '../api/assistant'
import { normTime } from '../utils/time'
import EntryItem, { type Entry } from './EntryItem.vue'

const router = useRouter()

/** 任务变更后通知父级（日历/抽屉）刷新 */
const emit = defineEmits<{ (e: 'changed'): void; (e: 'date-change', date: string): void; (e: 'edit-entry', entry: Entry): void; (e: 'delete-entry', entry: Entry): void }>()

const pad = (n: number) => String(n).padStart(2, '0')
const fmtDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

const selDate = ref(fmtDate(new Date()))
const dayItems = ref<Entry[]>([])
const asstNotices = ref<AssistantRecord[]>([])
const busy = ref(false)

const prettyDate = computed(() => {
  const [y, m, d] = selDate.value.split('-').map(Number)
  return `${y} 年 ${m} 月 ${d} 日`
})
/** 任务表只承担「任务」：列表仅显示 task */
const todos = computed(() => dayItems.value.filter((it) => it.type === 'task'))

interface DdlItem {
  id: string | number
  title: string
  time_start?: string
  done: boolean
  isSchedule: boolean
  rawEntry?: Entry
  assistantRecordId?: number
}

const allDdls = computed<DdlItem[]>(() => {
  const result: DdlItem[] = []

  // 1. 从当日日程中筛选 type === 'ddl'
  const scheduleDdls = dayItems.value.filter((it) => it.type === 'ddl')
  for (const it of scheduleDdls) {
    result.push({
      id: `sched-${it.id}`,
      title: it.title,
      time_start: it.time_start,
      done: it.done,
      isSchedule: true,
      rawEntry: it
    })
  }

  // 2. 从助手通知事项中查找当日或关联的截止事项（去重避免与已同步日程重复）
  for (const asst of asstNotices.value) {
    if (asst.deadline_date === selDate.value) {
      const exists = result.some((r) => r.title === asst.title)
      if (!exists) {
        result.push({
          id: `asst-${asst.id}`,
          title: asst.title,
          time_start: asst.deadline_time,
          done: asst.thread?.status === 'completed',
          isSchedule: false,
          assistantRecordId: asst.id
        })
      }
    }
  }

  return result
})

function onDdlClick(it: DdlItem) {
  if (it.isSchedule && it.rawEntry) {
    emit('edit-entry', it.rawEntry)
  } else {
    router.push('/assistant')
  }
}

async function loadData() {
  try {
    const r = await http.get<{ items: Entry[] }>(`/schedule/day?date=${selDate.value}`)
    dayItems.value = r.items
  } catch { /* 会话失效由 client 统一处理 */ }

  try {
    asstNotices.value = await assistantApi.list('notice')
  } catch { /* ignore */ }
}

/** 切换日期：供父组件（日历点选/深链）调用 */
async function setDate(date: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return
  if (date === selDate.value) return
  selDate.value = date
  await loadData()
}

function move(dir: number) {
  const d = new Date(selDate.value)
  d.setDate(d.getDate() + dir)
  selDate.value = fmtDate(d)
  emit('date-change', selDate.value)
  loadData()
}

function goToday() {
  const t = fmtDate(new Date())
  if (t === selDate.value) return
  selDate.value = t
  emit('date-change', selDate.value)
  loadData()
}

const quick = reactive({ title: '', time: '' })

async function submitQuick() {
  if (!quick.title.trim()) {
    ElMessage.warning('请先填写要做的事')
    return
  }
  // 与 Schedule.vue 同口径：时间先归一化（全角冒号/9:5 → 09:05），非法格式直接提示不发请求
  const t = normTime(quick.time)
  if (quick.time.trim() && !t) return ElMessage.warning('时间格式应为 HH:MM，如 14:30')
  busy.value = true
  try {
    await http.post('/schedule', {
      date: selDate.value, kind: 'daily', type: 'task',
      title: quick.title.trim(), time_start: t, note: '',
    })
    quick.title = ''
    quick.time = ''
    await loadData()
    emit('changed')
    ElMessage.success('已添加')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加失败')
  } finally { busy.value = false }
}

const formOpen = ref(false)
const entryForm = reactive({ id: null as number | null, title: '', time_start: '', note: '' })

function openEdit(entry: Entry) {
  Object.assign(entryForm, { id: entry.id, title: entry.title, time_start: entry.time_start, note: entry.note })
  formOpen.value = true
}

async function submitForm() {
  if (!entryForm.title.trim()) return ElMessage.warning('请填写标题')
  // 与 Schedule.vue 同口径：时间先归一化（全角冒号/9:5 → 09:05），非法格式直接提示不发请求
  const t = normTime(entryForm.time_start)
  if (entryForm.time_start.trim() && !t) return ElMessage.warning('时间格式应为 HH:MM，如 14:30')
  busy.value = true
  const body = {
    date: selDate.value, kind: 'daily', type: 'task',
    title: entryForm.title.trim(), time_start: t, note: entryForm.note.trim(),
  }
  try {
    if (entryForm.id) await http.put(`/schedule/${entryForm.id}`, body)
    else await http.post('/schedule', body)
    formOpen.value = false
    await loadData()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { busy.value = false }
}

async function onToggle(entry: Entry, done: boolean) {
  try {
    await http.put(`/schedule/${entry.id}/done`, { done })
    await loadData()
    emit('changed')
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
    await loadData()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

loadData()

defineExpose({ setDate, refresh: loadData })
</script>

<style scoped>
.task-panel { padding: 14px 16px 16px; }
.thead { display: flex; align-items: center; gap: 2px; margin-bottom: 10px; flex-wrap: wrap; }
.ttitle { font-size: 17px; font-weight: 800; margin: 0 6px; }
.thead .el-button + .el-button { margin-left: 0; }

.qadd { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.qadd-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.qadd-row .el-input:first-child { flex: 1; min-width: 120px; }
.qtime { width: 82px; }
.qhint { font-size: 11px; color: var(--txt2); }

.btitle { font-size: 14px; font-weight: 800; margin-bottom: 6px; color: var(--txt2); }
.blist { display: flex; flex-direction: column; gap: 4px; }
.sempty { color: var(--txt2); font-size: 12.5px; padding: 8px 2px; line-height: 1.7; }

/* 今日/近期截止 (DDL) 样式 */
.ddl-section {
  margin-bottom: 14px;
  background: rgba(245, 108, 108, 0.08);
  border: 1px dashed rgba(245, 108, 108, 0.4);
  border-radius: 8px;
  padding: 8px 10px;
}
.ddl-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.ddl-title {
  color: var(--el-color-danger) !important;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 0;
}
.asst-jump-btn {
  background: transparent;
  border: none;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  padding: 0;
}
.asst-jump-btn:hover {
  text-decoration: underline;
}
.ddl-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.ddl-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
  transition: all 0.15s;
}
.ddl-item:hover {
  border-color: var(--el-color-danger);
}
.ddl-item.done {
  opacity: 0.55;
}
.ddl-left {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ddl-badge {
  background: var(--el-color-danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  line-height: 14px;
}
.ddl-time {
  font-size: 11.5px;
  color: var(--txt2);
}
.ddl-name {
  font-size: 13px;
  color: var(--el-text-color-primary);
  font-weight: 500;
}
.ddl-name.done-text {
  text-decoration: line-through;
  color: var(--txt2);
}
.ddl-ops {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
