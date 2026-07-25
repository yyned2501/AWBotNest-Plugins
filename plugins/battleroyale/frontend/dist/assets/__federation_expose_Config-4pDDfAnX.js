import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,renderList:_renderList,Fragment:_Fragment,createTextVNode:_createTextVNode,vModelText:_vModelText,withDirectives:_withDirectives,vModelCheckbox:_vModelCheckbox,vModelSelect:_vModelSelect} = await importShared('vue');


const _hoisted_1 = { class: "brcfg" };
const _hoisted_2 = {
  key: 0,
  class: "muted"
};
const _hoisted_3 = {
  key: 1,
  class: "layout"
};
const _hoisted_4 = { class: "left-panel" };
const _hoisted_5 = { class: "card" };
const _hoisted_6 = { class: "status-row" };
const _hoisted_7 = {
  key: 1,
  class: "tag idle"
};
const _hoisted_8 = {
  key: 0,
  class: "status-detail"
};
const _hoisted_9 = { class: "status-row" };
const _hoisted_10 = { class: "val" };
const _hoisted_11 = { class: "status-row" };
const _hoisted_12 = { class: "val" };
const _hoisted_13 = { class: "status-row" };
const _hoisted_14 = { class: "val" };
const _hoisted_15 = { key: 1 };
const _hoisted_16 = { class: "status-row" };
const _hoisted_17 = { class: "val" };
const _hoisted_18 = { class: "status-row" };
const _hoisted_19 = {
  key: 1,
  class: "status-row"
};
const _hoisted_20 = {
  key: 2,
  class: "action-row"
};
const _hoisted_21 = { class: "card" };
const _hoisted_22 = { class: "card-h" };
const _hoisted_23 = ["disabled"];
const _hoisted_24 = {
  key: 0,
  class: "muted"
};
const _hoisted_25 = {
  key: 1,
  class: "hist-list"
};
const _hoisted_26 = { class: "hist-round" };
const _hoisted_27 = { class: "hist-result" };
const _hoisted_28 = {
  key: 0,
  class: "hist-mut"
};
const _hoisted_29 = { class: "hist-votes" };
const _hoisted_30 = { class: "right-panel" };
const _hoisted_31 = { class: "card" };
const _hoisted_32 = { class: "fld" };
const _hoisted_33 = { class: "fld" };
const _hoisted_34 = { class: "card" };
const _hoisted_35 = { class: "row switch" };
const _hoisted_36 = {
  key: 0,
  class: "grid"
};
const _hoisted_37 = { class: "fld" };
const _hoisted_38 = { class: "fld" };
const _hoisted_39 = { class: "card" };
const _hoisted_40 = { class: "row switch" };
const _hoisted_41 = { class: "row switch" };
const _hoisted_42 = { class: "savebar" };
const _hoisted_43 = ["disabled"];

const {ref,reactive,onMounted,onUnmounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
},
  setup(__props) {

// 大逃杀助手 · 配置界面（模块联邦暴露为 ./Config）
// 接收 pluginId 和 host 两个 prop。
// host.getConfig() / host.saveConfig() 读写配置
// host.callApi(path) 调用后端 API
const props = __props;

const DEFAULTS = {
  chat_id: '', bot_id: 8835151149,
  auto_bet: true, bet_timing: 5, bet_strategy: '少',
  notify_round: true, notify_summary: true,
};

const loading = ref(true);
const saving = ref(false);
const cfg = reactive({ ...DEFAULTS });
const status = ref(null);
const history = ref([]);
const statusLoading = ref(false);
const historyLoading = ref(false);
let pollTimer = null;

// ── 配置读写 ──

onMounted(async () => {
  try {
    const saved = await props.host.getConfig();
    Object.assign(cfg, DEFAULTS, saved || {});
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e));
  } finally {
    loading.value = false;
  }
  fetchStatus();
  fetchHistory();
  // 每 5 秒轮询状态
  pollTimer = setInterval(fetchStatus, 5000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});

async function save() {
  saving.value = true;
  try {
    await props.host.saveConfig({ ...cfg });
    props.host.toast.success('配置已保存');
  } catch (e) {
    props.host.toast.error('保存失败：' + (e.message || e));
  } finally {
    saving.value = false;
  }
}

// ── API 调用 ──

async function fetchStatus() {
  statusLoading.value = true;
  try {
    const res = await props.host.callApi('/status');
    status.value = res;
  } catch {
    // 静默失败，轮询不用每次都弹
  } finally {
    statusLoading.value = false;
  }
}

async function fetchHistory() {
  historyLoading.value = true;
  try {
    const res = await props.host.callApi('/history');
    history.value = res || [];
  } catch (e) {
    props.host.toast.error('获取历史失败：' + (e.message || e));
  } finally {
    historyLoading.value = false;
  }
}

async function forceBet() {
  try {
    await props.host.callApi('/force_bet', { method: 'POST' });
    props.host.toast.success('下注指令已发送');
    fetchStatus();
  } catch (e) {
    props.host.toast.error('下注失败：' + (e.message || e));
  }
}

