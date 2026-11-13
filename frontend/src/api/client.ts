import axios from 'axios'

export const TOKEN_KEY = 'krs_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

/** 向本机后端换取会话 token（单机应用没有登录，启动时自动建立）。 */
let sessionPending: Promise<boolean> | null = null
export function ensureSession(): Promise<boolean> {
  if (getToken()) return Promise.resolve(true)
  if (!sessionPending) {
    sessionPending = fetch('/api/auth/local-session', { method: 'POST' })
      .then(async (r) => {
        if (!r.ok) return false
        const data = await r.json()
        setToken(data.token)
        return true
      })
      .catch(() => false)
      .finally(() => { sessionPending = null })
  }
  return sessionPending
}

export const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use((cfg) => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    // token 失效（如数据目录被替换）：重新换一张本机会话票再刷新一次，避免卡在空页
    if (err.response?.status === 401) {
      clearToken()
      const reloadKey = 'krs_session_reload'
      const last = Number(sessionStorage.getItem(reloadKey) || 0)
      if (Date.now() - last > 10000) {
        sessionStorage.setItem(reloadKey, String(Date.now()))
        ensureSession().then((ok) => { if (ok) location.reload() })
      }
    }
    return Promise.reject(err)
  },
)

export const http = {
  get: <T = any>(url: string) => api.get<T>(url).then((r) => r.data),
  post: <T = any>(url: string, data?: any) => api.post<T>(url, data).then((r) => r.data),
  put: <T = any>(url: string, data?: any) => api.put<T>(url, data).then((r) => r.data),
  patch: <T = any>(url: string, data?: any) => api.patch<T>(url, data).then((r) => r.data),
  del: <T = any>(url: string) => api.delete<T>(url).then((r) => r.data),
  /** 下载二进制（如导出的 PDF） */
  blob: (url: string) => api.get(url, { responseType: 'blob', timeout: 240000 }).then((r) => r.data as Blob),
}
