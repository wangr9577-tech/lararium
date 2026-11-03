<template>
  <div class="entry" :class="`ty-${entry.type}`" :style="{ opacity: entry.done ? 0.55 : 1 }">
    <el-checkbox
      v-if="checkable && entry.type !== 'event'"
      :model-value="entry.done" size="small" class="chk"
      @change="(v: any) => emit('toggle', v)"
    />
    <span v-else class="ev-dot" />
    <div class="emain" @click="emit('edit', entry)">
      <div class="etop">
        <span v-if="entry.time_start" class="etime">{{ entry.time_start }}</span>
        <span class="etitle" :class="{ done: entry.done }">{{ entry.title }}</span>
        <span v-if="entry.type === 'ddl' && !entry.done" class="eddl">DDL</span>
      </div>
      <div v-if="entry.note" class="enote">{{ entry.note }}</div>
    </div>
    <el-tooltip content="编辑" placement="top">
      <el-button text circle size="small" class="op" @click="emit('edit', entry)">
        <el-icon><EditPen /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip content="删除" placement="top">
      <el-button text circle size="small" type="danger" class="op" @click="emit('del', entry)">
        <el-icon><Delete /></el-icon>
      </el-button>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { EditPen, Delete } from '@element-plus/icons-vue'

export interface Entry {
  id: number
  date: string
  kind: 'daily' | 'monthly'
  type: 'task' | 'ddl' | 'event'
  title: string
  time_start: string
  note: string
  done: boolean
}

const emit = defineEmits<{
  (e: 'toggle', done: boolean): void
  (e: 'edit', entry: Entry): void
  (e: 'del', entry: Entry): void
}>()

withDefaults(defineProps<{ entry: Entry; checkable?: boolean }>(), { checkable: true })
</script>

<style scoped>
.entry {
  display: flex; align-items: flex-start; gap: 6px; padding: 6px 10px;
  border-left: 3px solid var(--c); border-radius: 8px; font-size: 13px;
}
.ty-task { --c: #a78bfa; background: rgba(167, 139, 250, 0.08); }
.ty-ddl { --c: #f43f5e; background: rgba(244, 63, 94, 0.07); }
.ty-event { --c: #0ea5e9; background: rgba(14, 165, 233, 0.07); }
.chk { margin-top: 1px; }
.ev-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--c); margin: 4px 0 0 4px; flex: none; }
.emain { flex: 1; min-width: 0; cursor: pointer; }
.etop { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.etime { font-size: 11px; color: var(--c); font-weight: 600; font-variant-numeric: tabular-nums; }
.etitle { font-weight: 500; overflow: hidden; text-overflow: ellipsis; }
.etitle.done { text-decoration: line-through; color: var(--txt2); }
.eddl { font-size: 10px; background: #f43f5e; color: #fff; border-radius: 5px; padding: 0 5px; line-height: 15px; }
.enote {
  font-size: 11.5px; color: var(--txt2); margin-top: 2px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.op { opacity: 0; transition: opacity .12s; }
.entry:hover .op { opacity: 1; }
</style>
