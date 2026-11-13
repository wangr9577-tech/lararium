<template>
  <el-button v-if="count" class="conflict-button" type="warning" @click="open = true">{{ count }} 项旧数据待核对</el-button>
  <el-dialog v-model="open" title="核对旧浏览器数据" width="min(900px, 94vw)" :close-on-click-modal="false">
    <p>这些旧值与服务端不同。当前页面使用服务端值；请选择保留哪一份。备份文件包含两份数据，请妥善保存。</p>
    <el-button type="primary" @click="backup">下载全部冲突的备份</el-button>
    <el-button type="warning" :disabled="busy" @click="resolveAllServer">全部保留服务端值</el-button>
    <p v-if="!backedUp">请先下载备份，再逐项处理。</p>
    <div v-for="(item, key) in legacyConflicts" :key="key" class="conflict">
      <strong>{{ key }}</strong>
      <div class="values">
        <div><b>浏览器旧值</b><pre>{{ format(item.local) }}</pre></div>
        <div><b>服务端当前值</b><pre>{{ format(item.server.value) }}</pre></div>
      </div>
      <el-button :disabled="!backedUp || busy" @click="resolve(String(key), 'server')">保留服务端值</el-button>
      <el-button :disabled="!backedUp || busy" type="warning" @click="resolve(String(key), 'local')">用浏览器旧值覆盖服务端</el-button>
    </div>
    <p v-if="!count">所有冲突已处理，刷新页面后可看到所选数据。</p>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { legacyConflicts, resolveLegacyConflict } from '../api/clientState'

const count = computed(() => Object.keys(legacyConflicts).length)
const open = ref(count.value > 0)
const backedUp = ref(false)
const busy = ref(false)
function format(value: string) {
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}
function backup() {
  const blob = new Blob([JSON.stringify({ exportedAt: new Date().toISOString(), conflicts: legacyConflicts }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `kruskal-conflicts-${Date.now()}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  backedUp.value = true
}
async function resolve(key: string, choice: 'local' | 'server') {
  try {
    await ElMessageBox.confirm(choice === 'local' ? '将用浏览器旧值覆盖服务端值，确定继续？' : '将保留服务端值并移除浏览器中的旧值，确定继续？', '确认处理', { type: 'warning' })
  } catch { return }
  busy.value = true
  try {
    await resolveLegacyConflict(key, choice)
    ElMessage.success('已处理。完成全部核对后请刷新页面。')
  } catch (error: any) {
    backedUp.value = false
    ElMessage.error(error?.response?.status === 409 ? '服务端数据已变化，请刷新后重新备份和核对。' : (error?.message || '处理失败，旧值仍保留在浏览器中。'))
  } finally { busy.value = false }
}
async function resolveAllServer() {
  try {
    await ElMessageBox.confirm('将先下载备份，再保留所有服务端值并移除对应的浏览器旧值。确定继续？', '确认处理全部冲突', { type: 'warning' })
  } catch { return }
  backup()
  busy.value = true
  let resolved = 0
  const errors: string[] = []
  try {
    for (const key of Object.keys(legacyConflicts)) {
      try { await resolveLegacyConflict(key, 'server'); resolved++ }
      catch { errors.push(key) }
    }
    if (errors.length) {
      backedUp.value = false
      ElMessage.warning({ message: `已处理 ${resolved} 项，${errors.length} 项发生变化或处理失败，请重新备份并核对。`, duration: 0, showClose: true })
    } else ElMessage.success(`已处理 ${resolved} 项，请刷新页面。`)
  } finally { busy.value = false }
}
</script>

<style scoped>
.conflict-button { position: fixed; right: 20px; bottom: 20px; z-index: 100; }
.conflict { border-top: 1px solid #ddd; margin-top: 20px; padding-top: 16px; overflow-wrap: anywhere; }
.values { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin: 10px 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; background: #f6f6f6; padding: 10px; }
</style>
