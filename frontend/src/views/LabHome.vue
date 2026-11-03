<template>
  <div class="page" v-loading="loading">
    <!-- 顶部工作台状态条：标题 + 全局展开控制 + 新建事项 + 随手记唤出 -->
    <div class="head glass">
      <div class="head-left">
        <div class="head-title grad-text">工作台</div>
        <div class="head-sub">理清每一件事的思路，自由书写安排与想法</div>
      </div>
      <div class="head-actions">
        <el-button round size="small" @click="toggleAll(!allExpanded)">
          <el-icon><component :is="allExpanded ? Fold : Expand" /></el-icon>
          <span>{{ allExpanded ? '全部收起' : '全部展开' }}</span>
        </el-button>
        <el-button type="primary" round size="small" @click="newItem(null)">
          <el-icon><Plus /></el-icon>
          <span>新建事项</span>
        </el-button>
        <el-badge :value="inboxTotal" :hidden="!inboxTotal" :max="99">
          <el-button round size="small" class="quick-btn" @click="drawerOpen = true">
            <el-icon><Opportunity /></el-icon>
            <span>随手记</span>
          </el-button>
        </el-badge>
      </div>
    </div>

    <!-- 主体：纯动态事项树（支持多项同时展开、两级就地编辑、零跳页） -->
    <div class="item-tree">
      <template v-if="items.length">
        <div
          v-for="(it, idx) in items"
          :key="it.id"
          class="item-card glass"
          :class="{ open: isOpen(it.id) }"
        >
          <!-- 主事项头部 -->
          <div
            class="item-head"
            role="button"
            tabindex="0"
            @click="toggle(it.id)"
            @keydown.enter.prevent="toggle(it.id)"
            @keydown.space.prevent="toggle(it.id)"
          >
            <el-icon class="caret" :size="16">
              <component :is="isOpen(it.id) ? ArrowDown : ArrowRight" />
            </el-icon>
            <span class="item-title" :title="it.title">{{ it.title }}</span>
            <span v-if="it.children?.length" class="sub-badge">{{ it.children.length }} 个子项</span>
            <span class="head-spacer" />

            <!-- 保存状态（展开时显示） -->
            <span v-if="isOpen(it.id)" class="save-tag" :class="saveStatusMap[it.id]?.cls">
              {{ saveStatusMap[it.id]?.text || '已就绪' }}
            </span>

            <span class="item-time">{{ fmtTime(it.updated_at) }}</span>

            <!-- 操作按钮 -->
            <div class="item-ops" @click.stop>
              <el-button
                text
                size="small"
                title="添加子事项"
                @click="newItem(it.id)"
              >
                <el-icon><Plus /></el-icon>
                <span>子事项</span>
              </el-button>
              <el-button
                text
                size="small"
                :disabled="idx === 0"
                title="上移"
                @click="moveItem(it.id, 'up')"
              >
                <el-icon><Top /></el-icon>
              </el-button>
              <el-button
                text
                size="small"
                :disabled="idx === items.length - 1"
                title="下移"
                @click="moveItem(it.id, 'down')"
              >
                <el-icon><Bottom /></el-icon>
              </el-button>
              <el-dropdown trigger="click" @command="(cmd: string) => onItemCmd(it, cmd)">
                <el-button text size="small">
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rename">重命名</el-dropdown-item>
                    <el-dropdown-item command="sub">添加子事项</el-dropdown-item>
                    <el-dropdown-item command="archive">归档</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <!-- 主事项展开区：纯粹的 Markdown 即时渲染窗口 + 子事项嵌套 -->
          <div v-if="isOpen(it.id)" class="item-body">
            <!-- 编辑区 -->
            <div v-loading="loadingMap[it.id]" class="editor-wrap">
              <VditorEditor
                v-if="contents[it.id] !== undefined"
                v-model="contents[it.id]"
                :min-height="200"
                :auto-focus="false"
                placeholder="在此自由梳理当前思路、推进计划与待办…（Typora 式即时渲染，边写边自动保存）"
                @update:model-value="(val: string) => onContentInput(it.id, val)"
                @save="saveItem(it.id)"
              />
            </div>

            <!-- 子事项嵌套树（例如：期中考下的四门科目） -->
            <div class="children-wrap">
              <div v-if="it.children?.length" class="children-list">
                <div
                  v-for="(sub, sIdx) in it.children"
                  :key="sub.id"
                  class="sub-card glass"
                  :class="{ open: isOpen(sub.id) }"
                >
                  <!-- 子事项头部 -->
                  <div
                    class="sub-head"
                    role="button"
                    tabindex="0"
                    @click="toggle(sub.id)"
                    @keydown.enter.prevent="toggle(sub.id)"
                    @keydown.space.prevent="toggle(sub.id)"
                  >
                    <el-icon class="caret" :size="14">
                      <component :is="isOpen(sub.id) ? ArrowDown : ArrowRight" />
                    </el-icon>
                    <span class="sub-title" :title="sub.title">{{ sub.title }}</span>
                    <span class="head-spacer" />

                    <span v-if="isOpen(sub.id)" class="save-tag sub-tag" :class="saveStatusMap[sub.id]?.cls">
                      {{ saveStatusMap[sub.id]?.text || '已就绪' }}
                    </span>

                    <span class="item-time">{{ fmtTime(sub.updated_at) }}</span>

                    <div class="item-ops" @click.stop>
                      <el-button
                        text
                        size="small"
                        :disabled="sIdx === 0"
                        title="上移"
                        @click="moveItem(sub.id, 'up')"
                      >
                        <el-icon><Top /></el-icon>
                      </el-button>
                      <el-button
                        text
                        size="small"
                        :disabled="sIdx === it.children.length - 1"
                        title="下移"
                        @click="moveItem(sub.id, 'down')"
                      >
                        <el-icon><Bottom /></el-icon>
                      </el-button>
                      <el-dropdown trigger="click" @command="(cmd: string) => onItemCmd(sub, cmd)">
                        <el-button text size="small">
                          <el-icon><MoreFilled /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="rename">重命名</el-dropdown-item>
                            <el-dropdown-item command="archive">归档</el-dropdown-item>
                            <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </div>
                  </div>

                  <!-- 子事项展开区：就地独立的 Markdown 编辑器 -->
                  <div v-if="isOpen(sub.id)" class="sub-body">
                    <div v-loading="loadingMap[sub.id]" class="editor-wrap">
                      <VditorEditor
                        v-if="contents[sub.id] !== undefined"
                        v-model="contents[sub.id]"
                        :min-height="160"
                        :auto-focus="false"
                        :placeholder="`自由梳理「${sub.title}」的思路、进展与笔记…（自动保存）`"
                        @update:model-value="(val: string) => onContentInput(sub.id, val)"
                        @save="saveItem(sub.id)"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 添加子项触发条 -->
              <div class="add-sub-bar">
                <el-button text size="small" class="add-sub-btn" @click="newItem(it.id)">
                  <el-icon><Plus /></el-icon>
                  <span>添加子事项</span>
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 空白页状态 -->
      <EmptyState
        v-else-if="!loading"
        icon="Grid"
        title="工作台暂无事项"
        desc="在这里理清思绪、规划手头推进的事；没有死板的规则，完全按你的想法自由书写。"
        :features="['支持多项同时展开，跨事项对照思路', 'Typora 式实时渲染 Markdown，告别表单束缚', '期中考等多科目可在原地嵌套展开编辑，零跳页']"
      >
        <template #default>
          <el-button type="primary" round style="margin-top:18px" @click="newItem(null)">
            <el-icon><Plus /></el-icon>
            <span>新建第一个事项</span>
          </el-button>
        </template>
      </EmptyState>
    </div>

    <!-- 右下角悬浮随手记唤出气泡 -->
    <div class="fab-bubble glass" @click="drawerOpen = true" title="随时记录灵感与碎片">
      <el-icon :size="18"><Opportunity /></el-icon>
      <span class="fab-text">随手记</span>
      <span v-if="inboxTotal" class="fab-badge">{{ inboxTotal > 99 ? '99+' : inboxTotal }}</span>
    </div>

    <!-- 侧边抽屉：「随手记 / 碎片灵感」（Typora 即时渲染 Markdown） -->
    <el-drawer
      v-model="drawerOpen"
      title="随手记 · 碎片灵感"
      direction="rtl"
      size="620px"
      :append-to-body="true"
      @open="onDrawerOpen"
    >
      <template #header>
        <div class="drawer-title-wrap">
          <div class="drawer-title">随手记 · 碎片灵感</div>
          <div class="drawer-sub">随时记录 AI 对话观点、小红书图文摘录与突发奇想</div>
        </div>
      </template>

      <div class="drawer-content">
        <!-- 随手写输入区：Vditor 即时渲染 -->
        <div class="quick-editor-box glass">
          <VditorEditor
            ref="quickVdRef"
            v-model="quickText"
            :min-height="200"
            :auto-focus="false"
            placeholder="在此自由写下想法，或粘贴 AI 对话、小红书链接与观点…（即时渲染，支持图片粘贴）"
          />
          <div class="quick-meta-row">
            <el-input
              v-model="quickSource"
              size="small"
              class="quick-src"
              placeholder="来源（选填，如：Claude / 小红书）"
              clearable
            />
            <el-input
              v-model="quickUrl"
              size="small"
              class="quick-url"
              placeholder="原链接（选填）"
              clearable
            />
          </div>
          <div class="quick-action-row">
            <el-button
              type="primary"
              size="small"
              round
              :loading="quickSaving"
              @click="saveToInbox"
            >
              存入暂存箱
            </el-button>

            <!-- 一键追加到某事项随笔 -->
            <el-dropdown trigger="click" @command="appendToItem">
              <el-button size="small" round :disabled="!quickText.trim()">
                追加到事项随笔
                <el-icon :size="12"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="o in allItemOptions"
                    :key="o.id"
                    :command="o.id"
                  >
                    {{ o.label }}
                  </el-dropdown-item>
                  <el-dropdown-item v-if="!allItemOptions.length" disabled>暂无事项</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <!-- 暂存箱列表 -->
        <div class="inbox-section">
          <div class="inbox-head">
            <span class="inbox-title">暂存箱（未归类）</span>
            <span class="inbox-cnt">{{ inboxTotal }} 条</span>
            <div class="head-spacer" />
            <el-input
              v-model="inboxQ"
              size="small"
              placeholder="搜索暂存片段…"
              style="width: 170px"
              clearable
              @input="onInboxSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>

          <div v-loading="inboxLoading" class="inbox-list">
            <div
              v-for="cap in inboxList"
              :key="cap.id"
              class="inbox-card glass"
            >
              <div class="inbox-card-text">{{ cap.excerpt || '（空文本）' }}</div>
              <div class="inbox-card-meta">
                <el-tag v-if="cap.source" size="small" effect="plain">{{ cap.source }}</el-tag>
                <a
                  v-if="cap.url"
                  class="inbox-url"
                  :href="cap.url"
                  target="_blank"
                  rel="noopener"
                >
                  {{ shortUrl(cap.url) }}
                </a>
                <span class="inbox-time">{{ fmtTime(cap.created_at) }}</span>
                <div class="head-spacer" />

                <!-- 操作按钮 -->
                <el-dropdown trigger="click" @command="(itemId: number) => appendCaptureToItem(cap, itemId)">
                  <el-button text size="small">追加到事项<el-icon :size="11"><ArrowDown /></el-icon></el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-for="o in allItemOptions"
                        :key="o.id"
                        :command="o.id"
                      >
                        {{ o.label }}
                      </el-dropdown-item>
                      <el-dropdown-item v-if="!allItemOptions.length" disabled>暂无事项</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button text size="small" @click="promoteCapture(cap.id)">整理为新事项</el-button>
                <el-button text size="small" type="danger" @click="removeCapture(cap.id)">删除</el-button>
              </div>
            </div>
            <div v-if="!inboxLoading && !inboxList.length" class="inbox-empty">
              暂存箱空空如也，随时记下一笔吧
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown, ArrowRight, Bottom, Expand, Fold, MoreFilled,
  Opportunity, Plus, Search, Top,
} from '@element-plus/icons-vue'
import {
  workbenchApi,
  type WbCaptureBrief, type WbItemNode,
} from '../api/workbench'
import VditorEditor from '../components/VditorEditor.vue'
import EmptyState from '../components/EmptyState.vue'

