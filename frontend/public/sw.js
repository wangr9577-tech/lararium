/* Kruskal PWA Service Worker —— 纯透传，不做任何缓存。
 *
 * 存在意义：让浏览器把本站判定为「可安装应用」（部分 Chromium/Edge 版本要求
 * 站点存在带 fetch 处理器的 Service Worker 才给「安装应用」入口）。
 *
 * 设计取舍：**故意不缓存任何响应**——本项目是本地加密个人站，内容必须实时，
 * 缓存只会带来「页面过期 / 白屏」类问题。所有请求原样转发到网络。
 *
 * 撤销方式：删除本文件 + 移除 main.ts 里的 register 调用即可；
 * 已装过的浏览器可在「应用信息 → 存储 → 清除」或站点设置里重置。
 */
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('fetch', (event) => {
  // 只接管同源 GET；非 GET（如导出 PDF 的 POST、上传）不拦截
  if (event.request.method !== 'GET') return
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin) return
  event.respondWith(fetch(event.request))
})