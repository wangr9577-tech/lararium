<template>
  <div class="asset-manager">
    <!-- 头部操作与说明 -->
    <div class="am-header">
      <div class="am-intro">
        <div class="am-title">
          <el-icon class="title-ico"><Files /></el-icon>
          <span>存储与附件管理 (Asset Garbage Collector)</span>
          <el-tag v-if="!scanning && scanData" :type="scanData.unreferenced_count === 0 ? 'success' : 'warning'" size="small" effect="plain" round>
            {{ scanData.unreferenced_count === 0 ? '体检健康 100%' : `发现 ${scanData.unreferenced_count} 个孤立文件` }}
          </el-tag>
        </div>
        <div class="am-desc">
          借鉴 Blossom 资产追踪与安全垃圾回收机制：精准扫描 <code>uploads/</code>、<code>album/</code> 与 <code>images/</code>，比对笔记、日记、白板、工作台及卡片引用，安全清理孤立文件。
        </div>
      </div>
      <div class="am-actions">
        <el-button :loading="scanning" :icon="Refresh" @click="runScan">
          {{ scanning ? '体检扫描中…' : '全面体检扫描' }}
        </el-button>
        <el-button
          type="danger"
          plain
          :disabled="!scanData || scanData.unreferenced_count === 0 || scanning || cleaning"
          :loading="cleaning && cleanTarget === 'all'"
          :icon="Delete"
          @click="confirmCleanAll"
        >
          一键清理孤立附件
        </el-button>
      </div>
    </div>

    <!-- 概览指标卡片网格 -->
    <div class="metric-grid">
      <div class="metric-card glass">
        <div class="mc-icon primary"><el-icon><Files /></el-icon></div>
        <div class="mc-info">
          <div class="mc-label">附件总数</div>
          <div class="mc-val">{{ scanData?.total_files ?? '—' }} <span class="mc-unit">个</span></div>
        </div>
      </div>

      <div class="metric-card glass">
        <div class="mc-icon info"><el-icon><Coin /></el-icon></div>
        <div class="mc-info">
          <div class="mc-label">存储占用总计</div>
          <div class="mc-val">{{ scanData?.total_size_human ?? '—' }}</div>
        </div>
      </div>

      <div class="metric-card glass" :class="{ 'has-warning': (scanData?.unreferenced_count || 0) > 0 }">
        <div class="mc-icon" :class="(scanData?.unreferenced_count || 0) > 0 ? 'warning' : 'success'">
          <el-icon><Warning v-if="(scanData?.unreferenced_count || 0) > 0" /><Check v-else /></el-icon>
        </div>
        <div class="mc-info">
          <div class="mc-label">孤立未引用文件</div>
          <div class="mc-val">{{ scanData?.unreferenced_count ?? '—' }} <span class="mc-unit">个</span></div>
        </div>
      </div>

      <div class="metric-card glass">
        <div class="mc-icon accent"><el-icon><Delete /></el-icon></div>
        <div class="mc-info">
          <div class="mc-label">潜在可释放空间</div>
          <div class="mc-val">{{ scanData?.unreferenced_size_human ?? '0 B' }}</div>
        </div>
      </div>
    </div>

    <!-- 扫描时间与安全提示 -->
    <div v-if="lastScanTime" class="scan-meta-bar">
      <span class="meta-time">上次体检时间：{{ lastScanTime }}</span>
      <span class="meta-tip">
        <el-icon style="vertical-align: middle; margin-right: 3px;"><Check /></el-icon>
        安全机制：清理操作默认将文件移至系统回收站 (<code>data/trash</code>)，保留元数据，可随时完整还原。
      </span>
    </div>

    <!-- 资产明细 Tab 页 -->
    <div class="am-body glass">
      <el-tabs v-model="activeTab" class="custom-tabs">
        <!-- Tab 1: 孤立未引用文件 -->
        <el-tab-pane name="unreferenced">
          <template #label>
            <span class="tab-label">
              <span>孤立未引用附件</span>
              <el-badge
                v-if="scanData?.unreferenced_count"
                :value="scanData.unreferenced_count"
                class="tab-badge"
                type="warning"
              />
            </span>
          </template>

          <!-- 批量操作与搜索栏 -->
          <div class="tab-toolbar">
            <div class="tool-left">
              <el-input
                v-model="unrefSearch"
                placeholder="按文件名或路径过滤…"
                clearable
                :prefix-icon="Search"
                class="search-input"
              />
              <el-button
                v-if="selectedUnref.length"
                type="danger"
                size="small"
                plain
                :loading="cleaning && cleanTarget === 'selected'"
                :icon="Delete"
                @click="confirmCleanSelected"
              >
                清理选中项 ({{ selectedUnref.length }})
              </el-button>
            </div>
            <div class="tool-right">
              <span class="tool-count">显示 {{ filteredUnreferenced.length }} / 共 {{ scanData?.unreferenced_count || 0 }} 项</span>
            </div>
          </div>

          <!-- 孤立文件数据表格 -->
          <el-table
            v-if="filteredUnreferenced.length"
            ref="unrefTableRef"
            :data="filteredUnreferenced"
            style="width: 100%"
            class="asset-table"
            row-key="path"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="48" align="center" />

            <el-table-column label="预览" width="80" align="center">
              <template #default="{ row }">
                <div class="thumb-cell" @click="handlePreview(row)">
                  <img
                    v-if="row.is_image && thumbUrls[row.path]"
                    :src="thumbUrls[row.path]"
                    class="thumb-img"
                    alt="缩略图"
                    loading="lazy"
                  />
                  <div v-else-if="row.is_image" class="thumb-placeholder" :title="row.filename">
                    <el-icon class="thumb-loading"><Picture /></el-icon>
                  </div>
                  <div v-else class="file-icon-box" :class="getFileExtClass(row.filename)">
                    <span>{{ getFileExt(row.filename) }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="文件名 / 存储路径" min-width="260">
              <template #default="{ row }">
                <div class="file-main-cell">
                  <div class="file-name-row">
                    <span class="file-name" :title="row.filename">{{ row.filename }}</span>
                    <el-tag size="small" effect="plain" class="category-tag">{{ row.category }}</el-tag>
                  </div>
                  <div class="file-path-row">
                    <span class="file-path">{{ row.path }}</span>
                    <el-button
                      type="primary"
                      link
                      size="small"
                      :icon="CopyDocument"
                      title="复制相对路径"
                      @click="copyText(row.path)"
                    />
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="文件大小" width="120" prop="size" sortable>
              <template #default="{ row }">
                <span class="size-badge">{{ row.size_human }}</span>
              </template>
            </el-table-column>

            <el-table-column label="修改时间" width="170" prop="mtime" sortable>
              <template #default="{ row }">
                <span class="mtime-text">{{ row.mtime }}</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="140" align="right">
              <template #default="{ row }">
                <el-button
                  type="primary"
                  link
                  size="small"
                  :icon="Download"
                  @click="downloadAsset(row)"
                >
                  下载
                </el-button>
                <el-button
                  type="danger"
                  link
                  size="small"
                  :icon="Delete"
                  :loading="cleaning && cleanTarget === row.path"
                  @click="confirmCleanSingle(row)"
                >
                  清理
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 0 孤立文件完美状态 -->
          <div v-else-if="!scanning" class="clean-empty-state">
            <el-empty
              description="干干净净！当前未发现任何孤立无引用的附件文件"
              :image-size="120"
            >
              <template #extra>
                <div class="empty-tip">全站附件均被笔记、日记、随手记等文档正常引用，运行状态极佳。</div>
              </template>
            </el-empty>
          </div>
        </el-tab-pane>

        <!-- Tab 2: 有效引用资产 -->
        <el-tab-pane name="referenced">
          <template #label>
            <span class="tab-label">
              <span>正常引用文件</span>
              <el-tag size="small" type="info" round class="tab-count-tag">
                {{ scanData?.referenced_files?.length || 0 }}
              </el-tag>
            </span>
          </template>

          <div class="tab-toolbar">
            <el-input
              v-model="refSearch"
              placeholder="搜索引用文件名或关联文档名称…"
              clearable
              :prefix-icon="Search"
              class="search-input"
            />
            <span class="tool-count">显示 {{ filteredReferenced.length }} / 共 {{ scanData?.referenced_files?.length || 0 }} 项</span>
          </div>

          <el-table
            :data="filteredReferenced"
            style="width: 100%"
            class="asset-table"
            row-key="path"
          >
            <el-table-column label="预览" width="76" align="center">
              <template #default="{ row }">
                <div class="thumb-cell" @click="handlePreview(row)">
                  <img
                    v-if="row.is_image && thumbUrls[row.path]"
                    :src="thumbUrls[row.path]"
                    class="thumb-img"
                    alt="缩略图"
                    loading="lazy"
                  />
                  <div v-else-if="row.is_image" class="thumb-placeholder">
                    <el-icon class="thumb-loading"><Picture /></el-icon>
                  </div>
                  <div v-else class="file-icon-box" :class="getFileExtClass(row.filename)">
                    <span>{{ getFileExt(row.filename) }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="文件名" min-width="220">
              <template #default="{ row }">
                <div class="file-name" :title="row.filename">{{ row.filename }}</div>
                <div class="file-path">{{ row.path }}</div>
              </template>
            </el-table-column>

            <el-table-column label="大小" width="110" prop="size" sortable>
              <template #default="{ row }">
                <span class="size-badge">{{ row.size_human }}</span>
              </template>
            </el-table-column>

            <el-table-column label="引用次数" width="110" prop="ref_count" sortable align="center">
              <template #default="{ row }">
                <el-tag type="success" size="small" effect="light" round>
                  {{ row.ref_count }} 次引用
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column label="关联引用文档" min-width="320">
              <template #default="{ row }">
                <div class="ref-docs-list">
                  <el-tag
                    v-for="(ref, i) in row.references"
                    :key="i"
                    size="small"
                    :type="getDocTagType(ref.type)"
                    effect="plain"
                    class="ref-doc-tag"
                    :title="`${ref.type}: ${ref.title} (${ref.path})`"
                  >
                    <span class="ref-type-badge">{{ ref.type }}</span>
                    <span class="ref-title-text">{{ ref.title }}</span>
                  </el-tag>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="90" align="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" :icon="Download" @click="downloadAsset(row)">
                  下载
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 大图放大查看 Dialog -->
    <el-dialog
      v-model="previewDialogVisible"
      :title="previewFile?.filename || '文件预览'"
      width="720px"
      append-to-body
      destroy-on-close
      class="preview-dialog"
    >
      <div class="preview-dialog-body">
        <div v-if="previewFile?.is_image" class="preview-img-wrap">
          <img :src="thumbUrls[previewFile.path]" class="full-preview-img" alt="预览大图" />
        </div>
        <div v-else class="preview-non-img">
          <el-icon style="font-size: 64px; color: var(--txt3); margin-bottom: 12px;"><Document /></el-icon>
          <div style="font-size: 15px; font-weight: 600;">{{ previewFile?.filename }}</div>
          <div style="font-size: 13px; color: var(--txt2); margin-top: 4px;">{{ previewFile?.path }} · {{ previewFile?.size_human }}</div>
        </div>
        <div class="preview-meta-info">
          <div><b>存储路径：</b>{{ previewFile?.path }}</div>
          <div><b>文件大小：</b>{{ previewFile?.size_human }} ({{ previewFile?.size }} 字节)</div>
          <div><b>修改时间：</b>{{ previewFile?.mtime }}</div>
          <div><b>媒体类型：</b>{{ previewFile?.mime_type }}</div>
        </div>
      </div>
      <template #footer>
        <el-button @click="previewDialogVisible = false">关闭</el-button>
        <el-button type="primary" :icon="Download" @click="previewFile && downloadAsset(previewFile)">
          下载文件
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Files,
  Coin,
  Delete,
  Refresh,
  Check,
  Warning,
  Search,
  Download,
  CopyDocument,
  Picture,
  Document,
} from '@element-plus/icons-vue'
import { http } from '../api/client'

interface AssetDocRef {
  title: string
  type: string
  path: string
}

interface AssetFileItem {
  filename: string
  path: string
  category: string
  size: number
  size_human: string
  mtime: string
  is_image: boolean
  mime_type: string
  preview_url: string
  ref_count: number
  references: AssetDocRef[]
}

interface ScanResponse {
  total_files: number
  total_bytes: number
  total_size_human: string
  unreferenced_count: number
  unreferenced_bytes: number
  unreferenced_size_human: string
  unreferenced_files: AssetFileItem[]
  referenced_files: AssetFileItem[]
}

const scanning = ref(false)
const cleaning = ref(false)
const cleanTarget = ref<string>('')
const scanData = ref<ScanResponse | null>(null)
const lastScanTime = ref('')
const activeTab = ref('unreferenced')

const unrefSearch = ref('')
const refSearch = ref('')
const selectedUnref = ref<AssetFileItem[]>([])

const thumbUrls = reactive<Record<string, string>>({})
const previewDialogVisible = ref(false)
const previewFile = ref<AssetFileItem | null>(null)

/** 过滤孤立附件 */
const filteredUnreferenced = computed(() => {
  const list = scanData.value?.unreferenced_files || []
  const kw = unrefSearch.value.trim().toLowerCase()
  if (!kw) return list
  return list.filter((f) => f.filename.toLowerCase().includes(kw) || f.path.toLowerCase().includes(kw))
})

/** 过滤引用附件 */
const filteredReferenced = computed(() => {
  const list = scanData.value?.referenced_files || []
  const kw = refSearch.value.trim().toLowerCase()
  if (!kw) return list
  return list.filter((f) => {
    if (f.filename.toLowerCase().includes(kw) || f.path.toLowerCase().includes(kw)) return true
    return f.references.some((r) => r.title.toLowerCase().includes(kw) || r.type.toLowerCase().includes(kw))
  })
})

/** 执行体检扫描 */
async function runScan() {
  scanning.value = true
  try {
    const res = await http.get<ScanResponse>('/assets/scan')
    scanData.value = res
    lastScanTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    // 异步拉取前 20 张图片的缩略图
    loadThumbnails(res.unreferenced_files.concat(res.referenced_files))
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '体检扫描失败，请检查网络后重试')
  } finally {
    scanning.value = false
  }
}