const OPEN_STORAGE_KEY = 'krs_wb_open_map_v2'

const loading = ref(false)
const items = ref<WbItemNode[]>([])

// 展开状态映射：id -> boolean（支持多项同时展开）
const openMap = ref<Record<number, boolean>>({})

// 各事项的 Markdown 正文缓存：id -> content
const contents = ref<Record<number, string>>({})
// 各事项的加载状态
const loadingMap = ref<Record<number, boolean>>({})
// 各事项的保存状态：'saved' | 'saving' | 'err'
const saveStatusMap = ref<Record<number, { text: string; cls: string }>>({})
// 各事项的 dirty 标记与防抖定时器
const dirtyMap = ref<Record<number, boolean>>({})
const saveTimers = new Map<number, any>()

// 随手记抽屉
const drawerOpen = ref(false)
const quickText = ref('')
const quickSource = ref('')
const quickUrl = ref('')
const quickSaving = ref(false)

// 暂存箱数据
const inboxTotal = ref(0)
const inboxList = ref<WbCaptureBrief[]>([])
const inboxLoading = ref(false)
const inboxQ = ref('')
let inboxTimer: any = null

/* ---------------- 展开控制 ---------------- */

function loadOpenMap() {
  try {
    const raw = localStorage.getItem(OPEN_STORAGE_KEY)
    if (raw) openMap.value = JSON.parse(raw)
  } catch {
    openMap.value = {}
  }
}

