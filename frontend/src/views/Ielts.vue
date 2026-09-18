<template>
  <div class="page">
    <div class="head">
      <el-button text @click="$router.push('/notes')"><el-icon><ArrowLeft /></el-icon>返回笔记</el-button>
      <div class="ht">
        <div class="page-title">雅思学习</div>
        <div class="page-sub">点卡片进入子页；也可以自己新建 markdown 子页</div>
      </div>
      <el-button type="primary" class="new-btn" @click="newDoc">
        <el-icon style="margin-right: 4px"><Plus /></el-icon>新建子页
      </el-button>
    </div>

    <!-- 全科资料包 -->
    <div class="kit glass">
      <span class="kit-tag">全科资料</span>
      <a class="kit-link" href="https://github.com/mcxiaoxiao/openIELTS" target="_blank" rel="noopener">
        openIELTS · 0 成本全套备考资料与计划（课程 / 刷题网站 / 作文批改 / AI 口语串题 prompt / 评分表）
      </a>
      <span class="kit-hint">页面里的「剑桥雅思」= 雅思官方历年真题集</span>
      <span class="kit-arrow">↗</span>
    </div>

    <!-- 内置卡片（雅思入门置顶） -->
    <div class="cards">
      <div v-for="b in builtin" :key="b.to" class="card glass" @click="$router.push(b.to)">
        <div class="b-mark" :style="{ background: b.color }" />
        <div class="b-title">{{ b.title }}</div>
        <div class="b-desc">{{ b.desc }}</div>
        <div class="b-go">进入 ›</div>
      </div>
    </div>

    <!-- 我的子页 -->
    <div class="grp">
      <span class="grp-t">我的子页</span>
      <span class="grp-n">{{ pages.length }} 个</span>
      <div class="fchips">
        <button class="fchip" :class="{ on: selFolder === null }" @click="pick(null)">全部</button>
        <button class="fchip" :class="{ on: selFolder === '' }" @click="pick('')">未分类 <i>{{ uncatCnt }}</i></button>
        <button
          v-for="f in dirs" :key="dirPath(f)" class="fchip"
          :class="{ on: selFolder === dirPath(f) }" @click="pick(dirPath(f))"
        >{{ dirLabel(f) }} <i>{{ f.count }}</i></button>
        <button class="fchip add" @click="quickCreate">＋ 新建目录</button>
        <button class="fchip add" @click="mgrOpen = true">管理</button>
      </div>
    </div>
    <div v-if="pages.length" class="cards sub">
      <div v-for="n in pages" :key="n.id" class="card glass sub-card" @click="$router.push(`/ielts/doc/${n.id}`)">
        <div class="nc-top">
          <span class="chip">子页</span>
          <span class="nc-title">{{ n.title }}</span>
          <span class="nc-time">{{ shortTime(n.updated) }}</span>
        </div>
        <div class="nc-sum">{{ n.summary || '（无摘要）' }}</div>
        <div class="nc-ops">
          <el-button text size="small" @click.stop="rename(n)">改名</el-button>
          <el-button text size="small" @click.stop="openMove(n)">目录</el-button>
        </div>
      </div>
    </div>
    <div v-else class="empty glass">
      {{ selFolder === null
        ? '还没有 markdown 子页 —— 点右上角「新建子页」，把口语话题库、错题本之类的内容放进来'
        : '这个目录还没有子页 —— 点右上角「新建子页」，新建时把目录选到这里' }}
    </div>

    <FolderDialog v-model="mgrOpen" module="ielts" @changed="refreshDirs" />

    <!-- 移动目录 -->
    <el-dialog v-model="moveOpen" title="移动子页目录" width="400px">
      <el-select v-model="moveFolder" style="width: 100%">
        <el-option label="未分类" value="" />
        <el-option v-for="f in dirs" :key="dirPath(f)" :label="dirLabel(f)" :value="dirPath(f)" />
      </el-select>
      <p class="move-tip">没有目标目录？可先点右上角「新建目录」或在「管理」里创建。</p>
      <template #footer>
        <el-button @click="moveOpen = false">取消</el-button>
        <el-button type="primary" :loading="moveBusy" @click="saveMove">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus } from '@element-plus/icons-vue'
import { http } from '../api/client'
import FolderDialog from '../components/FolderDialog.vue'

interface PageNote { id: string; title: string; type: string; module: string; folder: string; tags: string[]; summary: string; created: string; updated: string }
/** 目录：path=自身全路径（顶层=名字），parent=父目录全路径（''=顶层）；兼容期后端未返回 path 时回落到 name */
interface Dir { name: string; path?: string; parent?: string; count: number }

const router = useRouter()

