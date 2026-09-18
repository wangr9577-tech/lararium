<template>
  <div class="vde">
    <!-- Vditor 挂载点：ir（即时渲染，Typora 式，不分屏） -->
    <div ref="hostEl" class="vde-host" />

    <!-- 引用其它文章：选一篇，在光标处插入站内链接 [标题](/notes/id) -->
    <el-dialog v-model="refOpen" title="引用其它文章" width="560px" @open="onRefOpen">
      <div class="mde-rf-tip">选择一篇文章，将在光标处插入站内引用链接（或包裹当前选中文字），阅读时点击即可跳转</div>
      <el-input v-model="refQ" placeholder="搜索标题 / 摘要 / 标签…" clearable>
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div class="mde-rf-list">
        <button v-for="n in refList" :key="n.id" type="button" class="mde-rf-item" @click="pickRef(n)">
          <span class="mde-rf-type">{{ typeLabel(n.type) }}</span>
          <span class="mde-rf-title">{{ n.title }}</span>
          <span v-if="n.summary" class="mde-rf-sum">{{ n.summary }}</span>
        </button>
        <div v-if="!refList.length" class="mde-rf-empty">没有可引用的文章</div>
      </div>
      <template #footer>
        <el-button @click="refOpen = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import Vditor from 'vditor'
import 'vditor/dist/index.css'
import { getToken, http } from '../api/client'
import { hydrateImages } from '../utils/media'

/**
 * 日记/博客正文编辑器（Vditor 即时渲染版）：
 * - ir 模式 = Typora 式「编辑区即时渲染」，不分屏；
 * - 内容仍是 Markdown 字符串，v-model 契约与原 MarkdownEditor 一致（Ctrl+S 触发 save 事件）；
 * - 图片上传复用现有 POST /api/notes/images，站内图片显示走 blob 鉴权（hydrateImages）；
 * - Vditor 运行时资源（lute/highlight/katex/i18n/emoji）走站内 /vditor 静态目录，不依赖外网 CDN。
 */
const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'save'): void }>()

const hostEl = ref<HTMLDivElement>()
let vd: Vditor | null = null
/** vditor 是否完成初始化（Lute 就绪、after 已回调）；此前的外部内容先挂起，after 时补写 */
let ready = false
/** vditor 异步初始化完成前收到的外部内容，after 时补写 */
let pendingExternal: string | null = null
let hydraTimer = 0
let themeMo: MutationObserver | null = null

const isDark = () => document.documentElement.classList.contains('theme-dark')

/* ---------------- 工具栏：贴近原 MarkdownEditor（H1~H3/粗斜删/行内码/代码块/公式/引用/列表/待办/分割/链接/引用文章/图片/表格） ---------------- */

const LINK_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>'
const MATH_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h4M4 12h6M8 4v14c0 2 1 3 3 3"/><path d="M13 12l3-3M19 12l-3-3" /></svg>'

interface RefNote { id: string; title: string; type: string; summary: string; tags: string[] }

/* ---------------- 引用其它文章（站内链接 [标题](/notes/id)，点选插入） ---------------- */
const refOpen = ref(false)
const refQ = ref('')
const refCandidates = ref<RefNote[]>([])

const refList = computed(() => {
  const q = refQ.value.trim().toLowerCase()
  return refCandidates.value.filter((n) => {
    if (!q) return true
    return `${n.title} ${n.summary} ${n.tags.join(' ')}`.toLowerCase().includes(q)
  })
})

function typeLabel(t: string) {
  return ({ blog: '博客', note: '学习笔记', project: '项目经历' } as Record<string, string>)[t] || t
}

/** 打开引用面板时按需加载文章列表（默认列表：普通博客/笔记） */
async function onRefOpen() {
  if (refCandidates.value.length) return
  try {
    const r = await http.get<{ items: RefNote[] }>('/notes?module=')
    refCandidates.value = r.items || []
  } catch { /* 401/423 忽略 */ }
}

/** 选中文章：光标处插入 [显示文字](/notes/id)；有选中文字则用选中文字 */
function pickRef(n: RefNote) {
  if (!vd) return
  const sel = vd.getSelection()?.trim() || ''
  const text = (sel || n.title).replace(/[[\]()]/g, '') || '文章'
  vd.insertValue(`[${text}](/notes/${n.id})`)
  refOpen.value = false
  vd.focus()
}

/**
 * 渲染结果里出现站内图片后把 <img src=/api/notes/images/..> 换成带鉴权的 blob URL
 * （img 无法带 Authorization header；幂等，debounce 合并输入高频触发）
 */
function queueHydrate() {
  window.clearTimeout(hydraTimer)
  hydraTimer = window.setTimeout(() => {
    if (vd) hydrateImages(vd.vditor.element)
    // 兜底：ir 渲染有异步节拍，图片元素可能稍后才挂进 DOM，1.5s 后再扫一次
    hydraTimer = window.setTimeout(() => {
      if (vd) hydrateImages(vd.vditor.element)
    }, 1500)
  }, 80)
}

/* ---------------- Vditor 初始化 ---------------- */