function saveOpenMap() {
  try {
    localStorage.setItem(OPEN_STORAGE_KEY, JSON.stringify(openMap.value))
  } catch { /* ignore */ }
}

function isOpen(id: number): boolean {
  return !!openMap.value[id]
}

const allExpanded = computed(() => {
  if (!items.value.length) return false
  for (const it of items.value) {
    if (!openMap.value[it.id]) return false
    for (const sub of it.children || []) {
      if (!openMap.value[sub.id]) return false
    }
  }
  return true
})

function toggleAll(open: boolean) {
  for (const it of items.value) {
    openMap.value[it.id] = open
    if (open && contents.value[it.id] === undefined) {
      loadContent(it.id)
    }
    for (const sub of it.children || []) {
      openMap.value[sub.id] = open
      if (open && contents.value[sub.id] === undefined) {
        loadContent(sub.id)
      }
    }
  }
  saveOpenMap()
}

async function toggle(id: number) {
  const next = !openMap.value[id]
  openMap.value[id] = next
  saveOpenMap()
  if (next && contents.value[id] === undefined) {
    await loadContent(id)
  }
}

/* ---------------- 事项正文加载与自动保存 ---------------- */

async function loadContent(id: number) {
  if (loadingMap.value[id]) return
  loadingMap.value[id] = true
  try {
    const res = await workbenchApi.getThinking(id)
    contents.value[id] = res.content || ''
    saveStatusMap.value[id] = { text: '已保存', cls: 'ok' }
  } catch (err: any) {
    contents.value[id] = ''
    saveStatusMap.value[id] = { text: '加载失败', cls: 'err' }
  } finally {
    loadingMap.value[id] = false
  }
}

