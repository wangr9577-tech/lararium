<template>
  <div
    class="vde"
    @dragenter.capture="onDragEnter"
    @dragover.capture="onDragOver"
    @dragleave.capture="onDragLeave"
    @drop.capture="onDrop"
    @paste.capture="onPaste"
  >
    <!-- Vditor 挂载点：ir（即时渲染，Typora 式，不分屏） -->
    <div ref="hostEl" class="vde-host" />
    <div v-if="dragging" class="vde-drop"><span>松开即插入图片</span></div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import Vditor from 'vditor'
import 'vditor/dist/index.css'
import { getToken, http } from '../api/client'
import { hydrateImages } from '../utils/media'

/**
 * 日记正文编辑器（Vditor 即时渲染版，无工具栏）：
 * - ir 模式 = Typora 式「编辑区即时渲染」，不分屏；
 * - 隐藏工具栏（用户要求）：粗体/标题/公式等用快捷键或直接输入 Markdown；
 * - 粘贴图片仍可上传（走 upload 配置），快捷键 Ctrl+S 触发 save 事件；
 * - 段首缩进保护：粘贴含行首缩进的纯文本、或在段首敲空格时，缩进字符换成 U+2002
 *   （Lute/HTML/pandoc 都会把行首半角空格当可折叠空白抹掉，详见下方 protectLeadingIndent 注释）；
 * - 列表标记修复：段首空格缩进后再打 `*` 时把 U+2002 还原成半角空格，保证列表真的渲染出来；
 * - 列表项 Tab 缩进：光标在列表项内任意位置按 Tab 都能缩进，且不让焦点移出编辑器；
 * - Vditor 运行时资源（lute/highlight/katex/i18n/emoji）走站内 /vditor 静态目录，不依赖外网 CDN。
 */
const props = withDefaults(defineProps<{
  modelValue: string
  /** 占位文案（缺省=通用「写点什么…」） */
  placeholder?: string
  /** 编辑器最小高度（px，缺省 420） */
  minHeight?: number
  /** 初始化后是否自动聚焦（默认 true，多开时建议传 false 避免抢焦点） */
  autoFocus?: boolean
}>(), {
  autoFocus: true,
})
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'save'): void }>()

const router = useRouter()

const hostEl = ref<HTMLDivElement>()
let vd: Vditor | null = null
/** vditor 是否完成初始化（Lute 就绪、after 已回调）；此前的外部内容先挂起，after 时补写 */
let ready = false
/** vditor 异步初始化完成前收到的外部内容，after 时补写 */
let pendingExternal: string | null = null
let hydraTimer = 0
let themeMo: MutationObserver | null = null

const isDark = () => document.documentElement.classList.contains('theme-dark')

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

/**
 * 补 hydrate：Vditor 异步重渲染会让 <img src=/api/notes/images/..>（未鉴权）随时重新挂进
 * DOM，仅靠 queueHydrate 的定时兜底追不上 → 监听编辑区 DOM，新增站内图片元素立即补换 blob URL。
 * hydrate 回写的是 blob: src，不满足下面判定，不会形成观察→回写→再观察的环。
 */
const INTERNAL_IMG_SEL = 'img[src^="/api/notes/images/"]'
let imgMo: MutationObserver | null = null
let imgMoTimer = 0
function nodeHasInternalImg(n: Node): boolean {
  if (n.nodeType !== 1) return false
  const el = n as Element
  return el.matches?.(INTERNAL_IMG_SEL) || !!el.querySelector?.(INTERNAL_IMG_SEL)
}
function startImgObserver() {
  const root = vd?.vditor.element
  if (!root || imgMo) return
  imgMo = new MutationObserver((muts) => {
    for (const m of muts) {
      let dirty = false
      if (m.type === 'childList') {
        for (const n of m.addedNodes) { if (nodeHasInternalImg(n)) { dirty = true; break } }
      } else if (m.attributeName === 'src' && m.target instanceof HTMLImageElement) {
        dirty = (m.target.getAttribute('src') || '').startsWith('/api/notes/images/')
      }
      if (dirty) {
        window.clearTimeout(imgMoTimer)
        imgMoTimer = window.setTimeout(() => { if (vd) hydrateImages(vd.vditor.element) }, 100)
        return
      }
    }
  })
  imgMo.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] })
}