const builtin = [
  { to: '/ielts/intro', color: '#38bdf8', title: '雅思入门', desc: '雅思是什么 / 怎么考 / 分数怎么算 / 如何报名 —— 先花几分钟读懂规则' },
  { to: '/ielts/timeline', color: '#f472b6', title: '时间轴', desc: '听力 · 口语 · 阅读 · 写作 四栏打卡，学完一项勾一项，附各科资料直达' },
  { to: '/ielts/plan', color: '#a78bfa', title: '周计划', desc: '每天 1 小时（含单词）按周打卡，可翻上周 / 下周看安排与进度' },
]

const pages = ref<PageNote[]>([])
/** 子页目录筛选：null=全部；''=未分类；path=目录全路径（按子树筛选，含其子目录） */
const selFolder = ref<string | null>(null)
const dirs = ref<Dir[]>([])
const totalPages = ref(0)
const mgrOpen = ref(false)

/** 未分类 = 总数 − 各顶层目录子树计数之和（子目录计数已含在顶层内，避免重复计） */
const uncatCnt = computed(() => {
  const sum = dirs.value.filter((f) => !(f.parent || '')).reduce((a, b) => a + b.count, 0)
  return Math.max(0, totalPages.value - sum)
})

/** 目录全路径（兼容：后端尚未返回 path 时回落到 name，即原顶层行为） */
function dirPath(f: Dir): string {
  return f.path || f.name
}
/** 层级展示名：顶层=自身名；子级=「父路径 / 名」 */
function dirLabel(f: Dir): string {
  return f.parent ? `${f.parent} / ${f.name}` : f.name
}

function shortTime(t: string) {
  return t ? t.slice(5, 16) : ''
}

/** 新建 markdown 子页：先弹命名（可留空 = 未命名，之后在卡片改名） */
async function newDoc() {
  let title = ''
  try {
    const r = await ElMessageBox.prompt('子页标题（可留空，之后在主页改名）', '新建子页', {
      confirmButtonText: '创建', cancelButtonText: '取消', inputValue: '',
    })
    title = (r.value || '').trim()
  } catch { return }
  router.push(title ? `/ielts/doc/new?title=${encodeURIComponent(title)}` : '/ielts/doc/new')
}

async function load() {
  try {
    const params = new URLSearchParams()
    params.set('module', 'ielts')
    if (selFolder.value !== null) params.set('folder', selFolder.value)
    const r = await http.get<{ items: PageNote[] }>(`/notes?${params.toString()}`)
    pages.value = r.items
  } catch (e: any) {
    if (e?.response?.status !== 401 && e?.response?.status !== 423) {
      ElMessage.error(e?.response?.data?.detail || '子页加载失败')
    }
  }
}

function pick(f: string | null) {
  selFolder.value = f
  load()
}

/** 刷新目录 chips（含被删目录的选中态复位） */
async function refreshDirs() {
  try {
    const [fd, all] = await Promise.all([
      http.get<{ items: Dir[] }>('/notes/folders?module=ielts'),
      http.get<{ items: PageNote[] }>('/notes?module=ielts'),
    ])
    dirs.value = fd.items
    totalPages.value = all.items.length
    if (selFolder.value !== null && selFolder.value !== '' && !fd.items.some((x) => dirPath(x) === selFolder.value)) {
      selFolder.value = null
    }
    load()
  } catch { /* ignore */ }
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
    await http.post('/notes/folders', { module: 'ielts', name })
    ElMessage.success('已创建')
    refreshDirs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

/* ---------------- 子页卡：改名 / 移动目录 ---------------- */

const moveOpen = ref(false)
const moveBusy = ref(false)
const moveId = ref('')
const moveFolder = ref('')

async function saveDocFull(id: string, patch: Partial<{ title: string; folder: string }>) {
  const n = await http.get<any>(`/notes/${id}`)
  const body = {
    title: patch.title ?? n.title,
    type: n.type ?? 'note',
    module: n.module ?? 'ielts',
    folder: patch.folder !== undefined ? patch.folder : (n.folder ?? ''),
    fmt: n.fmt ?? 'md',
    tags: n.tags ?? [],
    summary: n.summary ?? '',
    content: n.content,
  }
  return http.put(`/notes/${id}`, body)
}

async function rename(n: PageNote) {
  let next = ''
  try {
    const r = await ElMessageBox.prompt('子页标题：', '重命名', {
      confirmButtonText: '确定', cancelButtonText: '取消', inputValue: n.title, inputPattern: /\S+/,
      inputErrorMessage: '标题不能为空',
    })
    next = (r.value || '').trim()
  } catch { return }
  if (!next || next === n.title) return
  try {
    await saveDocFull(n.id, { title: next })
    ElMessage.success('已改名')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '改名失败')
  }
}

