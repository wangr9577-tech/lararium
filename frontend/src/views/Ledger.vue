<template>
  <div class="page">
    <div class="page-title">钱包</div>
    <div class="page-sub">记收入 / 支出 / 欠款，自动算可用余额与净资产 —— 看看钱都花到哪了</div>

    <!-- 余额与统计 -->
    <div class="glass bal">
      <div class="bal-left">
        <div class="bl">可用余额（现金）</div>
        <div class="bal-num" :class="stats.balance < 0 ? 'neg' : ''">¥ {{ fmt(stats.balance) }}</div>
        <div class="bl-sub">起始余额 ¥{{ fmt(stats.start_balance) }}
          <el-button text size="small" type="primary" @click="openSb">设置</el-button>
        </div>
      </div>
      <div class="bal-right">
        <div class="bal-stat"><span class="bs-lab">欠款合计</span><span class="bs-num debt">{{ stats.debt.owed_total > 0 ? '-' : '' }}¥{{ fmt(stats.debt.owed_total) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">净资产</span><span class="bs-num" :class="stats.net_worth < 0 ? 'neg' : 'ok'">¥{{ fmt(stats.net_worth) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月收入</span><span class="bs-num in">+¥{{ fmt(stats.month.income) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月支出（现金）</span><span class="bs-num out">{{ stats.month.expense > 0 ? '-' : '' }}¥{{ fmt(stats.month.expense) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月信用消费</span><span class="bs-num debt">{{ stats.month.debt_expense > 0 ? '-' : '' }}¥{{ fmt(stats.month.debt_expense) }}</span></div>
        <div class="bal-stat"><span class="bs-lab">本月结余（现金）</span><span class="bs-num" :class="monthBalance < 0 ? 'neg' : 'ok'">¥{{ fmt(monthBalance) }}</span></div>
      </div>
    </div>

    <!-- 欠款（单列）：花呗 / 京东白条 / 美团月付 / 抖音月付 … 用分类名识别 -->
    <div class="glass debt-card">
      <div class="dc-head">
        <span class="lc-t">欠款</span>
        <span class="dc-total">待还 <b :class="stats.debt.owed_total > 0 ? 'out' : 'ok'">¥{{ fmt(stats.debt.owed_total) }}</b></span>
        <span class="dc-sub">本月新增 ¥{{ fmt(stats.debt.month_spent) }} · 本月已还 ¥{{ fmt(stats.debt.month_repaid) }} · 累计已还 ¥{{ fmt(stats.debt.repaid_total) }}</span>
        <div class="dc-btns">
          <el-button size="small" round @click="openChMgr">管理渠道</el-button>
          <el-button size="small" round type="primary" plain @click="openRepay()">记还款</el-button>
        </div>
      </div>
      <div v-if="activeChannels.length" class="dc-rows">
        <div v-for="c in activeChannels" :key="c.channel" class="dc-row">
          <span class="dc-ch">{{ c.channel }}</span>
          <span class="dc-owed" :class="c.owed > 0 ? 'out' : 'ok'">{{ c.owed > 0 ? '待还 ¥' + fmt(c.owed) : (c.owed < 0 ? '多还 ¥' + fmt(-c.owed) : '已还清') }}</span>
          <span class="dc-meta">本月 +¥{{ fmt(c.month_spent) }}<template v-if="c.month_repaid"> · 还 ¥{{ fmt(c.month_repaid) }}</template> · 累计 {{ c.count }} 笔</span>
          <el-button text size="small" type="primary" @click="openRepay(c.channel)">还款</el-button>
        </div>
      </div>
      <div v-else class="empty">
        还没有欠款记录 —— 用花呗 / 白条这类渠道消费时，把「分类」写成渠道名（如 <b>花呗</b>）就会自动计入这里，不再当成现金支出。
      </div>
      <div class="dc-foot">
        渠道清单：<span v-for="c in channels" :key="c" class="ch-pill">{{ c }}</span>
        <span v-if="!channels.length" class="hint">（清单为空——所有支出都按现金支出算）</span>
      </div>
    </div>

    <!-- 月份切换 -->
    <div class="glass mbar">
      <el-button text circle size="small" @click="moveMonth(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
      <span class="mlabel grad-text">{{ ymLabel }}</span>
      <el-button text circle size="small" @click="moveMonth(1)"><el-icon><ArrowRight /></el-icon></el-button>
      <el-button size="small" round @click="goNow">本月</el-button>
      <el-button size="small" round type="danger" plain @click="openClear">清空…</el-button>
      <span class="mcnt">{{ filtered.length }} 笔</span>
    </div>

    <!-- 快速记账 -->
    <div ref="formEl" class="glass form" :class="{ editing: !!editingId }">
      <el-radio-group v-model="form.kind" size="small">
        <el-radio-button value="expense">支出</el-radio-button>
        <el-radio-button value="income">收入</el-radio-button>
        <el-radio-button value="repay">还款</el-radio-button>
      </el-radio-group>
      <el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 140px" />
      <el-input v-model="form.amount" size="small" type="number" placeholder="金额（元）" class="amt" @keyup.enter="save" />
      <el-select v-if="form.kind === 'repay'" v-model="form.channel" size="small" placeholder="还款渠道" class="cat">
        <el-option v-for="c in channels" :key="c" :label="c" :value="c" />
      </el-select>
      <template v-else>
        <el-input v-model="form.category" size="small" placeholder="分类（写「花呗」等渠道名即算欠款）" class="cat" list="cat-list" />
        <datalist id="cat-list">
          <option v-for="c in catOptions" :key="c" :value="c" />
        </datalist>
      </template>
      <el-input v-model="form.note" size="small" placeholder="备注（可空）" class="note" @keyup.enter="save" />
      <el-button type="primary" size="small" @click="save">{{ editingId ? '保存修改' : (form.kind === 'repay' ? '记还款' : '记一笔') }}</el-button>
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
        <div v-if="kind === 'debt' && debtChannelsInMonth.length" class="chips dchips">
          <button class="ttab" :class="{ on: !debtCh }" @click="debtCh = ''">全部渠道</button>
          <button v-for="c in debtChannelsInMonth" :key="c" class="ttab" :class="{ on: debtCh === c }" @click="debtCh = c">{{ c }}</button>
        </div>
        <div v-if="filtered.length" class="rows">
          <div v-for="it in filtered" :key="it.id" class="lrow">
            <span class="ldate">{{ it.date.slice(5) }}</span>
            <span v-if="it.is_debt" class="lcat debt">{{ it.category }}</span>
            <span v-else-if="it.category" class="lcat">{{ it.category }}</span>
            <span v-if="rowTag(it)" class="ltag" :class="{ repay: it.kind === 'repay' }">{{ rowTag(it) }}</span>
            <span class="lnote">{{ it.note }}</span>
            <span class="lsum" :class="rowCls(it)">{{ rowAmt(it) }}</span>
            <el-button text size="small" @click="editRow(it)">改</el-button>
            <el-button text size="small" type="danger" @click="del(it)">删</el-button>
          </div>
        </div>
        <div v-else-if="items.length" class="empty">该筛选下暂无记录 —— 点上面「全部」看这个月的所有账目。</div>
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
          <div class="st-t">支出去向（现金）</div>
          <div v-if="expBreak.length" class="bars">
            <div v-for="b in expBreak" :key="b.category" class="bar-row">
              <span class="b-cat">{{ b.category }} <small>({{ b.count }})</small></span>
              <div class="b-track"><div class="b-fill out" :style="{ width: pct(b.amount, expTotal) + '%' }" /></div>
              <span class="b-amt">¥{{ fmt(b.amount) }}</span>
              <span class="b-pct">{{ pct(b.amount, expTotal) }}%</span>
            </div>
          </div>
          <div v-else class="empty">暂无现金支出（信用消费见下方「欠款去向」）</div>
        </div>

        <div class="st-sec">
          <div class="st-t">欠款去向（信用消费）</div>
          <div v-if="debtBreak.length" class="bars">
            <div v-for="b in debtBreak" :key="b.label" class="bar-row">
              <span class="b-cat">{{ b.label }} <small>({{ b.count }})</small></span>
              <div class="b-track"><div class="b-fill debt" :style="{ width: pct(b.amount, debtTotal) + '%' }" /></div>
              <span class="b-amt">¥{{ fmt(b.amount) }}</span>
              <span class="b-pct">{{ pct(b.amount, debtTotal) }}%</span>
            </div>
          </div>
          <div v-else class="empty">这段时间没有信用消费</div>
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
                <div class="t-fill out" :style="{ height: h(t.expense) + 'px' }" :title="'现金支出 ¥' + t.expense" />
                <div class="t-fill in" :style="{ height: h(t.income) + 'px' }" :title="'收入 ¥' + t.income" />
                <div class="t-fill dbt" :style="{ height: h(t.debt_expense) + 'px' }" :title="'信用消费 ¥' + t.debt_expense" />
              </div>
              <div class="t-lab">{{ t.month.slice(5) }}</div>
            </div>
          </div>
          <div class="trend-legend">
            <span><i class="dot out" />现金支出</span>
            <span><i class="dot in" />收入</span>
            <span><i class="dot dbt" />信用消费</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 还款 -->
    <el-dialog v-model="rpOpen" title="记一笔还款" width="420px">
      <div class="rp-form">
        <el-select v-model="rp.channel" placeholder="选择渠道" style="width: 100%">
          <el-option v-for="c in channels" :key="c" :label="c" :value="c" />
        </el-select>
        <div class="rp-owed">该渠道当前待还：<b :class="rpOwed > 0 ? 'out' : 'ok'">¥{{ fmt(rpOwed) }}</b></div>
        <el-input v-model="rp.amount" type="number" placeholder="还款金额（元）" />
        <el-date-picker v-model="rp.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        <el-input v-model="rp.note" placeholder="备注（可空）" />
      </div>
      <p class="hint">还款会冲减该渠道欠款，并真实减少可用余额（钱确实还出去了）。</p>
      <template #footer>
        <el-button @click="rpOpen = false">取消</el-button>
        <el-button type="primary" @click="doRepay">确认还款</el-button>
      </template>
    </el-dialog>

    <!-- 欠款渠道管理 -->
    <el-dialog v-model="chOpen" title="欠款渠道" width="460px">
      <p class="hint">分类名与下面清单完全一致的支出，会计入「欠款」而不扣现金余额。默认：花呗、京东白条、美团月付、抖音月付等。</p>
      <div class="ch-tags">
        <el-tag v-for="c in chList" :key="c" closable type="warning" effect="plain" @close="rmCh(c)">{{ c }}</el-tag>
        <span v-if="!chList.length" class="hint">清单为空：所有支出都按现金支出算。</span>
      </div>
      <div class="ch-add">
        <el-input v-model="chNew" size="small" placeholder="新增渠道，如：抖音月付" @keyup.enter="addCh()" />
        <el-button size="small" @click="addCh()">添加</el-button>
      </div>
      <div v-if="chCandidates.length" class="ch-cand">
        <span class="hint">记账里用过、还没进清单的分类（点一下加入）：</span>
        <el-tag v-for="c in chCandidates" :key="c" size="small" effect="plain" class="cand" @click="addCh(c)">{{ c }}</el-tag>
      </div>
      <p class="hint">从清单里删掉的渠道，它的支出会重新算作普通现金支出（<b>历史记录不会被改动</b>）。</p>
      <template #footer>
        <el-button @click="chOpen = false">取消</el-button>
        <el-button type="primary" @click="saveCh">保存</el-button>
      </template>
    </el-dialog>

    <!-- 起始余额设置 -->
    <el-dialog v-model="sbOpen" title="起始余额" width="360px">
      <el-input-number v-model="sbVal" :min="-1e9" :max="1e9" :precision="2" style="width: 100%" />
      <p class="hint">可用余额 = 起始余额 + 累计收入 − 累计现金支出 − 累计还款。只影响展示，不改动历史记录。</p>
      <template #footer>
        <el-button @click="sbOpen = false">取消</el-button>
        <el-button type="primary" @click="saveStartBalance">保存</el-button>
      </template>
    </el-dialog>

    <!-- 清空（危险操作：服务端会先把待删记录导出 JSON 存档） -->
    <el-dialog v-model="clearOpen" title="清空记录" width="460px">
      <el-radio-group v-model="clearScope" size="small">
        <el-radio-button value="month">本月（{{ ymLabel }}）</el-radio-button>
        <el-radio-button value="all">全部记录</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="clearOnlyDebt" class="cl-debt">只清欠款相关记录（渠道信用消费 + 还款）</el-checkbox>
      <p class="hint danger">
        将删除 <b>{{ clearRows.length }}</b> 笔记录，合计 ¥{{ fmt(clearTotal) }}。
        删除前服务端会先把这些记录导出成 JSON 存档（保留可回溯），但删除本身不可撤销。
      </p>
      <p class="hint">起始余额（¥{{ fmt(stats.start_balance) }}）不受影响，需要时在余额卡片处单独调整。</p>
      <template #footer>
        <el-button @click="clearOpen = false">取消</el-button>
        <el-button type="danger" :disabled="!clearRows.length" @click="doClear">确认清空</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { http } from '../api/client'

interface Row { id: number; date: string; kind: string; amount: number; amount_yuan: number; category: string; note: string; is_debt: boolean; channel: string }
interface CatAgg { category: string; amount: number; count: number }
interface ChStat { channel: string; spent: number; repaid: number; owed: number; count: number; month_spent: number; month_repaid: number; month_count: number }
interface DebtChAgg { channel: string; amount: number; count: number; repaid: number }
interface Stats {
  balance: number; start_balance: number; net_worth: number; debt_channels: string[]
  total: { income: number; expense: number; debt_expense: number; repay: number }
  debt: { owed_total: number; spent_total: number; repaid_total: number; month_spent: number; month_repaid: number; channels: ChStat[] }
  month: {
    ym: string; income: number; expense: number; debt_expense: number; repay: number
    income_count: number; expense_count: number; debt_count: number; repay_count: number
    expense_by_category: CatAgg[]; income_by_category: CatAgg[]; debt_by_channel: DebtChAgg[]
  }
  trend: { month: string; income: number; expense: number; debt_expense: number; repay: number }[]
}

const formEl = ref<HTMLDivElement>()
const pad = (n: number) => String(n).padStart(2, '0')
// P2-M1：一律用本地时间取日/月。toISOString 是 UTC——东八区每天 00:00–07:59
// 打开会拿到"昨天"、每月 1 日早晨整页跳上月，与后端本地时间统计对不上。
const localYmd = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const localYm = () => localYmd().slice(0, 7)
const curYm = ref(localYm())
const items = ref<Row[]>([])
const channels = ref<string[]>([])
const stats = reactive<Stats>({
  balance: 0, start_balance: 0, net_worth: 0, debt_channels: [],
  total: { income: 0, expense: 0, debt_expense: 0, repay: 0 },
  debt: { owed_total: 0, spent_total: 0, repaid_total: 0, month_spent: 0, month_repaid: 0, channels: [] },
  month: {
    ym: '', income: 0, expense: 0, debt_expense: 0, repay: 0,
    income_count: 0, expense_count: 0, debt_count: 0, repay_count: 0,
    expense_by_category: [], income_by_category: [], debt_by_channel: [],
  },
  trend: [],
})
const kind = ref('')
const debtCh = ref('')
const scope = ref<'month' | 'all'>('month')
const sbOpen = ref(false)
const sbVal = ref(0)
const clearOpen = ref(false)
const clearScope = ref<'month' | 'all'>('month')
const clearOnlyDebt = ref(false)
const rpOpen = ref(false)
const rp = reactive({ date: localYmd(), channel: '', amount: '' as any, note: '' })
const chOpen = ref(false)
const chList = ref<string[]>([])
const chNew = ref('')
const form = reactive({ kind: 'expense', date: localYmd(), amount: '' as any, category: '', channel: '', note: '' })
const editingId = ref<number | null>(null)
const allRows = ref<Row[]>([])

const ymLabel = computed(() => { const [y, m] = curYm.value.split('-'); return `${y} 年 ${Number(m)} 月` })
const monthBalance = computed(() => Math.round((stats.month.income - stats.month.expense - stats.month.repay) * 100) / 100)
// 欠款 tab 下按渠道再筛一层
const filtered = computed(() => items.value.filter((x) => {
  if (!kind.value) return true
  if (kind.value === 'debt') return isDebtRow(x) && (!debtCh.value || x.category === debtCh.value)
  if (kind.value === 'expense') return x.kind === 'expense' && !x.is_debt
  return x.kind === kind.value
}))
const kindTabs = [{ value: '', label: '全部' }, { value: 'expense', label: '支出' }, { value: 'income', label: '收入' }, { value: 'debt', label: '欠款' }]
const usedCats = computed(() => { const s = new Set<string>(); for (const r of allRows.value) if (r.category) s.add(r.category); return [...s] })
// 分类候选：欠款渠道排前面（写渠道名即自动算欠款），再是记账里用过的分类
const catOptions = computed(() => [...channels.value, ...usedCats.value.filter((c) => !channels.value.includes(c))])
const debtChannelsInMonth = computed(() => [...new Set(items.value.filter(isDebtRow).map((x) => x.category))].filter(Boolean))
const activeChannels = computed(() => stats.debt.channels.filter((c) => c.spent || c.repaid))
const chCandidates = computed(() => usedCats.value.filter((c) => !chList.value.includes(c)).slice(0, 20))
const rpOwed = computed(() => stats.debt.channels.find((c) => c.channel === rp.channel)?.owed ?? 0)

// 清空预览：本月用当前月列表，全部用全量列表；可选只清欠款相关记录
const clearRows = computed<Row[]>(() => {
  const base = clearScope.value === 'month' ? items.value : allRows.value
  return clearOnlyDebt.value ? base.filter(isDebtRow) : base
})
const clearTotal = computed(() => Math.round(clearRows.value.reduce((a, r) => a + r.amount_yuan, 0) * 100) / 100)

function fmt(v: number) { return (v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pct(v: number, total: number) { return total > 0 ? Math.round((v / total) * 100) : 0 }
// 欠款相关行 = 渠道信用消费（is_debt）或还款（kind=repay；渠道被删的老还款也要看得见）
function isDebtRow(r: Row) { return r.is_debt || r.kind === 'repay' }

const expBreak = computed(() => scope.value === 'month' ? stats.month.expense_by_category : groupBy(allRows.value.filter((r) => r.kind === 'expense' && !r.is_debt)))
const incBreak = computed(() => scope.value === 'month' ? stats.month.income_by_category : groupBy(allRows.value.filter((r) => r.kind === 'income')))
const debtBreak = computed(() => scope.value === 'month'
  ? stats.month.debt_by_channel.map((x) => ({ label: x.channel, amount: x.amount, count: x.count }))
  : stats.debt.channels.filter((c) => c.spent > 0).map((c) => ({ label: c.channel, amount: c.spent, count: c.count })))
const expTotal = computed(() => expBreak.value.reduce((a, b) => a + b.amount, 0))
const incTotal = computed(() => incBreak.value.reduce((a, b) => a + b.amount, 0))
const debtTotal = computed(() => debtBreak.value.reduce((a, b) => a + b.amount, 0))

function groupBy(rows: Row[]): CatAgg[] {
  const m = new Map<string, { amount: number; count: number }>()
  for (const r of rows) {
    const k = r.category || '（未分类）'
    const e = m.get(k) || { amount: 0, count: 0 }
    e.amount += r.amount_yuan; e.count += 1
    m.set(k, e)
  }
  return [...m.entries()].map(([category, v]) => ({ category, amount: Math.round(v.amount * 100) / 100, count: v.count })).sort((a, b) => b.amount - a.amount)
}
function h(v: number) { const max = Math.max(...stats.trend.map((t) => Math.max(t.income, t.expense, t.debt_expense)), 1); return Math.round((v / max) * 70) }

// 行内金额展示：收入 +¥ / 现金支出 -¥ / 信用消费「欠 ¥」/ 还款「还 ¥」
function rowTag(it: Row) { return it.kind === 'repay' ? '还款' : (it.is_debt ? '欠款' : '') }
function rowCls(it: Row) { return it.kind === 'income' ? 'income' : it.kind === 'repay' ? 'repay' : (it.is_debt ? 'debt' : 'expense') }
function rowAmt(it: Row) {
  const s = '¥' + fmt(it.amount_yuan)
  if (it.kind === 'income') return '+' + s
  if (it.kind === 'repay') return '还 ' + s
  return (it.is_debt ? '欠 ' : '-') + s
}

function moveMonth(d: number) {
  const [y, m] = curYm.value.split('-').map(Number)
  const dt = new Date(y, m - 1 + d, 1)
  curYm.value = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}`
}
// 切月必须重新拉数据（原实现只改了标题变量，明细/统计一直停在上一个月）；
// 切月时若正在编辑某笔，先退出编辑，免得「保存修改」改到当前看不见的记录。
watch(curYm, (ym) => {
  if (editingId.value) { resetForm(); ElMessage.info(`已切到 ${ym}，退出该笔的编辑`) }
  debtCh.value = ''
  load()
})
function goNow() {
  // 已经在本月时 watch 不会触发，所以这里手动刷一次（「本月」也当刷新按钮用）
  if (curYm.value === localYm()) load()
  else curYm.value = localYm()
}

async function load() {
  try {
    // 只按月份拉整月：kind 全部交给前端 filtered 过滤。原实现把 kind 塞进 URL，
    // 与服务端 SQL 过滤叠加——在「支出」tab 下记账/删账后再点「全部」，收入行会消失。
    // 若正在编辑的那笔已不在新列表里（被删/清空/跨月），退出编辑态。
    const [r, s] = await Promise.all([
      http.get<{ items: Row[] }>(`/ledger?month=${curYm.value}`),
      http.get<Stats>(`/ledger/stats?month=${curYm.value}`),
    ])
    items.value = r.items
    Object.assign(stats, s)
    channels.value = s.debt_channels || []
    // 全部记录（供全部去向统计/候选分类/清空预览）
    const all = await http.get<{ items: Row[] }>('/ledger')
    allRows.value = all.items
    if (editingId.value && !allRows.value.some((x) => x.id === editingId.value)) resetForm()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败，请稍后重试')
  }
}

async function save() {
  const amt = Number(form.amount)
  if (!form.date) return ElMessage.warning('请选择日期')
  if (!(amt > 0)) return ElMessage.warning('请输入金额')
  if (form.kind === 'repay' && !form.channel) return ElMessage.warning('请选择还款渠道')
  const body = {
    date: form.date, kind: form.kind, amount: amt,
    category: form.kind === 'repay' ? form.channel : form.category.trim(),
    note: form.note.trim(),
  }
  try {
    if (editingId.value) await http.put(`/ledger/${editingId.value}`, body)
    else await http.post('/ledger', body)
    ElMessage.success(editingId.value ? '已更新' : (form.kind === 'repay' ? '已记还款' : '已记一笔'))
    resetForm()
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

function editRow(r: Row) {
  editingId.value = r.id
  form.kind = r.kind
  form.date = r.date
  form.amount = r.amount_yuan
  form.note = r.note
  if (r.kind === 'repay') { form.channel = r.category; form.category = '' }
  else { form.category = r.category; form.channel = '' }
  ElMessage.info(r.kind === 'repay' ? '已载入该笔还款，请在上面修改后点「保存修改」' : '已载入该笔，请在上面修改后点「保存修改」')
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
  form.channel = ''
  form.note = ''
}
async function del(r: Row) {
  try { await ElMessageBox.confirm('删除这笔记录？', '确认删除', { type: 'warning' }) } catch { return }
  try { await http.del(`/ledger/${r.id}`); load() } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

// ---- 还款 ----
function openRepay(ch?: string) {
  const list = activeChannels.value.length ? activeChannels.value : stats.debt.channels
  rp.date = localYmd()
  rp.channel = ch || list[0]?.channel || channels.value[0] || ''
  const owed = stats.debt.channels.find((c) => c.channel === rp.channel)?.owed ?? 0
  // 预填当前待还金额（已还清就留空由用户自己填）
  rp.amount = owed > 0 ? owed : ''
  rp.note = ''
  rpOpen.value = true
}
async function doRepay() {
  const amt = Number(rp.amount)
  if (!rp.channel) return ElMessage.warning('请选择渠道')
  if (!(amt > 0)) return ElMessage.warning('请输入还款金额')
  try {
    const r = await http.post<{ owed: number; overpaid: boolean }>('/ledger/debt/repay', {
      date: rp.date, channel: rp.channel, amount: amt, note: rp.note.trim(),
    })
    rpOpen.value = false
    ElMessage.success(r.overpaid
      ? `已记还款 —— ${rp.channel} 多还了 ¥${fmt(-r.owed)}`
      : `已记还款 —— ${rp.channel} 剩余待还 ¥${fmt(r.owed)}`)
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '还款记录保存失败') }
}

// ---- 欠款渠道管理 ----
function openChMgr() {
  chList.value = [...channels.value]
  chNew.value = ''
  chOpen.value = true
}
function addCh(name?: string) {
  const s = String(name ?? chNew.value).trim().slice(0, 30)
  if (!s) return
  if (chList.value.includes(s)) { ElMessage.info('已在清单里'); return }
  if (chList.value.length >= 50) { ElMessage.warning('最多 50 个渠道'); return }
  chList.value.push(s)
  chNew.value = ''
}
function rmCh(c: string) { chList.value = chList.value.filter((x) => x !== c) }
async function saveCh() {
  try {
    const r = await http.put<{ channels: string[] }>('/ledger/debt/channels', { channels: chList.value })
    channels.value = r.channels
    chOpen.value = false
    ElMessage.success('渠道已保存')
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

async function saveStartBalance() {
  try {
    await http.put('/settings', { updates: { 'ledger.start_balance': sbVal.value } })
    sbOpen.value = false
    ElMessage.success('已保存')
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
}

// 打开弹窗时才把服务端的值灌进输入框。原实现在 onMounted 里取（当时 stats 还是 0），
// 且 load 完成后不同步 —— 弹窗永远显示 0，用户一点保存就把起始余额清成 0。
function openSb() {
  sbVal.value = stats.start_balance
  sbOpen.value = true
}

async function openClear() {
  await load()          // 先刷新，保证预览的笔数/金额是最新的
  clearOnlyDebt.value = false
  clearOpen.value = true
}

async function doClear() {
  const n = clearRows.value.length
  if (!n) { ElMessage.info('当前范围没有可清空的记录'); return }
  const label = (clearScope.value === 'month' ? `本月（${ymLabel.value}）` : '全部月份')
    + (clearOnlyDebt.value ? '的欠款相关记录' : '')
  try {
    await ElMessageBox.prompt(
      `将清空${label}的 ${n} 笔记录，合计 ¥${fmt(clearTotal.value)}。`
      + '服务端会先把这些记录导出为 JSON 存档，但删除本身不可撤销。请输入「清空」以确认。',
      '危险操作确认',
      {
        type: 'warning', confirmButtonText: '确认清空', cancelButtonText: '取消',
        inputPlaceholder: '清空', inputPattern: /^清空$/,
        inputErrorMessage: '请输入「清空」两个字',
      },
    )
  } catch { return }   // 用户取消
  try {
    const qs = `?yes=true${clearScope.value === 'month' ? `&month=${curYm.value}` : ''}`
      + (clearOnlyDebt.value ? '&kind=debt' : '')
    const r = await http.del<{ deleted: number; backup: string | null }>(`/ledger/clear${qs}`)
    clearOpen.value = false
    resetForm()
    ElMessage.success(`已清空 ${r.deleted} 笔${r.backup ? '，存档：' + r.backup.split('/').pop() : ''}`)
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '清空失败') }
}

onMounted(() => { load() })
</script>

<style scoped>
.bal { display: flex; align-items: center; gap: 30px; padding: 20px 26px; margin-bottom: 14px; flex-wrap: wrap; }
.bl { font-size: 13px; color: var(--txt2); }
.bal-num { font-size: 42px; font-weight: 900; line-height: 1.15; color: var(--acc2); }
.bal-num.neg { color: #f43f5e; }
.bl-sub { font-size: 12px; color: var(--txt2); }
.bal-right { display: flex; gap: 24px; flex-wrap: wrap; margin-left: auto; }
.bal-stat { display: grid; gap: 2px; min-width: 92px; }
.bs-lab { font-size: 12px; color: var(--txt2); }
.bs-num { font-weight: 800; font-size: 16px; }
.bs-num.in { color: #16a34a; } .bs-num.out { color: #dc2626; }
.bs-num.neg { color: #f43f5e; } .bs-num.ok { color: var(--acc2); }
.bs-num.debt { color: #f59e0b; }

/* 欠款卡片 */
.debt-card { padding: 14px 18px; margin-bottom: 14px; border: 1px solid rgba(245, 158, 11, 0.32); }
.dc-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.dc-total { font-size: 15px; font-weight: 700; }
.dc-total b { font-size: 20px; }
.dc-total b.out { color: #f59e0b; } .dc-total b.ok { color: var(--acc2); }
.dc-sub { font-size: 12px; color: var(--txt2); }
.dc-btns { margin-left: auto; display: flex; gap: 8px; }
.dc-rows { display: grid; margin-top: 10px; }
.dc-row { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 10px; font-size: 13.5px; }
.dc-row:nth-child(odd) { background: rgba(245, 158, 11, 0.06); }
.dc-ch { font-weight: 700; min-width: 90px; }
.dc-owed { font-weight: 800; min-width: 130px; }
.dc-owed.out { color: #f59e0b; } .dc-owed.ok { color: var(--txt2); font-weight: 600; }
.dc-meta { flex: 1; min-width: 0; color: var(--txt2); font-size: 12px; }
.dc-foot { margin-top: 10px; font-size: 12px; color: var(--txt2); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ch-pill { background: rgba(245, 158, 11, 0.14); color: #f59e0b; border-radius: 999px; padding: 1px 10px; font-size: 12px; }

.mbar { display: flex; align-items: center; gap: 6px; padding: 8px 14px; margin-bottom: 12px; }
.mlabel { font-weight: 800; font-size: 17px; min-width: 120px; text-align: center; }
.mcnt { margin-left: auto; color: var(--txt2); font-size: 12px; }

.form { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 16px; margin-bottom: 14px; }
.amt { width: 130px; } .cat { width: 200px; } .note { width: 180px; flex: 1; min-width: 120px; }
.form.editing { outline: 2px solid var(--acc2); outline-offset: 3px; border-radius: 18px; }

.cols { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
.list-card, .stats-card { padding: 14px 16px; }
.lc-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 10px; flex-wrap: wrap; }
.lc-t { font-weight: 700; }
.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.dchips { margin-bottom: 8px; }
.ttab { border: none; background: transparent; cursor: pointer; color: var(--txt2); padding: 4px 12px; border-radius: 999px; font-size: 13px; font-family: inherit; }
.ttab.on { background: var(--acc-grad); color: #fff; font-weight: 700; }
.rows { display: grid; }
.lrow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; font-size: 13.5px; }
.lrow:nth-child(odd) { background: rgba(148, 163, 184, 0.06); }
.ldate { color: var(--txt2); font-size: 12px; flex: none; }
.lcat { background: rgba(167, 139, 250, 0.14); color: var(--acc2); border-radius: 6px; padding: 0 8px; font-size: 12px; flex: none; }
.lcat.debt { background: rgba(245, 158, 11, 0.16); color: #f59e0b; }
.ltag { border-radius: 6px; padding: 0 8px; font-size: 12px; flex: none; background: rgba(245, 158, 11, 0.12); color: #f59e0b; }
.ltag.repay { background: rgba(56, 189, 248, 0.14); color: #0ea5e9; }
.lnote { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--txt3); }
.lsum { font-weight: 800; flex: none; }
.lsum.income { color: #16a34a; } .lsum.expense { color: #dc2626; }
.lsum.debt { color: #f59e0b; } .lsum.repay { color: #0ea5e9; }
.empty { color: var(--txt2); font-size: 13px; padding: 18px 4px; }
.empty b { color: #f59e0b; }

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
.b-fill.debt { background: linear-gradient(90deg, #fbbf24, #f59e0b); }
.b-amt { width: 86px; text-align: right; font-weight: 700; flex: none; }
.b-pct { width: 44px; text-align: right; color: var(--txt2); flex: none; font-size: 12px; }

.trend { display: flex; align-items: flex-end; gap: 10px; height: 90px; padding: 4px 0; }
.t-col { display: flex; flex-direction: column; align-items: center; flex: 1; gap: 4px; }
.t-bar { display: flex; align-items: flex-end; gap: 3px; height: 74px; width: 100%; justify-content: center; }
.t-fill { width: 9px; border-radius: 3px 3px 0 0; }
.t-fill.out { background: #f43f5e; } .t-fill.in { background: #22c55e; } .t-fill.dbt { background: #f59e0b; }
.t-lab { font-size: 11px; color: var(--txt2); }
.trend-legend { display: flex; gap: 16px; margin-top: 6px; font-size: 12px; color: var(--txt2); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 4px; }
.dot.out { background: #f43f5e; } .dot.in { background: #22c55e; } .dot.dbt { background: #f59e0b; }
.hint { color: var(--txt2); font-size: 12.5px; margin: 10px 0 0; }
.hint.danger { color: #f43f5e; }
.hint b { color: inherit; }

.rp-form { display: grid; gap: 10px; }
.rp-owed { font-size: 13px; color: var(--txt2); }
.rp-owed b.out { color: #f59e0b; } .rp-owed b.ok { color: var(--acc2); }
.ch-tags { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.ch-add { display: flex; gap: 8px; }
.ch-cand { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.ch-cand .hint { margin: 0; }
.cand { cursor: pointer; }
.cl-debt { margin-top: 12px; }
</style>