<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">笔记 · 博客</div>
        <div class="page-sub">学习笔记 / 博客文章 / 项目经历 —— 全部在网页上创建与修改</div>
      </div>
      <div class="head-ops">
        <el-button :loading="importing" @click="pickImport" title="导入 .pptx / .pdf 成为可直接书写的多页笔记（也可把文件拖到页面上）">
          <el-icon style="margin-right:4px"><Upload /></el-icon>
          {{ importing ? (impProgress ? `导入中 ${impProgress}` : '导入中…') : '导入 PPT / PDF' }}
        </el-button>
        <el-button @click="toggleCardCreator" title="在当前目录直接新建速记卡片，无需跳入新页面">
          <el-icon style="margin-right:4px"><Postcard /></el-icon>
          {{ cardCreatorOpen ? '收起速记' : '新建速记' }}
        </el-button>
        <el-button type="primary" @click="newNote">
          <el-icon style="margin-right:4px"><Plus /></el-icon>新建笔记
        </el-button>
        <el-button @click="trashOpen = true">回收站</el-button>
        <input
          ref="impInput" type="file" multiple class="hidden-input"
          accept=".pptx,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/pdf"
          @change="onImportFiles"
        />
      </div>
    </div>

    <div class="col">
      <!-- 面包屑 + 目录操作 -->
      <div class="crumbs glass">
        <button class="crumb" :class="{ on: selFolder === null }" @click="pickDir(null)" title="根视图：各一级目录卡片 + 未分类文章">全部目录</button>
        <template v-for="seg in crumbSegs" :key="seg.path">
          <span class="crumb-sep">/</span>
          <button class="crumb" :class="{ on: selFolder === seg.path }" @click="pickDir(seg.path)">{{ seg.name }}</button>
        </template>
        <span class="crumbs-spacer" />
        <el-button size="small" text @click="quickCreate">
          <el-icon style="margin-right:2px"><FolderAdd /></el-icon>{{ selFolder ? '新建子目录' : '新建目录' }}
        </el-button>
        <el-button size="small" text @click="mgrOpen = true">
          <el-icon style="margin-right:2px"><Setting /></el-icon>管理目录
        </el-button>
      </div>

      <!-- 当前层目录卡片：根视图=所有一级目录；目录视图=直接子目录（子目录不出现在主页面） -->
      <div v-if="levelDirs.length" class="dirgrid">
        <div v-for="f in levelDirs" :key="dirPath(f)" class="dircard glass" role="button" tabindex="0" @click="pickDir(dirPath(f))" @keydown.enter.prevent="pickDir(dirPath(f))" @keydown.space.prevent="pickDir(dirPath(f))">
          <div class="dc-ico"><el-icon :size="26"><Folder /></el-icon></div>
          <div class="dc-meta">
            <div class="dc-name" :title="f.name">{{ f.name }}</div>
            <div class="dc-sub" title="含子目录内的笔记">{{ f.count }} 篇</div>
          </div>
          <span class="dc-add" :title="`在「${f.name}」下新建子目录`" @click.stop="addSub(f)"><el-icon><FolderAdd /></el-icon></span>
        </div>
      </div>
      <div v-else class="dir-hint">
        <template v-if="selFolder === null">还没有目录<br>点右上角「新建目录」，把笔记分门别类</template>
        <template v-else>这个目录下还没有子目录<br>点右上角「新建子目录」继续细分</template>
      </div>

      <!-- 筛选条 -->
      <div class="filters glass">
        <el-input v-model="q" placeholder="搜索标题 / 摘要 / 标签…" clearable style="width: 220px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="type-tabs">
          <button
            v-for="t in typeTabs" :key="t.value" class="ttab"
            :class="{ on: type === t.value }" @click="type = t.value"
          >{{ t.label }}</button>
        </div>
        <el-select v-model="sortBy" size="small" style="width: 128px" @change="onSortChange">
          <el-option label="最新更新" value="updated" />
          <el-option label="标题 A-Z" value="title" />
        </el-select>
        <div v-if="tags.length" class="tags">
          <el-tag
            v-for="t in tags" :key="t.name" size="small" effect="plain" class="tag"
            :type="tag === t.name ? 'primary' : 'info'"
            @click="tag = tag === t.name ? '' : t.name"
          >#{{ t.name }} {{ t.count }}</el-tag>
        </div>
        <span class="cnt">{{ realNotes }} 篇</span>
      </div>

      <!-- 未分类分组标题（仅根视图且非搜索态，文章只在其最邻近上级目录显示） -->
      <div v-if="selFolder === null && !searchAll && items.length" class="group-label">未分类（{{ uncatCnt }} 篇）</div>
      <!-- 全库搜索提示条（搜索框非空时跨目录搜索） -->
      <div v-if="searchAll" class="search-hint">全库搜索中（跨目录）· 找到 {{ realNotes }} 篇 · 清空搜索框回到当前目录</div>

      <!-- 列表容器：首屏/刷新期间 v-loading 加载态，避免慢网无反馈、空状态误判 -->
      <div class="list-wrap" v-loading="listLoading">
        <!-- 行内速记卡片创建面板：就地创建、就地保存、不跳转新界面 -->
        <transition name="el-zoom-in-top">
          <div v-if="cardCreatorOpen" class="inline-card-box glass">
            <div class="icb-header">
              <div class="icb-title">
                <el-icon :size="16" class="icb-ico"><Postcard /></el-icon>
                <span class="icb-name">新建速记小卡片</span>
                <span class="icb-dir-badge" :title="selFolder ? `归入目录: ${selFolder}` : '根目录: 未分类'">
                  <el-icon :size="12"><Folder /></el-icon>
                  {{ selFolder || '未分类' }}
                </span>
              </div>
              <button type="button" class="icb-close-btn" title="收起 (Esc)" @click="cardCreatorOpen = false">
                <el-icon :size="14"><Close /></el-icon>
              </button>
            </div>

            <div class="icb-body">
              <input
                ref="cardTitleRef"
                v-model="cardDraft.title"
                class="icb-input-title"
                placeholder="卡片标题（可选，留空将自动使用首行或当前时间）"
                maxlength="100"
                @keydown.enter.prevent="cardContentRef?.focus()"
              />
              <textarea
                ref="cardContentRef"
                v-model="cardDraft.content"
                class="icb-input-content"
                rows="4"
                placeholder="直接在此输入速记内容，支持 Markdown，按 Ctrl+Enter 立即保存…"
                @keydown="onCardKeydown"
              />
              <div class="icb-meta-bar">
                <div class="icb-tags-wrap">
                  <span class="icb-tag-lbl">标签:</span>
                  <input
                    v-model="cardDraft.tagsText"
                    class="icb-input-tags"
                    placeholder="标签（逗号或空格分隔）"
                  />
                  <div class="icb-pills">
                    <button
                      v-for="qt in ['#灵感', '#待办', '#速记', '#备忘', '#学习']"
                      :key="qt"
                      type="button"
                      class="icb-pill"
                      :class="{ active: cardDraft.tagsText.includes(qt.slice(1)) }"
                      @click="addCardTag(qt.slice(1))"
                    >{{ qt }}</button>
                  </div>
                </div>
              </div>
            </div>

            <div class="icb-footer">
              <div class="icb-shortcut-hint">
                <kbd>Ctrl</kbd> + <kbd>Enter</kbd> 快捷保存 · 自动同步至当前目录
              </div>
              <div class="icb-actions">
                <el-button size="small" @click="cardCreatorOpen = false">取消</el-button>
                <el-button type="primary" size="small" :loading="cardSaving" @click="saveQuickCard">
                  <el-icon style="margin-right:3px"><Check /></el-icon>保存速记
                </el-button>
              </div>
            </div>
          </div>
        </transition>

        <!-- 列表（含雅思学习虚拟卡，归类为学习笔记） -->
        <div v-if="items.length" class="list">
          <template v-for="n in sortedItems" :key="n.id">
            <!-- 速记小卡片：支持在目录页面直接阅读正文，展开全文与行内快速编辑，不跳转新页面 -->
            <div
              v-if="n.fmt === 'card'"
              class="note-card memo-card glass"
              :class="{ expanded: expandedCardIds.has(n.id), editing: editingCardId === n.id }"
              role="article"
              tabindex="0"
              @click="onCardClick(n)"
            >
              <div class="nc-top">
                <span class="chip card-chip">速记卡片</span>
                <span class="nc-title" :title="n.title">{{ n.title }}</span>
                <span class="nc-time">{{ n.updated?.slice(5, 16) }}</span>
              </div>

              <!-- 行内快速编辑 -->
              <div v-if="editingCardId === n.id" class="memo-inline-editor" @click.stop>
                <input
                  v-model="cardEditDraft.title"
                  class="icb-input-title"
                  placeholder="标题"
                />
                <textarea
                  v-model="cardEditDraft.content"
                  class="icb-input-content"
                  rows="4"
                  placeholder="速记正文…"
                  @keydown="onEditCardKeydown($event, n)"
                />
                <div class="memo-edit-ops">
                  <span class="icb-shortcut-hint"><kbd>Ctrl+Enter</kbd> 保存修改</span>
                  <div class="memo-edit-btns">
                    <el-button size="small" @click.stop="cancelEditCard">取消</el-button>
                    <el-button size="small" type="primary" :loading="cardEditSaving" @click.stop="saveEditCard(n)">保存</el-button>
                  </div>
                </div>
              </div>

              <!-- 目录页直接浏览速记正文 -->
              <template v-else>
                <div class="memo-content-view" :class="{ clamp: !expandedCardIds.has(n.id) }">
                  <div class="memo-text">{{ n.content || n.summary || '（空速记卡片）' }}</div>
                </div>
                <div class="nc-tags">
                  <el-tag v-for="t in n.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
                  <span class="nc-ops">
                    <el-button
                      v-if="(n.content || n.summary || '').length > 120"
                      text size="small"
                      @click.stop="toggleCardExpand(n)"
                    >
                      {{ expandedCardIds.has(n.id) ? '收起' : '展开' }}
                    </el-button>
                    <el-button text size="small" @click.stop="startEditCard(n)">快速修改</el-button>
                    <el-button text size="small" @click.stop="rename(n)">改名</el-button>
                    <el-button text size="small" @click.stop="openMeta(n)">信息</el-button>
                  </span>
                </div>
              </template>
            </div>

            <!-- 普通笔记 / 博客 / 项目经历 -->
            <div
              v-else
              class="note-card glass"
              :class="{ 'v-ielts': n.id === IELTS_ID }" role="button" tabindex="0"
              @click="openNote(n)" @keydown.enter.prevent="openNote(n)" @keydown.space.prevent="openNote(n)"
            >
              <div class="nc-top">
                <span class="chip">{{ typeLabel(n.type) }}</span>
                <span v-if="n.ppt" class="ppt-chip" :title="'PPT 笔记：' + n.ppt">PPT</span>
                <span v-else-if="n.pdf" class="pdf-chip" :title="'PDF 笔记：' + n.pdf">PDF</span>
                <span v-else-if="n.fmt === 'ink'" class="ink-chip" title="白板手写笔记">白板</span>
                <span v-if="n.id === IELTS_ID" class="mini-logo">雅</span>
                <span v-if="n.subs" class="subs-chip" :title="`含 ${n.subs} 个子页`">子页 {{ n.subs }}</span>
                <span class="nc-title" :title="n.title">{{ n.title }}</span>
                <span class="nc-time" :class="{ pin: n.id === IELTS_ID && sortBy === 'title' }" :title="n.id === IELTS_ID ? '雅思学习入口卡固定置顶，不参与排序' : ''">{{ n.id === IELTS_ID ? (sortBy === 'title' ? '置顶' : '打卡') : n.updated?.slice(5, 16) }}</span>
              </div>
              <div class="nc-sum">{{ n.summary || '（无摘要 —— 点击进入编辑补充）' }}</div>
              <div class="nc-tags">
                <el-tag v-for="t in n.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
                <span v-if="n.id !== IELTS_ID" class="nc-ops">
                  <el-button text size="small" @click.stop="rename(n)">改名</el-button>
                  <el-button text size="small" @click.stop="openMeta(n)">信息</el-button>
                </span>
              </div>
            </div>
          </template>
        </div>

        <EmptyState v-else-if="!listLoading" icon="Notebook" :title="emptyTitle" :desc="emptyDesc"
          :features="['博客 / 学习笔记 / 项目经历 三种分类', '所见即所得 Markdown：# 标题、公式、表格边打边出效果', '站内引用其它文章 · 正文 AES 加密存储 · 可导出 PDF']">
          <template #default>
            <el-button type="primary" round style="margin-top:18px" @click="newNote">
              {{ selFolder === null ? '写下第一篇' : '新建笔记' }}
            </el-button>
            <el-button v-if="hasFilter" round style="margin-top:18px; margin-left:10px" @click="clearFilters">清除筛选</el-button>
          </template>
        </EmptyState>
      </div>
    </div>

    <!-- 拖拽导入遮罩：把 .pptx / .pdf 拖进页面任意位置即可导入（支持多文件） -->
    <div v-if="dragOver" class="drop-mask">
      <div class="drop-card">
        <el-icon class="drop-ico"><Upload /></el-icon>
        <div class="drop-t">松开即导入</div>
        <div class="drop-s">支持 .pptx / .pdf · 可一次拖入多个文件，按顺序导入到当前目录</div>
      </div>
    </div>

    <FolderDialog v-model="mgrOpen" module="" @changed="onDirChanged" />

    <!-- 笔记信息（分类/目录/标签/摘要） -->
    <el-dialog v-model="metaOpen" title="笔记信息" width="440px">
      <el-form label-position="top">
        <el-form-item label="分类">
          <el-radio-group v-model="metaDraft.type">
            <el-radio-button value="blog">博客</el-radio-button>
            <el-radio-button value="note">学习笔记</el-radio-button>
            <el-radio-button value="project">项目经历</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目录">
          <el-select v-model="metaDraft.folder" style="width: 100%">
            <el-option label="未分类" value="" />
            <el-option v-for="o in dirOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签（逗号分隔）">
          <el-input v-model="metaDraft.tagsText" placeholder="如：深度学习, 论文笔记" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="metaDraft.summary" type="textarea" :rows="2" maxlength="600" placeholder="一两句话概括这篇文章" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="meta-footer">
          <el-button type="danger" :loading="metaDeleting" @click="doDelete">删除这篇笔记</el-button>
          <span class="spacer" />
          <el-button @click="metaOpen = false">取消</el-button>
          <el-button type="primary" :loading="metaSaving" @click="saveMeta">保存</el-button>
        </div>
      </template>
    </el-dialog>
    <TrashDialog v-model="trashOpen" @restored="() => { fetchAll(); refreshDir() }" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderAdd, Plus, Search, Setting, Upload, Postcard, Check, Close } from '@element-plus/icons-vue'
