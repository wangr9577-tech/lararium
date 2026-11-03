<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">项目文档</div>
        <div class="page-sub">
          把各项目的 md 直接挂进来读 —— 文件留在原处（git 管、agent 读的还是同一份），这里只是它的视图
        </div>
      </div>
      <div class="head-ops">
        <el-input
          v-model="q" placeholder="搜索所有已挂载的文档…" clearable style="width: 230px"
          @keyup.enter="runSearch" @clear="clearSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button :disabled="!q.trim()" @click="runSearch">搜索</el-button>
        <el-button :loading="discoverLoading" @click="openDiscover">
          <el-icon style="margin-right:4px"><Aim /></el-icon>发现项目
        </el-button>
        <el-button type="primary" @click="openAdd">
          <el-icon style="margin-right:4px"><Plus /></el-icon>挂载目录
        </el-button>
      </div>
    </div>

    <div class="grid2">
      <!-- 左：文档源 + 目录树 -->
      <aside class="side glass">
        <div class="side-head">
          <span>文档源</span>
          <el-button size="small" text :loading="loading" @click="reload">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
        <div v-if="sources.length" class="src-list">
          <button
            v-for="s in sources" :key="s.id" type="button" class="src-item"
            :class="{ on: s.id === activeSid }" @click="pickSource(s)"
          >
            <span class="src-icon"><el-icon><FolderOpened /></el-icon></span>
            <span class="src-main">
              <span class="src-name">{{ s.name }}</span>
              <span class="src-path">{{ s.root || '（工作区根目录）' }}</span>
            </span>
            <span class="src-meta">
              <span class="src-count">{{ s.md_count }}{{ s.md_count_truncated ? '+' : '' }} 篇</span>
              <span v-if="s.readonly" class="src-ro">只读</span>
              <span v-if="!s.exists" class="src-bad">目录不存在</span>
            </span>
          </button>
        </div>
        <div v-else-if="!loading" class="side-empty">
          还没有挂载任何项目<br>
          点右上角「发现项目」或「挂载目录」
        </div>

        <div v-if="activeSid" class="side-tree">
          <FileTree :sid="activeSid" @pick="(p) => openDoc(activeSid, p)" @open-dir="openDir" />
        </div>
      </aside>

      <!-- 右：当前目录 / 搜索结果 -->
      <main class="main glass" v-loading="listLoading || searching">
        <div class="bar">
          <div class="crumbs">
            <template v-if="activeSource">
              <button type="button" class="crumb" :class="{ on: !dir && !searchMode }" @click="openDir('')">
                {{ activeSource.name }}
              </button>
              <template v-for="(seg, i) in crumbSegs" :key="seg.path">
                <span class="crumb-sep">/</span>
                <button
                  type="button" class="crumb" :class="{ on: i === crumbSegs.length - 1 && !searchMode }"
                  @click="openDir(seg.path)"
                >{{ seg.name }}</button>
              </template>
            </template>
            <span v-else class="crumb on">未选择文档源</span>
          </div>
          <div class="bar-ops">
            <template v-if="activeSource">
              <span v-if="activeSource.readonly" class="ro-chip">只读源</span>
              <el-button size="small" text @click="openEdit(activeSource)">
                <el-icon style="margin-right:2px"><Setting /></el-icon>管理源
              </el-button>
            </template>
          </div>
        </div>

        <!-- 搜索态 -->
        <template v-if="searchMode">
          <div class="sec-t">
            搜索「{{ q }}」 · {{ hits.length }} 条命中
            <span class="sec-sub">（最多扫 {{ searchScanned }} 个文件{{ searchTruncated ? '，已截断，请缩小关键词' : '' }}）</span>
            <el-button size="small" text @click="clearSearch">退出搜索</el-button>
          </div>
          <div v-if="hits.length" class="rows">
            <button v-for="h in hits" :key="h.sid + h.path" type="button" class="row" @click="openDoc(h.sid, h.path)">
              <span class="row-main">
                <span class="row-title">{{ h.title || h.name }}</span>
                <span class="row-ex">{{ h.excerpt || h.path }}</span>
              </span>
              <span class="row-side">
                <span class="row-src">{{ h.source }}</span>
                <span class="row-time">{{ h.mtime.slice(5, 16) }}</span>
              </span>
            </button>
          </div>
          <div v-else class="empty">没有命中 —— 换个关键词试试</div>
        </template>

        <!-- 目录态 -->
        <template v-else-if="activeSource">
          <div v-if="tree && (tree.dirs.length || tree.files.length)" class="rows">
            <button
              v-for="d in tree.dirs" :key="'d' + d.path" type="button" class="row dir"
              @click="openDir(d.path)"
            >
              <span class="row-main">
                <span class="row-title"><el-icon class="ic"><Folder /></el-icon>{{ d.name }}</span>
              </span>
              <span class="row-side"><span class="row-time">目录</span></span>
            </button>
            <button
              v-for="f in tree.files" :key="'f' + f.path" type="button" class="row"
              @click="openDoc(activeSid, f.path)"
            >
              <span class="row-main">
                <span class="row-title">{{ f.title }}</span>
                <span class="row-ex">{{ f.name }}</span>
              </span>
              <span class="row-side">
                <span class="row-time">{{ f.mtime.slice(5, 16) }}</span>
                <span class="row-time">{{ fmtSize(f.size) }}</span>
              </span>
            </button>
          </div>
          <div v-else class="empty">
            这个目录下没有 md 文档<br>
            <span class="empty-sub">（只挂 md；.git / node_modules / data 等噪声目录默认不看）</span>
          </div>
        </template>

        <div v-else class="empty">左侧选一个文档源开始</div>
      </main>
    </div>

    <!-- 挂载 / 编辑源 -->
    <el-dialog v-model="formOpen" :title="formMode === 'add' ? '挂载项目目录' : '管理文档源'" width="560px">
      <el-form label-position="top">
        <el-form-item label="名称（列表里显示）">
          <el-input v-model="form.name" maxlength="40" placeholder="如：mathmodelagent" />
        </el-form-item>
        <el-form-item label="目录（相对工作区根，也接受绝对路径）">
          <el-input v-model="form.root" placeholder="如：ocean ／ kruskal/docs">
            <template #prefix><el-icon><FolderOpened /></el-icon></template>
          </el-input>
          <div class="form-hint">只能挂载 <code>{{ rootPath }}</code> 之内的目录；挂载只写配置，不动任何文件。</div>
        </el-form-item>
        <el-form-item label="只挂哪些（每行一条，留空 = 全部 md）">
          <el-input
            v-model="rulesText" type="textarea" :rows="4"
            placeholder="README.md&#10;docs/**&#10;AGENTS.md"
          />
          <div class="form-hint">
            支持精确文件名、目录前缀、glob。<code>.git</code> / <code>node_modules</code> / <code>data</code> / <code>tmp</code>
            等噪声目录默认跳过，规则里显式写出路径才会放行。
          </div>
        </el-form-item>
        <el-form-item>
          <el-switch v-model="form.readonly" active-text="只读（网页里禁止改这些文件）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="formMode === 'edit'" type="danger" plain @click="doRemove">移除这个源</el-button>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">
          {{ formMode === 'add' ? '挂载' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 发现候选 -->
    <el-dialog v-model="discoverOpen" title="发现项目目录" width="640px">
      <div class="form-hint" style="margin-bottom:10px">
        扫描 <code>{{ rootPath }}</code> 下含 md 的目录（只列出来，不自动挂载）。
      </div>
      <div v-loading="discoverLoading" class="cand-list">
        <button
          v-for="c in candidates" :key="c.root" type="button" class="cand"
          :disabled="c.added" @click="pickCandidate(c)"
        >
          <span class="cand-name">{{ c.name }}</span>
          <span class="cand-path">{{ c.root }}</span>
          <span class="cand-meta">
            {{ c.md_count }}{{ c.md_count_truncated ? '+' : '' }} 篇 md
            <span v-if="c.has_git" class="cand-git">git</span>
            <span v-if="c.added" class="cand-added">已挂载</span>
          </span>
        </button>
        <div v-if="!candidates.length && !discoverLoading" class="empty">没有发现候选目录</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Aim, Folder, FolderOpened, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'
import FileTree from '../components/FileTree.vue'
import { fmtSize, fsApi, type FsCandidate, type FsHit, type FsSource, type FsTree } from '../api/fs'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const listLoading = ref(false)
const searching = ref(false)
const saving = ref(false)
const rootPath = ref('')
const sources = ref<FsSource[]>([])
const activeSid = ref('')
const dir = ref('')
const tree = ref<FsTree | null>(null)
const q = ref('')
const hits = ref<FsHit[]>([])
const searchMode = ref(false)
const searchTruncated = ref(false)
const searchScanned = ref(0)

const activeSource = computed(() => sources.value.find((s) => s.id === activeSid.value) || null)
const crumbSegs = computed(() => {
  if (!dir.value) return [] as { name: string; path: string }[]
  const parts = dir.value.split('/')
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})

/* ---------------- 数据加载 ---------------- */

async function loadSources() {
  loading.value = true
  try {
    const r = await fsApi.sources()
    rootPath.value = r.root
    sources.value = r.items
    if (!sources.value.some((s) => s.id === activeSid.value)) {
      // 首次进入（或当前源已被移除）：按 URL 里的 sid/dir 恢复视图，否则用第一个源
      const fromQuery = typeof route.query.sid === 'string' ? route.query.sid : ''
      activeSid.value = sources.value.some((s) => s.id === fromQuery) ? fromQuery : (sources.value[0]?.id || '')
      dir.value = typeof route.query.dir === 'string' ? route.query.dir : ''
    }
    await loadTree()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '文档源加载失败')
  } finally {
    loading.value = false
  }
}

async function loadTree() {
  if (!activeSid.value) { tree.value = null; return }
  listLoading.value = true
  try {
    tree.value = await fsApi.tree(activeSid.value, dir.value)
  } catch (e: any) {
    tree.value = null
    ElMessage.error(e?.response?.data?.detail || '目录读取失败')
  } finally {
    listLoading.value = false
  }
}

function syncQuery() {
  router.replace({ path: '/projects', query: { sid: activeSid.value, dir: dir.value || undefined } })
}

function pickSource(s: FsSource) {
  activeSid.value = s.id
  dir.value = ''
  searchMode.value = false
  syncQuery()
  loadTree()
}

function openDir(path: string) {
  dir.value = path
  searchMode.value = false
  syncQuery()
  loadTree()
}

function openDoc(sid: string, path: string) {
  router.push({ path: '/projects/doc', query: { sid, path } })
}

async function reload() {
  await loadSources()
  if (searchMode.value && q.value.trim()) await runSearch()
}

/* ---------------- 搜索 ---------------- */

async function runSearch() {
  const kw = q.value.trim()
  if (!kw) { clearSearch(); return }
  searchMode.value = true
  searching.value = true
  try {
    const r = await fsApi.search(kw)
    hits.value = r.items
    searchTruncated.value = r.truncated
    searchScanned.value = r.scanned
  } catch (e: any) {
    hits.value = []
    ElMessage.error(e?.response?.data?.detail || '搜索失败')
  } finally {
    searching.value = false
  }
}

function clearSearch() {
  q.value = ''
  searchMode.value = false
  hits.value = []
}

/* ---------------- 源管理 ---------------- */

const formOpen = ref(false)
const formMode = ref<'add' | 'edit'>('add')
const form = reactive({ id: '', name: '', root: '', include: [] as string[], readonly: false })
const rulesText = computed({
  get: () => form.include.join('\n'),
  set: (v: string) => { form.include = v.split('\n').map((x) => x.trim()).filter(Boolean) },
})

function openAdd() {
  formMode.value = 'add'
  form.id = ''
  form.name = ''
  form.root = ''
  form.include = []
  form.readonly = false
  formOpen.value = true
}

function openEdit(s: FsSource) {
  formMode.value = 'edit'
  form.id = s.id
  form.name = s.name
  form.root = s.root
  form.include = [...s.include]
  form.readonly = s.readonly
  formOpen.value = true
}

async function submitForm() {
  if (!form.root.trim()) { ElMessage.warning('请填写目录'); return }
  saving.value = true
  try {
    const body = { name: form.name.trim(), root: form.root.trim(), include: form.include, readonly: form.readonly }
    const r = formMode.value === 'add'
      ? await fsApi.addSource(body)
      : await fsApi.updateSource(form.id, body)
    ElMessage.success(formMode.value === 'add' ? `已挂载「${r.name}」` : '已保存')
    formOpen.value = false
    activeSid.value = r.id
    dir.value = ''
    searchMode.value = false
    await loadSources()
    syncQuery()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    saving.value = false
  }
}

async function doRemove() {
  const s = sources.value.find((x) => x.id === form.id)
  if (!s) return
  try {
    await ElMessageBox.confirm(
      `移除文档源「${s.name}」？\n\n只会删掉这条挂载配置，${s.root || '工作区根目录'} 里的文件一个都不会动，agent 照常读。`,
      '移除文档源', { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch { return }  // 用户取消
  try {
    await fsApi.removeSource(s.id)
    ElMessage.success('已移除（文件未做任何改动）')
    formOpen.value = false
    if (activeSid.value === s.id) activeSid.value = ''
    await loadSources()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除失败')
  }
}

/* ---------------- 发现候选 ---------------- */

const discoverOpen = ref(false)
const discoverLoading = ref(false)
const candidates = ref<FsCandidate[]>([])

async function openDiscover() {
  discoverOpen.value = true
  if (candidates.value.length) return
  discoverLoading.value = true
  try {
    const r = await fsApi.discover()
    candidates.value = r.items
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '扫描失败')
  } finally {
    discoverLoading.value = false
  }
}

function pickCandidate(c: FsCandidate) {
  formMode.value = 'add'
  form.id = ''
  form.name = c.name
  form.root = c.root
  form.include = []
  form.readonly = false
  discoverOpen.value = false
  formOpen.value = true
}

onMounted(loadSources)
</script>

<style scoped>
.grid2 { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }

.side { padding: 12px; max-height: calc(100vh - 190px); overflow: auto; }
.side-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; font-weight: 700; color: var(--txt2); padding: 0 4px 8px;
}
.src-list { display: flex; flex-direction: column; gap: 6px; }
.src-item {
  display: flex; align-items: center; gap: 9px; width: 100%; text-align: left;
  padding: 8px 10px; border-radius: 12px; cursor: pointer;
  border: 1px solid transparent; background: rgba(148, 163, 184, 0.09);
  color: inherit; font: inherit;
}
.src-item:hover { background: rgba(139, 92, 246, 0.12); }
.src-item.on { border-color: var(--acc2); background: rgba(139, 92, 246, 0.18); }
.src-icon { color: var(--acc2); display: flex; }
.src-main { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.src-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src-path { font-size: 11px; color: var(--txt2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex: none; }
.src-count { font-size: 11px; color: var(--txt3); }
.src-ro, .src-bad {
  font-size: 10px; padding: 0 5px; border-radius: 6px;
  background: rgba(245, 158, 11, 0.18); color: #b45309;
}
.src-bad { background: rgba(239, 68, 68, 0.16); color: #dc2626; }
html.theme-dark .src-ro { color: #fbbf24; }
html.theme-dark .src-bad { color: #fca5a5; }
.side-empty { font-size: 12px; color: var(--txt2); padding: 8px; line-height: 1.7; }
.side-tree { margin-top: 8px; border-top: 1px dashed rgba(148, 163, 184, 0.35); padding-top: 6px; }

.main { padding: 14px 16px 18px; min-height: 320px; }
.bar { display: flex; align-items: center; gap: 8px; padding-bottom: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); }
.crumbs { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; min-width: 0; }
.crumb {
  border: none; background: none; cursor: pointer; font: inherit; font-size: 13px;
  color: var(--txt2); padding: 2px 6px; border-radius: 8px;
}
.crumb:hover { background: rgba(139, 92, 246, 0.12); }
.crumb.on { color: inherit; font-weight: 700; }
.crumb-sep { color: var(--txt2); opacity: 0.6; }
.bar-ops { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.ro-chip {
  font-size: 11px; padding: 1px 7px; border-radius: 8px;
  background: rgba(245, 158, 11, 0.18); color: #b45309;
}
html.theme-dark .ro-chip { color: #fbbf24; }

.sec-t { display: flex; align-items: center; gap: 8px; padding: 10px 2px 6px; font-size: 13px; font-weight: 600; }
.sec-sub { font-weight: 400; color: var(--txt2); font-size: 12px; }
.rows { display: flex; flex-direction: column; }
.row {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  padding: 9px 10px; border: none; border-radius: 10px; background: none;
  color: inherit; font: inherit; cursor: pointer;
}
.row + .row { border-top: 1px solid rgba(148, 163, 184, 0.12); }
.row:hover { background: rgba(139, 92, 246, 0.1); }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.row-title {
  font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row.dir .row-title { color: var(--txt3); }
.ic { color: #f59e0b; }
.row-ex {
  font-size: 12px; color: var(--txt2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row-side { display: flex; align-items: center; gap: 10px; flex: none; }
.row-time { font-size: 11px; color: var(--txt2); white-space: nowrap; }
.row-src {
  font-size: 11px; color: var(--txt3); padding: 1px 6px; border-radius: 7px;
  background: rgba(148, 163, 184, 0.14);
}
.empty { padding: 40px 10px; text-align: center; color: var(--txt2); font-size: 13px; line-height: 1.9; }
.empty-sub { font-size: 12px; opacity: 0.85; }

.form-hint { font-size: 12px; color: var(--txt2); line-height: 1.7; margin-top: 5px; }
.form-hint code, .src-path code { font-size: 11px; }
.cand-list { display: flex; flex-direction: column; gap: 6px; max-height: 46vh; overflow: auto; }
.cand {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  padding: 9px 11px; border-radius: 12px; cursor: pointer; font: inherit; color: inherit;
  border: 1px solid rgba(148, 163, 184, 0.28); background: rgba(148, 163, 184, 0.07);
}
.cand:hover:not(:disabled) { border-color: var(--acc2); background: rgba(139, 92, 246, 0.12); }
.cand:disabled { opacity: 0.55; cursor: default; }
.cand-name { font-weight: 600; font-size: 13px; }
.cand-path { font-size: 11px; color: var(--txt2); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cand-meta { font-size: 11px; color: var(--txt3); display: flex; align-items: center; gap: 6px; flex: none; }
.cand-git, .cand-added {
  font-size: 10px; padding: 0 6px; border-radius: 6px;
  background: rgba(56, 189, 248, 0.18); color: #0369a1;
}
.cand-added { background: rgba(34, 197, 94, 0.18); color: #15803d; }
html.theme-dark .cand-git { color: #7dd3fc; }
html.theme-dark .cand-added { color: #86efac; }
</style>