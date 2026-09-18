<template>
  <el-dialog :model-value="modelValue" :title="`目录管理${module === 'ielts' ? '（雅思）' : ''}`" width="470px" @update:model-value="emit('update:modelValue', $event)" @open="load">
    <div class="fd-new">
      <el-input v-model="newName" placeholder="输入新目录名，回车创建（顶层）" size="small" @keyup.enter="create" />
      <el-button type="primary" size="small" :disabled="!newName.trim()" @click="create">新建</el-button>
    </div>
    <div class="fd-list">
      <div v-for="row in dirRows" :key="dirPath(row.f)" class="fd-row" :style="{ marginLeft: row.depth * 14 + 'px' }">
        <span v-if="row.hasKids" class="fd-caret" title="展开/收起" @click="toggleDir(dirPath(row.f))">{{ collapsed[dirPath(row.f)] ? '▸' : '▾' }}</span>
        <span class="fd-name" :title="dirLabel(row.f)">{{ row.f.name }}</span>
        <span class="fd-cnt" title="含子目录内的笔记">{{ row.f.count }}</span>
        <el-button v-if="row.depth < 2" text size="small" @click="addSub(row.f)">子目录</el-button>
        <el-button text size="small" @click="rename(row.f)">改名</el-button>
        <el-button text size="small" type="danger" @click="del(row.f)">删除</el-button>
      </div>
      <div v-if="!items.length" class="fd-empty">还没有目录，先新建一个</div>
    </div>
    <p class="fd-tip">删除目录会连同其子目录一起删除，笔记不删，全部回到「未分类」。</p>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '../api/client'

const props = defineProps<{ modelValue: boolean; module?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'changed'): void }>()
const module = props.module || ''

/** 目录：path=自身全路径（顶层=名字），parent=父目录全路径（''=顶层） */
interface DirItem { name: string; path?: string; parent?: string; count: number }

const items = ref<DirItem[]>([])
const newName = ref('')

/** 目录全路径（兼容：后端尚未返回 path 时回落到 name，即原顶层行为） */
function dirPath(f: DirItem): string {
  return f.path || f.name
}
/** 层级展示名：顶层=自身名；子级=「父路径 / 名」 */
function dirLabel(f: DirItem): string {
  return f.parent ? `${f.parent} / ${f.name}` : f.name
}
function groupByParent(list: DirItem[]): Map<string, DirItem[]> {
  const m = new Map<string, DirItem[]>()
  for (const f of list) {
    const p = f.parent || ''
    const arr = m.get(p)
    if (arr) arr.push(f)
    else m.set(p, [f])
  }
  return m
}
/** 子目录展开态：默认全部展开，仅显式收起为 false */
const collapsed = ref<Record<string, boolean>>({})
function toggleDir(p: string) {
  collapsed.value = { ...collapsed.value, [p]: !collapsed.value[p] }
}
interface DirRow { f: DirItem; depth: number; hasKids: boolean }
/** 目录行（按树序拍平：父先子后；收起的节点隐藏其子级） */
const dirRows = computed<DirRow[]>(() => {
  const byParent = groupByParent(items.value)
  const rows: DirRow[] = []
  const walk = (parent: string, depth: number) => {
    for (const f of byParent.get(parent) || []) {
      const kids = byParent.get(dirPath(f))
      const hasKids = !!(kids && kids.length)
      rows.push({ f, depth, hasKids })
      if (hasKids && !collapsed.value[dirPath(f)]) walk(dirPath(f), depth + 1)
    }
  }
  walk('', 0)
  return rows
})

async function load() {
  try {
    const r = await http.get<{ items: DirItem[] }>(`/notes/folders?module=${encodeURIComponent(module)}`)
    items.value = r.items
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '目录加载失败')
  }
}

/** 新建顶层目录 */
async function create() {
  const name = newName.value.trim()
  if (!name) return
  try {
    await http.post('/notes/folders', { module, name })
    newName.value = ''
    ElMessage.success('已创建')
    await load()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

/** 新建子目录：parent=目标目录全路径 */
async function addSub(f: DirItem) {
  const p = dirPath(f)
  let name = ''
  try {
    const r = await ElMessageBox.prompt('新子目录名：', `在「${dirLabel(f)}」下新建子目录`, {
      confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    name = (r.value || '').trim()
  } catch { return }
  try {
    await http.post('/notes/folders', { module, name, parent: p })
    collapsed.value = { ...collapsed.value, [p]: false } // 确保父目录展开
    ElMessage.success('已创建')
    await load()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

async function rename(f: DirItem) {
  let next = ''
  try {
    const r = await ElMessageBox.prompt(`把目录「${dirLabel(f)}」改名为：`, '重命名目录', {
      confirmButtonText: '确定', cancelButtonText: '取消', inputValue: f.name, inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    next = (r.value || '').trim()
  } catch { return }
  if (!next || next === f.name) return
  try {
    // name 为旧参数（顶层时与 path 相同），path 为新参数，双发兼容新旧后端
    await http.put('/notes/folders', { module, name: f.name, path: dirPath(f), new_name: next })
    ElMessage.success('已改名')
    await load()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '改名失败')
  }
}

async function del(f: DirItem) {
  try {
    await ElMessageBox.confirm(
      `删除目录「${dirLabel(f)}」？其下子目录会一并删除，笔记不删，全部回到「未分类」。`,
      '确认删除', { type: 'warning' },
    )
  } catch { return }
  try {
    const p = dirPath(f)
    const r = await http.del<{ moved_to_root?: number }>(
      `/notes/folders?module=${encodeURIComponent(module)}&name=${encodeURIComponent(f.name)}&path=${encodeURIComponent(p)}`,
    )
    ElMessage.success(r.moved_to_root ? `已删除，${r.moved_to_root} 篇笔记已回到未分类` : '已删除')
    await load()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}
</script>

<style scoped>
.fd-new { display: flex; gap: 8px; margin-bottom: 12px; }
.fd-list { display: grid; gap: 4px; max-height: 40vh; overflow: auto; }
.fd-row {
  display: flex; align-items: center; gap: 6px; padding: 4px 8px;
  border-radius: 8px; border: 1px solid rgba(148, 163, 184, 0.14);
}
.fd-caret { flex: none; width: 12px; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; color: var(--txt3); cursor: pointer; }
html.theme-dark .fd-caret { color: #94a3b8; }
.fd-name { flex: 1; min-width: 0; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fd-cnt { flex: none; font-size: 11px; color: var(--txt3); background: rgba(148, 163, 184, 0.16); border-radius: 999px; padding: 0 7px; }
html.theme-dark .fd-cnt { color: var(--txt2); }
.fd-empty { color: var(--txt2); font-size: 12.5px; text-align: center; padding: 16px 0; }
.fd-tip { color: var(--txt3); font-size: 11.5px; margin: 10px 0 0; }
html.theme-dark .fd-tip { color: var(--txt2); }
</style>