function onContentInput(id: number, val: string) {
  contents.value[id] = val
  dirtyMap.value[id] = true
  saveStatusMap.value[id] = { text: '保存中…', cls: 'busy' }

  if (saveTimers.has(id)) {
    clearTimeout(saveTimers.get(id))
  }
  const timer = setTimeout(() => {
    saveItem(id)
  }, 1200)
  saveTimers.set(id, timer)
}

async function saveItem(id: number) {
  if (!dirtyMap.value[id]) return
  const text = contents.value[id] ?? ''
  saveStatusMap.value[id] = { text: '保存中…', cls: 'busy' }
  try {
    const res = await workbenchApi.putThinking(id, text)
    dirtyMap.value[id] = false
    saveStatusMap.value[id] = { text: '已保存', cls: 'ok' }
    if (res.title_adopted) {
      await loadOverview(false)
    }
  } catch (err: any) {
    saveStatusMap.value[id] = { text: '保存失败', cls: 'err' }
  }
}

/* ---------------- 事项树加载与管理 ---------------- */

const allItemOptions = computed(() => {
  const opts: { id: number; label: string }[] = []
  for (const it of items.value) {
    opts.push({ id: it.id, label: it.title })
    for (const sub of it.children || []) {
      opts.push({ id: sub.id, label: `${it.title} › ${sub.title}` })
    }
  }
  return opts
})

