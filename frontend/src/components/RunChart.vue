<template>
  <div class="chart-box">
    <div v-for="(g, i) in groups" :key="i" class="chart-wrap">
      <div class="chart-title">{{ g.metric }}</div>
      <div :ref="(x: any) => setRef(i, x)" class="chart"></div>
    </div>
    <p v-if="!groups.length" class="hint">暂无指标数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  series: { name: string; metric: string; data: [number, number][] }[]
  title?: string
}>()

const els = ref<(HTMLDivElement | null)[]>([])
const charts: echarts.ECharts[] = []

function setRef(i: number, el: HTMLDivElement | null) {
  els.value[i] = el
}

const groups = computed(() => {
  const map = new Map<string, { name: string; metric: string; data: [number, number][] }[]>()
  for (const s of props.series) {
    if (!map.has(s.metric)) map.set(s.metric, [])
    map.get(s.metric)!.push(s)
  }
  return Array.from(map.entries()).map(([metric, series]) => ({ metric, series }))
})

function render() {
  charts.forEach((c) => c.dispose())
  charts.length = 0
  groups.value.forEach((g, i) => {
    const el = els.value[i]
    if (!el) return
    const chart = echarts.init(el)
    charts.push(chart)
    // 步号排序（字符串键转数字）
    const option = {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: g.series.map((s) => s.name), top: 2 },
      grid: { left: 52, right: 20, top: 30, bottom: 40 },
      xAxis: { type: 'category', name: 'step' },
      yAxis: { type: 'value' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }],
      series: g.series.map((s) => ({ name: s.name, type: 'line' as const, smooth: true, showSymbol: false, data: s.data })),
    }
    chart.setOption(option)
  })
}

watch(groups, () => { requestAnimationFrame(render) }, { deep: true })

function onResize() { charts.forEach((c) => c.resize()) }

onMounted(() => {
  requestAnimationFrame(render)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  charts.forEach((c) => c.dispose())
  charts.length = 0
})
</script>

<style scoped>
.chart-box { display: grid; gap: 18px; width: 100%; }
.chart-wrap { width: 100%; }
.chart-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; color: var(--txt2); }
.chart { width: 100%; height: 300px; }
.hint { color: var(--txt2); font-size: 12.5px; }
</style>