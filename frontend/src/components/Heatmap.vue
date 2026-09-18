<template>
  <div class="hm">
    <div class="hm-head">
      <span class="hm-title">{{ title }}</span>
      <span class="hm-badge">{{ year }}</span>
      <span v-if="tip" class="hm-tip">{{ tip }}</span>
    </div>
    <div class="hm-body">
      <div class="hm-weeks" v-if="weeks.length">
        <div class="hm-col wk" v-for="w in weeks" :key="w.key">
          <div
            v-for="c in w.cells"
            :key="c.key"
            class="cell"
            :class="c.lv === null ? 'blank' : `lv${c.lv}`"
            :title="c.title"
          />
        </div>
      </div>
    </div>
    <div class="hm-foot">
      <span class="legend">少</span>
      <span v-for="i in 5" :key="i" class="cell lg" :class="`lv${i - 1}`" />
      <span class="legend">多</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Cell { key: string; lv: number | null; title: string }
interface Week { key: string; cells: Cell[] }

const props = withDefaults(
  defineProps<{
    year?: number
    data?: Record<string, number>
    mode?: 'percent' | 'minutes'
    demo?: boolean
    title?: string
    tip?: string
  }>(),
  { year: new Date().getFullYear(), data: () => ({}), mode: 'percent', demo: true, title: '年度热力图', tip: '' },
)

function demoPercent(dayOfYear: number): number {
  const seed = Math.sin(props.year * 7919 + dayOfYear * 104729) * 10000
  return Math.abs(Math.floor(seed)) % 100
}

function levelOf(value: number | undefined): number {
  if (props.mode === 'minutes') {
    const m = value ?? 0
    if (m <= 0) return 0
    if (m < 30) return 1
    if (m < 60) return 2
    if (m < 120) return 3
    return 4
  }
  const p = value ?? 0
  if (p <= 0) return 0
  if (p < 35) return 1
  if (p < 60) return 2
  if (p < 85) return 3
  return 4
}

const weeks = computed<Week[]>(() => {
  const isLeap = (props.year % 4 === 0 && props.year % 100 !== 0) || props.year % 400 === 0
  const totalDays = isLeap ? 366 : 365
  const firstDow = (new Date(props.year, 0, 1).getDay() + 6) % 7 // 周一=0
  const cols = Math.ceil((firstDow + totalDays) / 7)
  const out: Week[] = []
  for (let w = 0; w < cols; w++) {
    const cells: Cell[] = []
    for (let d = 0; d < 7; d++) {
      const doy = w * 7 + d - firstDow + 1
      if (doy < 1 || doy > totalDays) {
        cells.push({ key: `w${w}d${d}`, lv: null, title: '' })
        continue
      }
      const dt = new Date(props.year, 0, doy)
      const iso = `${props.year}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
      let value: number | undefined
      if (props.data && props.data[iso] !== undefined) value = props.data[iso]
      else if (props.demo && props.mode === 'percent') value = demoPercent(doy)
      else value = 0
      const suffix = props.mode === 'minutes' ? `专注 ${value} 分钟` : `完成度 ${value}%`
      cells.push({ key: iso, lv: levelOf(value), title: `${iso} · ${suffix}` })
    }
    out.push({ key: `w${w}`, cells })
  }
  return out
})
</script>

<style scoped>
.hm { padding: 6px 4px; }
.hm-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.hm-title { font-size: 15px; font-weight: 700; }
.hm-badge { font-size: 12px; color: #fff; background: var(--acc-grad); border-radius: 8px; padding: 1px 8px; }
.hm-tip { margin-left: auto; font-size: 12px; color: var(--txt2); }
.hm-body { overflow-x: auto; }
.hm-weeks { display: flex; gap: 3px; width: max-content; }
.hm-col { display: flex; flex-direction: column; gap: 3px; }
.cell { width: 11px; height: 11px; border-radius: 3px; }
.cell.blank { background: transparent; }
.lv0 { background: #f1f5f9; }
html.theme-dark .lv0 { background: #1e293b; }
.lv1 { background: #fbcfe8; }
.lv2 { background: #f0abfc; }
.lv3 { background: #d8b4fe; }
.lv4 { background: #a78bfa; }
.hm-foot { display: flex; align-items: center; gap: 4px; margin-top: 12px; justify-content: flex-end; }
.legend { font-size: 11px; color: var(--txt2); margin: 0 4px; }
.cell.lg { width: 11px; height: 11px; border-radius: 3px; }
</style>
