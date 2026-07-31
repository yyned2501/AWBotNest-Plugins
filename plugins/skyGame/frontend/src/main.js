// 本地预览入口（npm run dev）：模拟 host 把 Config.vue 跑起来
// 真正运行时由平台注入真实 host（见 Config.vue 注释）
import { createApp, h } from 'vue'
import Config from './Config.vue'

const DEFAULTS = {
  // 全局设置
  target_groups: '-1001326208894',
  bot: '',
  // 养马
  horse_enabled: false,
  horse_notify: true,
  // 炸金花
  zjh_enabled: true,
  zjh_cookie_file: '/home/hermes/.hermes/cookies/hdsky_cookie.txt',
  zjh_base_url: 'https://hdsky.supertimi.de:8443',
  zjh_poll_interval: 2,
  zjh_good_hands: ['豹子', '同花顺', '金花', '顺子', '对子'],
  zjh_notify_join: true,
  zjh_notify_hand: true,
  zjh_notify_fold_confirm: false,
  zjh_notify_error: true,
}

const mockHost = {
  pluginId: 'skyGame',
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