async function loadOverview(showSpinner = true) {
  if (showSpinner) loading.value = true
  try {
    const res = await workbenchApi.overview()
    items.value = res.items || []
    inboxTotal.value = res.inbox_total || 0

    // 对所有已处于展开状态的事项，预先拉取正文
    for (const it of items.value) {
      if (openMap.value[it.id] && contents.value[it.id] === undefined) {
        loadContent(it.id)
      }
      for (const sub of it.children || []) {
        if (openMap.value[sub.id] && contents.value[sub.id] === undefined) {
          loadContent(sub.id)
        }
      }
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '工作台数据加载失败')
  } finally {
    if (showSpinner) loading.value = false
  }
}

async function newItem(parentId: number | null = null) {
  const isSub = parentId !== null
  try {
    const { value } = await ElMessageBox.prompt(
      isSub ? '请输入子事项名称（例如：回归分析、实验代码）：' : '请输入事项名称（例如：准备会议 PPT、推进论文、期中考）：',
      isSub ? '新建子事项' : '新建主事项',
      { confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/, inputErrorMessage: '名称不能为空' },
    )
    const title = value?.trim()
    if (!title) return
    const res = await workbenchApi.createItem(title, parentId)
    ElMessage.success('创建成功')
    await loadOverview(false)
    // 自动展开新建的事项并拉取正文
    if (parentId !== null) {
      openMap.value[parentId] = true
    }
    openMap.value[res.id] = true
    saveOpenMap()
    await loadContent(res.id)
  } catch (err: any) {
    if (err === 'cancel') return
    ElMessage.error(err?.response?.data?.detail || '创建事项失败')
  }
}

async function moveItem(id: number, dir: 'up' | 'down') {
  try {
    await workbenchApi.moveItem(id, dir)
    await loadOverview(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '移动失败')
  }
}