function initVditor() {
  if (!hostEl.value) return
  const tb = [
    'undo', 'redo', '|',
    'headings', 'bold', 'italic', 'strike', '|',
    'inline-code', 'code',
    { name: 'krs-math', icon: MATH_SVG, tip: '公式', prefix: '$', suffix: '$' },
    '|',
    'quote', 'list', 'ordered-list', 'check', 'line', '|',
    'link',
    { name: 'kruskal-ref', icon: LINK_SVG, tip: '引用其它文章', click: () => { refOpen.value = true } },
    'upload', 'table',
    '|', 'fullscreen',
  ]
  vd = new Vditor(hostEl.value, {
    value: props.modelValue,
    mode: 'ir', // 即时渲染（类似 Typora），编辑区直接渲染，不分屏
    lang: 'zh_CN',
    theme: isDark() ? 'dark' : 'classic',
    icon: 'ant',
    cdn: '/vditor', // 本地静态资源，走站内服务，不依赖外网 CDN
    height: 'auto',
    minHeight: 420,
    placeholder: '写点什么…（Markdown 即时渲染，标题/加粗等直接呈现效果）',
    cache: { enable: false }, // 正文已由后端加密落盘，不做 localStorage 缓存
    counter: { enable: true, type: 'text' },
    preview: { math: { engine: 'KaTeX', inlineDigit: true } },
    hint: { emojiPath: '/vditor/images/emoji' },
    upload: {
      url: '/api/notes/images',
      fieldName: 'file',
      accept: 'image/*',
      max: 20 * 1024 * 1024, // 与后端一致 ≤20MB
      setHeaders: () => ({ Authorization: `Bearer ${getToken()}` }),
      format(files, responseText) {
        // 后端返回 {url, name} → 转为 Vditor 内置结构
        let parsed: { url?: string } = {}
        try { parsed = JSON.parse(responseText) } catch { /* ignore */ }
        const succMap: Record<string, string> = {}
        if (parsed.url) succMap[files[0]?.name || 'image.png'] = parsed.url
        return JSON.stringify({ msg: '', code: 0, data: { errFiles: [], succMap } })
      },
      error(msg) {
        if (msg) ElMessage.error(msg)
      },
    },
    toolbar: tb,
    toolbarConfig: { pin: true },
    after() {
      if (pendingExternal !== null && pendingExternal !== vd?.getValue()) {
        vd?.setValue(pendingExternal || '', true)
      }
      pendingExternal = null
      ready = true
      queueHydrate()
      vd?.focus()
    },
    input() {
      emit('update:modelValue', vd?.getValue() || '')
      queueHydrate()
    },
    keydown(e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault()
        emit('save')
      }
    },
  })
}

/* 站点明/暗主题切换 → 跟随切换 Vditor 主题 */
function applyTheme() {
  vd?.setTheme(isDark() ? 'dark' : 'classic', isDark() ? 'dark' : 'light')
}

onMounted(() => {
  initVditor()
  themeMo = new MutationObserver(applyTheme)
  themeMo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

/* 外部内容变化（切日期/清空）→ 覆盖编辑器内容并清撤销栈 */
watch(
  () => props.modelValue,
  (v) => {
    // 初始化完成前到达的外部内容挂起，after() 里补写（此时 setValue 会被 lute 未就绪的编辑器丢弃）
    if (!ready) { pendingExternal = v; return }
    if (!vd || v === vd.getValue()) return
    vd.setValue(v || '', true)
    queueHydrate()
  },
)

onBeforeUnmount(() => {
  window.clearTimeout(hydraTimer)
  themeMo?.disconnect()
  vd?.destroy()
  vd = null
})
</script>

<style scoped>
.vde { width: 100%; }
.vde-host { width: 100%; }

/* 与现有玻璃拟态主题对齐：圆角 + 半透明面板 */
.vde :deep(.vditor) {
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.35);
}
html.theme-dark .vde :deep(.vditor) {
  background: rgba(30, 41, 59, 0.28);
  border-color: rgba(148, 163, 184, 0.14);
}
.vde :deep(.vditor-toolbar) {
  border-top-left-radius: 14px;
  border-top-right-radius: 14px;
}
.vde :deep(.vditor-ir),
.vde :deep(.vditor-reset) {
  background: transparent;
}
.vde :deep(.vditor-reset img) { border-radius: 10px; }

/* 引用其它文章对话框（teleport 到 body，需非 scoped 样式） */
</style>

<style>
.mde-rf-tip { color: var(--txt2); font-size: 12px; margin: 2px 0 10px; }
.mde-rf-tip code { background: rgba(139, 92, 246, 0.12); padding: 0 5px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11.5px; }
.mde-rf-list { max-height: 44vh; overflow-y: auto; display: grid; gap: 6px; margin-top: 10px; }
.mde-rf-item {
  display: flex; align-items: baseline; gap: 8px; width: 100%; text-align: left;
  border: 1px solid rgba(148, 163, 184, 0.22); background: transparent; border-radius: 10px;
  padding: 8px 12px; cursor: pointer; font-family: inherit; color: var(--txt1);
  transition: border-color .15s, background .15s;
}
html.theme-dark .mde-rf-item { color: #cbd5e1; }
.mde-rf-item:hover { border-color: var(--acc2); background: rgba(139, 92, 246, 0.08); }
.mde-rf-type {
  flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: rgba(167, 139, 250, 0.14); color: var(--acc2);
}
.mde-rf-title { font-weight: 600; font-size: 13.5px; flex: none; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mde-rf-sum { color: var(--txt3); font-size: 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
html.theme-dark .mde-rf-sum { color: var(--txt2); }
.mde-rf-empty { color: var(--txt2); font-size: 13px; text-align: center; padding: 24px 0; }
</style>