function openMove(n: PageNote) {
  moveId.value = n.id
  moveFolder.value = n.folder || ''
  moveOpen.value = true
}

async function saveMove() {
  if (!moveId.value) return
  moveBusy.value = true
  try {
    await saveDocFull(moveId.value, { folder: moveFolder.value })
    ElMessage.success('已移动')
    moveOpen.value = false
    refreshDirs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移动失败')
  } finally {
    moveBusy.value = false
  }
}

onMounted(() => {
  refreshDirs()
})
</script>

<style scoped>
/* 模块页宽屏铺开（全局 .page 默认限宽 1200px） */
.page { max-width: 1600px; }
.head { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; flex-wrap: wrap; }
.ht { min-width: 0; }
.new-btn { margin-left: auto; }

.kit {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; margin-bottom: 18px; border-radius: 14px;
  background: rgba(56, 189, 248, 0.06); border: 1px solid rgba(56, 189, 248, 0.18);
}
.kit-tag {
  flex: none; font-size: 12px; font-weight: 700; color: #0ea5e9;
  border: 1px solid rgba(56, 189, 248, 0.4); border-radius: 999px; padding: 2px 10px;
}
.kit-link {
  color: var(--acc2); font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kit-hint { color: var(--txt3); font-size: 12px; flex: none; }
html.theme-dark .kit-hint { color: var(--txt2); }
.kit-arrow { margin-left: auto; color: var(--txt3); font-size: 13px; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.card {
  position: relative; overflow: hidden; cursor: pointer;
  padding: 16px 18px 14px; border-radius: 14px;
  transition: transform .15s, box-shadow .15s;
}
.card:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.18); }
.b-mark { position: absolute; inset: 0 0 auto; height: 4px; }
.b-title { font-size: 16.5px; font-weight: 800; margin: 4px 0 6px; }
.b-desc { font-size: 12.5px; line-height: 1.7; color: var(--txt3); min-height: 42px; }
html.theme-dark .b-desc { color: var(--txt2); }
.b-go { margin-top: 10px; font-size: 12.5px; color: var(--acc2); font-weight: 600; }

.grp { display: flex; align-items: baseline; gap: 8px; margin: 20px 0 10px; flex-wrap: wrap; }
.grp-t { font-size: 15px; font-weight: 800; }
.grp-n { font-size: 11.5px; color: var(--txt3); }
html.theme-dark .grp-n { color: var(--txt2); }
.fchips { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
.fchip {
  border: 1px solid rgba(148, 163, 184, 0.25); background: transparent; cursor: pointer;
  border-radius: 999px; padding: 3px 11px; font-size: 12px; color: var(--txt1);
  font-family: inherit; transition: all .12s;
}
html.theme-dark .fchip { color: #cbd5e1; }
.fchip:hover { border-color: var(--acc3); color: var(--acc2); }
.fchip.on { background: var(--acc-grad); color: #fff; font-weight: 600; border-color: transparent; }
.fchip i { font-style: normal; opacity: 0.65; font-size: 10.5px; margin-left: 2px; }
.fchip.add { border-style: dashed; color: var(--txt3); }
html.theme-dark .fchip.add { color: var(--txt2); }
.fchip.add:hover { color: var(--acc2); }

.cards.sub { margin-bottom: 6px; }
.sub-card { border: 1px solid rgba(148, 163, 184, 0.14); }
.nc-top { display: flex; align-items: center; gap: 8px; }
.chip {
  flex: none; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: rgba(167, 139, 250, 0.14); color: var(--acc2);
}
.nc-title { font-size: 15px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-time { margin-left: auto; font-size: 11px; color: var(--txt2); flex: none; font-variant-numeric: tabular-nums; }

.nc-ops { display: flex; gap: 2px; margin-top: 8px; }
.move-tip { color: var(--txt3); font-size: 12px; margin: 10px 0 0; }
html.theme-dark .move-tip { color: var(--txt2); }
.nc-sum {
  margin-top: 8px; font-size: 12.5px; color: var(--txt3); line-height: 1.7;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
html.theme-dark 
.nc-ops { display: flex; gap: 2px; margin-top: 8px; }
.move-tip { color: var(--txt3); font-size: 12px; margin: 10px 0 0; }
html.theme-dark .move-tip { color: var(--txt2); }
.nc-sum { color: var(--txt2); }

.empty {
  color: var(--txt2); font-size: 13px; line-height: 1.8;
  padding: 26px 20px; border-radius: 14px; border: 1px dashed rgba(148, 163, 184, 0.3);
}
</style>
