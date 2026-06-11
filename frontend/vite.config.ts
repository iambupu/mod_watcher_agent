// 中文注释：配置 Vite 开发服务器、React 插件和构建入口。

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 17501,
    proxy: {
      '/api': {
        target: 'http://localhost:17500',
        changeOrigin: true,
      },
    },
  },
})