/* ---------------- 拖入 / 粘贴图片（自有上传，不依赖 vditor 内置拖放） ---------------- */
const dragging = ref(false)
const uploading = ref(false)
/** 拖拽进出计数：内容区有嵌套元素，只看 dragleave 会闪 */
let dragDepth = 0

/** 取拖拽/粘贴里的图片文件（非图片返回空数组，交回浏览器/Vditor 自己处理） */
function imageFilesFrom(dt: DataTransfer | null): File[] {
  if (!dt) return []
  return Array.from(dt.files || []).filter((f) => f.type.startsWith('image/'))
}

/** 拖拽里是否含文件（编辑器内选中文字拖拽不含 Files，必须放行给 vditor） */
function hasFiles(e: DragEvent): boolean {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')
}

function onDragEnter(e: DragEvent) {
  if (!hasFiles(e)) return
  dragDepth++
  dragging.value = true
}
function onDragOver(e: DragEvent) {
  if (!hasFiles(e)) return
  e.preventDefault() // 不 preventDefault 就不会触发 drop
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  dragging.value = true
}
function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}
function onDrop(e: DragEvent) {
  dragDepth = 0
  dragging.value = false
  if (!hasFiles(e)) return // 编辑器内文字拖拽：不动
  e.preventDefault()
  e.stopPropagation() // 捕获阶段拦住，避免 Vditor 内置 drop 再插一次
  const imgs = imageFilesFrom(e.dataTransfer)
  if (!imgs.length) {
    ElMessage.warning('仅支持图片（jpg / png / webp / gif）')
    return
  }
  uploadAndInsert(imgs)
}
function onPaste(e: ClipboardEvent) {
  const imgs = imageFilesFrom(e.clipboardData)
  if (imgs.length) {
    e.preventDefault()
    e.stopPropagation() // 避免与 Vditor 内置粘贴上传重复插入
    uploadAndInsert(imgs)
    return
  }
  // 纯文本粘贴：含段首缩进时接管（Vditor 走 Md2VditorIRDOM，段首半角空白会被 Lute 归一化掉，
  // 粘贴进去就没了）。无段首缩进 / 光标在代码块内 → 照旧交给 vditor（富文本粘贴不受影响）。
  if (caretInCodeBlock()) return
  const text = e.clipboardData?.getData('text/plain') || ''
  const fixed = protectLeadingIndent(text)
  if (!text || fixed === text) return
  e.preventDefault()
  e.stopPropagation()
  insertPlainText(fixed)
}

/* ---------------- 段首缩进保护：不让 Lute / HTML 吃掉行首空格 ---------------- */

/**
 * 「每行前面打空格」保护（用户 2026-10 需求，实证依据）：
 * Markdown 与 HTML 都把行首半角空格 / Tab 当可折叠空白 ——
 *  · Vditor(Lute) IR 下 setValue → getValue 一圈后段首空格已被抹平（实测 2/4 空格、Tab 全丢），
 *    而保存用的正是 getValue()，所以粘贴/手打的缩进都落不了盘；
 *  · 阅读页 markdown-it + 浏览器、PDF 导出的 pandoc 同样把段首半角空格折叠成看不见。
 * 做法：把「行首缩进」换成 U+2002（EN SPACE）——不是 ASCII 空白，上述三条链路都原样保留，
 * 视觉宽度≈半角空格，用户无感。语义缩进一律不动：围栏代码块内部、以及行首去掉缩进后
 * 是列表 / 引用 / 标题标记（- * + 1. > #）的行——那些缩进是 Markdown 语义，改了就破坏结构。
 */
