import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,vModelText:_vModelText,withDirectives:_withDirectives,vModelCheckbox:_vModelCheckbox,createTextVNode:_createTextVNode} = await importShared('vue');


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
const _hoisted_8 = { class: "fld" };
const _hoisted_9 = { class: "fld" };
const _hoisted_10 = { class: "savebar" };
const _hoisted_11 = ["disabled"];
const _hoisted_12 = { class: "card" };
const _hoisted_13 = { class: "row switch" };
const _hoisted_14 = { class: "grid" };
const _hoisted_15 = { class: "fld" };
const _hoisted_16 = { class: "fld" };
const _hoisted_17 = { class: "card" };
const _hoisted_18 = { class: "row switch" };
const _hoisted_19 = { class: "row switch" };
const _hoisted_20 = { class: "savebar" };
const _hoisted_21 = ["disabled"];
const _hoisted_22 = { class: "card" };
const _hoisted_23 = { class: "row switch" };
const _hoisted_24 = { class: "fld" };
const _hoisted_25 = { class: "card" };
const _hoisted_26 = { class: "grid" };
const _hoisted_27 = { class: "fld" };
const _hoisted_28 = { class: "fld" };
const _hoisted_29 = { class: "fld" };
const _hoisted_30 = { class: "fld" };
const _hoisted_31 = { class: "fld" };
const _hoisted_32 = { class: "fld" };
const _hoisted_33 = { class: "fld" };
const _hoisted_34 = { class: "fld" };
const _hoisted_35 = { class: "row switch" };
const _hoisted_36 = { class: "card" };
const _hoisted_37 = { class: "stats-box" };
const _hoisted_38 = { class: "savebar" };
const _hoisted_39 = ["disabled"];
const _hoisted_40 = { class: "card" };
const _hoisted_41 = { class: "card-h tpl-bar" };
const _hoisted_42 = {
  key: 0,
  class: "muted"
};
const _hoisted_43 = {
  key: 1,
  class: "muted empty"
};
const _hoisted_44 = {
  key: 2,
  class: "tpl-list"
};
const _hoisted_45 = { class: "tpl-header" };
const _hoisted_46 = { class: "tpl-type" };
const _hoisted_47 = {
  key: 0,
  class: "badge b-builtin"
};
const _hoisted_48 = { class: "tpl-count" };
const _hoisted_49 = { class: "tpl-actions" };
const _hoisted_50 = ["onClick"];
const _hoisted_51 = ["onClick"];
const _hoisted_52 = { class: "tpl-row" };
const _hoisted_53 = { class: "tpl-regex" };
const _hoisted_54 = { class: "tpl-row" };
const _hoisted_55 = { class: "tpl-sample" };
const _hoisted_56 = {
  key: 1,
  class: "editor"
};
const _hoisted_57 = { class: "ed-fld" };
const _hoisted_58 = { class: "ed-fld" };
const _hoisted_59 = {
  key: 0,
  class: "ed-error"
};
const _hoisted_60 = { class: "ed-bar" };
const _hoisted_61 = ["disabled"];
const _hoisted_62 = ["disabled", "onClick"];

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
  // 全局设置
  target_groups: '-1001326208894',
  bot: '',
  // 自动答题
  enable_reward_answer: false,
  reward_delay_min: 2,
  reward_delay_max: 5,
  use_ai_fallback: true,
  enable_template_learning: true,
  // 自动触发
  trig_enabled: false,
  trig_start_min: 5,
  trig_max_attempts: 10,
  trig_info_every: 5,
  trig_interval: 5,
  trig_active_start: 8,
  trig_active_end: 23,
  trig_info_timeout: 60,
  trig_drop_timeout: 120,
  trig_use_info: true,
  trig_message_template: '第{n}题{x}',
  trig_stats: '',
};

const GROUPS = [
  { key: 'global', label: '全局设置' },
  { key: 'trigger', label: '自动触发' },
  { key: 'reward', label: '自动答题' },
  { key: 'templates', label: '学习模板' },
];

const group = ref('global');
const loading = ref(true);
const saving = ref(false);
const cfg = reactive({ ...DEFAULTS });
const templates = ref([]);
const tplLoading = ref(false);
// 模板编辑态
const editingId = ref(null);
const editSaving = ref(false);
const editError = ref('');
const editForm = reactive({ regex: '', script_code: '' });

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
    await props.host.callApi('/api/templates', {
      method: 'DELETE',
      body: { id: tpl.id },
    });
    props.host.toast.success('已删除');
    loadTemplates();
  } catch (e) {
    props.host.toast.error('删除失败：' + (e.message || e));
  }
}