/** 批量/按需加载缩略图为本地 blob URL（支持 AES 解密图片） */
async function loadThumbnails(files: AssetFileItem[]) {
  const imgFiles = files.filter((f) => f.is_image && !thumbUrls[f.path]).slice(0, 40)
  for (const f of imgFiles) {
    try {
      const blob = await http.blob(`/assets/file?path=${encodeURIComponent(f.path)}`)
      thumbUrls[f.path] = URL.createObjectURL(blob)
    } catch {
      // 忽略单个缩略图拉取异常
    }
  }
}

function handleSelectionChange(selection: AssetFileItem[]) {
  selectedUnref.value = selection
}

/** 一键清理所有孤立附件 */
async function confirmCleanAll() {
  if (!scanData.value || scanData.value.unreferenced_count === 0) return
  try {
    await ElMessageBox.confirm(
      `确定一键清理全部 ${scanData.value.unreferenced_count} 个孤立附件？\n预计释放 ${scanData.value.unreferenced_size_human} 存储空间。\n\n【安全承诺】清理的文件将完整转移到回收站 (data/trash)，不会直接物理抹除，可随时还原。`,
      '一键清理孤立附件确认',
      {
        confirmButtonText: '确认清理',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  cleaning.value = true
  cleanTarget.value = 'all'
  try {
    const res = await http.post<{ ok: boolean; cleaned_count: number; freed_size_human: string }>('/assets/clean', {
      all_unreferenced: true,
      permanent: false,
    })
    ElMessage.success(`清理完成！已移入回收站 ${res.cleaned_count} 个孤立文件，释放 ${res.freed_size_human} 空间`)
    await runScan()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '清理失败，请重试')
  } finally {
    cleaning.value = false
    cleanTarget.value = ''
  }
}

/** 清理选中项 */
async function confirmCleanSelected() {
  if (!selectedUnref.value.length) return
  const count = selectedUnref.value.length
  try {
    await ElMessageBox.confirm(
      `确认清理选中的 ${count} 个孤立附件？文件将移入系统回收站。`,
      '批量清理确认',
      { confirmButtonText: '确认清理', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  cleaning.value = true
  cleanTarget.value = 'selected'
  try {
    const paths = selectedUnref.value.map((f) => f.path)
    const res = await http.post<{ ok: boolean; cleaned_count: number; freed_size_human: string }>('/assets/clean', {
      paths,
      permanent: false,
    })
    ElMessage.success(`成功清理 ${res.cleaned_count} 个附件，释放 ${res.freed_size_human} 空间`)
    selectedUnref.value = []
    await runScan()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '清理失败')
  } finally {
    cleaning.value = false
    cleanTarget.value = ''
  }
}

/** 清理单个孤立项 */
async function confirmCleanSingle(row: AssetFileItem) {
  try {
    await ElMessageBox.confirm(`确认清理孤立文件「${row.filename}」？文件将移动到回收站。`, '清理确认', {
      confirmButtonText: '清理',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  cleaning.value = true
  cleanTarget.value = row.path
  try {
    const res = await http.post<{ ok: boolean; cleaned_count: number; freed_size_human: string }>('/assets/clean', {
      paths: [row.path],
      permanent: false,
    })
    ElMessage.success(`已清理「${row.filename}」，释放 ${res.freed_size_human}`)
    await runScan()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '清理失败')
  } finally {
    cleaning.value = false
    cleanTarget.value = ''
  }
}

/** 下载资产文件 */
async function downloadAsset(row: AssetFileItem) {
  try {
    const blob = await http.blob(`/assets/file?path=${encodeURIComponent(row.path)}&download=true`)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error('文件下载失败')
  }
}

/** 点击缩略图弹出详情预览 */
async function handlePreview(row: AssetFileItem) {
  previewFile.value = row
  previewDialogVisible.value = true
  if (row.is_image && !thumbUrls[row.path]) {
    try {
      const blob = await http.blob(`/assets/file?path=${encodeURIComponent(row.path)}`)
      thumbUrls[row.path] = URL.createObjectURL(blob)
    } catch {
      /* ignore */
    }
  }
}

function copyText(txt: string) {
  navigator.clipboard.writeText(txt).then(
    () => ElMessage.success('相对路径已复制'),
    () => ElMessage.error('复制失败'),
  )
}

function getFileExt(filename: string): string {
  if (!filename.includes('.')) return 'FILE'
  return filename.split('.').pop()?.toUpperCase().slice(0, 4) || 'FILE'
}

function getFileExtClass(filename: string): string {
  const ext = getFileExt(filename).toLowerCase()
  if (['pdf'].includes(ext)) return 'pdf-box'
  if (['doc', 'docx'].includes(ext)) return 'doc-box'
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return 'zip-box'
  return 'default-box'
}

function getDocTagType(type: string): '' | 'success' | 'warning' | 'info' | 'danger' {
  if (type.includes('笔记')) return 'primary' as any
  if (type.includes('日记')) return 'success'
  if (type.includes('白板')) return 'warning'
  if (type.includes('相册')) return 'danger'
  return 'info'
}

onMounted(() => {
  runScan()
})
</script>

<style scoped>
.asset-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.am-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.am-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 700;
  color: var(--txt);
}

.title-ico {
  font-size: 18px;
  color: var(--acc2);
}

.am-desc {
  font-size: 12.5px;
  color: var(--txt2);
  margin-top: 6px;
  line-height: 1.7;
}

.am-desc code {
  background: rgba(139, 92, 246, 0.12);
  padding: 1px 6px;
  border-radius: 6px;
  color: var(--acc2);
}

.am-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* 4 指标卡片网格 */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.06);
  border: 1px solid rgba(148, 163, 184, 0.18);
  transition: transform 0.2s, box-shadow 0.2s;
}

.metric-card:hover {
  transform: translateY(-1px);
  border-color: rgba(167, 139, 250, 0.35);
}

.metric-card.has-warning {
  border-color: rgba(245, 158, 11, 0.3);
  background: rgba(245, 158, 11, 0.04);
}

.mc-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.mc-icon.primary { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.mc-icon.info { background: rgba(14, 165, 233, 0.15); color: #0ea5e9; }
.mc-icon.warning { background: rgba(245, 158, 11, 0.18); color: #f59e0b; }
.mc-icon.success { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.mc-icon.accent { background: rgba(168, 85, 247, 0.15); color: #a855f7; }

.mc-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.mc-label {
  font-size: 12px;
  color: var(--txt3);
}

.mc-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--txt);
  margin-top: 2px;
}

.mc-unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--txt3);
}

/* 提示与状态条 */
.scan-meta-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--txt3);
  padding: 6px 12px;
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.05);
  flex-wrap: wrap;
  gap: 8px;
}

.meta-tip code {
  color: var(--acc2);
}

/* 数据主体面板 */
.am-body {
  border-radius: 14px;
  padding: 12px 16px 18px;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.tab-badge :deep(.el-badge__content) {
  background-color: #f59e0b;
}

.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 12px 0 16px;
  gap: 12px;
  flex-wrap: wrap;
}

.tool-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  max-width: 520px;
}