async function onItemCmd(it: { id: number; title: string }, cmd: string) {
  if (cmd === 'rename') {
    try {
      const { value } = await ElMessageBox.prompt('重命名事项：', '重命名', {
        inputValue: it.title,
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputPattern: /\S+/,
        inputErrorMessage: '名称不能为空',
      })
      const title = value?.trim()
      if (!title || title === it.title) return
      await workbenchApi.patchItem(it.id, { title })
      ElMessage.success('已重命名')
      await loadOverview(false)
    } catch { /* cancel */ }
    return
  }
  if (cmd === 'sub') {
    await newItem(it.id)
    return
  }
  if (cmd === 'archive') {
    try {
      await ElMessageBox.confirm('归档后随笔完整保留，但不再出现在首页列表。确定归档？', '归档事项', {
        type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消',
      })
      await workbenchApi.patchItem(it.id, { archived: true })
      ElMessage.success('已归档')
      delete openMap.value[it.id]
      saveOpenMap()
      await loadOverview(false)
    } catch { /* cancel */ }
    return
  }
  if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm(
        `确定删除「${it.title}」？随笔将进入回收站，可按需恢复。`,
        '删除事项',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
      await workbenchApi.deleteItem(it.id)
      ElMessage.success('已删除')
      delete openMap.value[it.id]
      delete contents.value[it.id]
      saveOpenMap()
      await loadOverview(false)
    } catch { /* cancel */ }
  }
}

/* ---------------- 随手记 / 碎片收集箱 ---------------- */

async function onDrawerOpen() {
  await loadInboxList()
}

async function loadInboxList() {
  inboxLoading.value = true
  try {
    const res = await workbenchApi.listCaptures({ scope: 'inbox', q: inboxQ.value, limit: 100 })
    inboxList.value = res.items || []
    inboxTotal.value = res.total || 0
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '暂存箱加载失败')
  } finally {
    inboxLoading.value = false
  }
}

function onInboxSearch() {
  clearTimeout(inboxTimer)
  inboxTimer = setTimeout(() => {
    loadInboxList()
  }, 300)
}

async function saveToInbox() {
  const text = quickText.value.trim()
  if (!text && !quickUrl.value.trim()) {
    ElMessage.warning('请填写文字或链接')
    return
  }
  quickSaving.value = true
  try {
    await workbenchApi.createCapture({
      text,
      source: quickSource.value.trim(),
      url: quickUrl.value.trim(),
      item_id: null,
    })
    ElMessage.success('已存入暂存箱')
    quickText.value = ''
    quickSource.value = ''
    quickUrl.value = ''
    await loadInboxList()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存失败')
  } finally {
    quickSaving.value = false
  }
}

/** 直接将随手记追加到某事项的 Markdown 正文末尾 */
async function appendToItem(itemId: number) {
  const text = quickText.value.trim()
  if (!text) {
    ElMessage.warning('内容为空')
    return
  }
  const itemOpt = allItemOptions.value.find((o) => o.id === itemId)
  const itemTitle = itemOpt ? itemOpt.label : '该事项'

  try {
    // 确保已有正文拉下来
    if (contents.value[itemId] === undefined) {
      await loadContent(itemId)
    }
    const current = contents.value[itemId] || ''
    const metaTag = quickSource.value.trim() ? `（来源: ${quickSource.value.trim()}）` : ''
    const urlTag = quickUrl.value.trim() ? `\n> 链接: ${quickUrl.value.trim()}` : ''
    const appendBlock = `\n\n---\n> 💡 **随手记** ${metaTag}${urlTag}\n\n${text}\n`
    const updated = (current + appendBlock).trim()

    contents.value[itemId] = updated
    dirtyMap.value[itemId] = true
    await saveItem(itemId)

    ElMessage.success(`已追加到「${itemTitle}」随笔`)
    quickText.value = ''
    quickSource.value = ''
    quickUrl.value = ''
    // 自动展开该事项方便查看
    openMap.value[itemId] = true
    saveOpenMap()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '追加失败')
  }
}

