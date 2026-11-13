<template>
  <div class="fp-wrap">
    <div ref="el" class="fp" />
    <div v-if="!data.length" class="fp-empty">这段时间还没有专注记录</div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { pieColor } from '../utils/chartColors'

const props = defineProps<{ data: { name: string; minutes: number }[] }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null
let mo: MutationObserver | null = null

/** 画布不认 CSS 变量，取当前主题的色值；切主题时重建 option */
function cssVar(name: string, fallback: string) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function buildOption() {
  const txt2 = cssVar('--txt2', '#4a5668')
  const dark = document.documentElement.classList.contains('theme-dark')
  const total = props.data.reduce((a, d) => a + d.minutes, 0)
  const days = props.data.length ? props.data : [{ name: '', minutes: 0 }]

  return {
    color: props.data.map((_, i) => pieColor(i)),
    title: {
      text: String(total),
      subtext: '分钟',
      left: 'center',
      top: '35%',
      textStyle: { color: cssVar('--acc2', '#8b5cf6'), fontSize: 24, fontWeight: 700 },
      subtextStyle: { color: txt2, fontSize: 12 },
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: dark ? 'rgba(15,23,42,.9)' : 'rgba(38,48,60,.92)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (p: any) => `${p.name}<br/>专注 <b>${p.value}</b> 分钟 · <b>${p.percent}%</b>`,
    },
    series: [{
      type: 'pie',
      radius: ['50%', '72%'],
      center: ['50%', '46%'],
      minAngle: props.data.length > 1 ? 6 : 0,
      avoidLabelOverlap: true,
      itemStyle: {
        borderColor: dark ? 'rgba(24,32,48,.9)' : 'rgba(255,255,255,.92)',
        borderWidth: 2,
        borderRadius: 6,
      },
      label: {
        color: txt2,
        fontSize: 11,
        // 名字长的扇区只标占比，避免标签互相压在一起
        formatter: (p: any) => (p.percent >= 6 ? `${p.name.length > 8 ? p.name.slice(0, 8) + '…' : p.name}\n${p.percent}%` : ''),
        lineHeight: 15,
      },
      labelLine: { length: 8, length2: 8, lineStyle: { color: 'rgba(148,163,184,.55)' } },
      emphasis: { scale: true, scaleSize: 4 },
      data: days.map((d) => ({ name: d.name || '未命名', value: d.minutes })),
    }],
  }
}

function render() {
  if (!el.value) return
  if (!chart) {
    chart = echarts.init(el.value)
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el.value)
  }
  chart.setOption(buildOption(), true)
}

onMounted(() => {
  render()
  mo = new MutationObserver(() => render())
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  mo?.disconnect()
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.fp-wrap { position: relative; }
.fp { width: 100%; height: 260px; }
.fp-empty { position: absolute; inset: 0; display: grid; place-content: center; color: var(--txt2); font-size: 12px; line-height: 20px; }
</style>
