<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">设置</div>
        <div class="page-sub">主题 / 翻译源 / 账户 —— 配置实时保存到后端</div>
      </div>
    </div>

    <!-- 站点信息 -->
    <section class="glass card">
      <div class="card-title"><el-icon><House /></el-icon>站点信息（品牌名 / 标语，全站生效）</div>
      <div class="form-grid">
        <el-form-item label="站点名称">
          <el-input v-model="siteName" placeholder="如 Kruskal" />
        </el-form-item>
        <el-form-item label="站点标语">
          <el-input v-model="siteSlogan" placeholder="如：日程 · 笔记 · 论文 · 二次元小站" />
        </el-form-item>
      </div>
      <el-button type="primary" size="small" @click="saveSite">保存站点信息</el-button>
    </section>

    <!-- 主题 -->
    <section class="glass card">
      <div class="card-title"><el-icon><Brush /></el-icon> 主题</div>
      <el-radio-group v-model="themeMode" @change="saveTheme">
        <el-radio-button value="dark">暗黑 · 星夜（默认）</el-radio-button>
        <el-radio-button value="light">明亮 · 粉紫</el-radio-button>
      </el-radio-group>
      <p class="hint">暗黑主题使用二次元背景图；明亮主题为纯渐变底（图片仅登录页显示）。</p>
    </section>

    <!-- 分享管理 -->
    <section class="glass card">
      <div class="card-title"><el-icon><Link /></el-icon> 分享管理（只读快照链接）</div>
      <div v-if="shareItems.length" class="share-list">
        <div v-for="s in shareItems" :key="s.token" class="share-row">
          <div class="sr-main">
            <div class="sr-title">{{ s.target === 'me' ? '个人主页' : s.title }}
              <span class="chip">{{ s.target === 'me' ? '主页' : '博客' }}</span>
            </div>
            <div class="sr-sub">{{ locationOrigin }}{{ s.url }} · 生成于 {{ s.created }}</div>
          </div>
          <el-button size="small" @click="copyShare(s)">复制</el-button>
          <el-button size="small" type="danger" plain @click="revokeShare(s)">撤销</el-button>
        </div>
      </div>
      <p v-else class="hint">还没有任何分享 —— 在博客阅读页或个人主页点「分享」即可生成。</p>
      <p class="hint">快照机制：内容更新后请在分享弹窗点「刷新快照」；撤销后链接立即失效。链接只在服务器对外可达时对方才能打开。</p>
    </section>

    <!-- 翻译源 -->
    <section class="glass card">
      <div class="card-title"><el-icon><Reading /></el-icon> 翻译源（划词翻译用）</div>
      <div v-if="translateSources.length" class="src-list">
        <label
          v-for="s in translateSources" :key="s.id"
          class="src" :class="{ active: translateSource === s.id }"
        >
          <input v-model="translateSource" type="radio" :value="s.id" />
          <div class="src-main">
            <div class="src-name">{{ s.name }}
              <span v-if="s.need_key" class="chip">需免费 key</span>
              <span v-else class="chip">免 key</span>
            </div>
            <div class="src-note">{{ s.note }}</div>
          </div>
        </label>
      </div>
      <p v-else class="hint">加载中…</p>
      <el-button type="primary" size="small" @click="saveTranslate">保存翻译源</el-button>
    </section>

    <!-- 账户 -->
    <section class="glass card">
      <div class="card-title"><el-icon><Key /></el-icon> 账户安全</div>
      <el-form label-position="top" class="pw-form" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="旧密码"><el-input v-model="pw.old" type="password" show-password /></el-form-item>
          <el-form-item label="新密码（≥8 位）"><el-input v-model="pw.next" type="password" show-password /></el-form-item>
          <el-form-item label="确认新密码"><el-input v-model="pw.confirm" type="password" show-password /></el-form-item>
        </div>
        <el-button type="warning" @click="changePassword">修改密码</el-button>
        <p class="hint">改密会重新加密你的数据密钥并注销其他会话；<b>忘记密码 = 数据无法恢复</b>，请牢记。</p>
      </el-form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { http, clearToken } from '../api/client'
import { loadSite } from '../stores/site'

const router = useRouter()
const themeMode = ref(localStorage.getItem('krs_theme') || 'dark')
const siteName = ref('Kruskal')
const siteSlogan = ref('')
const translateSources = ref<{ id: string; name: string; note: string; need_key: boolean }[]>([])
const translateSource = ref('youdao-dict')
const pw = reactive({ old: '', next: '', confirm: '' })
const locationOrigin = window.location.origin
const shareItems = ref<{ token: string; target: string; ref: string; title: string; url: string; created: string }[]>([])

