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
const _hoisted_19 = { class: "card-h tpl-bar" };
const _hoisted_20 = {
  key: 0,
  class: "muted"
};
const _hoisted_21 = {
  key: 1,
  class: "muted empty"
};
const _hoisted_22 = {
  key: 2,
  class: "tpl-list"
};
const _hoisted_23 = { class: "tpl-header" };
const _hoisted_24 = { class: "tpl-type" };
const _hoisted_25 = {
  key: 0,
  class: "badge b-builtin"
};
const _hoisted_26 = { class: "tpl-count" };
const _hoisted_27 = { class: "tpl-actions" };
const _hoisted_28 = ["onClick"];
const _hoisted_29 = ["onClick"];
const _hoisted_30 = { class: "tpl-row" };
const _hoisted_31 = { class: "tpl-regex" };
const _hoisted_32 = { class: "tpl-row" };
const _hoisted_33 = { class: "tpl-sample" };
const _hoisted_34 = {
  key: 1,
  class: "editor"
};
const _hoisted_35 = { class: "ed-fld" };
const _hoisted_36 = { class: "ed-fld" };
const _hoisted_37 = {
  key: 0,
  class: "ed-error"
};
const _hoisted_38 = { class: "ed-bar" };
const _hoisted_39 = ["disabled"];
const _hoisted_40 = ["disabled", "onClick"];

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
            _cache[8] || (_cache[8] = _createElementVNode("div", { class: "side-title" }, "设置分组", -1)),
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
                  _cache[20] || (_cache[20] = _createElementVNode("h3", { class: "det-title" }, "答题奖励", -1)),
                  _createElementVNode("section", _hoisted_7, [
                    _cache[14] || (_cache[14] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                    _createElementVNode("label", _hoisted_8, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.enable_reward_answer) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.enable_reward_answer]
                      ]),
                      _cache[9] || (_cache[9] = _createElementVNode("span", null, "开启答题奖励", -1))
                    ]),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[10] || (_cache[10] = _createElementVNode("span", { class: "lbl" }, "答题机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.reward_bot_ids) = $event)),
                        class: "inp",
                        placeholder: "@机器人用户名，逗号分隔"
                      }, null, 512), [
                        [_vModelText, cfg.reward_bot_ids]
                      ]),
                      _cache[11] || (_cache[11] = _createElementVNode("span", { class: "help" }, "@机器人用户名，逗号分隔。留空=不限", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _createElementVNode("div", _hoisted_11, [
                        _cache[12] || (_cache[12] = _createElementVNode("span", { class: "lbl" }, "延迟最小(秒)", -1)),
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
                        _cache[13] || (_cache[13] = _createElementVNode("span", { class: "lbl" }, "延迟最大(秒)", -1)),
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
                    _cache[17] || (_cache[17] = _createElementVNode("div", { class: "card-h" }, "智能答题", -1)),
                    _createElementVNode("label", _hoisted_14, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.use_ai_fallback) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.use_ai_fallback]
                      ]),
                      _cache[15] || (_cache[15] = _createElementVNode("span", null, "AI智能答题", -1))
                    ]),
                    _cache[18] || (_cache[18] = _createElementVNode("span", {
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
                      _cache[16] || (_cache[16] = _createElementVNode("span", null, "AI学习模板", -1))
                    ]),
                    _cache[19] || (_cache[19] = _createElementVNode("span", {
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
                    _cache[27] || (_cache[27] = _createElementVNode("h3", { class: "det-title" }, "回答模板", -1)),
                    _createElementVNode("div", _hoisted_18, [
                      _createElementVNode("div", _hoisted_19, [
                        _createElementVNode("span", null, "模板（" + _toDisplayString(templates.value.length) + "）", 1),
                        (templates.value.length > 0)
                          ? (_openBlock(), _createElementBlock("button", {
                              key: 0,
                              class: "btn sm danger",
                              onClick: clearTemplates
                            }, "清空学习模板"))
                          : _createCommentVNode("", true)
                      ]),
                      _cache[26] || (_cache[26] = _createElementVNode("p", { class: "tpl-tip" }, "AI 学会的与内置的模板都在此。正则匹配不上或答案不对时，点「编辑」直接微调正则与脚本，保存后立即生效。", -1)),
                      (tplLoading.value)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_20, "加载中…"))
                        : (templates.value.length === 0)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_21, [...(_cache[21] || (_cache[21] = [
                              _createTextVNode(" 暂无模板", -1),
                              _createElementVNode("br", null, null, -1),
                              _createElementVNode("span", null, "AI 智能答题后自动生成，下次同类题直接命中", -1)
                            ]))]))
                          : (_openBlock(), _createElementBlock("div", _hoisted_22, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(templates.value, (tpl) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: tpl.id,
                                  class: _normalizeClass(["tpl-card", { editing: editingId.value === tpl.id }])
                                }, [
                                  _createElementVNode("div", _hoisted_23, [
                                    _createElementVNode("span", _hoisted_24, _toDisplayString(tpl.type || '未知'), 1),
                                    _createElementVNode("span", {
                                      class: _normalizeClass(["badge", tpl.status === 'verified' ? 'b-ok' : 'b-learn'])
                                    }, _toDisplayString(tpl.status === 'verified' ? '已验证' : '学习中'), 3),
                                    (isBuiltin(tpl))
                                      ? (_openBlock(), _createElementBlock("span", _hoisted_25, "内置"))
                                      : _createCommentVNode("", true),
                                    _createElementVNode("span", _hoisted_26, "命中 " + _toDisplayString(tpl.count || 0), 1),
                                    _createElementVNode("span", _hoisted_27, [
                                      (editingId.value !== tpl.id)
                                        ? (_openBlock(), _createElementBlock("button", {
                                            key: 0,
                                            class: "btn xs",
                                            onClick: $event => (startEdit(tpl))
                                          }, "编辑", 8, _hoisted_28))
                                        : _createCommentVNode("", true),
                                      (!isBuiltin(tpl) && editingId.value !== tpl.id)
                                        ? (_openBlock(), _createElementBlock("button", {
                                            key: 1,
                                            class: "btn xs danger",
                                            onClick: $event => (deleteTemplate(tpl))
                                          }, "删除", 8, _hoisted_29))
                                        : _createCommentVNode("", true)
                                    ])
                                  ]),
                                  (editingId.value !== tpl.id)
                                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                        _createElementVNode("div", _hoisted_30, [
                                          _cache[22] || (_cache[22] = _createElementVNode("span", { class: "tpl-label" }, "正则", -1)),
                                          _createElementVNode("code", _hoisted_31, _toDisplayString(tpl.regex), 1)
                                        ]),
                                        _createElementVNode("div", _hoisted_32, [
                                          _cache[23] || (_cache[23] = _createElementVNode("span", { class: "tpl-label" }, "示例", -1)),
                                          _createElementVNode("span", _hoisted_33, _toDisplayString((tpl.sample || '—').replace(/\n/g, ' ⏎ ')), 1)
                                        ])
                                      ], 64))
                                    : (_openBlock(), _createElementBlock("div", _hoisted_34, [
                                        _createElementVNode("label", _hoisted_35, [
                                          _cache[24] || (_cache[24] = _createElementVNode("span", { class: "ed-lbl" }, "正则表达式", -1)),
                                          _withDirectives(_createElementVNode("input", {
                                            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((editForm.regex) = $event)),
                                            class: "inp mono",
                                            spellcheck: "false"
                                          }, null, 512), [
                                            [_vModelText, editForm.regex]
                                          ])
                                        ]),
                                        _createElementVNode("label", _hoisted_36, [
                                          _cache[25] || (_cache[25] = _createElementVNode("span", { class: "ed-lbl" }, "提取脚本 extract(text) —— 返回字符串答案", -1)),
                                          _withDirectives(_createElementVNode("textarea", {
                                            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((editForm.script_code) = $event)),
                                            class: "inp mono code",
                                            rows: "9",
                                            spellcheck: "false"
                                          }, null, 512), [
                                            [_vModelText, editForm.script_code]
                                          ])
                                        ]),
                                        (editError.value)
                                          ? (_openBlock(), _createElementBlock("div", _hoisted_37, "⚠ " + _toDisplayString(editError.value), 1))
                                          : _createCommentVNode("", true),
                                        _createElementVNode("div", _hoisted_38, [
                                          _createElementVNode("button", {
                                            class: "btn sm",
                                            disabled: editSaving.value,
                                            onClick: cancelEdit
                                          }, "取消", 8, _hoisted_39),
                                          _createElementVNode("button", {
                                            class: "btn sm primary",
                                            disabled: editSaving.value,
                                            onClick: $event => (saveEdit(tpl))
                                          }, _toDisplayString(editSaving.value ? '校验保存中…' : '保存'), 9, _hoisted_40)
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-dd961703"]]);

export { Config as default };
