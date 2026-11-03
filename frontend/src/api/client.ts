import axios from 'axios'

export const TOKEN_KEY = 'krs_token'
export const USER_KEY = 'krs_user'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
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
    const code = err.response?.status
    if (code === 423) {
      // 数据未解锁（服务重启后 DEK 仅在内存）：需重新登录解锁
      clearToken()
      if (location.pathname !== '/login') location.href = '/login?reason=relock'
    } else if (code === 401 && location.pathname !== '/login') {
      clearToken()
      location.href = '/login'
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
