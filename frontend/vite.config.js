import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  // 开发服务器：代理 /api 到后端
  server: {
    port: 3000,
    host: true,
    allowedHosts: 'all',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  // 生产构建：输出到后端 static/ 目录，由 FastAPI 直接提供服务
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
    assetsDir: 'assets'
  }
})