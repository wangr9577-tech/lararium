import { http, getToken } from './client'

// 清理历史可能残留在浏览器中的本地演示/mock 数据
try {
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('krs_assistant_local_records_v1')
  }
} catch {
  // ignore
}

export type AssistantKind = 'notice' | 'later'
export type AssistantFilter = 'all' | 'alerts' | 'notice' | 'later' | 'archived'

export interface AssistantAttachment {
  filename: string
  original_name?: string
  url: string
  size: number
  is_image: boolean
  mime?: string
}

export interface AssistantThreadSource {
  id: number
  thread_id: number
  record_id: number
  sequence: number
  change_type: 'new' | 'update' | 'postpone' | 'cancel' | 'conflict'
  change_reason: string
  received_at: string
  created_at: string
  source_title?: string
  raw_content?: string
}

export interface AssistantThread {
  id: number
  title: string
  summary: string
  highlights: string[]
  latest_change: string
  deadline_date: string
  deadline_time: string
  has_conflict: boolean
  wb_item_id?: number | null
  status: 'active' | 'completed' | 'archived'
  created_at: string
  updated_at: string
  sources?: AssistantThreadSource[]
}

export interface LlmDiagnostics {
  connected: boolean
  latency_ms: number
  model: string
  provider?: string
  endpoint?: string
  error_hint: string
}

export interface AssistantRecord {
  id: number
  capture_id?: number | null
  kind: AssistantKind
  title: string
  source_type: 'text' | 'image' | 'file' | 'url'
  source_url: string
  user_note: string
  category: string
  tags: string[]
  status: 'pending' | 'processing' | 'ready' | 'failed'
  error_msg?: string
  read_state: 'unread' | 'read' | 'noted'
  archived: boolean | number
  pinned: boolean | number
  created_at: string
  updated_at: string

  // 稍后看特有字段
  summary?: string
  reason?: string
  content?: string
  raw_content?: string
  image_preview?: string

  // 工作台关联字段
  wb_item_id?: number | null
  wb_item_title?: string

  // 通知事项特有或关联线程字段
  thread_id?: number
  deadline_date?: string
  deadline_time?: string
  highlights?: string[]
  latest_change?: string
  has_conflict?: boolean
  thread?: AssistantThread

  // 核心证据依据与附件
  quote?: string
  evidence_quotes?: string[]
  attachments?: AssistantAttachment[]
  attachments_count?: number
}

export interface AssistantChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  loading?: boolean
}

export interface NoteDraft {
  title: string
  content: string
  summary?: string
  tags?: string[]
  source_url?: string
}

export interface CreateRecordPayload {
  kind: 'auto' | 'notice' | 'later'
  content?: string
  url?: string
  user_note?: string
  image_preview?: string
  filename?: string
  file?: File
}

function parseArrayField(val: unknown): string[] {
  if (Array.isArray(val)) return val.map(String)
  if (typeof val === 'string' && val.trim()) {
    try {
      const parsed = JSON.parse(val)
      if (Array.isArray(parsed)) return parsed.map(String)
    } catch {
      return [val]
    }
  }
  return []
}

