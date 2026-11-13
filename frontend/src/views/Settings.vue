<template>
  <div class="page">
    <div class="head">
      <div>
        <div class="page-title">设置</div>
        <div class="page-sub">翻译源 / 站点 / 存储 —— 配置实时保存到后端</div>
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
      <p class="hint">快照机制：内容更新后请在分享弹窗点「刷新快照」；撤销后链接立即失效。链接只在本机打开时可用（本应用不对外提供服务）。</p>
    </section>

    <!-- 存储与附件管理 (Asset Garbage Collector) -->
    <section class="glass card asset-card">
      <AssetManager />
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

    <!-- AI 模型服务管理 -->
    <section class="glass card ai-manage-card">
      <div class="card-title">
        <el-icon><Cpu /></el-icon>
        <span>AI 模型服务配置</span>
        <el-tag v-if="aiEnabled" type="success" size="small" effect="plain" style="margin-left:auto">服务已开启</el-tag>
        <el-tag v-else type="info" size="small" effect="plain" style="margin-left:auto">服务已关闭</el-tag>
      </div>

      <!-- 总开关 -->
      <div class="ai-master-row">
        <el-switch v-model="aiEnabled" @change="saveAiConfig(false)" />
        <span class="ai-master-text">
          <b>启用 AI 服务</b>（用于：助手智能提取、通知日程分析、稍后看卡片整理、周报起草等）
        </span>
      </div>

      <!-- 模型渠道切换与管理栏 -->
      <div class="ai-switcher-card">
        <div class="switcher-header">
          <div class="sw-left">
            <span class="sw-label">当前生效模型：</span>
            <el-select
              v-model="activeProfileId"
              placeholder="选择生效模型"
              style="width: 280px"
              @change="switchActiveProfile"
            >
              <el-option
                v-for="p in aiProfiles"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              >
                <div class="profile-option-item">
                  <span class="p-name">{{ p.name }}</span>
                  <el-tag size="small" type="info" style="font-size:11px; margin-left: 8px">{{ p.model || '未设模型' }}</el-tag>
                </div>
              </el-option>
            </el-select>
          </div>

          <div class="sw-right">
            <el-button
              type="primary"
              plain
              size="small"
              :loading="aiTesting"
              @click="testCurrentEdit"
            >
              <el-icon style="margin-right:4px"><Connection /></el-icon>
              测试当前连接
            </el-button>
            <el-button size="small" type="primary" @click="addNewProfile">
              <el-icon style="margin-right:4px"><Plus /></el-icon>
              添加新模型
            </el-button>
          </div>
        </div>

        <!-- 测试连通性结果反馈 -->
        <div v-if="aiTestResult" class="test-feedback-box" :class="{ ok: aiTestResult.ok }">
          <el-icon v-if="aiTestResult.ok" color="#10b981"><Check /></el-icon>
          <el-icon v-else color="#ef4444"><CloseBold /></el-icon>
          <div class="feedback-content">
            <span class="feedback-text">{{ aiTestResult.message }}</span>
            <div
              v-if="aiTestResult.available_models && aiTestResult.available_models.length > 0 && currentEdit.model !== aiTestResult.available_models[0]"
              class="feedback-action-row"
            >
              <span>服务端检测到可用模型：</span>
              <el-tag
                v-for="m in aiTestResult.available_models"
                :key="m"
                size="small"
                effect="plain"
                class="clickable-model-tag"
                @click="applyDiscoveredModel(m)"
              >
                点此填入 {{ m }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 渠道标签选项卡 -->
        <div class="profiles-tab-bar">
          <div
            v-for="p in aiProfiles"
            :key="p.id"
            class="profile-tab-chip"
            :class="{ active: editingProfileId === p.id, current: activeProfileId === p.id }"
            @click="selectProfileToEdit(p.id)"
          >
            <span class="chip-name">{{ p.name }}</span>
            <span v-if="activeProfileId === p.id" class="chip-active-badge">生效中</span>
            <span class="chip-model-sub">{{ p.model || '未配置模型' }}</span>
          </div>
        </div>

        <!-- 编辑面板 -->
        <div class="profile-editor-box">
          <div class="editor-header">
            <div class="ed-title">
              配置详情：<span>{{ currentEdit.name || '未命名配置' }}</span>
              <el-tag v-if="activeProfileId === currentEdit.id" type="success" size="small" style="margin-left:8px">当前生效</el-tag>
            </div>
            <div class="ed-actions">
              <el-button
                v-if="activeProfileId !== currentEdit.id"
                size="small"
                type="success"
                plain
                @click="switchActiveProfile(currentEdit.id)"
              >
                设为当前生效
              </el-button>
              <el-button size="small" text @click="duplicateProfile(currentEdit)">
                <el-icon><CopyDocument /></el-icon> 复制
              </el-button>
              <el-button
                size="small"
                text
                type="danger"
                :disabled="aiProfiles.length <= 1"
                @click="deleteProfile(currentEdit.id)"
              >
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </div>
          </div>

          <!-- 标准表单区：用户自由命名与填写模型信息 -->
          <el-form label-position="top" class="ai-editor-form" @submit.prevent>
            <!-- 配置名称 -->
            <div class="form-row-1">
              <el-form-item label="配置名称">
                <el-input
                  v-model="currentEdit.name"
                  placeholder="例如：我的大模型 / HPC 远程节点 / 个人云端"
                />
              </el-form-item>
            </div>

            <!-- API 服务地址 Base URL -->
            <div class="form-row-1">
              <el-form-item label="API 服务地址 (Base URL / Endpoint)">
                <el-input
                  v-model="currentEdit.endpoint"
                  size="large"
                  clearable
                  placeholder="例如：http://127.0.0.1:11434/v1 或 https://api.your-domain.com/v1"
                >
                  <template #prefix>
                    <el-icon><Link /></el-icon>
                  </template>
                </el-input>
                <div class="field-hint">
                  <el-icon><Check /></el-icon>
                  <span>遵循标准 OpenAI 兼容协议。可直接粘贴网址（末尾 <code>/v1</code> 自动规范化补齐）。</span>
                </div>
              </el-form-item>
            </div>

            <!-- API 密钥 + 模型标识 -->
            <div class="form-row-2">
              <el-form-item label="API 密钥 (API Key)">
                <el-input
                  v-model="currentEdit.api_key"
                  type="password"
                  show-password
                  clearable
                  placeholder="如需密钥请填写，免密或本地服务可直接留空"
                >
                  <template #prefix>
                    <el-icon><Key /></el-icon>
                  </template>
                </el-input>
                <div class="field-hint-sub">本地或免密推理服务留空或保持 <code>unused</code> 即可。</div>
              </el-form-item>

              <el-form-item label="模型标识 (Model ID)">
                <div style="display:flex; gap:8px; width:100%; align-items:center;">
                  <el-select
                    v-model="currentEdit.model"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入模型名称，或点右侧「拉取模型」"
                    style="flex: 1"
                  >
                    <el-option
                      v-for="m in discoveredModels"
                      :key="m"
                      :label="m"
                      :value="m"
                    />
                  </el-select>
                  <el-button
                    size="default"
                    plain
                    type="primary"
                    :loading="discoveringModels"
                    title="从端点 /models 接口自动拉取当前加载的所有模型"
                    @click="discoverModels"
                  >
                    拉取模型
                  </el-button>
                </div>
                <div class="field-hint-sub">可直接键盘输入任何模型标识，或点「拉取模型」从服务实时识别已加载的模型。</div>
              </el-form-item>
            </div>

            <!-- 超时时间 + SSH 隧道命令 -->
            <div class="form-row-2">
              <el-form-item label="请求超时时间（秒）">
                <el-input-number v-model="currentEdit.timeout" :min="10" :max="600" style="width: 100%" />
              </el-form-item>

              <el-form-item label="SSH 端口转发隧道命令（可选备注）">
                <el-input
                  v-model="currentEdit.tunnel_hint"
                  placeholder="例如：ssh -N -L 11434:127.0.0.1:11434 user@remote-host"
                />
              </el-form-item>
            </div>
          </el-form>

          <div class="editor-footer">
            <el-button type="primary" @click="saveAiConfig(true)">
              保存并应用 AI 配置
            </el-button>
            <el-button :loading="aiTesting" @click="testCurrentEdit">
              测试此配置
            </el-button>
          </div>
        </div>
      </div>
      <p class="hint">
        提示：支持自由添加任意 OpenAI 兼容的模型服务。填写对应服务网址与 API Key，点击「拉取模型」即可快速完成配置。
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Cpu,
  Key,
  Plus,
  Delete,
  CopyDocument,
  Connection,
  Check,
  CloseBold
} from '@element-plus/icons-vue'
import { http } from '../api/client'
import { loadSite } from '../stores/site'
import AssetManager from '../components/AssetManager.vue'

