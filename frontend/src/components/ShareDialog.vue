<template>
  <span>
    <el-button :type="type" :plain="plain" :size="size" @click="open">
      <el-icon style="margin-right:4px"><Share /></el-icon>{{ buttonText }}
    </el-button>
    <el-dialog v-model="visible" :title="dialogTitle" width="480px">
      <div v-if="loading" class="hint">读取分享状态…</div>
      <template v-else>
        <div v-if="cur" class="share-box">
          <div class="sb-head">
            <el-input v-model="link" readonly>
              <template #append>
                <el-button @click="copy">复制</el-button>
              </template>
            </el-input>
          </div>
          <div class="sb-meta">已生成于 {{ cur.created }} · 内容更新后请点「刷新快照」</div>
          <div class="sb-ops">
            <el-button type="primary" size="small" :loading="busy" @click="publish">刷新快照</el-button>
            <el-button type="danger" plain size="small" :loading="busy" @click="revoke">撤销分享</el-button>
          </div>
        </div>
        <div v-else class="share-empty">
          <p>还没生成分享链接。生成后任何人打开链接都能看到这份内容的只读快照（无需登录）。</p>
          <el-button type="primary" :loading="busy" @click="publish">生成分享链接</el-button>
        </div>
        <p class="share-tip">提示：链接使用当前访问地址生成。若本机只能通过 SSH 隧道访问，对方打不开——对外可达后再把链接发出去即可。</p>
      </template>
    </el-dialog>
  </span>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Share } from '@element-plus/icons-vue'
import { http } from '../api/client'

const props = withDefaults(
  defineProps<{
    target: 'note' | 'me'
    ref: string
    buttonText?: string
    type?: 'primary' | 'default' | 'danger' | 'success' | 'warning'
    plain?: boolean
    size?: 'large' | 'default' | 'small'
  }>(),
  { buttonText: '分享', type: 'primary', plain: false, size: 'default' },
)

interface ShareItem { token: string; target: string; ref: string; title: string; url: string; created: string; updated: string }

const visible = ref(false)
const loading = ref(false)
const busy = ref(false)
const cur = ref<ShareItem | null>(null)
const link = ref('')

const dialogTitle = computed(() => `分享${props.target === 'me' ? '个人主页' : '这篇博客'}`)

async function load() {
  loading.value = true
  try {
    const r = await http.get<{ items: ShareItem[] }>('/share')
    cur.value = r.items.find((x) => x.target === props.target && x.ref === props.ref) || null
    link.value = cur.value ? `${location.origin}${cur.value.url}` : ''
  } finally {
    loading.value = false
  }
}

async function publish() {
  busy.value = true
  try {
    const r = await http.post<ShareItem>('/share', { target: props.target, ref: props.ref })
    cur.value = r
    link.value = `${location.origin}${r.url}`
    ElMessage.success('分享已生成')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    busy.value = false
  }
}

async function revoke() {
  if (!cur.value) return
  busy.value = true
  try {
    await http.del(`/share/${cur.value.token}`)
    cur.value = null
    link.value = ''
    ElMessage.success('已撤销，链接已失效')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '撤销失败')
  } finally {
    busy.value = false
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(link.value)
    ElMessage.success('链接已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = link.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
    ElMessage.success('链接已复制')
  }
}

function open() {
  visible.value = true
  load()
}

onMounted(() => { /* noop */ })
</script>

<style scoped>
.hint { color: var(--txt2); padding: 20px 0; }
.share-empty { padding: 6px 0 14px; }
.share-empty p { color: var(--txt2); font-size: 13px; margin: 0 0 14px; }
.share-tip { color: var(--txt3); font-size: 12px; margin-top: 16px; line-height: 1.8; }
.sb-head { display: flex; gap: 8px; }
.sb-meta { color: var(--txt2); font-size: 12px; margin: 10px 0; }
.sb-ops { display: flex; gap: 10px; }
</style>
