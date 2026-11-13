/**
 * 工作台 API 封装（/api/workbench）。
 *
 * 设计约定（与后端 routers/workbench.py 一一对应）：
 *  - 首页列表只返回摘要摘要（summary）与计数，不带正文：展开事项后再拉详情，
 *    避免首页同时解密并挂载所有长文编辑器。
 *  - item.id / entry.id / capture.id / link.id 都是整数；target_id（论文/笔记）是 12 位 hex 字符串。
 *  - 所有正文（当前思路/小记/收集片段）都在服务端加密落盘，前端不把明文长期放进 localStorage。
 */
import { http } from './client'

/** 首页/详情里的事项摘要（不含正文） */
export interface WbItemBrief {
  id: number
  title: string
  parent_id: number | null
  sort: number
  archived: boolean
  summary: string
  entry_count: number
  capture_count: number
  sub_count: number
  updated_at: string
  created_at: string
}

/** 首页的主事项（带一层子事项） */
export interface WbItemNode extends WbItemBrief {
  children: WbItemBrief[]
}

/** 收集箱条目（无正文全文，只有摘要） */
export interface WbCaptureBrief {
  id: number
  excerpt: string
  has_text: boolean
  source: string
  url: string
  item_id: number | null
  archived: boolean
  created_at: string
}

export interface WbCapture extends WbCaptureBrief {
  text: string
}

export interface WbEntry {
  id: number
  text: string
  created_at: string
  updated_at: string
}

export interface WbLink {
  id: number
  target_type: 'note' | 'paper' | string
  target_id: string
  title: string
  route: string
  missing: boolean
  author?: string
  folder?: string
}

export interface WbBacklinkItem {
  id: number
  title: string
  parent_id: number | null
  parent_title: string | null
  updated_at: string
  archived?: boolean
}

export interface WbOverview {
  items: WbItemNode[]
  inbox: WbCaptureBrief[]
  inbox_total: number
}

export interface WbItemDetail extends WbItemBrief {
  thinking: string
  entries: WbEntry[]
  captures: WbCaptureBrief[]
  links: WbLink[]
  children: WbItemBrief[]
  parent: { id: number; title: string } | null
  siblings: { id: number; title: string }[]
}

/** 搜索选择器候选资料（现有论文 / 笔记·博客） */
export interface WbCandidate {
  target_type: 'note' | 'paper' | string
  target_id: string
  title: string
  kind: string
  folder?: string
  summary?: string
  author?: string
  status?: string
}

