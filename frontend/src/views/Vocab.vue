<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">生词本 · 复习</div>
        <div class="page-sub">读论文划词自动收集 · 简单间隔复习（Leitner 盒子）</div>
      </div>
      <div class="actions">
        <el-button @click="exportTsv">导出 TSV</el-button>
        <el-button type="primary" @click="openForm()"><el-icon style="margin-right:4px"><Plus /></el-icon>添加单词</el-button>
        <el-button type="success" :disabled="!stats.due" :loading="session.loading" @click="startSession">
          <el-icon style="margin-right:4px"><VideoPlay /></el-icon>开始复习（待复习 {{ stats.due }}）
        </el-button>
      </div>
    </div>

    <!-- 统计 -->
    <div class="grid">
      <div class="stat glass"><div class="num grad-text">{{ stats.total }}</div><div class="lab">总词数</div></div>
      <div class="stat glass"><div class="num grad-text">{{ stats.due }}</div><div class="lab">今日待复习</div></div>
      <div class="stat glass"><div class="num grad-text">{{ stats.mastered }}</div><div class="lab">已掌握</div></div>
      <div class="stat glass"><div class="num grad-text">{{ stats.fresh }}</div><div class="lab">还没练过</div></div>
    </div>

    <!-- 复习卡片 -->
    <div v-if="session.active" class="glass review">
      <div class="rv-head">
        <span>复习卡片</span>
        <span class="rv-prog">{{ session.idx + 1 }} / {{ session.items.length }}</span>
        <el-button size="small" text @click="endSession">退出</el-button>
      </div>
      <div class="rv-body" :class="{ show: session.reveal }" @click="session.reveal = true">
        <div class="rv-word">{{ cur.word }}</div>
        <div v-if="session.reveal" class="rv-detail">
          <div v-if="cur.meaning" class="rv-meaning">{{ cur.meaning }}</div>
          <div v-if="cur.sentence" class="rv-sentence">{{ cur.sentence }}</div>
        </div>
        <div v-else class="rv-tip">点击卡片查看释义</div>
      </div>
      <div v-if="session.reveal" class="rv-ops">
        <el-button size="large" type="danger" plain @click="answer(false)">
          <el-icon style="margin-right:4px"><Close /></el-icon>没记住
        </el-button>
        <el-button size="large" type="success" @click="answer(true)">
          <el-icon style="margin-right:4px"><Check /></el-icon>记住了
        </el-button>
      </div>
      <div v-if="session.done" class="rv-done">
        <div class="rv-done-t">本轮复习完成，练了 {{ session.doneCount }} 个词</div>
        <el-button type="primary" round @click="startSession">再来一轮</el-button>
        <el-button round @click="endSession">返回词库</el-button>
      </div>
    </div>

    <!-- 词库列表 -->
    <div class="glass list-card">
      <div class="lc-head">
        <span class="lc-t">词库（{{ items.length }}）</span>
        <el-input v-model="q" placeholder="搜索单词 / 释义…" clearable size="small" style="width: 220px" @input="loadList" />
      </div>
      <div v-if="items.length" class="rows">
        <div v-for="v in items" :key="v.id" class="vrow">
          <div class="vword" @click="pick(v)">{{ v.word }}</div>
          <div class="vpips" :title="`盒子 ${v.box}`">
            <span v-for="i in 5" :key="i" class="pip" :class="{ on: i <= v.box }" />
          </div>
          <div class="vmeaning">{{ v.meaning || '—' }}</div>
          <div class="vsentence">{{ v.sentence }}</div>
          <span class="vmeta" v-if="v.reviews">练 {{ v.reviews }} 次</span>
          <el-button text size="small" @click="openForm(v)">改</el-button>
          <el-button text size="small" type="danger" @click="del(v)">删</el-button>
        </div>
      </div>
      <div v-else class="empty">词库为空 —— 在论文阅读器里选中单词点"入生词本"，或手动添加。</div>
    </div>

    <!-- 添加/编辑 -->
    <el-dialog v-model="formOpen" :title="form.id ? '编辑单词' : '添加单词'" width="460px">
      <el-form label-position="top">
        <el-form-item label="单词"><el-input v-model="form.word" placeholder="英文单词 / 短语" /></el-form-item>
        <el-form-item label="释义"><el-input v-model="form.meaning" type="textarea" :rows="2" placeholder="中文释义，可多行" /></el-form-item>
        <el-form-item label="例句（可空）"><el-input v-model="form.sentence" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, VideoPlay, Check, Close } from '@element-plus/icons-vue'
import { http } from '../api/client'

interface VItem {
  id: number; word: string; meaning: string; sentence: string; source: string;
  added: string; box: number; reviews: number; next_due: string
}

const items = ref<VItem[]>([])
const q = ref('')
const stats = reactive({ total: 0, due: 0, mastered: 0, fresh: 0 })
const session = reactive({ active: false, loading: false, items: [] as VItem[], idx: 0, reveal: false, done: false, doneCount: 0 })
const formOpen = ref(false)
const saving = ref(false)
const form = reactive({ id: null as number | null, word: '', meaning: '', sentence: '' })

