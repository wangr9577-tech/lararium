<template>
  <div class="page pw">
    <div class="phead glass">
      <el-button text @click="$router.push('/papers')"><el-icon><ArrowLeft /></el-icon>返回论文库</el-button>
      <div class="ptitle">{{ paper?.title || '论文阅读' }}</div>
      <div class="pmeta">
        <el-tag v-if="paper?.status" size="small" effect="plain">{{ paper.status }}</el-tag>
        <el-tag v-for="t in paper?.tags || []" :key="t" size="small" effect="plain">{{ t }}</el-tag>
        <span v-if="pageTotal" class="pg">第 {{ curPage }}/{{ pageTotal }} 页</span>
      </div>
      <div class="pops">
        <el-button size="small" @click="questionOpen = true">论文问答 / 对比</el-button>
        <el-button size="small" @click="metaOpen = true">编辑信息</el-button>
        <el-button size="small" type="danger" plain @click="removePaper">删除论文</el-button>
      </div>
    </div>

    <PaperReader
      v-if="paper" :paper-id="paper.id" :title="paper.title"
      @pages="(n: number) => savePageCount(n)"
      @page="(n: number, t: number) => { curPage = n; pageTotal = t }"
    />
    <PaperQuestion v-if="paper" v-model="questionOpen" :paper-id="paper.id" />

    <el-dialog v-model="metaOpen" title="论文信息" width="460px">
      <el-form label-position="top" v-if="paper">
        <el-form-item label="标题"><el-input v-model="ed.title" /></el-form-item>
        <el-form-item label="作者（可空）"><el-input v-model="ed.author" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="ed.status" style="width: 120px">
            <el-option v-for="s in ['想读', '在读', '精读', '读完', '搁置']" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="ed.category" filterable allow-create clearable style="width: 100%" @change="ed.subcategory = ''">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="DOI / 链接（可空）"><el-input v-model="ed.link" placeholder="https://doi.org/…" /></el-form-item>
        <el-form-item label="arXiv id（可空）"><el-input v-model="ed.arxiv_id" placeholder="如 2503.12345" /></el-form-item>
        <el-form-item label="年份 / 期刊会议"><div class="yr-row">
          <el-input v-model="ed.year" placeholder="年份" style="width: 90px" />
          <el-input v-model="ed.venue" placeholder="期刊 / 会议名" />
        </div></el-form-item>
        <el-form-item label="作者（逗号分隔）"><el-input v-model="ed.authorsText" /></el-form-item>
        <el-form-item label="摘要"><el-input v-model="ed.abstract" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="关键词（逗号分隔）"><el-input v-model="ed.keywordsText" /></el-form-item>
        <el-form-item v-if="subOptions.length" label="子分组">
          <el-select v-model="ed.subcategory" filterable allow-create clearable style="width: 100%">
            <el-option v-for="s in subOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签（逗号分隔）"><el-input v-model="ed.tags" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="ed.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importMeta">一键导入元数据（arXiv id）</el-button>
        <el-button @click="metaOpen = false">取消</el-button>
        <el-button type="primary" :loading="metaSaving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { http } from '../api/client'
import PaperReader from '../components/PaperReader.vue'
import PaperQuestion from '../components/PaperQuestion.vue'

interface Paper { id: string; title: string; author: string; status: string; tags: string[]; note: string; page_count: number; category: string; subcategory: string; link: string }

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)
const paper = ref<Paper | null>(null)
const curPage = ref(1)
const pageTotal = ref(0)
const metaOpen = ref(false)
const questionOpen = ref(false)
const metaSaving = ref(false)
const ed = reactive({
  title: '', author: '', status: '想读', tags: '', note: '', category: '', subcategory: '', link: '',
  arxiv_id: '', year: '', venue: '', authorsText: '', abstract: '', keywordsText: '',
})
const categories = ref<string[]>([])
const subcats = ref<Record<string, string[]>>({})
const subOptions = computed(() => (ed.category ? (subcats.value[ed.category] || []) : []))
let countSaved = false

async function savePageCount(n: number) {
  if (!paper.value || countSaved) return
  countSaved = true
  if (paper.value.page_count === n) return
  await http.put(`/papers/${paper.value.id}/meta`, {
    title: paper.value.title, author: paper.value.author, status: paper.value.status,
    tags: paper.value.tags, note: paper.value.note, page_count: n,
  }).catch(() => {})
  paper.value.page_count = n
}

