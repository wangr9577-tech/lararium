<template>
  <div ref="el" class="fc" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{ data: { date: string; minutes: number }[] }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function buildOption() {
  const days = props.data.length ? props.data : [{ date: '', minutes: 0 }]
  return {
    grid: { left: 44, right: 14, top: 26, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15,23,42,.85)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (ps: any) => {
        const p = ps[0]
        return `${p.axisValue}<br/>专注 <b>${p.value}</b> 分钟`
      },
    },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.date.slice(5)), // MM-DD
      axisLine: { lineStyle: { color: 'var(--txt2)' } },
      axisLabel: { color: 'var(--txt2)', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '分钟',
      nameTextStyle: { color: 'var(--txt2)', fontSize: 11 },
      axisLabel: { color: 'var(--txt2)', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.18)' } },
    },
    series: [{
      type: 'bar',
      data: days.map((d) => d.minutes),
      barWidth: '52%',
      itemStyle: {
        borderRadius: [7, 7, 0, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#a78bfa' },
          { offset: 1, color: '#f0abfc' },
        ]),
      },
    }],
  }
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.setOption(buildOption())
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value)
})

watch(
  () => props.data,
  () => chart?.setOption(buildOption(), true),
  { deep: true },
)

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.fc { width: 100%; height: 260px; }
</style>
