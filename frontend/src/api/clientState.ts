/** 客户端业务状态以服务端为准。内存只用于同步读取，写入按键排队并校验版本。 */
import { ElMessage } from 'element-plus'
import { http } from './client'
import { reactive } from 'vue'

type Entry = { value: string; revision: number }
const entries: Record<string, Entry> = {}
const pending = new Map<string, Promise<void>>()
const blocked = new Set<string>()
export const legacyConflicts = reactive<Record<string, { local: string; server: Entry }>>({})
window.addEventListener('beforeunload', (event) => {
  if (!pending.size && !blocked.size) return
  event.preventDefault()
  event.returnValue = ''
})
const keys = new Set([
  'krs_ei…ower', 'krs_pomo_cfg', 'krs_pomo_state', 'krs_pomo_log',
  'krs_pomo_name', 'krs_pomo_names', 'krs_side', 'krs_md_mode',
  'krs_md_follow', 'krs_wb_open_map_v2', 'krs_notes_sort',
  'krs_schedule_deadline_notice',
])
const isManaged = (key: string) => keys.has(key) || key.startsWith('krs_pp_') || key.startsWith('krs_schedule_notice_')

export async function initClientState() {
  Object.assign(entries, await http.get<Record<string, Entry>>('/client-state'))
  // 旧浏览器数据逐键迁移；服务端已有不同值时不覆盖、不删除旧值。
  const legacy = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
    .filter((key): key is string => !!key && isManaged(key))
  let conflicts = 0
  for (const key of legacy) {
    const value = localStorage.getItem(key)
    if (value === null) continue
    if (entries[key]) {
      if (entries[key].value === value) localStorage.removeItem(key)
      else { legacyConflicts[key] = { local: value, server: { ...entries[key] } }; conflicts++ }
      continue
    }
    try {
      const result = await http.put<{ revision: number }>(`/client-state/${encodeURIComponent(key)}`, { value, revision: 0 })
      entries[key] = { value, revision: result.revision }
      localStorage.removeItem(key)
    } catch (error: any) {
      if (error?.response?.status === 409) {
        Object.assign(entries, await http.get<Record<string, Entry>>('/client-state'))
        if (entries[key]?.value === value) localStorage.removeItem(key)
        else if (entries[key]) { legacyConflicts[key] = { local: value, server: { ...entries[key] } }; conflicts++ }
      } else throw error
    }
  }
  if (conflicts) ElMessage.warning({ message: `有 ${conflicts} 项旧浏览器数据与服务端不同，旧值仍保留在浏览器中，请先备份并核对。`, duration: 0, showClose: true })
}

/** 重新读取版本后处理冲突；并发变更时保留浏览器旧值，要求重新核对。 */
export async function resolveLegacyConflict(key: string, choice: 'local' | 'server') {
  const conflict = legacyConflicts[key]
  if (!conflict) return
  if (pending.has(key) || blocked.has(key)) throw new Error('该项有尚未确认的修改，请先刷新页面。')
  const current = (await http.get<Record<string, Entry>>('/client-state'))[key]
  const local = localStorage.getItem(key)
  if (!current || current.revision !== conflict.server.revision || local !== conflict.local) {
    if (current && local !== null) legacyConflicts[key] = { local, server: { ...current } }
    throw new Error('数据已发生变化，请重新核对。')
  }
  if (choice === 'local') {
    const result = await http.put<{ revision: number }>(`/client-state/${encodeURIComponent(key)}`, { value: local, revision: current.revision })
    entries[key] = { value: local!, revision: result.revision }
  } else entries[key] = current
  // 其他标签页可能在请求期间修改旧值，不能删除新值。
  if (localStorage.getItem(key) === local) {
    localStorage.removeItem(key)
    delete legacyConflicts[key]
  } else {
    const latest = localStorage.getItem(key)
    if (latest !== null) legacyConflicts[key] = { local: latest, server: { ...entries[key] } }
    else delete legacyConflicts[key]
    throw new Error('浏览器旧值在处理期间发生变化，请重新备份并核对。')
  }
}

export const clientState = {
  getItem(key: string): string | null { return entries[key]?.value ?? null },
  setItem(key: string, value: string): void {
    if (!isManaged(key)) throw new Error(`不支持的客户端状态键: ${key}`)
    if (legacyConflicts[key]) {
      ElMessage.error('此项存在待核对的旧数据，当前修改未保存，请先处理冲突后刷新页面。')
      return
    }
    if (blocked.has(key)) {
      ElMessage.error('此数据未保存：请先保留当前内容，再刷新页面检查其他设备的更改')
      return
    }
    // 立刻更新内存供当前页面读取，但只有服务器确认后才算持久保存。
    const previous = entries[key]
    entries[key] = { value, revision: previous?.revision || 0 }
    const task = (pending.get(key) || Promise.resolve()).then(async () => {
      if (blocked.has(key)) return
      const result = await http.put<{ revision: number }>(`/client-state/${encodeURIComponent(key)}`, {
        value, revision: entries[key]?.revision || 0,
      })
      entries[key].revision = result.revision
    }).catch((error: any) => {
      blocked.add(key)
      const reason = error?.response?.status === 409 ? '其他设备已修改同一项' : '无法连接服务端'
      ElMessage.error({ message: `保存失败：${reason}。当前修改只在本页面内，请先保留内容并刷新后检查。`, duration: 0, showClose: true })
    })
    pending.set(key, task)
    void task.then(() => { if (pending.get(key) === task) pending.delete(key) })
  },
}