interface AiProfile {
  id: string
  name: string
  provider: string
  endpoint: string
  model: string
  api_key: string
  timeout: number
  tunnel_hint: string
}

const DEFAULT_AI_PROFILES: AiProfile[] = [
  {
    id: 'default',
    name: 'Local Ollama (默认)',
    provider: 'ollama',
    endpoint: 'http://127.0.0.1:11434/v1',
    model: 'qwen2.5:7b',
    api_key: '',
    timeout: 60,
    tunnel_hint: '',
  },
]

const siteName = ref('Kruskal')
const siteSlogan = ref('')
const translateSources = ref<{ id: string; name: string; note: string; need_key: boolean }[]>([])
const translateSource = ref('youdao-dict')
const locationOrigin = window.location.origin
const shareItems = ref<{ token: string; target: string; ref: string; title: string; url: string; created: string }[]>([])

// AI 多模型与多 Key 管理状态
const aiEnabled = ref(true)
const aiProfiles = ref<AiProfile[]>([])
const activeProfileId = ref('default')
const editingProfileId = ref('default')
const currentEdit = reactive<AiProfile>({
  id: 'default',
  name: 'Local Ollama (默认)',
  provider: 'ollama',
  endpoint: 'http://127.0.0.1:11434/v1',
  model: 'qwen2.5:7b',
  api_key: '',
  timeout: 60,
  tunnel_hint: '',
})
const aiTesting = ref(false)
const aiTestResult = ref<{ ok: boolean; message: string; latency_ms?: number; available_models?: string[] } | null>(null)
const discoveredModels = ref<string[]>([])
const discoveringModels = ref(false)

