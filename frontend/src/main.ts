import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { ensureSession } from './api/client'
import { initClientState } from './api/clientState'
import { ElMessage } from 'element-plus'

// 路由懒加载的失败由 Vue Router 捕获，不一定会触发 unhandledrejection。
// 保留当前页面与未保存内容，让用户决定何时刷新。
router.onError((error) => {
  const msg = String(error?.message || error)
  if (/loading chunk|failed to fetch dynamically imported|importing a module script failed|ChunkLoadError/i.test(msg)) {
    ElMessage.warning({ message: '页面资源已更新或暂时不可用。请先保存当前内容，再刷新页面后重试。', duration: 0, showClose: true })
  }
})

// 其他异步资源失败时也提示手动刷新，避免强制刷新丢失未保存内容。
window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
  const msg = String((e.reason && (e.reason.message || e.reason)) || e.reason || '')
  if (!/loading chunk|failed to fetch dynamically imported|ChunkLoadError|import.meta.url|Unexpected token/i.test(msg)) return
  ElMessage.warning({ message: '页面资源已更新或暂时不可用。请先保存当前内容，再刷新页面后重试。', duration: 0, showClose: true })
})

// 固定使用明亮粉紫主题，忽略旧版本保存的暗黑主题偏好
document.documentElement.classList.remove('theme-dark')

// 清理登录时代的本地残留标记
try {
  localStorage.removeItem('krs_user')
  sessionStorage.removeItem('krs_local_mode')
} catch { /* ignore */ }

const app = createApp(App)
app.use(ElementPlus, { locale: zhCn })
app.use(router)

// 单机应用：先建立本机会话，再挂载，避免首屏接口 401
async function bootstrap() {
  try {
    if (!await ensureSession()) throw new Error('无法建立会话')
    await initClientState()
  } catch {
    const root = document.getElementById('app')
    if (root) root.textContent = '无法读取或迁移服务端数据，请检查服务连接后刷新。尚未迁移的浏览器数据会保留。'
    return
  }
  app.mount('#app')
}
bootstrap()

// PWA：注册纯透传 Service Worker（仅生产构建 + 安全上下文）
// 使站点可被「安装」到平板/手机桌面，安装后全屏运行、无地址栏
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* 注册失败不影响正常网页访问，静默忽略 */
    })
  })
}