import { api, http } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import FolderDialog from '../components/FolderDialog.vue'
import TrashDialog from '../components/TrashDialog.vue'

const trashOpen = ref(false)

interface Note { id: string; title: string; type: string; fmt?: string; ppt?: string; pdf?: string; subs?: number; tags: string[]; summary: string; created: string; updated: string; content?: string }
/** 目录：path=自身全路径（顶层=名字），parent=父目录全路径（''=顶层）；兼容期后端未返回 path 时回落到 name */
interface Dir { name: string; path?: string; parent?: string; count: number }

/** 雅思学习：虚拟卡，归类为「学习笔记」，置顶展示，点击进 /ielts */
const IELTS_ID = 'ielts'
const VIRTUAL_IELTS: Note = {
  id: IELTS_ID,
  title: '雅思学习',
  type: 'note',
  tags: ['雅思', '备考'],
  summary: '听力 / 口语 / 阅读 / 写作 —— 四栏时间线打卡，学完一项勾一项，附备考资料直达',
  created: '',
  updated: '学习打卡',
}

const route = useRoute()
const router = useRouter()
const q = ref('')
const type = ref('')
const tag = ref('')
/** 排序：'updated'=最新更新（后端文件更新时间倒序，默认）；'title'=标题 A-Z（中文 zh-Hans-CN）。持久化到 localStorage；仅接受 'title'，其余（含非法值）回落 'updated' */
const sortBy = ref<'updated' | 'title'>(localStorage.getItem('krs_notes_sort') === 'title' ? 'title' : 'updated')
const items = ref<Note[]>([])
const listLoading = ref(true) // 列表加载态：首屏/刷新期间为 true，避免慢网无反馈、请求返回前空状态误判
const tags = ref<{ name: string; count: number }[]>([])
/** 目录钻取：null=根视图（一级目录 + 未分类文章）；path=该目录视图（直接子目录 + 直接文章） */
const selFolder = ref<string | null>(null)
const dirs = ref<Dir[]>([])
const totalCnt = ref(0)
const mgrOpen = ref(false)

