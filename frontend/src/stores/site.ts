import { reactive } from 'vue'
import { http } from '../api/client'

/** 站点公开信息（site.name / site.slogan，来自 /api/site 公共接口） */
export const site = reactive({ name: 'Kruskal', slogan: '', loaded: false })

export async function loadSite(force = false) {
  if (site.loaded && !force) return
  try {
    const s = await http.get<{ name: string; slogan: string }>('/site')
    if (s.name) site.name = s.name
    site.slogan = s.slogan || ''
    site.loaded = true
  } catch {
    /* 网络失败时保持默认 */
  }
}
