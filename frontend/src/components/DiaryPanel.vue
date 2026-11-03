<template>
  <div id="diary-panel" class="glass diary-panel">
    <!-- 轻量日期导航 -->
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

    <!-- 文字记录 -->
    <div class="ehead">
      <div class="edate grad-text">{{ prettyDate }}</div>
      <div class="emeta">
        <el-button size="small" round type="primary" plain :loading="footprintLoading" @click="fetchAndInjectFootprint">
          <el-icon><MagicStick /></el-icon> 注入今日足迹
        </el-button>
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
    <VditorEditor ref="editorRef" v-model="form.content" @save="() => save(true)" />

    <TrashDialog v-model="trashOpen" @restored="onRestored" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, MagicStick } from '@element-plus/icons-vue'
import { http, getToken } from '../api/client'
import VditorEditor from './VditorEditor.vue'
import TrashDialog from './TrashDialog.vue'

const props = withDefaults(defineProps<{ initialDate?: string }>(), { initialDate: '' })
const emit = defineEmits<{ (e: 'date-change', date: string): void; (e: 'changed'): void }>()

const editorRef = ref<InstanceType<typeof VditorEditor> | null>(null)
const footprintLoading = ref(false)
const trashOpen = ref(false) // P1-5：日记删除进回收站，本页直接可恢复

const pad = (n: number) => String(n).padStart(2, '0')
const fmtDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const moods = ['平静', '开心', '低落', '焦虑', '疲惫', '充实', '其他']
const weathers = ['晴', '多云', '阴', '雨', '雪', '雷雨']

const cur = ref(new Date()) // 导航所在月
const selDate = ref(/^\d{4}-\d{2}-\d{2}$/.test(props.initialDate) ? props.initialDate : fmtDate(new Date()))
const monthDays = ref<string[]>([])
const form = reactive({ mood: '', weather: '', content: '' })
const saveHint = ref('就绪')
const saveOk = ref(true)
let loadingEntry = false
let dirty = false
let saveTimer: ReturnType<typeof setTimeout> | undefined
let saving = false // doSave 串行化：请求进行中再次触发只排一次队
let queued = false
let dayHasFile = false // 当天是否已有日记文件（loadEntry 时按 updated 判定，用于空内容保护）
let formDay = selDate.value // 当前 form 内容所属的日期：初始=选中日，仅 loadEntry 成功后更新；
                            // 恒非空，保证「内容归属日」在任何加载失败态下都不退化为空而串到别的日期
// P0-1：正文打字也要自动保存（原只有心情/天气 @change 与 Ctrl+S 会存，切日期必丢稿）。
// suppressContentWatch 屏蔽"加载/清空时代码赋值 form.content"触发的伪改动：watcher 回调
// 在微任务里执行，那时 loadingEntry 已复位，故必须显式抑制 + nextTick 后再释放。
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

async function loadCalendar() {
  try {
    const r = await http.get<{ days: string[] }>(`/diary/calendar?month=${curYear.value}-${pad(curMonth.value)}`)
    monthDays.value = r.days
  } catch { /* 401/423 跳登录 */ }
}

/** 切换选中日期：供父组件（日程页抽屉/深链）调用 */
async function setDate(date: string) {
  if (date === selDate.value) return
  await flush()
  const [y, m] = date.split('-').map(Number)
  cur.value = new Date(y, m - 1, 1) // 导航定位到该月
  selDate.value = date
  emit('date-change', date)
  await loadEntry()
}

async function pickDate(date: string) {
  await setDate(date)
}

async function onDateChange(v: string | null) {
  if (!v) return
  await setDate(v)
}

async function loadEntry() {
  const target = selDate.value // 本次加载的目标日：整段流程都用它，避免中途切换日期导致错配
  loadingEntry = true
  suppressContentWatch = true
  try {
    const r = await http.get<{ mood: string; weather: string; content: string; updated: string }>(`/diary/${target}`)
    form.mood = r.mood
    form.weather = r.weather
    form.content = r.content
    dirty = false
    dayHasFile = !!r.updated
    formDay = target // form 内容归属日：仅加载成功后置位，写盘时按它落盘
    saveHint.value = r.updated ? `已保存于 ${r.updated.slice(11, 16)}` : '空'
  } catch (e: any) {
    // 加载失败不改动 form，也就不改动 dayHasFile/formDay：两者描述的是「form 内容所属那一天的文件状态」，
    // 若在此置 false 会造成归属错配（失败态下清空旧日正文会被空内容保护误拦，即 P-e）
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
  dirty = true // 先置脏：flush/页面卸载才认得出还有待落盘改动
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
  if (saving) { queued = true; return }
  // 空内容保护：正文/心情/天气全空且当天本来没写过 → 不落盘，避免凭空建空日记
  // 判据用 dayHasFile（当天是否已有文件），不能用 monthDays（那是"导航所在月"的数据，
  // 切月后 selDate 不在该月会误判为"没写过"→ 已有日记被清空时反而不落盘）
  if (!form.content.trim() && !form.mood && !form.weather && !dayHasFile) {
    dirty = false
    saveHint.value = '空'
    return
  }
  saving = true
  dirty = true
  const day = formDay || selDate.value // 内容归属日：form 仍是上一天正文时（如新日期加载失败）写回上一天，而不是污染新日期
  const payload = { ...form } // 正文快照：请求期间继续输入不会改变本次写入内容
  try {
    const r = await http.put<{ updated: string }>(`/diary/${day}`, payload)
    saveOk.value = true
    saveHint.value = `已保存 ${r.updated.slice(11, 16)}`
    dirty = false
    dayHasFile = true
    if (!monthDays.value.includes(day)) {
      monthDays.value.push(day)
      monthDays.value.sort()
    }
    emit('changed')
  } catch (e: any) {
    saveOk.value = false
    saveHint.value = '保存失败，请检查网络后重试'
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '保存失败')
    }
  } finally {
    saving = false
    // P1：切日期时 loadEntry 会在途（loadingEntry=true），此刻 form 仍是上一天的正文，
    // 补跑会把上一天正文写进新日期文件 → 只在没有加载在途时补跑。
    // 该窗口内更晚的输入与"已切到新日期"语义冲突，丢弃比污染安全；在途那一轮的内容已由本次 PUT 落盘。
    if (queued) { queued = false; if (!loadingEntry) void doSave() }
  }
}

