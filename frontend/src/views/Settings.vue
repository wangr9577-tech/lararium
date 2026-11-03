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

    <!-- AI 本地与多模型服务管理 -->
    <section class="glass card ai-manage-card">
      <div class="card-title">
        <el-icon><Cpu /></el-icon>
        <span>AI 本地与多模型服务配置</span>
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
                  <el-tag size="small" type="info" style="font-size:11px; margin-left: 8px">{{ p.model }}</el-tag>
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
            <el-button size="small" @click="addNewProfile">
              <el-icon style="margin-right:4px"><Plus /></el-icon>
              新增模型
            </el-button>
          </div>
        </div>

        <!-- 测试连通性结果反馈 -->
        <div v-if="aiTestResult" class="test-feedback-box" :class="{ ok: aiTestResult.ok }">
          <el-icon v-if="aiTestResult.ok" color="#10b981"><Check /></el-icon>
          <el-icon v-else color="#ef4444"><CloseBold /></el-icon>
          <span class="feedback-text">
            {{ aiTestResult.ok ? `连接成功！响应延迟: ${aiTestResult.latency_ms}ms` : `连接失败：${aiTestResult.message}` }}
          </span>
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
            <span class="chip-model-sub">{{ p.model }}</span>
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

          <!-- 工业标准渠道快速预设 (类似 ccswitch / deepseek-harness) -->
          <div class="preset-quick-bar">
            <span class="preset-quick-title">标准渠道快速预设：</span>
            <div class="preset-chips">
              <span class="preset-chip" @click="applyPreset('deepseek')">
                <span class="preset-chip-dot ds"></span>DeepSeek 官方 API
              </span>
              <span class="preset-chip" @click="applyPreset('siliconflow')">
                <span class="preset-chip-dot sf"></span>SiliconFlow 硅基流动
              </span>
              <span class="preset-chip" @click="applyPreset('ollama')">
                <span class="preset-chip-dot ol"></span>Local Ollama (本地)
              </span>
              <span class="preset-chip" @click="applyPreset('vllm')">
                <span class="preset-chip-dot vl"></span>Local vLLM / LocalAI
              </span>
              <span class="preset-chip" @click="applyPreset('openai')">
                <span class="preset-chip-dot oa"></span>OpenAI 兼容
              </span>
            </div>
          </div>

          <!-- 标准表单区 -->
          <el-form label-position="top" class="ai-editor-form" @submit.prevent>
            <!-- Row 1: 显示名称 + 渠道类型 -->
            <div class="form-row-2">
              <el-form-item label="配置显示名称">
                <el-input v-model="currentEdit.name" placeholder="例如：DeepSeek 官方 API / Local Ollama" />
              </el-form-item>

              <el-form-item label="渠道类型 / 提供商">
                <el-select v-model="currentEdit.provider" placeholder="选择渠道协议" style="width:100%">
                  <el-option label="openai (标准兼容格式)" value="openai" />
                  <el-option label="deepseek (深度求索 DeepSeek)" value="deepseek" />
                  <el-option label="ollama (本地 Ollama)" value="ollama" />
                  <el-option label="vllm (本地 vLLM)" value="vllm" />
                </el-select>
              </el-form-item>
            </div>

            <!-- Row 2: 服务地址 Base URL (独占整行，通栏大输入框，醒目无遮挡) -->
            <div class="form-row-1">
              <el-form-item label="API 服务地址 (Base URL / Endpoint)">
                <el-input
                  v-model="currentEdit.endpoint"
                  size="large"
                  clearable
                  placeholder="https://api.deepseek.com/v1 或 http://127.0.0.1:11434/v1"
                >
                  <template #prefix>
                    <el-icon><Link /></el-icon>
                  </template>
                </el-input>
                <div class="field-hint">
                  <el-icon><Check /></el-icon>
                  <span>遵循标准 OpenAI 兼容协议。可直接粘贴 Base URL（末尾 <code>/v1</code> 自动补齐，多余路径自动规范化）。</span>
                </div>
              </el-form-item>
            </div>

            <!-- Row 3: API 密钥 + 模型 ID -->
            <div class="form-row-2">
              <el-form-item label="API 密钥 (API Key)">
                <el-input
                  v-model="currentEdit.api_key"
                  type="password"
                  show-password
                  clearable
                  placeholder="云端服务填 sk-...，本地 Ollama 填 unused"
                >
                  <template #prefix>
                    <el-icon><Key /></el-icon>
                  </template>
                </el-input>
                <div class="field-hint-sub">本地 Ollama / vLLM 无需 key，保留 <code>unused</code> 即可。</div>
              </el-form-item>

              <el-form-item label="模型 ID (Model ID)">
                <el-select
                  v-model="currentEdit.model"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择常用推荐模型或直接键盘输入"
                  style="width: 100%"
                >
                  <el-option-group label="DeepSeek 官方推荐">
                    <el-option label="deepseek-chat (通用对话 / V3)" value="deepseek-chat" />
                    <el-option label="deepseek-reasoner (深度思考推理 / R1)" value="deepseek-reasoner" />
                  </el-option-group>
                  <el-option-group label="硅基流动 SiliconFlow 推荐">
                    <el-option label="deepseek-ai/DeepSeek-V3" value="deepseek-ai/DeepSeek-V3" />
                    <el-option label="deepseek-ai/DeepSeek-R1" value="deepseek-ai/DeepSeek-R1" />
                    <el-option label="Qwen/Qwen2.5-7B-Instruct" value="Qwen/Qwen2.5-7B-Instruct" />
                  </el-option-group>
                  <el-option-group label="本地 Ollama / vLLM 常用">
                    <el-option label="qwen2.5:7b" value="qwen2.5:7b" />
                    <el-option label="qwen2.5:14b" value="qwen2.5:14b" />
                    <el-option label="deepseek-r1:7b" value="deepseek-r1:7b" />
                    <el-option label="deepseek-r1:8b" value="deepseek-r1:8b" />
                    <el-option label="llama3.1:8b" value="llama3.1:8b" />
                  </el-option-group>
                  <el-option-group label="OpenAI 官方">
                    <el-option label="gpt-4o-mini" value="gpt-4o-mini" />
                    <el-option label="gpt-4o" value="gpt-4o" />
                  </el-option-group>
                </el-select>
                <div class="field-hint-sub">可直接键盘输入任何私有量化或部署的模型标识</div>
              </el-form-item>
            </div>

            <!-- Row 4: 超时时间 + SSH 隧道命令 -->
            <div class="form-row-2">
              <el-form-item label="超时时间（秒）">
                <el-input-number v-model="currentEdit.timeout" :min="10" :max="600" style="width: 100%" />
              </el-form-item>

              <el-form-item label="SSH 端口转发隧道命令（可选，远程服务器映射）">
                <el-input
                  v-model="currentEdit.tunnel_hint"
                  placeholder="例如：ssh -N -L 11434:localhost:11434 user@your-server"
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
            <el-button text @click="resetAllProfilesToDefault">
              重置为标准官方预设列表
            </el-button>
          </div>
        </div>
      </div>
      <p class="hint">
        提示：支持随时切换不同的模型服务。若使用本地 Ollama、vLLM 或云端 API，填写对应 Endpoint 与 API Key 即可。
      </p>
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

      <!-- 免密自动解锁：只免掉「每次重启都要输主密码」，加密本身不变 -->
      <div class="auto-row">
        <div class="mc-lines">
          <div class="src-name">本机免密解锁</div>
          <div class="src-note">
            开启后服务器重启、开机自启都不再要主密码（用本机密钥自动解开数据密钥）。
            关闭或点「一键上锁」即恢复必须输入主密码。
          </div>
        </div>
        <el-switch v-model="auto.enabled" @change="toggleAuto" />
      </div>
      <p class="hint">
        本机密钥存在 <code>{{ auto.keyPath || 'backend/.autokey' }}</code>，已 gitignore，且<b>不在备份包里</b>
        —— 拿到备份仍然解不开你的数据。它把防线从「主密码」降为「文件权限 + 备份口令」：
        仍挡住同机其他普通用户，<b>不挡</b> root 与恶意进程。换机器、重装、从备份还原仍需主密码。
      </p>
      <p v-if="auto.enabled && !auto.keyOutsideData" class="hint">
        ⚠️ 当前本机密钥落在数据目录内，会被 <code>deploy/backup.sh</code> 一起打包。
        建议设 <code>KRUSKAL_AUTOKEY</code> 指到数据目录之外。
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
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
import { http, clearToken } from '../api/client'
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
    id: 'local-ollama',
    name: 'Local Ollama (默认)',
    provider: 'ollama',
    endpoint: 'http://127.0.0.1:11434/v1',
    model: 'qwen2.5:7b',
    api_key: 'unused',
    timeout: 60,
    tunnel_hint: '',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek 官方 API',
    provider: 'deepseek',
    endpoint: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    api_key: '',
    timeout: 60,
    tunnel_hint: '',
  },
  {
    id: 'siliconflow',
    name: 'SiliconFlow 硅基流动',
    provider: 'openai',
    endpoint: 'https://api.siliconflow.cn/v1',
    model: 'deepseek-ai/DeepSeek-V3',
    api_key: '',
    timeout: 60,
    tunnel_hint: '',
  },
  {
    id: 'local-vllm',
    name: '本地 vLLM / LocalAI',
    provider: 'openai',
    endpoint: 'http://127.0.0.1:8000/v1',
    model: 'qwen2.5-7b-instruct',
    api_key: 'unused',
    timeout: 60,
    tunnel_hint: '',
  },
]