const cur = computed(() => session.items[session.idx])

async function loadStats() {
  try {
    const s = await http.get<typeof stats>('/vocab/stats')
    Object.assign(stats, s)
  } catch { /* ignore */ }
}

async function loadList() {
  try {
    const r = await http.get<{ items: VItem[] }>(q.value.trim() ? `/vocab?q=${encodeURIComponent(q.value.trim())}` : '/vocab')
    items.value = r.items
  } catch { /* ignore */ }
}

async function startSession() {
  session.loading = true
  try {
    const r = await http.get<{ items: VItem[] }>('/vocab/review?limit=15')
    if (!r.items.length) {
      ElMessage.success('当前没有待复习的词')
      session.active = false
      return
    }
    session.items = r.items
    session.idx = 0
    session.reveal = false
    session.done = false
    session.active = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally { session.loading = false }
}

async function answer(correct: boolean) {
  const item = cur.value
  if (!item) return
  session.doneCount++
  try {
    await http.post(`/vocab/${item.id}/review`, { correct })
  } catch { /* 忽略单次上报失败 */ }
  if (session.idx + 1 >= session.items.length) {
    session.done = true
    session.reveal = false
    loadStats()
    loadList()
  } else {
    session.idx++
    session.reveal = false
  }
}

function endSession() {
  session.active = false
  session.items = []
  loadStats()
  loadList()
}

function openForm(v?: VItem) {
  form.id = v?.id ?? null
  form.word = v?.word ?? ''
  form.meaning = v?.meaning ?? ''
  form.sentence = v?.sentence ?? ''
  formOpen.value = true
}

async function saveForm() {
  if (!form.word.trim()) return ElMessage.warning('请填写单词')
  saving.value = true
  const body = { word: form.word.trim(), meaning: form.meaning.trim(), sentence: form.sentence.trim(), source: '' }
  try {
    if (form.id) await http.put(`/vocab/${form.id}`, body)
    else await http.post('/vocab', body)
    formOpen.value = false
    loadList()
    loadStats()
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

async function del(v: VItem) {
  try {
    await ElMessageBox.confirm(`删除「${v.word}」？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/vocab/${v.id}`)
    loadList()
    loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function pick(v: VItem) {
  ElMessageBox.alert(`${v.word}\n\n释义：${v.meaning || '—'}${v.sentence ? `\n例句：${v.sentence}` : ''}`, '词条详情', { confirmButtonText: '知道了' }).catch(() => {})
}

function exportTsv() {
  const esc = (s: string) => (s || '').replace(/\t/g, ' ').replace(/\r?\n/g, ' ')
  const lines = items.value.map((v) => [esc(v.word), esc(v.meaning), esc(v.sentence)].join('\t'))
  const blob = new Blob([`单词\t释义\t例句\n${lines.join('\n')}`], { type: 'text/tab-separated-values;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '生词本.tsv'
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadStats()
  loadList()
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin: 16px 0; }
.stat { padding: 16px 18px; }
.stat .num { font-size: 26px; font-weight: 900; }
.stat .lab { font-size: 12.5px; margin-top: 2px; color: var(--txt2); }

.review { padding: 22px; margin-bottom: 16px; text-align: center; }
.rv-head { display: flex; align-items: center; gap: 12px; font-weight: 700; }
.rv-head > span:first-child { margin-left: auto; }
.rv-head .el-button { margin-left: 0; }
.rv-prog { color: var(--txt2); font-weight: 500; }
.rv-body { margin: 18px auto; max-width: 640px; min-height: 170px; cursor: pointer; display: flex; flex-direction: column; justify-content: center; }
.rv-word { font-size: 42px; font-weight: 900; letter-spacing: 1px; word-break: break-all; }
.rv-tip { color: var(--txt2); font-size: 13px; margin-top: 14px; }
.rv-detail { margin-top: 16px; }
.rv-meaning { font-size: 17px; line-height: 1.8; }
.rv-sentence { margin-top: 10px; font-size: 13.5px; color: var(--txt3); font-style: italic; }
.rv-ops { display: flex; justify-content: center; gap: 14px; }
.rv-done { margin-top: 18px; }
.rv-done-t { font-size: 16px; font-weight: 700; margin-bottom: 14px; }

.list-card { padding: 16px 18px; }
.lc-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 10px; }
.lc-t { font-weight: 700; }
.rows { display: grid; gap: 6px; }
.vrow {
  display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 10px;
  background: rgba(148, 163, 184, 0.06); font-size: 13px; flex-wrap: wrap;
}
.vword { font-weight: 700; min-width: 130px; cursor: pointer; color: var(--acc2); }
.vpips { display: flex; gap: 3px; }
.pip { width: 7px; height: 7px; border-radius: 50%; background: rgba(148, 163, 184, 0.4); }
.pip.on { background: var(--acc2); }
.vmeaning { flex: 1; min-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vsentence { color: var(--txt3); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vmeta { font-size: 11px; color: var(--txt2); }
.empty { color: var(--txt2); padding: 20px 4px; font-size: 13.5px; }
</style>
