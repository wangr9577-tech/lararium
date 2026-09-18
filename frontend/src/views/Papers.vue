<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">论文阅读</div>
        <div class="page-sub">论文库 · 分组/子分组 · 荧光笔标注 · 划词翻译 · 批量导入</div>
      </div>
      <el-button type="primary" @click="uploadOpen = true">
        <el-icon style="margin-right:4px"><Upload /></el-icon>导入论文（可多篇）
      </el-button>
      <el-button @click="trashOpen = true">回收站</el-button>
    </div>

    <!-- 上传弹窗（多文件） -->
    <el-dialog v-model="uploadOpen" title="导入论文 PDF（可一次多篇）" width="520px">
      <el-form label-position="top">
        <el-form-item label="选择 PDF（≤30MB/篇，最多 30 篇）">
          <el-upload drag multiple :auto-upload="false" accept=".pdf,application/pdf"
            :on-change="onPick" :file-list="[]" class="up">
            <div style="padding: 10px">拖拽或点击选择多篇 PDF</div>
          </el-upload>
        </el-form-item>
        <p v-if="pending.length" class="cnt">已选 {{ pending.length }} 篇：{{ pending.map((f) => f.name).join('、') }}</p>
        <el-form-item label="分类">
          <el-select v-model="upCategory" filterable allow-create default-first-option clearable placeholder="选择或输入新分类" style="width:100%" @change="upSub = ''">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="subOptions.length" label="子分组（可选）">
          <el-select v-model="upSub" filterable allow-create default-first-option clearable placeholder="选择或输入子分组" style="width:100%">
            <el-option v-for="s in subOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签（逗号分隔，可空）"><el-input v-model="upTags" placeholder="如：ABM, 社会模拟" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadOpen = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!pending.length" @click="doUpload">
          上传 {{ pending.length || '' }} 篇
        </el-button>
      </template>
    </el-dialog>

    <!-- 状态 + 分类筛选 -->
    <div class="filters glass">
      <button v-for="f in statusFilters" :key="f.value" class="ttab"
        :class="{ on: status === f.value }" @click="status = f.value">{{ f.label }}</button>
      <span class="sep" />
      <button class="ttab" :class="{ on: catFilter === '' }" @click="catFilter = ''; subFilter = ''">全部分类</button>
      <button v-for="c in categories" :key="c" class="ttab"
        :class="{ on: catFilter === c }" @click="catFilter = catFilter === c ? '' : c; subFilter = ''">{{ c }}</button>
      <el-button size="small" text type="primary" @click="newCatOpen = true">＋ 新建分组</el-button>
      <el-button size="small" text @click="manageOpen = true" :disabled="!categories.length">管理分组</el-button>
      <span class="cnt">{{ filtered.length }} 篇</span>
    </div>

    <!-- 当前分组的子分组筛选 -->
    <div v-if="catFilter && subOptions.length" class="filters glass subs">
      <button class="ttab" :class="{ on: subFilter === '' }" @click="subFilter = ''">全部子组</button>
      <button v-for="s in subOptions" :key="s" class="ttab"
        :class="{ on: subFilter === s }" @click="subFilter = subFilter === s ? '' : s">{{ s }}</button>
    </div>

    <!-- 列表 -->
    <div v-if="filtered.length" class="list">
      <div v-for="p in filtered" :key="p.id" class="paper-card glass" @click="$router.push(`/papers/${p.id}`)">
        <div class="pc-top">
          <span class="pc-title">{{ p.title }}</span>
          <el-select v-model="p.status" size="small" style="width: 92px" @change="(v: string) => setStatus(p, v)" @click.stop>
            <el-option v-for="s in ['想读', '在读', '读完']" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
        <div class="pc-sub">
          <el-select v-model="p.category" size="small" filterable allow-create clearable placeholder="分组"
            style="width: 110px" @change="(v: string) => setCategory(p, v)" @click.stop>
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-if="p.category" v-model="p.subcategory" size="small" filterable allow-create clearable placeholder="子分组"
            style="width: 110px" @change="(v: string) => setSubCategory(p, v)" @click.stop>
            <el-option v-for="s in (subcats[p.category] || [])" :key="s" :label="s" :value="s" />
          </el-select>
          <span v-if="p.author">{{ p.author }}</span>
          <el-tag v-for="t in p.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
          <span v-if="p.page_count" class="pg">共 {{ p.page_count }} 页</span>
        </div>
        <div v-if="p.note" class="pc-note">{{ p.note }}</div>
        <div class="pc-foot">
          <span class="time">{{ p.updated }}</span>
          <el-button size="small" type="danger" plain @click.stop="remove(p)">删除</el-button>
        </div>
      </div>
    </div>

    <EmptyState v-else icon="Reading" title="论文库还是空的"
      desc="可一次导入多篇 PDF，用「分组 → 子分组」整理、荧光笔标注重点、选中即查词/翻译。"
      :features="['多篇批量导入', '二级分组（分组内再分子分组）', '荧光笔标注（多色，翻页不丢）', '划词查词 / 免费翻译 / 入词本']">
      <template #default>
        <el-button type="primary" round style="margin-top:18px" @click="uploadOpen = true">导入论文</el-button>
      </template>
    </EmptyState>

    <!-- 新建分组 -->
    <el-dialog v-model="newCatOpen" title="新建分组" width="380px">
      <el-input v-model="newCatName" placeholder="分组名，如：经典 / 待读 / 大模型" @keyup.enter="addCategory" />
      <template #footer>
        <el-button @click="newCatOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!newCatName.trim()" @click="addCategory">添加</el-button>
      </template>
    </el-dialog>

    <!-- 管理分组（含子分组） -->
    <el-dialog v-model="manageOpen" title="管理分组（可加子分组）" width="480px">
      <div v-if="categories.length" class="mg-rows">
        <div v-for="c in categories" :key="c" class="mg-cat">
          <div class="mg-top">
            <span class="mg-name">{{ c }}</span>
            <el-button text size="small" @click="toggleSubInput(c)">＋ 子分组</el-button>
            <el-button text size="small" type="danger" @click="deleteCategory(c)">删除分组</el-button>
          </div>
          <div v-if="subInputCat === c" class="mg-newsub">
            <el-input v-model="subInputName" size="small" placeholder="子分组名" @keyup.enter="addSub(c)" />
            <el-button size="small" type="primary" @click="addSub(c)">添加</el-button>
          </div>
          <div class="mg-subs" v-if="(subcats[c] || []).length">
            <span v-for="s in subcats[c]" :key="s" class="sub-chip">{{ s }}
              <span class="x" @click="removeSub(c, s)">×</span>
            </span>
          </div>
        </div>
      </div>
      <p v-else class="hint">暂无分组 —— 用「＋ 新建分组」或论文卡片上的分组下拉添加。</p>
      <p class="hint">删除分组会一并删掉其子分组，组内论文变为未分组。</p>
    </el-dialog>
    <TrashDialog v-model="trashOpen" @restored="load" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { api, http } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import TrashDialog from '../components/TrashDialog.vue'

