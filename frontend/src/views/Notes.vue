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

    <div class="layout">
      <!-- 目录栏 -->
      <aside class="dir glass">
        <div class="dir-title">
          目录
          <el-tooltip content="新建目录" placement="top">
            <el-button text circle size="small" @click="quickCreate"><el-icon><FolderAdd /></el-icon></el-button>
          </el-tooltip>
          <el-tooltip content="管理目录（改名/删除）" placement="top">
            <el-button text circle size="small" @click="mgrOpen = true"><el-icon><Setting /></el-icon></el-button>
          </el-tooltip>
        </div>
        <div class="dir-body">
          <button class="dir-row" :class="{ on: selFolder === null }" @click="pickDir(null)">
            <span class="d-name">全部</span><span class="d-cnt">{{ totalCnt }}</span>
          </button>
          <button class="dir-row" :class="{ on: selFolder === '' }" @click="pickDir('')">
            <span class="d-name">未分类</span><span class="d-cnt">{{ uncatCnt }}</span>
          </button>
          <button
            v-for="row in dirRows" :key="dirPath(row.f)" class="dir-row"
            :class="{ on: selFolder === dirPath(row.f) }"
            :style="{ paddingLeft: 9 + row.depth * 14 + 'px' }"
            @click="pickDir(dirPath(row.f))"
          >
            <span v-if="row.hasKids" class="d-caret" title="展开/收起子目录" @click.stop="toggleDir(dirPath(row.f))">{{ collapsed[dirPath(row.f)] ? '▸' : '▾' }}</span>
            <span v-else class="d-caret d-caret-ph" />
            <span class="d-name" :title="dirLabel(row.f)">{{ row.f.name }}</span>
            <span class="d-cnt">{{ row.f.count }}</span>
            <span class="d-add" title="在「{{ dirLabel(row.f) }}」下新建子目录" @click.stop="addSub(row.f)"><el-icon><FolderAdd /></el-icon></span>
          </button>
        </div>
        <div v-if="!dirs.length" class="dir-hint">还没有目录<br>点上面 + 新建，把笔记分门别类</div>
      </aside>

      <!-- 主列 -->
      <div class="col">
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
          <div v-if="tags.length" class="tags">
            <el-tag
              v-for="t in tags" :key="t.name" size="small" effect="plain" class="tag"
              :type="tag === t.name ? 'primary' : 'info'"
              @click="tag = tag === t.name ? '' : t.name"
            >#{{ t.name }} {{ t.count }}</el-tag>
          </div>
          <span class="cnt">{{ realNotes }} 篇</span>
        </div>

        <!-- 列表（含雅思学习虚拟卡，归类为学习笔记） -->
        <div v-if="items.length" class="list">
          <div
            v-for="n in items" :key="n.id" class="note-card glass"
            :class="{ 'v-ielts': n.id === IELTS_ID }" @click="openNote(n)"
          >
            <div class="nc-top">
              <span class="chip">{{ typeLabel(n.type) }}</span>
              <span v-if="n.ppt" class="ppt-chip" :title="'PPT 笔记：' + n.ppt">PPT</span>
              <span v-else-if="n.pdf" class="pdf-chip" :title="'PDF 笔记：' + n.pdf">PDF</span>
              <span v-else-if="n.fmt === 'ink'" class="ink-chip" title="白板手写笔记">白板</span>
              <span v-if="n.id === IELTS_ID" class="mini-logo">雅</span>
              <span class="nc-title">{{ n.title }}</span>
              <span class="nc-time">{{ n.updated?.slice(5, 16) }}</span>
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
        </div>

        <EmptyState v-else icon="Notebook" :title="emptyTitle" :desc="emptyDesc"
          :features="['博客 / 学习笔记 / 项目经历 三种分类', '工具栏一键插入 Markdown（加粗/标题/公式/表格…）', '实时预览 + KaTeX 公式渲染']">
          <template #default>
            <el-button type="primary" round style="margin-top:18px" @click="newNote">写下第一篇</el-button>
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

    <FolderDialog v-model="mgrOpen" module="" @changed="refreshDir" />

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
        <el-button @click="metaOpen = false">取消</el-button>
        <el-button type="primary" :loading="metaSaving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>
    <TrashDialog v-model="trashOpen" @restored="() => { fetchAll(); refreshDir() }" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, FolderAdd, Setting, Upload } from '@element-plus/icons-vue'
