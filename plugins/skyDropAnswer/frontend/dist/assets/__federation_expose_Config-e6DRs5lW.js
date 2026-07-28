import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,vModelText:_vModelText,createTextVNode:_createTextVNode} = await importShared('vue');


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
const _hoisted_6 = { class: "detail" };
const _hoisted_7 = { class: "card" };
const _hoisted_8 = { class: "row switch" };
const _hoisted_9 = { class: "fld" };
const _hoisted_10 = { class: "grid" };
const _hoisted_11 = { class: "fld" };
const _hoisted_12 = { class: "fld" };
const _hoisted_13 = { class: "card" };
const _hoisted_14 = { class: "row switch" };
const _hoisted_15 = { class: "row switch" };
const _hoisted_16 = { class: "savebar" };
const _hoisted_17 = ["disabled"];
const _hoisted_18 = { class: "card" };
const _hoisted_19 = {
  class: "card-h",
  style: {"display":"flex","justify-content":"space-between","align-items":"center"}
};
const _hoisted_20 = {
  key: 0,
  class: "muted"
};
const _hoisted_21 = {
  key: 1,
  class: "muted",
  style: {"padding":"24px 0","text-align":"center"}
};
const _hoisted_22 = {
  key: 2,
  class: "tpl-list"
};
const _hoisted_23 = { class: "tpl-header" };
const _hoisted_24 = { class: "tpl-type" };
const _hoisted_25 = { class: "tpl-count" };
const _hoisted_26 = ["onClick"];
const _hoisted_27 = { class: "tpl-row" };
const _hoisted_28 = { class: "tpl-regex" };
const _hoisted_29 = { class: "tpl-row" };
const _hoisted_30 = { class: "tpl-sample" };
const _hoisted_31 = { class: "tpl-row" };
const _hoisted_32 = { class: "tpl-answer" };

const {ref,reactive,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
},
  setup(__props) {

// 天空答题 · 配置界面
// host.getConfig() / host.saveConfig() / host.callApi()
const props = __props;

const DEFAULTS = {
  enable_reward_answer: false,
  reward_bot_ids: '',
  reward_delay_min: 2,
  reward_delay_max: 5,
  use_ai_fallback: true,
  enable_template_learning: true,
};

const GROUPS = [
  { key: 'reward', label: '答题奖励' },
  { key: 'templates', label: '学习模板' },
];

const group = ref('reward');
const loading = ref(true);
const saving = ref(false);
const cfg = reactive({ ...DEFAULTS });
const templates = ref([]);
const tplLoading = ref(false);

onMounted(async () => {
  try {
    const saved = await props.host.getConfig();
    Object.assign(cfg, DEFAULTS, saved || {});
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e));
  } finally {
    loading.value = false;
  }
  loadTemplates();
});

async function loadTemplates() {
  tplLoading.value = true;
  try {
    const res = await props.host.callApi('/api/templates');
    templates.value = (res && res.data) || [];
  } catch (e) {
    props.host.toast.error('加载模板失败：' + (e.message || e));
  } finally {
    tplLoading.value = false;
  }
}

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

async function deleteTemplate(tpl) {
  try {
    await fetch(`/api/plugins/${props.pluginId}/api/templates`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: tpl.id }),
    });
    props.host.toast.success('已删除');
    loadTemplates();
  } catch (e) {
    props.host.toast.error('删除失败：' + (e.message || e));
  }
}