const trashOpen = ref(false)

interface Paper { id: string; title: string; author: string; status: string; tags: string[]; note: string; page_count: number; category: string; subcategory: string; added: string; updated: string }
type Picked = { raw: File; name: string }

const router = useRouter()
const uploadOpen = ref(false)
const uploading = ref(false)
const upTags = ref('')
const upCategory = ref('')
const upSub = ref('')
const papers = ref<Paper[]>([])
const categories = ref<string[]>([])
const subcats = ref<Record<string, string[]>>({})
const status = ref('')
const catFilter = ref('')
const subFilter = ref('')
const newCatOpen = ref(false)
const newCatName = ref('')
const manageOpen = ref(false)
const subInputCat = ref('')
const subInputName = ref('')
const pending = ref<Picked[]>([])

const statusFilters = [
  { value: '', label: '全部' }, { value: '想读', label: '想读' },
  { value: '在读', label: '在读' }, { value: '读完', label: '读完' },
]
const filtered = computed(() => papers.value.filter((p) => (
  (!status.value || p.status === status.value) &&
  (!catFilter.value || p.category === catFilter.value) &&
  (!subFilter.value || p.subcategory === subFilter.value)
)))
const subOptions = computed(() => (catFilter.value ? (subcats.value[catFilter.value] || []) : []))

type P = { raw: File; name: string }
function onPick(f: { raw?: File; name: string }) { if (f.raw) pending.value.push({ raw: f.raw, name: f.raw.name || f.name }) }

async function doUpload() {
  if (!pending.value.length) return ElMessage.warning('请先选择 PDF')
  uploading.value = true
  try {
    const fd = new FormData()
    pending.value.forEach((p) => fd.append('files', p.raw))
    if (upTags.value) fd.append('tags', upTags.value)
    if (upCategory.value) fd.append('category', ensureCategory(upCategory.value))
    if (upSub.value && upCategory.value) fd.append('subcategory', ensureSub(upCategory.value, upSub.value))
    const r = await api.post<{ items: Paper[] }>('/papers', fd, { timeout: 120000 })
    ElMessage.success(`已上传 ${r.items.length} 篇`)
    uploadOpen.value = false
    pending.value = []; upTags.value = ''; upCategory.value = ''; upSub.value = ''
    load(); loadCategories()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '上传失败') } finally { uploading.value = false }
}

async function loadCategories() {
  try {
    const r = await http.get<{ categories: string[]; subcategories: Record<string, string[]> }>('/papers/categories')
    categories.value = r.categories
    subcats.value = r.subcategories || {}
  } catch { /* ignore */ }
}

async function persistCats() {
  try { await http.put('/settings', { updates: { 'paper.categories': categories.value } }) } catch { /* ignore */ }
}
function subList(): { category: string; name: string }[] {
  const out: { category: string; name: string }[] = []
  for (const [c, arr] of Object.entries(subcats.value)) for (const n of arr) out.push({ category: c, name: n })
  return out
}
async function persistSubs() {
  try { await http.put('/settings', { updates: { 'paper.subcategories': subList() } }) } catch { /* ignore */ }
}