export const assistantApi = {
  /** 获取真实记录列表 */
  async list(filter: AssistantFilter = 'all', q = ''): Promise<AssistantRecord[]> {
    const qParams = new URLSearchParams()
    qParams.set('scope', filter)
    if (q.trim()) qParams.set('q', q.trim())
    const url = `/assistant/records?${qParams.toString()}`

    const res = await http.get<{ items: any[]; total?: number }>(url)
    if (!res || !Array.isArray(res.items)) {
      return []
    }

    return res.items.map((r) => {
      const parsedTags = parseArrayField(r.tags)
      const parsedHighlights = parseArrayField(r.highlights)

      return {
        ...r,
        tags: parsedTags,
        highlights: parsedHighlights.length ? parsedHighlights : (r.thread?.highlights ? parseArrayField(r.thread.highlights) : []),
        summary: r.summary || (r.thread?.summary) || r.thread_summary || '',
        reason: r.reason || r.user_note || '',
        deadline_date: r.deadline_date || (r.thread?.deadline_date) || '',
        deadline_time: r.deadline_time || (r.thread?.deadline_time) || '',
        latest_change: r.latest_change || (r.thread?.latest_change) || '',
        error_msg: r.error_msg || '',
        quote: r.quote || '',
        evidence_quotes: Array.isArray(r.evidence_quotes) ? r.evidence_quotes : [],
        attachments: Array.isArray(r.attachments) ? r.attachments : [],
        attachments_count: typeof r.attachments_count === 'number' ? r.attachments_count : (Array.isArray(r.attachments) ? r.attachments.length : 0),
        archived: Boolean(r.archived),
        pinned: Boolean(r.pinned),
        has_conflict: Boolean(r.has_conflict || r.thread?.has_conflict),
      } as AssistantRecord
    })
  },

  /** 提交新内容到真实后端（支持文字、真正的二进制文件、截图附件与链接） */
  async create(payload: CreateRecordPayload): Promise<AssistantRecord> {
    let res: {
      id: number
      kind: AssistantKind
      title: string
      status: string
      job_id?: number
      created_at?: string
    }

    if (payload.file) {
      // 存在真实附件/截图文件：使用 FormData 传输真实文件内容
      const formData = new FormData()
      formData.append('text', payload.content || '')
      formData.append('mode', payload.kind || 'auto')
      formData.append('source_url', payload.url || '')
      formData.append('user_note', payload.user_note || '')
      formData.append('source_type', payload.file.type.startsWith('image/') ? 'image' : 'file')
      formData.append('file', payload.file, payload.file.name)

      res = await http.post('/assistant/submit', formData)
    } else {
      // 纯文本或带有 base64 截图预览的 JSON 请求
      res = await http.post('/assistant/submit', {
        text: payload.content || '',
        mode: payload.kind || 'auto',
        source_url: payload.url || '',
        user_note: payload.user_note || '',
        source_type: payload.image_preview ? 'image' : (payload.url ? 'url' : 'text'),
        image_base64: payload.image_preview || undefined,
      })
    }

    if (!res || !res.id) {
      throw new Error('提交失败，服务器未返回有效 ID')
    }

    // 尝试拉取刚生成的记录详情
    const created = await this.get(res.id)
    if (created) return created

    // 兜底返回初始状态
    return {
      id: res.id,
      kind: res.kind,
      title: res.title,
      source_type: (payload.file?.type.startsWith('image/') || payload.image_preview) ? 'image' : payload.url ? 'url' : 'text',
      source_url: payload.url || '',
      user_note: payload.user_note || '',
      category: '',
      tags: [],
      status: 'pending',
      read_state: 'unread',
      archived: false,
      pinned: false,
      created_at: res.created_at || '刚刚',
      updated_at: res.created_at || '刚刚',
      summary: '已接收，后台正在整理...',
      reason: payload.user_note || '',
      image_preview: payload.image_preview,
    }
  },

  /** 获取单条详情（含原文解密与演变记录） */
  async get(id: number): Promise<AssistantRecord | null> {
    try {
      const res = await http.get<{
        id: number
        capture_id?: number | null
        kind: AssistantKind
        title: string
        source_type: 'text' | 'image' | 'file' | 'url'
        source_url: string
        user_note: string
        category: string
        tags: string[]
        status: 'pending' | 'processing' | 'ready' | 'failed'
        read_state: 'unread' | 'read' | 'noted'
        archived: boolean
        pinned: boolean
        wb_item_id?: number | null
        wb_item_title?: string
        created_at: string
        updated_at: string
        raw_text?: string
        card?: any
        thread?: any
        schedules?: any[]
        links?: any[]
      }>(`/assistant/records/${id}`)

      if (!res || !res.id) return null

      const c = res.card || {}
      const t = res.thread
      const parsedTags = parseArrayField(res.tags)
      const parsedHighlights = c.highlights || (t ? parseArrayField(t.highlights) : [])

      return {
        id: res.id,
        capture_id: res.capture_id,
        kind: res.kind,
        title: res.title,
        source_type: res.source_type,
        source_url: res.source_url,
        user_note: res.user_note,
        category: res.category,
        tags: parsedTags,
        status: res.status,
        error_msg: (res as any).error_msg || '',
        read_state: res.read_state,
        archived: res.archived,
        pinned: res.pinned,
        wb_item_id: res.wb_item_id,
        wb_item_title: res.wb_item_title || '',
        created_at: res.created_at,
        updated_at: res.updated_at,
        summary: c.brief || c.summary || (t?.summary) || '',
        reason: c.why_focus || res.user_note || '',
        highlights: parsedHighlights,
        raw_content: res.raw_text || '',
        content: res.raw_text || '',
        thread: t,
        thread_id: t?.id,
        deadline_date: t?.deadline_date,
        deadline_time: t?.deadline_time,
        latest_change: t?.latest_change,
        has_conflict: Boolean(t?.has_conflict),
        quote: (res as any).quote || c.quote || (t?.quote) || '',
        evidence_quotes: Array.isArray((res as any).evidence_quotes)
          ? (res as any).evidence_quotes
          : (c.evidence_quotes || t?.evidence_quotes || []),
        attachments: Array.isArray((res as any).attachments) ? (res as any).attachments : [],
        attachments_count: Array.isArray((res as any).attachments) ? (res as any).attachments.length : 0,
      } as AssistantRecord
    } catch {
      return null
    }
  },

  /** 获取附件安全访问完整 URL（自动携带 token，支持下载参数） */
  getAttachmentUrl(recordId: number, filename: string, options?: { download?: boolean }): string {
    const token = getToken()
    const base = `/api/assistant/records/${recordId}/attachments/${encodeURIComponent(filename)}`
    const params = new URLSearchParams()
    if (token) params.set('token', token)
    if (options?.download) params.set('download', '1')
    const qs = params.toString()
    return qs ? `${base}?${qs}` : base
  },

  /** 归档 / 取消归档 */
  async toggleArchive(id: number, archived: boolean): Promise<void> {
    await http.patch(`/assistant/records/${id}`, { archived: archived ? 1 : 0 })
  },

  /** 标记已看 / 未读 */
  async toggleRead(id: number, read: boolean): Promise<void> {
    await http.patch(`/assistant/records/${id}`, { read_state: read ? 'read' : 'unread' })
  },

  /** 手动重新处理 (重试) */
  async retry(id: number): Promise<void> {
    await http.post(`/assistant/records/${id}/retry`)
  },

  /** 改用规则降级整理 */
  async fallbackRule(id: number): Promise<void> {
    await http.post(`/assistant/records/${id}/fallback-rule`)
  },

  /** 真实大模型连通性与延迟探测 */
  async diagnosticsLlm(): Promise<LlmDiagnostics> {
    return http.get<LlmDiagnostics>('/assistant/diagnostics/llm')
  },

  /** 完成事项 */
  async toggleComplete(id: number, completed: boolean): Promise<void> {
    const rec = await this.get(id)
    if (rec?.thread_id) {
      await http.post(`/assistant/threads/${rec.thread_id}/reconcile`, {
        status: completed ? 'completed' : 'active',
      })
    }
  },

  /** 获取写笔记草稿（预填标题、双句简介、关注理由、原链接） */
  async getNoteDraft(recordId: number | string): Promise<NoteDraft> {
    const res = await http.get<NoteDraft>(`/assistant/records/${recordId}/note-draft`)
    if (res && res.title) return res
    throw new Error('未获取到笔记草稿')
  },

  /** 建立笔记/事项与助手记录关联 */
  async linkRecord(
    recordId: number | string,
    data: { target_type: 'note' | 'workbench_item'; target_id: string }
  ): Promise<void> {
    if (data.target_type === 'note') {
      await http.post(`/assistant/records/${recordId}/link-note`, { note_id: data.target_id })
    } else {
      await http.post(`/assistant/records/${recordId}/link`, data)
    }
  },

  /** 事项拆分撤销：将误合并的记录拆分为独立事项 */
  async splitSource(threadId: number, recordId: number): Promise<{
    ok: boolean
    old_thread_id: number
    new_thread_id: number
    split_record_id: number
    remaining_count: number
  }> {
    return await http.post(`/assistant/threads/${threadId}/split-source`, { record_id: recordId })
  },

  /** 关联助手记录到工作台事项 */
  async linkWorkbench(recordId: number, wbItemId: number): Promise<{
    ok: boolean
    record_id: number
    wb_item_id: number
    wb_item_title: string
  }> {
    return await http.post(`/assistant/records/${recordId}/link-workbench`, { wb_item_id: wbItemId })
  },

  /** 取消助手记录与工作台事项关联 */
  async unlinkWorkbench(recordId: number): Promise<{ ok: boolean; record_id: number }> {
    return await http.delete(`/assistant/records/${recordId}/link-workbench`)
  },

  /** 获取所有可用工作台事项轻量列表 */
  async getWorkbenchItems(): Promise<{ id: number; title: string; parent_id?: number | null }[]> {
    return await http.get('/assistant/workbench-items')
  },

  /** 真实有据问答对话调用 */
  async chat(message: string, contextRecordId?: number): Promise<string> {
    const res = await http.post<{ answer?: string; sources_used?: number }>('/assistant/chat', {
      query: message,
      record_id: contextRecordId,
    })
    if (res && res.answer) {
      return res.answer
    }
    return '未获取到回答，请检查后台助手状态或稍后重试。'
  },
}
