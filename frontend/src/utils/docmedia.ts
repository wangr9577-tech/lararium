/**
 * 项目文档里的图片显示：md 正文常写成相对路径（`![](./fig/1.png)`），
 * 这些图片在项目目录里、由 /api/fs/blob 提供，但 <img src> 带不了 Authorization 头，
 * 所以先按文档所在目录把相对路径解析成源内路径，再用带鉴权的 blob 请求换 objectURL。
 *
 * 只处理相对路径的图片；http(s)/data:/blob:/站内 /api/ 图片一律原样交给浏览器。
 */
import { fsApi } from '../api/fs'

const IMG_RE = /\.(png|jpe?g|gif|webp|bmp|avif)$/i
const cache = new Map<string, string>()

/** 相对路径 → 源内路径（`..` 越界返回空串=不处理） */
export function resolveRel(baseDir: string, rel: string): string {
  if (!rel || rel.startsWith('/')) return ''
  const parts = baseDir ? baseDir.split('/') : []
  for (const seg of rel.split('/')) {
    if (!seg || seg === '.') continue
    if (seg === '..') {
      if (!parts.length) return ''
      parts.pop()
      continue
    }
    parts.push(seg)
  }
  return parts.join('/')
}

/** 文档所在目录（'docs/a.md' → 'docs'） */
export function dirOf(path: string): string {
  const i = path.lastIndexOf('/')
  return i < 0 ? '' : path.slice(0, i)
}

/** 把容器内所有相对路径图片换成带鉴权的 blob URL（渲染/挂载后调用；幂等） */
export async function hydrateDocImages(
  root: HTMLElement | null | undefined,
  sid: string,
  baseDir: string,
): Promise<void> {
  if (!root) return
  const imgs = Array.from(root.querySelectorAll<HTMLImageElement>('img'))
  for (const img of imgs) {
    const raw = img.getAttribute('src') || ''
    if (!raw || /^(https?:|data:|blob:|\/api\/)/i.test(raw)) continue
    const clean = raw.split(/[?#]/)[0]
    if (!IMG_RE.test(clean)) continue
    let rel = clean
    try {
      rel = decodeURIComponent(clean)
    } catch {
      /* 保留原样 */
    }
    const path = resolveRel(baseDir, rel)
    if (!path) continue
    const key = `${sid}|${path}`
    let url = cache.get(key)
    if (!url) {
      try {
        url = URL.createObjectURL(await fsApi.blob(sid, path))
        cache.set(key, url)
      } catch {
        continue // 图片不存在/超限：保持原样，不打断正文阅读
      }
    }
    if (img.isConnected && img.getAttribute('src') !== url) img.src = url
  }
}