import { http } from '../api/client'

/**
 * 站内图片（/api/notes/images/...）显示统一入口：
 * 图片接口需要会话 token，而 <img src> 无法携带 Authorization header，
 * 故用带鉴权的 blob 下载后替换为 objectURL（与相册照片同一模式，
 * token 只走 header，不进 URL、不进访问日志）。
 */
const cache = new Map<string, string>()
const pending = new Map<string, Promise<string>>()

/** 解析媒体 URL：站内图片返回 blob URL（缓存复用），其它原样返回 */
export function resolveMediaUrl(url: string): Promise<string> {
  if (!url.startsWith('/api/notes/images/')) return Promise.resolve(url)
  const hit = cache.get(url)
  if (hit) return Promise.resolve(hit)
  const task = pending.get(url)
  if (task) return task
  // api 实例 baseURL=/api：去掉前缀传相对路径，否则会被拼成 /api/api/... 双重前缀
  const rel = url.replace(/^\/api\//, '')
  const p = http.blob(rel)
    .then((b) => {
      const u = URL.createObjectURL(b)
      cache.set(url, u)
      pending.delete(url)
      return u
    })
    .catch(() => {
      pending.delete(url)
      return url // 失败（如会话过期）保留原 URL，由外层 401 拦截器统一处理
    })
  pending.set(url, p)
  return p
}

/** 把容器内所有站内图片 <img src> 替换为 blob URL（内容渲染/挂载后调用；幂等） */
export function hydrateImages(root: HTMLElement | null | undefined) {
  if (!root) return
  root.querySelectorAll<HTMLImageElement>('img[src^="/api/notes/images/"]').forEach((img) => {
    const src = img.getAttribute('src') || ''
    if (!src) return
    resolveMediaUrl(src).then((u) => {
      if (img.isConnected && img.getAttribute('src') !== u) img.src = u
    })
  })
}