/** 将暂存箱已有片段追加到事项随笔 */
async function appendCaptureToItem(cap: WbCaptureBrief, itemId: number) {
  try {
    // 先获取全文
    const full = await workbenchApi.getCapture(cap.id)
    if (contents.value[itemId] === undefined) {
      await loadContent(itemId)
    }
    const current = contents.value[itemId] || ''
    const metaTag = full.source ? `（来源: ${full.source}）` : ''
    const urlTag = full.url ? `\n> 链接: ${full.url}` : ''
    const appendBlock = `\n\n---\n> 💡 **收集片段** ${metaTag}${urlTag}\n\n${full.text}\n`
    const updated = (current + appendBlock).trim()

    contents.value[itemId] = updated
    dirtyMap.value[itemId] = true
    await saveItem(itemId)

    // 追加后将该片段从暂存箱删除
    await workbenchApi.deleteCapture(cap.id)
    ElMessage.success('已追加到事项随笔')
    await loadInboxList()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '追加失败')
  }
}

async function promoteCapture(capId: number) {
  try {
    const res = await workbenchApi.promoteCapture(capId)
    ElMessage.success(`已整理成新事项「${res.title}」`)
    await loadOverview(false)
    await loadInboxList()
    openMap.value[res.id] = true
    saveOpenMap()
    await loadContent(res.id)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '整理失败')
  }
}

async function removeCapture(capId: number) {
  try {
    await workbenchApi.deleteCapture(capId)
    ElMessage.success('已删除片段')
    await loadInboxList()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '删除失败')
  }
}

/* ---------------- 辅助工具 ---------------- */

function fmtTime(s: string) {
  if (!s) return ''
  return s.length >= 16 ? s.slice(5, 16) : s
}

function shortUrl(u: string) {
  if (!u) return ''
  return u.length > 36 ? `${u.slice(0, 36)}…` : u
}

function flushAllDirty() {
  const token = localStorage.getItem('krs_token') || ''
  for (const [idStr, dirty] of Object.entries(dirtyMap.value)) {
    if (!dirty) continue
    const id = Number(idStr)
    const text = contents.value[id] || ''
    try {
      fetch(`/api/workbench/items/${id}/thinking`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ content: text }),
        keepalive: true,
      }).catch(() => {})
    } catch { /* ignore */ }
  }
}

function onPageHide() {
  flushAllDirty()
}

onMounted(async () => {
  loadOpenMap()
  window.addEventListener('pagehide', onPageHide)
  await loadOverview()

  // 如果此前没有任何展开项，默认展开第一个事项
  if (items.value.length && Object.keys(openMap.value).length === 0) {
    openMap.value[items.value[0].id] = true
    saveOpenMap()
    await loadContent(items.value[0].id)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPageHide)
  for (const [, timer] of saveTimers) {
    clearTimeout(timer)
  }
  flushAllDirty()
})
</script>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px 20px 80px;
}

/* 顶栏 */
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  margin-bottom: 18px;
  border-radius: 14px;
}
.head-left { display: flex; flex-direction: column; gap: 2px; }
.head-title { font-size: 20px; font-weight: 800; letter-spacing: .5px; }
.head-sub { font-size: 12.5px; color: var(--txt3); }
html.theme-dark .head-sub { color: var(--txt2); }
.head-actions { display: flex; align-items: center; gap: 10px; }
.quick-btn {
  background: var(--acc-grad) !important;
  color: #fff !important;
  font-weight: 600;
  border: none !important;
}

/* 事项树 */
.item-tree { display: grid; gap: 14px; }
.item-card {
  border-radius: 14px;
  overflow: hidden;
  transition: all .2s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid rgba(148, 163, 184, 0.22);
}
.item-card.open {
  box-shadow: 0 8px 24px rgba(139, 92, 246, 0.08);
}

.item-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
  cursor: pointer;
  user-select: none;
  background: rgba(255, 255, 255, 0.35);
}
html.theme-dark .item-head {
  background: rgba(30, 41, 59, 0.4);
}
.item-head:hover {
  background: rgba(167, 139, 250, 0.08);
}
.caret { flex: none; color: var(--acc2); transition: transform .15s; }
.item-title {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--txt1);
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-badge {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(167, 139, 250, 0.15);
  color: var(--acc2);
  font-weight: 600;
  flex: none;
}
.head-spacer { flex: 1; }
.item-time { font-size: 11.5px; color: var(--txt3); flex: none; }
html.theme-dark .item-time { color: var(--txt2); }