import { api, http } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import FolderDialog from '../components/FolderDialog.vue'
import TrashDialog from '../components/TrashDialog.vue'

const trashOpen = ref(false)

interface Note { id: string; title: string; type: string; fmt?: string; ppt?: string; pdf?: string; tags: string[]; summary: string; created: string; updated: string }
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

const router = useRouter()
const q = ref('')
const type = ref('')
const tag = ref('')
const items = ref<Note[]>([])
const tags = ref<{ name: string; count: number }[]>([])
/** 目录筛选：null=全部；''=未分类；path=指定目录全路径（按子树筛选，含其子目录） */
const selFolder = ref<string | null>(null)
const dirs = ref<Dir[]>([])
const totalCnt = ref(0)
const mgrOpen = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

const realNotes = computed(() => items.value.filter((i) => i.id !== IELTS_ID).length)
/** 未分类 = 总数 − 各顶层目录子树计数之和（子目录计数已含在顶层内，避免重复计） */
const uncatCnt = computed(() => {
  const sum = dirs.value.filter((f) => !(f.parent || '')).reduce((a, b) => a + b.count, 0)
  return Math.max(0, totalCnt.value - sum)
})

/* ---------------- 目录树（子文件夹：path=全路径，parent=父目录全路径） ---------------- */

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
/** 子目录展开态：默认全部展开，仅显式收起为 false */
const collapsed = ref<Record<string, boolean>>({})
function toggleDir(p: string) {
  collapsed.value = { ...collapsed.value, [p]: !collapsed.value[p] }
}
interface DirRow { f: Dir; depth: number; hasKids: boolean }
/** 侧边栏目录行（按树序拍平：父先子后；收起的节点隐藏其子级） */
const dirRows = computed<DirRow[]>(() => {
  const byParent = groupByParent(dirs.value)
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

const emptyTitle = computed(() => (selFolder.value === null ? '还没有任何笔记' : '这个目录还没有子页'))
const emptyDesc = computed(() => (selFolder.value === null
  ? '点右上角「新建笔记」，用工具栏式编辑器直接开写 —— 标题/分类/标签/正文全部网页可改，正文加密存储。'
  : '点右上角「新建笔记」，创建后会自动归入当前目录，就能在这里看到它。'))

function typeLabel(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

/** 雅思虚拟卡是否命中当前筛选（仅「全部」视图展示） */
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

function openNote(n: Note) {
  router.push(n.id === IELTS_ID ? '/ielts' : `/notes/${n.id}`)
}

/** 新建笔记：弹出命名窗口（可留空 = 未命名，之后在列表改名）。
    功能A：目录视图中新建 → 自动归入当前目录（?folder= 直接带入） */
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
  if (selFolder.value && selFolder.value !== '') params.set('folder', selFolder.value)
  const qs = params.toString()
  router.push(qs ? `/notes/new?${qs}` : '/notes/new')
}

/* ---------------- 卡片：改名 / 信息 ---------------- */

const metaOpen = ref(false)
const metaSaving = ref(false)
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
        fd.append('folder', selFolder.value === null || selFolder.value === '' ? '' : selFolder.value)
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

function pickDir(f: string | null) {
  selFolder.value = f
  fetchAll()
}

async function fetchAll() {
  try {
    const params = new URLSearchParams()
    if (type.value) params.set('type', type.value)
    if (tag.value) params.set('tag', tag.value)
    if (q.value.trim()) params.set('q', q.value.trim())
    if (selFolder.value !== null) params.set('folder', selFolder.value)
    const r = await http.get<{ items: Note[] }>(`/notes?${params.toString()}`)
    const arr = r.items
    if (ieltsMatch()) arr.unshift(VIRTUAL_IELTS)
    items.value = arr
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '笔记加载失败')
    }
    items.value = []
  }
}

/** 刷新目录栏（总数 + 目录计数），并处理被删目录的选中态 */
async function refreshDir() {
  try {
    const [fd, all] = await Promise.all([
      http.get<{ items: Dir[] }>('/notes/folders?module='),
      http.get<{ items: Note[] }>('/notes?module='),
    ])
    dirs.value = fd.items
    totalCnt.value = all.items.length
    if (selFolder.value !== null && selFolder.value !== '' && !fd.items.some((x) => dirPath(x) === selFolder.value)) {
      selFolder.value = null
    }
    fetchAll()
  } catch { /* 401/423 忽略 */ }
}

