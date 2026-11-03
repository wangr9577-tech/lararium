<template>
  <div class="page" v-loading="loading">
    <div class="head-row">
      <div>
        <div class="page-title">个人主页</div>
        <div class="page-sub">所有内容网页可直接编辑 —— 点各区块「保存」即时生效</div>
      </div>
      <ShareDialog target="me" ref="" button-text="分享主页" type="success" plain />
    </div>

    <div class="me-grid">
      <!-- 基本信息（占满两列） -->
      <section class="glass card">
        <div class="card-title"><el-icon><User /></el-icon>基本信息
          <span class="unsaved" v-if="dirty.profile">（未保存）</span>
        </div>
        <div class="basic">
          <div class="fg"><el-input v-model="profile.name" placeholder="昵称/姓名" /></div>
          <div class="fg-wide"><el-input v-model="profile.tagline" placeholder="一句话自我介绍（副标题）" /></div>
        </div>
        <div class="grid">
          <label v-for="f in basicFields" :key="f.key" class="field">
            <span class="lab">{{ f.label }}</span>
            <el-input v-model="profile[f.key]" :placeholder="f.ph" />
          </label>
          <label class="field wide">
            <span class="lab">研究方向 / 简介（可多行）</span>
            <el-input v-model="profile.bio" type="textarea" :rows="2" placeholder="研究方向、想做的事…" />
          </label>
        </div>
        <div class="sec-ops"><el-button type="primary" size="small" @click="saveKey('me.profile', profile)">保存基本信息</el-button></div>
      </section>

      <div class="col">
      <section class="glass card">
        <div class="card-title"><el-icon><Trophy /></el-icon>荣誉 / 奖项
          <span class="unsaved" v-if="dirty.honors">（未保存）</span>
          <el-button size="small" circle class="add-btn" @click="honors.push({ id: uid(), year: '', title: '' })">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div v-if="honors.length" class="rows">
          <div v-for="h in honors" :key="h.id" class="row3">
            <el-input v-model="h.year" placeholder="年份" class="w100" />
            <el-input v-model="h.title" placeholder="荣誉或奖项名称" />
            <el-button text type="danger" circle @click="honors = honors.filter((x) => x.id !== h.id)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <p v-else class="empty-hint">点击右上角 ＋ 添加荣誉与奖项</p>
        <div class="sec-ops"><el-button type="primary" size="small" @click="saveKey('me.honors', honors)">保存</el-button></div>
      </section>

      <!-- 右列：论文 -->
      <section class="glass card">
        <div class="card-title"><el-icon><Document /></el-icon>论文 / 学术成果
          <span class="unsaved" v-if="dirty.publications">（未保存）</span>
          <el-button size="small" circle class="add-btn" @click="publications.push({ id: uid(), title: '', venue: '', status: '进行中', year: '', note: '', link: '' })">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div v-if="publications.length" class="pub-list">
          <div v-for="p in publications" :key="p.id" class="pub glass2">
            <div class="pub-row"><el-input v-model="p.title" placeholder="论文标题" /></div>
            <div class="pub-row">
              <el-select v-model="p.status" style="width: 110px">
                <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
              </el-select>
              <el-input v-model="p.venue" placeholder="会议/期刊" />
              <el-input v-model="p.year" placeholder="年份" class="w70" />
              <el-button text type="danger" circle @click="publications = publications.filter((x) => x.id !== p.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <div class="pub-row"><el-input v-model="p.note" placeholder="备注（oral / 投稿中…）" /></div>
          </div>
        </div>
        <p v-else class="empty-hint">点击右上角 ＋ 添加学术成果或论文</p>
        <div class="sec-ops"><el-button type="primary" size="small" @click="saveKey('me.publications', publications)">保存</el-button></div>
      </section>
      </div>

      <!-- 里程碑（占满两列） -->
      <section class="glass card span-all">
        <div class="card-title"><el-icon><Flag /></el-icon>重要阶段里程碑
          <span class="unsaved" v-if="dirty.milestones">（未保存）</span>
          <el-button size="small" circle class="add-btn" @click="milestones.push({ id: uid(), time: '', title: '', note: '', done: false })">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <el-timeline v-if="milestones.length" class="tl">
          <el-timeline-item v-for="m in milestones" :key="m.id" :timestamp="m.time" placement="top"
            :type="m.done ? 'success' : 'primary'">
            <div class="tl-row">
              <el-checkbox v-model="m.done" class="tl-done" />
              <el-input v-model="m.title" class="tl-title" placeholder="里程碑标题" />
              <el-input v-model="m.time" class="w150" placeholder="时间节点，如 2027 年秋" />
              <el-button text type="danger" circle @click="milestones = milestones.filter((x) => x.id !== m.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-input v-model="m.note" class="tl-note" placeholder="说明 / 下一步…" />
          </el-timeline-item>
        </el-timeline>
        <p v-else class="empty-hint">点击右上角 ＋ 添加里程碑规划</p>
        <div class="sec-ops"><el-button type="primary" size="small" @click="saveKey('me.milestones', milestones)">保存</el-button></div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Trophy, Document, Flag, Plus, Delete } from '@element-plus/icons-vue'
