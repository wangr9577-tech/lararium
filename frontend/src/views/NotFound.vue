<template>
  <div class="nf">
    <div class="nf-inner glass">
      <div class="nf-code grad-text">404</div>
      <div class="nf-text">呜哇…… 页面走丢了，像迷路的小动物一样</div>
      <el-button type="primary" round @click="$router.push('/')">回到首页</el-button>
    </div>
  </div>
</template>

<style scoped>
.nf { min-height: 100vh; display: grid; place-items: center; padding: 20px; }
.nf-inner { text-align: center; padding: 46px 40px; border-radius: 24px; }
.nf-code { font-size: 88px; font-weight: 900; line-height: 1.1; }
.nf-text { color: var(--txt2); margin: 14px 0 20px; }
</style>
