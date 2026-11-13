<template>
  <div class="page">
    <div class="page-title">时光机</div>
    <div class="page-sub">博客、笔记、日记与重要里程碑汇成一条时间轴，回看走过的路</div>

    <!-- 年份切换 + 年度统计 -->
    <div class="glass ybar">
      <button v-for="y in years" :key="y" class="ybtn" :class="{ on: y === selYear }" @click="selYear = y">{{ y }}</button>
      <span v-if="visible.length" class="ycnt">
        博客 {{ cnt.blog }} · 笔记 {{ cnt.note }} · 项目 {{ cnt.project }} · 日记 {{ cnt.diary }} 天<template v-if="cnt.milestone"> · 里程碑 {{ cnt.milestone }}</template>
      </span>
    </div>

    <div v-if="visible.length" class="tl">
      <!-- 里程碑块（该年） -->
      <div v-if="milestones.length" class="tgroup">
        <div class="tmonth">★</div>
        <div class="titems">
          <div class="titem milestone">
            <div class="tdot" />
            <div class="ttxt">
              <div class="ttitle">重要里程碑</div>
              <div v-for="m in milestones" :key="m.date + m.title" class="msub">
                <span class="mcheck" :class="{ on: m.done }">{{ m.done ? '✓' : '○' }}</span>
                <span :class="{ strike: m.done }">{{ m.title }}</span>
                <span class="mtime">{{ m.sub }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 按月的博客/笔记/日记 -->
      <div v-for="m in months" :key="m.mk" class="tgroup">
        <div class="tmonth">{{ m.month }} 月</div>
        <div class="titems">
          <div v-for="it in m.items" :key="it.kind + it.ref + it.date" class="titem" :class="it.kind" @click="open(it)">
            <div class="tdot" />
            <div class="ttxt">
              <div class="ttitle">{{ it.title }}</div>
              <div class="tsub">
                {{ it.date }} · {{ it.kind === 'diary' ? (it.sub ? `心情：${it.sub}` : '日记') : typeName(it.sub) }}
              </div>
            </div>
            <span class="tarrow">›</span>
          </div>
        </div>
      </div>
    </div>

    <EmptyState v-else icon="Clock" title="时间轴还是空的"
      desc="写下的博客与日记会自动按时间出现在这里——先写几篇，再来回看一整年的轨迹。"
      :features="['博客 / 学习笔记 / 项目经历 / 日记 统一时间轴', '重要里程碑时间线自动纳入', '按年筛选 · 按月分组', '点击条目直达原文']">
      <template #default>
        <el-button type="primary" round style="margin-top:18px" @click="$router.push('/notes')">去写博客</el-button>
        <el-button round style="margin-top:18px;margin-left:8px" @click="$router.push('/schedule')">写日记</el-button>
      </template>
    </EmptyState>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '../api/client'
import EmptyState from '../components/EmptyState.vue'

interface TlItem { date: string; kind: string; title: string; ref: string; sub: string; tag: string[]; done?: boolean }

const router = useRouter()
const items = ref<TlItem[]>([])
const selYear = ref('')

const years = computed(() => [...new Set(items.value.map((x) => x.date.slice(0, 4)))].sort().reverse())
const visible = computed(() => items.value.filter((x) => x.date.slice(0, 4) === selYear.value))
const milestones = computed(() => visible.value.filter((x) => x.kind === 'milestone'))
const cnt = computed(() => {
  const m: Record<string, number> = { blog: 0, note: 0, project: 0, diary: 0, milestone: 0 }
  for (const x of visible.value) {
    if (x.kind === 'diary') m.diary++
    else if (x.kind === 'milestone') m.milestone++
    else m[x.sub as string] = (m[x.sub as string] || 0) + 1
  }
  return m as { blog: number; note: number; project: number; diary: number; milestone: number }
})

const months = computed(() => {
  const map = new Map<string, TlItem[]>()
  for (const it of visible.value) {
    if (it.kind === 'milestone') continue
    const mk = it.date.slice(5, 7)
    map.set(mk, [...(map.get(mk) || []), it])
  }
  return [...map.entries()]
    .sort((a, b) => Number(b[0]) - Number(a[0]))
    .map(([mk, arr]) => ({ mk, month: Number(mk), items: arr }))
})

function typeName(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

function open(it: TlItem) {
  if (it.kind === 'diary') router.push(`/schedule?date=${it.ref}`)
  else if (it.kind === 'note') router.push(`/notes/${it.ref}`)
}

onMounted(async () => {
  try {
    const r = await http.get<{ items: TlItem[] }>('/timeline')
    items.value = r.items
    if (years.value.length) selYear.value = years.value[0]
  } catch { /* 会话失效由 client 统一处理 */ }
})
</script>

<style scoped>
.ybar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 16px; margin-bottom: 18px; }
.ybtn { border: none; cursor: pointer; padding: 4px 14px; border-radius: 999px; font-size: 13px; background: transparent; color: var(--txt2); font-family: inherit; }
.ybtn.on { background: var(--acc-grad); color: #fff; font-weight: 700; }
.ycnt { margin-left: auto; font-size: 12px; color: var(--txt2); }

.tl { display: grid; gap: 18px; }
.tgroup { display: grid; grid-template-columns: 64px 1fr; gap: 8px; }
.tmonth { text-align: right; color: var(--acc2); font-weight: 800; font-size: 16px; padding-top: 2px; }
.titems { border-left: 2px solid rgba(167, 139, 250, 0.35); padding-left: 16px; display: grid; gap: 4px; }
.titem { display: flex; align-items: flex-start; gap: 10px; padding: 9px 12px; border-radius: 10px; cursor: pointer; position: relative; }
.titem:hover { background: rgba(148, 163, 184, 0.1); }
.titem.milestone { cursor: default; }
.tdot { width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; flex: none; border: 2px solid #fff; box-shadow: 0 0 0 2px var(--c); }
html.theme-dark .tdot { border-color: #171b30; }
.titem.note { --c: #a78bfa; }
.titem.diary { --c: #ec4899; }
.titem.milestone { --c: #f59e0b; }
.ttxt { flex: 1; min-width: 0; }
.ttitle { font-weight: 600; font-size: 14px; }
.tsub { color: var(--txt2); font-size: 12px; margin-top: 1px; }
.tarrow { color: var(--txt3); align-self: center; }
.msub { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 13px; }
.mcheck { color: var(--txt3); font-weight: 700; }
.mcheck.on { color: #22c55e; }
.mtime { margin-left: auto; color: var(--txt2); font-size: 12px; }
.strike { text-decoration: line-through; color: var(--txt3); }
</style>
