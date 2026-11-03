<template>
  <teleport to="body">
    <transition name="qc-fade">
      <div
        v-if="visible"
        class="qc-overlay"
        tabindex="-1"
        @click.self="close"
        @keydown="onModalKeydown"
      >
        <div class="qc-dialog glass" role="dialog" aria-modal="true" aria-label="闪念随手记录">
          <!-- 头部：标题与目标投递切换 -->
          <div class="qc-header">
            <div class="qc-title">
              <span class="qc-badge">
                <el-icon :size="15"><Lightning /></el-icon>
              </span>
              <span class="qc-title-text">闪念随手记</span>
            </div>

            <!-- 目标投递选择器 -->
            <div class="qc-targets" role="tablist" aria-label="投递目标">
              <button
                type="button"
                class="qc-target-btn"
                :class="{ active: target === 'card' }"
                role="tab"
                :aria-selected="target === 'card'"
                title="存入笔记·博客速记小卡片，随时查看"
                @click="target = 'card'"
              >
                <el-icon :size="13"><Postcard /></el-icon>
                <span>速记卡片</span>
              </button>
              <button
                type="button"
                class="qc-target-btn"
                :class="{ active: target === 'assistant' }"
                role="tab"
                :aria-selected="target === 'assistant'"
                title="送入智能助手，AI 自动提取待办或归档稍后读"
                @click="target = 'assistant'"
              >
                <el-icon :size="13"><ChatDotRound /></el-icon>
                <span>智能助手</span>
              </button>
              <button
                type="button"
                class="qc-target-btn"
                :class="{ active: target === 'daynote' }"
                role="tab"
                :aria-selected="target === 'daynote'"
                title="追加至首页今日安排随手记"
                @click="target = 'daynote'"
              >
                <el-icon :size="13"><Calendar /></el-icon>
                <span>今日安排</span>
              </button>
            </div>

            <button
              type="button"
              class="qc-close-btn"
              title="关闭 (Esc)"
              aria-label="关闭"
              @click="close"
            >
              <el-icon :size="16"><Close /></el-icon>
            </button>
          </div>

          <!-- 核心内容区 -->
          <div class="qc-body" @dragover.prevent @drop="onDrop">
            <!-- 快速多行文本域 -->
            <textarea
              ref="textareaRef"
              v-model="text"
              class="qc-textarea"
              :placeholder="placeholderText"
              rows="3"
              @input="onTextareaInput"
              @paste="onPaste"
            />

            <!-- 暂存截图预览卡片 -->
            <div v-if="pastedImage" class="qc-image-preview">
              <div class="qc-image-thumb-wrap">
                <img :src="pastedImage.preview" :alt="pastedImage.name" class="qc-image-thumb" />
              </div>
              <div class="qc-image-meta">
                <div class="qc-image-name" :title="pastedImage.name">{{ pastedImage.name }}</div>
                <div class="qc-image-sub">
                  <span class="qc-image-size">{{ pastedImage.sizeText }}</span>
                  <span class="qc-image-tag">已捕获截图</span>
                </div>
              </div>
              <button
                type="button"
                class="qc-image-remove"
                title="移除截图"
                aria-label="移除截图"
                @click="removeImage"
              >
                <el-icon :size="14"><Close /></el-icon>
              </button>
            </div>

            <!-- 附加选项（链接 / 来源 / 备注） -->
            <div v-if="showExtraFields" class="qc-extra-fields">
              <div class="qc-field-row">
                <el-input
                  v-model="url"
                  size="small"
                  placeholder="关联网址链接 (http/https)..."
                  clearable
                >
                  <template #prefix>
                    <el-icon><Link /></el-icon>
                  </template>
                </el-input>
              </div>
              <div class="qc-field-row qc-field-duo">
                <el-input
                  v-model="source"
                  size="small"
                  placeholder="来源 (如: 网页采集 / 读书 / 灵感)"
                  clearable
                >
                  <template #prefix>
                    <el-icon><Document /></el-icon>
                  </template>
                </el-input>
                <el-input
                  v-model="userNote"
                  size="small"
                  placeholder="备注 / 补充说明"
                  clearable
                >
                  <template #prefix>
                    <el-icon><EditPen /></el-icon>
                  </template>
                </el-input>
              </div>
            </div>

            <!-- 快速标签胶囊栏 -->
            <div class="qc-capsules-bar">
              <div class="qc-capsules-label">常用标签:</div>
              <div class="qc-capsules-list">
                <button
                  v-for="tag in quickTags"
                  :key="tag"
                  type="button"
                  class="qc-capsule"
                  :class="{ active: text.includes(tag) }"
                  @click="addTag(tag)"
                >
                  {{ tag }}
                </button>
              </div>
              <button
                type="button"
                class="qc-extra-toggle"
                :class="{ active: showExtraFields || url || source || userNote }"
                title="展开来源与备注填写"
                @click="showExtraFields = !showExtraFields"
              >
                <el-icon :size="13"><Operation /></el-icon>
                <span>{{ showExtraFields ? '收起选项' : '来源 / 链接' }}</span>
              </button>
            </div>
          </div>

          <!-- 底部工具与提交操作栏 -->
          <div class="qc-footer">
            <div class="qc-hints">
              <span class="qc-hint-key"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> 快速收录</span>
              <span class="qc-hint-sep">·</span>
              <span class="qc-hint-tip">支持剪贴板图片 <kbd>Ctrl+V</kbd> 自动暂存</span>
            </div>

            <div class="qc-actions">
              <button
                type="button"
                class="qc-btn-cancel"
                @click="close"
              >
                取消
              </button>
              <button
                type="button"
                class="qc-btn-submit"
                :disabled="saving"
                @click="submitCapture"
              >
                <el-icon v-if="saving" class="is-loading"><Loading /></el-icon>
                <el-icon v-else><Check /></el-icon>
                <span>{{ submitBtnText }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import {
  Lightning, Postcard, ChatDotRound, Calendar, Close,
  Link, Document, EditPen, Operation, Check, Loading,
} from '@element-plus/icons-vue'
import { http } from '../api/client'
import { workbenchApi, dayNoteApi } from '../api/workbench'
import { assistantApi } from '../api/assistant'

const props = withDefaults(defineProps<{
  modelValue?: boolean
}>(), {
  modelValue: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'saved'): void
}>()

const visible = ref(false)
const target = ref<'card' | 'assistant' | 'daynote'>('card')
const text = ref('')
const url = ref('')
const source = ref('')
const userNote = ref('')
const showExtraFields = ref(false)
const saving = ref(false)

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const previousActive = ref<HTMLElement | null>(null)

interface PastedImageInfo {
  file: File
  preview: string
  name: string
  sizeText: string
}
const pastedImage = ref<PastedImageInfo | null>(null)

const quickTags = ['#灵感', '#待办', '#稍后看', '#随手记', '#工作', '#学习']

const placeholderText = computed(() => {
  if (target.value === 'workbench') {
    return '随手记下当前闪念、待办想法或粘贴截图... (存入工作台收集箱)'
  }
  if (target.value === 'assistant') {
    return '将文字、网页或截图发给助手，AI 自动提取关键信息与待办...'
  }
  return '输入今天的新增安排或备忘，将直接追加至首页今日清单...'
})

const submitBtnText = computed(() => {
  if (saving.value) return '收录中...'
  if (target.value === 'workbench') return '存入收集箱'
  if (target.value === 'assistant') return '发送给助手'
  return '加入今日安排'
})

function onTextareaInput() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const targetH = Math.max(100, Math.min(el.scrollHeight, 280))
  el.style.height = `${targetH}px`
}

