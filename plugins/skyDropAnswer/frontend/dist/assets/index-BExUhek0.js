import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-e6DRs5lW.js';

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
  enable_reward_answer: false,
  reward_bot_ids: '',
  reward_delay_min: 2,
  reward_delay_max: 5,
  use_ai_fallback: true,
  enable_template_learning: true,
};

const mockHost = {
  pluginId: 'skyDropAnswer',
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
