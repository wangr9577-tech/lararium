<template>
  <div class="cm">
    <div class="cm-head">
      <span v-for="w in weekNames" :key="w" class="cw">{{ w }}</span>
    </div>
    <div class="cm-body">
      <div v-for="(week, wi) in weeks" :key="wi" class="cm-week">
        <div
          v-for="c in week" :key="c.key"
          class="day"
          :class="[c.inMonth ? '' : 'dim', c.isToday ? 'today' : '', c.hasDdl && c.inMonth ? 'has-ddl' : '']"
          @click="c.inMonth && emit('pick', c.date)"
        >
          <div class="dhead">
            <span class="dnum">{{ c.day || '' }}</span>
            <span v-if="c.isToday" class="dtag">今天</span>
            <span v-if="c.inMonth && hols[c.date]" class="hol"
              :class="{ off: hols[c.date].is_off, work: hols[c.date].is_workday }">
              {{ hols[c.date].is_workday ? '班' : hols[c.date].name.slice(0, 3) }}
            </span>
            <span v-if="c.inMonth && ann[c.date]?.length" class="ann"
              :title="ann[c.date].map((a) => `${a.name}（${a.kind === 'lunar' ? '农历' : '公历'}）`).join('\n')">
              ★{{ ann[c.date][0].name }}{{ ann[c.date][0].kind === 'lunar' ? '·农历' : '' }}{{ ann[c.date].length > 1 ? ` +${ann[c.date].length - 1}` : '' }}
            </span>
          </div>
          <div v-if="c.inMonth && c.items.length" class="cells">
            <template v-for="(it, i) in c.items.slice(0, 3)" :key="it.id">
              <div class="mini" :class="`m-${it.type} ${it.done ? 'mdone' : ''}`">
                <span class="mtime" v-if="it.time_start">{{ it.time_start }}</span>
                <span class="mtitle">{{ it.title }}</span>
              </div>
            </template>
            <div v-if="c.items.length > 3" class="more">+{{ c.items.length - 3 }} 更多</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Entry } from './EntryItem.vue'

export interface HolInfo { name: string; is_off: boolean; is_workday: boolean }
export interface AnnInfo { name: string; kind: 'solar' | 'lunar' }

const props = defineProps<{
  year: number
  month: number // 1-12
  items: Entry[]
  ann?: Record<string, AnnInfo[]>       // date -> 纪念日（公历/农历）
  hols?: Record<string, HolInfo>        // date -> 节假日
}>()
const emit = defineEmits<{ (e: 'pick', date: string): void }>()

const weekNames = ['一', '二', '三', '四', '五', '六', '日']
const ann = computed(() => props.ann || {})
const hols = computed(() => props.hols || {})

function pad(n: number) { return String(n).padStart(2, '0') }

const today = new Date()
const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`

const byDate = computed<Record<string, Entry[]>>(() => {
  const m: Record<string, Entry[]> = {}
  for (const it of props.items) (m[it.date] ||= []).push(it)
  return m
})

const weeks = computed(() => {
  const y = props.year
  const m = props.month
  const first = new Date(y, m - 1, 1)
  const daysIn = new Date(y, m, 0).getDate()
  const lead = (first.getDay() + 6) % 7 // 周一为首
  const cells: { key: string; date: string; day: number; inMonth: boolean; isToday: boolean; items: Entry[]; hasDdl: boolean }[] = []
  for (let i = 0; i < lead; i++) {
    cells.push({ key: `lead${i}`, date: '', day: 0, inMonth: false, isToday: false, items: [], hasDdl: false })
  }
  for (let d = 1; d <= daysIn; d++) {
    const date = `${y}-${pad(m)}-${pad(d)}`
    const items = byDate.value[date] || []
    cells.push({
      key: date, date, day: d, inMonth: true,
      isToday: date === todayStr,
      items,
      hasDdl: items.some((x) => x.type === 'ddl' && !x.done),
    })
  }
  while (cells.length % 7 !== 0) {
    cells.push({ key: `tail${cells.length}`, date: '', day: 0, inMonth: false, isToday: false, items: [], hasDdl: false })
  }
  const out = []
  for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7))
  return out
})
</script>

<style scoped>
.cm-head { display: grid; grid-template-columns: repeat(7, 1fr); margin-bottom: 4px; }
.cw { text-align: center; font-size: 12px; color: var(--txt2); padding: 4px 0; }
.cm-body { display: grid; gap: 4px; }
.cm-week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.day {
  min-height: 96px; border-radius: 10px; padding: 5px 6px; cursor: pointer;
  background: rgba(148, 163, 184, 0.05); border: 1px solid transparent;
  transition: background .12s, border-color .12s;
}
.day:hover { background: rgba(167, 139, 250, 0.12); border-color: rgba(167, 139, 250, 0.35); }
.day.dim { background: transparent; cursor: default; }
.day.today { border-color: var(--acc2); background: rgba(167, 139, 250, 0.07); }
.day.has-ddl { box-shadow: inset 0 -2px 0 #f43f5e; }
html.theme-dark .day { background: rgba(30, 41, 59, 0.3); }
html.theme-dark .day.dim { background: transparent; }

.dhead { display: flex; align-items: center; gap: 4px; margin-bottom: 3px; flex-wrap: wrap; }
.dnum { font-size: 13px; font-weight: 600; }
.today .dnum {
  width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
  background: var(--acc-grad); color: #fff; font-size: 12px;
}
.dtag { font-size: 9px; color: var(--acc2); }
.hol {
  font-size: 9px; border-radius: 4px; padding: 0 4px; line-height: 14px; color: #e11d48;
  background: rgba(244, 63, 94, 0.16); margin-left: auto; overflow: hidden; white-space: nowrap;
}
.hol.work { color: #374151; background: rgba(100, 116, 139, 0.24); }
html.theme-dark .hol { color: #fecdd3; background: rgba(244, 63, 94, 0.28); }
html.theme-dark .hol.work { color: #e5e7eb; background: rgba(148, 163, 184, 0.25); }
.ann {
  font-size: 9px; border-radius: 4px; padding: 0 5px; line-height: 14px;
  color: #fff; background: rgba(236, 72, 153, 0.85);
  overflow: hidden; white-space: nowrap; max-width: 74px; text-overflow: ellipsis;
}
.cells { display: grid; gap: 2px; }
.mini {
  font-size: 10.5px; line-height: 1.25; padding: 1px 4px; border-radius: 5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.m-task { background: rgba(167, 139, 250, 0.16); color: #8b5cf6; }
.m-ddl { background: rgba(244, 63, 94, 0.14); color: #e11d48; }
.m-event { background: rgba(14, 165, 233, 0.14); color: #0284c7; }
html.theme-dark .m-task { color: #c4b5fd; }
html.theme-dark .m-ddl { color: #fda4af; }
html.theme-dark .m-event { color: #7dd3fc; }
.mdone { text-decoration: line-through; opacity: 0.55; }
.mtime { opacity: 0.75; margin-right: 3px; }
.more { font-size: 10px; color: var(--txt2); padding: 1px 4px; }
</style>
