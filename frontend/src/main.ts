import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './style.css'
import App from './App.vue'
import router from './router'

// 旧标签页自愈：若页面引用的新构建资源加载失败（多标签/部署后），自动刷新一次
window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
  const msg = String((e.reason && (e.reason.message || e.reason)) || e.reason || '')
  if (!/loading chunk|failed to fetch dynamically imported|ChunkLoadError|import.meta.url|Unexpected token/i.test(msg)) return
  const now = Date.now()
  try {
    const last = Number(sessionStorage.getItem('krs_reload_ts') || 0)
    if (now - last < 30000) return
    sessionStorage.setItem('krs_reload_ts', String(now))
  } catch { /* ignore */ }
  location.reload()
})

// 主题在挂载前应用（默认暗黑：深色二次元背景是本站主视觉）
const theme = localStorage.getItem('krs_theme') || 'dark'
document.documentElement.classList.toggle('theme-dark', theme === 'dark')

const app = createApp(App)
app.use(ElementPlus, { locale: zhCn })
app.use(router)
app.mount('#app')

// PWA：注册纯透传 Service Worker（仅生产构建 + 安全上下文），
// 使站点可被「安装」到平板/手机桌面，安装后全屏运行、无地址栏。
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* 注册失败不影响正常网页访问，静默忽略 */
    })
  })
}
