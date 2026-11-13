<template>
  <div class="assistant-page" :class="{ 'with-aside': isLargeScreen }">
    <!-- 左侧/主体主工作区 -->
    <div class="assistant-main">
      <!-- 页面顶部标题栏 -->
      <div class="head glass">
        <div class="head-left">
          <div class="head-title grad-text">智能助手</div>
          <div class="head-sub">通知聚合演变 · 稍后看资料整理 · 日程与笔记多维联动</div>
        </div>
        <div class="head-actions">
          <el-button
            round
            size="small"
            :type="diagState.connected ? 'success' : 'danger'"
            plain
            class="diag-btn"
            @click="openDiagnosticsDialog"
          >
            <el-icon style="margin-right:4px"><Odometer /></el-icon>
            <span>{{ diagState.connected ? `模型在线 (${diagState.latency_ms}ms)` : '模型连接诊断' }}</span>
          </el-button>
          <el-button
            v-if="!isLargeScreen"
            round
            size="small"
            type="primary"
            class="drawer-toggle-btn"
            @click="drawerVisible = true"
          >
            <el-icon style="margin-right:4px"><ChatLineRound /></el-icon>
            <span>详情与对话</span>
          </el-button>
          <el-button round size="small" @click="refreshList">
            <el-icon style="margin-right:4px"><Refresh /></el-icon>
            <span>刷新</span>
          </el-button>
        </div>
      </div>

      <!-- 顶部统一输入区 -->
      <div
        class="input-card glass"
        :class="{ 'drag-over': isDraggingOver }"
        @dragover.prevent="onDragOver"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onFileDrop"
      >
        <div class="input-card-header">
          <div class="unified-input-title">
            <el-icon style="margin-right: 5px; color: var(--el-color-primary);"><Compass /></el-icon>
            <span style="font-weight: 600;">智能信息收录</span>
            <span style="font-size: 12px; color: var(--el-text-color-secondary); margin-left: 8px;">自动提炼核心摘要、待办事项与截止时间</span>
          </div>
          <span class="shortcut-tip">支持快捷键 Ctrl + Enter 极速提交</span>
        </div>

        <!-- 文本与链接多行输入 -->
        <div class="input-body">
          <el-input
            ref="textareaRef"
            v-model="inputContent"
            type="textarea"
            :rows="3"
            placeholder="在此粘贴通知公告、邮件正文、会议安排、论文/项目链接、文章资料，或直接按 Ctrl+V 粘贴截图..."
            resize="vertical"
            @paste="onTextareaPaste"
            @keydown.ctrl.enter="submitInput"
          />
        </div>

        <!-- 截图 / 附件拖拽预览区 -->
        <div v-if="pastedImagePreview || uploadedFileName" class="preview-strip">
          <div v-if="pastedImagePreview" class="image-preview-box">
            <img :src="pastedImagePreview" alt="截图预览" class="pasted-thumb" />
            <span class="preview-tag">已捕获截图</span>
            <el-button circle size="small" type="danger" class="del-preview-btn" @click="clearImage">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
          <div v-if="uploadedFileName" class="file-preview-box">
            <el-icon :size="20"><Document /></el-icon>
            <span class="filename-text">{{ uploadedFileName }}</span>
            <el-button circle size="small" text type="danger" @click="clearFile">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- 用户备注与快捷标签 -->
        <div class="note-intent-row">
          <el-input
            v-model="inputUserNote"
            size="small"
            placeholder="附加我的备注或意图（如：关注申报条件、精读模型设计）"
            class="intent-input"
            @keydown.ctrl.enter="submitInput"
          >
            <template #prefix>
              <el-icon><EditPen /></el-icon>
            </template>
          </el-input>

          <div class="quick-tags">
            <span class="quick-hint">快捷填充：</span>
            <button
              v-for="tag in quickTags"
              :key="tag"
              type="button"
              class="quick-tag-chip"
              @click="applyQuickTag(tag)"
            >
              {{ tag }}
            </button>
          </div>
        </div>

        <!-- 底部提交操作栏 -->
        <div class="input-footer">
          <div class="drop-hint">
            <el-icon><UploadFilled /></el-icon>
            <span>支持拖入图片或附件文件</span>
            <label class="file-upload-btn" title="选择图片或附件">
              <input type="file" accept="image/*,.pdf,.docx,.txt,.md" class="hidden-file-input" @change="onFileInputChange" />
              <span>选择文件</span>
            </label>
          </div>

          <el-button
            type="primary"
            round
            :loading="submitting"
            class="submit-btn"
            @click="submitInput"
          >
            <el-icon style="margin-right: 4px"><Promotion /></el-icon>
            <span>提交并整理</span>
          </el-button>
        </div>
      </div>

      <!-- 中间筛选与搜索条 -->
      <div class="filter-bar glass">
        <el-tabs v-model="activeTab" class="filter-tabs" @tab-change="onTabChange">
          <el-tab-pane label="全部记录" name="all" />
          <el-tab-pane label="通知事项" name="notice" />
          <el-tab-pane label="稍后看" name="later" />
          <el-tab-pane name="alerts">
            <template #label>
              <span class="tab-badge-wrap">
                待办与截止期
                <span v-if="alertCount > 0" class="badge-dot">{{ alertCount }}</span>
              </span>
            </template>
          </el-tab-pane>
          <el-tab-pane label="已归档" name="archived" />
        </el-tabs>

        <div class="search-wrap">
          <el-input
            v-model="searchQuery"
            size="small"
            placeholder="搜索事项标题、摘要、标签或备注..."
            clearable
            class="search-input"
            @input="onSearchInput"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>
      </div>

      <!-- 列表内容区 -->
      <div v-loading="loading" class="record-list">
        <template v-if="filteredRecords.length">
          <component :is="group.isCollection ? 'details' : 'div'" v-for="group in recordGroups" :key="group.key" :class="{ 'collection-group': group.isCollection, glass: group.isCollection }">
          <summary v-if="group.isCollection" class="collection-heading">{{ group.title }} <span>{{ group.items.length }} 条 · 展开查看</span></summary>
          <div
            v-for="item in group.items"
            :key="item.id"
            class="record-card glass"
            :class="[
              `card-kind-${item.kind}`,
              {
                active: selectedItem?.id === item.id,
                'is-archived': item.archived,
                'is-read': item.read_state === 'read' || item.read_state === 'noted',
                'is-failed': item.status === 'failed'
              }
            ]"
            @click="selectItem(item)"
          >
            <!-- 头部类型标识与元数据 -->
            <div class="card-top">
              <div class="kind-tag-group">
                <span class="category-pill" :class="item.category">{{ item.category || '记录' }}</span>
                <span v-if="item.thread?.source_count && item.thread.source_count > 1" class="category-pill">已合并 {{ item.thread.source_count }} 条通知</span>
                <span v-if="item.status === 'pending' || item.status === 'processing'" class="category-pill">正在整理</span>
                <span v-else-if="item.status === 'failed'" class="category-pill failed-pill">
                  <el-icon style="margin-right:2px"><WarningFilled /></el-icon>整理失败
                </span>
                <span v-if="item.read_state === 'noted'" class="noted-pill">已入笔记</span>
                <span
                  v-if="item.wb_item_title || item.wb_item_id"
                  class="wb-pill"
                  :title="'关联工作台事项: ' + (item.wb_item_title || ('#' + item.wb_item_id))"
                >
                  💼 {{ item.wb_item_title || ('工作台 #' + item.wb_item_id) }}
                </span>
                <span v-if="item.attachments_count" class="attachment-pill">
                  <el-icon style="margin-right: 2px"><Paperclip /></el-icon>{{ item.attachments_count }}个附件
                </span>
              </div>

              <!-- DDL 倒计时标签（任意含有截止期的卡片展示） -->
              <div v-if="item.deadline_date" class="ddl-pill" :class="getDdlStatus(item.deadline_date).urgency">
                <el-icon style="margin-right: 3px"><Clock /></el-icon>
                <span>DDL: {{ item.deadline_date }} {{ item.deadline_time || '' }} ({{ getDdlStatus(item.deadline_date).label }})</span>
              </div>

              <span class="card-time">{{ item.created_at }}</span>
            </div>

            <!-- 卡片核心标题 -->
            <div class="card-title-row">
              <h3 class="card-title" :title="item.title">{{ item.title }}</h3>
            </div>
            <div v-if="item.kind === 'notice' && ((item.thread?.source_deadlines?.length || 0) > 0 || item.tasks?.some(task => task.deadline_date))" class="deadline-section">
              <div class="deadline-heading">各事项截止时间</div>
              <div v-for="deadline in item.thread?.source_deadlines || []" :key="`source-${deadline.record_id}`" class="deadline-line">
                {{ deadline.title }}：{{ deadline.date }} {{ deadline.time }}
              </div>
              <div v-for="task in (item.tasks || []).filter(task => task.deadline_date)" :key="`task-${task.id}`" class="deadline-line" @click.stop>
                {{ task.title }}：{{ task.deadline_date }} {{ task.deadline_time }}
                <span v-if="task.date_conflict">（时间有冲突，请核对）</span>
                <el-button size="small" text @click="editTask(item, task)">编辑</el-button>
              </div>
            </div>

            <!-- 整理失败醒目警告条 -->
            <div v-if="item.status === 'failed'" class="card-failed-warning">
              <div class="failed-warning-header">
                <el-icon class="warning-icon"><CircleCloseFilled /></el-icon>
                <strong>整理失败</strong>
              </div>
              <div v-if="item.error_msg" class="failed-warning-desc">
                {{ item.error_msg }}
              </div>
            </div>

            <!-- 通知事项卡片展示：最新变动提示条 -->
            <div v-if="item.latest_change && (item.kind !== 'notice' || item.has_conflict)" class="latest-change-banner">
              <el-icon class="banner-icon"><WarningFilled /></el-icon>
              <span class="banner-text"><strong>最新变动：</strong>{{ item.latest_change }}</span>
            </div>
            <div v-for="suggestion in item.thread?.suggestions || []" :key="suggestion.id" class="latest-change-banner" @click.stop>
              <span>可能属于同一事项：{{ suggestion.title }}</span>
              <el-button size="small" text @click="mergeSuggestion(item, suggestion.id)">合并</el-button>
              <el-button size="small" text @click="dismissSuggestion(item, suggestion.id)">不是同一事项</el-button>
            </div>

            <!-- 一段信息依次展示来源、消息框与对应原句。 -->
            <div v-if="item.kind === 'notice' && item.thread?.source_messages?.length" class="source-messages">
              <section v-for="source in item.thread.source_messages" :key="source.record_id" class="source-message">
                <div class="source-origin" @click.stop="openSourceRecord(source.record_id)">
                  <span class="source-origin-label">包含来源</span>
                  <span class="source-origin-title">{{ source.title }}</span>
                  <button type="button" class="source-open">查看原文</button>
                </div>
                <div class="source-message-box">
                  <template v-if="source.summary">
                    <div v-for="(sentence, index) in splitSentences(source.summary)" :key="index" class="source-sentence">{{ sentence }}</div>
                  </template>
                  <div v-else class="source-summary-pending">
                    <span>{{ sourceSummaryJobs[source.record_id]?.status === 'running' ? '正在整理这段信息…' : '这段信息尚无独立摘要' }}</span>
                    <el-button v-if="sourceSummaryJobs[source.record_id]?.status !== 'running'" size="small" text @click.stop="refreshSourceSummary(source.record_id)">整理这段信息</el-button>
                  </div>
                </div>
                <div class="source-evidence-box">
                  <div class="source-evidence-label">依据原句</div>
                  <template v-if="source.evidence_quotes.length">
                    <div v-for="(sentence, index) in splitSourceQuotes(source.evidence_quotes)" :key="index" class="source-evidence-sentence">{{ sentence }}</div>
                  </template>
                  <div v-else class="source-evidence-missing">暂无可核对的原句，请查看来源原文。</div>
                </div>
              </section>
            </div>
            <div v-else class="card-summary">{{ item.summary || item.content || '暂无详细摘要内容' }}</div>
            <div v-if="item.kind !== 'notice' && item.quote" class="card-quote-snippet">
              <span class="quote-tag">📌 依据原句</span>
              <span class="quote-snippet-text" :title="item.quote">{{ item.quote }}</span>
            </div>

            <!-- 稍后看卡片展示：关注理由与我的备注 -->
            <div v-if="item.kind !== 'notice' && (item.reason || item.user_note)" class="reason-box">
              <div class="reason-label">关注理由：</div>
              <div class="reason-content">{{ item.reason || item.user_note }}</div>
            </div>

            <!-- 标签与来源线索 -->
            <div class="card-meta-row">
              <div class="tags-cluster">
                <span v-for="t in item.tags" :key="t" class="tag-item"># {{ t }}</span>
              </div>

              <div v-if="item.source_url" class="source-clue">
                <el-icon><Link /></el-icon>
                <a :href="item.source_url" target="_blank" rel="noopener noreferrer" class="source-link" @click.stop>
                  {{ formatUrl(item.source_url) }}
                </a>
              </div>
            </div>

            <!-- 底部操作按钮栏 -->
            <div class="card-actions" @click.stop>
              <!-- 失败状态只提供真实重试：不做规则降级伪装 -->
              <template v-if="item.status === 'failed'">
                <el-button size="small" round type="danger" plain @click="retryRecord(item)">
                  <el-icon><RefreshRight /></el-icon>重新处理 (重试)
                </el-button>
              </template>
              <!-- 统一卡片操作 -->
              <template v-else>
                <el-button v-if="item.kind === 'notice' && item.thread?.id" size="small" round text @click="mergeItem(item)">合并事项</el-button>
                <el-button v-if="item.kind === 'notice' && item.thread?.id" size="small" round text @click="extractMissingTasks(item)">补提待办</el-button>
                <el-button v-if="item.thread?.last_manual_merge_id" size="small" round text @click="undoMerge(item)">撤销合并</el-button>
                <el-button v-if="item.source_url" size="small" round text @click="openSourceUrl(item.source_url)">
                  <el-icon><Link /></el-icon>打开来源
                </el-button>
                <el-button v-if="item.deadline_date" size="small" round text @click="goToSchedule(item)">
                  <el-icon><Calendar /></el-icon>查看日程
                </el-button>
                <el-button size="small" round text @click="openRawDetail(item)">
                  <el-icon><Document /></el-icon>详情与原文
                </el-button>
                <el-button size="small" round type="primary" plain @click="writeNoteFromRecord(item)">
                  <el-icon><EditPen /></el-icon>写笔记
                </el-button>
                <el-button
                  size="small"
                  round
                  :type="(item.deadline_date ? item.thread?.status === 'completed' : item.read_state === 'read') ? 'success' : 'default'"
                  @click="item.deadline_date ? toggleComplete(item) : toggleReadState(item)"
                >
                  <el-icon><Check /></el-icon>{{ (item.deadline_date ? item.thread?.status === 'completed' : item.read_state === 'read') ? '已完成' : (item.deadline_date ? '完成' : '已读') }}
                </el-button>
                <el-button size="small" round text @click="toggleArchive(item)">
                  {{ item.archived ? '恢复' : '归档' }}
                </el-button>
              </template>
            </div>
          </div>
          </component>
        </template>

        <div v-else class="empty-state glass">
          <el-icon :size="48" class="empty-icon"><Compass /></el-icon>
          <div class="empty-text">当前分类下暂无记录</div>
          <div class="empty-sub">在上方输入框粘贴内容、输入链接或截图，助手将自动整理</div>
        </div>
      </div>
    </div>

    <!-- 右侧详情与对话区：大屏常驻侧栏 -->
    <aside v-if="isLargeScreen" class="assistant-aside glass">
      <SidePanelContent
        :selected-item="selectedItem"
        :active-mode="sideMode"
        @update:active-mode="sideMode = $event"
        @close="selectedItem = null"
        @write-note="writeNoteFromRecord"
        @split-source="handleSplitSource"
        @retry="retryRecord"
      />
    </aside>

    <!-- 小屏抽屉 -->
    <el-drawer
      v-else
      v-model="drawerVisible"
      title="助手详情与对话"
      direction="rtl"
      size="440px"
      :with-header="true"
      class="assistant-drawer"
    >
      <SidePanelContent
        :selected-item="selectedItem"
        :active-mode="sideMode"
        @update:active-mode="sideMode = $event"
        @close="drawerVisible = false"
        @write-note="writeNoteFromRecord"
        @split-source="handleSplitSource"
        @retry="retryRecord"
      />
    </el-drawer>

    <!-- 大模型连通性与隧道诊断对话框 -->
    <el-dialog v-model="diagDialogVisible" title="大模型服务连通性与隧道诊断" width="540px" append-to-body>
      <div v-loading="diagLoading" class="diag-dialog-body">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="模型提供商">{{ diagState.provider || 'local' }}</el-descriptions-item>
          <el-descriptions-item label="模型名称">{{ diagState.model || 'qwen2.5:7b' }}</el-descriptions-item>
          <el-descriptions-item label="服务端点">{{ diagState.endpoint || 'http://127.0.0.1:11434/v1' }}</el-descriptions-item>
          <el-descriptions-item label="连接状态">
            <el-tag :type="diagState.connected ? 'success' : 'danger'" size="small">
              {{ diagState.connected ? `已连通 (${diagState.latency_ms} ms)` : '连接不可用' }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="!diagState.connected" class="diag-error-box">
          <div class="diag-error-title">
            <el-icon style="color: var(--el-color-danger)"><WarningFilled /></el-icon>
            <strong>未连通原因与解决提示：</strong>
          </div>
          <div class="diag-error-detail">{{ diagState.error_hint }}</div>
          <div v-if="diagState.error_hint && diagState.error_hint.includes('ssh -N')" class="tunnel-hint-card">
            <div class="tunnel-hint-label">若使用远程端口转发，请在本地终端执行 SSH 隧道命令：</div>
            <div class="tunnel-cmd-row">
              <code>{{ copyTunnelCmdText }}</code>
              <el-button size="small" type="primary" plain @click="copyTunnelCommand">
                <el-icon style="margin-right:4px"><CopyDocument /></el-icon>复制
              </el-button>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button size="small" :loading="diagLoading" @click="runDiagnostics">
            <el-icon style="margin-right:4px"><Refresh /></el-icon>重新探测
          </el-button>
          <el-button size="small" type="primary" @click="diagDialogVisible = false">确定</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  ElInput,
  ElButton,
  ElTimeline,
  ElTimelineItem,
  ElIcon,
  ElSelect,
  ElOption,
  ElImage,
  ElTag
} from 'element-plus'
import {
  ChatLineRound, Refresh, Compass, WarningFilled, Clock, Document,
  Close, EditPen, UploadFilled, Promotion, Search, Link, Calendar,
  Finished, Check, ArrowRight, UserFilled, CircleCloseFilled,
  RefreshRight, Odometer, CopyDocument, Paperclip, View, Download, Picture
} from '@element-plus/icons-vue'
import {
  assistantApi,
  type AssistantRecord,
  type AssistantFilter,
  type AssistantChatMessage,
  type AssistantAttachment,
  type AssistantTask,
  type LlmDiagnostics
} from '../api/assistant'

function formatFileSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

const router = useRouter()

// 状态定义
const loading = ref(false)
const submitting = ref(false)
const records = ref<AssistantRecord[]>([])
const sourceSummaryJobs = ref<Record<number, { status: string; error: string }>>({})
const selectedItem = ref<AssistantRecord | null>(null)
const activeTab = ref<AssistantFilter>('all')
const searchQuery = ref('')
const sideMode = ref<'detail' | 'chat'>('detail')
const drawerVisible = ref(false)
let processingTimer: ReturnType<typeof setInterval> | undefined
let refreshingProcessing = false

// 大模型服务连通性诊断状态
const diagDialogVisible = ref(false)
const diagLoading = ref(false)
const diagState = ref<LlmDiagnostics>({
  connected: false,
  latency_ms: 0,
  model: 'qwen2.5:7b',
  provider: 'local',
  endpoint: 'http://127.0.0.1:11434/v1',
  error_hint: '尚未探测连通性',
})

const copyTunnelCmdText = computed(() => {
  const hint = diagState.value.error_hint || ''
  const m = hint.match(/ssh\s+-N\s+[^\r\n"']+/)
  return m ? m[0] : 'ssh -N -L 11434:localhost:11434 user@remote'
})

async function runDiagnostics() {
  diagLoading.value = true
  try {
    const res = await assistantApi.diagnosticsLlm()
    diagState.value = res
  } catch (err: any) {
    diagState.value = {
      connected: false,
      latency_ms: 0,
      model: 'qwen2.5:7b',
      provider: 'local',
      endpoint: 'http://127.0.0.1:11434/v1',
      error_hint: err?.message || '无法连接后端诊断接口',
    }
  } finally {
    diagLoading.value = false
  }
}

function openDiagnosticsDialog() {
  diagDialogVisible.value = true
  runDiagnostics()
}

function copyTunnelCommand() {
  navigator.clipboard.writeText(copyTunnelCmdText.value).then(() => {
    ElMessage.success('已复制 SSH 隧道命令到剪贴板')
  })
}

// 响应式屏幕检测
const isLargeScreen = ref(window.innerWidth >= 1180)
function handleResize() {
  isLargeScreen.value = window.innerWidth >= 1180
}

// 统一输入区状态（支持真实文件与预览）
const inputKind = ref<'auto' | 'notice' | 'later'>('auto')
const inputContent = ref('')
const inputUserNote = ref('')
const pastedImagePreview = ref<string | null>(null)
const pastedImageFile = ref<File | null>(null)
const uploadedFileName = ref<string | null>(null)
const uploadedFileObj = ref<File | null>(null)
const isDraggingOver = ref(false)
const textareaRef = ref<any>(null)

const quickTags = [
  '帮我追踪',
  '先存着以后看',
  '注意截止日期',
  '提取关键材料',
  '归纳论文核心',
  '需要报销发票'
]

function applyQuickTag(tag: string) {
  if (!inputUserNote.value) {
    inputUserNote.value = tag
  } else if (!inputUserNote.value.includes(tag)) {
    inputUserNote.value = `${inputUserNote.value}，${tag}`
  }
}

// 剪贴板图片处理
function onTextareaPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        pastedImageFile.value = file
        const reader = new FileReader()
        reader.onload = (event) => {
          pastedImagePreview.value = event.target?.result as string
          ElMessage.info('已捕获剪贴板截图')
        }
        reader.readAsDataURL(file)
        break
      }
    }
  }
}