export type WbCaptureScope = 'inbox' | 'item' | 'all' | 'archived'

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue
    p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const workbenchApi = {
  /** 首页：事项树 + 未归类收集箱最近片段 */
  overview: (includeArchived = false) =>
    http.get<WbOverview>(`/workbench${qs({ include_archived: includeArchived })}`),

  createItem: (title: string, parentId: number | null = null) =>
    http.post<{ id: number; title: string; parent_id: number | null }>('/workbench/items', {
      title, parent_id: parentId,
    }),

  getItem: (id: number) => http.get<WbItemDetail>(`/workbench/items/${id}`),

  /** 改名 / 移动层级（moveParent=true 时同时应用 parentId，传 null 即提升为主事项）/ 归档 */
  patchItem: (
    id: number,
    body: { title?: string; parent_id?: number | null; move_parent?: boolean; archived?: boolean },
  ) => http.put<{ ok: true }>(`/workbench/items/${id}`, body),

  /** 同级上移/下移一位（首页手动调整顺序） */
  moveItem: (id: number, direction: 'up' | 'down') =>
    http.post<{ ok: true; moved: boolean }>(`/workbench/items/${id}/move`, { direction }),

  /** 删除事项：连同子事项/小记/片段/链接；资料正文一律保留（正文进回收站可恢复） */
  deleteItem: (id: number) =>
    http.del<{ ok: true; deleted_items: number; trash_id: string | null }>(`/workbench/items/${id}`),

  getThinking: (id: number) =>
    http.get<{ content: string }>(`/workbench/items/${id}/thinking`),
  /** 保存当前思路；若事项还是「未命名」，后端会把正文第一行提上来当标题（title_adopted=true） */
  putThinking: (id: number, content: string) =>
    http.put<{ ok: true; updated_at: string; summary: string; title: string; title_adopted: boolean }>(
      `/workbench/items/${id}/thinking`, { content }),

  createEntry: (itemId: number, text: string) =>
    http.post<WbEntry>(`/workbench/items/${itemId}/entries`, { text }),
  updateEntry: (itemId: number, entryId: number, text: string) =>
    http.put<{ ok: true; updated_at: string }>(
      `/workbench/items/${itemId}/entries/${entryId}`, { text }),
  deleteEntry: (itemId: number, entryId: number) =>
    http.del<{ ok: true }>(`/workbench/items/${itemId}/entries/${entryId}`),

  listCaptures: (opts: { q?: string; scope?: WbCaptureScope; itemId?: number; limit?: number } = {}) =>
    http.get<{ items: WbCaptureBrief[]; total: number }>(
      `/workbench/captures${qs({
        q: opts.q ?? '', scope: opts.scope ?? 'inbox',
        item_id: opts.itemId ?? null, limit: opts.limit ?? 100,
      })}`),

  getCapture: (id: number) => http.get<WbCapture>(`/workbench/captures/${id}`),

  createCapture: (body: { text?: string; source?: string; url?: string; user_note?: string; item_id?: number | null }) =>
    http.post<WbCaptureBrief>('/workbench/captures', body),

  updateCapture: (id: number, body: { text?: string; source?: string; url?: string }) =>
    http.put<{ ok: true }>(`/workbench/captures/${id}`, body),

  /** 把片段放进某个事项（itemId=null 移回收集箱）；archive 可单独切换归档 */
  moveCapture: (id: number, body: { item_id?: number | null; archived?: boolean }) =>
    http.post<{ ok: true }>(`/workbench/captures/${id}/move`, body),

  /** 把片段直接整理成一个事项：原文成为该事项的「当前思路」，片段本身归档保留 */
  promoteCapture: (id: number) =>
    http.post<{ ok: true; item_id: number; title: string; thinking: string }>(
      `/workbench/captures/${id}/promote`),

  deleteCapture: (id: number) => http.del<{ ok: true }>(`/workbench/captures/${id}`),

  listLinks: (itemId: number) =>
    http.get<{ items: WbLink[] }>(`/workbench/items/${itemId}/links`),

  /** 关联已有资料；后端幂等（同一事项内同资料只保留一条），重复调用不会产生重复链接 */
  addLink: (itemId: number, targetType: 'note' | 'paper' | string, targetId: string) =>
    http.post<{ ok: true; created: boolean; link_id: number | null }>(
      `/workbench/items/${itemId}/links`, { target_type: targetType, target_id: targetId }),

  /** 只移除工作台入口，不删除论文或博客笔记本身 */
  removeLink: (itemId: number, linkId: number) =>
    http.del<{ ok: true }>(`/workbench/items/${itemId}/links/${linkId}`),

  /** 笔记编辑页用：该事项是否已关联这篇笔记 */
  noteLinkStatus: (itemId: number, noteId: string) =>
    http.get<{ linked: boolean; link_id: number | null }>(
      `/workbench/items/${itemId}/note-link${qs({ note_id: noteId })}`),

  /** 反向引用查询：查询某篇笔记或论文被哪些工作台事项引用 */
  getBacklinks: (targetType: string, targetId: string) =>
    http.get<{ items: WbBacklinkItem[] }>(
      `/workbench/links/backlinks${qs({ target_type: targetType, target_id: targetId })}`),

  /** 搜索可关联的现有资料（kind: all | note | paper） */
  selector: (q = '', kind: 'all' | 'note' | 'paper' | string = 'all', limit = 30) =>
    http.get<{ items: WbCandidate[]; total: number }>(
      `/workbench/selector${qs({ q, kind, limit })}`),
}

/** 事项详情的路由（首页与详情页共用） */
export const itemRoute = (id: number) => `/lab/items/${id}`

/* ---------------- 首页「今日安排」随手记（一份固定的加密 md） ---------------- */

export interface DayNote {
  content: string
  updated: string
}

export const dayNoteApi = {
  /** 读这份随手记（固定一份，不按天） */
  get: () => http.get<DayNote>('/daynote'),
  /** 整篇覆盖保存（前端防抖自动保存）；内容不会被自动清空或按天重置 */
  put: (content: string) =>
    http.put<{ ok: true; updated: string }>('/daynote', { content }),
}

/** 资料类型中文名 */
export function kindLabel(kind: string): string {
  return ({
    blog: '博客',
    note: '学习笔记',
    project: '项目经历',
    paper: '论文',
  } as Record<string, string>)[kind] || kind
}