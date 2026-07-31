import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,vModelText:_vModelText,withDirectives:_withDirectives,vModelCheckbox:_vModelCheckbox} = await importShared('vue');


const _hoisted_1 = { class: "lcfg" };
const _hoisted_2 = {
  key: 0,
  class: "muted"
};
const _hoisted_3 = {
  key: 1,
  class: "layout"
};
const _hoisted_4 = { class: "sidebar" };
const _hoisted_5 = ["onClick"];
const _hoisted_6 = { class: "side-icon" };
const _hoisted_7 = { class: "detail" };
const _hoisted_8 = { class: "card" };
const _hoisted_9 = { class: "fld" };
const _hoisted_10 = { class: "fld" };
const _hoisted_11 = { class: "savebar" };
const _hoisted_12 = ["disabled"];
const _hoisted_13 = { class: "card" };
const _hoisted_14 = { class: "row switch" };
const _hoisted_15 = { class: "row switch" };
const _hoisted_16 = { class: "savebar" };
const _hoisted_17 = ["disabled"];
const _hoisted_18 = { class: "card" };
const _hoisted_19 = { class: "row switch" };
const _hoisted_20 = { class: "fld" };
const _hoisted_21 = { class: "grid" };
const _hoisted_22 = { class: "fld" };
const _hoisted_23 = { class: "fld" };
const _hoisted_24 = { class: "card" };
const _hoisted_25 = { class: "fld" };
const _hoisted_26 = { class: "hand-grid" };
const _hoisted_27 = ["checked", "onChange"];
const _hoisted_28 = { class: "card" };
const _hoisted_29 = { class: "row switch" };
const _hoisted_30 = { class: "row switch" };
const _hoisted_31 = { class: "row switch" };
const _hoisted_32 = { class: "row switch" };
const _hoisted_33 = { class: "savebar" };
const _hoisted_34 = ["disabled"];

const {ref,reactive,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
},
  setup(__props) {

// 天空游戏 · 配置界面
// 左侧按游戏分组：全局设置 / 养马 / 炸金花
// host.getConfig() / host.saveConfig() / host.callApi()
const props = __props;

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
};

// 左侧分组：按游戏归类
const GROUPS = [
  { key: 'global', label: '全局设置', icon: '⚙️' },
  { key: 'horse', label: '养马', icon: '🐴' },
  { key: 'zjh', label: '炸金花', icon: '🃏' },
];

// 炸金花可勾选的牌型
const HAND_TYPES = ['豹子', '同花顺', '金花', '顺子', '对子', '散牌'];

const group = ref('global');
const loading = ref(true);
const saving = ref(false);
const cfg = reactive({ ...DEFAULTS });

onMounted(async () => {
  try {
    const saved = await props.host.getConfig();
    Object.assign(cfg, DEFAULTS, saved || {});
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e));
  } finally {
    loading.value = false;
  }
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