async function clearTemplates() {
  try {
    await props.host.callApi('/api/templates/clear', { method: 'POST' });
    props.host.toast.success('已清空');
    loadTemplates();
  } catch (e) {
    props.host.toast.error('清空失败：' + (e.message || e));
  }
}

function isBuiltin(tpl) {
  return String(tpl.id || '').startsWith('builtin_')
}

function startEdit(tpl) {
  editingId.value = tpl.id;
  editError.value = '';
  editForm.regex = tpl.regex || '';
  editForm.script_code = tpl.script_code || '';
}

function cancelEdit() {
  editingId.value = null;
  editError.value = '';
}

async function saveEdit(tpl) {
  editSaving.value = true;
  editError.value = '';
  try {
    const res = await props.host.callApi('/api/templates/save', {
      method: 'POST',
      body: { id: tpl.id, regex: editForm.regex, script_code: editForm.script_code },
    });
    if (res && res.ok) {
      props.host.toast.success(res.message || '已保存');
      editingId.value = null;
      loadTemplates();
    } else {
      editError.value = (res && res.message) || '保存失败';
    }
  } catch (e) {
    editError.value = e.message || String(e);
  } finally {
    editSaving.value = false;
  }
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[20] || (_cache[20] = _createElementVNode("div", { class: "side-title" }, "设置分组", -1)),
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
            (group.value === 'global')
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _cache[26] || (_cache[26] = _createElementVNode("h3", { class: "det-title" }, "全局设置", -1)),
                  _createElementVNode("section", _hoisted_7, [
                    _cache[25] || (_cache[25] = _createElementVNode("div", { class: "card-h" }, "目标与机器人", -1)),
                    _createElementVNode("div", _hoisted_8, [
                      _cache[21] || (_cache[21] = _createElementVNode("span", { class: "lbl" }, "目标群组（一行一个ID）", -1)),
                      _withDirectives(_createElementVNode("textarea", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.target_groups) = $event)),
                        class: "inp",
                        rows: "3",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.target_groups]
                      ]),
                      _cache[22] || (_cache[22] = _createElementVNode("span", { class: "help" }, "触发消息发到这些群，一行一个（/info 校准走私聊 bot，不占群）", -1))
                    ]),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[23] || (_cache[23] = _createElementVNode("span", { class: "lbl" }, "天空小秘机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.bot) = $event)),
                        class: "inp",
                        placeholder: "@用户名 或 数字ID，逗号分隔可填多个"
                      }, null, 512), [
                        [_vModelText, cfg.bot]
                      ]),
                      _cache[24] || (_cache[24] = _createElementVNode("span", { class: "help" }, "留空=默认天空小秘。答题过滤与掉落统计都认这个", -1))
                    ])
                  ]),
                  _createElementVNode("div", _hoisted_10, [
                    _createElementVNode("button", {
                      class: "btn primary lg",
                      disabled: saving.value,
                      onClick: save
                    }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_11)
                  ])
                ], 64))
              : (group.value === 'reward')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[36] || (_cache[36] = _createElementVNode("h3", { class: "det-title" }, "自动答题", -1)),
                    _createElementVNode("section", _hoisted_12, [
                      _cache[30] || (_cache[30] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                      _createElementVNode("label", _hoisted_13, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.enable_reward_answer) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.enable_reward_answer]
                        ]),
                        _cache[27] || (_cache[27] = _createElementVNode("span", null, "开启自动答题", -1))
                      ]),
                      _createElementVNode("div", _hoisted_14, [
                        _createElementVNode("div", _hoisted_15, [
                          _cache[28] || (_cache[28] = _createElementVNode("span", { class: "lbl" }, "延迟最小(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.reward_delay_min) = $event)),
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
                        _createElementVNode("div", _hoisted_16, [
                          _cache[29] || (_cache[29] = _createElementVNode("span", { class: "lbl" }, "延迟最大(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.reward_delay_max) = $event)),
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
                    _createElementVNode("section", _hoisted_17, [
                      _cache[33] || (_cache[33] = _createElementVNode("div", { class: "card-h" }, "智能答题", -1)),
                      _createElementVNode("label", _hoisted_18, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.use_ai_fallback) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.use_ai_fallback]
                        ]),
                        _cache[31] || (_cache[31] = _createElementVNode("span", null, "AI智能答题", -1))
                      ]),
                      _cache[34] || (_cache[34] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "未知题型时使用AI分析并回答", -1)),
                      _createElementVNode("label", _hoisted_19, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.enable_template_learning) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.enable_template_learning]
                        ]),
                        _cache[32] || (_cache[32] = _createElementVNode("span", null, "AI学习模板", -1))
                      ]),
                      _cache[35] || (_cache[35] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "AI答完题后自动提取模板，下次同类题直接脚本答", -1))
                    ]),
                    _createElementVNode("div", _hoisted_20, [
                      _createElementVNode("button", {
                        class: "btn primary lg",
                        disabled: saving.value,
                        onClick: save
                      }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_21)
                    ])
                  ], 64))
                : (group.value === 'trigger')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _cache[62] || (_cache[62] = _createElementVNode("h3", { class: "det-title" }, "自动触发", -1)),
                      _createElementVNode("section", _hoisted_22, [
                        _cache[40] || (_cache[40] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                        _createElementVNode("label", _hoisted_23, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((cfg.trig_enabled) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.trig_enabled]
                          ]),
                          _cache[37] || (_cache[37] = _createElementVNode("span", null, "启用自动触发", -1))
                        ]),
                        _cache[41] || (_cache[41] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "开启时段内定时循环：/info 校准 → 发「第n题x」触发掉落 → 定时触发下一题", -1)),
                        _cache[42] || (_cache[42] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "每小时掉落目标自动从 /info 读取（私聊 bot，读「当前时段剩余掉落」），无需手动设置", -1)),
                        _createElementVNode("div", _hoisted_24, [
                          _cache[38] || (_cache[38] = _createElementVNode("span", { class: "lbl" }, "触发消息模板", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cfg.trig_message_template) = $event)),
                            class: "inp",
                            placeholder: "第{n}题{x}"
                          }, null, 512), [
                            [_vModelText, cfg.trig_message_template]
                          ]),
                          _cache[39] || (_cache[39] = _createElementVNode("span", { class: "help" }, "{n}=本小时题号 {x}=本题尝试次数", -1))
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_25, [
                        _cache[59] || (_cache[59] = _createElementVNode("div", { class: "card-h" }, "循环节奏", -1)),
                        _createElementVNode("div", _hoisted_26, [
                          _createElementVNode("div", _hoisted_27, [
                            _cache[43] || (_cache[43] = _createElementVNode("span", { class: "lbl" }, "触发窗口起始分", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((cfg.trig_start_min) = $event)),
                              class: "inp",
                              type: "number",
                              min: "0",
                              max: "30"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_start_min,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[44] || (_cache[44] = _createElementVNode("span", { class: "help" }, "每小时第几分开始触发", -1))
                          ]),
                          _createElementVNode("div", _hoisted_28, [
                            _cache[45] || (_cache[45] = _createElementVNode("span", { class: "lbl" }, "单题最大尝试次数", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cfg.trig_max_attempts) = $event)),
                              class: "inp",
                              type: "number",
                              min: "1",
                              max: "20"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_max_attempts,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[46] || (_cache[46] = _createElementVNode("span", { class: "help" }, "超过就放弃该题", -1))
                          ]),
                          _createElementVNode("div", _hoisted_29, [
                            _cache[47] || (_cache[47] = _createElementVNode("span", { class: "lbl" }, "每几次未掉落查/info", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((cfg.trig_info_every) = $event)),
                              class: "inp",
                              type: "number",
                              min: "0",
                              max: "10"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_info_every,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[48] || (_cache[48] = _createElementVNode("span", { class: "help" }, "0=不检查", -1))
                          ]),
                          _createElementVNode("div", _hoisted_30, [
                            _cache[49] || (_cache[49] = _createElementVNode("span", { class: "lbl" }, "触发间隔(分钟)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((cfg.trig_interval) = $event)),
                              class: "inp",
                              type: "number",
                              min: "1",
                              max: "60"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_interval,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[50] || (_cache[50] = _createElementVNode("span", { class: "help" }, "一次触发完成后定时这么久再触发下一题", -1))
                          ]),
                          _createElementVNode("div", _hoisted_31, [
                            _cache[51] || (_cache[51] = _createElementVNode("span", { class: "lbl" }, "开启时段·开始(点)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((cfg.trig_active_start) = $event)),
                              class: "inp",
                              type: "number",
                              min: "0",
                              max: "23"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_active_start,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[52] || (_cache[52] = _createElementVNode("span", { class: "help" }, "每天这个点起才触发", -1))
                          ]),
                          _createElementVNode("div", _hoisted_32, [
                            _cache[53] || (_cache[53] = _createElementVNode("span", { class: "lbl" }, "开启时段·结束(点)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((cfg.trig_active_end) = $event)),
                              class: "inp",
                              type: "number",
                              min: "0",
                              max: "23"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_active_end,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[54] || (_cache[54] = _createElementVNode("span", { class: "help" }, "到这个点停止；开始>结束=跨午夜", -1))
                          ]),
                          _createElementVNode("div", _hoisted_33, [
                            _cache[55] || (_cache[55] = _createElementVNode("span", { class: "lbl" }, "/info等待超时(秒)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((cfg.trig_info_timeout) = $event)),
                              class: "inp",
                              type: "number",
                              min: "10",
                              max: "300"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_info_timeout,
                                void 0,
                                { number: true }
                              ]
                            ])
                          ]),
                          _createElementVNode("div", _hoisted_34, [
                            _cache[56] || (_cache[56] = _createElementVNode("span", { class: "lbl" }, "等掉落超时(秒)", -1)),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((cfg.trig_drop_timeout) = $event)),
                              class: "inp",
                              type: "number",
                              min: "30",
                              max: "600"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.trig_drop_timeout,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[57] || (_cache[57] = _createElementVNode("span", { class: "help" }, "超时视为本次失败", -1))
                          ])
                        ]),
                        _createElementVNode("label", _hoisted_35, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((cfg.trig_use_info) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.trig_use_info]
                          ]),
                          _cache[58] || (_cache[58] = _createElementVNode("span", null, "发送/info校准", -1))
                        ]),
                        _cache[60] || (_cache[60] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "每小时私聊 bot 发 /info 校准；连续失败时也用它检查", -1))
                      ]),
                      _createElementVNode("section", _hoisted_36, [
                        _cache[61] || (_cache[61] = _createElementVNode("div", { class: "card-h" }, "触发统计", -1)),
                        _createElementVNode("div", _hoisted_37, _toDisplayString(cfg.trig_stats || '暂无统计（启用后自动刷新）'), 1)
                      ]),
                      _createElementVNode("div", _hoisted_38, [
                        _createElementVNode("button", {
                          class: "btn primary lg",
                          disabled: saving.value,
                          onClick: save
                        }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_39)
                      ])
                    ], 64))
                  : (group.value === 'templates')
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                        _cache[69] || (_cache[69] = _createElementVNode("h3", { class: "det-title" }, "回答模板", -1)),
                        _createElementVNode("div", _hoisted_40, [
                          _createElementVNode("div", _hoisted_41, [
                            _createElementVNode("span", null, "模板（" + _toDisplayString(templates.value.length) + "）", 1),
                            (templates.value.length > 0)
                              ? (_openBlock(), _createElementBlock("button", {
                                  key: 0,
                                  class: "btn sm danger",
                                  onClick: clearTemplates
                                }, "清空学习模板"))
                              : _createCommentVNode("", true)
                          ]),
                          _cache[68] || (_cache[68] = _createElementVNode("p", { class: "tpl-tip" }, "AI 学会的与内置的模板都在此。正则匹配不上或答案不对时，点「编辑」直接微调正则与脚本，保存后立即生效。", -1)),
                          (tplLoading.value)
                            ? (_openBlock(), _createElementBlock("div", _hoisted_42, "加载中…"))
                            : (templates.value.length === 0)
                              ? (_openBlock(), _createElementBlock("div", _hoisted_43, [...(_cache[63] || (_cache[63] = [
                                  _createTextVNode(" 暂无模板", -1),
                                  _createElementVNode("br", null, null, -1),
                                  _createElementVNode("span", null, "AI 智能答题后自动生成，下次同类题直接命中", -1)
                                ]))]))
                              : (_openBlock(), _createElementBlock("div", _hoisted_44, [
                                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(templates.value, (tpl) => {
                                    return (_openBlock(), _createElementBlock("div", {
                                      key: tpl.id,
                                      class: _normalizeClass(["tpl-card", { editing: editingId.value === tpl.id }])
                                    }, [
                                      _createElementVNode("div", _hoisted_45, [
                                        _createElementVNode("span", _hoisted_46, _toDisplayString(tpl.type || '未知'), 1),
                                        _createElementVNode("span", {
                                          class: _normalizeClass(["badge", tpl.status === 'verified' ? 'b-ok' : 'b-learn'])
                                        }, _toDisplayString(tpl.status === 'verified' ? '已验证' : '学习中'), 3),
                                        (isBuiltin(tpl))
                                          ? (_openBlock(), _createElementBlock("span", _hoisted_47, "内置"))
                                          : _createCommentVNode("", true),
                                        _createElementVNode("span", _hoisted_48, "命中 " + _toDisplayString(tpl.count || 0), 1),
                                        _createElementVNode("span", _hoisted_49, [
                                          (editingId.value !== tpl.id)
                                            ? (_openBlock(), _createElementBlock("button", {
                                                key: 0,
                                                class: "btn xs",
                                                onClick: $event => (startEdit(tpl))
                                              }, "编辑", 8, _hoisted_50))
                                            : _createCommentVNode("", true),
                                          (!isBuiltin(tpl) && editingId.value !== tpl.id)
                                            ? (_openBlock(), _createElementBlock("button", {
                                                key: 1,
                                                class: "btn xs danger",
                                                onClick: $event => (deleteTemplate(tpl))
                                              }, "删除", 8, _hoisted_51))
                                            : _createCommentVNode("", true)
                                        ])
                                      ]),
                                      (editingId.value !== tpl.id)
                                        ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                            _createElementVNode("div", _hoisted_52, [
                                              _cache[64] || (_cache[64] = _createElementVNode("span", { class: "tpl-label" }, "正则", -1)),
                                              _createElementVNode("code", _hoisted_53, _toDisplayString(tpl.regex), 1)
                                            ]),
                                            _createElementVNode("div", _hoisted_54, [
                                              _cache[65] || (_cache[65] = _createElementVNode("span", { class: "tpl-label" }, "示例", -1)),
                                              _createElementVNode("span", _hoisted_55, _toDisplayString((tpl.sample || '—').replace(/\n/g, ' ⏎ ')), 1)
                                            ])
                                          ], 64))
                                        : (_openBlock(), _createElementBlock("div", _hoisted_56, [
                                            _createElementVNode("label", _hoisted_57, [
                                              _cache[66] || (_cache[66] = _createElementVNode("span", { class: "ed-lbl" }, "正则表达式", -1)),
                                              _withDirectives(_createElementVNode("input", {
                                                "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((editForm.regex) = $event)),
                                                class: "inp mono",
                                                spellcheck: "false"
                                              }, null, 512), [
                                                [_vModelText, editForm.regex]
                                              ])
                                            ]),
                                            _createElementVNode("label", _hoisted_58, [
                                              _cache[67] || (_cache[67] = _createElementVNode("span", { class: "ed-lbl" }, "提取脚本 extract(text) —— 返回字符串答案", -1)),
                                              _withDirectives(_createElementVNode("textarea", {
                                                "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((editForm.script_code) = $event)),
                                                class: "inp mono code",
                                                rows: "9",
                                                spellcheck: "false"
                                              }, null, 512), [
                                                [_vModelText, editForm.script_code]
                                              ])
                                            ]),
                                            (editError.value)
                                              ? (_openBlock(), _createElementBlock("div", _hoisted_59, "⚠ " + _toDisplayString(editError.value), 1))
                                              : _createCommentVNode("", true),
                                            _createElementVNode("div", _hoisted_60, [
                                              _createElementVNode("button", {
                                                class: "btn sm",
                                                disabled: editSaving.value,
                                                onClick: cancelEdit
                                              }, "取消", 8, _hoisted_61),
                                              _createElementVNode("button", {
                                                class: "btn sm primary",
                                                disabled: editSaving.value,
                                                onClick: $event => (saveEdit(tpl))
                                              }, _toDisplayString(editSaving.value ? '校验保存中…' : '保存'), 9, _hoisted_62)
                                            ])
                                          ]))
                                    ], 2))
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-5b355b5c"]]);

export { Config as default };