.save-tag {
  font-size: 11.5px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 6px;
  flex: none;
}
.save-tag.ok { color: #16a34a; background: rgba(22, 163, 74, 0.1); }
.save-tag.busy { color: var(--acc2); background: rgba(139, 92, 246, 0.1); }
.save-tag.err { color: #dc2626; background: rgba(220, 38, 38, 0.1); }

.item-ops { display: flex; align-items: center; gap: 4px; flex: none; }

/* 展开区域 */
.item-body {
  padding: 12px 18px 18px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}
.editor-wrap {
  margin-bottom: 12px;
  border-radius: 10px;
  overflow: hidden;
}

/* 子事项嵌套区 */
.children-wrap {
  margin-top: 14px;
  padding-left: 20px;
  border-left: 2px dashed rgba(167, 139, 250, 0.35);
  display: grid;
  gap: 8px;
}
.children-list { display: grid; gap: 8px; }
.sub-card {
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
}
.sub-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  cursor: pointer;
  user-select: none;
  background: rgba(255, 255, 255, 0.25);
}
html.theme-dark .sub-head {
  background: rgba(30, 41, 59, 0.3);
}
.sub-head:hover {
  background: rgba(167, 139, 250, 0.08);
}
.sub-title {
  font-size: 14px;
  font-weight: 600;
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-tag { font-size: 11px; }
.sub-body {
  padding: 10px 14px 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
}

.add-sub-bar {
  display: flex;
  align-items: center;
  padding: 2px 0;
}
.add-sub-btn {
  color: var(--acc2) !important;
  font-size: 12.5px;
}

/* 右下角悬浮随手记气泡 */
.fab-bubble {
  position: fixed;
  right: 32px;
  bottom: 32px;
  z-index: 99;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: 999px;
  cursor: pointer;
  background: var(--acc-grad);
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  box-shadow: 0 8px 24px rgba(139, 92, 246, 0.45);
  transition: all .2s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid rgba(255, 255, 255, 0.35);
}
.fab-bubble:hover {
  transform: translateY(-2px) scale(1.03);
  box-shadow: 0 12px 30px rgba(139, 92, 246, 0.6);
}
.fab-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: #fff;
  color: var(--acc2);
  font-weight: 800;
}

/* 抽屉样式 */
.drawer-title-wrap { display: flex; flex-direction: column; gap: 2px; }
.drawer-title { font-size: 17px; font-weight: 800; color: var(--txt1); }
.drawer-sub { font-size: 12px; color: var(--txt3); }
html.theme-dark .drawer-sub { color: var(--txt2); }

.drawer-content { display: grid; gap: 16px; padding: 0 4px; }
.quick-editor-box {
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.25);
}
.quick-meta-row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.quick-src { width: 180px; flex: none; }
.quick-url { flex: 1; }
.quick-action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

.inbox-section { display: grid; gap: 10px; margin-top: 6px; }
.inbox-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.inbox-title { font-size: 14px; font-weight: 700; color: var(--txt1); }
.inbox-cnt { font-size: 12px; color: var(--txt3); }
html.theme-dark .inbox-cnt { color: var(--txt2); }

.inbox-list {
  display: grid;
  gap: 8px;
  max-height: 48vh;
  overflow-y: auto;
  padding-right: 2px;
}
.inbox-card {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}
.inbox-card-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--txt1);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.inbox-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 11.5px;
}
.inbox-url {
  color: var(--acc2);
  text-decoration: none;
  font-size: 11.5px;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-time { color: var(--txt3); }
html.theme-dark .inbox-time { color: var(--txt2); }
.inbox-empty {
  text-align: center;
  padding: 30px 0;
  font-size: 12.5px;
  color: var(--txt3);
}
html.theme-dark .inbox-empty { color: var(--txt2); }
</style>