function applyTheme(mode: string) {
  document.documentElement.classList.toggle('theme-dark', mode === 'dark')
}

async function saveSite() {
  try {
    await http.put('/settings', { updates: { 'site.name': siteName.value, 'site.slogan': siteSlogan.value } })
    await loadSite(true)
    ElMessage.success('站点信息已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

async function saveTheme() {
  localStorage.setItem('krs_theme', themeMode.value)
  applyTheme(themeMode.value)
  try { await http.put('/settings', { updates: { 'theme.mode': themeMode.value } }) } catch { /* ignore */ }
}

async function saveTranslate() {
  try {
    await http.put('/settings', { updates: { 'translate.source': translateSource.value } })
    ElMessage.success('翻译源已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

async function changePassword() {
  if (!pw.old || pw.next.length < 8) return ElMessage.warning('新密码至少 8 位')
  if (pw.next !== pw.confirm) return ElMessage.warning('两次输入的新密码不一致')
  try {
    await http.put('/auth/password', { old_password: pw.old, new_password: pw.next })
    ElMessage.success('密码已修改，请重新登录')
    clearToken()
    setTimeout(() => router.push('/login'), 600)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

async function loadShares() {
  try {
    const r = await http.get<{ items: typeof shareItems.value }>('/share')
    shareItems.value = r.items
  } catch { /* ignore */ }
}

async function copyShare(s: { url: string }) {
  const link = `${locationOrigin}${s.url}`
  try {
    await navigator.clipboard.writeText(link)
    ElMessage.success('链接已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = link
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
    ElMessage.success('链接已复制')
  }
}

async function revokeShare(s: { token: string }) {
  try {
    await http.del(`/share/${s.token}`)
    ElMessage.success('已撤销')
    loadShares()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '撤销失败')
  }
}

async function loadAll() {
  try {
    const cfg = await http.get<Record<string, any>>('/settings')
    siteName.value = cfg['site.name'] || 'Kruskal'
    siteSlogan.value = cfg['site.slogan'] || ''
    const s = await http.get<{ sources: any[]; default: string }>('/translate/sources')
    translateSources.value = s.sources
    translateSource.value = cfg['translate.source'] || s.default
    loadShares()
  } catch { /* 401 会跳登录 */ }
}

onMounted(() => {
  applyTheme(themeMode.value)
  loadAll()
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.card { padding: 20px 24px; margin-bottom: 16px; max-width: 900px; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.hint { color: var(--txt2); font-size: 12.5px; line-height: 1.8; margin: 10px 0 14px; }
.hint code { background: rgba(139, 92, 246, 0.12); padding: 1px 6px; border-radius: 6px; }

.src-list { display: grid; gap: 8px; margin-bottom: 14px; }
.src {
  display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px;
  border-radius: 12px; border: 1.5px solid rgba(148, 163, 184, 0.25); cursor: pointer; transition: all .15s;
}
.src.active { border-color: var(--acc2); background: rgba(167, 139, 250, 0.08); }
.src input { margin-top: 4px; accent-color: var(--acc2); }
.src-name { font-weight: 600; font-size: 14px; display: flex; gap: 8px; align-items: center; }
.src-note { color: var(--txt2); font-size: 12px; margin-top: 2px; }

.preset-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.preset-lab { font-size: 13px; color: var(--txt3); }
.preset { cursor: pointer; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0 14px; }

.prov-table { margin-top: 8px; display: grid; gap: 8px; }
.prov-row {
  display: flex; align-items: center; gap: 12px; padding: 10px 14px;
  background: rgba(167, 139, 250, 0.07); border-radius: 12px;
}
.prov-info { flex: 1; min-width: 0; }
.prov-name { font-weight: 600; font-size: 14px; }
.prov-sub { color: var(--txt2); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pw-form { max-width: 720px; }
.mc-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.hint.inline { margin: 0; }
.mc-lines { max-width: 520px; }
.share-list { display: grid; gap: 8px; }
.share-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 10px; background: rgba(148, 163, 184, 0.08); }
.sr-main { flex: 1; min-width: 0; }
.sr-title { font-weight: 600; font-size: 13.5px; display: flex; gap: 8px; align-items: center; }
.sr-sub { color: var(--txt2); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