/* ---------------- 行内小卡片速记状态 ---------------- */
const cardCreatorOpen = ref(false)
const cardSaving = ref(false)
const cardTitleRef = ref<HTMLInputElement | null>(null)
const cardContentRef = ref<HTMLTextAreaElement | null>(null)
const cardDraft = reactive({ title: '', content: '', tagsText: '' })
const expandedCardIds = ref<Set<string>>(new Set())
const editingCardId = ref<string | null>(null)
const cardEditDraft = reactive({ title: '', content: '' })
const cardEditSaving = ref(false)

let timer: ReturnType<typeof setTimeout> | undefined
let listSeq = 0 // 列表请求序号：快速搜索/切换类型/标签时据此丢弃过期响应，避免旧结果覆盖新数据
let syncing = false // 「同步中」短路标记：从 URL 读回/外部导航改本地 ref 时置位，避免 syncQuery↔query-watcher 重复请求或死循环

const realNotes = computed(() => items.value.filter((i) => i.id !== IELTS_ID).length)
/** 全库搜索中：搜索框非空时跨目录搜索，不受当前目录范围限制 */
const searchAll = computed(() => !!q.value.trim())
/** 是否处于筛选态（搜索/类型/标签任一非空）：空状态据此区分「筛选无结果」与「真没数据」 */
const hasFilter = computed(() => !!q.value.trim() || !!type.value || !!tag.value)
/** 展示用列表：雅思虚拟卡固定置顶，其余按 sortBy 本地排序（'updated'=更新时间倒序、空值最后；'title'=标题 A-Z 中文升序）。
    是 items 的重排（同元素），故 realNotes/未分类计数等语义不受影响。 */
const sortedItems = computed<Note[]>(() => {
  const ielts = items.value.find((i) => i.id === IELTS_ID)
  const rest = items.value.filter((i) => i.id !== IELTS_ID)
  if (sortBy.value === 'title') {
    rest.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh-Hans-CN'))
  } else {
    // ISO 风格 'YYYY-MM-DD HH:MM:SS' 直接字符串比较：空值排最后，其余倒序（最新在前）
    rest.sort((a, b) => {
      const au = a.updated || ''
      const bu = b.updated || ''
      if (!au && !bu) return 0
      if (!au) return 1
      if (!bu) return -1
      return bu > au ? 1 : bu < au ? -1 : 0
    })
  }
  return ielts ? [ielts, ...rest] : rest
})
/** 未分类 = 总数 − 各顶层目录子树计数之和（子目录计数已含在顶层内，避免重复计） */
const uncatCnt = computed(() => {
  const sum = dirs.value.filter((f) => !(f.parent || '')).reduce((a, b) => a + b.count, 0)
  return Math.max(0, totalCnt.value - sum)
})

