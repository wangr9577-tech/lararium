<template>
  <div>
    <div class="sub-head">
      <el-button text @click="$router.push('/ielts')"><el-icon><ArrowLeft /></el-icon>雅思主页</el-button>
      <span class="sub-name">周计划 · 每日 1 小时打卡</span>
    </div>
    <!-- 规则说明 -->
    <div class="tip glass">
      <div class="tip-main">每天固定 1 小时：先背 15 分钟单词（百词斩 · 雅思核心词 30 个），剩余时间按当天主题练 —— 单词已包含在这 1 小时内</div>
      <div class="tip-sub">约 2 个月后考试：前 6 周按此表执行；最后 2 周周六升级为完整套题模考</div>
    </div>

    <!-- 周切换 -->
    <div class="wbar glass">
      <el-button text circle @click="moveWeek(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
      <div class="wlabel">
        <span class="wrange">{{ weekLabel }}</span>
        <el-button size="small" round :disabled="isCurWeek" @click="goCurWeek">本周</el-button>
      </div>
      <el-button text circle @click="moveWeek(1)"><el-icon><ArrowRight /></el-icon></el-button>
      <span class="wdone">本周 {{ doneCount }} / 7 完成</span>
    </div>

    <!-- 7 天打卡 -->
    <div class="days">
      <div v-for="d in days" :key="d.date" class="day glass" :class="{ today: d.isToday, done: d.done }">
        <div class="d-left">
          <div class="d-date">
            <span class="d-dow">{{ d.label }}</span>
            <span class="d-num">{{ d.monthDay }}</span>
          </div>
          <el-checkbox class="d-chk" :model-value="d.done" size="small" @change="(v: any) => toggle(d, v)" />
        </div>
        <div class="d-main">
          <div class="d-focus" :style="{ color: d.color }">{{ d.focus }}</div>
          <div class="d-segs">
            <div v-for="(s, i) in d.segs" :key="i" class="seg">
              <span class="seg-i" :style="{ background: d.color }">{{ i + 1 }}</span>
              <span>{{ s }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { http } from '../../api/client'

/** 周计划模板：dow=1..7 周一~周日；三段合计 60 分钟（含 15 分钟单词） */
const WEEK_PLAN = [
  { dow: 1, label: '周一', focus: '听力', color: '#38bdf8', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '雅思官方真题听力 S1/S2 一套并对答案（30 分钟）', '错题重听 + 场景词复习（15 分钟）'] },
  { dow: 2, label: '周二', focus: '阅读', color: '#a78bfa', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '雅思官方真题阅读 1 篇限时（20 分钟）', '精读 + 整理同义替换 5–10 组（25 分钟）'] },
  { dow: 3, label: '周三', focus: '口语', color: '#f472b6', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '本周 2 个主题素材：背表达 + 造句（30 分钟）', '影子跟读 / 自录复听（15 分钟）'] },
  { dow: 4, label: '周四', focus: '写作', color: '#fbbf24', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '小作文限时写作（20 分钟）', '对照范文改写润色 + 功能句积累（25 分钟）'] },
  { dow: 5, label: '周五', focus: '复盘', color: '#34d399', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '本周听力/阅读错题重做复盘（30 分钟）', '生词滚动复习（15 分钟）'] },
  { dow: 6, label: '周六', focus: '模考', color: '#fb7185', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '听力半套限时（25 分钟）', '阅读 1 篇限时（20 分钟）——考前 2 周起改为完整套题模考'] },
  { dow: 7, label: '周日', focus: '复盘', color: '#34d399', segs: ['单词 · 百词斩雅思核心词 30 个（15 分钟）', '补齐本周未完成 + 错词总复习（25 分钟）', '写周小结 + 预习下周口语主题（20 分钟）'] },
]

const pad = (n: number) => String(n).padStart(2, '0')
const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function mondayOf(d: Date): Date {
  const x = new Date(d)
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7))
  x.setHours(0, 0, 0, 0)
  return x
}

const cursor = ref(mondayOf(new Date()))
const doneMap = ref<Record<string, boolean>>({}) // "week:dow" -> done
const busy = ref(false)

