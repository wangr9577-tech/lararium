<template>
  <div class="page" v-loading="loading">
    <template v-if="detail">
      <!-- 顶部：返回工作台 +「⋯」更多操作 -->
      <div class="head">
        <el-button text class="back-btn" @click="goLab">
          <el-icon><ArrowLeft /></el-icon><span>返回工作台</span>
        </el-button>
        <div class="head-ops">
          <span v-if="detail.archived" class="arch-chip">已归档</span>
          <el-dropdown trigger="click" @command="onHeaderCommand">
            <el-button text class="more-btn" title="更多操作"><el-icon><MoreFilled /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="archive">{{ detail.archived ? '取消归档' : '归档' }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除事项</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <!-- 面包屑：父事项 › 本事项（父事项可点击回去） -->
      <div v-if="detail.parent" class="crumb">
        <button type="button" class="crumb-parent" @click="openItem(detail.parent.id)">{{ detail.parent.title }}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb-cur">{{ detail.title }}</span>
      </div>

      <div class="page-title">{{ detail.title }}</div>
      <div class="page-sub">更新于 {{ fmtTime(detail.updated_at) }}<span v-if="countsText" class="sub-counts">{{ countsText }}</span></div>

      <!-- 1. 当前思路 -->
      <section class="glass sec">
        <div class="sec-head">
          <span class="sec-title">当前思路</span>
          <span class="save-status" :class="'st-' + saveState">{{ saveStatusText }}</span>
          <el-button v-if="saveState === 'error'" size="small" text class="retry-btn" @click="saveThinkingNow">重试</el-button>
          <el-button size="small" text class="save-btn" :loading="saveState === 'saving'" @click="saveThinkingNow">保存</el-button>
        </div>
        <VditorEditor
          v-model="thinkingText"
          :min-height="360"
          :auto-focus="false"
          placeholder="现在怎么想…（自由书写，支持 Markdown 与即时渲染）"
          @update:model-value="onThinkingInput"
          @save="saveThinkingNow"
        />
        <div class="hint">可以反复修改；这里是「现在怎么想」，不是按时间追加的记录</div>
      </section>

      <!-- 2. 小记 -->
      <section class="glass sec">
        <div class="sec-head">
          <span class="sec-title">小记</span>
          <span class="sec-count">{{ detail.entries.length }}</span>
        </div>
        <div class="entry-add">
          <el-input v-model="entryText" placeholder="写下一条新想法…" @keydown.enter.prevent="addEntry" />
          <el-button type="primary" :loading="entryAdding" @click="addEntry">
            <el-icon><Plus /></el-icon><span>追加</span>
          </el-button>
        </div>
        <div v-if="detail.entries.length" class="entry-list">
          <div v-for="en in detail.entries" :key="en.id" class="entry-row">
            <span class="entry-time">{{ fmtTime(en.created_at) }}</span>
            <span class="entry-text">{{ en.text }}</span>
            <span class="row-ops">
              <el-button text size="small" @click="editEntry(en)">编辑</el-button>
              <el-button text size="small" @click="removeEntry(en)">删除</el-button>
            </span>
          </div>
        </div>
        <div v-else class="muted">还没有小记 —— 记下讨论、实验和想法变化</div>
      </section>

      <!-- 3. 收集片段 -->
      <section class="glass sec">
        <div class="sec-head">
          <span class="sec-title">收集片段</span>
          <span class="sec-count">{{ detail.captures.length }}</span>
        </div>
        <div v-if="detail.captures.length" class="cap-list">
          <div v-for="c in detail.captures" :key="c.id" class="cap-row">
            <div class="cap-main">
              <div class="cap-excerpt">{{ c.excerpt }}</div>
              <div class="cap-meta">
                <span v-if="c.source" class="chip">{{ c.source }}</span>
                <a v-if="c.url" class="cap-url" :href="c.url" target="_blank" rel="noopener">{{ c.url }}</a>
                <span class="cap-time">{{ fmtTime(c.created_at) }}</span>
              </div>
            </div>
            <span class="row-ops">
              <el-button text size="small" @click="openCapture(c)">查看全文</el-button>
              <el-button text size="small" @click="moveCaptureToInbox(c)">移回收集箱</el-button>
              <el-button text size="small" @click="archiveCapture(c)">归档</el-button>
              <el-button text size="small" @click="removeCapture(c)">删除</el-button>
            </span>
          </div>
        </div>
        <div v-else class="muted">还没有从这个事项收集片段</div>
      </section>

      <!-- 4. 子事项 -->
      <section class="glass sec">
        <div class="sec-head">
          <span class="sec-title">子事项</span>
          <span class="sec-count">{{ detail.children.length }}</span>
          <el-button size="small" text class="sec-act" @click="newChild">
            <el-icon><Plus /></el-icon><span>新建子事项</span>
          </el-button>
        </div>
        <div v-if="detail.children.length" class="child-list">
          <div
            v-for="ch in detail.children" :key="ch.id" class="child-row"
            role="button" tabindex="0"
            @click="openItem(ch.id)" @keydown.enter.prevent="openItem(ch.id)" @keydown.space.prevent="openItem(ch.id)"
          >
            <span class="child-title" :title="ch.title">{{ ch.title }}</span>
            <span class="child-sum">{{ ch.summary || '（还没有内容）' }}</span>
            <span class="child-cnt">小记 {{ ch.entry_count }}</span>
          </div>
        </div>
        <div v-else class="muted">还没有子事项</div>
        <div class="hint">子事项只支持一层：子事项下面不再挂子事项。</div>
      </section>

      <!-- 5. 相关资料 -->
      <section class="glass sec">
        <div class="sec-head">
          <span class="sec-title">相关资料</span>
          <span class="sec-count">{{ detail.links.length }}</span>
          <span class="sec-ops">
            <el-button size="small" text @click="openPicker('paper')">关联论文</el-button>
            <el-button size="small" text @click="openPicker('note')">关联已有笔记</el-button>
            <el-button size="small" text @click="openPicker('doc')">关联项目文档</el-button>
            <el-button size="small" text @click="newNote">
              <el-icon><Plus /></el-icon><span>新建笔记</span>
            </el-button>
          </span>
        </div>
        <div class="hint">这里只展示入口，不复制资料正文；点击可快速预览或平滑跳转至原页面。</div>
        <div v-if="detail.links.length" class="link-list">
          <div
            v-for="l in detail.links" :key="l.id" class="link-row"
            role="button" tabindex="0"
            @click="goLink(l)" @keydown.enter.prevent="goLink(l)" @keydown.space.prevent="goLink(l)"
          >
            <span class="link-kind" :class="'kind-' + l.target_type">{{ kindLabel(l.target_type) }}</span>
            <span class="link-title" :class="{ gone: l.missing }" :title="l.title">{{ l.title }}</span>
            <span v-if="l.author" class="link-extra">{{ l.author }}</span>
            <span v-else-if="l.folder" class="link-extra">{{ l.folder }}</span>
            <span v-if="l.missing" class="miss-chip">资料已删除</span>
            <span class="row-ops" @click.stop>
              <el-button v-if="!l.missing" text size="small" @click.stop="openPreview(l)">
                <el-icon style="margin-right:2px"><View /></el-icon>预览
              </el-button>
              <el-button v-if="!l.missing" text size="small" type="primary" @click.stop="goLink(l)">
                打开
              </el-button>
              <el-button v-if="l.missing" text size="small" @click.stop="dropMissing(l)">移除失效链接</el-button>
              <el-button text size="small" @click.stop="removeLink(l)">移除</el-button>
            </span>
          </div>
        </div>
        <div v-else class="muted">还没有相关资料 —— 用上面的「关联论文 / 关联已有笔记 / 关联项目文档 / 新建笔记」把入口挂到这里</div>
      </section>
    </template>

    <EmptyState
      v-else-if="!loading" class="miss-wrap" icon="ChatDotRound"
      title="事项不存在或已被删除"
      desc="可能它已被删除（子事项、随笔与小记会一起进入回收站，可以恢复），或者链接里的编号不对。"
    >
      <el-button type="primary" round style="margin-top:18px" @click="goLab">返回工作台</el-button>
    </EmptyState>

    <!-- 片段全文（可编辑后保存） -->
    <el-dialog v-model="capOpen" title="片段全文" width="720px" append-to-body>
      <div v-loading="capLoading" class="cap-dlg">
        <div v-if="capDraft" class="cap-dlg-meta">
          <span v-if="capDraft.source" class="chip">{{ capDraft.source }}</span>
          <a v-if="capDraft.url" class="cap-url" :href="capDraft.url" target="_blank" rel="noopener">{{ capDraft.url }}</a>
        </div>
        <el-input
          v-if="capDraft" v-model="capDraft.text" type="textarea"
          :autosize="{ minRows: 10, maxRows: 30 }" placeholder="片段全文…"
        />
      </div>
      <template #footer>
        <el-button @click="capOpen = false">取消</el-button>
        <el-button type="primary" :loading="capSaving" @click="saveCapture">保存</el-button>
      </template>
    </el-dialog>

    <!-- 资料轻量弹窗预览 -->
    <el-dialog
      v-model="previewOpen"
      :title="previewItem ? `${kindLabel(previewItem.target_type)} · 快速预览` : '资料预览'"
      width="700px"
      append-to-body
    >
      <div v-loading="previewLoading" class="preview-dlg">
        <template v-if="previewItem">
          <div class="preview-header">
            <span class="link-kind" :class="'kind-' + previewItem.target_type">{{ kindLabel(previewItem.target_type) }}</span>
            <span class="preview-title">{{ previewItem.title }}</span>
          </div>
          <div v-if="previewSubtitle" class="preview-sub">{{ previewSubtitle }}</div>
          <el-divider style="margin: 12px 0;" />
          <div v-if="previewHtml" class="markdown-body preview-body" v-html="previewHtml" />
          <div v-else-if="previewText" class="preview-text">{{ previewText }}</div>
          <div v-else class="preview-empty">暂无正文预览内容</div>
        </template>
      </div>
      <template #footer>
        <el-button @click="previewOpen = false">关闭</el-button>
        <el-button v-if="previewItem" type="primary" @click="goLinkFromPreview">进入完整页面阅读</el-button>
      </template>
    </el-dialog>

    <!-- 关联已有资料（论文 / 博客笔记 / 项目文档） -->
    <RelatedMaterialPicker v-model="pickerOpen" :item-id="id" :kind="pickerKind" @changed="reload" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, MoreFilled, Plus, View } from '@element-plus/icons-vue'
