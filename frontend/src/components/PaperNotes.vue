<template>
  <div class="paper-notes">
    <div class="notes-head">论文摘录笔记 <el-button size="small" text @click="load">刷新</el-button></div>
    <div v-if="loading">加载中…</div>
    <div v-else-if="error">加载失败，请点击刷新重试。</div>
    <div v-else-if="!notes.length">还没有关联笔记。可通过“导出为笔记”创建。</div>
    <a v-for="note in notes" :key="note.id" :href="`/notes/${encodeURIComponent(note.id)}`" target="_blank" rel="noopener" class="note-link">{{ note.title }}</a>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '../api/client'

const props = defineProps<{ paperId: string }>()
const notes = ref<{ id: string; title: string }[]>([])
const loading = ref(false)
const error = ref(false)
async function load() {
  loading.value = true
  error.value = false
  try {
    const result = await http.get<{ items: { id: string; title: string }[] }>(`/notes?tag=${encodeURIComponent(`paper:${props.paperId}`)}`)
    notes.value = result.items || []
  } catch { error.value = true }
  finally { loading.value = false }
}
onMounted(load)
</script>

<style scoped>
.paper-notes { padding-top: 10px; color: var(--txt2); font-size: 13px; }
.notes-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; }
.note-link { display: block; padding: 8px 0; overflow-wrap: anywhere; color: var(--el-color-primary); }
</style>
