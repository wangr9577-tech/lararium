<template>
  <el-tooltip v-if="supported" :content="isFs ? '退出全屏' : '全屏（隐藏地址栏）'" placement="bottom">
    <el-button text circle @click="toggle">
      <el-icon :size="18"><FullScreen /></el-icon>
    </el-button>
  </el-tooltip>
</template>

<script setup lang="ts">
/**
 * 全屏开关：点一下隐藏浏览器地址栏与系统状态栏，整页全屏（平板/手机更接近原生 App）。
 *
 * 说明：浏览器安全策略要求全屏必须由「用户手势」触发，因此刷新/重开页面后需再点一次；
 * SPA 内部切换路由不会退出全屏。不支持 Fullscreen API 的内核上按钮自动隐藏。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { FullScreen } from '@element-plus/icons-vue'

type FsDoc = Document & {
  webkitFullscreenElement?: Element | null
  webkitExitFullscreen?: () => Promise<void> | void
}
type FsEl = HTMLElement & {
  webkitRequestFullscreen?: (options?: { navigationUI?: string }) => Promise<void> | void
}

const supported = ref(false)
const isFs = ref(false)

function fsElement(): Element | null {
  const d = document as FsDoc
  return document.fullscreenElement || d.webkitFullscreenElement || null
}

function onChange() {
  isFs.value = !!fsElement()
}

async function toggle() {
  const d = document as FsDoc
  const el = document.documentElement as FsEl
  try {
    if (fsElement()) {
      if (document.exitFullscreen) await document.exitFullscreen()
      else if (d.webkitExitFullscreen) await d.webkitExitFullscreen()
    } else if (el.requestFullscreen) {
      await el.requestFullscreen({ navigationUI: 'hide' })
    } else if (el.webkitRequestFullscreen) {
      await el.webkitRequestFullscreen({ navigationUI: 'hide' })
    }
  } catch {
    /* 个别内核可能拒绝全屏请求（权限策略等）：静默忽略，不影响页面其他功能 */
  }
  onChange()
}

onMounted(() => {
  const el = document.documentElement as FsEl
  supported.value = !!document.fullscreenEnabled && !!(el.requestFullscreen || el.webkitRequestFullscreen)
  document.addEventListener('fullscreenchange', onChange)
  document.addEventListener('webkitfullscreenchange', onChange)
  onChange()
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onChange)
  document.removeEventListener('webkitfullscreenchange', onChange)
})
</script>