const weekKey = computed(() => fmt(cursor.value))
const isCurWeek = computed(() => weekKey.value === fmt(mondayOf(new Date())))
const weekLabel = computed(() => {
  const b = new Date(cursor.value)
  b.setDate(b.getDate() + 6)
  return `${fmt(cursor.value)} ~ ${fmt(b)}`
})
const days = computed(() => {
  const today = fmt(new Date())
  return WEEK_PLAN.map((p) => {
    const d = new Date(cursor.value)
    d.setDate(d.getDate() + p.dow - 1)
    return {
      ...p,
      date: fmt(d),
      monthDay: `${d.getMonth() + 1}/${d.getDate()}`,
      isToday: fmt(d) === today,
      done: !!doneMap.value[`${weekKey.value}:${p.dow}`],
    }
  })
})
const doneCount = computed(() => days.value.filter((x) => x.done).length)

async function load() {
  try {
    const r = await http.get<{ items: { slot: string; done: boolean }[] }>(`/ielts/plan?week=${weekKey.value}`)
    const m: Record<string, boolean> = {}
    for (const it of r.items) m[`${weekKey.value}:${Number(it.slot.slice(1))}`] = it.done
    doneMap.value = m
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '周计划加载失败')
    }
  }
}

function moveWeek(dir: number) {
  const c = new Date(cursor.value)
  c.setDate(c.getDate() + dir * 7)
  cursor.value = c
  load()
}
function goCurWeek() {
  cursor.value = mondayOf(new Date())
  load()
}

async function toggle(d: { dow: number }, v: boolean) {
  if (busy.value) return
  busy.value = true
  const key = `${weekKey.value}:${d.dow}`
  const before = doneMap.value[key]
  doneMap.value = { ...doneMap.value, [key]: !!v }
  try {
    await http.put('/ielts/plan', { week: weekKey.value, slot: `d${d.dow}`, done: !!v })
  } catch (e: any) {
    doneMap.value = { ...doneMap.value, [key]: before }
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '打卡失败')
    }
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sub-name { font-size: 15px; font-weight: 800; }
.tip {
  padding: 12px 18px; margin-bottom: 12px; border-radius: 14px;
  background: rgba(167, 139, 250, 0.08); border: 1px solid rgba(167, 139, 250, 0.2);
}
.tip-main { font-size: 14px; font-weight: 700; }
.tip-sub { font-size: 12.5px; color: var(--txt3); margin-top: 4px; }
html.theme-dark .tip-sub { color: var(--txt2); }

.wbar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; margin-bottom: 12px; border-radius: 14px;
}
.wlabel { display: flex; align-items: center; gap: 10px; }
.wrange { font-size: 15px; font-weight: 800; font-variant-numeric: tabular-nums; }
.wdone { margin-left: auto; font-size: 12.5px; color: var(--txt2); }

.days { display: grid; gap: 10px; }
.day {
  display: flex; gap: 16px; padding: 12px 18px; border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  transition: border-color .15s;
}
.day.today { border-color: var(--acc2); background: rgba(167, 139, 250, 0.06); }
.day.done { opacity: 0.72; }
.day.done .d-main { text-decoration: line-through; }
.d-left { flex: none; display: flex; flex-direction: column; align-items: center; gap: 6px; width: 58px; }
.d-date { display: flex; flex-direction: column; align-items: center; }
.d-dow { font-size: 13px; font-weight: 800; }
.d-num { font-size: 11px; color: var(--txt3); font-variant-numeric: tabular-nums; }
html.theme-dark .d-num { color: var(--txt2); }
.d-chk { margin-top: 2px; }
.d-main { flex: 1; min-width: 0; }
.d-focus { font-size: 15px; font-weight: 800; margin-bottom: 6px; }
.d-segs { display: grid; gap: 4px; }
.seg { display: flex; align-items: baseline; gap: 8px; font-size: 13px; line-height: 1.6; }
.seg-i {
  flex: none; width: 16px; height: 16px; border-radius: 5px;
  color: #fff; font-size: 10.5px; font-weight: 700;
  display: inline-grid; place-items: center; transform: translateY(2px);
}
</style>