// 文件拖拽与选择
function onDragOver() {
  isDraggingOver.value = true
}

function onDragLeave() {
  isDraggingOver.value = false
}

function onFileDrop(e: DragEvent) {
  isDraggingOver.value = false
  const files = e.dataTransfer?.files
  if (!files || !files.length) return
  handleIncomingFile(files[0])
}

function onFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length) {
    handleIncomingFile(target.files[0])
  }
}

function handleIncomingFile(file: File) {
  uploadedFileObj.value = file
  uploadedFileName.value = file.name
  if (file.type.startsWith('image/')) {
    pastedImageFile.value = file
    const reader = new FileReader()
    reader.onload = (event) => {
      pastedImagePreview.value = event.target?.result as string
    }
    reader.readAsDataURL(file)
  }
  ElMessage.success(`已载入文件：${file.name}`)
}

function clearImage() {
  pastedImagePreview.value = null
  pastedImageFile.value = null
}

function clearFile() {
  uploadedFileName.value = null
  uploadedFileObj.value = null
}

// 提交收录
async function submitInput() {
  const content = inputContent.value.trim()
  const note = inputUserNote.value.trim()
  const img = pastedImagePreview.value
  const fname = uploadedFileName.value
  const targetFile = uploadedFileObj.value || pastedImageFile.value || undefined

  if (!content && !img && !fname && !targetFile) {
    ElMessage.warning('请输入文字内容、网址、粘贴截图或上传文件')
    return
  }

  submitting.value = true
  ElMessage.info('正在提交...')

  try {
    const isUrl = /^https?:\/\//i.test(content)
    const newRecord = await assistantApi.create({
      kind: inputKind.value,
      content,
      url: isUrl ? content : undefined,
      user_note: note,
      image_preview: img || undefined,
      filename: fname || undefined,
      file: targetFile
    })

    if (newRecord.status === 'ready') {
      ElMessage.success('已保存并整理完成')
    } else if (newRecord.status === 'failed') {
      ElMessage.warning('内容已保存，但整理失败，请查看记录后重试')
    } else {
      ElMessage.success('内容已保存，正在后台整理')
    }

    // 清空输入区
    inputContent.value = ''
    inputUserNote.value = ''
    pastedImagePreview.value = null
    pastedImageFile.value = null
    uploadedFileName.value = null
    uploadedFileObj.value = null

    // 选中并呈现新记录
    selectedItem.value = newRecord
    sideMode.value = 'detail'
    if (!isLargeScreen.value) drawerVisible.value = true
    try {
      await refreshList()
    } catch {
      ElMessage.warning('内容已保存，但列表刷新失败，请稍后刷新页面')
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    const message = typeof detail === 'string' ? detail : ''
    ElMessage.error(message ? `提交失败：${message}` : '提交失败，请检查网络或服务状态后重试')
  } finally {
    submitting.value = false
  }
}

// 列表与过滤
async function refreshList() {
  loading.value = true
  try {
    records.value = await assistantApi.list(activeTab.value, searchQuery.value)
    const pendingSources = records.value.flatMap(item => item.thread?.source_messages || [])
      .filter(source => source.needs_summary && !sourceSummaryJobs.value[source.record_id])
    await Promise.all(pendingSources.map(async source => {
      try {
        const status = await assistantApi.sourceSummaryStatus(source.record_id)
        if (status.status === 'running') sourceSummaryJobs.value[source.record_id] = status
      } catch { /* 列表仍可正常查看 */ }
    }))
    if (!selectedItem.value && records.value.length) {
      selectedItem.value = records.value[0]
      // 预拉取首项详情
      selectItem(records.value[0])
    }
  } finally {
    loading.value = false
  }
}

function onTabChange() {
  refreshList()
}

function onSearchInput() {
  refreshList()
}

async function retryRecord(item: AssistantRecord) {
  try {
    await assistantApi.retry(item.id)
    item.status = 'pending'
    ElMessage.success('已重新提交模型处理...')
    await refreshList()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? `重试失败：${detail}` : '重试失败，请稍后再试')
  }
}