const INDENT_CH = '\u2002'
const FENCE_RE = /^\s*(`{3,}|~{3,})/
const BLOCK_MARK_RE = /^(?:[-*+]\s|\d+[.)]\s|>|#{1,6}\s)/

/** 行首半角缩进 → U+2002（无变化时原样返回同一字符串，调用方据此判断是否接管） */
function protectLeadingIndent(src: string): string {
  if (!src) return src
  let inFence = false
  let fenceChar = ''
  let changed = false
  const out = src.split('\n').map((line) => {
    const fence = line.match(FENCE_RE)
    if (inFence) {
      if (fence && fence[1][0] === fenceChar) inFence = false
      return line
    }
    if (fence) {
      inFence = true
      fenceChar = fence[1][0]
      return line
    }
    const m = line.match(/^([ \t]+)(\S.*)$/) // 只处理「缩进 + 内容」的行；纯空白行不动
    if (!m) return line
    if (BLOCK_MARK_RE.test(m[2])) return line // 列表/引用/标题：缩进有语义，不动
    changed = true
    return m[1].replace(/\t/g, '    ').replace(/ /g, INDENT_CH) + m[2]
  })
  return changed ? out.join('\n') : src
}

/** 光标是否落在代码块内（IR 的代码块元素 data-type="code-block"）——代码里的空格不能动 */
function caretInCodeBlock(): boolean {
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount) return false
  const node = sel.getRangeAt(0).startContainer
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement
  return !!el?.closest('[data-type="code-block"]')
}

/** 光标是否位于「段首 / 软换行行首」（其前只有空白）；代码块内不算，行中间不算 */
function caretAtBlockStart(): boolean {
  const root = vd?.vditor.element
  const sel = window.getSelection()
  if (!root || !sel || !sel.rangeCount || !sel.isCollapsed) return false
  const caret = sel.getRangeAt(0)
  if (!root.contains(caret.startContainer)) return false
  const node = caret.startContainer
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement
  const block = el?.closest('[data-block], p, li, h1, h2, h3, h4, h5, h6, blockquote')
  if (!block || block.closest('[data-type="code-block"]')) return false
  try {
    const pre = document.createRange()
    pre.setStart(block, 0)
    pre.setEnd(node, caret.startOffset)
    const before = pre.toString()
    // 只看光标前的「本行」内容（IR 一个块里可有软换行，段首与软换行行首都算）
    return before.slice(before.lastIndexOf('\n') + 1).trim() === ''
  } catch {
    return false
  }
}

/** 在光标处插入纯文本（与 Vditor 自己处理纯文本粘贴同一条 md→IR DOM 通道） */
function insertPlainText(text: string) {
  if (!vd) return
  vd.focus()
  vd.insertMD(text)
  // 与 insertImage 同理：insertMD 不触发 input 回调，显式同步内容到父组件
  emit('update:modelValue', vd.getValue() || '')
  queueHydrate()
}

/** 段首按空格 → 插入 U+2002（否则 IR 下打完看不见、保存后丢失） */
function insertIndentSpace() {
  if (!vd) return
  vd.insertValue(INDENT_CH, true)
  emit('update:modelValue', vd.getValue() || '')
}

/* ---------------- 列表标记修复 / 列表项 Tab 缩进（2026-10 用户反馈） ---------------- */

/**
 * 列表标记修复（用户实测反馈：段首打空格缩进后，再打 `*` 不会渲染成列表）：
 * 段首空格被保护成 U+2002 后，行首就不再是 ASCII 空白 —— Markdown 不认这行是列表标记，
 * `*` 退化成普通字符。这里在每次输入后检查「光标所在块」的行首：
 * 一旦是「U+2002 × N + 列表标记（- * + 或 1.）」，就把这 N 个 U+2002 原地换回 N 个半角空格
 * （等长替换，光标偏移不受影响），再补发一次 input —— Vditor 的 input 管道会把该块按
 * Markdown 重渲染，这一行才真正变成列表项（实测：`* 一级A` + `　　* 二级B` → 真二级嵌套）。
 */
const MD_LIST_MARK_RE = /(^|\n)(\u2002+)(?=(?:[-*+]|\d+[.)])(?:\s|$))/
let repairing = false

function repairIndentList(): boolean {
  const root = vd?.vditor.element
  if (!root || repairing) return false
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount) return false
  const node = sel.getRangeAt(0).startContainer
  if (!root.contains(node)) return false
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement
  const block = el?.closest('[data-block], p, li')
  if (!block) return false
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  let textNode = walker.nextNode() as Text | null
  while (textNode) {
    const text = textNode.textContent || ''
    const m = text.match(MD_LIST_MARK_RE)
    if (m) {
      const start = m.index + m[1].length
      const len = m[2].length
      textNode.replaceData(start, len, ' '.repeat(len)) // 等长：光标偏移保持不变
      repairing = true
      try {
        root.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: ' ' }))
      } finally {
        repairing = false
      }
      return true
    }
    textNode = walker.nextNode() as Text | null
  }
  return false
}

/** 块内第一个非空文本节点（用于把光标落到「列表项开头」） */
function firstTextNode(el: Element): Text | null {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let n = walker.nextNode()
  while (n) {
    if ((n.textContent || '').length) return n as Text
    n = walker.nextNode()
  }
  return null
}

/** 光标所在的列表项（代码块 / 表格内不算） */
function caretListItem(): Element | null {
  const root = vd?.vditor.element
  const sel = window.getSelection()
  if (!root || !sel || !sel.rangeCount) return null
  const node = sel.getRangeAt(0).startContainer
  if (!root.contains(node)) return null
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement
  if (!el || el.closest('[data-type="code-block"], table')) return null
  return el.closest('li')
}

/** 设置光标（节点可能已被重渲染替换，失败就忽略） */
function setCaret(node: Node, offset: number) {
  try {
    const sel = window.getSelection()
    if (!sel) return
    const r = document.createRange()
    r.setStart(node, Math.min(offset, (node.textContent || '').length))
    r.collapse(true)
    sel.removeAllRanges()
    sel.addRange(r)
  } catch {
    /* 忽略 */
  }
}

/** Tab 重入保护：补发的 Tab 事件不能再走一遍我们的处理 */
let tabRedispatch = false

/**
 * 列表项 Tab 缩进（用户实测反馈：Tab 没反应）：
 * Vditor 的列表缩进只认「光标位于该项第一个字符处」，光标在项中间时它直接放弃 ——
 * 浏览器的 Tab 默认行为随即把焦点移出编辑器，看起来就是「Tab 没反应」。
 * 这里把项中/项尾的 Tab 也接住：光标先落到项首，再补发一个 Tab 走 Vditor 自己的列表缩进；
 * 若该项没有可缩进的同级项（Vditor 不动），恢复原光标 —— 无论哪种情况都不让焦点跳出去。
 * 实测：项中间按 Tab → `* 一级A` + `  * 一级B`；上面有同级项时 → `    * 三级C`。
 */
function tabInListItem(e: KeyboardEvent) {
  if (tabRedispatch) return
  const root = vd?.vditor.element
  const li = caretListItem()
  if (!root || !li || !vd) return
  const first = firstTextNode(li)
  if (!first) return
  const sel = window.getSelection()
  const caret = sel && sel.rangeCount ? sel.getRangeAt(0) : null
  const atItemStart = !!caret && caret.collapsed && caret.startContainer === first && caret.startOffset === 0
  if (atItemStart) return // 已在项首：交给 Vditor 自己的逻辑（同一事件它还会继续处理）
  e.preventDefault() // 不让 Tab 把焦点移出编辑器
  const from = vd.getValue() || ''
  const savedNode = caret?.startContainer
  const savedOffset = caret?.startOffset ?? 0
  setCaret(first, 0)
  tabRedispatch = true
  try {
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', code: 'Tab', shiftKey: e.shiftKey, bubbles: true, cancelable: true }))
  } finally {
    tabRedispatch = false
  }
  const to = vd.getValue() || ''
  if (to !== from) emit('update:modelValue', to)
  else if (savedNode) setCaret(savedNode, savedOffset) // 没法再缩进：光标放回原处，别乱跳
}

/** 逐张上传（复用已鉴权的 http 客户端，与旧编辑器同一接口）→ 光标处插入 markdown → 立即 hydrate */
async function uploadAndInsert(files: File[]) {
  if (!files.length || uploading.value) return
  uploading.value = true
  const tip = ElMessage({ message: `上传图片中…（0/${files.length}）`, type: 'info', duration: 0 })
  let ok = 0
  try {
    for (let i = 0; i < files.length; i++) {
      const f = files[i]
      tip.message = `上传图片中…（${i + 1}/${files.length}）`
      const fd = new FormData()
      fd.append('file', f)
      const r = await http.post<{ url: string }>('/notes/images', fd)
      insertImage(r.url, f.name)
      ok++
    }
  } catch (err: any) {
    if (err?.response?.status !== 401 && err?.response?.status !== 423) {
      ElMessage.error(err?.response?.data?.detail || '图片上传失败，请重试')
    }
  } finally {
    tip.close()
    uploading.value = false
    if (ok) {
      ElMessage.success(`已插入 ${ok} 张图片`)
      queueHydrate() // 把 <img src=/api/notes/images/..> 换成带鉴权的 blob URL，当场就能看到图
    }
  }
}

/** 在光标处插入图片 markdown（alt 去扩展名/方括号，截断 30 字，与旧编辑器一致） */
function insertImage(url: string, fileName: string) {
  if (!vd) return
  const alt = (fileName || '').replace(/\.[a-z0-9]+$/i, '').replace(/[[\]]/g, '').trim().slice(0, 30) || '图片'
  // 先 focus 再插入：拖入/粘贴图片时光标可能不在编辑区，先落焦点才能插到光标处
  vd.focus()
  vd.insertMD(`\n\n![${alt}](${url})\n\n`)
  // 隔离实验证实：insertMD 不触发 input 回调（0 次）→ 父组件 form.content 不含图片，
  // 保存后图消失。插入后显式同步内容（watch 里 v === getValue() 直接返回，不会回灌成环）。
  emit('update:modelValue', vd.getValue() || '')
  queueHydrate()
}

/* ---------------- Vditor 初始化 ---------------- */

function initVditor() {
  if (!hostEl.value) return
  vd = new Vditor(hostEl.value, {
    value: props.modelValue,
    mode: 'ir', // 即时渲染（类似 Typora），编辑区直接渲染，不分屏
    lang: 'zh_CN',
    theme: isDark() ? 'dark' : 'classic',
    icon: 'ant',
    cdn: '/vditor', // 本地静态资源，走站内服务，不依赖外网 CDN
    height: 'auto',
    minHeight: props.minHeight ?? 420,
    placeholder: props.placeholder ?? '写点什么…（Markdown 即时渲染，标题/加粗等直接呈现效果）',
    cache: { enable: false }, // 正文已由后端加密落盘，不做 localStorage 缓存
    // 链接点击接管（vditor 已 preventDefault）：站内 /notes/ 走 SPA 不整页刷新；外链新窗口打开
    link: {
      click(el: Element) {
        const href = (el as HTMLAnchorElement).getAttribute('href') || ''
        if (href.startsWith('/notes/')) router.push(href)
        else if (/^https?:\/\//i.test(href)) window.open(href, '_blank')
      },
    },
    counter: { enable: true, type: 'text' },
    preview: {
      // 内容主题跟随站点明/暗（vditor 默认 light；不传则暗色首屏加载 light.css，
      // 主题只在 class 变化时才经 applyTheme 切换，首屏已暗色时永远不触发）
      theme: { current: isDark() ? 'dark' : 'light' },
      math: { engine: 'KaTeX', inlineDigit: true },
    },
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
    toolbar: [], // 不要工具栏（用户要求）：vditor 不传会渲染默认工具栏，必需显式空数组
    after() {
      if (pendingExternal !== null && pendingExternal !== vd?.getValue()) {
        vd?.setValue(pendingExternal || '', true)
      }
      pendingExternal = null
      ready = true
      startImgObserver() // 编辑区 DOM 稳定后开始盯「未鉴权 img」随时补 hydrate
      queueHydrate()
      if (props.autoFocus) {
        vd?.focus()
      }
    },
    input() {
      repairIndentList() // 段首空格缩进 + 列表标记 → 还原成半角空格，Vditor 重渲染成真列表
      emit('update:modelValue', vd?.getValue() || '')
      queueHydrate()
    },
    keydown(e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault()
        emit('save')
        return
      }
      // 段首空格保护：IR 下前导半角空格会被 Lute 抹平（保存即丢），段首改插 U+2002
      if (e.key === ' ' && !e.ctrlKey && !e.metaKey && !e.altKey && caretAtBlockStart()) {
        e.preventDefault()
        insertIndentSpace()
        return
      }
      // 列表项 Tab 缩进：光标在项中也能缩进，且不让焦点移出编辑器
      if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey && !e.altKey) tabInListItem(e)
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

/* 暴露给外部组件（博客「引用其它文章」对话框等）：
   insertMD 在光标处插入 Markdown（lute 自动渲染成对应元素；有选中文字会先删除，可用作包裹链接文字） */
function insertMD(md: string) {
  if (!vd) return
  vd.insertMD(md)
  vd.focus()
  // 与 insertImage 同理：insertMD 不触发 input 回调，显式同步内容到父组件
  emit('update:modelValue', vd.getValue() || '')
}
/** 当前选中的文字（无选中返回空串） */
function getSelectionText(): string {
  return vd?.getSelection() || ''
}
/** 聚焦编辑器并将光标定位至末尾 */
function focus() {
  if (!vd) return
  vd.focus()
  try {
    const el = (vd as any).vditor?.ir?.element || (vd as any).vditor?.element
    if (el) {
      el.scrollTop = el.scrollHeight
      const range = document.createRange()
      const sel = window.getSelection()
      range.selectNodeContents(el)
      range.collapse(false)
      sel?.removeAllRanges()
      sel?.addRange(range)
    }
  } catch {
    // 降级为基础 vd.focus()
  }
}
defineExpose({ insertMD, getSelectionText, focus })

onBeforeUnmount(() => {
  window.clearTimeout(hydraTimer)
  window.clearTimeout(imgMoTimer)
  imgMo?.disconnect()
  imgMo = null
  themeMo?.disconnect()
  vd?.destroy()
  vd = null
})
</script>

<style scoped>
.vde { width: 100%; }
.vde-host { width: 100%; }
.vde { position: relative; }
/* 拖拽提示浮层 */
.vde-drop {
  position: absolute; inset: 0; z-index: 20; border-radius: 14px;
  display: grid; place-items: center; pointer-events: none;
  border: 2px dashed rgba(167, 139, 250, 0.75);
  background: rgba(167, 139, 250, 0.1);
  color: var(--txt1); font-weight: 700; font-size: 15px;
}
html.theme-dark .vde-drop { background: rgba(139, 92, 246, 0.16); color: #e6ecf7; }

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
/* 无工具栏：vditor 仍会渲染空工具栏条，直接隐藏 */
.vde :deep(.vditor-toolbar) { display: none; }
.vde :deep(.vditor-ir),
.vde :deep(.vditor-reset) {
  background: transparent;
}
.vde :deep(.vditor-reset img) { border-radius: 10px; }

/* 暗色主题兜底：正文强制亮色可见
   （工具栏已移除；vditor 自身 dark 主题负责大部分配色） */
html.theme-dark .vde :deep(.vditor-ir) { color: #e6ecf7 !important; }
html.theme-dark .vde :deep(.vditor-reset) { color: #e6ecf7 !important; }
html.theme-dark .vde :deep(.vditor-ir a),
html.theme-dark .vde :deep(.vditor-reset a) { color: #7dd3fc !important; }
html.theme-dark .vde :deep(.vditor-ir__placeholder),
html.theme-dark .vde :deep(.vditor-empty__prompt) { color: #8b97ab !important; }

/* 表格配色：vditor 默认走内容主题的 #fafbfc/#fff 纯白行底，暗色下会与强制亮色文字撞成白底白字，
   这里统一改为「透明行底 + 淡紫表头 + 石板灰描边 + 轻微斑马纹」（与阅读页 NoteView 的表格观感一致），明暗两色同样生效。 */
.vde :deep(.vditor-reset table tr) {
  background-color: transparent !important;
  border-top: 1px solid rgba(148, 163, 184, 0.35) !important;
}
.vde :deep(.vditor-reset table tbody tr:nth-child(2n)) {
  background-color: rgba(148, 163, 184, 0.1) !important;
}
.vde :deep(.vditor-reset table td),
.vde :deep(.vditor-reset table th) {
  border: 1px solid rgba(148, 163, 184, 0.35) !important;
}
.vde :deep(.vditor-reset table th) {
  background-color: rgba(167, 139, 250, 0.16) !important;
  font-weight: 600;
}
</style>