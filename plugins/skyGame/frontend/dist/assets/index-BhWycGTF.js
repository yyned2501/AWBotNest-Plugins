import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-DArLvI4_.js';

true&&(function polyfill() {
  const relList = document.createElement("link").relList;
  if (relList && relList.supports && relList.supports("modulepreload")) {
    return;
  }
  for (const link of document.querySelectorAll('link[rel="modulepreload"]')) {
    processPreload(link);
  }
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "childList") {
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node.tagName === "LINK" && node.rel === "modulepreload")
          processPreload(node);
      }
    }
  }).observe(document, { childList: true, subtree: true });
  function getFetchOpts(link) {
    const fetchOpts = {};
    if (link.integrity) fetchOpts.integrity = link.integrity;
    if (link.referrerPolicy) fetchOpts.referrerPolicy = link.referrerPolicy;
    if (link.crossOrigin === "use-credentials")
      fetchOpts.credentials = "include";
    else if (link.crossOrigin === "anonymous") fetchOpts.credentials = "omit";
    else fetchOpts.credentials = "same-origin";
    return fetchOpts;
  }
  function processPreload(link) {
    if (link.ep)
      return;
    link.ep = true;
    const fetchOpts = getFetchOpts(link);
    fetch(link.href, fetchOpts);
  }
}());

// 本地预览入口（npm run dev）：模拟 host 把 Config.vue 跑起来
// 真正运行时由平台注入真实 host（见 Config.vue 注释）
const {createApp,h} = await importShared('vue');

const DEFAULTS = {
  // 全局设置
  target_groups: '-1001326208894',
  bot: '',
  hdsky_cookie_file: '/app/data/hdsky_cookie.txt',
  hdsky_base_url: 'https://hdsky.supertimi.de:8443',
  // Cookie 自动续期
  auth_auto_renew: true,
  cc_server: 'http://192.168.31.10:3000',
  cc_uuid: '',
  cc_password: '',
  hdsky_uid: '105577',
  auth_check_interval: 1800,
  auth_notify: true,
  // 养马
  horse_enabled: false,
  horse_poll_interval: 120,
  horse_feed_type: 'fine',
  horse_feed_threshold: 60,
  horse_auto_walk: true,
  horse_auto_match_race: true,
  horse_race_min_stamina: 30,
  horse_auto_official_race: false,
  horse_auto_revive: false,
  horse_notify: true,
  // 炸金花
  zjh_enabled: true,
  zjh_poll_interval: 2,
  zjh_good_hands: ['豹子', '同花顺', '金花', '顺子', '对子'],
  zjh_notify_join: true,
  zjh_notify_hand: true,
  zjh_notify_fold_confirm: false,
  zjh_notify_error: true,
};

const mockHost = {
  pluginId: 'skyGame',
  token: 'dev',
  async getConfig() {
    console.log('[mock] getConfig');
    return { ...DEFAULTS }
  },
  async saveConfig(values) {
    console.log('[mock] saveConfig', values);
  },
  async callApi(path, opts = {}) {
    console.log('[mock] callApi', path, opts);
    return { ok: true, data: [] }
  },
  toast: {
    success: (m) => console.log('[toast.success]', m),
    error: (m) => console.warn('[toast.error]', m),
  },
};

createApp({
  render: () => h(Config, { pluginId: mockHost.pluginId, host: mockHost }),
}).mount('#app');