async function clearTemplates() {
  try {
    await fetch(`/api/plugins/${props.pluginId}/api/templates/clear`, {
      method: 'POST',
    });
    props.host.toast.success('已清空');
    loadTemplates();
  } catch (e) {
    props.host.toast.error('清空失败：' + (e.message || e));
  }
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[6] || (_cache[6] = _createElementVNode("div", { class: "side-title" }, "设置分组", -1)),
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(GROUPS, (g) => {
              return _createElementVNode("button", {
                key: g.key,
                class: _normalizeClass(['side-item', { on: group.value === g.key }]),
                onClick: $event => (group.value = g.key)
              }, [
                _createElementVNode("span", null, _toDisplayString(g.label), 1)
              ], 10, _hoisted_5)
            }), 64))
          ]),
          _createElementVNode("div", _hoisted_6, [
            (group.value === 'reward')
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _cache[18] || (_cache[18] = _createElementVNode("h3", { class: "det-title" }, "答题奖励", -1)),
                  _createElementVNode("section", _hoisted_7, [
                    _cache[12] || (_cache[12] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                    _createElementVNode("label", _hoisted_8, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.enable_reward_answer) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.enable_reward_answer]
                      ]),
                      _cache[7] || (_cache[7] = _createElementVNode("span", null, "开启答题奖励", -1))
                    ]),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[8] || (_cache[8] = _createElementVNode("span", { class: "lbl" }, "答题机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.reward_bot_ids) = $event)),
                        class: "inp",
                        placeholder: "@机器人用户名，逗号分隔"
                      }, null, 512), [
                        [_vModelText, cfg.reward_bot_ids]
                      ]),
                      _cache[9] || (_cache[9] = _createElementVNode("span", { class: "help" }, "@机器人用户名，逗号分隔。留空=不限", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _createElementVNode("div", _hoisted_11, [
                        _cache[10] || (_cache[10] = _createElementVNode("span", { class: "lbl" }, "延迟最小(秒)", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.reward_delay_min) = $event)),
                          class: "inp",
                          type: "number",
                          min: "1",
                          max: "30"
                        }, null, 512), [
                          [
                            _vModelText,
                            cfg.reward_delay_min,
                            void 0,
                            { number: true }
                          ]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_12, [
                        _cache[11] || (_cache[11] = _createElementVNode("span", { class: "lbl" }, "延迟最大(秒)", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.reward_delay_max) = $event)),
                          class: "inp",
                          type: "number",
                          min: "1",
                          max: "60"
                        }, null, 512), [
                          [
                            _vModelText,
                            cfg.reward_delay_max,
                            void 0,
                            { number: true }
                          ]
                        ])
                      ])
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_13, [
                    _cache[15] || (_cache[15] = _createElementVNode("div", { class: "card-h" }, "智能答题", -1)),
                    _createElementVNode("label", _hoisted_14, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.use_ai_fallback) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.use_ai_fallback]
                      ]),
                      _cache[13] || (_cache[13] = _createElementVNode("span", null, "AI智能答题", -1))
                    ]),
                    _cache[16] || (_cache[16] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, "未知题型时使用AI分析并回答", -1)),
                    _createElementVNode("label", _hoisted_15, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.enable_template_learning) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.enable_template_learning]
                      ]),
                      _cache[14] || (_cache[14] = _createElementVNode("span", null, "AI学习模板", -1))
                    ]),
                    _cache[17] || (_cache[17] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, "AI答完题后自动提取模板，下次同类题直接脚本答", -1))
                  ]),
                  _createElementVNode("div", _hoisted_16, [
                    _createElementVNode("button", {
                      class: "btn primary lg",
                      disabled: saving.value,
                      onClick: save
                    }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_17)
                  ])
                ], 64))
              : (group.value === 'templates')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[23] || (_cache[23] = _createElementVNode("h3", { class: "det-title" }, "学习模板", -1)),
                    _createElementVNode("div", _hoisted_18, [
                      _createElementVNode("div", _hoisted_19, [
                        _createElementVNode("span", null, "已学模板（" + _toDisplayString(templates.value.length) + "）", 1),
                        (templates.value.length > 0)
                          ? (_openBlock(), _createElementBlock("button", {
                              key: 0,
                              class: "btn sm danger",
                              onClick: clearTemplates
                            }, "清空全部"))
                          : _createCommentVNode("", true)
                      ]),
                      (tplLoading.value)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_20, "加载中…"))
                        : (templates.value.length === 0)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_21, [...(_cache[19] || (_cache[19] = [
                              _createTextVNode(" 暂无学习模板", -1),
                              _createElementVNode("br", null, null, -1),
                              _createElementVNode("span", { style: {"font-size":"12px","color":"#7a8291"} }, "AI智能答题后自动生成，下次同类题直接命中", -1)
                            ]))]))
                          : (_openBlock(), _createElementBlock("div", _hoisted_22, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(templates.value, (tpl) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: tpl.id,
                                  class: "tpl-card"
                                }, [
                                  _createElementVNode("div", _hoisted_23, [
                                    _createElementVNode("span", _hoisted_24, _toDisplayString(tpl.type || '未知'), 1),
                                    _createElementVNode("span", _hoisted_25, "命中 " + _toDisplayString(tpl.count || 0) + " 次", 1),
                                    _createElementVNode("button", {
                                      class: "btn xs",
                                      onClick: $event => (deleteTemplate(tpl))
                                    }, "删除", 8, _hoisted_26)
                                  ]),
                                  _createElementVNode("div", _hoisted_27, [
                                    _cache[20] || (_cache[20] = _createElementVNode("span", { class: "tpl-label" }, "正则", -1)),
                                    _createElementVNode("code", _hoisted_28, _toDisplayString(tpl.regex), 1)
                                  ]),
                                  _createElementVNode("div", _hoisted_29, [
                                    _cache[21] || (_cache[21] = _createElementVNode("span", { class: "tpl-label" }, "示例", -1)),
                                    _createElementVNode("span", _hoisted_30, _toDisplayString(tpl.sample || '—'), 1)
                                  ]),
                                  _createElementVNode("div", _hoisted_31, [
                                    _cache[22] || (_cache[22] = _createElementVNode("span", { class: "tpl-label" }, "答案", -1)),
                                    _createElementVNode("span", _hoisted_32, _toDisplayString(tpl.answer || '—'), 1)
                                  ])
                                ]))
                              }), 128))
                            ]))
                    ])
                  ], 64))
                : _createCommentVNode("", true)
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-dfeae3e0"]]);

export { Config as default };