async function quickCreate() {
  let name = ''
  try {
    const r = await ElMessageBox.prompt('新目录名：', '新建目录', {
      confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    name = (r.value || '').trim()
  } catch { return }
  try {
    await http.post('/notes/folders', { module: '', name })
    ElMessage.success('已创建')
    refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

/** 新建子目录：parent=目标目录全路径（顶层目录传 ''） */
async function addSub(f: Dir) {
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
    await http.post('/notes/folders', { module: '', name, parent: p })
    ElMessage.success('已创建')
    collapsed.value = { ...collapsed.value, [p]: false } // 确保父目录展开
    refreshDir()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

function scheduleFetch() {
  clearTimeout(timer)
  timer = setTimeout(fetchAll, 250)
}

watch([type, tag], fetchAll)
watch(q, scheduleFetch)

onMounted(async () => {
  fetchAll()
  refreshDir()
  // 页面级拖拽导入（.pptx / .pdf，支持多文件）
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('dragleave', onDragLeave)
  window.addEventListener('drop', onDrop)
  try {
    const r = await http.get<{ tags: { name: string; count: number }[] }>('/notes/tags')
    tags.value = r.tags
  } catch { /* ignore */ }
})

onBeforeUnmount(() => {
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('dragleave', onDragLeave)
  window.removeEventListener('drop', onDrop)
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; }
.head-ops { display: flex; align-items: center; gap: 10px; }
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
.layout { display: flex; gap: 14px; align-items: flex-start; }
.col { flex: 1; min-width: 0; }

/* 目录栏 */
.dir { width: 190px; flex: none; padding: 12px 10px; display: flex; flex-direction: column; max-height: 70vh; }
.dir-title { display: flex; align-items: center; gap: 2px; font-size: 14px; font-weight: 800; padding: 2px 6px 8px; }
.dir-title .el-button { margin-left: auto; }
.dir-title .el-button + .el-button { margin-left: 0; }
.dir-body { display: grid; gap: 2px; overflow-y: auto; }
.dir-row {
  display: flex; align-items: center; gap: 6px; width: 100%;
  border: none; cursor: pointer; background: transparent; border-radius: 9px;
  padding: 7px 9px; font-size: 13px; color: var(--txt1); font-family: inherit; text-align: left;
}
html.theme-dark .dir-row { color: #cbd5e1; }
.dir-row:hover { background: rgba(167, 139, 250, 0.1); }
.dir-row.on { background: var(--acc-grad); color: #fff; font-weight: 600; }
.d-caret { flex: none; width: 12px; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; color: var(--txt3); cursor: pointer; }
html.theme-dark .d-caret { color: #94a3b8; }
.d-caret-ph { cursor: default; }
.d-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.d-cnt { flex: none; font-size: 10.5px; color: var(--txt3); background: rgba(148, 163, 184, 0.18); border-radius: 999px; padding: 0 6px; }
.d-add { flex: none; display: inline-flex; align-items: center; font-size: 13px; color: var(--txt3); opacity: 0; transition: opacity .12s; }
.dir-row:hover .d-add, .dir-row:focus .d-add { opacity: 1; }
.d-add:hover { color: var(--acc2); }
html.theme-dark .d-add { color: #94a3b8; }
.dir-row.on .d-cnt { color: #fff; background: rgba(255, 255, 255, 0.25); }
html.theme-dark .d-cnt { color: var(--txt2); }
.dir-hint { color: var(--txt2); font-size: 11.5px; line-height: 1.7; padding: 8px 6px 2px; }

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

.list { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.note-card { padding: 16px 18px; cursor: pointer; transition: transform .15s, box-shadow .15s; }
.note-card:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.18); }
.nc-top { display: flex; align-items: center; gap: 8px; }
.nc-title { font-size: 15.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-time { margin-left: auto; font-size: 11px; color: var(--txt2); flex: none; font-variant-numeric: tabular-nums; }
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

@media (max-width: 860px) {
  .layout { flex-direction: column; }
  .dir { width: 100%; max-height: none; }
  .dir-body { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
}
</style>