const router = useRouter()
const themeMode = ref(localStorage.getItem('krs_theme') || 'dark')
const siteName = ref('Kruskal')
const siteSlogan = ref('')
const translateSources = ref<{ id: string; name: string; note: string; need_key: boolean }[]>([])
const translateSource = ref('youdao-dict')
const pw = reactive({ old: '', next: '', confirm: '' })
const auto = reactive({ enabled: false, keyOutsideData: true, keyPath: '' })
const locationOrigin = window.location.origin
const shareItems = ref<{ token: string; target: string; ref: string; title: string; url: string; created: string }[]>([])

// AI 多模型与多 Key 管理状态
const aiEnabled = ref(true)
const aiProfiles = ref<AiProfile[]>([])
const activeProfileId = ref('local-ollama')
const editingProfileId = ref('local-ollama')
const currentEdit = reactive<AiProfile>({
  id: 'local-ollama',
  name: 'Local Ollama (默认)',
  provider: 'ollama',
  endpoint: 'http://127.0.0.1:11434/v1',
  model: 'qwen2.5:7b',
  api_key: 'unused',
  timeout: 60,
  tunnel_hint: '',
})
const aiTesting = ref(false)
const aiTestResult = ref<{ ok: boolean; message: string; latency_ms?: number } | null>(null)

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
    name: `新模型配置 ${aiProfiles.value.length + 1}`,
    provider: 'openai',
    endpoint: 'http://127.0.0.1:11434/v1',
    model: 'qwen2.5:7b',
    api_key: 'unused',
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

