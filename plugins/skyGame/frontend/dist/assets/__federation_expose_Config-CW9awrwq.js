import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,vModelText:_vModelText,withDirectives:_withDirectives,vModelCheckbox:_vModelCheckbox,vModelSelect:_vModelSelect} = await importShared('vue');


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
const _hoisted_11 = { class: "card" };
const _hoisted_12 = { class: "fld" };
const _hoisted_13 = { class: "fld" };
const _hoisted_14 = { class: "card" };
const _hoisted_15 = { class: "row switch" };
const _hoisted_16 = { class: "grid" };
const _hoisted_17 = { class: "fld" };
const _hoisted_18 = { class: "fld" };
const _hoisted_19 = { class: "fld" };
const _hoisted_20 = { class: "fld" };
const _hoisted_21 = { class: "fld" };
const _hoisted_22 = { class: "fld" };
const _hoisted_23 = { class: "row switch" };
const _hoisted_24 = {
  class: "row",
  style: {"justify-content":"flex-end"}
};
const _hoisted_25 = ["disabled"];
const _hoisted_26 = { class: "savebar" };
const _hoisted_27 = ["disabled"];
const _hoisted_28 = { class: "card" };
const _hoisted_29 = { class: "row switch" };
const _hoisted_30 = { class: "grid" };
const _hoisted_31 = { class: "fld" };
const _hoisted_32 = { class: "fld" };
const _hoisted_33 = { class: "row switch" };
const _hoisted_34 = { class: "card" };
const _hoisted_35 = { class: "grid" };
const _hoisted_36 = { class: "fld" };
const _hoisted_37 = ["value"];
const _hoisted_38 = { class: "fld" };
const _hoisted_39 = { class: "card" };
const _hoisted_40 = { class: "row switch" };
const _hoisted_41 = { class: "row switch" };
const _hoisted_42 = { class: "row switch" };
const _hoisted_43 = { class: "savebar" };
const _hoisted_44 = ["disabled"];
const _hoisted_45 = { class: "card" };
const _hoisted_46 = { class: "row switch" };
const _hoisted_47 = { class: "fld" };
const _hoisted_48 = { class: "card" };
const _hoisted_49 = { class: "grid" };
const _hoisted_50 = { class: "fld" };
const _hoisted_51 = { class: "row switch" };
const _hoisted_52 = { class: "lbl" };
const _hoisted_53 = { class: "fld" };
const _hoisted_54 = { class: "row switch" };
const _hoisted_55 = { class: "lbl" };
const _hoisted_56 = { class: "card" };
const _hoisted_57 = { class: "fld" };
const _hoisted_58 = { class: "lbl" };
const _hoisted_59 = { class: "card" };
const _hoisted_60 = { class: "row switch" };
const _hoisted_61 = { class: "row switch" };
const _hoisted_62 = { class: "row switch" };
const _hoisted_63 = { class: "row switch" };
const _hoisted_64 = { class: "savebar" };
const _hoisted_65 = ["disabled"];

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
  horse_feed_type: 'weed',
  horse_feed_threshold: 60,
  horse_auto_walk: true,
  horse_auto_official_race: false,
  horse_auto_revive: false,
  horse_notify: true,
  // 炸金花
  zjh_enabled: true,
  zjh_poll_interval: 2,
  zjh_peeked_threshold: 50,
  zjh_open_enabled: false,
  zjh_open_max_win_rate: 50,
  zjh_raise_enabled: false,
  zjh_raise_min_win_rate: 75,
  zjh_notify_join: true,
  zjh_notify_hand: true,
  zjh_notify_fold_confirm: false,
  zjh_notify_error: true,
};

// 草料选项（与后端 config_schema 一致）
const FEED_TYPES = [
  { value: 'weed', label: '杂草（100银元 +12饱腹）' },
  { value: 'fine', label: '精草（300银元 +30饱腹）' },
  { value: 'divine', label: '仙草（1000银元 +60饱腹）' },
];

// 左侧分组：按游戏归类
const GROUPS = [
  { key: 'global', label: '全局设置', icon: '⚙️' },
  { key: 'horse', label: '养马', icon: '🐴' },
  { key: 'zjh', label: '炸金花', icon: '🃏' },
];

const group = ref('global');
const loading = ref(true);
const saving = ref(false);
const renewing = ref(false);
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