async function refreshProcessing() {
  if (refreshingProcessing || !records.value.some((item) => item.status === 'pending' || item.status === 'processing')) return
  refreshingProcessing = true
  try {
    const items = await assistantApi.list(activeTab.value, searchQuery.value)
    records.value = items
    const selected = selectedItem.value
    if (selected && (selected.status === 'pending' || selected.status === 'processing')) {
      const updated = items.find((item) => item.id === selected.id)
      if (updated && updated.status !== 'pending' && updated.status !== 'processing') {
        const full = await assistantApi.get(updated.id)
        if (selectedItem.value?.id === updated.id) selectedItem.value = full || updated
      }
    }
  } catch {
    // 网络暂时不可用时保留当前列表，下次轮询再试。
  } finally {
    refreshingProcessing = false
  }
}

const filteredRecords = computed(() => records.value)

// 统一卡片流：每条记录保持独立卡片展示与清晰的操作闭环
const recordGroups = computed(() => {
  return filteredRecords.value.map((item) => ({
    key: `record:${item.id}`,
    title: item.title,
    isCollection: false,
    items: [item]
  }))
})

const alertCount = computed(() => {
  return records.value.filter((r) => r.deadline_date || r.latest_change || r.has_conflict).length
})

async function selectItem(item: AssistantRecord) {
  selectedItem.value = item
  if (!isLargeScreen.value) {
    drawerVisible.value = true
  }
  try {
    const full = await assistantApi.get(item.id)
    if (full && selectedItem.value?.id === item.id) {
      selectedItem.value = full
    }
  } catch (err) {
    console.error('Failed to load item detail:', err)
  }
}

function openRawDetail(item: AssistantRecord) {
  selectItem(item)
  sideMode.value = 'detail'
}

function goToSchedule(item: AssistantRecord) {
  if (item.deadline_date) {
    router.push(`/schedule?date=${item.deadline_date}`)
  } else {
    router.push('/schedule')
  }
}

function openSourceUrl(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function toggleArchive(item: AssistantRecord) {
  const next = !item.archived
  await assistantApi.toggleArchive(item.id, next)
  item.archived = next ? 1 : 0
  ElMessage.success(next ? '已移入归档' : '已移出归档')
  await refreshList()
}

async function toggleReadState(item: AssistantRecord) {
  const next = item.read_state !== 'read'
  await assistantApi.toggleRead(item.id, next)
  item.read_state = next ? 'read' : 'unread'
  ElMessage.success(next ? '已标记为看过' : '已标记为未看')
}

async function toggleComplete(item: AssistantRecord) {
  const isDone = item.thread?.status === 'completed'
  await assistantApi.toggleComplete(item.id, !isDone)
  if (!item.thread) {
    item.thread = {
      id: item.thread_id || Date.now(),
      title: item.title,
      summary: item.summary || '',
      highlights: item.highlights || [],
      latest_change: item.latest_change || '',
      deadline_date: item.deadline_date || '',
      deadline_time: item.deadline_time || '',
      has_conflict: false,
      status: !isDone ? 'completed' : 'active',
      created_at: item.created_at,
      updated_at: '刚刚'
    }
  } else {
    item.thread.status = !isDone ? 'completed' : 'active'
  }
  ElMessage.success(!isDone ? '已标记完成' : '已重置为进行中')
}

function writeNoteFromRecord(item: AssistantRecord) {
  router.push(`/notes/new?source_record_id=${item.id}`)
}

function formatUrl(url: string): string {
  try {
    const u = new URL(url)
    return u.hostname + (u.pathname.length > 20 ? u.pathname.slice(0, 20) + '...' : u.pathname)
  } catch {
    return url.slice(0, 30)
  }
}

function getDdlStatus(dateStr: string) {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const [y, m, d] = dateStr.split('-').map(Number)
  const target = new Date(y, m - 1, d)
  target.setHours(0, 0, 0, 0)

  const diffDays = Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays < 0) {
    return { urgency: 'urgent', label: `已超期 ${Math.abs(diffDays)} 天` }
  }
  if (diffDays === 0) {
    return { urgency: 'urgent', label: '今日截止' }
  }
  if (diffDays <= 3) {
    return { urgency: 'warning', label: `仅剩 ${diffDays} 天` }
  }
  return { urgency: 'normal', label: `还有 ${diffDays} 天` }
}

async function handleSplitSource(payload: { threadId: number; recordId: number }) {
  try {
    await ElMessageBox.confirm(
      '确定将此通知从当前事项中拆分出来并撤销合并吗？拆分后两者将各自恢复为独立事项并拥有各自独立的日程 DDL。',
      '事项拆分撤销',
      {
        confirmButtonText: '确认拆分',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }

  try {
    await assistantApi.splitSource(payload.threadId, payload.recordId)
    ElMessage.success('已成功拆分撤销为独立事项')
    await refreshList()
    if (selectedItem.value) {
      const updated = await assistantApi.get(selectedItem.value.id)
      if (updated) {
        selectedItem.value = updated
      }
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '拆分失败，请重试')
  }
}

async function updateTask(item: AssistantRecord, task: AssistantTask, changes: Partial<AssistantTask>) {
  if (!item.thread?.id) return
  try {
    await assistantApi.updateTask(item.thread.id, task.id, changes)
    await refreshList()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '更新待办失败')
  }
}

async function openSourceRecord(id: number) {
  const record = await assistantApi.get(id)
  if (record) {
    selectedItem.value = record
    sideMode.value = 'detail'
    if (!isLargeScreen.value) drawerVisible.value = true
  }
}

function splitSentences(text: string): string[] {
  return text.split(/(?<=[。！？；])|(?<=[.!?])(?=\s|$)|\r?\n+/u).map(part => part.trim()).filter(Boolean)
}

function splitSourceQuotes(quotes: string[]): string[] {
  return quotes.flatMap(quote => splitSentences(quote))
}

async function refreshSourceSummary(recordId: number) {
  try {
    await assistantApi.refreshSourceSummary(recordId)
    sourceSummaryJobs.value[recordId] = { status: 'running', error: '' }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '无法整理这段信息')
  }
}

async function refreshSourceSummaryJobs() {
  for (const idText of Object.keys(sourceSummaryJobs.value)) {
    const id = Number(idText)
    if (sourceSummaryJobs.value[id]?.status !== 'running') continue
    try {
      const status = await assistantApi.sourceSummaryStatus(id)
      sourceSummaryJobs.value[id] = status
      if (status.status !== 'running') {
        await refreshList()
        if (status.status === 'done') ElMessage.success('这段信息已整理')
        else ElMessage.warning(status.error || '无法整理，请查看原文')
      }
    } catch { /* 下次轮询时重试 */ }
  }
}

async function editTask(item: AssistantRecord, task: AssistantTask) {
  try {
    const title = await ElMessageBox.prompt('修改待办名称', '编辑待办', { inputValue: task.title })
    const date = await ElMessageBox.prompt('截止日期（YYYY-MM-DD，留空表示未确定）', '编辑时间', { inputValue: task.deadline_date || '' })
    const time = await ElMessageBox.prompt('截止时间（HH:MM，留空表示未确定）', '编辑时间', { inputValue: task.deadline_time || '' })
    await updateTask(item, task, { title: title.value, deadline_date: date.value || '', deadline_time: time.value || '' })
  } catch { /* 用户取消 */ }
}

async function mergeItem(item: AssistantRecord) {
  if (!item.thread?.id) return
  try {
    const all = await assistantApi.list('all')
    const candidates = all.filter(r => r.thread?.id && r.thread.id !== item.thread?.id)
    if (!candidates.length) { ElMessage.info('没有其他可合并的事项'); return }
    const labels = candidates.map((r, i) => `${i + 1}. ${r.title}`).join('\n')
    const result = await ElMessageBox.prompt(`输入要合并进当前事项的编号：\n${labels}`, '合并事项', {
      inputPattern: /^\d+$/, inputErrorMessage: '请输入编号', inputPlaceholder: '事项编号',
      customClass: 'assistant-merge-dialog'
    })
    const chosen = candidates[Number(result.value) - 1]
    if (!chosen?.thread?.id) { ElMessage.error('编号不存在'); return }
    await assistantApi.mergeThreads(item.thread.id, chosen.thread.id)
    ElMessage.success('事项已合并，可在卡片上撤销')
    await refreshList()
  } catch (err: any) {
    if (err !== 'cancel' && err !== 'close') ElMessage.error(err?.response?.data?.detail || err?.message || '合并失败')
  }
}

async function undoMerge(item: AssistantRecord) {
  const mergeId = item.thread?.last_manual_merge_id
  if (!mergeId) return
  try {
    await assistantApi.undoMerge(mergeId)
    await refreshList()
    ElMessage.success('已撤销合并')
  } catch (err: any) { ElMessage.error(err?.response?.data?.detail || err?.message || '撤销失败') }
}

async function mergeSuggestion(item: AssistantRecord, candidateId: number) {
  if (!item.thread?.id) return
  try {
    await assistantApi.mergeThreads(item.thread.id, candidateId)
    await refreshList()
    ElMessage.success('已合并事项')
  } catch (err: any) { ElMessage.error(err?.response?.data?.detail || err?.message || '合并失败') }
}

