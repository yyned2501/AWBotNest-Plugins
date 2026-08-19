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
const _hoisted_16 = { class: "fld" };
const _hoisted_17 = { class: "fld" };
const _hoisted_18 = { class: "card" };
const _hoisted_19 = { class: "row switch" };
const _hoisted_20 = { class: "fld" };
const _hoisted_21 = { class: "card" };
const _hoisted_22 = { class: "row switch" };
const _hoisted_23 = { class: "grid" };
const _hoisted_24 = { class: "fld" };
const _hoisted_25 = { class: "fld" };
const _hoisted_26 = { class: "fld" };
const _hoisted_27 = { class: "fld" };
const _hoisted_28 = { class: "fld" };
const _hoisted_29 = { class: "fld" };
const _hoisted_30 = { class: "row switch" };
const _hoisted_31 = {
  class: "row",
  style: {"justify-content":"flex-end"}
};
const _hoisted_32 = ["disabled"];
const _hoisted_33 = { class: "savebar" };
const _hoisted_34 = ["disabled"];
const _hoisted_35 = { class: "card" };
const _hoisted_36 = { class: "row switch" };
const _hoisted_37 = { class: "grid" };
const _hoisted_38 = { class: "fld" };
const _hoisted_39 = { class: "fld" };
const _hoisted_40 = { class: "row switch" };
const _hoisted_41 = { class: "fld" };
const _hoisted_42 = { class: "row switch" };
const _hoisted_43 = { class: "card" };
const _hoisted_44 = { class: "grid" };
const _hoisted_45 = { class: "fld" };
const _hoisted_46 = ["value"];
const _hoisted_47 = { class: "fld" };
const _hoisted_48 = { class: "card" };
const _hoisted_49 = { class: "row switch" };
const _hoisted_50 = { class: "row switch" };
const _hoisted_51 = { class: "fld" };
const _hoisted_52 = { class: "row switch" };
const _hoisted_53 = { class: "row switch" };
const _hoisted_54 = { class: "savebar" };
const _hoisted_55 = ["disabled"];
const _hoisted_56 = { class: "card" };
const _hoisted_57 = { class: "row switch" };
const _hoisted_58 = { class: "fld" };
const _hoisted_59 = { class: "card" };
const _hoisted_60 = { class: "grid" };
const _hoisted_61 = { class: "fld" };
const _hoisted_62 = { class: "row switch" };
const _hoisted_63 = { class: "lbl" };
const _hoisted_64 = { class: "lbl" };
const _hoisted_65 = { class: "fld" };
const _hoisted_66 = { class: "row switch" };
const _hoisted_67 = { class: "lbl" };
const _hoisted_68 = { class: "lbl" };
const _hoisted_69 = { class: "row switch" };
const _hoisted_70 = { class: "card" };
const _hoisted_71 = { class: "fld" };
const _hoisted_72 = { class: "lbl" };
const _hoisted_73 = { class: "card" };
const _hoisted_74 = { class: "fld" };
const _hoisted_75 = { class: "lbl" };
const _hoisted_76 = { class: "fld" };
const _hoisted_77 = { class: "lbl" };
const _hoisted_78 = { class: "card" };
const _hoisted_79 = { class: "fld" };
const _hoisted_80 = { class: "lbl" };
const _hoisted_81 = { class: "fld" };
const _hoisted_82 = { class: "lbl" };
const _hoisted_83 = { class: "row switch" };
const _hoisted_84 = { class: "card" };
const _hoisted_85 = { class: "row switch" };
const _hoisted_86 = { class: "row switch" };
const _hoisted_87 = { class: "row switch" };
const _hoisted_88 = { class: "row switch" };
const _hoisted_89 = { class: "savebar" };
const _hoisted_90 = ["disabled"];
const _hoisted_91 = { class: "card" };
const _hoisted_92 = { class: "row switch" };
const _hoisted_93 = { class: "grid" };
const _hoisted_94 = { class: "fld" };
const _hoisted_95 = { class: "fld" };
const _hoisted_96 = { class: "row switch" };
const _hoisted_97 = { class: "card" };
const _hoisted_98 = { class: "grid" };
const _hoisted_99 = { class: "fld" };
const _hoisted_100 = { class: "fld" };
const _hoisted_101 = { class: "savebar" };
const _hoisted_102 = ["disabled"];

