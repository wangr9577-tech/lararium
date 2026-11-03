<template>
  <div class="ft">
    <el-tree
      ref="treeRef"
      :key="sid"
      lazy
      node-key="path"
      :props="treeProps"
      :load="loadNode"
      :expand-on-click-node="false"
      :indent="12"
      highlight-current
      @node-click="onClick"
    >
      <template #default="{ data }">
        <span class="ft-row" :class="{ dir: data.isDir }" :title="data.tip || data.path">
          <el-icon class="ft-ico">
            <Folder v-if="data.isDir" />
            <Document v-else />
          </el-icon>
          <span class="ft-name">{{ data.label }}</span>
          <span v-if="!data.isDir" class="ft-size">{{ fmtSize(data.size || 0) }}</span>
        </span>
      </template>
    </el-tree>
  </div>
</template>

<script setup lang="ts">
/**
 * 文档源目录树：懒加载（点开一层拉一层），只出现目录与 md 文件。
 * 目录点击 → 右侧列出该目录内容；文件点击 → 打开阅读页。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Folder } from '@element-plus/icons-vue'
import { fmtSize, fsApi } from '../api/fs'

const props = defineProps<{ sid: string }>()
const emit = defineEmits<{ (e: 'pick', path: string): void; (e: 'open-dir', path: string): void }>()

interface TreeNode {
  path: string
  label: string
  tip: string
  isDir: boolean
  leaf?: boolean
  size?: number
}

const treeRef = ref()
const treeProps = { label: 'label', isLeaf: 'leaf' }
let warned = false

async function fetchNodes(path: string): Promise<TreeNode[]> {
  const r = await fsApi.tree(props.sid, path)
  const dirs: TreeNode[] = r.dirs.map((d) => ({ path: d.path, label: d.name, tip: d.path, isDir: true, leaf: false }))
  const files: TreeNode[] = r.files.map((f) => ({
    path: f.path,
    // 树上显示文件名（与项目里、agent 看到的一致），完整标题放 tooltip
    label: f.name.replace(/\.(md|markdown)$/i, ''),
    tip: `${f.title} · ${f.mtime}`,
    isDir: false,
    leaf: true,
    size: f.size,
  }))
  if (r.truncated) ElMessage.warning('这个目录条目太多，只显示了前 200 项，请用搜索定位')
  return [...dirs, ...files]
}

async function loadNode(node: any, resolve: (data: TreeNode[]) => void) {
  const path: string = node.level === 0 ? '' : (node.data?.path || '')
  if (node.level > 0 && !node.data?.isDir) { resolve([]); return }
  try {
    resolve(await fetchNodes(path))
  } catch (e: any) {
    resolve([])
    if (!warned) {
      warned = true
      ElMessage.error(e?.response?.data?.detail || '目录读取失败')
    }
  }
}

function onClick(data: TreeNode, node: any) {
  if (data.isDir) {
    emit('open-dir', data.path)
    try { node.expand() } catch { /* 忽略 */ }
    return
  }
  emit('pick', data.path)
}
</script>

<style scoped>
.ft { padding: 4px 2px 10px; }
.ft-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.ft-ico { color: var(--acc2); flex: none; }
.ft-row.dir .ft-ico { color: #f59e0b; }
.ft-name {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 13px; color: var(--txt3);
}
.ft-row.dir .ft-name { font-weight: 600; }
.ft-size { margin-left: auto; font-size: 11px; color: var(--txt2); opacity: 0.7; flex: none; }
:deep(.el-tree-node__content) { height: 28px; border-radius: 8px; }
:deep(.el-tree-node.is-current > .el-tree-node__content) { background: rgba(139, 92, 246, 0.16); }
</style>