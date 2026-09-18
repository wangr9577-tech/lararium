<template>
  <div class="page">
    <div class="page-title">钱包</div>
    <div class="page-sub">记收入 / 支出，自动算余额 —— 看看钱都花到哪了</div>

    <!-- 余额与统计 -->
    <div class="glass bal">
      <div class="bal-left">
        <div class="bl">当前余额</div>
        <div class="bal-num" :class="stats.balance < 0 ? 'neg' : ''">¥ {{ fmt(stats.balance) }}</div>
        <div class="bl-sub">起始余额 ¥{{ fmt(stats.start_balance) }}
          <el-button text size="small" type="primary" @click="sbOpen = true">设置</el-button>
        </div>
      </div>
      <div class="bal-right">
        <div class="bal-stat"><span class="bs-lab">本月收入</span><span class="bs-num in">+¥{{ fmt(stats.month.income) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月支出</span><span class="bs-num out">-¥{{ fmt(stats.month.expense) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月结余</span><span class="bs-num" :class="monthBalance < 0 ? 'neg' : 'ok'">¥{{ fmt(monthBalance) }}</span></div>
      </div>
    </div>

    <!-- 月份切换 -->
    <div class="glass mbar">
      <el-button text circle size="small" @click="moveMonth(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
      <span class="mlabel grad-text">{{ ymLabel }}</span>
      <el-button text circle size="small" @click="moveMonth(1)"><el-icon><ArrowRight /></el-icon></el-button>
      <el-button size="small" round @click="goNow">本月</el-button>
      <span class="mcnt">{{ items.length }} 笔</span>
    </div>

    <!-- 快速记账 -->
    <div ref="formEl" class="glass form" :class="{ editing: !!editingId }">
      <el-radio-group v-model="form.kind" size="small">
        <el-radio-button value="expense">支出</el-radio-button>
        <el-radio-button value="income">收入</el-radio-button>
      </el-radio-group>
      <el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 140px" />
      <el-input v-model="form.amount" size="small" type="number" placeholder="金额（元）" class="amt" @keyup.enter="save" />
      <el-input v-model="form.category" size="small" placeholder="分类（自由填写，如：餐饮）" class="cat" list="cat-list" />
      <datalist id="cat-list">
        <option v-for="c in usedCats" :key="c" :value="c" />
      </datalist>
      <el-input v-model="form.note" size="small" placeholder="备注（可空）" class="note" @keyup.enter="save" />
      <el-button type="primary" size="small" @click="save">{{ editingId ? '保存修改' : '记一笔' }}</el-button>
      <el-button v-if="editingId" size="small" @click="resetForm">取消</el-button>
    </div>

    <div class="cols">
      <!-- 明细 -->
      <div class="glass list-card">
        <div class="lc-head">
          <span class="lc-t">明细</span>
          <div class="chips">
            <button v-for="k in kindTabs" :key="k.value" class="ttab" :class="{ on: kind === k.value }" @click="kind = k.value">{{ k.label }}</button>
          </div>
        </div>
        <div v-if="filtered.length" class="rows">
          <div v-for="it in filtered" :key="it.id" class="lrow">
            <span class="ldate">{{ it.date.slice(5) }}</span>
            <span class="lcat" v-if="it.category">{{ it.category }}</span>
            <span class="lnote">{{ it.note }}</span>
            <span class="lsum" :class="it.kind">{{ it.kind === 'income' ? '+' : '-' }}¥{{ fmt(it.amount_yuan) }}</span>
            <el-button text size="small" @click="editRow(it)">改</el-button>
            <el-button text size="small" type="danger" @click="del(it)">删</el-button>
          </div>
          <div v-if="!filtered.length && items.length" class="empty">该筛选下暂无记录</div>
        </div>
        <div v-else class="empty">这个月还没有账目 —— 在上面记一笔吧。</div>
      </div>

      <!-- 统计：钱花哪了 -->
      <div class="glass stats-card">
        <div class="lc-head"><span class="lc-t">钱花哪了</span>
          <el-radio-group v-model="scope" size="small">
            <el-radio-button value="month">本月</el-radio-button>
            <el-radio-button value="all">全部</el-radio-button>
          </el-radio-group>
        </div>

        <div class="st-sec">
          <div class="st-t">支出去向</div>
          <div v-if="expBreak.length" class="bars">
            <div v-for="b in expBreak" :key="b.category" class="bar-row">
              <span class="b-cat">{{ b.category }} <small>({{ b.count }})</small></span>
              <div class="b-track"><div class="b-fill out" :style="{ width: pct(b.amount, expTotal) + '%' }" /></div>
              <span class="b-amt">¥{{ fmt(b.amount) }}</span>
              <span class="b-pct">{{ pct(b.amount, expTotal) }}%</span>
            </div>
          </div>
          <div v-else class="empty">暂无支出</div>
        </div>

        <div class="st-sec" v-if="incBreak.length">
          <div class="st-t">收入来源</div>
          <div class="bars">
            <div v-for="b in incBreak" :key="b.category" class="bar-row">
              <span class="b-cat">{{ b.category }} <small>({{ b.count }})</small></span>
              <div class="b-track"><div class="b-fill in" :style="{ width: pct(b.amount, incTotal) + '%' }" /></div>
              <span class="b-amt">¥{{ fmt(b.amount) }}</span>
            </div>
          </div>
        </div>

        <div class="st-sec" v-if="scope === 'all'">
          <div class="st-t">近 6 个月趋势</div>
          <div class="trend">
            <div v-for="t in stats.trend" :key="t.month" class="t-col">
              <div class="t-bar">
                <div class="t-fill out" :style="{ height: h(t.expense) + 'px' }" :title="'支出 ¥' + t.expense" />
                <div class="t-fill in" :style="{ height: h(t.income) + 'px' }" :title="'收入 ¥' + t.income" />
              </div>
              <div class="t-lab">{{ t.month.slice(5) }}</div>
            </div>
          </div>
          <div class="trend-legend"><span><i class="dot out" />支出</span><span><i class="dot in" />收入</span></div>
        </div>
      </div>
    </div>

    <!-- 起始余额设置 -->
    <el-dialog v-model="sbOpen" title="起始余额" width="360px">
      <el-input-number v-model="sbVal" :min="-1e9" :max="1e9" :precision="2" style="width: 100%" />
      <p class="hint">余额 = 起始余额 + 累计收入 − 累计支出。只影响展示，不改动历史记录。</p>
      <template #footer>
        <el-button @click="sbOpen = false">取消</el-button>
        <el-button type="primary" @click="saveStartBalance">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { http } from '../api/client'

interface Row { id: number; date: string; kind: string; amount: number; amount_yuan: number; category: string; note: string }
interface Stats { balance: number; start_balance: number; total: { income: number; expense: number }; month: { ym: string; income: number; expense: number; income_count: number; expense_count: number; expense_by_category: { category: string; amount: number; count: number }[]; income_by_category: { category: string; amount: number; count: number }[] }; trend: { month: string; income: number; expense: number }[] }

const formEl = ref<HTMLDivElement>()
const pad = (n: number) => String(n).padStart(2, '0')
// P2-M1：一律用本地时间取日/月。toISOString 是 UTC——东八区每天 00:00–07:59
// 打开会拿到"昨天"、每月 1 日早晨整页跳上月，与后端本地时间统计对不上。
const localYmd = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const localYm = () => localYmd().slice(0, 7)
const curYm = ref(localYm())
const items = ref<Row[]>([])
const stats = reactive<Stats>({ balance: 0, start_balance: 0, total: { income: 0, expense: 0 }, month: { ym: '', income: 0, expense: 0, income_count: 0, expense_count: 0, expense_by_category: [], income_by_category: [] }, trend: [] })
const kind = ref('')
const scope = ref<'month' | 'all'>('month')
const sbOpen = ref(false)
const sbVal = ref(0)
const form = reactive({ kind: 'expense', date: localYmd(), amount: '' as any, category: '', note: '' })
const editingId = ref<number | null>(null)
let allRows: Row[] = []

const ymLabel = computed(() => { const [y, m] = curYm.value.split('-'); return `${y} 年 ${Number(m)} 月` })
const monthBalance = computed(() => stats.month.income - stats.month.expense)
const filtered = computed(() => items.value.filter((x) => !kind.value || x.kind === kind.value))
const kindTabs = [{ value: '', label: '全部' }, { value: 'expense', label: '支出' }, { value: 'income', label: '收入' }]
const usedCats = computed(() => { const s = new Set<string>(); for (const r of allRows) if (r.category) s.add(r.category); return [...s] })

function fmt(v: number) { return (v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pct(v: number, total: number) { return total > 0 ? Math.round((v / total) * 100) : 0 }

const expBreak = computed(() => scope.value === 'month' ? stats.month.expense_by_category : groupBy(allRows.filter((r) => r.kind === 'expense')))
const incBreak = computed(() => scope.value === 'month' ? stats.month.income_by_category : groupBy(allRows.filter((r) => r.kind === 'income')))
const expTotal = computed(() => expBreak.value.reduce((a, b) => a + b.amount, 0))
const incTotal = computed(() => incBreak.value.reduce((a, b) => a + b.amount, 0))

function groupBy(rows: Row[]): { category: string; amount: number; count: number }[] {
  const m = new Map<string, { amount: number; count: number }>()
  for (const r of rows) {
    const k = r.category || '（未分类）'
    const e = m.get(k) || { amount: 0, count: 0 }
    e.amount += r.amount_yuan; e.count += 1
    m.set(k, e)
  }
  return [...m.entries()].map(([category, v]) => ({ category, amount: Math.round(v.amount * 100) / 100, count: v.count })).sort((a, b) => b.amount - a.amount)
}
function h(v: number) { const max = Math.max(...stats.trend.map((t) => Math.max(t.income, t.expense)), 1); return Math.round((v / max) * 70) }

function moveMonth(d: number) {
  const [y, m] = curYm.value.split('-').map(Number)
  const dt = new Date(y, m - 1 + d, 1)
  curYm.value = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}`
}
function goNow() { curYm.value = localYm() }

async function load() {
  try {
    const [r, s] = await Promise.all([
      http.get<{ items: Row[] }>(`/ledger?month=${curYm.value}${kind.value ? '&kind=' + kind.value : ''}`),
      http.get<Stats>(`/ledger/stats?month=${curYm.value}`),
    ])
    items.value = r.items
    Object.assign(stats, s)
    // 全部记录（供全部去向统计/候选分类）
    const all = await http.get<{ items: Row[] }>('/ledger')
    allRows = all.items
  } catch { /* ignore */ }
}

async function save() {
  const amt = Number(form.amount)
  if (!form.date) return ElMessage.warning('请选择日期')
  if (!(amt > 0)) return ElMessage.warning('请输入金额')
  const body = { date: form.date, kind: form.kind, amount: amt, category: form.category.trim(), note: form.note.trim() }
  try {
    if (editingId.value) await http.put(`/ledger/${editingId.value}`, body)
    else await http.post('/ledger', body)
    ElMessage.success(editingId.value ? '已更新' : '已记一笔')
    resetForm()
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

function editRow(r: Row) {
  editingId.value = r.id
  form.kind = r.kind
  form.date = r.date
  form.amount = r.amount_yuan
  form.category = r.category
  form.note = r.note
  ElMessage.info('已载入该笔，请在上面修改后点「保存修改」')
  nextTick(() => {
    formEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
function resetForm() {
  editingId.value = null
  form.kind = 'expense'
  form.date = localYmd()
  form.amount = ''
  form.category = ''
  form.note = ''
}
async function del(r: Row) {
  try { await ElMessageBox.confirm('删除这笔记录？', '确认删除', { type: 'warning' }) } catch { return }
  try { await http.del(`/ledger/${r.id}`); load() } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

async function saveStartBalance() {
  try {
    await http.put('/settings', { updates: { 'ledger.start_balance': sbVal.value } })
    sbOpen.value = false
    ElMessage.success('已保存')
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

onMounted(() => { sbVal.value = stats.start_balance; load() })
</script>

<style scoped>
.bal { display: flex; align-items: center; gap: 30px; padding: 20px 26px; margin-bottom: 14px; flex-wrap: wrap; }
.bl { font-size: 13px; color: var(--txt2); }
.bal-num { font-size: 42px; font-weight: 900; line-height: 1.15; color: var(--acc2); }
.bal-num.neg { color: #f43f5e; }
.bl-sub { font-size: 12px; color: var(--txt2); }
.bal-right { display: flex; gap: 28px; flex-wrap: wrap; margin-left: auto; }
.bal-stat { display: grid; gap: 2px; min-width: 92px; }
.bs-lab { font-size: 12px; color: var(--txt2); }
.bs-num { font-weight: 800; font-size: 16px; }
.bs-num.in { color: #16a34a; } .bs-num.out { color: #dc2626; }
.bs-num.neg { color: #f43f5e; } .bs-num.ok { color: var(--acc2); }

.mbar { display: flex; align-items: center; gap: 6px; padding: 8px 14px; margin-bottom: 12px; }
.mlabel { font-weight: 800; font-size: 17px; min-width: 120px; text-align: center; }
.mcnt { margin-left: auto; color: var(--txt2); font-size: 12px; }

.form { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 16px; margin-bottom: 14px; }
.amt { width: 130px; } .cat { width: 150px; } .note { width: 180px; flex: 1; min-width: 120px; }
.form.editing { outline: 2px solid var(--acc2); outline-offset: 3px; border-radius: 18px; }

.cols { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
.list-card, .stats-card { padding: 14px 16px; }
.lc-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 10px; flex-wrap: wrap; }
.lc-t { font-weight: 700; }
.chips { display: flex; gap: 4px; }
.ttab { border: none; background: transparent; cursor: pointer; color: var(--txt2); padding: 4px 12px; border-radius: 999px; font-size: 13px; font-family: inherit; }
.ttab.on { background: var(--acc-grad); color: #fff; font-weight: 700; }
.rows { display: grid; }
.lrow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; font-size: 13.5px; }
.lrow:nth-child(odd) { background: rgba(148, 163, 184, 0.06); }
.ldate { color: var(--txt2); font-size: 12px; flex: none; }
.lcat { background: rgba(167, 139, 250, 0.14); color: var(--acc2); border-radius: 6px; padding: 0 8px; font-size: 12px; flex: none; }
.lnote { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--txt3); }
.lsum { font-weight: 800; flex: none; }
.lsum.income { color: #16a34a; } .lsum.expense { color: #dc2626; }
.empty { color: var(--txt2); font-size: 13px; padding: 18px 4px; }

.st-sec { margin-top: 14px; }
.st-t { font-weight: 700; font-size: 14px; margin-bottom: 8px; }
.bars { display: grid; gap: 6px; }
.bar-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.b-cat { width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--txt2); }
.b-cat small { color: var(--txt3); }
.b-track { flex: 1; height: 14px; background: rgba(148, 163, 184, 0.14); border-radius: 7px; overflow: hidden; }
.b-fill { height: 100%; border-radius: 7px; transition: width .3s; }
.b-fill.out { background: linear-gradient(90deg, #f87171, #f43f5e); }
.b-fill.in { background: linear-gradient(90deg, #34d399, #10b981); }
.b-amt { width: 86px; text-align: right; font-weight: 700; flex: none; }
.b-pct { width: 44px; text-align: right; color: var(--txt2); flex: none; font-size: 12px; }

.trend { display: flex; align-items: flex-end; gap: 10px; height: 90px; padding: 4px 0; }
.t-col { display: flex; flex-direction: column; align-items: center; flex: 1; gap: 4px; }
.t-bar { display: flex; align-items: flex-end; gap: 3px; height: 74px; width: 100%; justify-content: center; }
.t-fill { width: 12px; border-radius: 3px 3px 0 0; }
.t-fill.out { background: #f43f5e; } .t-fill.in { background: #22c55e; }
.t-lab { font-size: 11px; color: var(--txt2); }
.trend-legend { display: flex; gap: 16px; margin-top: 6px; font-size: 12px; color: var(--txt2); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 4px; }
.dot.out { background: #f43f5e; } .dot.in { background: #22c55e; }
.hint { color: var(--txt2); font-size: 12.5px; margin: 10px 0 0; }
</style>
