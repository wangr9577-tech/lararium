import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { site } from '../stores/site'

export interface NavItem {
  path: string
  title: string
  icon: string
  group: string
}

export const navItems: NavItem[] = [
  { path: '/', title: '首页', icon: 'HomeFilled', group: '工作区' },
  { path: '/schedule', title: '日程', icon: 'Memo', group: '工作区' },
  { path: '/pomodoro', title: '番茄钟', icon: 'Timer', group: '工作区' },
  { path: '/assistant', title: '助手', icon: 'ChatLineRound', group: '工作区' },
  { path: '/ledger', title: '钱包', icon: 'Wallet', group: '工作区' },
  { path: '/notes', title: '笔记·博客', icon: 'Notebook', group: '工作区' },
  { path: '/papers', title: '论文阅读', icon: 'Reading', group: '工作区' },
  { path: '/me', title: '个人主页', icon: 'User', group: '工作区' },
  { path: '/album', title: '相册', icon: 'Picture', group: '生活区' },
  { path: '/timeline', title: '时光机', icon: 'Clock', group: '生活区' },
  { path: '/vocab', title: '生词本', icon: 'CollectionTag', group: '生活区' },
  { path: '/settings', title: '设置', icon: 'Setting', group: '系统' },
]

export const navGroups = ['工作区', '生活区', '系统']

// 显式标注 RouteRecordRaw[]：避免 TS 推断数组联合类型时把
// redirect/children 以 `?: undefined` 注入个别成员，导致与
// RouteRecordSingleView 的 `redirect?: never; children?: never` 冲突
const routes: RouteRecordRaw[] = [
  ...navItems.map((n) => ({
    path: n.path,
    component: () => import(`../views/${viewName(n.path)}.vue`),
    meta: { title: n.title, icon: n.icon, group: n.group },
  })),
  // 工作台已下线：重定向到首页
  { path: '/lab', redirect: '/' },
  { path: '/lab/:pathMatch(.*)*', redirect: '/' },
  // 登录页已下线（本机免登录）：旧书签回首页
  { path: '/login', redirect: '/' },
  // 笔记子页（不进导航）
  { path: '/notes/new', component: () => import('../views/NoteEdit.vue'), meta: { title: '新建笔记' } },
  { path: '/notes/:id', component: () => import('../views/NoteView.vue'), meta: { title: '阅读笔记' } },
  // 查看与编辑已合一：/edit 旧链接仍可用，由阅读页原地进入编辑态
  { path: '/notes/:id/edit', component: () => import('../views/NoteView.vue'), meta: { title: '编辑笔记' } },
  // 论文阅读器（不进导航）
  { path: '/papers/:id', component: () => import('../views/PaperView.vue'), meta: { title: '论文阅读' } },
  // 雅思学习（不进导航，由 笔记·博客 列表入口进入；主页=卡片墙，点卡进子页）
  { path: '/ielts', component: () => import('../views/Ielts.vue'), meta: { title: '雅思学习' } },
  { path: '/ielts/intro', component: () => import('../views/ielts/IntroView.vue'), meta: { title: '雅思学习 · 入门' } },
  { path: '/ielts/timeline', component: () => import('../views/ielts/TimelineView.vue'), meta: { title: '雅思学习 · 时间轴' } },
  { path: '/ielts/plan', component: () => import('../views/ielts/PlanView.vue'), meta: { title: '雅思学习 · 周计划' } },
  { path: '/ielts/doc/new', component: () => import('../views/ielts/DocEdit.vue'), meta: { title: '雅思学习 · 新建子页' } },
  { path: '/ielts/doc/:id', component: () => import('../views/ielts/DocView.vue'), meta: { title: '雅思学习 · 子页' } },
  { path: '/ielts/doc/:id/edit', component: () => import('../views/ielts/DocEdit.vue'), meta: { title: '雅思学习 · 编辑子页' } },
  // 旧日记页已并入日程页（/schedule 底部）：旧链接重定向保兼容（保留 ?date= query）
  { path: '/diary', redirect: (to) => ({ path: '/schedule', query: to.query }) },
  { path: '/diary/:date', redirect: (to) => `/schedule?date=${to.params.date}` },
  // 旧科研工作台入口（卡片笔记/想法/代码/实验/写作资产/投稿）已随工作台重构下线：
  // 这些路径不再存在任何页面，统一落到 404；相关历史数据文件仍留在数据目录里未删。
  { path: '/cards/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/ideas/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/code/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/experiments/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/writing/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/submissions/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
  { path: '/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { title: '404' } },
]

function viewName(path: string): string {
  const map: Record<string, string> = {
    '/': 'Dashboard',
    '/schedule': 'Schedule',
    '/pomodoro': 'Pomodoro',
    '/assistant': 'Assistant',
    '/ledger': 'Ledger',
    '/notes': 'Notes',
    '/papers': 'Papers',
    '/me': 'Me',
    '/album': 'Album',
    '/timeline': 'Timeline',
    '/vocab': 'Vocab',
    '/settings': 'Settings',
  }
  return map[path] || 'NotFound'
}

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const t = String(to.meta.title ?? '')
  document.title = t ? `${t} · ${site.name}` : site.name
})

export default router
