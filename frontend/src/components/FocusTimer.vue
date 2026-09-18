<template>
  <div class="ft glass">
    <div class="ft-main">
      <div class="ring" :class="{ running }">
        <div class="ring-in">
          <div class="time">{{ display }}</div>
          <div class="state">{{ stateText }}</div>
        </div>
      </div>
      <div class="ft-side">
        <div class="ft-title grad-text">专注计时</div>
        <div class="ft-sub">开启计时，自动统计每天专注时长</div>
        <div class="ft-stats">
          <div class="stat">
            <div class="num">{{ todayMin }}<small> 分</small></div>
            <div class="lab">今日专注</div>
          </div>
          <div class="stat">
            <div class="num">{{ todaySessions }}<small> 次</small></div>
            <div class="lab">今日会话</div>
          </div>
          <div class="stat">
            <div class="num">{{ weekTotal }}<small> 分</small></div>
            <div class="lab">近 7 天</div>
          </div>
        </div>
        <div class="ft-btns">
          <el-button v-if="!running" type="primary" size="large" round @click="start">
            <el-icon style="margin-right:6px"><VideoPlay /></el-icon>开始专注
          </el-button>
          <template v-else>
            <el-button type="success" size="large" round @click="stop">
              <el-icon style="margin-right:6px"><VideoPause /></el-icon>结束（记录时长）
            </el-button>
            <el-button size="large" round @click="cancel" :loading="busy">放弃本次</el-button>
          </template>
          <el-button size="large" round @click="dialog = true">
            <el-icon style="margin-right:6px"><EditPen /></el-icon>补记
          </el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="dialog" title="补记专注时长（忘了开计时时用）" width="420px">
      <el-form label-position="top">
        <el-form-item label="日期">
          <el-date-picker v-model="manual.date" type="date" value-format="YYYY-MM-DD"
            :disabled-date="(d: Date) => d.getTime() > Date.now()" style="width: 100%" />
        </el-form-item>
        <el-form-item label="专注分钟数">
          <el-input-number v-model="manual.minutes" :min="1" :max="1440" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注（可空）">
          <el-input v-model="manual.note" maxlength="100" />
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, VideoPause, EditPen } from '@element-plus/icons-vue'
import { http } from '../api/client'

const emit = defineEmits<{ (e: 'changed'): void }>()

const running = ref(false)
const startedAt = ref(0)
const elapsed = ref(0)
const todayMin = ref(0)
const todaySessions = ref(0)
const weekTotal = ref(0)
const busy = ref(false)
const dialog = ref(false)
const manual = reactive({ date: todayStr(), minutes: 30, note: '' })

let ticker: ReturnType<typeof setInterval> | undefined

const display = computed(() => fmt(elapsed.value))
const stateText = computed(() => (running.value ? '专注进行中…' : '准备开始'))

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(s: number) {
  s = Math.max(0, Math.floor(s))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

function parseLocal(iso: string) {
  return new Date(iso.replace(' ', 'T')).getTime()
}

async function refresh() {
  try {
    const stats = await http.get<{
      today: { minutes: number; sessions: number; running: { id: number; start: string; start_ms?: number } | null }
      daily: { date: string; minutes: number }[]
    }>('/focus/stats?days=7')
    const r = stats.today.running
    if (r) {
      running.value = true
      startedAt.value = r.start_ms || parseLocal(r.start)
      elapsed.value = Math.max(0, (Date.now() - startedAt.value) / 1000)
    } else {
      running.value = false
      elapsed.value = 0
    }
    todayMin.value = stats.today.minutes
    todaySessions.value = stats.today.sessions
    weekTotal.value = stats.daily.reduce((a, d) => a + d.minutes, 0)
  } catch { /* 401/423 拦截处理 */ }
}

async function start() {
  busy.value = true
  try {
    const r = await http.post<{ id: number; start: string; start_ms?: number }>('/focus/start', { note: '' })
    running.value = true
    startedAt.value = r.start_ms || parseLocal(r.start)
    elapsed.value = 0
    ElMessage.success('专注开始，加油')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  } finally { busy.value = false }
}

async function stop() {
  busy.value = true
  try {
    const s = await http.get<{ running: { id: number } | null }>('/focus/running')
    if (!s.running) {
      ElMessage.warning('没有进行中的专注')
      running.value = false
      return
    }
    const r = await http.post<{ minutes: number }>('/focus/stop', { id: s.running.id })
    ElMessage.success(`本轮专注 ${r.minutes} 分钟`)
    running.value = false
    elapsed.value = 0
    await refresh()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '结束失败')
  } finally { busy.value = false }
}

async function cancel() {
  busy.value = true
  try {
    const s = await http.get<{ running: { id: number } | null }>('/focus/running')
    if (s.running) await http.del(`/focus/${s.running.id}`)
    running.value = false
    elapsed.value = 0
    await refresh()
    emit('changed')
  } catch { /* ignore */ } finally { busy.value = false }
}

async function submitManual() {
  busy.value = true
  try {
    await http.post('/focus/manual', { date: manual.date, minutes: manual.minutes, note: manual.note })
    ElMessage.success('已补记')
    dialog.value = false
    await refresh()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '补记失败')
  } finally { busy.value = false }
}

onMounted(() => {
  refresh()
  ticker = setInterval(() => {
    if (running.value && startedAt.value) elapsed.value = (Date.now() - startedAt.value) / 1000
  }, 1000)
})

onBeforeUnmount(() => clearInterval(ticker))
</script>

<style scoped>
.ft { padding: 22px 26px; margin-bottom: 16px; }
.ft-main { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
.ring {
  width: 128px; height: 128px; flex: none; border-radius: 50%;
  display: grid; place-items: center;
  background: conic-gradient(#e2e8f0 0 100%);
}
html.theme-dark .ring { background: conic-gradient(#334155 0 100%); }
.ring.running { background: conic-gradient(var(--acc2) 0 100%); }
.ring-in {
  width: 108px; height: 108px; border-radius: 50%;
  background: var(--glass-bg, #fff);
  display: grid; place-items: center; text-align: center;
}
html.theme-dark .ring-in { background: #111827; }
.time { font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }
.state { font-size: 11px; color: var(--txt2); margin-top: -14px; }
.ft-side { flex: 1; min-width: 260px; }
.ft-title { font-size: 18px; font-weight: 800; }
.ft-sub { color: var(--txt2); font-size: 13px; margin: 4px 0 14px; }
.ft-stats { display: flex; gap: 26px; margin-bottom: 16px; }
.stat .num { font-size: 22px; font-weight: 800; color: var(--acc2); }
.stat .num small { font-size: 12px; }
.stat .lab { font-size: 12px; color: var(--txt2); }
.ft-btns { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
