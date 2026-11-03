<template>
  <div class="shell">
    <a class="skip-link" href="#main-content">跳转到主要内容</a>
    <!-- 侧边导航 -->
    <aside class="side glass" :class="{ open: drawerOpen, collapsed: !narrow && sideCollapsed }">
      <div class="brand">
        <span class="brand-logo">K</span>
        <span class="brand-copy"><span class="brand-name">{{ site.name }}</span><span class="brand-caption">PERSONAL SPACE</span></span>
        <!-- 收起按钮放在侧栏本体上：编辑页顶栏被 hideTop 隐藏，按钮在侧栏里才不会跟着消失 -->
        <el-tooltip v-if="!narrow" content="收起侧栏" placement="bottom">
          <el-button class="side-toggle" text circle aria-label="收起侧栏" @click="toggleSide">
            <el-icon :size="17"><Fold /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <nav class="nav" aria-label="主导航">
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
            <div class="utag">个人空间</div>
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

    <!-- 侧栏收起后的唯一入口：编辑页没有顶栏，靠这条左边缘把手把侧栏叫回来 -->
    <button
      v-if="!narrow && sideCollapsed"
      type="button"
      class="edge-handle"
      title="展开侧栏"
      aria-label="展开侧栏"
      @click="toggleSide"
    >
      <el-icon :size="13"><Expand /></el-icon>
    </button>

    <!-- 主区 -->
    <div class="main">
      <header v-if="!hideTop" class="top glass">
        <!-- 桌面端的收起/展开按钮已移入侧栏本体；顶栏只在窄屏保留菜单按钮（唤出抽屉） -->
        <el-tooltip v-if="narrow" content="打开菜单" placement="bottom">
          <el-button class="burger" text circle aria-label="打开菜单" @click="toggleSide">
            <el-icon :size="20"><Menu /></el-icon>
          </el-button>
        </el-tooltip>
        <div class="top-breadcrumb"><span class="top-context">WORKSPACE</span><span class="top-slash">/</span><span class="top-title">{{ currentTitle }}</span></div>
        <div class="top-right">
          <span class="today">{{ todayText }}</span>
          <el-tooltip content="随手记录 (Alt+C / Ctrl+Alt+N)" placement="bottom">
            <el-button class="quick-capture-btn" text circle aria-label="随手记录" @click="openQuickCapture">
              <el-icon :size="18"><EditPen /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip :content="isDark ? '切换明亮' : '切换暗黑'" placement="bottom">
            <el-button text circle :aria-label="isDark ? '切换明亮主题' : '切换暗黑主题'" @click="toggleTheme">
              <el-icon :size="18"><component :is="isDark ? Sunny : Moon" /></el-icon>
            </el-button>
          </el-tooltip>
          <FullscreenToggle />
        </div>
      </header>
      <main id="main-content" class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- 全局便签极速录入浮窗 -->
    <QuickCaptureModal ref="quickCaptureRef" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  HomeFilled, Memo, Notebook, Reading, Calendar, User, Wallet,
  ChatDotRound, ChatLineRound, Picture, Clock, CollectionTag, Setting,
  Grid, FolderOpened,
  SwitchButton, Lock, Menu, Sunny, Moon, Fold, Expand, type Component as IconComponent,
  EditPen,
} from '@element-plus/icons-vue'
import { http, clearToken, getToken } from '../api/client'
import { navGroups, navItems } from '../router'
import { site, loadSite } from '../stores/site'
import FullscreenToggle from '../components/FullscreenToggle.vue'
import QuickCaptureModal from '../components/QuickCaptureModal.vue'

const iconMap: Record<string, IconComponent> = {
  HomeFilled, Memo, Notebook, Reading, Calendar, User, Wallet,
  ChatDotRound, ChatLineRound, Picture, Clock, CollectionTag, Setting,
  Grid, FolderOpened,
}

const route = useRoute()
const router = useRouter()
const drawerOpen = ref(false)
const narrow = ref(false) // ≤820px：抽屉模式
const sideCollapsed = ref(localStorage.getItem('krs_side') === '1') // 桌面端侧栏收起（记忆）
const username = ref(localStorage.getItem('krs_user') || '主人')
const isDark = ref(false)
const todayText = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

const quickCaptureRef = ref<InstanceType<typeof QuickCaptureModal> | null>(null)

function openQuickCapture() {
  quickCaptureRef.value?.open()
}

