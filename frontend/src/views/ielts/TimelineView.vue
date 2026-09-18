<template>
  <div>
    <div class="sub-head">
      <el-button text @click="$router.push('/ielts')"><el-icon><ArrowLeft /></el-icon>雅思主页</el-button>
      <span class="sub-name">时间轴 · 四科打卡</span>
    </div>
    <div class="cols">
    <section v-for="s in sections" :key="s.key" class="col glass" :style="{ '--col': s.color }">
      <header class="col-head">
        <span class="col-title">{{ s.title }}</span>
        <span class="col-count">{{ doneOf(s.key) }} / {{ listOf(s.key).length }}</span>
      </header>

      <!-- 时间线 -->
      <div class="tl">
        <div v-for="it in listOf(s.key)" :key="it.id" class="item" :class="{ done: it.done }">
          <el-checkbox :model-value="it.done" size="small" @change="(v: any) => toggle(it, v)" />
          <input
            v-if="editingId === it.id" v-model="editText" class="edit-in" autofocus
            @keyup.enter="commitEdit(it)" @keyup.esc="cancelEdit" @blur="commitEdit(it)"
          />
          <span v-else class="txt" @dblclick="startEdit(it)">{{ it.text }}</span>
          <span class="date">{{ it.created.slice(5, 10) }}</span>
          <button class="mini" type="button" title="修改" @click="startEdit(it)">改</button>
          <button class="mini del" type="button" title="删除" @click="remove(it)">删</button>
        </div>
        <div v-if="!listOf(s.key).length" class="empty">还没有条目，下面添加</div>
      </div>

      <!-- 新增 -->
      <div class="add">
        <el-input
          v-model="newText[s.key]" size="small" clearable
          :placeholder="s.ph" @keyup.enter="addItem(s.key)"
        >
          <template #append>
            <el-button :disabled="!newText[s.key]?.trim()" @click="addItem(s.key)">新增</el-button>
          </template>
        </el-input>
      </div>

      <!-- 学习资料 -->
      <div class="res">
        <div class="res-t">学习资料</div>
        <div v-for="(r, i) in resOf(s.key)" :key="i" class="res-item">
          <a v-if="r.url" class="res-a" :href="r.url" target="_blank" rel="noopener">{{ r.name }}</a>
          <span v-else class="res-a">{{ r.name }}</span>
          <span class="res-note">{{ r.note }}</span>
        </div>
      </div>
    </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { http } from '../../api/client'

type Section = 'listening' | 'speaking' | 'reading' | 'writing'
interface Item { id: number; section: Section; text: string; done: boolean; created: string }

const sections: { key: Section; title: string; color: string; ph: string }[] = [
  { key: 'listening', title: '听力', color: '#38bdf8', ph: '记一条听力计划 / 已完成…' },
  { key: 'speaking', title: '口语', color: '#f472b6', ph: '主题素材背完一项勾一项…' },
  { key: 'reading', title: '阅读', color: '#a78bfa', ph: '记一条阅读计划 / 已完成…' },
  { key: 'writing', title: '写作', color: '#fbbf24', ph: '记一条写作计划 / 已完成…' },
]

const resources: Record<Section, { name: string; url?: string; note: string }[]> = {
  listening: [
    { name: 'onenetbee/IELTS · 雅思官方真题（剑桥雅思）', url: 'https://github.com/onenetbee/IELTS', note: '官方历年真题集含音频与文本，精听用' },
    { name: 'geally/IELTS · 真题镜像库', url: 'https://github.com/geally/IELTS', note: '备用下载源，防失效' },
  ],
  speaking: [
    { name: 'IELTS-Speaking-AI（练习）', url: 'https://github.com/1599570912/IELTS-Speaking-AI', note: '本地 AI 口语：语音识别 + 评分 + 210+ 题，无需 ChatGPT' },
    { name: '背诵 · ieltia', url: 'https://github.com/RobinTrigon/ieltia', note: 'IELTS 资料合集（打开确认分话题内容）' },
    { name: '背诵 · IELTS-Speaking-Preparation', url: 'https://github.com/moo-gh/IELTS-Speaking-Preparation', note: '口语示例回答合集' },
    { name: '背诵 · 200 IELTS Speaking Cue Cards', url: 'https://zabanhub.ir/book/%da%a9%d8%aa%d8%a8-200ielts-speaking-cue-cards/', note: 'Part1-3 话题卡题库与范文（免费电子书）' },
  ],
  reading: [
    { name: '百词斩', note: 'App 内背「雅思核心词」词书，每日 30 个（含在周计划 1 小时内）' },
    { name: '雅思官方真题 Reading', url: 'https://github.com/onenetbee/IELTS', note: '剑桥雅思 C16-C19 限时练习与精读' },
  ],
  writing: [
    { name: 'IELTS_Writing_Task1_Band9_Answers', url: 'https://github.com/MikeWu597/IELTS_Writing_Task1_Band9_Answers', note: '小作文 Band9 范文' },
    { name: 'openIELTS · 写作批改与范文', url: 'https://github.com/mcxiaoxiao/openIELTS', note: '批改渠道 + 评分表 + AI 辅助' },
  ],
}

