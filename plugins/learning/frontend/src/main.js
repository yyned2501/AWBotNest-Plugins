// 本地预览入口（npm run dev）：用一个「模拟 host」把 Config.vue 跑起来，
// 方便不启动平台也能调界面。真正运行时由平台注入真实 host（见 Config.vue 注释）。
import { createApp, h } from 'vue'
import Config from './Config.vue'

// learning 插件默认配置（与 Config.vue 内 DEFAULTS 保持一致）
const DEFAULTS = {
  api_key: '', base_url: '', model: 'gpt-3.5-turbo',
  summarize_gap: 10, max_context_lines: 5,
  target_groups: '',
  enable_participation: true, participation_rate: 20,
  participation_context_lines: 5, min_participation_gap: 60, participation_msg_gap: 5,
  keywords: '', max_keywords: 20, keyword_display: '',
  profile_display: '', profile_prompt_template: '',
}

const mockHost = {
  pluginId: 'learning',
  token: 'dev',
  async getConfig() {
    console.log('[mock] getConfig')
    return { ...DEFAULTS }
  },
  async saveConfig(values) {
    console.log('[mock] saveConfig', values)
  },
  toast: {
    success: (m) => console.log('[toast.success]', m),
    error: (m) => console.warn('[toast.error]', m),
  },
}

createApp({
  render: () => h(Config, { pluginId: mockHost.pluginId, host: mockHost }),
}).mount('#app')
