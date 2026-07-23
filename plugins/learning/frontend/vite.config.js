import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

// 插件前端 = 模块联邦「远程」。平台从 /api/plugins/learning/fe/assets/remoteEntry.js
// 动态 import，取 exposes 的 './Config' 挂进配置弹窗。vue 声明 shared+generate:false，
// 复用平台那份 Vue，不重复打包。
// base 用「平台前端资源绝对挂载路径」而非 './'：平台把 remoteEntry.js 从
// /api/plugins/<id>/fe/assets/remoteEntry.js 加载，而 vite-plugin-federation 生成的
// 子 chunk 引用是 './assets/xxx.js'（按 remoteEntry 在 dist 根算），相对 assets/ 下的
// remoteEntry 解析会变成 .../fe/assets/assets/xxx.js（多一层 assets）导致 404。
// 用绝对 base 让所有 chunk URL 变成 /api/plugins/learning/fe/assets/xxx.js，消歧。
export default defineConfig({
  base: '/api/plugins/learning/fe/',
  plugins: [
    vue(),
    federation({
      name: 'awbotnest_learning',
      filename: 'remoteEntry.js',
      exposes: {
        './Config': './src/Config.vue',
      },
      shared: {
        vue: { singleton: true, requiredVersion: false, generate: false },
      },
      format: 'esm',
    }),
  ],
  build: {
    target: 'esnext',         // 联邦运行时用到顶层 await
    minify: false,            // 方便排查，可按需改 true
    cssCodeSplit: true,       // 分离组件样式，联邦加载时自动注入
  },
  server: { port: 5004, cors: true },
})