function onGlobalKeydown(e: KeyboardEvent) {
  const isKeyC = e.code === 'KeyC' || e.key?.toLowerCase() === 'c'
  const isKeyN = e.code === 'KeyN' || e.key?.toLowerCase() === 'n'
  // Alt+C (Mac 下 Option+C) 或 Ctrl+Alt+N
  const isAltC = e.altKey && !e.ctrlKey && !e.metaKey && isKeyC
  const isCtrlAltN = e.altKey && (e.ctrlKey || e.metaKey) && isKeyN

  if (isAltC || isCtrlAltN) {
    e.preventDefault()
    e.stopPropagation()
    openQuickCapture()
  }
}

const currentTitle = computed(() => String(route.meta.title ?? ''))
const avatarChar = computed(() => (username.value || '主').charAt(0).toUpperCase())
/** 编辑类页面隐藏顶部栏，把整屏让给写作区 */
const hideTop = computed(() => /^\/(notes\/new|notes\/[^/]+\/edit|ielts\/doc\/new|ielts\/doc\/[^/]+\/edit)$/.test(route.path))

/* 收起/展开侧栏按钮的归宿：桌面端在侧栏顶行（.side-toggle），收起后由左边缘把手（.edge-handle）展开；
   顶栏按钮只在窄屏保留（打开抽屉菜单）。 */

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
  let serverLocked = true
  try { await http.post('/auth/lock') } catch { serverLocked = false }
  clearToken()
  if (serverLocked) {
    ElMessage.success('网页已上锁')
  } else {
    ElMessage.error('服务端上锁请求失败（密钥可能仍在内存），本机已登出；可稍后再点一次上锁')
  }
  router.push({ path: '/login', query: { reason: 'lock' } })
}

onMounted(async () => {
  syncNarrow()
  window.addEventListener('resize', syncNarrow)
  window.addEventListener('keydown', onGlobalKeydown)
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
  window.removeEventListener('keydown', onGlobalKeydown)
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
.side-toggle { margin-left: auto; flex: none; color: var(--txt2); }
.side-toggle:hover { color: var(--acc2); }
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
.quick-capture-btn { color: var(--txt2); transition: all .16s ease; }
.quick-capture-btn:hover { color: var(--acc2); background: rgba(139, 92, 246, 0.12); }
.burger { display: inline-flex; }
.content { flex: 1; overflow-y: auto; }

.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); z-index: 25; }