.search-input {
  max-width: 320px;
}

.tool-count {
  font-size: 12.5px;
  color: var(--txt3);
}

/* 表格样式 */
.asset-table {
  border-radius: 10px;
  overflow: hidden;
  background: transparent;
}

.asset-table :deep(th.el-table__cell) {
  background: rgba(148, 163, 184, 0.06);
  color: var(--txt2);
  font-weight: 600;
  font-size: 13px;
}

.asset-table :deep(td.el-table__cell) {
  background: transparent;
  color: var(--txt);
}

/* 缩略图 */
.thumb-cell {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid rgba(148, 163, 184, 0.15);
  transition: transform 0.15s;
}

.thumb-cell:hover {
  transform: scale(1.08);
  border-color: var(--acc2);
}

.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--txt3);
  font-size: 20px;
}

.file-icon-box {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.file-icon-box.pdf-box { background: rgba(239, 68, 68, 0.18); color: #ef4444; }
.file-icon-box.doc-box { background: rgba(59, 130, 246, 0.18); color: #3b82f6; }
.file-icon-box.zip-box { background: rgba(245, 158, 11, 0.18); color: #f59e0b; }
.file-icon-box.default-box { background: rgba(148, 163, 184, 0.18); color: var(--txt2); }

/* 文件信息单元格 */
.file-main-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.file-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-name {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--txt);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-tag {
  font-size: 11px;
  height: 20px;
  line-height: 18px;
}

.file-path-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.file-path {
  font-size: 11.5px;
  color: var(--txt3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.size-badge {
  font-family: monospace;
  font-size: 12.5px;
  font-weight: 500;
}

.mtime-text {
  font-size: 12px;
  color: var(--txt3);
}

/* 引用文档列表 */
.ref-docs-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ref-doc-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 280px;
}

.ref-type-badge {
  font-size: 10.5px;
  opacity: 0.85;
}

.ref-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 空状态 */
.clean-empty-state {
  padding: 40px 0;
}

.empty-tip {
  font-size: 13px;
  color: var(--txt3);
  margin-top: 6px;
}

/* 预览大图弹窗 */
.preview-dialog-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.preview-img-wrap {
  width: 100%;
  max-height: 480px;
  display: flex;
  justify-content: center;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 12px;
  overflow: hidden;
  padding: 12px;
}

.full-preview-img {
  max-width: 100%;
  max-height: 450px;
  object-fit: contain;
  border-radius: 8px;
}

.preview-non-img {
  padding: 30px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.preview-meta-info {
  width: 100%;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.08);
  font-size: 12.5px;
  color: var(--txt2);
  line-height: 1.8;
}
</style>
