<template>
  <div class="login-page">
    <div class="blob b1" /><div class="blob b2" /><div class="blob b3" />
    <div class="login-card glass">
      <div class="logo">K</div>
      <h1 class="grad-text">{{ site.name }}</h1>
      <p v-if="site.slogan" class="slogan">{{ site.slogan }}</p>
      <el-form :model="form" @submit.prevent="doLogin">
        <el-form-item>
          <el-input v-model="form.username" size="large" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password" size="large" type="password" placeholder="密码"
            :prefix-icon="Lock" show-password @keyup.enter="doLogin"
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
  fetch('https://v1.hitokoto.cn/?encode=json', { signal: AbortSignal.timeout(3000) })
    .then((r) => r.json())
    .then((d) => {
      if (d?.hitokoto) quote.value = d.hitokoto
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
</style>