async function dismissSuggestion(item: AssistantRecord, candidateId: number) {
  if (!item.thread?.id) return
  try {
    await assistantApi.dismissSuggestion(item.thread.id, candidateId)
    await refreshList()
  } catch (err: any) { ElMessage.error(err?.response?.data?.detail || err?.message || '操作失败') }
}

async function extractMissingTasks(item: AssistantRecord) {
  if (!item.thread?.id) return
  try {
    ElMessage.info('正在从历史通知中提取缺失待办，请稍候')
    const result = await assistantApi.extractMissingTasks(item.thread.id)
    await refreshList()
    if (result.errors.length) ElMessage.warning(`处理 ${result.processed} 条，${result.errors.length} 条未能处理：${result.errors[0].reason}`)
    else ElMessage.success(`已处理 ${result.processed} 条历史通知`)
  } catch (err: any) { ElMessage.error(err?.response?.data?.detail || err?.message || '提取失败') }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  refreshList()
  runDiagnostics()
  processingTimer = setInterval(() => { refreshProcessing(); refreshSourceSummaryJobs() }, 3000)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (processingTimer) clearInterval(processingTimer)
})

/* ================= 内部右侧面板组件 (SidePanelContent) ================= */
const SidePanelContent = defineComponent({
  name: 'SidePanelContent',
  props: {
    selectedItem: {
      type: Object as () => AssistantRecord | null,
      default: null
    },
    activeMode: {
      type: String as () => 'detail' | 'chat',
      default: 'detail'
    }
  },
  emits: ['update:activeMode', 'close', 'writeNote', 'splitSource', 'retry'],
  setup(props, { emit }) {
    const showErrorDetails = ref(false)
    const chatInput = ref('')
    const chatBusy = ref(false)
    const messages = ref<AssistantChatMessage[]>([
      {
        id: '1',
        role: 'assistant',
        content: '你好！我是你的个人助手。你可以随时向我追问：通知中还缺什么材料、近期的 DDL 安排，或者让我把稍后看收藏按方向分类。',
        created_at: '刚刚'
      }
    ])

    const chatChips = [
      '这次申报还差什么材料？',
      '把这些收藏按方向分一下',
      '近期还有哪些未完成的 DDL？',
      '帮我起草这篇论文的笔记提纲'
    ]

    const chatSources = ref<Array<{ type: string; id: number; title: string }>>([])

    // 还没收到第一个 token 时才显示“思考回答中”，避免和流式气泡重复。
    const showThinking = computed(() => {
      if (!chatBusy.value) return false
      const last = messages.value[messages.value.length - 1]
      return !(last && last.role === 'assistant' && last.content)
    })

    function scrollChatToBottom() {
      nextTick(() => {
        const el = document.querySelector('.chat-scroll-area') as HTMLElement | null
        if (el) el.scrollTop = el.scrollHeight
      })
    }

    function setMode(m: 'detail' | 'chat') {
      emit('update:activeMode', m)
    }

    async function sendChat(textToSend?: string) {
      const q = (textToSend || chatInput.value).trim()
      if (!q || chatBusy.value) return

      messages.value.push({
        id: String(Date.now()),
        role: 'user',
        content: q,
        created_at: '刚刚'
      })

      chatInput.value = ''
      chatBusy.value = true
      chatSources.value = []

      const replyId = String(Date.now() + 1)
      messages.value.push({
        id: replyId,
        role: 'assistant',
        content: '',
        created_at: '刚刚'
      })
      const replyIndex = messages.value.length - 1

      try {
        await assistantApi.chatStream(
          q,
          props.selectedItem?.id,
          {
            onMeta: (sources) => {
              chatSources.value = Array.isArray(sources) ? sources : []
            },
            onDelta: (text) => {
              messages.value[replyIndex].content += text
              scrollChatToBottom()
            }
          },
          { timeoutMs: 120_000 }
        )
        if (!messages.value[replyIndex].content) {
          messages.value[replyIndex].content = '（模型没有返回内容，请重试）'
        }
      } catch (err: any) {
        const reason = err?.message || '回复生成失败，请稍后重试'
        const partial = messages.value[replyIndex].content
        messages.value[replyIndex].content = partial
          ? `${partial}\n\n（生成中断：${reason}）`
          : `⚠️ ${reason}`
      } finally {
        chatBusy.value = false
        scrollChatToBottom()
      }
    }

    function copyRawText() {
      const text = props.selectedItem?.raw_content || props.selectedItem?.content || ''
      if (!text) return
      navigator.clipboard.writeText(text).then(() => {
        ElMessage.success('已复制原文到剪贴板')
      })
    }

    // 生成时间轴节点（多阶段演变通知与真实来源）
    const timelineEvents = computed(() => {
      const item = props.selectedItem
      if (!item) return []

      const events: any[] = []
      const sources = item.thread?.sources || []

      if (sources.length > 0) {
        sources.forEach((src: any, index: number) => {
          let type = 'primary'
          let color = '#409eff'
          let title = `第 ${index + 1} 封通知（初始建档）`

          if (index > 0) {
            type = 'warning'
            color = '#e6a23c'
            if (src.change_type === 'postpone') {
              title = `第 ${index + 1} 封通知（截止时间顺延）`
              type = 'success'
              color = '#67c23a'
            } else if (src.change_type === 'cancel') {
              title = `第 ${index + 1} 封通知（事项取消/终止）`
              type = 'info'
              color = '#909399'
            } else if (src.change_type === 'advance') {
              title = `第 ${index + 1} 封通知（截止时间提前）`
              type = 'danger'
              color = '#f56c6c'
            } else {
              title = `第 ${index + 1} 封通知（规则/内容更新）`
            }
          }

          events.push({
            title,
            time: `导入时间：${src.received_at || item.created_at}`,
            type,
            color,
            desc: src.change_reason || src.summary || (index === 0 ? item.title : '通知内容更新'),
            source: src,
            index,
            canSplit: index > 0 && !!src.record_id && !!item.thread?.id
          })
        })
      } else {
        // 无 sources 时回退单封记录展示
        events.push({
          title: '第 1 封通知送达（初始建档）',
          time: item.created_at,
          type: 'primary',
          color: '#409eff',
          desc: item.summary || `系统收录初始通知：${item.title}`
        })

        if (item.latest_change) {
          events.push({
            title: '通知规则更新',
            time: item.updated_at,
            type: 'warning',
            color: '#e6a23c',
            desc: item.latest_change
          })
        }
      }

      // 若有 DDL，生成关键截止里程碑节点
      if (item.deadline_date) {
        events.push({
          title: '关键截止时间 (DDL)',
          time: `${item.deadline_date} ${item.deadline_time || ''}`.trim(),
          type: 'danger',
          color: '#f56c6c',
          desc: '已同步至日程（截止当日与临近 3 天在日程视图重点标识）'
        })
      }

      return events
    })

    return () => {
      const item = props.selectedItem

      return h('div', { class: 'side-panel' }, [
        // 模式切换顶栏
        h('div', { class: 'side-nav-bar' }, [
          h('div', { class: 'nav-tabs' }, [
            h(
              'button',
              {
                class: ['side-nav-btn', { on: props.activeMode === 'detail' }],
                onClick: () => setMode('detail')
              },
              '详情与演变'
            ),
            h(
              'button',
              {
                class: ['side-nav-btn', { on: props.activeMode === 'chat' }],
                onClick: () => setMode('chat')
              },
              '对话问答'
            )
          ]),
          h(
            ElButton,
            {
              text: true,
              circle: true,
              size: 'small',
              onClick: () => emit('close')
            },
            () => [h(ElIcon, null, () => [h(Close)])]
          )
        ]),

        // 内容区
        props.activeMode === 'detail'
          ? item
            ? h('div', { class: 'detail-scroll-area' }, [
                // 详情头部
                h('div', { class: 'detail-header' }, [
                  h('div', { class: 'detail-kind-row' }, [
                    h('span', { class: ['category-pill', item.category] }, item.category || '记录'),
                    item.category ? h('span', { class: 'category-pill' }, item.category) : null,
                    item.status === 'failed'
                      ? h('span', { class: 'category-pill failed-pill' }, '整理失败')
                      : null,
                    h('span', { class: 'detail-time' }, item.created_at)
                  ]),
                  h('h2', { class: 'detail-title' }, item.title)
                ]),

                // 整理失败面板（显式透出真实错误原因，只提供重试，不做规则降级伪装）
                item.status === 'failed'
                  ? h('div', { class: 'detail-failed-alert' }, [
                      h('div', { class: 'df-alert-title-row' }, [
                        h(ElIcon, { class: 'df-alert-ico' }, () => [h(CircleCloseFilled)]),
                        h('span', { class: 'df-alert-title' }, '整理失败')
                      ]),
                      h('div', { class: 'df-alert-actions' }, [
                        h(
                          ElButton,
                          {
                            size: 'small',
                            type: 'danger',
                            round: true,
                            onClick: () => emit('retry', item)
                          },
                          () => [h(ElIcon, { style: 'margin-right:4px' }, () => [h(RefreshRight)]), '重新处理 (重试)']
                        ),
                        h(
                          ElButton,
                          {
                            size: 'small',
                            text: true,
                            onClick: () => (showErrorDetails.value = !showErrorDetails.value)
                          },
                          () => (showErrorDetails.value ? '收起错误详情 ▲' : '查看错误详情 ▼')
                        )
                      ]),
                      showErrorDetails.value
                        ? h('div', { class: 'df-folded-details' }, [
                            h('div', { class: 'df-error-msg' }, item.error_msg || '模型连接超时或服务未就绪。'),
                            h('div', { class: 'df-tunnel-box' }, [
                              h('div', { class: 'df-tunnel-tip' }, '可在【设置 ➔ AI 服务】中配置本地 Ollama 或外部大模型服务。'),
                              h(
                                ElButton,
                                {
                                  size: 'small',
                                  type: 'primary',
                                  plain: true,
                                  style: 'margin-top:6px;',
                                  onClick: () => {
                                    router.push('/settings')
                                  }
                                },
                                () => [h(ElIcon, { style: 'margin-right:4px' }, () => [h(Setting)]), '前往设置']
                              )
                            ])
                          ])
                        : null
                    ])
                  : null,

                // 核心依据原文段落 (Evidence Quotes)
                (item.quote || (item.evidence_quotes && item.evidence_quotes.length > 0))
                  ? h('div', { class: 'detail-section evidence-quotes-section' }, [
                      h('div', { class: 'section-head' }, [
                        h('span', { class: 'section-title evidence-title' }, [
                          h('span', { style: 'margin-right: 6px' }, '📌'),
                          '核心依据原文段落'
                        ]),
                        h('span', { class: 'evidence-badge' }, '事实依据锚点')
                      ]),
                      h('div', { class: 'evidence-quote-box' }, [
                        item.quote
                          ? h('div', { class: 'primary-quote-item' }, [
                              h('div', { class: 'quote-mark-icon' }, '“'),
                              h('div', { class: 'quote-body' }, [
                                h('div', { class: 'quote-text' }, item.quote),
                                h('div', { class: 'quote-meta' }, [
                                  h('span', { class: 'quote-label' }, '🎯 关键事实与截止时间依据'),
                                  item.deadline_date
                                    ? h(
                                        'span',
                                        { class: 'quote-ddl-hint' },
                                        `提炼截止：${item.deadline_date} ${item.deadline_time || ''}`.trim()
                                      )
                                    : null
                                ])
                              ])
                            ])
                          : null,
                        item.evidence_quotes && item.evidence_quotes.length > 0
                          ? h('div', { class: 'supporting-quotes-list' }, [
                              h('div', { class: 'supporting-title' }, '支撑事实依据：'),
                              item.evidence_quotes.map((q, idx) =>
                                h('div', { key: idx, class: 'supporting-quote-item' }, [
                                  h('span', { class: 'quote-bullet' }, '•'),
                                  h('span', { class: 'supporting-text' }, q)
                                ])
                              )
                            ])
                          : null
                      ])
                    ])
                  : null,

                // 关联附件与凭证区 (Attachments Section)
                item.attachments && item.attachments.length > 0
                  ? h('div', { class: 'detail-section attachments-section' }, [
                      h('div', { class: 'section-head' }, [
                        h('span', { class: 'section-title' }, [
                          h(ElIcon, { style: 'margin-right: 6px; vertical-align: -2px' }, () => [h(Paperclip)]),
                          `关联附件与凭证 (${item.attachments.length})`
                        ])
                      ]),
                      h(
                        'div',
                        { class: 'attachments-list' },
                        item.attachments.map((att, attIdx) => {
                          const authUrl = assistantApi.getAttachmentUrl(item.id, att.filename)
                          const downloadUrl = assistantApi.getAttachmentUrl(item.id, att.filename, { download: true })
                          const ext = (att.original_name || att.filename).split('.').pop()?.toUpperCase() || 'FILE'
                          const humanSize = formatFileSize(att.size)

                          if (att.is_image) {
                            return h('div', { key: attIdx, class: 'attachment-card image-att-card' }, [
                              h('div', { class: 'att-thumb-wrap' }, [
                                h(ElImage, {
                                  src: authUrl,
                                  previewSrcList: [authUrl],
                                  previewTeleported: true,
                                  fit: 'cover',
                                  class: 'att-thumb-img',
                                  alt: att.original_name || att.filename
                                })
                              ]),
                              h('div', { class: 'att-info-wrap' }, [
                                h(
                                  'div',
                                  { class: 'att-name', title: att.original_name || att.filename },
                                  att.original_name || att.filename
                                ),
                                h('div', { class: 'att-meta-row' }, [
                                  h('span', { class: 'att-type-badge badge-img' }, '图片'),
                                  h('span', { class: 'att-size' }, humanSize)
                                ])
                              ]),
                              h('div', { class: 'att-actions-wrap' }, [
                                h(
                                  ElButton,
                                  {
                                    size: 'small',
                                    type: 'primary',
                                    text: true,
                                    onClick: () => window.open(authUrl, '_blank')
                                  },
                                  () => [h(ElIcon, { style: 'margin-right:2px' }, () => [h(View)]), '新标签打开']
                                ),
                                h(
                                  ElButton,
                                  {
                                    size: 'small',
                                    text: true,
                                    onClick: () => {
                                      const a = document.createElement('a')
                                      a.href = downloadUrl
                                      a.download = att.original_name || att.filename
                                      a.click()
                                    }
                                  },
                                  () => [h(ElIcon, { style: 'margin-right:2px' }, () => [h(Download)]), '下载']
                                )
                              ])
                            ])
                          } else {
                            const isPdf = ext === 'PDF'
                            const badgeClass = isPdf ? 'badge-pdf' : ['DOC', 'DOCX'].includes(ext) ? 'badge-doc' : 'badge-file'
                            return h('div', { key: attIdx, class: 'attachment-card doc-att-card' }, [
                              h('div', { class: 'att-doc-icon-wrap' }, [
                                h('span', { class: ['att-ext-badge', badgeClass] }, ext)
                              ]),
                              h('div', { class: 'att-info-wrap' }, [
                                h(
                                  'div',
                                  { class: 'att-name', title: att.original_name || att.filename },
                                  att.original_name || att.filename
                                ),
                                h('div', { class: 'att-meta-row' }, [
                                  h('span', { class: 'att-size' }, humanSize)
                                ])
                              ]),
                              h('div', { class: 'att-actions-wrap' }, [
                                h(
                                  ElButton,
                                  {
                                    size: 'small',
                                    type: 'primary',
                                    text: true,
                                    onClick: () => window.open(authUrl, '_blank')
                                  },
                                  () => [h(ElIcon, { style: 'margin-right:2px' }, () => [h(View)]), isPdf ? '在线预览' : '打开查看']
                                ),
                                h(
                                  ElButton,
                                  {
                                    size: 'small',
                                    text: true,
                                    onClick: () => {
                                      const a = document.createElement('a')
                                      a.href = downloadUrl
                                      a.download = att.original_name || att.filename
                                      a.click()
                                    }
                                  },
                                  () => [h(ElIcon, { style: 'margin-right:2px' }, () => [h(Download)]), '下载']
                                )
                              ])
                            ])
                          }
                        })
                      )
                    ])
                  : null,

                // 原文解密展示区
                h('div', { class: 'detail-section' }, [
                  h('div', { class: 'section-head' }, [
                    h('span', { class: 'section-title' }, '原文证据快照'),
                    h(
                      ElButton,
                      { size: 'small', text: true, onClick: copyRawText },
                      () => '复制原文'
                    )
                  ]),
                  h('div', { class: 'raw-content-box' }, [
                    item.image_preview
                      ? h('img', { src: item.image_preview, class: 'detail-img-preview' })
                      : null,
                    h('pre', { class: 'raw-text' }, item.raw_content || item.content || item.summary || '暂无原文快照')
                  ])
                ]),

                // 通知演变时间轴 (仅通知事项展示)
                Boolean(item.thread_id || (item.thread?.sources && item.thread.sources.length > 1))
                  ? h('div', { class: 'detail-section' }, [
                      h('div', { class: 'section-head' }, [
                        h('span', { class: 'section-title' }, '通知演变历程')
                      ]),
                      h('div', { class: 'timeline-wrap' }, [
                        h(
                          ElTimeline,
                          null,
                          () =>
                            timelineEvents.value.map((ev, i) =>
                              h(
                                ElTimelineItem,
                                {
                                  key: i,
                                  timestamp: ev.time,
                                  type: ev.type,
                                  color: ev.color,
                                  hollow: i > 0
                                },
                                () => [
                                  h('div', { class: 'tl-item-title' }, ev.title),
                                  h('div', { class: 'tl-item-desc' }, ev.desc),
                                  ev.canSplit
                                    ? h('div', { class: 'tl-split-action' }, [
                                        h(
                                          ElButton,
                                          {
                                            size: 'small',
                                            type: 'warning',
                                            plain: true,
                                            round: true,
                                            onClick: () =>
                                              emit('splitSource', {
                                                threadId: item.thread?.id,
                                                recordId: ev.source.record_id
                                              })
                                          },
                                          () => '⚠️ 并非同一事项？拆分撤销'
                                        )
                                      ])
                                    : null
                                ]
                              )
                            )
                        )
                      ])
                    ])
                  : null,

                // 快捷操作
                h('div', { class: 'detail-footer-ops' }, [
                  true
                    ? h(
                        ElButton,
                        {
                          type: 'primary',
                          round: true,
                          size: 'small',
                          onClick: () => emit('writeNote', item)
                        },
                        () => [h(ElIcon, { style: 'margin-right:4px' }, () => [h(EditPen)]), '以此为基础写笔记']
                      )
                    : null
                ])
              ])
            : h('div', { class: 'side-empty' }, [
                h(ElIcon, { size: 36, class: 'empty-ico' }, () => [h(Document)]),
                h('div', { class: 'empty-txt' }, '请在左侧点击任一张卡片查看原文与演变历程')
              ])
          : // 对话问答模式
            h('div', { class: 'chat-scroll-area' }, [
              h('div', { class: 'chat-messages' }, [
                messages.value.map((m) =>
                  h(
                    'div',
                    { key: m.id, class: ['chat-bubble-row', m.role] },
                    [
                      h(
                        'div',
                        { class: 'avatar-col' },
                        m.role === 'assistant'
                          ? h('span', { class: 'asst-avatar' }, '助')
                          : h(ElIcon, { class: 'user-avatar' }, () => [h(UserFilled)])
                      ),
                      h('div', { class: 'bubble-content' }, m.content)
                    ]
                  )
                ),
                chatSources.value.length
                  ? h('div', { class: 'chat-sources' }, [
                      h('span', { class: 'src-label' }, '依据：'),
                      ...chatSources.value.slice(0, 4).map((s) =>
                        h('span', { key: `${s.type}-${s.id}`, class: 'src-chip' }, s.title)
                      )
                    ])
                  : null,
                showThinking.value
                  ? h('div', { class: 'chat-bubble-row assistant' }, [
                      h('span', { class: 'asst-avatar' }, '助'),
                      h('div', { class: 'bubble-content loading' }, '思考回答中...')
                    ])
                  : null
              ]),

              // 快捷建议问题
              h('div', { class: 'chat-chips-area' }, [
                chatChips.map((chip) =>
                  h(
                    'button',
                    {
                      key: chip,
                      type: 'button',
                      class: 'chat-chip',
                      onClick: () => sendChat(chip)
                    },
                    chip
                  )
                )
              ]),

              // 输入栏
              h('div', { class: 'chat-input-bar' }, [
                h(ElInput, {
                  modelValue: chatInput.value,
                  'onUpdate:modelValue': (val: string) => (chatInput.value = val),
                  placeholder: '输入问题，如：还差什么材料？',
                  size: 'default',
                  onKeydown: (e: KeyboardEvent) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      sendChat()
                    }
                  }
                }),
                h(
                  ElButton,
                  {
                    type: 'primary',
                    loading: chatBusy.value,
                    onClick: () => sendChat()
                  },
                  () => '发送'
                )
              ])
            ])
      ])
    }
  }
})
</script>

