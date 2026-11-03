<template>
  <div class="lab-wrap">
    <!-- 工作台导航条：工作台主体（首页/事项详情）+ 仍在下游的资料入口。
         日程表照旧由用户自己填写 DDL 与重要节点，工作台不自动识别日期或同步任务。 -->
    <div class="lab-tabs glass">
      <router-link to="/lab" class="lab-tab" :class="{ on: isHome }">
        <el-icon :size="15"><Grid /></el-icon>
        <span>工作台</span>
      </router-link>
      <span class="lab-sep" />
      <span class="lab-hint">资料在</span>
      <router-link to="/notes" class="lab-tab">
        <el-icon :size="15"><Notebook /></el-icon>
        <span>笔记·博客</span>
      </router-link>
      <router-link to="/papers" class="lab-tab">
        <el-icon :size="15"><Reading /></el-icon>
        <span>论文阅读</span>
      </router-link>
      <router-link to="/schedule" class="lab-tab">
        <el-icon :size="15"><Memo /></el-icon>
        <span>日程表</span>
      </router-link>
    </div>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Grid, Memo, Notebook, Reading } from '@element-plus/icons-vue'

const route = useRoute()
/** 首页（/lab）高亮；事项详情 /lab/items/:id 也属于工作台主体，仍让「工作台」保持选中 */
const isHome = computed(() => route.path === '/lab' || route.path.startsWith('/lab/items/'))
</script>

<style scoped>
.lab-tabs {
  position: sticky; top: 0; z-index: 10;
  display: flex; gap: 6px; overflow-x: auto; align-items: center;
  max-width: 1200px; margin: 0 auto;
  padding: 14px 26px 10px;
  scrollbar-width: none;
}
.lab-tabs::-webkit-scrollbar { display: none; }

.lab-tab {
  flex: none;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 999px;
  font-size: 13px; color: var(--txt2);
  border: 1px solid rgba(148, 163, 184, 0.25);
  transition: all .15s;
}
html.theme-dark .lab-tab { color: #cbd5e1; }
.lab-tab:hover { background: rgba(167, 139, 250, 0.12); }
.lab-tab.on {
  background: var(--acc-grad); color: #fff; font-weight: 600; border-color: transparent;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.35);
}
.lab-sep {
  flex: none; width: 1px; height: 18px; margin: 0 4px;
  background: rgba(148, 163, 184, 0.3);
}
.lab-hint {
  flex: none; font-size: 12px; color: var(--txt3); padding: 0 2px;
}
html.theme-dark .lab-hint { color: var(--txt2); }
</style>