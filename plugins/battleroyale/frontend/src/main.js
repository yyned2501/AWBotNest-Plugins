// 开发模式入口，仅用于本地预览
import { createApp } from 'vue'
import Config from './Config.vue'

const app = createApp(Config, {
  pluginId: 'battleroyale',
  host: {
    getConfig: async () => ({
      chat_id: '-1003808371287',
      bot_id: 8835151149,
      auto_bet: true,
      bet_timing: 5,
      bet_strategy: '少',
      notify_round: true,
      notify_summary: true,
    }),
    saveConfig: async (values) => console.log('save:', values),
    callApi: async (path, opts) => {
      console.log('api:', path, opts)
      return { is_active: false }
    },
    toast: {
      success: (msg) => console.log('success:', msg),
      error: (msg) => console.log('error:', msg),
    },
  },
})
app.mount('#app')