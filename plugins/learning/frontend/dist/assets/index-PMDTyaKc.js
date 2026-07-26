import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-DUDPNcCn.js';

true              &&(function polyfill() {
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

// 本地预览入口（npm run dev）：用一个「模拟 host」把 Config.vue 跑起来，
// 方便不启动平台也能调界面。真正运行时由平台注入真实 host（见 Config.vue 注释）。
const {createApp,h} = await importShared('vue');

// learning 插件默认配置（与 Config.vue 内 DEFAULTS 保持一致）
const DEFAULTS = {
  api_key: '', base_url: '', model: 'gpt-3.5-turbo',
  summarize_gap: 10, max_context_lines: 5,
  target_groups: '',
  enable_participation: true, participation_rate: 20,
  participation_context_lines: 5, min_participation_gap: 60, participation_msg_gap: 5,
  keywords: '', max_keywords: 20, keyword_display: '',
  profile_display: '', profile_prompt_template: '',
};

const mockHost = {
  pluginId: 'learning',
  token: 'dev',
  async getConfig() {
    console.log('[mock] getConfig');
    return { ...DEFAULTS }
  },
  async saveConfig(values) {
    console.log('[mock] saveConfig', values);
  },
  toast: {
    success: (m) => console.log('[toast.success]', m),
    error: (m) => console.warn('[toast.error]', m),
  },
};

createApp({
  render: () => h(Config, { pluginId: mockHost.pluginId, host: mockHost }),
}).mount('#app');
