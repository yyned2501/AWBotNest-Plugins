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
const _hoisted_6 = {
  key: 0,
  class: "dot",
  title: "已启用"
};
const _hoisted_7 = { class: "detail" };
const _hoisted_8 = { class: "card" };
const _hoisted_9 = { class: "fld" };
const _hoisted_10 = { class: "fld" };
const _hoisted_11 = { class: "fld" };
const _hoisted_12 = { class: "card" };
const _hoisted_13 = { class: "grid" };
const _hoisted_14 = { class: "fld" };
const _hoisted_15 = { class: "fld" };
const _hoisted_16 = { class: "card" };
const _hoisted_17 = { class: "fld" };
const _hoisted_18 = { class: "card" };
const _hoisted_19 = { class: "row switch" };
const _hoisted_20 = {
  key: 0,
  class: "grid"
};
const _hoisted_21 = { class: "fld" };
const _hoisted_22 = { class: "fld" };
const _hoisted_23 = { class: "grid" };
const _hoisted_24 = { class: "fld" };
const _hoisted_25 = { class: "fld" };
const _hoisted_26 = { class: "card" };
const _hoisted_27 = { class: "fld" };
const _hoisted_28 = { class: "grid" };
const _hoisted_29 = { class: "fld" };
const _hoisted_30 = { class: "fld" };
const _hoisted_31 = ["value"];
const _hoisted_32 = { class: "card" };
const _hoisted_33 = { class: "fld" };
const _hoisted_34 = ["value"];
const _hoisted_35 = { class: "fld" };
const _hoisted_36 = { class: "savebar" };
const _hoisted_37 = ["disabled"];