/* 侧栏收起后的展开把手：贴视口左边缘，宽度落在侧栏让出的 12px 边距里（正文另有 26px 内边距），不压内容 */
.edge-handle {
  position: fixed; left: 0; top: 50%; transform: translateY(-50%);
  width: 16px; height: 64px; padding: 0; z-index: 30;
  display: grid; place-items: center;
  border: none; cursor: pointer; color: var(--txt2);
  border-radius: 0 10px 10px 0;
  background: rgba(148, 163, 184, 0.18);
  backdrop-filter: blur(10px) saturate(1.2);
  -webkit-backdrop-filter: blur(10px) saturate(1.2);
  transition: width .16s ease, background .16s ease, color .16s ease;
}
.edge-handle:hover { width: 24px; background: var(--acc-grad); color: #fff; }

@media (max-width: 820px) {
  .side { position: fixed; left: 0; top: 0; bottom: 0; margin: 8px; transform: translateX(-120%); transition: transform .2s; }
  .side.open { transform: none; }
  .side.collapsed { width: 228px; padding: 16px 12px; opacity: 1; } /* 窄屏忽略桌面收起态 */
}

/* 打印：与全局 .side/.top 一致，把手不参与打印版面 */
@media print {
  .edge-handle { display: none; }
}

/* Workspace navigation */
.skip-link { position: fixed; z-index: 100; left: 16px; top: 16px; padding: 8px 12px; background: #fff; color: #30283f; border-radius: 8px; transform: translateY(-160%); }
.skip-link:focus { transform: translateY(0); }
.side { width: 240px; margin: 16px 0 16px 16px; padding: 24px 12px 16px; border-radius: 16px; transition: width .5s cubic-bezier(.22,1,.36,1), padding .5s cubic-bezier(.22,1,.36,1), opacity .3s cubic-bezier(.22,1,.36,1); }
.brand { gap: 12px; padding: 0 8px 24px; font-size: 18px; font-weight: 700; }
.brand-name { color: inherit; }
.brand-logo { width: 32px; height: 32px; border-radius: 8px; background: #7257b7; color: #fff; box-shadow: none; font-weight: 700; }
.nav-group { padding: 16px 12px 8px; color: var(--txt2); font-size: 12px; letter-spacing: .05em; }
.nav-item { gap: 12px; padding: 8px 12px; margin: 4px 0; border-radius: 8px; color: #555e59; transition: color .3s cubic-bezier(.22,1,.36,1), background-color .3s cubic-bezier(.22,1,.36,1); }
.nav-item:hover { background: #f3f0fa; color: #60468f; }
.nav-item.router-link-active { color: #654994; background: #f0ecf8; box-shadow: none; }
:global(html.theme-dark) .nav-item { color: #c4c4c4; }
:global(html.theme-dark) .nav-item:hover { background: #272727; color: #eee; }
:global(html.theme-dark) .nav-item.router-link-active { background: #313131; color: #e0d3fa; }
.side-foot { border-top-color: rgba(128,128,128,.18); padding-top: 16px; }
.avatar { width: 32px; height: 32px; background: #7257b7; }
.uname { font-size: 14px; }
.utag { font-size: 12px; }
.top { margin: 16px 16px 0; padding: 12px 24px; border-radius: 16px; }
.top-title { font-size: 16px; font-weight: 600; }
.today { font-size: 12px; }
.edge-handle { background: #e3e1e8; transition: color .3s cubic-bezier(.22,1,.36,1), background-color .3s cubic-bezier(.22,1,.36,1); }
.edge-handle:hover { width: 16px; background: #7257b7; color: #fff; }
:global(html.theme-dark) .edge-handle { background: #313131; }
@media (max-width: 820px) {
  .side { width: min(280px, calc(100vw - 32px)); margin: 16px; padding: 24px 12px 16px; transition: transform .5s cubic-bezier(.22,1,.36,1); }
  .side.collapsed { width: min(280px, calc(100vw - 32px)); padding: 24px 12px 16px; }
  .top { margin: 16px 16px 0; padding: 8px 12px; }
  .today { display: none; }
}


/* Navigation and top bar */
.side { width:256px; margin:16px 0 16px 16px; padding:24px 16px 16px; border-radius:16px; }
.brand { gap:12px; padding:0 4px 24px; }
.brand-logo { width:40px; height:40px; border:1px solid rgba(215,199,249,.5); border-radius:12px; background:rgba(119,87,181,.16); color:#7254ad; font-size:20px; font-weight:700; }
:global(html.theme-dark) .brand-logo { color:#ebddff; background:rgba(204,182,248,.12); }
.brand-copy { display:grid; gap:2px; min-width:0; }
.brand-name { font-size:16px; line-height:20px; letter-spacing:.01em; color:inherit; }
.brand-caption { font-size:12px; line-height:16px; letter-spacing:.06em; color:var(--txt2); font-weight:500; white-space:nowrap; }
.nav-group { padding:24px 12px 8px; font-size:12px; line-height:16px; letter-spacing:.08em; }
.nav-item { gap:12px; padding:12px; margin:2px 0; border-radius:8px; font-size:14px; line-height:20px; }
.nav-item.router-link-active { color:#69499d; background:rgba(119,87,181,.11); }
:global(html.theme-dark) .nav-item { color:#d8d3dd; }
:global(html.theme-dark) .nav-item.router-link-active { background:rgba(226,207,255,.14); color:#fff; }
:global(html.theme-dark) .nav-item:hover { background:rgba(255,255,255,.08); }
.user-chip { padding:4px; }
.avatar { width:40px; height:40px; background:#7757b5; }
.side-foot { padding-top:16px; }
.top { min-height:64px; margin:16px 16px 0; padding:12px 24px; }
.top-breadcrumb { display:flex; gap:12px; align-items:center; }
.top-context { color:var(--txt2); font-size:12px; line-height:16px; letter-spacing:.08em; }
.top-slash { color:var(--txt2); opacity:.5; }
.top-title { font-size:14px; line-height:20px; }
.today { font-size:12px; line-height:16px; }
@media(max-width:820px) { .side,.side.collapsed { width:min(288px,calc(100vw - 32px)); padding:24px 16px 16px; } .top { margin:16px 16px 0; padding:8px 12px; } .top-context { display:none; } .top-slash { display:none; } }

</style>