/* ---------------- 目录钻取（子文件夹：path=全路径，parent=父目录全路径） ---------------- */

/** 目录全路径（兼容：后端尚未返回 path 时回落到 name，即原顶层行为） */
function dirPath(f: Dir): string {
  return f.path || f.name
}
/** 层级展示名：顶层=自身名；子级=「父路径 / 名」 */
function dirLabel(f: Dir): string {
  return f.parent ? `${f.parent} / ${f.name}` : f.name
}
function groupByParent(list: Dir[]): Map<string, Dir[]> {
  const m = new Map<string, Dir[]>()
  for (const f of list) {
    const p = f.parent || ''
    const arr = m.get(p)
    if (arr) arr.push(f)
    else m.set(p, [f])
  }
  return m
}
/** 面包屑段：'A/B' → [{name:'A',path:'A'},{name:'B',path:'A/B'}] */
const crumbSegs = computed(() => {
  if (!selFolder.value) return []
  const parts = selFolder.value.split('/')
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})
/** 当前层目录：根视图=一级目录；目录视图=直接子目录（子目录不在主页面出现） */
const levelDirs = computed(() => dirs.value.filter((f) => (f.parent || '') === (selFolder.value ?? '')))
/** 「信息」弹窗目录选项（树序，label=层级全路径） */
const dirOptions = computed(() => {
  const byParent = groupByParent(dirs.value)
  const out: { label: string; value: string }[] = []
  const walk = (parent: string) => {
    for (const f of byParent.get(parent) || []) {
      out.push({ label: dirLabel(f), value: dirPath(f) })
      walk(dirPath(f))
    }
  }
  walk('')
  return out
})

const typeTabs = [
  { value: '', label: '全部' },
  { value: 'blog', label: '博客' },
  { value: 'note', label: '学习笔记' },
  { value: 'project', label: '项目经历' },
]

const emptyTitle = computed(() => (hasFilter.value
  ? '没有匹配的笔记'
  : (selFolder.value === null ? '还没有未分类的笔记' : '这个目录下还没有笔记')))
const emptyDesc = computed(() => (hasFilter.value
  ? '试试换个关键词，或清空筛选条件（清空搜索框、切回「全部」、取消标签选择）。'
  : (selFolder.value === null
    ? '点右上角「新建笔记」，用工具栏式编辑器直接开写 —— 标题/分类/标签/正文全部网页可改，正文加密存储；也可以先建目录再归入。'
    : '点右上角「新建笔记」，创建后会自动归入当前目录，就能在这里看到它。')))

