<template>
  <div class="shell">
    <!-- 侧边导航 -->
    <aside class="side glass" :class="{ open: drawerOpen, collapsed: !narrow && sideCollapsed }">
      <div class="brand">
        <span class="brand-logo">K</span>
        <span class="brand-name grad-text">{{ site.name }}</span>
      </div>
      <nav class="nav">
        <template v-for="g in navGroups" :key="g">
          <div class="nav-group">{{ g }}</div>
          <router-link
            v-for="item in itemsOf(g)"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            @click="drawerOpen = false"
          >
            <el-icon :size="17"><component :is="iconMap[item.icon]" /></el-icon>
            <span>{{ item.title }}</span>
          </router-link>
        </template>
      </nav>
      <div class="side-foot">
        <div class="user-chip">
          <div class="avatar">{{ avatarChar }}</div>
          <div class="user-meta">
            <div class="uname">{{ username }}</div>
            <div class="utag">主人</div>
          </div>
          <el-tooltip content="上锁网页" placement="top">
            <el-button text circle @click="lock">
              <el-icon :size="18"><Lock /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="退出登录" placement="top">
            <el-button text circle @click="logout"><el-icon><SwitchButton /></el-icon></el-button>
          </el-tooltip>
        </div>
      </div>
    </aside>
    <div v-if="drawerOpen" class="mask" @click="drawerOpen = false" />

    <!-- 主区 -->
    <div class="main">
      <header v-if="!hideTop" class="top glass">
        <el-tooltip :content="navTip" placement="bottom">
          <el-button class="burger" text circle @click="toggleSide">
            <el-icon :size="20"><component :is="navIcon" /></el-icon>
          </el-button>
        </el-tooltip>
        <div class="top-title">{{ currentTitle }}</div>
        <div class="top-right">
          <span class="today">{{ todayText }}</span>
          <el-tooltip :content="isDark ? '切换明亮' : '切换暗黑'" placement="bottom">
            <el-button text circle @click="toggleTheme">
              <el-icon :size="18"><component :is="isDark ? Sunny : Moon" /></el-icon>
            </el-button>
          </el-tooltip>
          <FullscreenToggle />
        </div>
      </header>
      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  HomeFilled, Memo, Notebook, Reading, Calendar, User, Wallet,
  ChatDotRound, Picture, Clock, CollectionTag, Setting,
  SwitchButton, Lock, Menu, Sunny, Moon, Fold, Expand, type Component as IconComponent,
} from '@element-plus/icons-vue'
import { http, clearToken, getToken } from '../api/client'
import { navGroups, navItems } from '../router'
import { site, loadSite } from '../stores/site'
import FullscreenToggle from '../components/FullscreenToggle.vue'

const iconMap: Record<string, IconComponent> = {
  HomeFilled, Memo, Notebook, Reading, Calendar, User, Wallet,
  ChatDotRound, Picture, Clock, CollectionTag, Setting,
}

const route = useRoute()
const router = useRouter()
const drawerOpen = ref(false)
const narrow = ref(false) // ≤820px：抽屉模式
const sideCollapsed = ref(localStorage.getItem('krs_side') === '1') // 桌面端侧栏收起（记忆）
const username = ref('主人')
const isDark = ref(false)
const todayText = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

const currentTitle = computed(() => String(route.meta.title ?? ''))
const avatarChar = computed(() => (username.value || '主').charAt(0).toUpperCase())
/** 编辑类页面隐藏顶部栏，把整屏让给写作区 */
const hideTop = computed(() => /^\/(notes\/new|notes\/[^/]+\/edit|ielts\/doc\/new|ielts\/doc\/[^/]+\/edit)$/.test(route.path))

/* 顶栏左侧按钮：桌面端收起/展开侧栏，窄屏唤出抽屉菜单 */
const navIcon = computed<IconComponent>(() => {
  if (narrow.value) return Menu
  return sideCollapsed.value ? Expand : Fold
})
const navTip = computed(() => (narrow.value ? '打开菜单' : sideCollapsed.value ? '展开侧栏' : '收起侧栏'))

function syncNarrow() {
  narrow.value = window.matchMedia('(max-width: 820px)').matches
}

function toggleSide() {
  if (narrow.value) {
    drawerOpen.value = true
    return
  }
  sideCollapsed.value = !sideCollapsed.value
  localStorage.setItem('krs_side', sideCollapsed.value ? '1' : '0')
}

