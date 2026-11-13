<template>
  <div class="bg-layer" :style="{ backgroundImage: `url(${bgUrl})` }" aria-hidden="true"></div>
  <AppShell />
  <LegacyStateConflicts />
</template>

<script setup lang="ts">
import AppShell from './layout/AppShell.vue'
import bgUrl from './assets/background.jpg'
import LegacyStateConflicts from './components/LegacyStateConflicts.vue'
</script>

<style scoped>
/* 全站背景：暗黑主题用二次元图，明亮主题用纯渐变底 */
.bg-layer {
  position: fixed;
  inset: 0;
  z-index: -1;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}
html:not(.theme-dark) .bg-layer { display: none; }
html.theme-dark .bg-layer::after {
  content: '';
  position: absolute;
  inset: 0;
  /* 轻压暗保文字可读：中央尽量保留原图色彩，四边渐入深底 */
  background:
    radial-gradient(150% 110% at 50% 20%, transparent 40%, rgba(3, 6, 20, 0.62) 100%),
    linear-gradient(rgba(3, 6, 20, 0.22), rgba(3, 6, 20, 0.3));
}
</style>