import { http } from '../api/client'
import { renderMd } from '../utils/md'
import {
  workbenchApi, itemRoute, kindLabel,
  type WbCapture, type WbCaptureBrief, type WbEntry, type WbItemDetail, type WbLink,
} from '../api/workbench'
import EmptyState from '../components/EmptyState.vue'
import RelatedMaterialPicker from '../components/RelatedMaterialPicker.vue'
import VditorEditor from '../components/VditorEditor.vue'

const route = useRoute()
const router = useRouter()

/** 当前事项 id（跟随路由参数：在事项之间跳转时同步更新，请求一律用它做闭环校验） */
const id = ref(Number(route.params.id))
const loading = ref(true)
const detail = ref<WbItemDetail | null>(null)
/** 过期响应护栏：id 在请求飞行途中变化时丢弃旧响应 */
let loadSeq = 0
let thinkSeq = 0

/* ---------------- 展示辅助 ---------------- */

/** 'YYYY-MM-DD HH:MM:SS' → 'YYYY-MM-DD HH:MM'（空值原样返回） */
function fmtTime(s?: string): string {
  return s && s.length >= 16 ? s.slice(0, 16) : (s || '')
}
/** 当前时钟 HH:MM（保存成功时间戳） */
function nowHHMM(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
/** 标题下计数：每一项 > 0 才出现 */
const countsText = computed(() => {
  const d = detail.value
  if (!d) return ''
  const parts: string[] = []
  if (d.entry_count > 0) parts.push(`${d.entry_count} 条小记`)
  if (d.capture_count > 0) parts.push(`${d.capture_count} 个片段`)
  if (d.sub_count > 0) parts.push(`${d.sub_count} 个子事项`)
  return parts.length ? ` · ${parts.join(' · ')}` : ''
})

function goLab() {
  router.push('/lab')
}
/** 跳去另一个事项（同页切换由 route.params.id 的 watcher 负责重载） */
function openItem(target: number) {
  if (target !== id.value) router.push(itemRoute(target))
}

/* ---------------- 加载 / 重载 ---------------- */

/** 重新拉取事项详情：每个成功的写操作之后都调用它 */
async function reload() {
  const itemId = id.value
  if (!itemId) { loading.value = false; detail.value = null; return }
  const seq = ++loadSeq
  loading.value = true
  try {
    const d = await workbenchApi.getItem(itemId)
    if (seq !== loadSeq || itemId !== id.value) return // 过期响应：id 已变，丢弃
    detail.value = d
    // 本地没有未落盘的正文时才用服务端内容回填编辑框（避免覆盖用户正在写的东西）
    if (pendingThink.value === null && saveState.value !== 'saving') {
      thinkingText.value = d.thinking || ''
      savedText.value = d.thinking || ''
      saveState.value = 'saved'
      savedAt.value = fmtTime(d.updated_at).slice(11)
    }
    document.title = `${d.title} · 事项`
  } catch (e: any) {
    if (seq !== loadSeq) return
    ElMessage.error(e?.response?.data?.detail || '事项加载失败')
    detail.value = null
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

/* ---------------- 当前思路（防抖自动保存 + 失焦立即保存 + 手动保存） ---------------- */

const thinkingText = ref('')
/** 当前思路输入框：进页面自动聚焦，打开就能写 */
const thinkRef = ref<any>(null)
/** 已成功落盘的正文（判断「真的改了没有」，避免无谓 PUT） */
const savedText = ref('')
const saveState = ref<'saved' | 'dirty' | 'saving' | 'error'>('saved')
const savedAt = ref('')
/** 待保存正文：null=没有未落盘的改动（离场护栏据此判断要不要 flush） */
const pendingThink = ref<string | null>(null)
let thinkTimer: ReturnType<typeof setTimeout> | undefined

const saveStatusText = computed(() => {
  if (saveState.value === 'saving') return '保存中…'
  if (saveState.value === 'error') return '保存失败，可重试'
  if (saveState.value === 'dirty') return '待保存…'
  return savedAt.value ? `已保存 ${savedAt.value}` : '已保存'
})

/** 输入：标记脏 + 1.2s 防抖后自动保存 */
function onThinkingInput(v: string | number) {
  if (typeof v === 'string' && v !== thinkingText.value) thinkingText.value = v
  pendingThink.value = thinkingText.value
  saveState.value = 'dirty'
  clearTimeout(thinkTimer)
  thinkTimer = setTimeout(() => { void flushThinking() }, 1200)
}

/** 失焦：立即落盘，不等防抖 */
function onThinkingBlur() {
  void flushThinking()
}

/** 把待保存正文写回服务端；返回是否成功（失败保留 pending 且不回滚屏幕上的文字） */
async function flushThinking(): Promise<boolean> {
  clearTimeout(thinkTimer)
  if (pendingThink.value === null) return true
  const text = pendingThink.value
  const itemId = id.value
  pendingThink.value = null
  saveState.value = 'saving'
  const seq = ++thinkSeq
  try {
    const r = await workbenchApi.putThinking(itemId, text)
    if (seq === thinkSeq && itemId === id.value) {
      savedText.value = text
      savedAt.value = nowHHMM()
      saveState.value = 'saved'
      // 「先写后命名」：标题还是「未命名」时，后端会把正文第一行提上来当标题
      if (r?.title_adopted && detail.value) {
        detail.value.title = r.title
        document.title = `${r.title} · 事项`
      }
    }
    return true
  } catch (e: any) {
    if (seq === thinkSeq && itemId === id.value) {
      pendingThink.value = text // 失败：内容留在屏幕上，等用户重试
      saveState.value = 'error'
      ElMessage.error(e?.response?.data?.detail || '当前思路保存失败，请点「重试」')
    }
    return false
  }
}

/** 「保存」/「重试」按钮：把编辑框里的内容立刻写回 */
async function saveThinkingNow() {
  if (saveState.value === 'saving') return
  if (pendingThink.value === null && thinkingText.value === savedText.value) {
    ElMessage.success('当前思路已是最新')
    return
  }
  pendingThink.value = thinkingText.value
  const ok = await flushThinking()
  if (ok) ElMessage.success('已保存当前思路')
}

/** 丢开待保存内容（仅用于事项已删除等确实无处可写的场景） */
function dropPendingThink() {
  clearTimeout(thinkTimer)
  pendingThink.value = null
  saveState.value = 'saved'
}

/* ---------------- 离场护栏：绝不静默丢字 ---------------- */

onBeforeRouteLeave(async () => {
  clearTimeout(thinkTimer)
  if (pendingThink.value === null) return true
  if (await flushThinking()) return true
  try {
    await ElMessageBox.confirm(
      '当前思路还没保存成功（网络或服务异常）。现在离开会丢掉这段文字，仍要离开吗？',
      '还有内容未保存',
      { type: 'warning', confirmButtonText: '仍然离开', cancelButtonText: '留在本页' },
    )
    return true
  } catch { return false }
})

/** 关标签页/刷新前的兜底提示（有未落盘正文时让浏览器拦一下） */
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (pendingThink.value === null) return
  e.preventDefault()
  e.returnValue = ''
}

/* ---------------- 头部操作：重命名 / 归档 / 删除 ---------------- */

function onHeaderCommand(cmd: string) {
  if (cmd === 'rename') void rename()
  else if (cmd === 'archive') void toggleArchive()
  else if (cmd === 'delete') void removeItem()
}

async function rename() {
  const cur = detail.value
  if (!cur) return
  let title = ''
  try {
    const r = await ElMessageBox.prompt('事项标题：', '重命名', {
      confirmButtonText: '保存', cancelButtonText: '取消',
      inputValue: cur.title, inputPattern: /\S+/, inputErrorMessage: '标题不能为空',
    })
    title = (r.value || '').trim()
  } catch { return }
  if (!title || title === cur.title) return
  try {
    await workbenchApi.patchItem(id.value, { title })
    ElMessage.success('已重命名')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重命名失败')
  }
}

async function toggleArchive() {
  const cur = detail.value
  if (!cur) return
  const next = !cur.archived
  try {
    await workbenchApi.patchItem(id.value, { archived: next })
    ElMessage.success(next ? '已归档' : '已取消归档')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || (next ? '归档失败' : '取消归档失败'))
  }
}

async function removeItem() {
  const cur = detail.value
  if (!cur) return
  try {
    await ElMessageBox.confirm(
      `确定删除事项「${cur.title}」？它的子事项、随笔与小记会一起进入回收站（可恢复），博客笔记与论文不受影响。`,
      '删除事项',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await workbenchApi.deleteItem(id.value)
    ElMessage.success('已删除（回收站可恢复）')
    dropPendingThink() // 事项已不存在：别再往它上面写正文
    router.push('/lab')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

/* ---------------- 小记 ---------------- */

const entryText = ref('')
const entryAdding = ref(false)

async function addEntry() {
  const text = entryText.value.trim()
  if (!text) { ElMessage.warning('先写点什么再追加'); return }
  if (entryAdding.value) return
  entryAdding.value = true
  try {
    await workbenchApi.createEntry(id.value, text)
    entryText.value = '' // 只在成功后才清空输入
    ElMessage.success('已追加小记')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '追加失败')
  } finally {
    entryAdding.value = false
  }
}

async function editEntry(en: WbEntry) {
  let text = ''
  try {
    const r = await ElMessageBox.prompt('修改这条小记：', '编辑小记', {
      confirmButtonText: '保存', cancelButtonText: '取消',
      inputValue: en.text, inputType: 'textarea',
      inputValidator: (v: string) => ((v || '').trim() ? true : '内容不能为空'),
    })
    text = (r.value || '').trim()
  } catch { return }
  if (!text || text === en.text) return
  try {
    await workbenchApi.updateEntry(id.value, en.id, text)
    ElMessage.success('已更新小记')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新小记失败')
  }
}

async function removeEntry(en: WbEntry) {
  try {
    await ElMessageBox.confirm('确定删除这条小记？删除后无法恢复。', '删除小记', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await workbenchApi.deleteEntry(id.value, en.id)
    ElMessage.success('已删除小记')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除小记失败')
  }
}

/* ---------------- 收集片段 ---------------- */

const capOpen = ref(false)
const capLoading = ref(false)
const capSaving = ref(false)
const capDraft = ref<WbCapture | null>(null)
let capSeq = 0

async function openCapture(c: WbCaptureBrief) {
  capOpen.value = true
  capLoading.value = true
  capDraft.value = null
  const seq = ++capSeq
  try {
    const full = await workbenchApi.getCapture(c.id)
    if (seq !== capSeq) return // 过期响应：已经点开了别的片段
    capDraft.value = full
  } catch (e: any) {
    if (seq !== capSeq) return
    ElMessage.error(e?.response?.data?.detail || '片段加载失败')
    capOpen.value = false
  } finally {
    if (seq === capSeq) capLoading.value = false
  }
}

async function saveCapture() {
  const d = capDraft.value
  if (!d || capSaving.value) return
  capSaving.value = true
  try {
    await workbenchApi.updateCapture(d.id, { text: d.text })
    ElMessage.success('已保存片段全文')
    capOpen.value = false
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存片段失败')
  } finally {
    capSaving.value = false
  }
}

async function moveCaptureToInbox(c: WbCaptureBrief) {
  try {
    await workbenchApi.moveCapture(c.id, { item_id: null })
    ElMessage.success('已移回收集箱')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移回收集箱失败')
  }
}

async function archiveCapture(c: WbCaptureBrief) {
  try {
    await workbenchApi.moveCapture(c.id, { archived: true })
    ElMessage.success('片段已归档')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '归档片段失败')
  }
}

async function removeCapture(c: WbCaptureBrief) {
  try {
    await ElMessageBox.confirm('确定删除这个收集片段？删除后无法恢复（资料正文不受影响）。', '删除片段', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await workbenchApi.deleteCapture(c.id)
    ElMessage.success('已删除片段')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除片段失败')
  }
}

/* ---------------- 子事项 ---------------- */

async function newChild() {
  let title = ''
  try {
    const r = await ElMessageBox.prompt('子事项标题：', '新建子事项', {
      confirmButtonText: '创建', cancelButtonText: '取消',
      inputPattern: /\S+/, inputErrorMessage: '标题不能为空',
    })
    title = (r.value || '').trim()
  } catch { return }
  if (!title) return
  try {
    await workbenchApi.createItem(title, id.value)
    ElMessage.success('已新建子事项')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '新建子事项失败')
  }
}

/* ---------------- 相关资料 ---------------- */

const pickerOpen = ref(false)
/** 传给选择器的过滤倾向（组件不支持时会被忽略，仍然只是打开选择器） */
const pickerKind = ref<'all' | 'note' | 'paper'>('all')

function openPicker(kind: 'note' | 'paper') {
  pickerKind.value = kind
  pickerOpen.value = true
}

async function goLink(l: WbLink) {
  if (l.missing) { ElMessage.warning('这份资料已被删除，入口暂时打不开'); return }
  router.push(l.route)
}

async function dropMissing(l: WbLink) {
  try {
    await workbenchApi.removeLink(id.value, l.id)
    ElMessage.success('已移除失效链接')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除失效链接失败')
  }
}

async function removeLink(l: WbLink) {
  try {
    await ElMessageBox.confirm(
      `确定移除「${l.title}」这个入口？只移除工作台里的关联，不会删除这篇论文 / 笔记本身。`,
      '移除关联',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await workbenchApi.removeLink(id.value, l.id)
    ElMessage.success('已移除关联（资料本身未删除）')
    await reload()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除关联失败')
  }
}

/** 新建笔记：带上来源事项，编辑页可直接把新笔记挂回来 */
function newNote() {
  router.push(`/notes/new?source_item_id=${id.value}`)
}

/* ---------------- 生命周期 ---------------- */

// 在事项之间跳转（点父事项/子事项/资料）：按新 id 重新加载
watch(() => route.params.id, (v) => {
  id.value = Number(v)
  detail.value = null
  capOpen.value = false
  void reload()
})

onMounted(() => {
  id.value = Number(route.params.id)
  void reload().then(() => {
    // 打开就能写：光标直接落在「当前思路」里
    nextTick(() => {
      const el = thinkRef.value?.textarea || thinkRef.value?.$el?.querySelector?.('textarea')
      el?.focus?.()
    })
  })
  window.addEventListener('beforeunload', onBeforeUnload)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  void flushThinking() // 兜底：销毁前再尽力落盘一次（无待保存时是空操作）
})
</script>

<style scoped>
/* ---------- 头部 ---------- */
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.back-btn { color: var(--txt2); }
.back-btn:hover { color: var(--acc2); }
.head-ops { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.more-btn { color: var(--txt2); font-size: 16px; }
.arch-chip {
  font-size: 11.5px; padding: 2px 10px; border-radius: 999px;
  color: var(--txt2); background: rgba(148, 163, 184, 0.18); border: 1px solid rgba(148, 163, 184, 0.35);
}
html.theme-dark .arch-chip { color: #cbd5e1; background: rgba(148, 163, 184, 0.22); border-color: rgba(148, 163, 184, 0.4); }

/* ---------- 面包屑 ---------- */
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; margin: 2px 0 4px; }
.crumb-parent { border: none; background: transparent; padding: 0; cursor: pointer; font-family: inherit; font-size: 13px; color: var(--acc2); }
.crumb-parent:hover { text-decoration: underline; }
.crumb-sep { color: var(--txt3); }
.crumb-cur { color: var(--txt2); }

.page-title { margin-bottom: 6px; }
.page-sub { margin: 0 0 16px; }
.sub-counts { margin-left: 2px; }

/* ---------- 通用区块 ---------- */
.sec { padding: 16px 20px; margin-bottom: 16px; }
.sec-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.sec-title { font-size: 15px; font-weight: 700; }
.sec-count {
  font-size: 11.5px; font-weight: 700; padding: 1px 9px; border-radius: 10px;
  color: var(--acc2); background: rgba(139, 92, 246, 0.14);
}
html.theme-dark .sec-count { color: #c4b5fd; background: rgba(167, 139, 250, 0.2); }
.sec-act { margin-left: auto; }
.sec-ops { margin-left: auto; display: inline-flex; align-items: center; gap: 2px; flex-wrap: wrap; }
.hint { font-size: 12px; line-height: 1.7; color: var(--txt3); margin-top: 8px; }
.muted { font-size: 13px; color: var(--txt3); padding: 8px 2px; }
.row-ops { flex: none; display: inline-flex; align-items: center; gap: 2px; }

/* ---------- 保存状态 ---------- */
.save-status { font-size: 12px; color: var(--txt3); }
.st-dirty { color: var(--txt2); }
.st-saving { color: var(--acc3); }
.st-saved { color: #059669; }
html.theme-dark .st-saved { color: #34d399; }
.st-error { color: #dc2626; font-weight: 700; }
html.theme-dark .st-error { color: #f87171; }
.retry-btn { color: #dc2626; }
html.theme-dark .retry-btn { color: #f87171; }
.save-btn { margin-left: 2px; }

/* ---------- 小记 ---------- */
.entry-add { display: flex; align-items: center; gap: 8px; }
.entry-list { display: flex; flex-direction: column; margin-top: 12px; }
.entry-row {
  display: flex; align-items: flex-start; gap: 14px; padding: 10px 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.32);
}
html.theme-dark .entry-row { border-top-color: rgba(148, 163, 184, 0.22); }
.entry-row:first-child { border-top: none; }
.entry-time { flex: none; width: 116px; font-size: 12px; color: var(--txt3); font-variant-numeric: tabular-nums; padding-top: 3px; }
.entry-text { flex: 1; min-width: 0; font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; }

/* ---------- 收集片段 ---------- */
.cap-list { display: flex; flex-direction: column; gap: 10px; }
.cap-row {
  display: flex; align-items: flex-start; gap: 12px; padding: 10px 12px; border-radius: 12px;
  background: rgba(148, 163, 184, 0.07); border: 1px solid rgba(148, 163, 184, 0.18);
}
html.theme-dark .cap-row { background: rgba(148, 163, 184, 0.1); border-color: rgba(148, 163, 184, 0.22); }
.cap-main { flex: 1; min-width: 0; }
.cap-excerpt {
  font-size: 13.5px; line-height: 1.75; word-break: break-word;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.cap-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.cap-url { font-size: 12px; max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cap-time { font-size: 11.5px; color: var(--txt3); margin-left: auto; }

/* ---------- 片段全文弹窗 ---------- */
.cap-dlg { min-height: 140px; }
.cap-dlg-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }

/* ---------- 子事项 ---------- */
.child-list { display: flex; flex-direction: column; gap: 8px; }
.child-row {
  display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 12px; cursor: pointer;
  background: rgba(148, 163, 184, 0.07); border: 1px solid rgba(148, 163, 184, 0.18);
  transition: border-color .15s, background .15s;
}
html.theme-dark .child-row { background: rgba(148, 163, 184, 0.1); border-color: rgba(148, 163, 184, 0.22); }
.child-row:hover { border-color: rgba(139, 92, 246, 0.55); background: rgba(139, 92, 246, 0.08); }
.child-row:focus-visible { outline: 2px solid var(--acc2); outline-offset: 2px; }
.child-title { flex: none; max-width: 40%; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.child-sum { flex: 1; min-width: 0; font-size: 12.5px; color: var(--txt2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.child-cnt { flex: none; font-size: 11.5px; color: var(--txt3); }

/* ---------- 相关资料 ---------- */
.link-list { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.link-row {
  display: flex; align-items: center; gap: 10px; padding: 9px 14px; border-radius: 12px; cursor: pointer;
  background: rgba(148, 163, 184, 0.07); border: 1px solid rgba(148, 163, 184, 0.18);
  transition: border-color .15s, background .15s;
}
html.theme-dark .link-row { background: rgba(148, 163, 184, 0.1); border-color: rgba(148, 163, 184, 0.22); }
.link-row:hover { border-color: rgba(56, 189, 248, 0.5); background: rgba(56, 189, 248, 0.08); }
.link-row:focus-visible { outline: 2px solid var(--acc2); outline-offset: 2px; }
.link-kind { flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px; color: var(--acc2); background: rgba(167, 139, 250, 0.14); }
html.theme-dark .link-kind { color: #c4b5fd; background: rgba(167, 139, 250, 0.2); }
.link-title { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.link-title.gone { color: var(--txt3); text-decoration: line-through; }
.miss-chip {
  flex: none; font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px;
  color: #b45309; background: rgba(251, 146, 60, 0.16); border: 1px solid rgba(251, 146, 60, 0.45);
}
html.theme-dark .miss-chip { color: #fdba74; background: rgba(251, 146, 60, 0.2); border-color: rgba(251, 146, 60, 0.5); }

/* ---------- 事项不存在 ---------- */
.miss-wrap { margin-top: 40px; }

@media (max-width: 760px) {
  .entry-row { flex-direction: column; gap: 6px; }
  .entry-time { width: auto; }
  .child-title { max-width: 55%; }
}
</style>