async function flush() {
  clearTimeout(saveTimer)
  if (dirty && !loadingEntry) {
    await doSave()
  }
}

async function clearDay() {
  if (!form.content && !form.mood && !form.weather) return
  try {
    await ElMessageBox.confirm('清空这一天的日记内容？', '确认', { type: 'warning' })
  } catch { return }
  try {
    const day = formDay || selDate.value // 与 doSave 同一口径：清空的是「form 内容所属的那一天」
    await http.del(`/diary/${day}`)
    monthDays.value = monthDays.value.filter((d) => d !== day)
    suppressContentWatch = true
    dirty = false
    dayHasFile = false
    form.content = ''
    form.mood = ''
    form.weather = ''
    saveHint.value = '空'
    ElMessage.success('已移入回收站，可在「回收站」恢复')
    emit('changed') // 通知父级（日程页抽屉「该天日记」状态）刷新为未写
    await nextTick()
    suppressContentWatch = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

/** 回收站恢复后：刷新月标记与当天内容 */
function onRestored() {
  void loadCalendar()
  void loadEntry()
  emit('changed') // 恢复后同步父级（日程页抽屉）的日记状态
}

/** 注入今日足迹：从后端聚合各模块今日数据并自动写入日记 */
async function fetchAndInjectFootprint() {
  if (footprintLoading.value) return
  footprintLoading.value = true
  try {
    const res = await http.get<{ template: string }>(`/diary/footprint?date=${selDate.value}`)
    const footprintText = res.template || ''
    if (!footprintText) {
      ElMessage.warning('未能获取到足迹内容')
      return
    }

    const currentContent = form.content.trim()
    if (!currentContent) {
      // 当前为空直接插入
      form.content = footprintText
    } else {
      // 当前已有内容，提示用户是“追加到底部”还是“覆盖原始内容”
      try {
        await ElMessageBox.confirm(
          '当前日记已有内容，请选择足迹注入方式：',
          '注入今日足迹',
          {
            distinguishCancelAndClose: true,
            confirmButtonText: '追加到底部',
            cancelButtonText: '覆盖原始内容',
            type: 'info',
          }
        )
        // 用户点击追加到底部
        form.content = `${form.content.trimEnd()}\n\n${footprintText}`
      } catch (action: any) {
        if (action === 'cancel') {
          // 用户点击覆盖原始内容
          form.content = footprintText
        } else {
          // 用户点击取消或关闭
          return
        }
      }
    }

    save(false)
    await nextTick()
    editorRef.value?.focus()
    ElMessage.success('已自动注入今日足迹，写下今天的感想吧！')
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '获取今日足迹失败')
    }
  } finally {
    footprintLoading.value = false
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

// P2-7：父组件（日程页深链/抽屉）传入的日期变化时同步切换选中日
watch(() => props.initialDate, (v) => {
  if (v && /^\d{4}-\d{2}-\d{2}$/.test(v) && v !== selDate.value) void setDate(v)
})

// P0-3：直接关标签/切后台时 axios 异步请求会被掐——用 fetch keepalive
// 把当天未落盘的日记尽力补发一次（浏览器允许 ≤64KB 同步排队）。
function onPageHide() {
  clearTimeout(saveTimer)
  if (!dirty || loadingEntry) return
  const day = formDay || selDate.value // 与 doSave 同一口径：补存写回内容归属日，不能写进当前选中日
  fetch(`/api/diary/${day}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify({ ...form }),
    keepalive: true,
  }).catch(() => { /* 关页阶段无法再提示 */ })
}

onMounted(() => {
  window.addEventListener('pagehide', onPageHide)
  const [y, m] = selDate.value.split('-').map(Number)
  cur.value = new Date(y, m - 1, 1)
  loadCalendar()
  loadEntry()
})

onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPageHide)
  clearTimeout(saveTimer)
  void flush()
})

defineExpose({ setDate })
</script>

<style scoped>
.diary-panel { padding: 14px 16px 16px; }
.nav-row { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.cal-title { font-weight: 700; font-size: 15px; margin-left: 4px; }
.recent { border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 10px; margin-bottom: 12px; }
.rt { font-size: 12px; color: var(--txt2); margin-bottom: 8px; font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.dchip {
  border: 1px solid rgba(167, 139, 250, 0.25); background: rgba(167, 139, 250, 0.12);
  color: #7c3aed; border-radius: 999px; padding: 2px 10px; font-size: 12px;
  cursor: pointer; font-family: inherit; font-weight: 500;
}
html.theme-dark .dchip { color: #c4b5fd; background: rgba(167, 139, 250, 0.16); border-color: rgba(167, 139, 250, 0.3); }
.dchip:hover { background: rgba(167, 139, 250, 0.22); }
.dchip.on { background: var(--acc-grad); color: #fff; border-color: transparent; }
.rn { font-size: 12px; color: var(--txt2); }
.ehead { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.edate { font-size: 19px; font-weight: 800; }
.emeta { display: flex; align-items: center; gap: 8px; margin-left: auto; flex-wrap: wrap; }
.saved-hint { font-size: 12px; color: var(--txt2); }
.saved-hint.err { color: #f43f5e; }
</style>