function addTag(tag: string) {
  const el = textareaRef.value
  if (!el) {
    text.value = text.value ? `${text.value} ${tag} ` : `${tag} `
    return
  }
  const start = el.selectionStart || text.value.length
  const end = el.selectionEnd || text.value.length
  const before = text.value.substring(0, start)
  const after = text.value.substring(end)
  const spaceBefore = before.length && !before.endsWith(' ') && !before.endsWith('\n') ? ' ' : ''
  const spaceAfter = !after.startsWith(' ') && !after.startsWith('\n') ? ' ' : ''
  text.value = `${before}${spaceBefore}${tag}${spaceAfter}${after}`

  nextTick(() => {
    el.focus()
    const newPos = start + spaceBefore.length + tag.length + spaceAfter.length
    el.setSelectionRange(newPos, newPos)
    onTextareaInput()
  })
}

function setUploadedImage(file: File) {
  const preview = URL.createObjectURL(file)
  const sizeKb = Math.round(file.size / 1024)
  const sizeText = sizeKb > 1024 ? `${(sizeKb / 1024).toFixed(1)} MB` : `${sizeKb} KB`
  pastedImage.value = {
    file,
    preview,
    name: file.name || `screenshot_${new Date().toISOString().slice(11, 19).replace(/:/g, '')}.png`,
    sizeText,
  }
}

function removeImage() {
  if (pastedImage.value?.preview) {
    URL.revokeObjectURL(pastedImage.value.preview)
  }
  pastedImage.value = null
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        setUploadedImage(file)
        // 剪贴板中纯图片时阻止粘贴无用字符
        if (!e.clipboardData.getData('text/plain')) {
          e.preventDefault()
        }
        return
      }
    }
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const f = files[0]
    if (f.type.startsWith('image/')) {
      setUploadedImage(f)
    }
  }
}

function onModalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    e.preventDefault()
    close()
    return
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.stopPropagation()
    e.preventDefault()
    submitCapture()
  }
}

async function submitCapture() {
  const rawText = text.value.trim()
  const rawUrl = url.value.trim()
  const rawSource = source.value.trim()
  const rawNote = userNote.value.trim()

  if (!rawText && !pastedImage.value && !rawUrl) {
    ElMessage.warning('请记录文字、粘贴截图或输入链接')
    textareaRef.value?.focus()
    return
  }

  saving.value = true
  try {
    let uploadedImgUrl = ''
    if (pastedImage.value?.file && target.value !== 'assistant') {
      // 真实后端上传图片至 /notes/images
      const fd = new FormData()
      fd.append('file', pastedImage.value.file)
      const res = await http.post<{ url: string }>('/notes/images', fd)
      uploadedImgUrl = res.url
    }

    if (target.value === 'card') {
      let finalText = rawText
      if (uploadedImgUrl) {
        const imgTag = `\n\n![${pastedImage.value?.name || '截图'}](${uploadedImgUrl})`
        finalText = finalText ? `${finalText}${imgTag}` : `![截图](${uploadedImgUrl})`
      }
      if (rawUrl) {
        finalText = `${finalText}\n\n链接: ${rawUrl}`
      }
      if (rawNote) {
        finalText = `${finalText}\n\n备注: ${rawNote}`
      }

      const firstLine = finalText.split('\n')[0].replace(/^#+\s*/, '').trim()
      const title = firstLine.slice(0, 50) || `速记 ${new Date().toLocaleString('zh-CN', { hour12: false })}`
      const extractedTags = (finalText.match(/#([\w\u4e00-\u9fa5]+)/g) || []).map((t) => t.slice(1))

      await http.post('/notes', {
        title,
        type: 'note',
        fmt: 'card',
        folder: '',
        tags: extractedTags,
        summary: finalText.slice(0, 200),
        content: finalText,
      })

      ElNotification({
        title: '已存入速记卡片',
        message: '卡片已直接加入笔记·博客列表',
        type: 'success',
        position: 'bottom-right',
        duration: 2600,
      })
    } else if (target.value === 'assistant') {
      await assistantApi.create({
        kind: 'auto',
        content: rawText,
        file: pastedImage.value?.file,
        image_preview: pastedImage.value?.preview,
        user_note: rawNote,
        url: rawUrl,
      })

      ElNotification({
        title: '已发送至智能助手',
        message: '助手正自动提取分析关键待办与信息',
        type: 'success',
        position: 'bottom-right',
        duration: 2600,
      })
    } else if (target.value === 'daynote') {
      const dayRes = await dayNoteApi.get()
      const current = (dayRes.content || '').trim()

      let itemLine = rawText
      if (uploadedImgUrl) {
        itemLine = `${itemLine} ![截图](${uploadedImgUrl})`
      }
      if (rawNote) {
        itemLine = `${itemLine} （${rawNote}）`
      }
      if (rawUrl) {
        itemLine = `${itemLine} ${rawUrl}`
      }
      const line = `- [ ] ${itemLine.trim()}`
      const updated = current ? `${current}\n${line}` : line
      await dayNoteApi.put(updated)

      ElNotification({
        title: '已添加到今日安排',
        message: '已作为待办事项追加至首页随手清单',
        type: 'success',
        position: 'bottom-right',
        duration: 2600,
      })
    }

    reset()
    close()
    emit('saved')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '保存失败，请重试')
  } finally {
    saving.value = false
  }
}

function reset() {
  text.value = ''
  url.value = ''
  source.value = ''
  userNote.value = ''
  showExtraFields.value = false
  removeImage()
}

function open() {
  previousActive.value = document.activeElement as HTMLElement | null
  visible.value = true
  emit('update:modelValue', true)
  nextTick(() => {
    onTextareaInput()
    textareaRef.value?.focus()
  })
}

function close() {
  visible.value = false
  emit('update:modelValue', false)
  nextTick(() => {
    if (previousActive.value && typeof previousActive.value.focus === 'function') {
      previousActive.value.focus()
    }
  })
}

defineExpose({
  open,
  close,
})
</script>

<style scoped>
/* 浮层淡入与缩放动画 */
.qc-fade-enter-active,
.qc-fade-leave-active {
  transition: opacity 0.18s ease;
}
.qc-fade-enter-active .qc-dialog,
.qc-fade-leave-active .qc-dialog {
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.18s ease;
}
.qc-fade-enter-from,
.qc-fade-leave-to {
  opacity: 0;
}
.qc-fade-enter-from .qc-dialog,
.qc-fade-leave-to .qc-dialog {
  opacity: 0;
  transform: scale(0.96) translateY(-8px);
}

/* 遮罩 */
.qc-overlay {
  position: fixed;
  inset: 0;
  z-index: 2100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  outline: none;
}

/* 浮窗主体卡片：毛玻璃质感 */
.qc-dialog {
  width: 100%;
  max-width: 630px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 24px 64px -12px rgba(15, 23, 42, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

html.theme-dark .qc-dialog {
  background: rgba(26, 26, 32, 0.92);
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 24px 64px -12px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255, 255, 255, 0.06);
}

/* 顶部栏 */
.qc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}

.qc-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.qc-badge {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--acc-grad);
  color: #fff;
  box-shadow: 0 3px 8px rgba(139, 92, 246, 0.35);
}
.qc-title-text {
  font-size: 14px;
  font-weight: 700;
  color: var(--txt1);
  letter-spacing: 0.02em;
}

/* 目标投递切换器 */
.qc-targets {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.12);
}

