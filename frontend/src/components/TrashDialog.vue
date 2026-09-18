<template>
  <el-dialog v-model="open" title="回收站" width="640px" append-to-body>
    <div class="trash-tip">删除的笔记 / 相册 / 论文 / 日记先进回收站（随数据加密存储），可随时恢复；「永久删除」后不可恢复。</div>
    <el-empty v-if="!items.length && !loading" description="回收站是空的" :image-size="64" />
    <div v-loading="loading" class="tlist">
      <div v-for="it in items" :key="it.tid" class="titem">
        <div class="tmain">
          <div class="tlabel">{{ it.label || '(未命名)' }}</div>
          <div class="tmeta">{{ MODULE_NAMES[it.module] || it.module }} · 删除于 {{ it.deleted_at }} · {{ it.count }} 个文件</div>
        </div>
        <div class="tops">
          <el-button size="small" :disabled="it.broken" @click="restore(it)">恢复</el-button>
          <el-button size="small" type="danger" plain :disabled="it.broken" @click="purge(it)">永久删除</el-button>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="open = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, http } from '../api/client'

const MODULE_NAMES: Record<string, string> = { note: '笔记', album: '相册', paper: '论文', diary: '日记' }

interface TrashItem {
  tid: string
  module: string
  label: string
  deleted_at: string
  count: number
  broken?: boolean
}

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'restored'): void }>()

const open = ref(props.modelValue)
watch(() => props.modelValue, (v) => { open.value = v })
watch(open, (v) => { emit('update:modelValue', v); if (v) load() })

const items = ref<TrashItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = (await http.get<{ items: TrashItem[] }>('/trash')).items
  } catch (e: unknown) {
    ElMessage.error(errMsg(e, '读取回收站失败'))
  } finally {
    loading.value = false
  }
}

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return d || fallback
}

async function restore(it: TrashItem) {
  try {
    const r = await http.post<{ restored: number }>(`/trash/${it.tid}/restore`)
    ElMessage.success(`已恢复（${r.restored} 个文件回到原位置）`)
    await load()
    emit('restored')
  } catch (e: unknown) {
    ElMessage.error(errMsg(e, '恢复失败'))
  }
}

async function purge(it: TrashItem) {
  try {
    await ElMessageBox.confirm(
      `「${it.label}」将从磁盘彻底删除，此操作不可恢复。确定吗？`,
      '永久删除', { type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await api.delete(`/trash/${it.tid}`, { params: { yes: true } })
    ElMessage.success('已永久删除')
    await load()
  } catch (e: unknown) {
    ElMessage.error(errMsg(e, '删除失败'))
  }
}
</script>

<style scoped>
.trash-tip { font-size: 12.5px; color: var(--el-text-color-secondary); margin-bottom: 10px; line-height: 1.7; }
.tlist { max-height: 46vh; overflow: auto; min-height: 60px; }
.titem { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 2px; border-bottom: 1px solid var(--el-border-color-lighter); }
.titem:last-child { border-bottom: none; }
.tlabel { font-size: 14px; font-weight: 600; word-break: break-all; }
.tmeta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.tops { flex-shrink: 0; }
</style>
