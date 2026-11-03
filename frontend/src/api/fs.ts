/**
 * 项目文档源 API 封装（/api/fs）。
 *
 * 设计约定（与后端 routers/fs.py 一一对应）：
 *  - 文档源 = CODE_ROOT（默认 deepseek-workspace）之内的一个项目目录；只挂 md，
 *    文件留在原处，站点只是视图 + 可选编辑器（不复制、不落库、不加密搬运）。
 *  - 保存必须带 base_sha256：后端比对不上就 409，绝不静默覆盖 agent 的改动。
 *  - 删除源只删挂载配置，磁盘上的文件一个都不动。
 */
import { http } from './client'

export interface FsSource {
  id: string
  name: string
  /** 相对 CODE_ROOT 的路径（空串=CODE_ROOT 本身） */
  root: string
  include: string[]
  readonly: boolean
  exists: boolean
  md_count: number
  md_count_truncated: boolean
}

export interface FsDirNode { name: string; path: string }

export interface FsFileNode {
  name: string
  path: string
  size: number
  mtime: string
  title: string
}

export interface FsTree {
  path: string
  dirs: FsDirNode[]
  files: FsFileNode[]
  truncated: boolean
  source: { id: string; name: string; readonly: boolean }
}

export interface FsDocMeta { title: string; tags: string[]; summary: string }

export interface FsDoc {
  sid: string
  path: string
  name: string
  size: number
  mtime: string
  sha256: string
  content: string
  meta: FsDocMeta
  source: { id: string; name: string; root: string; readonly: boolean }
}

export interface FsHit {
  sid: string
  source: string
  path: string
  name: string
  title: string
  excerpt: string
  mtime: string
}

export interface FsCandidate {
  root: string
  name: string
  md_count: number
  md_count_truncated: boolean
  has_git: boolean
  added: boolean
}

export interface SourcePayload {
  name: string
  root: string
  include: string[]
  readonly: boolean
}

/** 拼查询串（http 封装只吃路径，不吃 axios params） */
function qs(params: Record<string, string>): string {
  return '?' + Object.entries(params)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
}

export const fsApi = {
  sources: () => http.get<{ root: string; items: FsSource[] }>('/fs/sources'),
  addSource: (body: SourcePayload) => http.post<FsSource>('/fs/sources', body),
  updateSource: (sid: string, body: SourcePayload) => http.put<FsSource>(`/fs/sources/${sid}`, body),
  removeSource: (sid: string) => http.del<{ ok: boolean }>(`/fs/sources/${sid}`),
  discover: () => http.get<{ root: string; items: FsCandidate[]; truncated: boolean }>('/fs/discover'),
  tree: (sid: string, path = '') => http.get<FsTree>(`/fs/tree${qs({ sid, path })}`),
  read: (sid: string, path: string) => http.get<FsDoc>(`/fs/file${qs({ sid, path })}`),
  save: (body: { sid: string; path: string; content: string; base_sha256: string }) =>
    http.put<{ path: string; size: number; mtime: string; sha256: string }>('/fs/file', body),
  search: (q: string, sid = '') =>
    http.get<{ items: FsHit[]; scanned: number; truncated: boolean }>(`/fs/search${qs({ q, sid })}`),
  /** 图片走 blob：<img> 带不了鉴权头，取回后换 objectURL（与站内图片同一模式） */
  blob: (sid: string, path: string) => http.blob(`fs/blob${qs({ sid, path })}`),
}

/** 人类可读体积 */
export function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}