const {ref,reactive,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
},
  setup(__props) {

// learning 插件 · 配置界面（模块联邦暴露为 ./Config，见 vite.config 的 exposes）。
// 平台运行时加载本组件并注入两个 prop：
//   pluginId: 本插件 id
//   host: 平台能力对象
//     host.getConfig()         读取本插件已保存配置（Promise<对象>）
//     host.saveConfig(values)  保存配置（Promise）——存平台统一存储，插件里 ctx.config 可读到
//     host.toast.success/error(msg)  弹平台提示
// 本插件没有后端 API（无 ctx.on_api），故不使用 host.callApi。
// 布局：左侧分组导航 + 右侧明细（master-detail），窄容器时侧栏收为横排 chips。
const props = __props;

// 默认配置（与 src/main.js 的 mock 保持一致）
const DEFAULTS = {
  api_key: '', base_url: '', model: 'gpt-3.5-turbo',
  summarize_gap: 10, max_context_lines: 5,
  target_groups: '',
  enable_participation: true, participation_rate: 20,
  participation_context_lines: 5, min_participation_gap: 60, participation_msg_gap: 5,
  keywords: '', max_keywords: 20, keyword_display: '',
  profile_display: '', profile_prompt_template: '',
};

// 左侧分组导航。en=对应启用开关键（有则显示启用小圆点）。
const GROUPS = [
  { key: 'api', label: '接口' },
  { key: 'learn', label: '学习' },
  { key: 'groups', label: '群组' },
  { key: 'participation', label: '参与', en: 'enable_participation' },
  { key: 'keywords', label: '关键词' },
  { key: 'profile', label: '身份模拟' },
];

const group = ref('api');
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

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[14] || (_cache[14] = _createElementVNode("div", { class: "side-title" }, "设置分组", -1)),
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(GROUPS, (g) => {
              return _createElementVNode("button", {
                key: g.key,
                class: _normalizeClass(['side-item', { on: group.value === g.key }]),
                onClick: $event => (group.value = g.key)
              }, [
                _createElementVNode("span", null, _toDisplayString(g.label), 1),
                (g.en && cfg[g.en])
                  ? (_openBlock(), _createElementBlock("span", _hoisted_6))
                  : _createCommentVNode("", true)
              ], 10, _hoisted_5)
            }), 64))
          ]),
          _createElementVNode("div", _hoisted_7, [
            (group.value === 'api')
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _cache[22] || (_cache[22] = _createElementVNode("h3", { class: "det-title" }, "接口", -1)),
                  _createElementVNode("section", _hoisted_8, [
                    _cache[21] || (_cache[21] = _createElementVNode("div", { class: "card-h" }, "LLM 接口（OpenAI 兼容）", -1)),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[15] || (_cache[15] = _createElementVNode("span", { class: "lbl" }, "API Key", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.api_key) = $event)),
                        class: "inp",
                        type: "password",
                        placeholder: "sk-…",
                        autocomplete: "off"
                      }, null, 512), [
                        [_vModelText, cfg.api_key]
                      ]),
                      _cache[16] || (_cache[16] = _createElementVNode("span", { class: "help" }, "OpenAI 兼容接口的密钥", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _cache[17] || (_cache[17] = _createElementVNode("span", { class: "lbl" }, "接口地址(Base URL)", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.base_url) = $event)),
                        class: "inp",
                        type: "text",
                        placeholder: "https://api.openai.com/v1"
                      }, null, 512), [
                        [_vModelText, cfg.base_url]
                      ]),
                      _cache[18] || (_cache[18] = _createElementVNode("span", { class: "help" }, "OpenAI 兼容接口地址，留空用官方默认", -1))
                    ]),
                    _createElementVNode("div", _hoisted_11, [
                      _cache[19] || (_cache[19] = _createElementVNode("span", { class: "lbl" }, "模型", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.model) = $event)),
                        class: "inp",
                        type: "text",
                        placeholder: "gpt-3.5-turbo"
                      }, null, 512), [
                        [_vModelText, cfg.model]
                      ]),
                      _cache[20] || (_cache[20] = _createElementVNode("span", { class: "help" }, "用于关键词风格分析和参与回复", -1))
                    ])
                  ])
                ], 64))
              : (group.value === 'learn')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[28] || (_cache[28] = _createElementVNode("h3", { class: "det-title" }, "学习", -1)),
                    _createElementVNode("section", _hoisted_12, [
                      _cache[27] || (_cache[27] = _createElementVNode("div", { class: "card-h" }, "自动总结", -1)),
                      _createElementVNode("div", _hoisted_13, [
                        _createElementVNode("div", _hoisted_14, [
                          _cache[23] || (_cache[23] = _createElementVNode("span", { class: "lbl" }, "总结间隔(条)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.summarize_gap) = $event)),
                            class: "inp",
                            type: "number",
                            min: "3",
                            max: "100"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.summarize_gap,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[24] || (_cache[24] = _createElementVNode("span", { class: "help" }, "每发这么多条消息就总结一次", -1))
                        ]),
                        _createElementVNode("div", _hoisted_15, [
                          _cache[25] || (_cache[25] = _createElementVNode("span", { class: "lbl" }, "总结上下文行数", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.max_context_lines) = $event)),
                            class: "inp",
                            type: "number",
                            min: "1",
                            max: "20"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.max_context_lines,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[26] || (_cache[26] = _createElementVNode("span", { class: "help" }, "总结时读取每条消息前 N 条上下文", -1))
                        ])
                      ])
                    ])
                  ], 64))
                : (group.value === 'groups')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _cache[32] || (_cache[32] = _createElementVNode("h3", { class: "det-title" }, "群组", -1)),
                      _createElementVNode("section", _hoisted_16, [
                        _cache[31] || (_cache[31] = _createElementVNode("div", { class: "card-h" }, "监听范围", -1)),
                        _createElementVNode("div", _hoisted_17, [
                          _cache[29] || (_cache[29] = _createElementVNode("span", { class: "lbl" }, "监听群组", -1)),
                          _withDirectives(_createElementVNode("textarea", {
                            "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.target_groups) = $event)),
                            class: "inp",
                            rows: "5",
                            placeholder: "每行一个群 ID\n也兼容逗号分隔\n留空 = 不监听任何群"
                          }, null, 512), [
                            [_vModelText, cfg.target_groups]
                          ]),
                          _cache[30] || (_cache[30] = _createElementVNode("span", { class: "help" }, "每个群 ID 一行，也兼容逗号分隔。留空=不监听", -1))
                        ])
                      ])
                    ], 64))
                  : (group.value === 'participation')
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                        _cache[39] || (_cache[39] = _createElementVNode("h3", { class: "det-title" }, "参与", -1)),
                        _createElementVNode("section", _hoisted_18, [
                          _cache[38] || (_cache[38] = _createElementVNode("div", { class: "card-h" }, "智能参与", -1)),
                          _createElementVNode("label", _hoisted_19, [
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.enable_participation) = $event)),
                              type: "checkbox"
                            }, null, 512), [
                              [_vModelCheckbox, cfg.enable_participation]
                            ]),
                            _cache[33] || (_cache[33] = _createElementVNode("span", null, "启用智能参与", -1))
                          ]),
                          (cfg.enable_participation)
                            ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
                                _createElementVNode("div", _hoisted_21, [
                                  _cache[34] || (_cache[34] = _createElementVNode("span", { class: "lbl" }, "参与概率(%)", -1)),
                                  _withDirectives(_createElementVNode("input", {
                                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((cfg.participation_rate) = $event)),
                                    class: "inp",
                                    type: "number",
                                    min: "1",
                                    max: "100"
                                  }, null, 512), [
                                    [
                                      _vModelText,
                                      cfg.participation_rate,
                                      void 0,
                                      { number: true }
                                    ]
                                  ])
                                ]),
                                _createElementVNode("div", _hoisted_22, [
                                  _cache[35] || (_cache[35] = _createElementVNode("span", { class: "lbl" }, "参与时读取上文(条)", -1)),
                                  _withDirectives(_createElementVNode("input", {
                                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cfg.participation_context_lines) = $event)),
                                    class: "inp",
                                    type: "number",
                                    min: "1",
                                    max: "20"
                                  }, null, 512), [
                                    [
                                      _vModelText,
                                      cfg.participation_context_lines,
                                      void 0,
                                      { number: true }
                                    ]
                                  ])
                                ])
                              ]))
                            : _createCommentVNode("", true),
                          _createElementVNode("div", _hoisted_23, [
                            _createElementVNode("div", _hoisted_24, [
                              _cache[36] || (_cache[36] = _createElementVNode("span", { class: "lbl" }, "发言冷却(秒)", -1)),
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((cfg.min_participation_gap) = $event)),
                                class: "inp",
                                type: "number",
                                min: "10",
                                max: "600",
                                step: "10"
                              }, null, 512), [
                                [
                                  _vModelText,
                                  cfg.min_participation_gap,
                                  void 0,
                                  { number: true }
                                ]
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_25, [
                              _cache[37] || (_cache[37] = _createElementVNode("span", { class: "lbl" }, "消息条数间隔", -1)),
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cfg.participation_msg_gap) = $event)),
                                class: "inp",
                                type: "number",
                                min: "1",
                                max: "50"
                              }, null, 512), [
                                [
                                  _vModelText,
                                  cfg.participation_msg_gap,
                                  void 0,
                                  { number: true }
                                ]
                              ])
                            ])
                          ])
                        ])
                      ], 64))
                    : (group.value === 'keywords')
                      ? (_openBlock(), _createElementBlock(_Fragment, { key: 4 }, [
                          _cache[46] || (_cache[46] = _createElementVNode("h3", { class: "det-title" }, "关键词", -1)),
                          _createElementVNode("section", _hoisted_26, [
                            _cache[45] || (_cache[45] = _createElementVNode("div", { class: "card-h" }, "关键词管理", -1)),
                            _createElementVNode("div", _hoisted_27, [
                              _cache[40] || (_cache[40] = _createElementVNode("span", { class: "lbl" }, "关键词（手动补充）", -1)),
                              _withDirectives(_createElementVNode("textarea", {
                                "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((cfg.keywords) = $event)),
                                class: "inp",
                                rows: "3",
                                placeholder: "每行一个，或逗号分隔"
                              }, null, 512), [
                                [_vModelText, cfg.keywords]
                              ]),
                              _cache[41] || (_cache[41] = _createElementVNode("span", { class: "help" }, "每行或逗号分隔，与自动学习的合并", -1))
                            ]),
                            _createElementVNode("div", _hoisted_28, [
                              _createElementVNode("div", _hoisted_29, [
                                _cache[42] || (_cache[42] = _createElementVNode("span", { class: "lbl" }, "关键词上限", -1)),
                                _withDirectives(_createElementVNode("input", {
                                  "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((cfg.max_keywords) = $event)),
                                  class: "inp",
                                  type: "number",
                                  min: "5",
                                  max: "100",
                                  step: "5"
                                }, null, 512), [
                                  [
                                    _vModelText,
                                    cfg.max_keywords,
                                    void 0,
                                    { number: true }
                                  ]
                                ])
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_30, [
                              _cache[43] || (_cache[43] = _createElementVNode("span", { class: "lbl" }, "已学关键词", -1)),
                              _createElementVNode("textarea", {
                                class: "inp ro",
                                value: cfg.keyword_display,
                                readonly: "",
                                rows: "4",
                                placeholder: "（暂无，运行后自动学习）"
                              }, null, 8, _hoisted_31),
                              _cache[44] || (_cache[44] = _createElementVNode("span", { class: "help" }, "自动学习，按命中次数降序", -1))
                            ])
                          ])
                        ], 64))
                      : (group.value === 'profile')
                        ? (_openBlock(), _createElementBlock(_Fragment, { key: 5 }, [
                            _cache[52] || (_cache[52] = _createElementVNode("h3", { class: "det-title" }, "身份模拟", -1)),
                            _createElementVNode("section", _hoisted_32, [
                              _cache[51] || (_cache[51] = _createElementVNode("div", { class: "card-h" }, "风格画像", -1)),
                              _createElementVNode("div", _hoisted_33, [
                                _cache[47] || (_cache[47] = _createElementVNode("span", { class: "lbl" }, "当前画像（自动累积）", -1)),
                                _createElementVNode("textarea", {
                                  class: "inp ro",
                                  value: cfg.profile_display,
                                  readonly: "",
                                  rows: "5",
                                  placeholder: "（暂无，学习后自动生成）"
                                }, null, 8, _hoisted_34),
                                _cache[48] || (_cache[48] = _createElementVNode("span", { class: "help" }, "每次学习后自动更新，仅供参考", -1))
                              ]),
                              _createElementVNode("div", _hoisted_35, [
                                _cache[49] || (_cache[49] = _createElementVNode("span", { class: "lbl" }, "画像总结模板", -1)),
                                _withDirectives(_createElementVNode("textarea", {
                                  "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((cfg.profile_prompt_template) = $event)),
                                  class: "inp mono",
                                  rows: "12",
                                  placeholder: "留空 = 使用插件内置默认模板"
                                }, null, 512), [
                                  [_vModelText, cfg.profile_prompt_template]
                                ]),
                                _cache[50] || (_cache[50] = _createElementVNode("span", { class: "help" }, "占位符: {context}=上下文, {my_messages}=我的发言", -1))
                              ])
                            ])
                          ], 64))
                        : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_36, [
              _createElementVNode("button", {
                class: "btn primary lg",
                disabled: saving.value,
                onClick: save
              }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_37)
            ])
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-059c899b"]]);

export { Config as default };