<style scoped>
.assistant-page {
  display: flex;
  gap: 16px;
  width: 100%;
  max-width: 1480px;
  margin: 0 auto;
  min-height: calc(100vh - 84px);
  padding-bottom: 24px;
}

.assistant-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.assistant-aside {
  width: 420px;
  flex-shrink: 0;
  height: calc(100vh - 100px);
  position: sticky;
  top: 80px;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 顶部标题栏 */
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-radius: 12px;
}

.head-title {
  font-size: 20px;
  font-weight: 700;
}

.head-sub {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 顶部输入区 */
.input-card {
  padding: 16px 20px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.input-card.drag-over {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 16px rgba(64, 158, 255, 0.25);
}

.input-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.kind-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switcher-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.shortcut-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.preview-strip {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.image-preview-box {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
}

.pasted-thumb {
  height: 48px;
  width: auto;
  border-radius: 4px;
  object-fit: cover;
}

.preview-tag {
  font-size: 12px;
  margin-left: 8px;
  color: var(--el-text-color-regular);
}

.del-preview-btn {
  margin-left: 8px;
}

.file-preview-box {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  font-size: 13px;
}

.note-intent-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quick-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.quick-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.quick-tag-chip {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-chip:hover {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
}

.input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 4px;
}

.drop-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.file-upload-btn {
  color: var(--el-color-primary);
  cursor: pointer;
  margin-left: 6px;
  text-decoration: underline;
}

.hidden-file-input {
  display: none;
}

/* 筛选与搜索 */
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-radius: 10px;
  gap: 16px;
}

.filter-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.filter-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.tab-badge-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-dot {
  background: var(--el-color-danger);
  color: #fff;
  border-radius: 10px;
  font-size: 11px;
  padding: 0 5px;
  line-height: 16px;
}

.search-wrap {
  width: 260px;
}

/* 记录卡片列表 */
.record-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.collection-group { padding: 12px; border-radius: 16px; }
.collection-heading { cursor: pointer; font-weight: 700; padding: 6px 4px; }
.collection-heading span { color: var(--txt2); font-size: 12px; font-weight: 400; margin-left: 8px; }
.collection-group[open] .record-card { margin-top: 10px; }

.record-card {
  padding: 16px 18px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: transform 0.15s, border-color 0.2s, box-shadow 0.2s;
  border: 1px solid transparent;
}

.record-card:hover {
  transform: translateY(-2px);
  border-color: var(--el-border-color-darker);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}

.record-card.active {
  border-color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.04);
}

.record-card.is-archived {
  opacity: 0.65;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.kind-tag-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kind-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.kind-badge.notice {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  border: 1px solid var(--el-color-danger-light-7);
}

.kind-badge.later {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
}

.category-pill,
.noted-pill {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-regular);
}

.noted-pill {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.wb-pill {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
  display: inline-flex;
  align-items: center;
  gap: 3px;
  max-width: 140px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ddl-pill {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
}

.ddl-pill.urgent {
  background: var(--el-color-danger);
  color: #fff;
  animation: pulse-danger 2s infinite;
}

.ddl-pill.warning {
  background: var(--el-color-warning);
  color: #fff;
}

.ddl-pill.normal {
  background: var(--el-color-info-light-7);
  color: var(--el-text-color-primary);
}

@keyframes pulse-danger {
  0% { opacity: 1; }
  50% { opacity: 0.8; }
  100% { opacity: 1; }
}

.card-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.4;
}

/* 变更提示条 */
.latest-change-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(230, 162, 60, 0.12);
  border-left: 3px solid var(--el-color-warning);
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.banner-icon {
  color: var(--el-color-warning);
}

.banner-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }

.card-summary {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.deadline-section { padding: 12px 14px; border-radius: 9px; background: var(--el-fill-color-light); display: flex; flex-direction: column; gap: 6px; }
.deadline-heading { color: var(--el-text-color-primary); font-size: 13px; font-weight: 600; }
.deadline-line { color: var(--el-text-color-regular); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.source-messages { display: flex; flex-direction: column; gap: 20px; }
.source-message { display: flex; flex-direction: column; gap: 8px; }
.source-origin { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 9px 12px; border: 1px solid var(--el-border-color); border-radius: 8px; cursor: pointer; }
.source-origin-label { flex-shrink: 0; color: var(--el-color-primary); font-size: 12px; font-weight: 600; }
.source-origin-title { flex: 1; color: var(--el-text-color-primary); font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.source-open { padding: 0; border: 0; background: transparent; color: var(--el-color-primary); font-size: 12px; cursor: pointer; }
.source-message-box { padding: 12px 14px; background: var(--el-fill-color-light); border-radius: 8px; color: var(--el-text-color-primary); font-size: 13px; line-height: 1.75; }
.source-sentence, .source-evidence-sentence { white-space: pre-wrap; overflow-wrap: anywhere; }
.source-sentence + .source-sentence, .source-evidence-sentence + .source-evidence-sentence { margin-top: 5px; }
.source-summary-pending { color: var(--el-text-color-secondary); display: flex; align-items: center; gap: 8px; }
.source-evidence-box { padding: 11px 14px; border-left: 3px solid var(--el-color-primary-light-5); background: var(--el-fill-color-blank); border-radius: 0 8px 8px 0; }
.source-evidence-label { color: var(--el-color-primary); font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.source-evidence-sentence { color: var(--el-text-color-regular); font-size: 12px; line-height: 1.7; }
.source-evidence-missing { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
:global(html.theme-dark) .source-origin { background: rgba(255, 255, 255, 0.06); border-color: rgba(255, 255, 255, 0.2); }
:global(html.theme-dark) .source-origin-title,
:global(html.theme-dark) .card-title { color: #eef2fb; }

.reason-box {
  background: rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  display: flex;
  gap: 6px;
}

.reason-label {
  color: var(--el-color-primary);
  font-weight: 600;
  flex-shrink: 0;
}

.reason-content {
  color: var(--el-text-color-regular);
}


.card-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}

.tags-cluster {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-item {
  color: var(--el-color-primary);
  opacity: 0.85;
}

.source-clue {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--el-text-color-secondary);
}

.source-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.source-link:hover {
  text-decoration: underline;
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 10px;
}

/* 空状态 */
.empty-state {
  padding: 48px 24px;
  border-radius: 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon {
  color: var(--el-text-color-secondary);
  opacity: 0.4;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.empty-sub {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

/* 右侧面板内部样式 (SidePanelContent) */
:deep(.side-panel) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

:deep(.side-nav-bar) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

:deep(.nav-tabs) {
  display: flex;
  gap: 4px;
  background: var(--el-fill-color);
  padding: 3px;
  border-radius: 8px;
}

:deep(.side-nav-btn) {
  border: none;
  background: transparent;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.2s;
}

:deep(.side-nav-btn.on) {
  background: var(--el-bg-color);
  color: var(--el-color-primary);
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

:deep(.detail-scroll-area) {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

:deep(.detail-header) {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

:deep(.detail-kind-row) {
  display: flex;
  align-items: center;
  gap: 6px;
}

:deep(.detail-time) {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}

:deep(.detail-title) {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.4;
}

:deep(.detail-section) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.section-head) {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.section-title) {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

:deep(.raw-content-box) {
  background: var(--el-fill-color-dark);
  border-radius: 8px;
  padding: 12px;
  max-height: 260px;
  overflow-y: auto;
}

:deep(.detail-img-preview) {
  max-width: 100%;
  border-radius: 6px;
  margin-bottom: 8px;
}

:deep(.raw-text) {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

:deep(.timeline-wrap) {
  padding: 8px 4px;
}

:deep(.tl-item-title) {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

:deep(.tl-item-desc) {
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-top: 4px;
}

:deep(.tl-split-action) {
  margin-top: 6px;
}

:deep(.wb-link-box) {
  padding: 2px 0;
}

:deep(.detail-footer-ops) {
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

:deep(.side-empty) {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  text-align: center;
  color: var(--el-text-color-secondary);
}

:deep(.empty-ico) {
  opacity: 0.35;
  margin-bottom: 12px;
}

:deep(.empty-txt) {
  font-size: 13px;
}

/* 对话问答样式 */
:deep(.chat-scroll-area) {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: calc(100% - 50px);
  padding: 12px 14px;
}

:deep(.chat-messages) {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

:deep(.chat-bubble-row) {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

:deep(.chat-bubble-row.user) {
  flex-direction: row-reverse;
}

:deep(.asst-avatar) {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

:deep(.user-avatar) {
  font-size: 24px;
  color: var(--el-text-color-regular);
  flex-shrink: 0;
}

:deep(.bubble-content) {
  max-width: 82%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

:deep(.chat-bubble-row.assistant .bubble-content) {
  background: var(--el-fill-color);
  color: var(--el-text-color-primary);
  border-top-left-radius: 2px;
}

:deep(.chat-bubble-row.user .bubble-content) {
  background: var(--el-color-primary);
  color: #fff;
  border-top-right-radius: 2px;
}

:deep(.chat-sources) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 2px 0 0 36px;
  font-size: 11px;
}

:deep(.chat-sources .src-label) {
  color: var(--el-text-color-secondary);
}

:deep(.chat-sources .src-chip) {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.chat-chips-area) {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 8px 0;
  margin-top: 4px;
}

:deep(.chat-chip) {
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 12px;
  padding: 4px 10px;
  font-size: 11px;
  white-space: nowrap;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.2s;
}

:deep(.chat-chip:hover) {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

:deep(.chat-input-bar) {
  display: flex;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 整理失败醒目样式 */
.failed-pill {
  background: var(--el-color-danger-light-9) !important;
  color: var(--el-color-danger) !important;
  border: 1px solid var(--el-color-danger-light-7) !important;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
}

.record-card.is-failed {
  border-color: rgba(239, 68, 68, 0.45) !important;
  background: rgba(239, 68, 68, 0.03) !important;
}

.card-failed-warning {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
  padding: 8px 12px;
  margin: 6px 0;
}

.failed-warning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  font-size: 13px;
}

.warning-icon {
  font-size: 16px;
  color: var(--el-color-danger);
}

.failed-warning-desc {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  word-break: break-all;
}

/* 详情侧栏失败警示 */
:deep(.detail-failed-alert) {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 14px;
}

:deep(.df-alert-title-row) {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

:deep(.df-alert-ico) {
  font-size: 18px;
}

:deep(.df-alert-actions) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

:deep(.df-folded-details) {
  margin-top: 10px;
  padding: 10px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  border: 1px dashed var(--el-border-color);
  font-size: 12px;
}

:deep(.df-error-msg) {
  color: var(--el-color-danger);
  margin-bottom: 8px;
  word-break: break-all;
}

:deep(.df-tunnel-box) {
  background: rgba(0, 0, 0, 0.25);
  padding: 8px 10px;
  border-radius: 6px;
}

:deep(.df-tunnel-tip) {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  margin-bottom: 4px;
}

:deep(.df-tunnel-code) {
  display: block;
  padding: 6px 8px;
  background: #18181b;
  color: #4ade80;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
}

/* 诊断弹窗样式 */
.diag-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.diag-error-box {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
  padding: 12px;
}

.diag-error-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  font-size: 13px;
  margin-bottom: 6px;
}

.diag-error-detail {
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  margin-bottom: 8px;
  word-break: break-all;
}

.tunnel-hint-card {
  background: rgba(0, 0, 0, 0.25);
  border-radius: 6px;
  padding: 8px 10px;
}

.tunnel-hint-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.tunnel-cmd-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.tunnel-cmd-row code {
  background: #18181b;
  color: #4ade80;
  padding: 4px 8px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  flex: 1;
  word-break: break-all;
}

/* 附件徽章与引用原句样式 (卡片端) */
.attachment-pill {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
  font-weight: 500;
}

.card-quote-snippet {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(64, 158, 255, 0.06);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 6px;
}

.quote-tag {
  color: var(--el-color-primary);
  font-weight: 600;
  white-space: nowrap;
}

.quote-snippet-text {
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 侧边栏核心依据原文段落样式 */
:deep(.evidence-quotes-section) {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 10px;
  padding: 12px;
}

:deep(.evidence-title) {
  display: flex;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-color-primary);
}

:deep(.evidence-badge) {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-color-primary);
  color: #fff;
}

:deep(.evidence-quote-box) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

:deep(.primary-quote-item) {
  display: flex;
  gap: 8px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

:deep(.quote-mark-icon) {
  font-size: 24px;
  line-height: 1;
  font-family: Georgia, serif;
  color: var(--el-color-primary);
  opacity: 0.7;
}

:deep(.quote-body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

:deep(.quote-text) {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.6;
  color: var(--el-text-color-primary);
  white-space: pre-wrap;
}

:deep(.quote-meta) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
}

:deep(.quote-label) {
  color: var(--el-color-primary);
  font-weight: 600;
}

:deep(.quote-ddl-hint) {
  color: var(--el-color-danger);
  font-weight: 500;
  background: var(--el-color-danger-light-9);
  padding: 1px 6px;
  border-radius: 4px;
}

:deep(.supporting-quotes-list) {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 6px;
  padding: 8px 10px;
}

:deep(.supporting-title) {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}

:deep(.supporting-quote-item) {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
}

:deep(.quote-bullet) {
  color: var(--el-color-primary);
}

:deep(.supporting-text) {
  flex: 1;
}

/* 侧边栏关联附件与凭证区样式 */
:deep(.attachments-section) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.attachments-list) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.attachment-card) {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  transition: all 0.2s ease;
}

:deep(.attachment-card:hover) {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}

:deep(.att-thumb-wrap) {
  width: 44px;
  height: 44px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--el-fill-color);
  border: 1px solid var(--el-border-color-light);
}

:deep(.att-thumb-img) {
  width: 100%;
  height: 100%;
  cursor: pointer;
}

:deep(.att-doc-icon-wrap) {
  width: 44px;
  height: 44px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--el-fill-color);
  border: 1px solid var(--el-border-color-light);
}

:deep(.att-ext-badge) {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 5px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}

:deep(.badge-pdf) {
  background: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fde2e2;
}

:deep(.badge-doc) {
  background: #ecf5ff;
  color: #409eff;
  border: 1px solid #d9ecff;
}

:deep(.badge-file) {
  background: #f4f4f5;
  color: #909399;
  border: 1px solid #e9e9eb;
}

:deep(.att-info-wrap) {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

:deep(.att-name) {
  font-size: 13px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.att-meta-row) {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

:deep(.att-type-badge) {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
}

:deep(.badge-img) {
  background: #f0f9eb;
  color: #67c23a;
  border: 1px solid #e1f3d8;
}

:deep(.att-size) {
  color: var(--el-text-color-secondary);
}

:deep(.att-actions-wrap) {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
</style>
