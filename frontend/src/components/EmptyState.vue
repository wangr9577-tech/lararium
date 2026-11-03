<template>
  <div class="glass empty-card">
    <div class="icon-circle"><el-icon :size="34"><component :is="iconMap[icon]" /></el-icon></div>
    <div class="title grad-text">{{ title }}</div>
    <div class="desc">{{ desc }}</div>
    <div v-if="features?.length" class="feats">
      <div v-for="f in features" :key="f" class="feat">
        <el-icon color="#8b5cf6"><CircleCheckFilled /></el-icon><span>{{ f }}</span>
      </div>
    </div>
    <div v-if="note" class="note">
      <el-icon :size="13"><InfoFilled /></el-icon>
      <span>{{ note }}</span>
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
import {
  ChatDotRound, Picture, Clock, CollectionTag, Calendar, Notebook,
  Reading, User, CircleCheckFilled, InfoFilled,
  type Component as IconComponent,
} from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{ icon: string; title: string; desc: string; features?: string[]; note?: string }>(),
  { features: () => [], note: '' },
)

const iconMap: Record<string, IconComponent> = {
  ChatDotRound, Picture, Clock, CollectionTag, Calendar, Notebook,
  Reading, User,
}
</script>

<style scoped>
.empty-card {
  padding: 32px 24px; text-align: center; max-width: 720px; margin: 24px auto;
}
.icon-circle {
  width: 70px; height: 70px; margin: 0 auto 14px; border-radius: 22px;
  display: grid; place-items: center; color: #fff;
  background: var(--acc-grad); box-shadow: 0 10px 24px rgba(139, 92, 246, 0.32);
  transform: rotate(-4deg);
}
.title { font-size: 20px; font-weight: 800; margin-bottom: 8px; }
.desc { color: var(--txt3); font-size: 13.5px; line-height: 1.7; margin: 0 auto 16px; max-width: 560px; }
html.theme-dark .desc { color: var(--txt2); }
.feats {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-bottom: 22px;
}
.feat {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px;
  border-radius: 999px; font-size: 13px; color: #475569;
  background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.18);
}
html.theme-dark .feat { color: #cbd5e1; }
.note { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--txt2); }
</style>