const {ref,reactive,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
},
  setup(__props) {

// 天空游戏 · 配置界面
// 左侧按游戏分组：全局设置 / 养马 / 炸金花 / 十点半
// host.getConfig() / host.saveConfig() / host.callApi()
const props = __props;

const DEFAULTS = {
  // 全局设置
  target_groups: '-1001326208894',
  bot: '',
  hdsky_cookie_file: '/app/data/hdsky_cookie.txt',
  hdsky_base_url: 'https://hdsky.supertimi.de:8443',
  hdsky_debug: false,
  hdsky_debug_file: '/app/data/hdsky_debug.jsonl',
  // 掉落守卫
  drop_guard_enabled: true,
  drop_guard_interval: 10,
  drop_guard_bot: '',
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
  horse_feed_type: 'fine',
  horse_feed_threshold: 60,
  horse_auto_walk: true,
  horse_auto_match_race: true,
  horse_race_min_stamina: 30,
  horse_auto_official_race: false,
  horse_auto_revive: false,
  horse_notify: true,
  horse_drop_guard: false,
  // 炸金花
  zjh_enabled: true,
  zjh_poll_interval: 2,
  zjh_peeked_threshold: 50,
  zjh_open_enabled: false,
  zjh_open_max_win_rate: 50,
  zjh_raise_enabled: false,
  zjh_raise_min_win_rate: 75,
  zjh_raise_frequency: 65,
  zjh_first_peek_no_raise: true,
  zjh_fold_ev_tolerance: 5,
  zjh_terminal_depth: 2,
  zjh_signal_mix_prob: 10,
  zjh_blind_max_calls: 3,
  zjh_profile_enabled: true,
  zjh_profile_halflife: 20,
  zjh_notify_join: true,
  zjh_notify_hand: true,
  zjh_notify_fold_confirm: false,
  zjh_notify_error: true,
  // 十点半
  tenhalf_enabled: false,
  tenhalf_poll_interval: 5,
  tenhalf_bet_amount: 100,
  tenhalf_stand_threshold: 8,
  tenhalf_notify: true,
};

// 草料选项（与后端 config_schema 一致）
const FEED_TYPES = [
  { value: 'weed', label: '杂草（100银元 +12饱腹 +6体力）' },
  { value: 'fine', label: '精草（300银元 +30饱腹 +18体力）' },
  { value: 'divine', label: '仙草（1000银元 +60饱腹 +50体力）' },
];

// 左侧分组：按游戏归类
const GROUPS = [
  { key: 'global', label: '全局设置', icon: '⚙️' },
  { key: 'horse', label: '养马', icon: '🐴' },
  { key: 'zjh', label: '炸金花', icon: '🃏' },
  { key: 'tenhalf', label: '十点半', icon: '🎲' },
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
            _cache[51] || (_cache[51] = _createElementVNode("div", { class: "side-title" }, "游戏", -1)),
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
                  _cache[85] || (_cache[85] = _createElementVNode("h3", { class: "det-title" }, "全局设置", -1)),
                  _createElementVNode("section", _hoisted_8, [
                    _cache[56] || (_cache[56] = _createElementVNode("div", { class: "card-h" }, "目标与机器人", -1)),
                    _createElementVNode("div", _hoisted_9, [
                      _cache[52] || (_cache[52] = _createElementVNode("span", { class: "lbl" }, "目标群组（一行一个ID）", -1)),
                      _withDirectives(_createElementVNode("textarea", {
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((cfg.target_groups) = $event)),
                        class: "inp",
                        rows: "3",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.target_groups]
                      ]),
                      _cache[53] || (_cache[53] = _createElementVNode("span", { class: "help" }, "游戏消息发到的群，一行一个。", -1))
                    ]),
                    _createElementVNode("div", _hoisted_10, [
                      _cache[54] || (_cache[54] = _createElementVNode("span", { class: "lbl" }, "天空小秘机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((cfg.bot) = $event)),
                        class: "inp",
                        placeholder: "@用户名 或 数字ID，逗号分隔可填多个"
                      }, null, 512), [
                        [_vModelText, cfg.bot]
                      ]),
                      _cache[55] || (_cache[55] = _createElementVNode("span", { class: "help" }, "留空=默认天空小秘。", -1))
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_11, [
                    _cache[60] || (_cache[60] = _createElementVNode("div", { class: "card-h" }, "HDSky 门户（炸金花/养马共用）", -1)),
                    _createElementVNode("div", _hoisted_12, [
                      _cache[57] || (_cache[57] = _createElementVNode("span", { class: "lbl" }, "Cookie 文件路径", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((cfg.hdsky_cookie_file) = $event)),
                        class: "inp",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.hdsky_cookie_file]
                      ]),
                      _cache[58] || (_cache[58] = _createElementVNode("span", { class: "help" }, "容器内路径（宿主 appdata/awbotnest/data 目录），过期后由下方自动续期覆盖", -1))
                    ]),
                    _createElementVNode("div", _hoisted_13, [
                      _cache[59] || (_cache[59] = _createElementVNode("span", { class: "lbl" }, "门户地址", -1)),
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
                    _cache[66] || (_cache[66] = _createElementVNode("div", { class: "card-h" }, "掉落配额守卫", -1)),
                    _createElementVNode("label", _hoisted_15, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((cfg.drop_guard_enabled) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.drop_guard_enabled]
                      ]),
                      _cache[61] || (_cache[61] = _createElementVNode("span", null, "掉落满时暂停游戏参与", -1))
                    ]),
                    _cache[67] || (_cache[67] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, " 定期私聊天空小秘发 /info 查「当前时段剩余掉落」，剩余为 0 时暂停十点半报名/炸金花入桌/赛马报名 （养马喂食/遛马不受影响），时段刷新后自动恢复；状态切换会通知一次 ", -1)),
                    _createElementVNode("div", _hoisted_16, [
                      _cache[62] || (_cache[62] = _createElementVNode("span", { class: "lbl" }, "掉落检查间隔(分钟)", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((cfg.drop_guard_interval) = $event)),
                        class: "inp",
                        type: "number",
                        min: "5",
                        max: "60",
                        step: "5"
                      }, null, 512), [
                        [
                          _vModelText,
                          cfg.drop_guard_interval,
                          void 0,
                          { number: true }
                        ]
                      ]),
                      _cache[63] || (_cache[63] = _createElementVNode("span", { class: "help" }, "多久私聊 bot 发一次 /info；越短对配额满的反应越快", -1))
                    ]),
                    _createElementVNode("div", _hoisted_17, [
                      _cache[64] || (_cache[64] = _createElementVNode("span", { class: "lbl" }, "掉落查询机器人", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cfg.drop_guard_bot) = $event)),
                        class: "inp",
                        placeholder: "@用户名 或 数字ID，留空=默认天空小秘"
                      }, null, 512), [
                        [_vModelText, cfg.drop_guard_bot]
                      ]),
                      _cache[65] || (_cache[65] = _createElementVNode("span", { class: "help" }, "/info 发给它查剩余掉落；独立于「目标与机器人」里的全局 bot 配置", -1))
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_18, [
                    _cache[71] || (_cache[71] = _createElementVNode("div", { class: "card-h" }, "调试", -1)),
                    _createElementVNode("label", _hoisted_19, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((cfg.hdsky_debug) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.hdsky_debug]
                      ]),
                      _cache[68] || (_cache[68] = _createElementVNode("span", null, "门户调试记录", -1))
                    ]),
                    _cache[72] || (_cache[72] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, " 开启后把每次门户 API 的请求与响应（脱敏后）追加写入下方 JSONL 文件，供事后核对实际请求；不改变平台日志级别 ", -1)),
                    _createElementVNode("div", _hoisted_20, [
                      _cache[69] || (_cache[69] = _createElementVNode("span", { class: "lbl" }, "调试记录文件路径", -1)),
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cfg.hdsky_debug_file) = $event)),
                        class: "inp",
                        spellcheck: "false"
                      }, null, 512), [
                        [_vModelText, cfg.hdsky_debug_file]
                      ]),
                      _cache[70] || (_cache[70] = _createElementVNode("span", { class: "help" }, "容器内 JSONL 路径（宿主 appdata/awbotnest/data 目录），超 10MB 自动轮转为 .1", -1))
                    ])
                  ]),
                  _createElementVNode("section", _hoisted_21, [
                    _cache[83] || (_cache[83] = _createElementVNode("div", { class: "card-h" }, "Cookie 自动续期", -1)),
                    _createElementVNode("label", _hoisted_22, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((cfg.auth_auto_renew) = $event)),
                        type: "checkbox"
                      }, null, 512), [
                        [_vModelCheckbox, cfg.auth_auto_renew]
                      ]),
                      _cache[73] || (_cache[73] = _createElementVNode("span", null, "门户会话过期自动续期", -1))
                    ]),
                    _cache[84] || (_cache[84] = _createElementVNode("span", {
                      class: "help",
                      style: {"margin-top":"-4px"}
                    }, " 经 MoviePilot CookieCloud 拉浏览器 cookie 快照 → 读 HDSky 站内信验证码 → 自动登录写回 Cookie 文件 ", -1)),
                    _createElementVNode("div", _hoisted_23, [
                      _createElementVNode("div", _hoisted_24, [
                        _cache[74] || (_cache[74] = _createElementVNode("span", { class: "lbl" }, "CookieCloud 地址", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cfg.cc_server) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_server]
                        ]),
                        _cache[75] || (_cache[75] = _createElementVNode("span", { class: "help" }, "MoviePilot 内置，http://<主机>:3000", -1))
                      ]),
                      _createElementVNode("div", _hoisted_25, [
                        _cache[76] || (_cache[76] = _createElementVNode("span", { class: "lbl" }, "HDSky UID", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((cfg.hdsky_uid) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.hdsky_uid]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_26, [
                        _cache[77] || (_cache[77] = _createElementVNode("span", { class: "lbl" }, "CookieCloud UUID（Key）", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((cfg.cc_uuid) = $event)),
                          class: "inp",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_uuid]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_27, [
                        _cache[78] || (_cache[78] = _createElementVNode("span", { class: "lbl" }, "CookieCloud 加密密钥", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((cfg.cc_password) = $event)),
                          class: "inp",
                          type: "password",
                          spellcheck: "false"
                        }, null, 512), [
                          [_vModelText, cfg.cc_password]
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_28, [
                        _cache[79] || (_cache[79] = _createElementVNode("span", { class: "lbl" }, "会话体检间隔(秒)", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((cfg.auth_check_interval) = $event)),
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
                        _cache[80] || (_cache[80] = _createElementVNode("span", { class: "help" }, "定期探测+主动续期；轮询遇到 401 也会即时触发", -1))
                      ]),
                      _createElementVNode("div", _hoisted_29, [
                        _cache[82] || (_cache[82] = _createElementVNode("span", { class: "lbl" }, "续期通知", -1)),
                        _createElementVNode("label", _hoisted_30, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((cfg.auth_notify) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.auth_notify]
                          ]),
                          _cache[81] || (_cache[81] = _createElementVNode("span", null, "结果推送", -1))
                        ])
                      ])
                    ]),
                    _createElementVNode("div", _hoisted_31, [
                      _createElementVNode("button", {
                        class: "btn",
                        disabled: renewing.value,
                        onClick: renewNow
                      }, _toDisplayString(renewing.value ? '续期中…' : '立即续期'), 9, _hoisted_32)
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
              : (group.value === 'horse')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _cache[111] || (_cache[111] = _createElementVNode("h3", { class: "det-title" }, "养马", -1)),
                    _createElementVNode("section", _hoisted_35, [
                      _cache[94] || (_cache[94] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                      _createElementVNode("label", _hoisted_36, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((cfg.horse_enabled) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_enabled]
                        ]),
                        _cache[86] || (_cache[86] = _createElementVNode("span", null, "启用养马自动化", -1))
                      ]),
                      _cache[95] || (_cache[95] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "每轮最多一个动作：参赛补体力（先精草后仙草）→ 喂食额度 → 遛马 → 官方赛", -1)),
                      _createElementVNode("div", _hoisted_37, [
                        _createElementVNode("div", _hoisted_38, [
                          _cache[87] || (_cache[87] = _createElementVNode("span", { class: "lbl" }, "养护轮询间隔(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((cfg.horse_poll_interval) = $event)),
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
                          _cache[88] || (_cache[88] = _createElementVNode("span", { class: "help" }, "节奏拟人，不用太频繁", -1))
                        ]),
                        _createElementVNode("div", _hoisted_39, [
                          _cache[90] || (_cache[90] = _createElementVNode("span", { class: "lbl" }, "养马通知", -1)),
                          _createElementVNode("label", _hoisted_40, [
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((cfg.horse_notify) = $event)),
                              type: "checkbox"
                            }, null, 512), [
                              [_vModelCheckbox, cfg.horse_notify]
                            ]),
                            _cache[89] || (_cache[89] = _createElementVNode("span", null, "操作结果推送", -1))
                          ])
                        ]),
                        _createElementVNode("div", _hoisted_41, [
                          _cache[92] || (_cache[92] = _createElementVNode("span", { class: "lbl" }, "掉落控制", -1)),
                          _createElementVNode("label", _hoisted_42, [
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((cfg.horse_drop_guard) = $event)),
                              type: "checkbox"
                            }, null, 512), [
                              [_vModelCheckbox, cfg.horse_drop_guard]
                            ]),
                            _cache[91] || (_cache[91] = _createElementVNode("span", null, "受游戏掉落控制", -1))
                          ]),
                          _cache[93] || (_cache[93] = _createElementVNode("span", { class: "help" }, "默认关：掉落配额满时养马照常；勾选后参赛也随守卫暂停", -1))
                        ])
                      ])
                    ]),
                    _createElementVNode("section", _hoisted_43, [
                      _cache[99] || (_cache[99] = _createElementVNode("div", { class: "card-h" }, "自动喂食", -1)),
                      _createElementVNode("div", _hoisted_44, [
                        _createElementVNode("div", _hoisted_45, [
                          _cache[96] || (_cache[96] = _createElementVNode("span", { class: "lbl" }, "草料", -1)),
                          _withDirectives(_createElementVNode("select", {
                            "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((cfg.horse_feed_type) = $event)),
                            class: "inp"
                          }, [
                            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(FEED_TYPES, (f) => {
                              return _createElementVNode("option", {
                                key: f.value,
                                value: f.value
                              }, _toDisplayString(f.label), 9, _hoisted_46)
                            }), 64))
                          ], 512), [
                            [_vModelSelect, cfg.horse_feed_type]
                          ])
                        ]),
                        _createElementVNode("div", _hoisted_47, [
                          _cache[97] || (_cache[97] = _createElementVNode("span", { class: "lbl" }, "体力阈值", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((cfg.horse_feed_threshold) = $event)),
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
                          _cache[98] || (_cache[98] = _createElementVNode("span", { class: "help" }, "体力低于此值才喂；优先配置草料，普通草冷却/额度用尽才喂仙草", -1))
                        ])
                      ])
                    ]),
                    _createElementVNode("section", _hoisted_48, [
                      _cache[106] || (_cache[106] = _createElementVNode("div", { class: "card-h" }, "自动行为", -1)),
                      _createElementVNode("label", _hoisted_49, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((cfg.horse_auto_walk) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_walk]
                        ]),
                        _cache[100] || (_cache[100] = _createElementVNode("span", null, "自动遛马", -1))
                      ]),
                      _cache[107] || (_cache[107] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "用完每日遛马额度（4 次），赚银元+经验，体力耗尽自动停", -1)),
                      _createElementVNode("label", _hoisted_50, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((cfg.horse_auto_match_race) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_match_race]
                        ]),
                        _cache[101] || (_cache[101] = _createElementVNode("span", null, "自动加入玩家养马赛", -1))
                      ]),
                      _cache[108] || (_cache[108] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "发现玩家开的 Horse2 时自动加入，报名额取房主设定", -1)),
                      _createElementVNode("div", _hoisted_51, [
                        _cache[102] || (_cache[102] = _createElementVNode("span", { class: "lbl" }, "参赛最低体力", -1)),
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((cfg.horse_race_min_stamina) = $event)),
                          class: "inp",
                          type: "number",
                          min: "0",
                          max: "100",
                          step: "5"
                        }, null, 512), [
                          [
                            _vModelText,
                            cfg.horse_race_min_stamina,
                            void 0,
                            { number: true }
                          ]
                        ]),
                        _cache[103] || (_cache[103] = _createElementVNode("span", { class: "help" }, "体力不够时喂一个仙草(+50)立即参赛（仙草每日 3 次）", -1))
                      ]),
                      _createElementVNode("label", _hoisted_52, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((cfg.horse_auto_official_race) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_official_race]
                        ]),
                        _cache[104] || (_cache[104] = _createElementVNode("span", null, "自动报名官方赛", -1))
                      ]),
                      _cache[109] || (_cache[109] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "每日官方赛开放报名时免费参加", -1)),
                      _createElementVNode("label", _hoisted_53, [
                        _withDirectives(_createElementVNode("input", {
                          "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((cfg.horse_auto_revive) = $event)),
                          type: "checkbox"
                        }, null, 512), [
                          [_vModelCheckbox, cfg.horse_auto_revive]
                        ]),
                        _cache[105] || (_cache[105] = _createElementVNode("span", null, "死亡自动复活", -1))
                      ]),
                      _cache[110] || (_cache[110] = _createElementVNode("span", {
                        class: "help",
                        style: {"margin-top":"-4px"}
                      }, "马匹死亡且余额足够时复活（约 30 万银元，默认关）", -1))
                    ]),
                    _createElementVNode("div", _hoisted_54, [
                      _createElementVNode("button", {
                        class: "btn primary lg",
                        disabled: saving.value,
                        onClick: save
                      }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_55)
                    ])
                  ], 64))
                : (group.value === 'zjh')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _cache[144] || (_cache[144] = _createElementVNode("h3", { class: "det-title" }, "炸金花", -1)),
                      _createElementVNode("section", _hoisted_56, [
                        _cache[115] || (_cache[115] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                        _createElementVNode("label", _hoisted_57, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((cfg.zjh_enabled) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_enabled]
                          ]),
                          _cache[112] || (_cache[112] = _createElementVNode("span", null, "启用自动参与", -1))
                        ]),
                        _cache[116] || (_cache[116] = _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"-4px"}
                        }, "轮询牌局：自动加入 → 首轮盲跟 → 看牌后按期望收益决策", -1)),
                        _createElementVNode("div", _hoisted_58, [
                          _cache[113] || (_cache[113] = _createElementVNode("span", { class: "lbl" }, "轮询间隔(秒)", -1)),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((cfg.zjh_poll_interval) = $event)),
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
                          _cache[114] || (_cache[114] = _createElementVNode("span", { class: "help" }, "Cookie 与门户地址见「全局设置」", -1))
                        ])
                      ]),
                      _cache[145] || (_cache[145] = _createElementVNode("section", { class: "card" }, [
                        _createElementVNode("div", { class: "card-h" }, "决策策略"),
                        _createElementVNode("span", { class: "help" }, " 已看牌完全按期望收益（EV）决策：胜率 ×（底池 + 跟注成本）− 跟注成本 ≥ 0 即跟注，否则弃牌。 胜率随剩余对手数衰减；已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛，再做条件胜率。 "),
                        _createElementVNode("span", {
                          class: "help",
                          style: {"margin-top":"8px"}
                        }, " 蒙牌用「终局 EV 决策树」：递归推演未来数轮对手的跟注/加注/弃牌，条件胜率随对手加注贝叶斯衰减， 求到达摊牌/弃牌时的终局期望，再和看牌、弃牌比较。避免单步 EV 把「跟这手就摊牌」当事实—— 实际门户单挑对手可持续加注把底池滚大，蒙牌闭眼跟到强制摊牌常常巨亏。 ")
                      ], -1)),
                      _createElementVNode("section", _hoisted_59, [
                        _cache[125] || (_cache[125] = _createElementVNode("div", { class: "card-h" }, "进攻策略（可选）", -1)),
                        _cache[126] || (_cache[126] = _createElementVNode("span", { class: "help" }, " 所有阈值均基于最终实际胜率：蒙牌对手按单挑胜率相乘；已看牌对手按其实际下注反推的最低牌力条件化后相乘。 开牌和追加只会在门户 actions 明确允许时发送；默认关闭，建议先观察日志中的服务端成本。 ", -1)),
                        _createElementVNode("div", _hoisted_60, [
                          _createElementVNode("div", _hoisted_61, [
                            _createElementVNode("label", _hoisted_62, [
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((cfg.zjh_open_enabled) = $event)),
                                type: "checkbox"
                              }, null, 512), [
                                [_vModelCheckbox, cfg.zjh_open_enabled]
                              ]),
                              _cache[117] || (_cache[117] = _createElementVNode("span", null, "启用低胜率主动开牌", -1))
                            ]),
                            _cache[118] || (_cache[118] = _createElementVNode("span", { class: "help" }, "正 EV 且最终实际胜率低于阈值时，若允许 open 则发起比牌。", -1)),
                            _createElementVNode("span", _hoisted_63, "最高实际胜率：" + _toDisplayString(cfg.zjh_open_max_win_rate) + "%", 1),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((cfg.zjh_open_max_win_rate) = $event)),
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
                            ]),
                            _createElementVNode("span", _hoisted_64, "信号混合：" + _toDisplayString(cfg.zjh_signal_mix_prob) + "%", 1),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((cfg.zjh_signal_mix_prob) = $event)),
                              type: "range",
                              min: "0",
                              max: "50",
                              step: "5"
                            }, null, 512), [
                              [
                                _vModelText,
                                cfg.zjh_signal_mix_prob,
                                void 0,
                                { number: true }
                              ]
                            ]),
                            _cache[119] || (_cache[119] = _createElementVNode("span", { class: "help" }, " 双向混合防读牌：弱牌该开牌止损时小概率改跟注慢打、强牌该继续时小概率直接开牌—— 对手统计不出「开牌=弱牌、继续=强牌」。0=关（旧行为：低于开牌阈值必开）。 ", -1))
                          ]),
                          _createElementVNode("div", _hoisted_65, [
                            _createElementVNode("label", _hoisted_66, [
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((cfg.zjh_raise_enabled) = $event)),
                                type: "checkbox"
                              }, null, 512), [
                                [_vModelCheckbox, cfg.zjh_raise_enabled]
                              ]),
                              _cache[120] || (_cache[120] = _createElementVNode("span", null, "启用高胜率主动追加", -1))
                            ]),
                            _cache[124] || (_cache[124] = _createElementVNode("span", { class: "help" }, "正 EV 且最终实际胜率达到阈值时，若允许 raise 则追加。", -1)),
                            _createElementVNode("span", _hoisted_67, "最低实际胜率：" + _toDisplayString(cfg.zjh_raise_min_win_rate) + "%", 1),
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((cfg.zjh_raise_min_win_rate) = $event)),
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
                            ]),
                            (cfg.zjh_raise_enabled)
                              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                  _createElementVNode("span", _hoisted_68, "达标加注频率：" + _toDisplayString(cfg.zjh_raise_frequency) + "%", 1),
                                  _withDirectives(_createElementVNode("input", {
                                    "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((cfg.zjh_raise_frequency) = $event)),
                                    type: "range",
                                    min: "0",
                                    max: "100",
                                    step: "5"
                                  }, null, 512), [
                                    [
                                      _vModelText,
                                      cfg.zjh_raise_frequency,
                                      void 0,
                                      { number: true }
                                    ]
                                  ]),
                                  _cache[122] || (_cache[122] = _createElementVNode("span", { class: "help" }, "达阈值时按此概率加注、其余慢打平跟做伪装；100=达标必加。", -1)),
                                  _createElementVNode("label", _hoisted_69, [
                                    _withDirectives(_createElementVNode("input", {
                                      "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((cfg.zjh_first_peek_no_raise) = $event)),
                                      type: "checkbox"
                                    }, null, 512), [
                                      [_vModelCheckbox, cfg.zjh_first_peek_no_raise]
                                    ]),
                                    _cache[121] || (_cache[121] = _createElementVNode("span", null, "第一次看牌不加注（慢打留人）", -1))
                                  ]),
                                  _cache[123] || (_cache[123] = _createElementVNode("span", { class: "help" }, "本局首次看牌即使达阈值也平跟不加注，避免吓退对手；后续轮次才按频率加注。", -1))
                                ], 64))
                              : _createCommentVNode("", true)
                          ])
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_70, [
                        _cache[128] || (_cache[128] = _createElementVNode("div", { class: "card-h" }, "看牌对手推断", -1)),
                        _createElementVNode("div", _hoisted_71, [
                          _createElementVNode("span", _hoisted_72, "未观测到下注时的牌力阈值：" + _toDisplayString(cfg.zjh_peeked_threshold) + "%", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((cfg.zjh_peeked_threshold) = $event)),
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
                          _cache[127] || (_cache[127] = _createElementVNode("span", { class: "help" }, " 系统优先按对手看牌后实际下注时的底池和成本反推门槛；轮询漏掉该动作时才使用此回退值。 ", -1))
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_73, [
                        _cache[131] || (_cache[131] = _createElementVNode("div", { class: "card-h" }, "对手范围与反诈唬（画像自动驱动）", -1)),
                        _cache[132] || (_cache[132] = _createElementVNode("span", { class: "help" }, " 看牌后评估胜率时，对手手牌范围与反诈唬全部由对手画像自动推断，无需手动设置： 加注对手按实测加注牌力下限估计，平跟对手永不封顶（可能慢打坚果牌）； 继续频率异常高的对手自动计入诈唬概率。无画像对手按推断门槛、不反诈唬。 ", -1)),
                        _createElementVNode("div", _hoisted_74, [
                          _createElementVNode("span", _hoisted_75, "弃牌 EV 容差：" + _toDisplayString(cfg.zjh_fold_ev_tolerance) + "% callBet", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[37] || (_cache[37] = $event => ((cfg.zjh_fold_ev_tolerance) = $event)),
                            type: "range",
                            min: "0",
                            max: "30",
                            step: "1"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.zjh_fold_ev_tolerance,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[129] || (_cache[129] = _createElementVNode("span", { class: "help" }, "跟注 EV 只是略负（≥ −此比例×callBet）时不弃牌。0% = 旧行为（EV<0 即弃）。", -1))
                        ]),
                        _createElementVNode("div", _hoisted_76, [
                          _createElementVNode("span", _hoisted_77, "画像半衰期：" + _toDisplayString(cfg.zjh_profile_halflife) + " 手", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((cfg.zjh_profile_halflife) = $event)),
                            type: "range",
                            min: "0",
                            max: "200",
                            step: "5"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.zjh_profile_halflife,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[130] || (_cache[130] = _createElementVNode("span", { class: "help" }, " 画像按对手已完成手数衰减：每结算一手，历史计数与手牌样本权重减半（半衰期手数见上）。 高频对手自然衰减快、低频慢；0 = 不衰减（永久保留全部历史，旧行为）。 手牌样本窗口自动跟随半衰期（3 个半衰期、最少 100 条），调大半衰期不会缩短真实记忆窗口。 ", -1))
                        ])
                      ]),
                      _createElementVNode("section", _hoisted_78, [
                        _cache[136] || (_cache[136] = _createElementVNode("div", { class: "card-h" }, "蒙牌决策（终局 EV 决策树）", -1)),
                        _cache[137] || (_cache[137] = _createElementVNode("span", { class: "help" }, " 蒙牌不再只看当前一步的期望收益，而是推演未来几轮：对手每轮跟/加/弃（概率来自对手画像）， 我方蒙牌胜率随对手连续加注衰减（门槛贝叶斯上调），求到达摊牌/弃牌的终局期望。 连续盲跟过多会被强制看牌止损，避免像单步 EV 那样闭眼跟到强制摊牌巨亏。 ", -1)),
                        _createElementVNode("div", _hoisted_79, [
                          _createElementVNode("span", _hoisted_80, "决策树深度：" + _toDisplayString(cfg.zjh_terminal_depth) + " 轮", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((cfg.zjh_terminal_depth) = $event)),
                            type: "range",
                            min: "1",
                            max: "3",
                            step: "1"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.zjh_terminal_depth,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[133] || (_cache[133] = _createElementVNode("span", { class: "help" }, "推演未来 N 轮对手动作再算终局 EV。1 = 退回旧单步 EV 行为。", -1))
                        ]),
                        _createElementVNode("div", _hoisted_81, [
                          _createElementVNode("span", _hoisted_82, "连续盲跟上限：" + _toDisplayString(cfg.zjh_blind_max_calls) + " 轮", 1),
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((cfg.zjh_blind_max_calls) = $event)),
                            type: "range",
                            min: "0",
                            max: "10",
                            step: "1"
                          }, null, 512), [
                            [
                              _vModelText,
                              cfg.zjh_blind_max_calls,
                              void 0,
                              { number: true }
                            ]
                          ]),
                          _cache[134] || (_cache[134] = _createElementVNode("span", { class: "help" }, "蒙牌连续盲跟达该轮数后强制看牌止损。0 = 不限，纯按终局 EV。", -1))
                        ]),
                        _createElementVNode("label", _hoisted_83, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[41] || (_cache[41] = $event => ((cfg.zjh_profile_enabled) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_profile_enabled]
                          ]),
                          _cache[135] || (_cache[135] = _createElementVNode("span", null, "启用对手画像", -1))
                        ]),
                        _cache[138] || (_cache[138] = _createElementVNode("span", { class: "help" }, "按玩家 ID 跨局统计每个对手的动作频率与实测手牌分位：决策树据此预测动作，已看牌胜率据此定对手范围与反诈唬。未知对手用全局先验、不反诈唬。", -1))
                      ]),
                      _createElementVNode("section", _hoisted_84, [
                        _cache[143] || (_cache[143] = _createElementVNode("div", { class: "card-h" }, "通知", -1)),
                        _createElementVNode("label", _hoisted_85, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((cfg.zjh_notify_join) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_join]
                          ]),
                          _cache[139] || (_cache[139] = _createElementVNode("span", null, "加入牌局", -1))
                        ]),
                        _createElementVNode("label", _hoisted_86, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[43] || (_cache[43] = $event => ((cfg.zjh_notify_hand) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_hand]
                          ]),
                          _cache[140] || (_cache[140] = _createElementVNode("span", null, "手牌决策（跟注/弃牌）", -1))
                        ]),
                        _createElementVNode("label", _hoisted_87, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((cfg.zjh_notify_fold_confirm) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_fold_confirm]
                          ]),
                          _cache[141] || (_cache[141] = _createElementVNode("span", null, "双击确认弃牌", -1))
                        ]),
                        _createElementVNode("label", _hoisted_88, [
                          _withDirectives(_createElementVNode("input", {
                            "onUpdate:modelValue": _cache[45] || (_cache[45] = $event => ((cfg.zjh_notify_error) = $event)),
                            type: "checkbox"
                          }, null, 512), [
                            [_vModelCheckbox, cfg.zjh_notify_error]
                          ]),
                          _cache[142] || (_cache[142] = _createElementVNode("span", null, "异常", -1))
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_89, [
                        _createElementVNode("button", {
                          class: "btn primary lg",
                          disabled: saving.value,
                          onClick: save
                        }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_90)
                      ])
                    ], 64))
                  : (group.value === 'tenhalf')
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                        _cache[159] || (_cache[159] = _createElementVNode("h3", { class: "det-title" }, "十点半", -1)),
                        _createElementVNode("section", _hoisted_91, [
                          _cache[151] || (_cache[151] = _createElementVNode("div", { class: "card-h" }, "基础设置", -1)),
                          _createElementVNode("label", _hoisted_92, [
                            _withDirectives(_createElementVNode("input", {
                              "onUpdate:modelValue": _cache[46] || (_cache[46] = $event => ((cfg.tenhalf_enabled) = $event)),
                              type: "checkbox"
                            }, null, 512), [
                              [_vModelCheckbox, cfg.tenhalf_enabled]
                            ]),
                            _cache[146] || (_cache[146] = _createElementVNode("span", null, "启用自动参与", -1))
                          ]),
                          _cache[152] || (_cache[152] = _createElementVNode("span", {
                            class: "help",
                            style: {"margin-top":"-4px"}
                          }, " 有桌开局时报名下注 → 抓牌阶段要牌/停牌 → 结算推送战绩。只玩玩家位不开庄。 动作契约来自门户前端尚未实测，首次启用建议同时开启「全局设置 · 门户调试记录」核对 ", -1)),
                          _createElementVNode("div", _hoisted_93, [
                            _createElementVNode("div", _hoisted_94, [
                              _cache[147] || (_cache[147] = _createElementVNode("span", { class: "lbl" }, "轮询间隔(秒)", -1)),
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[47] || (_cache[47] = $event => ((cfg.tenhalf_poll_interval) = $event)),
                                class: "inp",
                                type: "number",
                                min: "2",
                                max: "60",
                                step: "1"
                              }, null, 512), [
                                [
                                  _vModelText,
                                  cfg.tenhalf_poll_interval,
                                  void 0,
                                  { number: true }
                                ]
                              ]),
                              _cache[148] || (_cache[148] = _createElementVNode("span", { class: "help" }, "报名阶段有倒计时，轮询太慢会错过报名", -1))
                            ]),
                            _createElementVNode("div", _hoisted_95, [
                              _cache[150] || (_cache[150] = _createElementVNode("span", { class: "lbl" }, "十点半通知", -1)),
                              _createElementVNode("label", _hoisted_96, [
                                _withDirectives(_createElementVNode("input", {
                                  "onUpdate:modelValue": _cache[48] || (_cache[48] = $event => ((cfg.tenhalf_notify) = $event)),
                                  type: "checkbox"
                                }, null, 512), [
                                  [_vModelCheckbox, cfg.tenhalf_notify]
                                ]),
                                _cache[149] || (_cache[149] = _createElementVNode("span", null, "报名/结算推送", -1))
                              ])
                            ])
                          ])
                        ]),
                        _createElementVNode("section", _hoisted_97, [
                          _cache[157] || (_cache[157] = _createElementVNode("div", { class: "card-h" }, "参与策略", -1)),
                          _createElementVNode("div", _hoisted_98, [
                            _createElementVNode("div", _hoisted_99, [
                              _cache[153] || (_cache[153] = _createElementVNode("span", { class: "lbl" }, "报名下注额", -1)),
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[49] || (_cache[49] = $event => ((cfg.tenhalf_bet_amount) = $event)),
                                class: "inp",
                                type: "number",
                                min: "100",
                                max: "10000",
                                step: "100"
                              }, null, 512), [
                                [
                                  _vModelText,
                                  cfg.tenhalf_bet_amount,
                                  void 0,
                                  { number: true }
                                ]
                              ]),
                              _cache[154] || (_cache[154] = _createElementVNode("span", { class: "help" }, "自动夹在门户最小下注与本桌单人上限之间", -1))
                            ]),
                            _createElementVNode("div", _hoisted_100, [
                              _cache[155] || (_cache[155] = _createElementVNode("span", { class: "lbl" }, "停牌点数阈值（基准）", -1)),
                              _withDirectives(_createElementVNode("input", {
                                "onUpdate:modelValue": _cache[50] || (_cache[50] = $event => ((cfg.tenhalf_stand_threshold) = $event)),
                                class: "inp",
                                type: "number",
                                min: "4",
                                max: "10",
                                step: "0.5"
                              }, null, 512), [
                                [
                                  _vModelText,
                                  cfg.tenhalf_stand_threshold,
                                  void 0,
                                  { number: true }
                                ]
                              ]),
                              _cache[156] || (_cache[156] = _createElementVNode("span", { class: "help" }, "仅画像样本不足时的回退基准；样本足够时走 EV 决策（停牌 EV 对要牌 EV 递推择优）", -1))
                            ])
                          ]),
                          _cache[158] || (_cache[158] = _createElementVNode("span", { class: "help" }, " 决策优先序：庄家爆牌→停牌 ｜ 我方/庄家五小→立即停牌 ｜ 庄家画像样本足够→EV 决策： 按画像点数分布+爆率算停牌 EV，对比 52 张先验递推的要牌 EV（含五小 ×5），择优要/停， 张数是一等公民（4 张低点数追五小、高点数早停）｜ 画像不足→退停牌阈值。 从不认输（fold 与停牌同样损失下注） ", -1))
                        ]),
                        _createElementVNode("div", _hoisted_101, [
                          _createElementVNode("button", {
                            class: "btn primary lg",
                            disabled: saving.value,
                            onClick: save
                          }, _toDisplayString(saving.value ? '保存中…' : '保存配置'), 9, _hoisted_102)
                        ])
                      ], 64))
                    : _createCommentVNode("", true)
          ])
        ]))
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-02bd9d28"]]);

export { Config as default };
