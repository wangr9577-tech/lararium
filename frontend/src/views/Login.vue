<template>
  <div class="login-page">
    <div class="login-intro"><div class="login-eyebrow">A SPACE OF YOUR OWN</div><h2>把生活与灵感，<br>安放在这里<span>。</span></h2><p>日程、笔记、阅读和专注，陪你整理每一天。</p><div class="intro-bottom">KRUSKAL <span> / </span> PERSONAL WORKSPACE</div></div>
    <div class="login-card glass">
      <div class="login-label"><div class="logo">K</div><span>WELCOME BACK</span></div>
      <h1 class="grad-text">{{ site.name }}</h1>
      <p class="slogan">{{ site.slogan || '欢迎回来，登录你的个人空间。' }}</p>
      <el-form :model="form" @submit.prevent="doLogin">
        <el-form-item>
          <el-input v-model="form.username" size="large" placeholder="用户名" aria-label="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password" size="large" type="password" placeholder="密码"
            aria-label="密码" :prefix-icon="Lock" show-password @keyup.enter="doLogin"
          />
        </el-form-item>
        <el-alert v-if="err" :title="err" type="error" :closable="false" style="margin-bottom:14px" />
        <el-button
          type="primary" size="large" class="go" :loading="loading" native-type="submit"
        >登 录</el-button>
      </el-form>
      <transition name="fade">
        <div class="quote" v-if="quote">
          <span class="q-mark">「</span>{{ quote }}<span class="q-mark">」</span>
        </div>
      </transition>
    </div>
    <footer class="foot">Kruskal v0.1 · 本地个人站 · 数据加密存储</footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { http, setToken, clearToken, USER_KEY } from '../api/client'
import { site, loadSite } from '../stores/site'

const router = useRouter()
const form = ref({ username: '', password: '' })
const loading = ref(false)
const err = ref('')
const quote = ref('')

const fallbackQuotes = [
  '每一个不曾起舞的日子，都是对生命的辜负。—— 尼采',
  '生活明朗，万物可爱。',
  '热爱可抵岁月漫长。',
  '慢慢来，比较快。',
  '把每一天都过成自己喜欢的样子。',
]