async function discoverModels() {
  if (!currentEdit.endpoint) {
    ElMessage.warning('请先填写 API 服务地址 (Base URL)')
    return
  }
  discoveringModels.value = true
  try {
    const res = await http.post<{ ok: boolean; models: string[] }>('/ai/discover-models', {
      endpoint: currentEdit.endpoint,
      api_key: currentEdit.api_key,
    })
    if (res.ok && res.models.length > 0) {
      discoveredModels.value = res.models
      currentEdit.model = res.models[0]
      ElMessage.success(`拉取到 ${res.models.length} 个端点模型，已填入：${res.models[0]}`)
    } else {
      ElMessage.warning('未能从端点 /models 获取到模型列表，请确认服务地址或隧道状态')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '拉取模型失败')
  } finally {
    discoveringModels.value = false
  }
}

function applyDiscoveredModel(m: string) {
  currentEdit.model = m
  ElMessage.success(`已应用模型名称：${m}`)
}

async function saveSite() {
  try {
    await http.put('/settings', { updates: { 'site.name': siteName.value, 'site.slogan': siteSlogan.value } })
    await loadSite(true)
    ElMessage.success('站点信息已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

async function saveTranslate() {
  try {
    await http.put('/settings', { updates: { 'translate.source': translateSource.value } })
    ElMessage.success('翻译源已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

// 选中某个 profile 进入编辑区
function selectProfileToEdit(id: string) {
  editingProfileId.value = id
  aiTestResult.value = null
  const target = aiProfiles.value.find((p) => p.id === id)
  if (target) {
    Object.assign(currentEdit, target)
  }
}

// 切换当前全局生效的模型
async function switchActiveProfile(id: string) {
  activeProfileId.value = id
  selectProfileToEdit(id)
  await saveAiConfig(false)
  ElMessage.success(`已切换生效模型为：${currentEdit.name}`)
}

// 新增模型
function addNewProfile() {
  const newId = `profile-${Date.now().toString(36)}`
  const newProfile: AiProfile = {
    id: newId,
    name: `模型配置 ${aiProfiles.value.length + 1}`,
    provider: 'openai',
    endpoint: '',
    model: '',
    api_key: '',
    timeout: 60,
    tunnel_hint: '',
  }
  aiProfiles.value.push(newProfile)
  selectProfileToEdit(newId)
  saveAiConfig(false)
}

// 复制新建
function duplicateProfile(p: AiProfile) {
  const newId = `profile-${Date.now().toString(36)}`
  const cloned: AiProfile = {
    ...p,
    id: newId,
    name: `${p.name} (副本)`,
  }
  aiProfiles.value.push(cloned)
  selectProfileToEdit(newId)
  saveAiConfig(false)
  ElMessage.success(`已复制为：${cloned.name}`)
}

// 删除模型
async function deleteProfile(id: string) {
  if (aiProfiles.value.length <= 1) {
    ElMessage.warning('至少需要保留一个模型配置')
    return
  }
  try {
    await ElMessageBox.confirm('确定要删除这个模型配置吗？', '删除配置', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  aiProfiles.value = aiProfiles.value.filter((p) => p.id !== id)
  if (activeProfileId.value === id) {
    activeProfileId.value = aiProfiles.value[0].id
  }
  selectProfileToEdit(activeProfileId.value)
  await saveAiConfig(false)
  ElMessage.success('已删除该模型配置')
}

// 保存所有配置到后端数据库
async function saveAiConfig(notify = true) {
  // 同步当前正在编辑的内容回数组
  const idx = aiProfiles.value.findIndex((p) => p.id === editingProfileId.value)
  if (idx !== -1) {
    aiProfiles.value[idx] = { ...currentEdit }
  }

  const active = aiProfiles.value.find((p) => p.id === activeProfileId.value) || aiProfiles.value[0] || currentEdit

  try {
    await http.put('/settings', {
      updates: {
        'ai.enabled': aiEnabled.value,
        'ai.active_profile_id': activeProfileId.value,
        'ai.profiles': aiProfiles.value,
        // 兼容单键模式，供直接读取
        'ai.provider': active.provider,
        'ai.endpoint': active.endpoint,
        'ai.model': active.model,
        'ai.api_key': active.api_key,
        'ai.timeout': Math.max(10, active.timeout || 120),
        'ai.tunnel_hint': active.tunnel_hint,
      },
    })
    if (notify) {
      ElMessage.success(`AI 配置已保存！当前生效：${active.name}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

// 测试当前编辑面板中的模型连接
async function testCurrentEdit() {
  aiTesting.value = true
  aiTestResult.value = null

  // 同步一次当前编辑
  const idx = aiProfiles.value.findIndex((p) => p.id === editingProfileId.value)
  if (idx !== -1) {
    aiProfiles.value[idx] = { ...currentEdit }
  }

  const payload = {
    provider: currentEdit.provider,
    endpoint: currentEdit.endpoint,
    model: currentEdit.model,
    api_key: currentEdit.api_key,
    timeout: currentEdit.timeout,
    tunnel_hint: currentEdit.tunnel_hint,
    name: currentEdit.name,
  }

  try {
    const res = await http.post<{
      ok: boolean
      latency_ms: number
      model: string
      provider: string
      endpoint: string
      available_models?: string[]
      reason: string
    }>('/ai/test', payload)

    if (res.available_models && res.available_models.length > 0) {
      discoveredModels.value = res.available_models
    }

    if (res.ok) {
      let msg = `连通成功！模型已就绪，响应延迟: ${res.latency_ms}ms`
      if (!aiEnabled.value) {
        msg += '（⚠️ 请注意：上方「启用 AI 服务」总开关当前已关闭，保存前请开启开关）'
      }
      aiTestResult.value = {
        ok: true,
        message: msg,
        latency_ms: res.latency_ms,
        available_models: res.available_models,
      }
    } else {
      aiTestResult.value = {
        ok: false,
        message: res.reason || '无法连接到模型端点，请检查服务或隧道状态',
        available_models: res.available_models,
      }
    }
  } catch (err: any) {
    aiTestResult.value = {
      ok: false,
      message: err?.response?.data?.detail || err?.message || '测试请求异常，请检查网络或后端服务',
    }
  } finally {
    aiTesting.value = false
  }
}

// 加载 AI 配置
function loadAiSettings(cfg: Record<string, any>) {
  aiEnabled.value = cfg['ai.enabled'] === undefined ? true : Boolean(cfg['ai.enabled'])

  let profiles: AiProfile[] = []
  if (Array.isArray(cfg['ai.profiles']) && cfg['ai.profiles'].length > 0) {
    profiles = cfg['ai.profiles'].map((p: any) => ({
      id: String(p.id || `p-${Math.random()}`),
      name: String(p.name || '未命名配置'),
      provider: 'openai',
      endpoint: String(p.endpoint || ''),
      model: String(p.model || ''),
      api_key: String(p.api_key || ''),
      timeout: Number(p.timeout || 60),
      tunnel_hint: String(p.tunnel_hint || ''),
    }))
  } else {
    profiles = DEFAULT_AI_PROFILES.map((p) => ({ ...p }))
    const savedEp = cfg['ai.endpoint']
    const savedModel = cfg['ai.model']
    if (savedEp) profiles[0].endpoint = savedEp
    if (savedModel) profiles[0].model = savedModel
    if (cfg['ai.api_key']) profiles[0].api_key = String(cfg['ai.api_key'])
    if (cfg['ai.timeout']) profiles[0].timeout = Number(cfg['ai.timeout'])
    if (cfg['ai.tunnel_hint']) profiles[0].tunnel_hint = String(cfg['ai.tunnel_hint'])
  }

  aiProfiles.value = profiles
  const savedActive = String(cfg['ai.active_profile_id'] || '')
  if (profiles.some((p) => p.id === savedActive)) {
    activeProfileId.value = savedActive
  } else {
    activeProfileId.value = profiles[0].id
  }
  selectProfileToEdit(activeProfileId.value)
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
    loadAiSettings(cfg)
    loadShares()
  } catch { /* 会话失效时由 client 统一恢复 */ }
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.card { padding: 20px 24px; margin-bottom: 16px; max-width: 900px; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.hint { color: var(--txt2); font-size: 12.5px; line-height: 1.8; margin: 10px 0 14px; }
.hint code { background: rgba(139, 92, 246, 0.12); padding: 1px 6px; border-radius: 6px; }

.ai-manage-card { max-width: 900px; }
.ai-master-row {
  display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  background: rgba(139, 92, 246, 0.08); border-radius: 12px; margin-bottom: 16px;
}
.ai-master-text { font-size: 13.5px; color: var(--txt); }

.ai-switcher-card {
  border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 14px;
  padding: 16px; background: rgba(255, 255, 255, 0.02); margin-bottom: 14px;
}
.switcher-header {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 12px; padding-bottom: 14px;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.2);
}
.sw-left { display: flex; align-items: center; gap: 10px; }
.sw-right { display: flex; align-items: center; gap: 8px; }
.sw-label { font-size: 13.5px; font-weight: 600; color: var(--txt); }
.profile-option-item { display: flex; justify-content: space-between; align-items: center; width: 100%; }

.test-feedback-box {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; margin: 12px 0;
  border-radius: 10px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25);
  font-size: 13px; color: #ef4444; word-break: break-all;
}
.test-feedback-box.ok {
  background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.25); color: #10b981;
}
.feedback-content { display: flex; flex-direction: column; gap: 6px; }
.feedback-action-row { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-top: 2px; }
.clickable-model-tag { cursor: pointer; transition: transform 0.15s ease; }
.clickable-model-tag:hover { transform: scale(1.03); }

.profiles-tab-bar { display: flex; gap: 8px; overflow-x: auto; padding: 12px 0 10px; }
.profile-tab-chip {
  display: flex; flex-direction: column; padding: 8px 14px; border-radius: 10px;
  border: 1.5px solid rgba(148, 163, 184, 0.2); background: rgba(0, 0, 0, 0.15);
  cursor: pointer; transition: all 0.2s ease; min-width: 140px;
}
.profile-tab-chip:hover { border-color: var(--acc2); }
.profile-tab-chip.active { border-color: var(--acc); background: rgba(139, 92, 246, 0.15); }
.chip-name { font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.chip-active-badge {
  font-size: 10px; background: #10b981; color: #fff; padding: 1px 5px;
  border-radius: 4px; display: inline-block; margin-top: 2px; width: fit-content;
}
.chip-model-sub {
  font-size: 11px; color: var(--txt3); margin-top: 2px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.profile-editor-box { margin-top: 14px; padding: 18px 20px; background: rgba(0, 0, 0, 0.25); border-radius: 12px; border: 1px solid rgba(148, 163, 184, 0.15); }
.editor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 8px; }
.ed-title { font-weight: 700; font-size: 14px; display: flex; align-items: center; }
.ed-actions { display: flex; align-items: center; gap: 6px; }

.ai-editor-form {
  margin-top: 10px;
}
.form-row-1 {
  width: 100%;
  margin-bottom: 4px;
}
.form-row-1 :deep(.el-form-item) {
  width: 100%;
  margin-bottom: 14px;
}
.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 4px;
}
.form-row-2 :deep(.el-form-item) {
  margin-bottom: 14px;
}
@media (max-width: 640px) {
  .form-row-2 {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
.field-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--txt3);
  margin-top: 6px;
  line-height: 1.4;
}
.field-hint code {
  background: rgba(139, 92, 246, 0.15);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--txt);
}
.field-hint-sub {
  font-size: 11.5px;
  color: var(--txt3);
  margin-top: 4px;
}
.field-hint-sub code {
  background: rgba(139, 92, 246, 0.12);
  padding: 1px 4px;
  border-radius: 4px;
}

.editor-footer { display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; }

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
.mc-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.hint.inline { margin: 0; }
.mc-lines { max-width: 520px; }
.share-list { display: grid; gap: 8px; }
.share-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 10px; background: rgba(148, 163, 184, 0.08); }
.sr-main { flex: 1; min-width: 0; }
.sr-title { font-weight: 600; font-size: 13.5px; display: flex; gap: 8px; align-items: center; }
.sr-sub { color: var(--txt2); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
.ai-lab { font-size: 13px; }
.ai-test { font-size: 12.5px; color: #ef4444; }
.ai-test.ok { color: #10b981; }
.asset-card { max-width: 1040px; }
</style>