// 应用预设配置
function applyPreset(type: string) {
  if (type === 'deepseek') {
    currentEdit.name = 'DeepSeek 官方 API'
    currentEdit.provider = 'deepseek'
    currentEdit.endpoint = 'https://api.deepseek.com/v1'
    currentEdit.model = 'deepseek-chat'
    if (currentEdit.api_key === 'unused') currentEdit.api_key = ''
    ElMessage.info('已应用 DeepSeek 官方预设，请填入你的 API Key')
  } else if (type === 'siliconflow') {
    currentEdit.name = 'SiliconFlow 硅基流动'
    currentEdit.provider = 'openai'
    currentEdit.endpoint = 'https://api.siliconflow.cn/v1'
    currentEdit.model = 'deepseek-ai/DeepSeek-V3'
    if (currentEdit.api_key === 'unused') currentEdit.api_key = ''
    ElMessage.info('已应用硅基流动预设，请填入你的 API Key')
  } else if (type === 'ollama') {
    currentEdit.name = 'Local Ollama (本地)'
    currentEdit.provider = 'ollama'
    currentEdit.endpoint = 'http://127.0.0.1:11434/v1'
    currentEdit.model = 'qwen2.5:7b'
    currentEdit.api_key = 'unused'
    ElMessage.info('已应用本地 Ollama 预设')
  } else if (type === 'vllm') {
    currentEdit.name = '本地 vLLM / LocalAI'
    currentEdit.provider = 'openai'
    currentEdit.endpoint = 'http://127.0.0.1:8000/v1'
    currentEdit.model = 'qwen2.5-7b-instruct'
    currentEdit.api_key = 'unused'
    ElMessage.info('已应用本地 vLLM 预设')
  } else if (type === 'openai') {
    currentEdit.name = 'OpenAI 兼容'
    currentEdit.provider = 'openai'
    currentEdit.endpoint = 'https://api.openai.com/v1'
    currentEdit.model = 'gpt-4o-mini'
    if (currentEdit.api_key === 'unused') currentEdit.api_key = ''
    ElMessage.info('已应用 OpenAI 预设，请填入你的 API Key')
  }
}

// 恢复为默认 Ollama 配置
function resetToDefaultOllama() {
  applyPreset('ollama')
  saveAiConfig(true)
}