function itemsOf(group: string) {
  return navItems.filter((n) => n.group === group)
}

function applyTheme(dark: boolean) {
  isDark.value = dark
  document.documentElement.classList.toggle('theme-dark', dark)
}

function toggleTheme() {
  const next = !isDark.value
  applyTheme(next)
  localStorage.setItem('krs_theme', next ? 'dark' : 'light')
  http.put('/settings', { updates: { 'theme.mode': next ? 'dark' : 'light' } }).catch(() => {})
}

async function logout() {
  try { await http.post('/auth/logout') } catch { /* ignore */ }
  clearToken()
  ElMessage.success('已退出登录')
  router.push('/login')
}

/** 一键上锁：撤销全部会话 + 清空服务端解密密钥，需重新输密码解锁 */
async function lock() {
  try {
    await ElMessageBox.confirm(
      '确定上锁网页吗？上锁后所有会话将失效，需输入密码才能再次进入。',
      '上锁网页',
      { confirmButtonText: '上锁', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try { await http.post('/auth/lock') } catch { /* 接口失败也继续本地清理 */ }
  clearToken()
  ElMessage.success('网页已上锁')
  router.push({ path: '/login', query: { reason: 'lock' } })
}

onMounted(async () => {
  syncNarrow()
  window.addEventListener('resize', syncNarrow)
  loadSite()
  const saved = localStorage.getItem('krs_theme')
  applyTheme(saved ? saved === 'dark' : true) // 默认暗黑（与主视觉一致）
  if (!getToken()) return
  try {
    const me = await http.get<{ id: number; username: string }>('/auth/me')
    username.value = me.username
    localStorage.setItem('krs_user', me.username)
  } catch { /* 401 拦截器会跳登录 */ }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncNarrow)
})
</script>

<style scoped>
.shell { display: flex; height: 100vh; overflow: hidden; }

.side {
  width: 228px; flex: none; margin: 12px; margin-right: 0;
  display: flex; flex-direction: column;
  border-radius: 20px; padding: 16px 12px; z-index: 30;
  overflow: hidden;
  transition: width .22s ease, padding .22s ease, opacity .18s ease;
}
.side.collapsed { width: 0; padding-left: 0; padding-right: 0; opacity: 0; }
.brand { display: flex; align-items: center; gap: 9px; padding: 4px 10px 14px; font-weight: 800; font-size: 19px; }
.brand-logo {
  width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center;
  background: var(--acc-grad); color: #fff; font-size: 16px; font-weight: 900;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.35);
}

.nav { flex: 1; overflow-y: auto; }
.nav-group {
  font-size: 11px; color: var(--txt2); letter-spacing: 2px;
  padding: 12px 10px 6px;
}
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; margin: 2px 0; border-radius: 12px;
  color: #475569; font-size: 14px; transition: all .15s;
}
html.theme-dark .nav-item { color: #cbd5e1; }
.nav-item:hover { background: rgba(167, 139, 250, 0.12); }
.nav-item.router-link-active {
  background: var(--acc-grad); color: #fff; font-weight: 600;
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.35);
}

.side-foot { border-top: 1px solid rgba(148, 163, 184, 0.2); padding-top: 10px; }
.user-chip { display: flex; align-items: center; gap: 8px; padding: 4px 6px; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%; flex: none;
  display: grid; place-items: center; color: #fff; font-weight: 700;
  background: var(--acc-grad);
}
.user-meta { flex: 1; min-width: 0; }
.uname { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.utag { font-size: 11px; color: var(--txt2); }

.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.top {
  margin: 12px 12px 0; padding: 10px 18px; border-radius: 16px;
  display: flex; align-items: center; gap: 10px; z-index: 20;
}
.top-title { font-size: 16px; font-weight: 700; }
.top-right { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.today { font-size: 12px; color: var(--txt2); margin-right: 4px; }
.burger { display: inline-flex; }
.content { flex: 1; overflow-y: auto; }

.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); z-index: 25; }

@media (max-width: 820px) {
  .side { position: fixed; left: 0; top: 0; bottom: 0; margin: 8px; transform: translateX(-120%); transition: transform .2s; }
  .side.open { transform: none; }
  .side.collapsed { width: 228px; padding: 16px 12px; opacity: 1; } /* 窄屏忽略桌面收起态 */
}
</style>