async function resetGame() {
  try {
    await props.host.callApi('/reset', { method: 'POST' });
    props.host.toast.success('游戏状态已重置');
    fetchStatus();
  } catch (e) {
    props.host.toast.error('重置失败：' + (e.message || e));
  }
}

function fmtDeadline(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000);
  const now = Date.now();
  const diff = d.getTime() - now;
  if (diff <= 0) return '已过期'
  const min = Math.floor(diff / 60000);
  const sec = Math.floor((diff % 60000) / 1000);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')} (剩余${min}分${sec}秒)`
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[16] || (_cache[16] = _createElementVNode("h3", { class: "panel-title" }, "实时状态", -1)),
            _createElementVNode("section", _hoisted_5, [
              _cache[14] || (_cache[14] = _createElementVNode("div", { class: "card-h" }, "游戏状态", -1)),
              _createElementVNode("div", _hoisted_6, [
                _cache[7] || (_cache[7] = _createElementVNode("span", { class: "lbl" }, "状态", -1)),
                (status.value)
                  ? (_openBlock(), _createElementBlock("span", {
                      key: 0,
                      class: _normalizeClass(['tag', status.value.is_active ? 'active' : 'idle'])
                    }, _toDisplayString(status.value.is_active ? '进行中' : '空闲'), 3))
                  : (_openBlock(), _createElementBlock("span", _hoisted_7, "未知"))
              ]),
              (status.value && status.value.is_active)
                ? (_openBlock(), _createElementBlock("div", _hoisted_8, [
                    _createElementVNode("div", _hoisted_9, [
                      _cache[8] || (_cache[8] = _createElementVNode("span", { class: "lbl" }, "当前圈数", -1)),
                      _createElementVNode("span", _hoisted_10, "第" + _toDisplayString(status.value.round) + "圈", 1)
                    ]),
                    _createElementVNode("div", _hoisted_11, [
                      _cache[9] || (_cache[9] = _createElementVNode("span", { class: "lbl" }, "选项", -1)),
                      _createElementVNode("span", _hoisted_12, _toDisplayString(status.value.options?.join(' / ') || '—'), 1)
                    ]),
                    _createElementVNode("div", _hoisted_13, [
                      _cache[10] || (_cache[10] = _createElementVNode("span", { class: "lbl" }, "投票统计", -1)),
                      _createElementVNode("span", _hoisted_14, [
                        (status.value.votes && Object.keys(status.value.votes).length)
                          ? (_openBlock(true), _createElementBlock(_Fragment, { key: 0 }, _renderList(status.value.votes, (cnt, opt) => {
                              return (_openBlock(), _createElementBlock("span", {
                                key: opt,
                                class: "vote-chip"
                              }, _toDisplayString(opt) + ": " + _toDisplayString(cnt) + "票 ", 1))
                            }), 128))
                          : (_openBlock(), _createElementBlock("span", _hoisted_15, "暂无投票"))
                      ])
                    ]),
                    _createElementVNode("div", _hoisted_16, [
                      _cache[11] || (_cache[11] = _createElementVNode("span", { class: "lbl" }, "结算时间", -1)),
                      _createElementVNode("span", _hoisted_17, _toDisplayString(fmtDeadline(status.value.deadline_ts)), 1)
                    ]),
                    _createElementVNode("div", _hoisted_18, [
                      _cache[12] || (_cache[12] = _createElementVNode("span", { class: "lbl" }, "自动下注", -1)),
                      _createElementVNode("span", {
                        class: _normalizeClass(['tag', status.value.bet_placed ? 'done' : 'wait'])
                      }, _toDisplayString(status.value.bet_placed ? '已下注' : '等待中'), 3)
                    ])
                  ]))
                : (_openBlock(), _createElementBlock("div", _hoisted_19, [...(_cache[13] || (_cache[13] = [
                    _createElementVNode("span", { class: "val muted" }, "等待游戏开始…", -1)
                  ]))])),
              (status.value && status.value.is_active)
                ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
                    _createElementVNode("button", {
                      class: "btn sm",
                      onClick: forceBet
                    }, "手动下注"),
                    _createElementVNode("button", {
                      class: "btn sm danger",
                      onClick: resetGame
                    }, "重置")
                  ]))
                : _createCommentVNode("", true)
            ]),
            _createElementVNode("section", _hoisted_21, [
              _createElementVNode("div", _hoisted_22, [
                _cache[15] || (_cache[15] = _createTextVNode(" 历史记录 ", -1)),
                _createElementVNode("button", {
                  class: "btn sm",
                  onClick: fetchHistory,
                  disabled: historyLoading.value
                }, "刷新", 8, _hoisted_23)
              ]),
              (history.value.length === 0)
                ? (_openBlock(), _createElementBlock("div", _hoisted_24, "暂无记录"))
                : (_openBlock(), _createElementBlock("div", _hoisted_25, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList([...history.value].reverse(), (h) => {
                      return (_openBlock(), _createElementBlock("div", {
                        key: h.round + h.time,
                        class: "hist-item"
                      }, [
                        _createElementVNode("span", _hoisted_26, "第" + _toDisplayString(h.round) + "圈", 1),
                        _createElementVNode("span", _hoisted_27, "结果: " + _toDisplayString(h.result), 1),
                        (h.mutation)
                          ? (_openBlock(), _createElementBlock("span", _hoisted_28, "基因突变"))
                          : _createCommentVNode("", true),
                        _createElementVNode("span", _hoisted_29, _toDisplayString(Object.entries(h.votes).map(([k, v]) => `${k}=${v}`).join(' ')), 1)
                      ]))
                    }), 128))
                  ]))
            ])
          ]),
          _createElementVNode("div", _hoisted_30, [
            _cache[31] || (_cache[31] = _createElementVNode("h3", { class: "panel-title" }, "配置", -1)),
            _createElementVNode("section", _hoisted_31, [
              _cache[21] || (_cache[21] = _createElementVNode("div", { class: "card-h" }, "监听", -1)),
              _createElementVNode("div", _hoisted_32, [
                _cache[17] || (_cache[17] = _createElementVNode("span", { class: "lbl" }, "监听群组", -1)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.chat_id) = $event)),
                  class: "inp",
                  type: "text",
                  placeholder: "如 -1003808371287"
                }, null, 512), [
                  [_vModelText, cfg.chat_id]
                ]),
                _cache[18] || (_cache[18] = _createElementVNode("span", { class: "help" }, "监听的群组 chat_id", -1))
              ]),
              _createElementVNode("div", _hoisted_33, [
                _cache[19] || (_cache[19] = _createElementVNode("span", { class: "lbl" }, "游戏 Bot ID", -1)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.bot_id) = $event)),
                  class: "inp",
                  type: "number"
                }, null, 512), [
                  [
                    _vModelText,
                    cfg.bot_id,
                    void 0,
                    { number: true }
                  ]
                ]),
                _cache[20] || (_cache[20] = _createElementVNode("span", { class: "help" }, "@NextFunBot 的 user_id", -1))
              ])
            ]),
            _createElementVNode("section", _hoisted_34, [
              _cache[27] || (_cache[27] = _createElementVNode("div", { class: "card-h" }, "自动下注", -1)),
              _createElementVNode("label", _hoisted_35, [
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.auto_bet) = $event)),
                  type: "checkbox"
                }, null, 512), [
                  [_vModelCheckbox, cfg.auto_bet]
                ]),
                _cache[22] || (_cache[22] = _createElementVNode("span", null, "启用自动下注", -1))
              ]),
              (cfg.auto_bet)
                ? (_openBlock(), _createElementBlock("div", _hoisted_36, [
                    _createElementVNode("div", _hoisted_37, [
                      _cache[23] || (_cache[23] = _createElementVNode("span", { class: "lbl" }, "结算前下注(秒)", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.bet_timing) = $event)),
                        class: "inp",
                        type: "number",
                        min: "0",
                        max: "30"
                      }, null, 512), [
                        [
                          _vModelText,
                          cfg.bet_timing,
                          void 0,
                          { number: true }
                        ]
                      ]),
                      _cache[24] || (_cache[24] = _createElementVNode("span", { class: "help" }, "距结算多少秒时下注", -1))
                    ]),
                    _createElementVNode("div", _hoisted_38, [
                      _cache[26] || (_cache[26] = _createElementVNode("span", { class: "lbl" }, "下注策略", -1)),
                      _withDirectives(_createElementVNode("select", {
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.bet_strategy) = $event)),
                        class: "inp"
                      }, [...(_cache[25] || (_cache[25] = [
                        _createElementVNode("option", { value: "少" }, "人少（以少胜多规则）", -1),
                        _createElementVNode("option", { value: "多" }, "人多（跟风策略）", -1)
                      ]))], 512), [
                        [_vModelSelect, cfg.bet_strategy]
                      ])
                    ])
                  ]))
                : _createCommentVNode("", true)
            ]),
            _createElementVNode("section", _hoisted_39, [
              _cache[30] || (_cache[30] = _createElementVNode("div", { class: "card-h" }, "通知", -1)),
              _createElementVNode("label", _hoisted_40, [
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.notify_round) = $event)),
                  type: "checkbox"
                }, null, 512), [
                  [_vModelCheckbox, cfg.notify_round]
                ]),
                _cache[28] || (_cache[28] = _createElementVNode("span", null, "每圈结算通知", -1))
              ]),
              _createElementVNode("label", _hoisted_41, [
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.notify_summary) = $event)),
                  type: "checkbox"
                }, null, 512), [
                  [_vModelCheckbox, cfg.notify_summary]
                ]),
                _cache[29] || (_cache[29] = _createElementVNode("span", null, "游戏结束总结", -1))
              ])
            ]),
            _createElementVNode("div", _hoisted_42, [
              _createElementVNode("button", {
                class: "btn primary lg",
                disabled: saving.value,
                onClick: save
              }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_43)
            ])
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-526f8daa"]]);

export { Config as default };
