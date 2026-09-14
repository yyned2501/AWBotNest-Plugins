// 本地预览入口（npm run dev）：模拟 host 把 Config.vue 跑起来
// 真正运行时由平台注入真实 host（见 Config.vue 注释）
import { createApp, h } from 'vue'
import Config from './Config.vue'

const DEFAULTS = {
  enable_reward_answer: false,
  reward_bot_ids: '',
  reward_delay_min: 2,
  reward_delay_max: 5,
  use_ai_fallback: true,
  enable_template_learning: true,
}

const mockHost = {
  pluginId: 'skyDropAnswer',
  token: 'dev',
  async getConfig() {
    console.log('[mock] getConfig')
    return { ...DEFAULTS }
  },
  async saveConfig(values) {
    console.log('[mock] saveConfig', values)
  },
  async callApi(path, opts = {}) {
    console.log('[mock] callApi', path, opts)
    return { ok: true, data: [] }
  },
  toast: {
    success: (m) => console.log('[toast.success]', m),
    error: (m) => console.warn('[toast.error]', m),
  },
}

createApp({
  render: () => h(Config, { pluginId: mockHost.pluginId, host: mockHost }),
}).mount('#app')