.qc-target-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--txt2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.16s ease;
  white-space: nowrap;
}
.qc-target-btn:hover {
  color: var(--txt1);
  background: rgba(255, 255, 255, 0.4);
}
html.theme-dark .qc-target-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.qc-target-btn.active {
  background: var(--acc-grad);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
}

.qc-close-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--txt2);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
  flex: none;
}
.qc-close-btn:hover {
  background: rgba(148, 163, 184, 0.18);
  color: var(--txt1);
}

/* 主内容区 */
.qc-body {
  padding: 14px 18px 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.qc-textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 100px;
  max-height: 280px;
  padding: 6px 4px;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  line-height: 1.6;
  color: var(--txt1);
  font-family: inherit;
  resize: none;
  overflow-y: auto;
}
.qc-textarea::placeholder {
  color: var(--txt3);
}

/* 截图预览 */
.qc-image-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid rgba(148, 163, 184, 0.18);
}
.qc-image-thumb-wrap {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.05);
  flex: none;
}
.qc-image-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.qc-image-meta {
  flex: 1;
  min-width: 0;
}
.qc-image-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--txt1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qc-image-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
}
.qc-image-size {
  font-size: 11px;
  color: var(--txt3);
}
.qc-image-tag {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(139, 92, 246, 0.15);
  color: var(--acc2);
}
.qc-image-remove {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--txt3);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
}
.qc-image-remove:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

/* 附加字段折叠面板 */
.qc-extra-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.06);
  border: 1px dashed rgba(148, 163, 184, 0.2);
}
.qc-field-duo {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

/* 标签胶囊栏 */
.qc-capsules-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
}
.qc-capsules-label {
  font-size: 11.5px;
  color: var(--txt3);
  flex: none;
}
.qc-capsules-list {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1;
}
.qc-capsule {
  border: 1px solid rgba(139, 92, 246, 0.22);
  background: rgba(139, 92, 246, 0.06);
  color: var(--acc2);
  padding: 2.5px 10px;
  border-radius: 9999px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}
.qc-capsule:hover {
  background: rgba(139, 92, 246, 0.16);
  border-color: rgba(139, 92, 246, 0.45);
  transform: translateY(-1px);
}
.qc-capsule.active {
  background: var(--acc-grad);
  border-color: transparent;
  color: #fff;
}

.qc-extra-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: none;
  background: transparent;
  color: var(--txt2);
  font-size: 11.5px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  margin-left: auto;
}
.qc-extra-toggle:hover,
.qc-extra-toggle.active {
  background: rgba(148, 163, 184, 0.15);
  color: var(--txt1);
}

/* 底部操作与快捷提示 */
.qc-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(148, 163, 184, 0.03);
}

.qc-hints {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--txt3);
}
.qc-hint-sep {
  opacity: 0.5;
}
.qc-hint-key kbd,
.qc-hint-tip kbd {
  font-family: inherit;
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(148, 163, 184, 0.16);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: var(--txt2);
}

.qc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.qc-btn-cancel {
  padding: 7px 14px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: transparent;
  color: var(--txt2);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.qc-btn-cancel:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--txt1);
}

.qc-btn-submit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 18px;
  border-radius: 10px;
  border: none;
  background: var(--acc-grad);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.35);
  transition: all 0.16s ease;
}
.qc-btn-submit:hover:not(:disabled) {
  opacity: 0.94;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.45);
}
.qc-btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .qc-dialog {
    max-width: 100%;
    border-radius: 16px;
  }
  .qc-header {
    flex-wrap: wrap;
  }
  .qc-targets {
    order: 3;
    width: 100%;
    justify-content: space-around;
  }
  .qc-field-duo {
    grid-template-columns: 1fr;
  }
  .qc-hints {
    display: none;
  }
}
</style>