// 手动触发一次 Cookie 续期（后端 hdsky_auth，跳过防抖）
async function renewNow() {
  renewing.value = true;
  try {
    const r = await props.host.callApi('/renew', { method: 'POST' });
    if (r && r.ok) props.host.toast.success(r.message || '续期成功');
    else props.host.toast.error((r && r.message) || '续期失败');
  } catch (e) {
    props.host.toast.error('续期请求失败：' + (e.message || e));
  } finally {
    renewing.value = false;
  }
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "加载配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("aside", _hoisted_4, [
            _cache[30] || (_cache[30] = _createElementVNode("div", { class: "side-title" }, "游戏", -1)),
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
                  _cache[52] || (_cache[52] = _createElementVNode("h3", { class: "det-title" }, "全局设置", -1)),
                  _createElementVNode("section", _hoisted_8, [
                    _cache[35] || (_cache[35] = _createElementVNode("div", { class: "card-h" }, "目标与机器人", -1)),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[31] || (_cache[31] = _createElementVNode("span", { class: "lbl" }, "目标群组（一行一个ID）", -1)),
                      _withDirectives(_createElementVNode("textarea", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.target_groups) = $event)),
                        class: "inp",
                        rows: "3",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.target_groups]
                      ]),
                      _cache[32] || (_cache[32] = _createElementVNode("span", { class: "help" }, "游戏消息发到的群，一行一个。", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _cache[33] || (_cache[33] = _createElementVNode("span", { class: "lbl" }, "天空小秘机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.bot) = $event)),
                        class: "inp",
                        placeholder: "@用户名 或 数字ID，逗号分隔可填多个"
                      }, null, 512), [
                        [_vModelText, cfg.bot]
                      ]),
                      _cache[34] || (_cache[34] = _createElementVNode("span", { class: "help" }, "留空=默认天空小秘。", -1))
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_11, [
                    _cache[39] || (_cache[39] = _createElementVNode("div", { class: "card-h" }, "HDSky 门户（炸金花/养马共用）", -1)),
                    _createElementVNode("div", _hoisted_12, [
                      _cache[36] || (_cache[36] = _createElementVNode("span", { class: "lbl" }, "Cookie 文件路径", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.hdsky_cookie_file) = $event)),
                        class: "inp",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.hdsky_cookie_file]
                      ]),
                      _cache[37] || (_cache[37] = _createElementVNode("span", { class: "help" }, "容器内路径（宿主 appdata/awbotnest/data 目录），过期后由下方自动续期覆盖", -1))
                    ]),
                    _createElementVNode("div", _hoisted_13, [
                      _cache[38] || (_cache[38] = _createElementVNode("span", { class: "lbl" }, "门户地址", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((cfg.hdsky_base_url) = $event)),
                        class: "inp",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.hdsky_base_url]
                      ])
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_14, [
                    _cache[50] || (_cache[50] = _createElementVNode("div", { class: "card-h" }, "Cookie 自动续期", -1)),
                    _createElementVNode("label", _hoisted_15, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.auth_auto_renew) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.auth_auto_renew]
                      ]),
                      _cache[40] || (_cache[40] = _createElementVNode("span", null, "门户会话过期自动续期", -1))
                    ]),
                    _cache[51] || (_cache[51] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, " 经 MoviePilot CookieCloud 拉浏览器 cookie 快照 → 读 HDSky 站内信验证码 → 自动登录写回 Cookie 文件 ", -1)),
                    _createElementVNode("div", _hoisted_16, [
                      _createElementVNode("div", _hoisted_17, [
                        _cache[41] || (_cache[41] = _createElementVNode("span", { class: "lbl" }, "CookieCloud 地址", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.cc_server) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_server]
                        ]),
                        _cache[42] || (_cache[42] = _createElementVNode("span", { class: "help" }, "MoviePilot 内置，http://<主机>:3000", -1))
                      ]),
                      _createElementVNode("div", _hoisted_18, [
                        _cache[43] || (_cache[43] = _createElementVNode("span", { class: "lbl" }, "HDSky UID", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.hdsky_uid) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.hdsky_uid]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_19, [
                        _cache[44] || (_cache[44] = _createElementVNode("span", { class: "lbl" }, "CookieCloud UUID（Key）", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((cfg.cc_uuid) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_uuid]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_20, [
                        _cache[45] || (_cache[45] = _createElementVNode("span", { class: "lbl" }, "CookieCloud 加密密钥", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cfg.cc_password) = $event)),
                          class: "inp",
                          type: "password",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_password]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_21, [
                        _cache[46] || (_cache[46] = _createElementVNode("span", { class: "lbl" }, "会话体检间隔(秒)", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((cfg.auth_check_interval) = $event)),
                          class: "inp",
                          type: "number",
                          min: "600",
                          max: "7200",
                          step: "300"
                        }, null, 512), [
                          [
                            _vModelText,
                            cfg.auth_check_interval,
                            void 0,
                            { number: true }
                          ]
                        ]),
                        _cache[47] || (_cache[47] = _createElementVNode("span", { class: "help" }, "定期探测+主动续期；轮询遇到 401 也会即时触发", -1))
                      ]),
                      _createElementVNode("div", _hoisted_22, [
                        _cache[49] || (_cache[49] = _createElementVNode("span", { class: "lbl" }, "续期通知", -1)),
                        _createElementVNode("label", _hoisted_23, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cfg.auth_notify) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.auth_notify]
                          ]),
                          _cache[48] || (_cache[48] = _createElementVNode("span", null, "结果推送", -1))
                        ])
                      ])
                    ]),
                    _createElementVNode("div", _hoisted_24, [
                      _createElementVNode("button", {
                        class: "btn",
                        disabled: renewing.value,
                        onClick: renewNow
                      }, _toDisplayString(renewing.value ? '续期中…' : '立即续期'), 9, _hoisted_25)
                    ])
                  ]),
                  _createElementVNode("div", _hoisted_26, [
                    _createElementVNode("button", {
                      class: "btn primary lg",
                      disabled: saving.value,
                      onClick: save
                    }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_27)
                  ])
                ], 64))
              : (group.value === 'horse')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[71] || (_cache[71] = _createElementVNode("h3", { class: "det-title" }, "养马", -1)),
                    _createElementVNode("section", _hoisted_28, [
                      _cache[58] || (_cache[58] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                      _createElementVNode("label", _hoisted_29, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((cfg.horse_enabled) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_enabled]
                        ]),
                        _cache[53] || (_cache[53] = _createElementVNode("span", null, "启用养马自动化", -1))
                      ]),
                      _cache[59] || (_cache[59] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "每轮轮询最多执行一个养护动作：喂食 → 遛马 → 官方赛", -1)),
                      _createElementVNode("div", _hoisted_30, [
                        _createElementVNode("div", _hoisted_31, [
                          _cache[54] || (_cache[54] = _createElementVNode("span", { class: "lbl" }, "养护轮询间隔(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((cfg.horse_poll_interval) = $event)),
                            class: "inp",
                            type: "number",
                            min: "30",
                            max: "600",
                            step: "10"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.horse_poll_interval,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[55] || (_cache[55] = _createElementVNode("span", { class: "help" }, "节奏拟人，不用太频繁", -1))
                        ]),
                        _createElementVNode("div", _hoisted_32, [
                          _cache[57] || (_cache[57] = _createElementVNode("span", { class: "lbl" }, "养马通知", -1)),
                          _createElementVNode("label", _hoisted_33, [
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((cfg.horse_notify) = $event)),
                              type: "checkbox"
                            }, null, 512), [
                              [_vModelCheckbox, cfg.horse_notify]
                            ]),
                            _cache[56] || (_cache[56] = _createElementVNode("span", null, "操作结果推送", -1))
                          ])
                        ])
                      ])
                    ]),
                    _createElementVNode("section", _hoisted_34, [
                      _cache[63] || (_cache[63] = _createElementVNode("div", { class: "card-h" }, "自动喂食", -1)),
                      _createElementVNode("div", _hoisted_35, [
                        _createElementVNode("div", _hoisted_36, [
                          _cache[60] || (_cache[60] = _createElementVNode("span", { class: "lbl" }, "草料", -1)),
                          _withDirectives(_createElementVNode("select", {
                            "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((cfg.horse_feed_type) = $event)),
                            class: "inp"
                          }, [
                            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(FEED_TYPES, (f) => {
                              return _createElementVNode("option", {
                                key: f.value,
                                value: f.value
                              }, _toDisplayString(f.label), 9, _hoisted_37)
                            }), 64))
                          ], 512), [
                            [_vModelSelect, cfg.horse_feed_type]
                          ])
                        ]),
                        _createElementVNode("div", _hoisted_38, [
                          _cache[61] || (_cache[61] = _createElementVNode("span", { class: "lbl" }, "饱腹度阈值", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((cfg.horse_feed_threshold) = $event)),
                            class: "inp",
                            type: "number",
                            min: "0",
                            max: "100",
                            step: "5"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.horse_feed_threshold,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[62] || (_cache[62] = _createElementVNode("span", { class: "help" }, "低于此值且今日次数未用完时喂（每日上限 5 次）", -1))
                        ])
                      ])
                    ]),
                    _createElementVNode("section", _hoisted_39, [
                      _cache[67] || (_cache[67] = _createElementVNode("div", { class: "card-h" }, "自动行为", -1)),
                      _createElementVNode("label", _hoisted_40, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((cfg.horse_auto_walk) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_walk]
                        ]),
                        _cache[64] || (_cache[64] = _createElementVNode("span", null, "自动遛马", -1))
                      ]),
                      _cache[68] || (_cache[68] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "用完每日遛马额度（4 次），赚银元+经验，体力耗尽自动停", -1)),
                      _createElementVNode("label", _hoisted_41, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((cfg.horse_auto_official_race) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_official_race]
                        ]),
                        _cache[65] || (_cache[65] = _createElementVNode("span", null, "自动报名官方赛", -1))
                      ]),
                      _cache[69] || (_cache[69] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "每日官方赛开放报名时免费参加", -1)),
                      _createElementVNode("label", _hoisted_42, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((cfg.horse_auto_revive) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_revive]
                        ]),
                        _cache[66] || (_cache[66] = _createElementVNode("span", null, "死亡自动复活", -1))
                      ]),
                      _cache[70] || (_cache[70] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "马匹死亡且余额足够时复活（约 30 万银元，默认关）", -1))
                    ]),
                    _createElementVNode("div", _hoisted_43, [
                      _createElementVNode("button", {
                        class: "btn primary lg",
                        disabled: saving.value,
                        onClick: save
                      }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_44)
                    ])
                  ], 64))
                : (group.value === 'zjh')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _cache[90] || (_cache[90] = _createElementVNode("h3", { class: "det-title" }, "炸金花", -1)),
                      _createElementVNode("section", _hoisted_45, [
                        _cache[75] || (_cache[75] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                        _createElementVNode("label", _hoisted_46, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((cfg.zjh_enabled) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_enabled]
                          ]),
                          _cache[72] || (_cache[72] = _createElementVNode("span", null, "启用自动参与", -1))
                        ]),
                        _cache[76] || (_cache[76] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "轮询牌局：自动加入 → 首轮盲跟 → 看牌后按期望收益决策", -1)),
                        _createElementVNode("div", _hoisted_47, [
                          _cache[73] || (_cache[73] = _createElementVNode("span", { class: "lbl" }, "轮询间隔(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((cfg.zjh_poll_interval) = $event)),
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
                          ]),
                          _cache[74] || (_cache[74] = _createElementVNode("span", { class: "help" }, "Cookie 与门户地址见「全局设置」", -1))
                        ])
                      ]),
                      _cache[91] || (_cache[91] = _createElementVNode("section", { class: "card" }, [
                        _createElementVNode("div", { class: "card-h" }, "决策策略"),
                        _createElementVNode("span", { class: "help" }, " 完全按期望收益（EV）决策，不再按牌型勾选：胜率 ×（底池 + 跟注成本）− 跟注成本 ≥ 0 即跟注，否则弃牌。 胜率随剩余对手数衰减；已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛，再做条件胜率。 ")
                      ], -1)),
                      _createElementVNode("section", _hoisted_48, [
                        _cache[81] || (_cache[81] = _createElementVNode("div", { class: "card-h" }, "进攻策略（可选）", -1)),
                        _cache[82] || (_cache[82] = _createElementVNode("span", { class: "help" }, " 所有阈值均基于最终实际胜率：蒙牌对手按单挑胜率相乘；已看牌对手按其实际下注反推的最低牌力条件化后相乘。 开牌和追加只会在门户 actions 明确允许时发送；默认关闭，建议先观察日志中的服务端成本。 ", -1)),
                        _createElementVNode("div", _hoisted_49, [
                          _createElementVNode("div", _hoisted_50, [
                            _createElementVNode("label", _hoisted_51, [
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((cfg.zjh_open_enabled) = $event)),
                                type: "checkbox"
                              }, null, 512), [
                                [_vModelCheckbox, cfg.zjh_open_enabled]
                              ]),
                              _cache[77] || (_cache[77] = _createElementVNode("span", null, "启用低胜率主动开牌", -1))
                            ]),
                            _cache[78] || (_cache[78] = _createElementVNode("span", { class: "help" }, "正 EV 且最终实际胜率低于阈值时，若允许 open 则发起比牌。", -1)),
                            _createElementVNode("span", _hoisted_52, "最高实际胜率：" + _toDisplayString(cfg.zjh_open_max_win_rate) + "%", 1),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((cfg.zjh_open_max_win_rate) = $event)),
                              type: "range",
                              min: "0",
                              max: "95",
                              step: "5"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.zjh_open_max_win_rate,
                                void 0,
                                { number: true }
                              ]
                            ])
                          ]),
                          _createElementVNode("div", _hoisted_53, [
                            _createElementVNode("label", _hoisted_54, [
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((cfg.zjh_raise_enabled) = $event)),
                                type: "checkbox"
                              }, null, 512), [
                                [_vModelCheckbox, cfg.zjh_raise_enabled]
                              ]),
                              _cache[79] || (_cache[79] = _createElementVNode("span", null, "启用高胜率主动追加", -1))
                            ]),
                            _cache[80] || (_cache[80] = _createElementVNode("span", { class: "help" }, "正 EV 且最终实际胜率达到阈值时，若允许 raise 则追加。", -1)),
                            _createElementVNode("span", _hoisted_55, "最低实际胜率：" + _toDisplayString(cfg.zjh_raise_min_win_rate) + "%", 1),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((cfg.zjh_raise_min_win_rate) = $event)),
                              type: "range",
                              min: "5",
                              max: "100",
                              step: "5"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.zjh_raise_min_win_rate,
                                void 0,
                                { number: true }
                              ]
                            ])
                          ])
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_56, [
                        _cache[84] || (_cache[84] = _createElementVNode("div", { class: "card-h" }, "看牌对手推断", -1)),
                        _createElementVNode("div", _hoisted_57, [
                          _createElementVNode("span", _hoisted_58, "未观测到下注时的牌力阈值：" + _toDisplayString(cfg.zjh_peeked_threshold) + "%", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((cfg.zjh_peeked_threshold) = $event)),
                            type: "range",
                            min: "0",
                            max: "95",
                            step: "5"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.zjh_peeked_threshold,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[83] || (_cache[83] = _createElementVNode("span", { class: "help" }, " 系统优先按对手看牌后实际下注时的底池和成本反推门槛；轮询漏掉该动作时才使用此回退值。 ", -1))
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_59, [
                        _cache[89] || (_cache[89] = _createElementVNode("div", { class: "card-h" }, "通知", -1)),
                        _createElementVNode("label", _hoisted_60, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((cfg.zjh_notify_join) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_join]
                          ]),
                          _cache[85] || (_cache[85] = _createElementVNode("span", null, "加入牌局", -1))
                        ]),
                        _createElementVNode("label", _hoisted_61, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((cfg.zjh_notify_hand) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_hand]
                          ]),
                          _cache[86] || (_cache[86] = _createElementVNode("span", null, "手牌决策（跟注/弃牌）", -1))
                        ]),
                        _createElementVNode("label", _hoisted_62, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((cfg.zjh_notify_fold_confirm) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_fold_confirm]
                          ]),
                          _cache[87] || (_cache[87] = _createElementVNode("span", null, "双击确认弃牌", -1))
                        ]),
                        _createElementVNode("label", _hoisted_63, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((cfg.zjh_notify_error) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_error]
                          ]),
                          _cache[88] || (_cache[88] = _createElementVNode("span", null, "异常", -1))
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_64, [
                        _createElementVNode("button", {
                          class: "btn primary lg",
                          disabled: saving.value,
                          onClick: save
                        }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_65)
                      ])
                    ], 64))
                  : _createCommentVNode("", true)
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-9e8548af"]]);

export { Config as default };