import { http } from '../api/client'
import ShareDialog from '../components/ShareDialog.vue'

const uid = () => `m${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`
const statuses = ['进行中', '已投稿', 'Under Review', 'Major/Minor Revision', '已录用', '已发表', 'Oral/Poster', '想投']

interface Row { id: string }
type AnyRow = Row & Record<string, any>

const loading = ref(true)
const profile = reactive<Record<string, string>>({ name: '', tagline: '', school: '', major: '', grade: '', bio: '' })
const honors = ref<AnyRow[]>([])
const publications = ref<AnyRow[]>([])
const milestones = ref<AnyRow[]>([])
const dirty = reactive({ profile: false, honors: false, publications: false, milestones: false })

const basicFields = [
  { key: 'school', label: '学校', ph: '你的学校' },
  { key: 'major', label: '专业', ph: '你的专业' },
  { key: 'grade', label: '年级', ph: '入学年份 / 年级' },
]

async function saveKey(key: string, data: any) {
  try {
    await http.put('/settings', { updates: { [key]: JSON.parse(JSON.stringify(data)) } })
    const section = key.replace('me.', '')
    ;(dirty as Record<string, boolean>)[section] = false
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

onMounted(async () => {
  try {
    const cfg = await http.get<Record<string, any>>('/settings')
    Object.assign(profile, cfg['me.profile'] || {})
    honors.value = cfg['me.honors'] || []
    publications.value = cfg['me.publications'] || []
    milestones.value = cfg['me.milestones'] || []
  } catch { /* 401/423 统一跳登录 */ }
  loading.value = false
})
</script>

<style scoped>
.head-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }

.me-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
.col { display: grid; gap: 14px; align-content: start; }
.span-all { grid-column: 1 / -1; }
@media (max-width: 900px) { .me-grid { grid-template-columns: 1fr; } }

.card { padding: 16px 18px; }
.card-title { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 700; margin-bottom: 12px; }
.add-btn { margin-left: auto; }
.unsaved { color: #f59e0b; font-size: 12px; font-weight: 500; }

.basic { display: grid; gap: 8px; margin-bottom: 10px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 4px 14px; }
.field { display: grid; gap: 4px; }
.lab { font-size: 12px; color: var(--txt3); }
.field.wide { grid-column: 1 / -1; }

.rows { display: grid; gap: 8px; }
.row3 { display: flex; gap: 8px; }
.row3 .w100 { width: 110px; }
.w70 { width: 74px; }
.w150 { width: 150px; }

.pub-list { display: grid; gap: 10px; }
.pub { padding: 10px 12px; border-radius: 12px; background: rgba(167, 139, 250, 0.06); }
.pub-row { display: flex; gap: 8px; margin-bottom: 8px; }
.pub-row:last-child { margin-bottom: 0; }

.tl { margin-top: 4px; }
.tl-row { display: flex; gap: 10px; align-items: center; }
.tl-main { display: flex; gap: 8px; align-items: center; flex: 1; }
.tl-title :deep(input) { font-weight: 600; }
.tl-note { margin-top: 6px; }

.empty-hint { color: var(--txt2); font-size: 12.5px; padding: 10px 4px; line-height: 1.7; }
.sec-ops { display: flex; justify-content: flex-end; margin-top: 10px; }
.glass2 { border: 1px solid rgba(148, 163, 184, 0.2); }
</style>