// 重置所有渠道为官方标准预设列表
async function resetAllProfilesToDefault() {
  try {
    await ElMessageBox.confirm('确定要将所有模型配置重置为官方标准列表（包含 DeepSeek、Ollama、SiliconFlow 等）吗？现有自定义配置将被覆盖。', '重置确认', {
      type: 'warning',
      confirmButtonText: '确定重置',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  aiProfiles.value = DEFAULT_AI_PROFILES.map((p) => ({ ...p }))
  activeProfileId.value = DEFAULT_AI_PROFILES[0].id
  selectProfileToEdit(DEFAULT_AI_PROFILES[0].id)
  await saveAiConfig(false)
  ElMessage.success('已重置为官方标准预设列表')
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
      reason: string
    }>('/ai/test', payload)

    if (res.ok) {
      aiTestResult.value = {
        ok: true,
        message: `连通成功！模型已就绪，响应延迟: ${res.latency_ms}ms`,
        latency_ms: res.latency_ms,
      }
    } else {
      aiTestResult.value = {
        ok: false,
        message: res.reason || '无法连接到模型端点，请检查服务或隧道状态',
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
      provider: String(p.provider || 'openai'),
      endpoint: String(p.endpoint || 'http://127.0.0.1:11434/v1'),
      model: String(p.model || 'qwen2.5:7b'),
      api_key: String(p.api_key || 'unused'),
      timeout: Number(p.timeout || 60),
      tunnel_hint: String(p.tunnel_hint || ''),
    }))
  } else {
    profiles = DEFAULT_AI_PROFILES.map((p) => ({ ...p }))
    // 若历史有单键保存项且非默认占位符，予以合并
    const savedEp = cfg['ai.endpoint']
    const savedModel = cfg['ai.model']
    if (savedEp && savedEp !== 'http://127.0.0.1:8000/v1') {
      profiles[0].endpoint = savedEp
    }
    if (savedModel && savedModel !== 'qwen3.8-27b') {
      profiles[0].model = savedModel
    }
    if (cfg['ai.api_key']) profiles[0].api_key = String(cfg['ai.api_key'])
    if (cfg['ai.provider']) profiles[0].provider = String(cfg['ai.provider'])
    if (cfg['ai.timeout']) profiles[0].timeout = Number(cfg['ai.timeout'])
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

async function loadAuto() {
  try {
    const r = await http.get<{ enabled: boolean; key_outside_data: boolean; key_path: string }>('/auth/auto-unlock')
    auto.enabled = r.enabled
    auto.keyOutsideData = r.key_outside_data
    auto.keyPath = r.key_path
  } catch { /* 401 会跳登录 */ }
}

async function toggleAuto(v: any) {
  const on = !!v
  if (!on) {
    try {
      await http.del('/auth/auto-unlock')
      auto.enabled = false
      ElMessage.success('已关闭：下次重启需要输入主密码')
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '关闭失败')
      loadAuto()
    }
    return
  }
  let pwd = ''
  try {
    const r = await ElMessageBox.prompt(
      '输入当前主密码确认。它只用于在本机生成一份解锁密钥（加密你的数据密钥），不会上传到任何地方。',
      '开启本机免密解锁',
      { inputType: 'password', confirmButtonText: '开启', cancelButtonText: '取消',
        inputValidator: (x: string) => (!!x ? true : '请输入主密码') },
    )
    pwd = String(r.value || '')
  } catch {
    loadAuto()   // 取消：开关回到真实状态
    return
  }
  try {
    const r = await http.post<{ key_outside_data: boolean; key_path: string }>('/auth/auto-unlock', { password: pwd })
    auto.enabled = true
    auto.keyOutsideData = r.key_outside_data
    auto.keyPath = r.key_path
    ElMessage.success('已开启：服务器重启后不再需要输入主密码')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '开启失败')
    loadAuto()
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
    loadAiSettings(cfg)
    loadShares()
    loadAuto()
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
  display: flex; align-items: center; gap: 8px; padding: 10px 14px; margin: 12px 0;
  border-radius: 10px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25);
  font-size: 13px; color: #ef4444; word-break: break-all;
}
.test-feedback-box.ok {
  background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.25); color: #10b981;
}

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

.preset-quick-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(139, 92, 246, 0.08);
  border: 1px dashed rgba(139, 92, 246, 0.25);
  border-radius: 10px;
  margin-bottom: 16px;
}
.preset-quick-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--txt2);
}
.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.preset-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  font-size: 12px;
  color: var(--txt);
  cursor: pointer;
  user-select: none;
  transition: all 0.2s ease;
}
.preset-chip:hover {
  background: rgba(139, 92, 246, 0.2);
  border-color: var(--acc2);
  transform: translateY(-1px);
}
.preset-chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.preset-chip-dot.ds { background: #0ea5e9; }
.preset-chip-dot.sf { background: #8b5cf6; }
.preset-chip-dot.ol { background: #10b981; }
.preset-chip-dot.vl { background: #f59e0b; }
.preset-chip-dot.oa { background: #10b981; }

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
.pw-form { max-width: 720px; }
.mc-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.auto-row { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
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