function typeLabel(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

/** 一键清空筛选（搜索/类型/标签），从「没有匹配的笔记」空状态回到当前目录全量 */
function clearFilters() {
  q.value = ''
  type.value = ''
  tag.value = ''
}

/** 排序方式变更：持久化到 localStorage（纯前端本地排序，不重新请求接口） */
function onSortChange() {
  localStorage.setItem('krs_notes_sort', sortBy.value)
}

/** 雅思虚拟卡是否命中当前筛选（仅根视图「未分类」展示） */
function ieltsMatch(): boolean {
  if (selFolder.value !== null) return false
  const v = VIRTUAL_IELTS
  if (type.value && v.type !== type.value) return false
  if (tag.value && !v.tags.includes(tag.value)) return false
  const qq = q.value.trim().toLowerCase()
  if (qq) {
    const hay = `${v.title} ${v.summary} ${v.tags.join(' ')}`.toLowerCase()
    if (!hay.includes(qq)) return false
  }
  return true
}

/** 进阅读页时携带当前筛选态（type/tag/q）：阅读页「返回列表」据此恢复同一筛选视图。
    目录（dir）不在此传 —— 返回哪一层由笔记自身 folder 决定（最邻近目录），不依赖来源视图。 */
function listViewQuery(): Record<string, string> {
  const out: Record<string, string> = {}
  if (type.value) out.type = type.value
  if (tag.value) out.tag = tag.value
  if (q.value.trim()) out.q = q.value.trim()
  return out
}

function openNote(n: Note) {
  if (n.id === IELTS_ID) { router.push('/ielts'); return }
  if (n.fmt === 'card') {
    onCardClick(n)
    return
  }
  router.push({ path: `/notes/${n.id}`, query: listViewQuery() })
}

/* ---------------- 速记小卡片快捷操作（目录页直接完成，不跳新界面） ---------------- */

function toggleCardCreator() {
  cardCreatorOpen.value = !cardCreatorOpen.value
  if (cardCreatorOpen.value) {
    nextTick(() => {
      cardContentRef.value?.focus()
    })
  }
}

function onCardClick(n: Note) {
  if (editingCardId.value === n.id) return
  toggleCardExpand(n)
}

function toggleCardExpand(n: Note) {
  if (expandedCardIds.value.has(n.id)) {
    expandedCardIds.value.delete(n.id)
  } else {
    expandedCardIds.value.add(n.id)
  }
}

function startEditCard(n: Note) {
  editingCardId.value = n.id
  cardEditDraft.title = n.title
  cardEditDraft.content = n.content || n.summary || ''
}

function cancelEditCard() {
  editingCardId.value = null
}

async function saveEditCard(n: Note) {
  cardEditSaving.value = true
  try {
    const rawContent = cardEditDraft.content.trim()
    const autoTitle = cardEditDraft.title.trim() || n.title || '速记卡片'
    await api.put(`/notes/${n.id}`, {
      title: autoTitle,
      type: n.type || 'note',
      fmt: 'card',
      folder: selFolder.value ?? undefined,
      tags: n.tags || [],
      summary: rawContent.slice(0, 200),
      content: rawContent,
    })
    n.title = autoTitle
    n.content = rawContent
    n.summary = rawContent.slice(0, 200)
    editingCardId.value = null
    ElMessage.success('速记卡片已更新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存卡片失败')
  } finally {
    cardEditSaving.value = false
  }
}

async function saveQuickCard() {
  const rawContent = cardDraft.content.trim()
  const rawTitle = cardDraft.title.trim()
  if (!rawContent && !rawTitle) {
    ElMessage.warning('请输入速记内容或标题')
    cardContentRef.value?.focus()
    return
  }
  cardSaving.value = true
  try {
    const firstLine = rawContent.split('\n')[0].replace(/^#+\s*/, '').trim()
    const now = new Date()
    const autoTitle = rawTitle || firstLine.slice(0, 40) || `速记 ${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    const extractedTags = [
      ...cardDraft.tagsText.split(/[,，\s]+/).map((t) => t.trim().replace(/^#/, '')).filter(Boolean),
      ...(rawContent.match(/#([\w\u4e00-\u9fa5]+)/g) || []).map((t) => t.slice(1)),
    ]
    const uniqueTags = Array.from(new Set(extractedTags))
    await http.post('/notes', {
      title: autoTitle,
      type: 'note',
      fmt: 'card',
      folder: selFolder.value || '',
      tags: uniqueTags,
      summary: rawContent.slice(0, 200),
      content: rawContent,
    })
    ElMessage.success('速记卡片已保存')
    cardDraft.title = ''
    cardDraft.content = ''
    cardDraft.tagsText = ''
    cardCreatorOpen.value = false
    await fetchAll()
    await refreshDir()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存速记卡片失败')
  } finally {
    cardSaving.value = false
  }
}

function onCardKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    e.stopPropagation()
    saveQuickCard()
  } else if (e.key === 'Escape') {
    cardCreatorOpen.value = false
  }
}

function onEditCardKeydown(e: KeyboardEvent, n: Note) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    e.stopPropagation()
    saveEditCard(n)
  } else if (e.key === 'Escape') {
    cancelEditCard()
  }
}

function addCardTag(tag: string) {
  const current = cardDraft.tagsText.trim()
  if (!current) {
    cardDraft.tagsText = tag
  } else {
    const list = current.split(/[,，\s]+/)
    if (!list.includes(tag)) {
      cardDraft.tagsText = `${current} ${tag}`
    }
  }
}

/** 钻取/回退：p=null 回根视图；同步 URL ?dir=（支持前进/后退与直达链接） */
function pickDir(p: string | null) {
  if (p === selFolder.value) return
  selFolder.value = p
  const query = { ...route.query }
  if (p) query.dir = p
  else delete query.dir
  router.replace({ query })
  fetchAll()
}

// 外部导航同步（?dir/?type/?tag/?q）统一见下方 onQueryNav（watch route.query）

/** 新建笔记：弹出命名窗口（可留空 = 未命名，之后在列表改名）。
    根视图新建 → 未分类；目录视图新建 → 自动归入当前目录（?folder= 直接带入） */
async function newNote() {
  let title = ''
  try {
    const r = await ElMessageBox.prompt('标题（可留空，之后在列表改名）', '新建笔记', {
      confirmButtonText: '创建', cancelButtonText: '取消', inputValue: '',
    })
    title = (r.value || '').trim()
  } catch { return }
  const params = new URLSearchParams()
  if (title) params.set('title', title)
  if (selFolder.value) params.set('folder', selFolder.value)
  const qs = params.toString()
  router.push(qs ? `/notes/new?${qs}` : '/notes/new')
}

/* ---------------- 卡片：改名 / 信息 ---------------- */

const metaOpen = ref(false)
const metaSaving = ref(false)
const metaDeleting = ref(false)
const metaDraft = reactive({ id: '', type: 'note', folder: '', tagsText: '', summary: '' })
const impInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
/** 多文件导入进度文案（如 2/5） */
const impProgress = ref('')
const dragOver = ref(false)

/* ---------------- 导入 PPT / PDF（拖拽或点选，支持多文件，逐个导入） ---------------- */

function pickImport() {
  impInput.value?.click()
}

async function onImportFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  await importFiles(files)
}

/** 逐个导入：.pptx → /ppt/import；.pdf → /pdf/import（均生成可书写的多页白板笔记） */
async function importFiles(files: File[]) {
  if (!files.length) return
  const imported: string[] = []
  importing.value = true
  try {
    for (let i = 0; i < files.length; i++) {
      const f = files[i]
      const lower = f.name.toLowerCase()
      const isPpt = lower.endsWith('.pptx')
      const isPdf = lower.endsWith('.pdf')
      if (!isPpt && !isPdf) {
        ElMessage.warning(`跳过不支持的文件：${f.name}（仅支持 .pptx / .pdf）`)
        continue
      }
      impProgress.value = files.length > 1 ? `${i + 1}/${files.length}` : ''
      try {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('folder', selFolder.value ?? '')
        // 逐页渲染 + 加密落盘较慢（大文档可达数十秒），放宽超时
        const resp = isPpt
          ? await api.post<any>('/ppt/import', fd, { timeout: 300000 })
          : await api.post<any>('/pdf/import', fd, { timeout: 300000 })
        const r = resp.data
        imported.push(r.id)
        ElMessage.success(`已导入${isPpt ? ' PPT' : ' PDF'}：${r.title}（${r.pages} 页）`)
      } catch (err: any) {
        ElMessage.error(`${f.name} 导入失败：${err?.response?.data?.detail || '请稍后重试'}`)
      }
    }
  } finally {
    importing.value = false
    impProgress.value = ''
    fetchAll()
    refreshDir()
  }
  if (imported.length) router.push(`/notes/${imported[imported.length - 1]}/edit`)
}

/* ---- 页面级拖拽导入 ---- */

function hasFiles(e: DragEvent): boolean {
  const t = e.dataTransfer?.types
  return !!t && Array.from(t).includes('Files')
}

function onDragOver(e: DragEvent) {
  if (!hasFiles(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  dragOver.value = true
}

function onDragLeave(e: DragEvent) {
  if (e.relatedTarget) return // 仍在页面内移动
  dragOver.value = false
}

function onDrop(e: DragEvent) {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  const ok = files.filter((f) => /\.(pptx|pdf)$/i.test(f.name))
  if (!ok.length) {
    ElMessage.warning('仅支持 .pptx / .pdf 文件')
    return
  }
  importFiles(ok)
}

/** 读全量后按 patch 覆盖并 PUT（保留 module/folder/fmt/content 等） */
async function saveNoteFull(id: string, patch: Partial<{ title: string; type: string; folder: string; tagsText: string; summary: string }>) {
  const n = await http.get<any>(`/notes/${id}`)
  const body = {
    title: patch.title ?? n.title,
    type: patch.type ?? n.type,
    module: n.module ?? '',
    folder: patch.folder !== undefined ? patch.folder : (n.folder ?? ''),
    fmt: n.fmt ?? 'md',
    tags: patch.tagsText !== undefined ? patch.tagsText.split(/[,，]/).map((t: string) => t.trim()).filter(Boolean) : n.tags,
    summary: patch.summary !== undefined ? patch.summary : (n.summary ?? ''),
    content: n.content,
  }
  return http.put(`/notes/${id}`, body)
}

async function rename(n: Note) {
  let next = ''
  try {
    const r = await ElMessageBox.prompt('标题：', '重命名', {
      confirmButtonText: '确定', cancelButtonText: '取消', inputValue: n.title, inputPattern: /\S+/,
      inputErrorMessage: '标题不能为空',
    })
    next = (r.value || '').trim()
  } catch { return }
  if (!next || next === n.title) return
  try {
    await saveNoteFull(n.id, { title: next })
    ElMessage.success('已改名')
    fetchAll(); refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '改名失败')
  }
}

async function openMeta(n: Note) {
  try {
    const full = await http.get<any>(`/notes/${n.id}`)
    metaDraft.id = n.id
    metaDraft.type = full.type || 'note'
    metaDraft.folder = full.folder || ''
    metaDraft.tagsText = (full.tags || []).join(', ')
    metaDraft.summary = full.summary || ''
    metaOpen.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

async function saveMeta() {
  if (!metaDraft.id) return
  metaSaving.value = true
  try {
    await saveNoteFull(metaDraft.id, {
      type: metaDraft.type, folder: metaDraft.folder, tagsText: metaDraft.tagsText, summary: metaDraft.summary,
    })
    ElMessage.success('已保存')
    metaOpen.value = false
    fetchAll(); refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    metaSaving.value = false
  }
}

/** 信息弹窗内删除：子页级联进回收站（可恢复）；删除后刷新列表与目录计数 */
async function doDelete() {
  const id = metaDraft.id
  if (!id || metaDeleting.value) return
  let subCnt = 0
  try {
    const r = await http.get<{ items: { id: string }[] }>(`/notes?parent=${encodeURIComponent(id)}`)
    subCnt = r.items.length
  } catch { /* 子页计数失败不阻断，用通用文案 */ }
  try {
    await ElMessageBox.confirm(
      subCnt
        ? `确定删除这篇笔记？其下 ${subCnt} 个子页将一并删除（进回收站，可恢复）。`
        : '确定删除这篇笔记？删除后进入回收站，可随时恢复。',
      '删除笔记', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  metaDeleting.value = true
  try {
    await http.del(`/notes/${id}`)
    ElMessage.success('已删除（回收站可恢复）')
    metaOpen.value = false
    fetchAll(); refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    metaDeleting.value = false
  }
}

async function fetchAll() {
  const seq = ++listSeq // 记录本次请求序号，快速搜索/切换类型/标签时据此丢弃过期响应
  listLoading.value = true // 首屏/刷新期间显示加载态，避免慢网时无反馈
  try {
    const params = new URLSearchParams()
    if (type.value) params.set('type', type.value)
    if (tag.value) params.set('tag', tag.value)
    if (q.value.trim()) params.set('q', q.value.trim())
    // 全库搜索（搜索框非空）时不传 folder/subtree → 后端不过滤，跨目录搜索；否则按当前目录范围
    if (!searchAll.value) {
      // 根视图=未分类（folder=''）；目录视图=精确匹配本层（subtree=false，不含子目录内文章）
      if (selFolder.value === null) {
        params.set('folder', '')
      } else {
        params.set('folder', selFolder.value)
        params.set('subtree', 'false')
      }
    }
    const r = await http.get<{ items: Note[] }>(`/notes?${params.toString()}`)
    if (seq !== listSeq) return // 已有更新的请求发出，丢弃本次过期响应
    const arr = r.items
    if (ieltsMatch()) arr.unshift(VIRTUAL_IELTS)
    items.value = arr
  } catch (e: any) {
    if (seq !== listSeq) return // 丢弃过期响应的错误提示
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '笔记加载失败')
    }
    items.value = []
  } finally {
    if (seq === listSeq) listLoading.value = false // 仅最新请求结束才关加载态，过期响应不得误关
  }
}

/** 刷新标签云（改名/删除/改标签后也要刷新，避免计数过期） */
async function loadTags() {
  try {
    const r = await http.get<{ tags: { name: string; count: number }[] }>('/notes/tags')
    tags.value = r.tags
  } catch { /* 401/423 忽略 */ }
}

/** 刷新目录栏（总数 + 目录计数），并处理被删目录的选中态；不在此刷新列表（由调用方决定，避免重复请求） */
async function refreshDir() {
  try {
    const [fd, all] = await Promise.all([
      http.get<{ items: Dir[] }>('/notes/folders?module='),
      http.get<{ items: Note[] }>('/notes?module='),
    ])
    dirs.value = fd.items
    totalCnt.value = all.items.length
    if (selFolder.value !== null && !fd.items.some((x) => dirPath(x) === selFolder.value)) {
      pickDir(null) // 当前目录已不存在 → 回根视图（pickDir 内部自带 fetchAll 与 URL 清理）
    }
    loadTags() // 刷新标签云计数（loadTags 内部已 try/catch，失败不影响主流程）
  } catch { /* 401/423 忽略 */ }
}

/** 目录管理弹窗改动后：刷新目录树同时刷新列表 */
function onDirChanged() { fetchAll(); refreshDir() }

/** 新建目录：根视图=建一级目录；目录视图=在当前目录下建子目录 */
async function quickCreate() {
  const isSub = !!selFolder.value
  let name = ''
  try {
    const r = await ElMessageBox.prompt('新目录名：', isSub ? `在「${selFolder.value}」下新建子目录` : '新建目录', {
      confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    name = (r.value || '').trim()
  } catch { return }
  try {
    await http.post('/notes/folders', { module: '', name, parent: selFolder.value ?? '' })
    ElMessage.success('已创建')
    refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

/** 在某个目录卡片上新建子目录：parent=目标目录全路径 */
async function addSub(f: Dir) {
  const p = dirPath(f)
  let name = ''
  try {
    const r = await ElMessageBox.prompt('新子目录名：', `在「${f.name}」下新建子目录`, {
      confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    name = (r.value || '').trim()
  } catch { return }
  try {
    await http.post('/notes/folders', { module: '', name, parent: p })
    ElMessage.success('已创建')
    refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

function scheduleFetch() {
  clearTimeout(timer)
  timer = setTimeout(fetchAll, 250)
}

/** 把当前筛选（type/tag/q）写回 URL（replace，不产生历史堆栈；dir 由 pickDir 维护，不在此动） */
function syncQuery() {
  const query = { ...route.query }
  if (type.value) query.type = type.value
  else delete query.type
  if (tag.value) query.tag = tag.value
  else delete query.tag
  if (q.value.trim()) query.q = q.value.trim()
  else delete query.q
  router.replace({ query })
}
/** 用户改类型/标签：写回 URL 后立即刷新（沿用原 watch([type,tag], fetchAll) 语义） */
function onFilterChange() {
  if (syncing) return // 本回合变更源自 URL 导航/读回，onQueryNav（或 onMounted）已统一刷新，跳过避免重复请求
  syncQuery()
  fetchAll()
}
/** 用户改搜索词：写回 URL 后防抖刷新（沿用原 watch(q, scheduleFetch) 语义，保持防抖） */
function onSearchInput() {
  if (syncing) return
  syncQuery()
  scheduleFetch()
}
/** 外部导航同步：浏览器前进/后退或侧栏点「笔记·博客」改变 ?dir/?type/?tag/?q 时跟随。
    只有值确实变化才赋值（避免与 syncQuery 形成无限循环）；任一变化由这里统一发一次请求，
    并置 syncing 让 onFilterChange/onSearchInput 跳过本回合的重复请求。 */
function onQueryNav() {
  const t = typeof route.query.type === 'string' ? route.query.type : ''
  const g = typeof route.query.tag === 'string' ? route.query.tag : ''
  const qq = typeof route.query.q === 'string' ? route.query.q : ''
  const dir = typeof route.query.dir === 'string' && route.query.dir ? route.query.dir : null
  if (dir === selFolder.value && t === type.value && g === tag.value && qq === q.value) return // 无变化（含 syncQuery 回写）
  syncing = true
  if (dir !== selFolder.value) selFolder.value = dir
  if (t !== type.value) type.value = t
  if (g !== tag.value) tag.value = g
  if (qq !== q.value) q.value = qq
  fetchAll() // dir 或 type/tag/q 任一变化：由这里统一发一次请求
  nextTick(() => { syncing = false }) // 待 ref-watcher（pre 刷新）跑完后再放开
}

watch([type, tag], onFilterChange)
watch(q, onSearchInput)
watch([() => route.query.dir, () => route.query.type, () => route.query.tag, () => route.query.q], onQueryNav)

onMounted(() => {
  // 直达链接 /notes?dir=A/B：进入即钻入对应目录
  const d = route.query.dir
  selFolder.value = typeof d === 'string' && d ? d : null
  // 读回筛选参数 type/tag/q（放在 fetchAll 之前，让首次请求带上）；
  // 置 syncing 抑制 ref-watcher 的重复请求，本次由下方显式 fetchAll 统一刷新
  syncing = true
  type.value = typeof route.query.type === 'string' ? route.query.type : ''
  tag.value = typeof route.query.tag === 'string' ? route.query.tag : ''
  q.value = typeof route.query.q === 'string' ? route.query.q : ''
  fetchAll()
  refreshDir()
  // 页面级拖拽导入（.pptx / .pdf，支持多文件）
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('dragleave', onDragLeave)
  window.addEventListener('drop', onDrop)
  loadTags()
  nextTick(() => { syncing = false }) // ref-watcher（pre 刷新）跑完后再放开 syncing
})

onBeforeUnmount(() => {
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('dragleave', onDragLeave)
  window.removeEventListener('drop', onDrop)
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; }
.head-ops { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hidden-input { display: none; }

/* 拖拽导入遮罩 */
.drop-mask {
  position: fixed; inset: 0; z-index: 3000; display: grid; place-items: center;
  background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(2px);
  pointer-events: none;
}
.drop-card {
  display: grid; justify-items: center; gap: 6px;
  padding: 36px 52px; border-radius: 18px; text-align: center;
  border: 2px dashed rgba(167, 139, 250, 0.75);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 24px 70px rgba(30, 20, 80, 0.35);
}
html.theme-dark .drop-card { background: rgba(24, 29, 44, 0.95); }
.drop-ico { font-size: 40px; color: var(--acc2); }
.drop-t { font-size: 18px; font-weight: 800; color: var(--txt1); }
.drop-s { font-size: 12.5px; color: var(--txt2); }
.col { min-width: 0; }

/* 面包屑 + 目录操作 */
.crumbs {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  padding: 8px 14px; margin-bottom: 14px;
}
.crumbs-spacer { flex: 1; }
.crumb {
  border: none; cursor: pointer; background: transparent; font-family: inherit;
  font-size: 13.5px; font-weight: 700; color: var(--txt3); padding: 4px 10px; border-radius: 999px;
}
html.theme-dark .crumb { color: #94a3b8; }
.crumb:hover { background: rgba(167, 139, 250, 0.1); color: var(--txt1); }
html.theme-dark .crumb:hover { color: #cbd5e1; }
.crumb.on { background: var(--acc-grad); color: #fff; }
.crumb-sep { color: var(--txt3); font-size: 12px; }

/* 目录卡片（当前层：一级目录 / 直接子目录） */
.dirgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; margin-bottom: 16px; }
.dircard {
  display: flex; align-items: center; gap: 12px; padding: 14px 16px; cursor: pointer;
  transition: transform .15s, box-shadow .15s;
}
.dircard:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.18); }
.dc-ico {
  flex: none; width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  background: linear-gradient(135deg, rgba(167, 139, 250, 0.2), rgba(56, 189, 248, 0.16));
  color: var(--acc2);
}
html.theme-dark .dc-ico { color: #a78bfa; }
.dc-meta { flex: 1; min-width: 0; }
.dc-name { font-size: 14.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dc-sub { font-size: 11.5px; color: var(--txt3); margin-top: 2px; }
html.theme-dark .dc-sub { color: var(--txt2); }
.dc-add {
  flex: none; display: inline-flex; align-items: center; font-size: 14px;
  color: var(--txt3); opacity: 0; transition: opacity .12s; padding: 4px;
}
.dircard:hover .dc-add, .dircard:focus .dc-add { opacity: 1; }
.dc-add:hover { color: var(--acc2); }
html.theme-dark .dc-add { color: #94a3b8; }
.dir-hint { color: var(--txt2); font-size: 12px; line-height: 1.7; padding: 6px 4px 14px; }

/* 未分类分组标题 */
.group-label { font-size: 12.5px; font-weight: 700; color: var(--txt3); margin: 4px 2px 10px; }
html.theme-dark .group-label { color: var(--txt2); }

/* 全库搜索提示条（搜索框非空时跨目录搜索） */
.search-hint { font-size: 12.5px; font-weight: 700; color: var(--txt3); margin: 4px 2px 10px; }
html.theme-dark .search-hint { color: var(--txt2); }

/* 笔记信息弹窗 footer：删除按钮居左，取消/保存居右 */
.meta-footer { display: flex; align-items: center; gap: 10px; }
.meta-footer .spacer { flex: 1; }

/* 雅思学习虚拟卡（归类学习笔记，置顶醒目） */
.note-card.v-ielts {
  border: 1px solid rgba(244, 114, 182, 0.25);
  background: linear-gradient(135deg, rgba(244, 114, 182, 0.09), rgba(56, 189, 248, 0.07));
}
.mini-logo {
  flex: none; width: 22px; height: 22px; border-radius: 7px;
  display: inline-grid; place-items: center;
  background: linear-gradient(135deg, #f472b6, #38bdf8);
  color: #fff; font-size: 12px; font-weight: 800;
}

.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 14px; margin-bottom: 16px; }
.type-tabs { display: flex; gap: 4px; }
.ttab {
  border: none; cursor: pointer; padding: 5px 11px; border-radius: 999px;
  background: transparent; color: var(--txt3); font-size: 13px; font-family: inherit;
}
html.theme-dark .ttab { color: #cbd5e1; }
.ttab.on { background: var(--acc-grad); color: #fff; font-weight: 600; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { cursor: pointer; }
.cnt { margin-left: auto; color: var(--txt2); font-size: 12px; }

/* 列表容器：给 v-loading 一个最小高度，避免加载态/空状态闪烁与跳动 */
.list-wrap { min-height: 220px; }
.list { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.note-card { padding: 16px 18px; cursor: pointer; transition: transform .15s, box-shadow .15s; }
.note-card:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.18); }
/* 键盘聚焦可见：目录卡/笔记卡可 Tab 进入，聚焦时高亮（无障碍） */
.dircard:focus-visible, .note-card:focus-visible { outline: 2px solid var(--acc2); outline-offset: 2px; }
.nc-top { display: flex; align-items: center; gap: 8px; }
.nc-title { font-size: 15.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-time { margin-left: auto; font-size: 11px; color: var(--txt2); flex: none; font-variant-numeric: tabular-nums; }
.nc-time.pin { color: var(--acc2); font-weight: 700; }
.nc-sum {
  color: var(--txt3); font-size: 13px; line-height: 1.7; margin: 8px 0 10px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
html.theme-dark .nc-sum { color: var(--txt2); }
.nc-tags { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.nc-ops { margin-left: auto; display: inline-flex; gap: 2px; }

.chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: rgba(167, 139, 250, 0.14); color: var(--acc2);
}
.ink-chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(139, 92, 246, 0.16));
  color: var(--acc2); border: 1px solid rgba(56, 189, 248, 0.35);
}
.ppt-chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: linear-gradient(135deg, rgba(251, 146, 60, 0.18), rgba(220, 38, 38, 0.14));
  color: #ea580c; border: 1px solid rgba(251, 146, 60, 0.45); font-weight: 700;
}
.pdf-chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(99, 102, 241, 0.14));
  color: #2563eb; border: 1px solid rgba(59, 130, 246, 0.45); font-weight: 700;
}
/* 子页数量徽标（后端 /notes 每项返回 subs:int；旧响应/雅思虚拟卡无 subs 时不显示） */
.subs-chip { flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px; background: linear-gradient(135deg, rgba(16, 185, 129, 0.16), rgba(56, 189, 248, 0.14)); color: #059669; border: 1px solid rgba(16, 185, 129, 0.42); font-weight: 700; }

/* 行内速记卡片快速创建面板 */
.inline-card-box {
  margin-bottom: 18px;
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid rgba(139, 92, 246, 0.28);
  box-shadow: 0 10px 30px rgba(139, 92, 246, 0.12);
  background: var(--bg-card);
}
.icb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.icb-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 14.5px;
  color: var(--txt);
}
.icb-ico {
  color: var(--acc2);
}
.icb-dir-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: normal;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(167, 139, 250, 0.12);
  color: var(--acc2);
}
.icb-close-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--txt3);
  padding: 4px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  transition: all .15s;
}
.icb-close-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--txt);
}
.icb-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.icb-input-title {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--txt);
  font-size: 14px;
  font-weight: 600;
  outline: none;
  transition: border-color .15s;
}
.icb-input-title:focus {
  border-color: var(--acc2);
}
.icb-input-content {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--txt);
  font-size: 13.5px;
  line-height: 1.6;
  outline: none;
  resize: vertical;
  min-height: 80px;
  font-family: inherit;
  transition: border-color .15s;
}
.icb-input-content:focus {
  border-color: var(--acc2);
}
.icb-meta-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.icb-tags-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1;
}
.icb-tag-lbl {
  font-size: 12px;
  color: var(--txt3);
}
.icb-input-tags {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--txt);
  font-size: 12px;
  outline: none;
  width: 160px;
}
.icb-input-tags:focus {
  border-color: var(--acc2);
}
.icb-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.icb-pill {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--txt3);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  cursor: pointer;
  transition: all .15s;
}
.icb-pill:hover, .icb-pill.active {
  background: rgba(167, 139, 250, 0.16);
  color: var(--acc2);
  border-color: var(--acc2);
}
.icb-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.icb-shortcut-hint {
  font-size: 12px;
  color: var(--txt3);
}
.icb-shortcut-hint kbd {
  padding: 1px 5px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  border: 1px solid var(--border);
  font-family: inherit;
  font-size: 11px;
}
.icb-actions {
  display: flex;
  gap: 8px;
}

/* 速记卡片项样式 */
.card-chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.16), rgba(56, 189, 248, 0.16));
  color: #059669; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 700;
}
.note-card.memo-card {
  border-left: 3px solid #10b981;
}
.memo-content-view {
  margin: 10px 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--txt);
  white-space: pre-wrap;
  word-break: break-word;
}
.memo-content-view.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.memo-inline-editor {
  margin: 10px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.memo-edit-ops {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.memo-edit-btns {
  display: flex;
  gap: 6px;
}

@media (max-width: 860px) {
  .dirgrid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .head-ops { width: 100%; }
}
</style>
