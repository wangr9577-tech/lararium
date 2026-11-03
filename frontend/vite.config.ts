import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: process.env.VITE_DEV_HOST || '127.0.0.1',
    port: Number(process.env.VITE_DEV_PORT) || 5173,
    proxy: { '/api': process.env.VITE_API_TARGET || 'http://127.0.0.1:18080' },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        // P2-M4：按第三方库拆包。现状 index 入口 ~1.1MB 全量首屏扛；
        // 拆开后 echarts/pdfjs/katex/codemirror/element-plus 各自成块，
        // 首屏只需 core+elplus，其余随对应页面/组件懒加载并行下载、独立缓存。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          if (id.includes('pdfjs-dist')) return 'vendor-pdfjs'
          if (id.includes('katex')) return 'vendor-katex'
          if (id.includes('codemirror') || id.includes('@codemirror') || id.includes('markdown-it') || id.includes('dompurify')) return 'vendor-editor'
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-elplus'
          if (id.includes('vue') || id.includes('axios') || id.includes('perfect-freehand')) return 'vendor-core'
          return 'vendor-misc'
        },
      },
    },
  },
})