function ensureCategory(name: string) {
  const v = name && name.trim()
  if (!v) return ''
  if (!categories.value.includes(v)) { categories.value = [...categories.value, v]; persistCats() }
  return v
}
function ensureSub(cat: string, name: string) {
  const v = name && name.trim()
  if (!v) return ''
  const list = subcats.value[cat] = subcats.value[cat] || []
  if (!list.includes(v)) { list.push(v); persistSubs() }
  return v
}

async function saveMeta(p: Paper, patch: Partial<Paper>) {
  const body = {
    title: p.title, author: p.author, status: p.status, tags: p.tags, note: p.note,
    page_count: p.page_count, category: patch.category ?? p.category,
    subcategory: patch.subcategory ?? p.subcategory, link: (p as any).link || '',
  }
  Object.assign(p, patch)
  try { await http.put(`/papers/${p.id}/meta`, body) }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

async function setCategory(p: Paper, v: string) { const c = ensureCategory(v); await saveMeta(p, { category: c, subcategory: '' }) }
async function setSubCategory(p: Paper, v: string) { const c = p.category; const s = ensureSub(c, v); await saveMeta(p, { subcategory: s }) }
async function setStatus(p: Paper, v: string) { p.status = v; await saveMeta(p, { status: v }) }

async function addCategory() {
  const name = ensureCategory(newCatName.value)
  if (name) ElMessage.success('分组已添加')
  newCatOpen.value = false; newCatName.value = ''
}

function toggleSubInput(c: string) { subInputCat.value = subInputCat.value === c ? '' : c; subInputName.value = '' }
async function addSub(c: string) {
  const s = ensureSub(c, subInputName.value)
  if (s) ElMessage.success('子分组已添加')
  subInputCat.value = ''; subInputName.value = ''
}

async function removeSub(c: string, s: string) {
  subcats.value[c] = (subcats.value[c] || []).filter((x) => x !== s)
  persistSubs()
  for (const p of papers.value) if (p.category === c && p.subcategory === s) { p.subcategory = ''; await saveMeta(p, { subcategory: '' }) }
}

async function deleteCategory(c: string) {
  try { await ElMessageBox.confirm(`删除分组「${c}」及其子分组？组内论文变为未分组。`, '确认删除', { type: 'warning' }) } catch { return }
  for (const p of papers.value) if (p.category === c) { p.category = ''; p.subcategory = ''; await saveMeta(p, { category: '', subcategory: '' }) }
  categories.value = categories.value.filter((x) => x !== c)
  delete subcats.value[c]
  persistCats(); persistSubs()
  if (catFilter.value === c) { catFilter.value = ''; subFilter.value = '' }
  ElMessage.success('已删除分组')
}

async function remove(p: Paper) {
  try { await ElMessageBox.confirm(`删除「${p.title}」及其全部标注？`, '确认删除', { type: 'warning' }) } catch { return }
  try { await http.del(`/papers/${p.id}`); ElMessage.success('已删除'); load() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

async function load() {
  try { const r = await http.get<{ items: Paper[] }>('/papers'); papers.value = r.items }
  catch { /* ignore */ }
}

onMounted(() => { load(); loadCategories() })
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; }
.up { width: 100%; }
.cnt { color: var(--txt2); font-size: 12.5px; margin: 8px 0; }
.filters { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; padding: 10px 14px; margin-bottom: 12px; }
.filters.subs { margin-top: -4px; }
.ttab { border: none; cursor: pointer; padding: 5px 12px; border-radius: 999px; background: transparent; color: var(--txt2); font-size: 13px; font-family: inherit; }
.ttab.on { background: var(--acc-grad); color: #fff; font-weight: 600; }
.sep { width: 1px; height: 18px; background: rgba(148, 163, 184, 0.3); margin: 0 4px; }
.cnt { margin-left: auto; }
.list { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.paper-card { padding: 16px 18px; cursor: pointer; transition: transform .15s; }
.paper-card:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.18); }
.pc-top { display: flex; align-items: center; gap: 10px; }
.pc-title { font-weight: 700; font-size: 15px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pc-sub { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 8px 0; color: var(--txt2); font-size: 12.5px; }
.pg { margin-left: auto; }
.pc-note { color: var(--txt3); font-size: 12.5px; margin-bottom: 6px; }
.pc-foot { display: flex; align-items: center; justify-content: space-between; border-top: 1px dashed rgba(148, 163, 184, 0.25); padding-top: 8px; }
.time { font-size: 11px; color: var(--txt2); }

.mg-rows { display: grid; gap: 10px; }
.mg-cat { background: rgba(148, 163, 184, 0.08); border-radius: 10px; padding: 8px 12px; }
.mg-top { display: flex; align-items: center; gap: 10px; }
.mg-name { font-weight: 700; }
.mg-newsub { display: flex; gap: 8px; margin: 6px 0; }
.mg-subs { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.sub-chip { font-size: 12px; background: rgba(167, 139, 250, 0.14); color: var(--acc2); border-radius: 999px; padding: 2px 10px; }
.sub-chip .x { cursor: pointer; margin-left: 4px; opacity: .7; }
.hint { color: var(--txt2); font-size: 12.5px; margin: 8px 0 0; }
</style>