// 跟注牌型多选：zjh_good_hands 是字符串数组
function hasHand(h) {
  return Array.isArray(cfg.zjh_good_hands) && cfg.zjh_good_hands.includes(h)
}
function toggleHand(h) {
  if (!Array.isArray(cfg.zjh_good_hands)) cfg.zjh_good_hands = [];
  const i = cfg.zjh_good_hands.indexOf(h);
  if (i >= 0) cfg.zjh_good_hands.splice(i, 1);
  else cfg.zjh_good_hands.push(h);
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[12] || (_cache[12] = _createElementVNode("div", { class: "side-title" }, "游戏", -1)),
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(GROUPS, (g) => {
              return _createElementVNode("button", {
                key: g.key,
                class: _normalizeClass(['side-item', { on: group.value === g.key }]),
                onClick: $event => (group.value = g.key)
              }, [
                _createElementVNode("span", _hoisted_6, _toDisplayString(g.icon), 1),
                _createElementVNode("span", null, _toDisplayString(g.label), 1)
              ], 10, _hoisted_5)
            }), 64))
          ]),
          _createElementVNode("div", _hoisted_7, [
            (group.value === 'global')
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _cache[18] || (_cache[18] = _createElementVNode("h3", { class: "det-title" }, "全局设置", -1)),
                  _createElementVNode("section", _hoisted_8, [
                    _cache[17] || (_cache[17] = _createElementVNode("div", { class: "card-h" }, "目标与机器人", -1)),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[13] || (_cache[13] = _createElementVNode("span", { class: "lbl" }, "目标群组（一行一个ID）", -1)),
                      _withDirectives(_createElementVNode("textarea", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.target_groups) = $event)),
                        class: "inp",
                        rows: "3",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.target_groups]
                      ]),
                      _cache[14] || (_cache[14] = _createElementVNode("span", { class: "help" }, "游戏消息发到的群，一行一个。", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _cache[15] || (_cache[15] = _createElementVNode("span", { class: "lbl" }, "天空小秘机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.bot) = $event)),
                        class: "inp",
                        placeholder: "@用户名 或 数字ID，逗号分隔可填多个"
                      }, null, 512), [
                        [_vModelText, cfg.bot]
                      ]),
                      _cache[16] || (_cache[16] = _createElementVNode("span", { class: "help" }, "留空=默认天空小秘。", -1))
                    ])
                  ]),
                  _createElementVNode("div", _hoisted_11, [
                    _createElementVNode("button", {
                      class: "btn primary lg",
                      disabled: saving.value,
                      onClick: save
                    }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_12)
                  ])
                ], 64))
              : (group.value === 'horse')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[23] || (_cache[23] = _createElementVNode("h3", { class: "det-title" }, "养马", -1)),
                    _createElementVNode("section", _hoisted_13, [
                      _cache[21] || (_cache[21] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                      _createElementVNode("label", _hoisted_14, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.horse_enabled) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_enabled]
                        ]),
                        _cache[19] || (_cache[19] = _createElementVNode("span", null, "启用养马", -1))
                      ]),
                      _createElementVNode("label", _hoisted_15, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.horse_notify) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_notify]
                        ]),
                        _cache[20] || (_cache[20] = _createElementVNode("span", null, "养马通知", -1))
                      ]),
                      _cache[22] || (_cache[22] = _createElementVNode("div", { class: "notice" }, "🐴 养马逻辑开发中，启用后仅记录提示，暂无自动操作。", -1))
                    ]),
                    _createElementVNode("div", _hoisted_16, [
                      _createElementVNode("button", {
                        class: "btn primary lg",
                        disabled: saving.value,
                        onClick: save
                      }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_17)
                    ])
                  ], 64))
                : (group.value === 'zjh')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _cache[39] || (_cache[39] = _createElementVNode("h3", { class: "det-title" }, "炸金花", -1)),
                      _createElementVNode("section", _hoisted_18, [
                        _cache[29] || (_cache[29] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                        _createElementVNode("label", _hoisted_19, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.zjh_enabled) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_enabled]
                          ]),
                          _cache[24] || (_cache[24] = _createElementVNode("span", null, "启用自动参与", -1))
                        ]),
                        _cache[30] || (_cache[30] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "轮询牌局：自动加入 → 看牌 → 好牌跟注 / 烂牌弃牌", -1)),
                        _createElementVNode("div", _hoisted_20, [
                          _cache[25] || (_cache[25] = _createElementVNode("span", { class: "lbl" }, "Cookie 文件路径", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.zjh_cookie_file) = $event)),
                            class: "inp",
                            spellcheck: "false"
                          }, null, 512), [
                            [_vModelText, cfg.zjh_cookie_file]
                          ]),
                          _cache[26] || (_cache[26] = _createElementVNode("span", { class: "help" }, "hdsky_portal_session cookie 文件路径", -1))
                        ]),
                        _createElementVNode("div", _hoisted_21, [
                          _createElementVNode("div", _hoisted_22, [
                            _cache[27] || (_cache[27] = _createElementVNode("span", { class: "lbl" }, "服务器地址", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.zjh_base_url) = $event)),
                              class: "inp",
                              spellcheck: "false"
                            }, null, 512), [
                              [_vModelText, cfg.zjh_base_url]
                            ])
                          ]),
                          _createElementVNode("div", _hoisted_23, [
                            _cache[28] || (_cache[28] = _createElementVNode("span", { class: "lbl" }, "轮询间隔(秒)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((cfg.zjh_poll_interval) = $event)),
                              class: "inp",
                              type: "number",
                              min: "1",
                              max: "10",
                              step: "0.5"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.zjh_poll_interval,
                                void 0,
                                { number: true }
                              ]
                            ])
                          ])
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_24, [
                        _cache[33] || (_cache[33] = _createElementVNode("div", { class: "card-h" }, "跟注牌型", -1)),
                        _createElementVNode("div", _hoisted_25, [
                          _cache[31] || (_cache[31] = _createElementVNode("span", { class: "lbl" }, "勾选的牌型跟注，未勾选的弃牌", -1)),
                          _createElementVNode("div", _hoisted_26, [
                            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(HAND_TYPES, (h) => {
                              return _createElementVNode("label", {
                                key: h,
                                class: "row switch"
                              }, [
                                _createElementVNode("input", {
                                  type: "checkbox",
                                  checked: hasHand(h),
                                  onChange: $event => (toggleHand(h))
                                }, null, 40, _hoisted_27),
                                _createElementVNode("span", null, _toDisplayString(h), 1)
                              ])
                            }), 64))
                          ]),
                          _cache[32] || (_cache[32] = _createElementVNode("span", { class: "help" }, "全不选时回退默认五种好牌（豹子/同花顺/金花/顺子/对子）", -1))
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_28, [
                        _cache[38] || (_cache[38] = _createElementVNode("div", { class: "card-h" }, "通知", -1)),
                        _createElementVNode("label", _hoisted_29, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cfg.zjh_notify_join) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_join]
                          ]),
                          _cache[34] || (_cache[34] = _createElementVNode("span", null, "加入牌局", -1))
                        ]),
                        _createElementVNode("label", _hoisted_30, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((cfg.zjh_notify_hand) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_hand]
                          ]),
                          _cache[35] || (_cache[35] = _createElementVNode("span", null, "手牌决策（跟注/弃牌）", -1))
                        ]),
                        _createElementVNode("label", _hoisted_31, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cfg.zjh_notify_fold_confirm) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_fold_confirm]
                          ]),
                          _cache[36] || (_cache[36] = _createElementVNode("span", null, "双击确认弃牌", -1))
                        ]),
                        _createElementVNode("label", _hoisted_32, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((cfg.zjh_notify_error) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_error]
                          ]),
                          _cache[37] || (_cache[37] = _createElementVNode("span", null, "异常", -1))
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_33, [
                        _createElementVNode("button", {
                          class: "btn primary lg",
                          disabled: saving.value,
                          onClick: save
                        }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_34)
                      ])
                    ], 64))
                  : _createCommentVNode("", true)
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-e3878450"]]);

export { Config as default };