async function doLogin() {
  if (!form.value.username || !form.value.password) {
    err.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  err.value = ''
  try {
    const r = await http.post<{ token: string; username: string }>('/auth/login', form.value)
    setToken(r.token)
    localStorage.setItem(USER_KEY, r.username)
    ElMessage.success(`欢迎回来，${r.username}`)
    router.push('/')
  } catch (e: any) {
    err.value = e?.response?.data?.detail || '登录失败，请稍后再试'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  clearToken() // 登录页进入即清残留会话
  loadSite()
  const reason = new URLSearchParams(location.search).get('reason')
  if (reason === 'relock') {
    ElMessage.info('数据已锁定，请重新登录解锁')
    history.replaceState(null, '', '/login')
  } else if (reason === 'lock') {
    ElMessage.info('网页已上锁，请输入密码解锁')
    history.replaceState(null, '', '/login')
  }
  // 一言走站内代理（P1-K3）：不再未登录先向第三方泄 IP/UA，失败回落本地句子
  http.get<{ quote: string }>('/site/quote')
    .then((d) => {
      if (d?.quote) quote.value = d.quote
    })
    .catch(() => {
      quote.value = fallbackQuotes[Math.floor(Math.random() * fallbackQuotes.length)]
    })
})
</script>

<style scoped>
.login-page {
  min-height: 100vh; display: grid; place-items: center; position: relative; overflow: hidden;
  padding: 20px;
  /* 明亮主题下全站无图，登录页单独用深色二次元底 + 暗罩（两主题一致） */
  background:
    linear-gradient(rgba(10, 8, 30, 0.55), rgba(10, 8, 30, 0.68)),
    url('../assets/background.jpg') center / cover no-repeat fixed;
  background-attachment: fixed;
}
.blob {
  position: absolute; border-radius: 50%; filter: blur(70px); opacity: 0.32; z-index: 0;
  animation: float 12s ease-in-out infinite;
}
.b1 { width: 380px; height: 380px; background: #f472b6; top: -80px; left: -60px; }
.b2 { width: 460px; height: 460px; background: #a78bfa; bottom: -140px; right: -80px; animation-delay: -4s; }
.b3 { width: 280px; height: 280px; background: #38bdf8; top: 40%; left: 62%; animation-delay: -8s; }
@keyframes float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-26px) } }

.login-card { position: relative; z-index: 1; width: 400px; max-width: 92vw; padding: 42px 40px 30px; text-align: center; }
.logo {
  width: 64px; height: 64px; margin: 0 auto 12px; border-radius: 20px;
  display: grid; place-items: center; color: #fff; font-size: 34px; font-weight: 900;
  background: var(--acc-grad); box-shadow: 0 10px 26px rgba(139, 92, 246, 0.4);
}
h1 { margin: 10px 0 4px; font-size: 34px; font-weight: 900; }
.slogan { color: rgba(225, 232, 245, 0.85); font-size: 13px; margin: 0 0 26px; }
.go { width: 100%; letter-spacing: 6px; font-weight: 700; border-radius: 12px; }
.quote { margin-top: 20px; font-size: 12.5px; color: rgba(220, 228, 242, 0.9); line-height: 1.8; }
.q-mark { color: var(--acc2); }
.foot { position: absolute; bottom: 12px; z-index: 1; font-size: 12px; color: rgba(210, 220, 238, 0.75); }

.login-page { display:grid; grid-template-columns:minmax(0,1fr) minmax(320px,440px); gap:64px; align-items:center; padding:64px 8%; background:rgba(0,0,0,.38) url('../assets/background.jpg') center / cover no-repeat fixed; background-blend-mode:multiply; }
.login-intro { position:relative; z-index:1; align-self:stretch; display:flex; flex-direction:column; justify-content:center; color:#fff; }
.login-eyebrow,.intro-bottom { font-size:12px; line-height:16px; letter-spacing:.16em; color:rgba(255,255,255,.8); }
.login-intro h2 { margin:24px 0 16px; font-size:48px; line-height:1.15; font-weight:700; letter-spacing:-.03em; text-shadow:0 4px 32px rgba(0,0,0,.35); }
.login-intro h2 span { color:#e6a8ca; }
.login-intro p { margin:0; font-size:16px; line-height:24px; color:rgba(255,255,255,.85); }
.intro-bottom { margin-top:64px; }.intro-bottom span { margin:0 8px; opacity:.5; }
.login-card { width:100%; max-width:none; padding:40px; text-align:left; background:rgba(24,24,24,.84); border:1px solid rgba(255,255,255,.18); color:#fff; }
.login-label { display:flex; align-items:center; gap:12px; color:#d5c4ea; font-size:12px; line-height:16px; letter-spacing:.12em; }
.login-label .logo { margin:0; width:40px; height:40px; border-radius:8px; font-size:20px; font-weight:700; background:#7757b5; box-shadow:none; }
.login-card h1 { margin:32px 0 8px; font-size:30px; line-height:36px; font-weight:700; color:#fff; }
.slogan { margin:0 0 24px; font-size:14px; line-height:20px; }
.login-card :deep(.el-input__wrapper) { min-height:48px; background:rgba(255,255,255,.08); box-shadow:0 0 0 1px rgba(255,255,255,.18) inset; }
.login-card :deep(.el-input__inner) { color:#fff; }.login-card :deep(.el-input__inner::placeholder) { color:#bdb5c8; }
.login-card :deep(.el-input__icon) { color:#c5bbce; }.go { height:48px; margin-top:8px; letter-spacing:.08em; border-radius:8px; }
.quote { margin-top:24px; color:#cfc6d8; font-size:12px; line-height:20px; }
.foot { bottom:24px; left:8%; font-size:12px; }
@media(max-width:820px) { .login-page { grid-template-columns:1fr; gap:24px; padding:32px 24px 80px; }.login-intro { align-self:auto; }.login-intro h2 { font-size:30px; line-height:36px; margin:16px 0 8px; }.login-intro p { font-size:14px; line-height:20px; }.intro-bottom { display:none; }.login-card { max-width:480px; padding:24px; }.login-card h1 { margin-top:24px; }.foot { left:24px; } }

</style>