const items = ref<Item[]>([])
const newText = reactive<Record<Section, string>>({ listening: '', speaking: '', reading: '', writing: '' })
const editingId = ref<number | null>(null)
const editText = ref('')

function listOf(k: Section) {
  return items.value.filter((i) => i.section === k)
}
function doneOf(k: Section) {
  return listOf(k).filter((i) => i.done).length
}
function resOf(k: Section) {
  return resources[k]
}

function err(e: any, fallback: string) {
  if (e?.response?.status !== 401 && e?.response?.status !== 423) {
    ElMessage.error(e?.response?.data?.detail || fallback)
  }
}

async function load() {
  try {
    const r = await http.get<{ items: Item[] }>('/ielts/items')
    items.value = r.items
  } catch (e: any) {
    err(e, '雅思学习数据加载失败')
    items.value = []
  }
}

async function addItem(k: Section) {
  const t = newText[k].trim()
  if (!t) return
  try {
    const r = await http.post<Item>('/ielts/items', { section: k, text: t })
    items.value.push(r)
    newText[k] = ''
  } catch (e: any) {
    err(e, '新增失败')
  }
}

async function toggle(it: Item, v: boolean) {
  const before = it.done
  it.done = !!v
  try {
    await http.put(`/ielts/items/${it.id}/done`, { done: it.done })
  } catch (e: any) {
    it.done = before
    err(e, '更新失败')
  }
}

function startEdit(it: Item) {
  editingId.value = it.id
  editText.value = it.text
}
function cancelEdit() {
  editingId.value = null
}
async function commitEdit(it: Item) {
  if (editingId.value !== it.id) return
  editingId.value = null
  const t = editText.value.trim()
  if (!t || t === it.text) return
  const before = it.text
  it.text = t
  try {
    await http.put(`/ielts/items/${it.id}`, { text: t })
  } catch (e: any) {
    it.text = before
    err(e, '修改失败')
  }
}

async function remove(it: Item) {
  try {
    await ElMessageBox.confirm(`删除「${it.text}」？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/ielts/items/${it.id}`)
    items.value = items.value.filter((x) => x.id !== it.id)
  } catch (e: any) {
    err(e, '删除失败')
  }
}

onMounted(load)
</script>

<style scoped>
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sub-name { font-size: 15px; font-weight: 800; }
.cols { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; align-items: start; }
.col { padding: 14px 14px 12px; display: flex; flex-direction: column; min-width: 0; }
.col-head {
  display: flex; align-items: center; gap: 8px;
  border-left: 4px solid var(--col); padding-left: 8px; margin-bottom: 10px;
}
.col-title { font-size: 17px; font-weight: 800; }
.col-count {
  margin-left: auto; font-size: 12px; color: var(--txt2);
  background: rgba(148, 163, 184, 0.14); border-radius: 999px; padding: 1px 9px;
}

.tl { display: grid; gap: 5px; min-height: 120px; }
.item {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 8px; border-radius: 9px; font-size: 13px;
  border: 1px solid rgba(148, 163, 184, 0.12);
}
.item.done .txt { text-decoration: line-through; color: var(--txt2); opacity: 0.72; }
.txt { flex: 1; min-width: 0; cursor: pointer; line-height: 1.5; }
.edit-in {
  flex: 1; min-width: 0; border: 1px solid var(--acc3); border-radius: 6px;
  background: transparent; color: inherit; font: inherit; padding: 2px 6px; outline: none;
}
.date { flex: none; font-size: 10.5px; color: var(--txt3); }
html.theme-dark .date { color: var(--txt2); }
.mini {
  flex: none; border: none; background: transparent; cursor: pointer;
  font-size: 11.5px; color: var(--acc2); padding: 0 2px; font-family: inherit;
}
.mini.del { color: #f43f5e; }
.empty { color: var(--txt2); font-size: 12.5px; padding: 18px 4px; text-align: center; }

.add { margin: 10px 0 4px; }

.res { border-top: 1px dashed rgba(148, 163, 184, 0.3); padding-top: 8px; }
.res-t { font-size: 11.5px; font-weight: 700; color: var(--txt2); letter-spacing: 1px; margin-bottom: 5px; }
.res-item { display: flex; flex-direction: column; gap: 1px; padding: 4px 2px; font-size: 12.5px; }
.res-a {
  color: var(--acc2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer;
}
.res-a:hover { text-decoration: underline; }
.res-note { color: var(--txt3); font-size: 11px; }
html.theme-dark .res-note { color: var(--txt2); }

@media (max-width: 1500px) {
  .cols { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .cols { grid-template-columns: 1fr; }
}
</style>
