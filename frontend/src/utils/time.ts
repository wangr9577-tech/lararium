/** 时间容错：全角冒号/空白归一化为 HH:MM（小时补零为两位），非法值返回空（后端会校验） */
export function normTime(v: string): string {
  const t = v.trim().replace(/：/g, ':').replace(/\s+/g, '')
  if (!/^\d{1,2}:\d{2}$/.test(t)) return ''
  const [h, m] = t.split(':')
  return `${h.padStart(2, '0')}:${m}`
}
