import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'
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
  { path: '/ledger', title: '钱包', icon: 'Wallet', group: '工作区' },
  { path: '/notes', title: '笔记·博客', icon: 'Notebook', group: '工作区' },
  { path: '/papers', title: '论文阅读', icon: 'Reading', group: '工作区' },
  { path: '/diary', title: '日记', icon: 'Calendar', group: '工作区' },
  { path: '/me', title: '个人主页', icon: 'User', group: '工作区' },
  { path: '/album', title: '相册', icon: 'Picture', group: '生活区' },
  { path: '/timeline', title: '时光机', icon: 'Clock', group: '生活区' },
  { path: '/vocab', title: '生词本', icon: 'CollectionTag', group: '生活区' },
  { path: '/settings', title: '设置', icon: 'Setting', group: '系统' },
]

export const navGroups = ['工作区', '生活区', '系统']

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true, title: '登录' } },
  ...navItems.map((n) => ({
    path: n.path,
    component: () => import(`../views/${viewName(n.path)}.vue`),
    meta: { title: n.title, icon: n.icon, group: n.group },
  })),
  // 笔记子页（不进导航）
  { path: '/notes/new', component: () => import('../views/NoteEdit.vue'), meta: { title: '新建笔记' } },
  { path: '/notes/:id', component: () => import('../views/NoteView.vue'), meta: { title: '阅读笔记' } },
  { path: '/notes/:id/edit', component: () => import('../views/NoteEdit.vue'), meta: { title: '编辑笔记' } },
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
  { path: '/:pathMatch(.*)*', component: () => import('../views/NotFound.vue'), meta: { public: true, title: '404' } },
]

function viewName(path: string): string {
  const map: Record<string, string> = {
    '/': 'Dashboard',
    '/schedule': 'Schedule',
    '/ledger': 'Ledger',
    '/notes': 'Notes',
    '/papers': 'Papers',
    '/diary': 'Diary',
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

router.beforeEach((to) => {
  const hasToken = !!getToken()
  if (!to.meta.public && !hasToken) return { path: '/login' }
  if (to.path === '/login' && hasToken) return { path: '/' }
  return true
})

router.afterEach((to) => {
  const t = String(to.meta.title ?? '')
  document.title = t ? `${t} · ${site.name}` : site.name
})

export default router
