import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-4pDDfAnX.js';

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

// 开发模式入口，仅用于本地预览
const {createApp} = await importShared('vue');

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
      console.log('api:', path, opts);
      return { is_active: false }
    },
    toast: {
      success: (msg) => console.log('success:', msg),
      error: (msg) => console.log('error:', msg),
    },
  },
});
app.mount('#app');