function saveMeta() {
  if (!paper.value) return
  metaSaving.value = true
  const tags = ed.tags.split(/[,，]/).map((t: string) => t.trim()).filter(Boolean)
  const authors = ed.authorsText.split(/[,，]/).map((a: string) => a.trim()).filter(Boolean)
  const keywords = ed.keywordsText.split(/[,，]/).map((k: string) => k.trim()).filter(Boolean)
  http.put(`/papers/${paper.value.id}/meta`, {
    title: ed.title.trim() || paper.value.title, author: ed.author.trim(),
    status: ed.status, tags, note: ed.note.trim(), page_count: paper.value.page_count,
    category: ed.category.trim(),
    subcategory: ed.subcategory.trim(),
    link: ed.link.trim(),
    arxiv_id: ed.arxiv_id.trim(), year: ed.year.trim(), venue: ed.venue.trim(),
    authors, abstract: ed.abstract.trim(), keywords,
  }).then((m: Paper) => {
    paper.value = { ...m, related_ids: (m as any).related_ids || [] }
    metaOpen.value = false
    ElMessage.success('已保存')
  }).catch((e: any) => ElMessage.error(e?.response?.data?.detail || '保存失败'))
    .finally(() => { metaSaving.value = false })
}

/** 按 arXiv id / DOI 一键拉取元数据 */
async function importMeta() {
  const src = ed.arxiv_id.trim() ? { source: 'arxiv', id: ed.arxiv_id.trim() } : null
  if (!src) return ElMessage.warning('请先填 arXiv id（DOI 导入请把链接填到 DOI 框也可用）')
  metaSaving.value = true
  try {
    const r = await http.post<{ meta: any }>('/papers/import-meta', src)
    const m = r.meta
    ed.title = m.title || ed.title
    ed.arxiv_id = m.arxiv_id || ed.arxiv_id
    ed.year = m.year || ed.year
    ed.venue = m.venue || ed.venue
    ed.authorsText = (m.authors || []).join(', ')
    ed.abstract = m.abstract || ed.abstract
    if (m.doi) ed.link = m.doi.startsWith('http') ? m.doi : `https://doi.org/${m.doi}`
    ElMessage.success('元数据已拉取，点「保存」落盘')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '拉取失败') }
  finally { metaSaving.value = false }
}

async function removePaper() {
  try {
    await ElMessageBox.confirm('删除该论文与全部标注？', '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/papers/${id}`)
    ElMessage.success('已删除')
    router.push('/papers')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

onMounted(async () => {
  try {
    paper.value = await http.get<Paper>(`/papers/${id}`)
    ed.title = paper.value.title
    ed.author = paper.value.author
    ed.status = paper.value.status
    ed.tags = paper.value.tags.join(', ')
    ed.note = paper.value.note
    ed.category = paper.value.category || ''
    ed.subcategory = paper.value.subcategory || ''
    ed.link = paper.value.link || ''
    ed.arxiv_id = (paper.value as any).arxiv_id || ''
    ed.year = (paper.value as any).year || ''
    ed.venue = (paper.value as any).venue || ''
    ed.authorsText = ((paper.value as any).authors || []).join(', ')
    ed.abstract = (paper.value as any).abstract || ''
    ed.keywordsText = ((paper.value as any).keywords || []).join(', ')
    try {
      const r = await http.get<{ categories: string[]; subcategories: Record<string, string[]> }>('/papers/categories')
      categories.value = r.categories
      subcats.value = r.subcategories || {}
    } catch { /* ignore */ }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '论文不存在')
    router.push('/papers')
  }
})
</script>

<style scoped>
.pw { max-width: 1680px; }   /* 中英对照两栏时给足宽度；窄屏仍受视口限制 */
.phead { display: flex; align-items: center; gap: 12px; padding: 10px 16px; margin-bottom: 12px; flex-wrap: wrap; }
.ptitle { font-weight: 700; font-size: 15px; }
.pmeta { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.pops { display: flex; gap: 8px; }
.pg { font-size: 12px; color: var(--txt2); }
.yr-row { display: flex; gap: 10px; width: 100%; }
</style>
