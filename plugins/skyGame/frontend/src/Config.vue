<script setup>
// 天空游戏 · 配置界面
// 左侧按游戏分组：全局设置 / 养马 / 炸金花
// host.getConfig() / host.saveConfig() / host.callApi()
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
})

const DEFAULTS = {
  // 全局设置
  target_groups: '-1001326208894',
  bot: '',
  hdsky_cookie_file: '/app/data/hdsky_cookie.txt',
  hdsky_base_url: 'https://hdsky.supertimi.de:8443',
  hdsky_debug: false,
  hdsky_debug_file: '/app/data/hdsky_debug.jsonl',
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
  zjh_call_range_cap: 85,
  zjh_raise_range_floor: 75,
  zjh_bluff_rate: 8,
  zjh_notify_join: true,
  zjh_notify_hand: true,
  zjh_notify_fold_confirm: false,
  zjh_notify_error: true,
}

// 草料选项（与后端 config_schema 一致）
const FEED_TYPES = [
  { value: 'weed', label: '杂草（100银元 +12饱腹）' },
  { value: 'fine', label: '精草（300银元 +30饱腹）' },
  { value: 'divine', label: '仙草（1000银元 +60饱腹）' },
]

// 左侧分组：按游戏归类
const GROUPS = [
  { key: 'global', label: '全局设置', icon: '⚙️' },
  { key: 'horse', label: '养马', icon: '🐴' },
  { key: 'zjh', label: '炸金花', icon: '🃏' },
]

const group = ref('global')
const loading = ref(true)
const saving = ref(false)
const renewing = ref(false)
const cfg = reactive({ ...DEFAULTS })

onMounted(async () => {
  try {
    const saved = await props.host.getConfig()
    Object.assign(cfg, DEFAULTS, saved || {})
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  try {
    await props.host.saveConfig({ ...cfg })
    props.host.toast.success('配置已保存')
  } catch (e) {
    props.host.toast.error('保存失败：' + (e.message || e))
  } finally {
    saving.value = false
  }
}

// 手动触发一次 Cookie 续期（后端 hdsky_auth，跳过防抖）
async function renewNow() {
  renewing.value = true
  try {
    const r = await props.host.callApi('/renew', { method: 'POST' })
    if (r && r.ok) props.host.toast.success(r.message || '续期成功')
    else props.host.toast.error((r && r.message) || '续期失败')
  } catch (e) {
    props.host.toast.error('续期请求失败：' + (e.message || e))
  } finally {
    renewing.value = false
  }
}
</script>

<template>
  <div class="lcfg">
    <div v-if="loading" class="muted">加载配置…</div>
    <div v-else class="layout">
      <aside class="sidebar">
        <div class="side-title">游戏</div>
        <button v-for="g in GROUPS" :key="g.key"
                :class="['side-item', { on: group === g.key }]" @click="group = g.key">
          <span class="side-icon">{{ g.icon }}</span>
          <span>{{ g.label }}</span>
        </button>
      </aside>

      <div class="detail">
        <!-- ============ 全局设置 ============ -->
        <template v-if="group === 'global'">
          <h3 class="det-title">全局设置</h3>

          <section class="card">
            <div class="card-h">目标与机器人</div>
            <div class="fld">
              <span class="lbl">目标群组（一行一个ID）</span>
              <textarea v-model="cfg.target_groups" class="inp" rows="3" spellcheck="false"></textarea>
              <span class="help">游戏消息发到的群，一行一个。</span>
            </div>
            <div class="fld">
              <span class="lbl">天空小秘机器人</span>
              <input v-model="cfg.bot" class="inp" placeholder="@用户名 或 数字ID，逗号分隔可填多个" />
              <span class="help">留空=默认天空小秘。</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">HDSky 门户（炸金花/养马共用）</div>
            <div class="fld">
              <span class="lbl">Cookie 文件路径</span>
              <input v-model="cfg.hdsky_cookie_file" class="inp" spellcheck="false" />
              <span class="help">容器内路径（宿主 appdata/awbotnest/data 目录），过期后由下方自动续期覆盖</span>
            </div>
            <div class="fld">
              <span class="lbl">门户地址</span>
              <input v-model="cfg.hdsky_base_url" class="inp" spellcheck="false" />
            </div>
          </section>

          <section class="card">
            <div class="card-h">调试</div>
            <label class="row switch">
              <input v-model="cfg.hdsky_debug" type="checkbox" />
              <span>门户调试记录</span>
            </label>
            <span class="help" style="margin-top:-4px">
              开启后把每次门户 API 的请求与响应（脱敏后）追加写入下方 JSONL 文件，供事后核对实际请求；不改变平台日志级别
            </span>
            <div class="fld">
              <span class="lbl">调试记录文件路径</span>
              <input v-model="cfg.hdsky_debug_file" class="inp" spellcheck="false" />
              <span class="help">容器内 JSONL 路径（宿主 appdata/awbotnest/data 目录），超 10MB 自动轮转为 .1</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">Cookie 自动续期</div>
            <label class="row switch">
              <input v-model="cfg.auth_auto_renew" type="checkbox" />
              <span>门户会话过期自动续期</span>
            </label>
            <span class="help" style="margin-top:-4px">
              经 MoviePilot CookieCloud 拉浏览器 cookie 快照 → 读 HDSky 站内信验证码 → 自动登录写回 Cookie 文件
            </span>
            <div class="grid">
              <div class="fld">
                <span class="lbl">CookieCloud 地址</span>
                <input v-model="cfg.cc_server" class="inp" spellcheck="false" />
                <span class="help">MoviePilot 内置，http://&lt;主机&gt;:3000</span>
              </div>
              <div class="fld">
                <span class="lbl">HDSky UID</span>
                <input v-model="cfg.hdsky_uid" class="inp" spellcheck="false" />
              </div>
              <div class="fld">
                <span class="lbl">CookieCloud UUID（Key）</span>
                <input v-model="cfg.cc_uuid" class="inp" spellcheck="false" />
              </div>
              <div class="fld">
                <span class="lbl">CookieCloud 加密密钥</span>
                <input v-model="cfg.cc_password" class="inp" type="password" spellcheck="false" />
              </div>
              <div class="fld">
                <span class="lbl">会话体检间隔(秒)</span>
                <input v-model.number="cfg.auth_check_interval" class="inp" type="number" min="600" max="7200" step="300" />
                <span class="help">定期探测+主动续期；轮询遇到 401 也会即时触发</span>
              </div>
              <div class="fld">
                <span class="lbl">续期通知</span>
                <label class="row switch">
                  <input v-model="cfg.auth_notify" type="checkbox" />
                  <span>结果推送</span>
                </label>
              </div>
            </div>
            <div class="row" style="justify-content:flex-end">
              <button class="btn" :disabled="renewing" @click="renewNow">{{ renewing ? '续期中…' : '立即续期' }}</button>
            </div>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 养马 ============ -->
        <template v-else-if="group === 'horse'">
          <h3 class="det-title">养马</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.horse_enabled" type="checkbox" />
              <span>启用养马自动化</span>
            </label>
            <span class="help" style="margin-top:-4px">每轮轮询最多执行一个养护动作：喂食 → 遛马 → 官方赛</span>
            <div class="grid">
              <div class="fld">
                <span class="lbl">养护轮询间隔(秒)</span>
                <input v-model.number="cfg.horse_poll_interval" class="inp" type="number" min="30" max="600" step="10" />
                <span class="help">节奏拟人，不用太频繁</span>
              </div>
              <div class="fld">
                <span class="lbl">养马通知</span>
                <label class="row switch">
                  <input v-model="cfg.horse_notify" type="checkbox" />
                  <span>操作结果推送</span>
                </label>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-h">自动喂食</div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">草料</span>
                <select v-model="cfg.horse_feed_type" class="inp">
                  <option v-for="f in FEED_TYPES" :key="f.value" :value="f.value">{{ f.label }}</option>
                </select>
              </div>
              <div class="fld">
                <span class="lbl">饱腹度阈值</span>
                <input v-model.number="cfg.horse_feed_threshold" class="inp" type="number" min="0" max="100" step="5" />
                <span class="help">低于此值且今日次数未用完时喂（每日上限 5 次）</span>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-h">自动行为</div>
            <label class="row switch">
              <input v-model="cfg.horse_auto_walk" type="checkbox" />
              <span>自动遛马</span>
            </label>
            <span class="help" style="margin-top:-4px">用完每日遛马额度（4 次），赚银元+经验，体力耗尽自动停</span>
            <label class="row switch">
              <input v-model="cfg.horse_auto_official_race" type="checkbox" />
              <span>自动报名官方赛</span>
            </label>
            <span class="help" style="margin-top:-4px">每日官方赛开放报名时免费参加</span>
            <label class="row switch">
              <input v-model="cfg.horse_auto_revive" type="checkbox" />
              <span>死亡自动复活</span>
            </label>
            <span class="help" style="margin-top:-4px">马匹死亡且余额足够时复活（约 30 万银元，默认关）</span>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 炸金花 ============ -->
        <template v-else-if="group === 'zjh'">
          <h3 class="det-title">炸金花</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.zjh_enabled" type="checkbox" />
              <span>启用自动参与</span>
            </label>
            <span class="help" style="margin-top:-4px">轮询牌局：自动加入 → 首轮盲跟 → 看牌后按期望收益决策</span>
            <div class="fld">
              <span class="lbl">轮询间隔(秒)</span>
              <input v-model.number="cfg.zjh_poll_interval" class="inp" type="number" min="1" max="10" step="0.5" />
              <span class="help">Cookie 与门户地址见「全局设置」</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">决策策略</div>
            <span class="help">
              完全按期望收益（EV）决策，不再按牌型勾选：胜率 ×（底池 + 跟注成本）− 跟注成本 ≥ 0 即跟注，否则弃牌。
              胜率随剩余对手数衰减；已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛，再做条件胜率。
            </span>
          </section>

          <section class="card">
            <div class="card-h">进攻策略（可选）</div>
            <span class="help">
              所有阈值均基于最终实际胜率：蒙牌对手按单挑胜率相乘；已看牌对手按其实际下注反推的最低牌力条件化后相乘。
              开牌和追加只会在门户 actions 明确允许时发送；默认关闭，建议先观察日志中的服务端成本。
            </span>
            <div class="grid">
              <div class="fld">
                <label class="row switch">
                  <input v-model="cfg.zjh_open_enabled" type="checkbox" />
                  <span>启用低胜率主动开牌</span>
                </label>
                <span class="help">正 EV 且最终实际胜率低于阈值时，若允许 open 则发起比牌。</span>
                <span class="lbl">最高实际胜率：{{ cfg.zjh_open_max_win_rate }}%</span>
                <input v-model.number="cfg.zjh_open_max_win_rate" type="range" min="0" max="95" step="5" />
              </div>
              <div class="fld">
                <label class="row switch">
                  <input v-model="cfg.zjh_raise_enabled" type="checkbox" />
                  <span>启用高胜率主动追加</span>
                </label>
                <span class="help">正 EV 且最终实际胜率达到阈值时，若允许 raise 则追加。</span>
                <span class="lbl">最低实际胜率：{{ cfg.zjh_raise_min_win_rate }}%</span>
                <input v-model.number="cfg.zjh_raise_min_win_rate" type="range" min="5" max="100" step="5" />
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-h">看牌对手推断</div>
            <div class="fld">
              <span class="lbl">未观测到下注时的牌力阈值：{{ cfg.zjh_peeked_threshold }}%</span>
              <input v-model.number="cfg.zjh_peeked_threshold" type="range" min="0" max="95" step="5" />
              <span class="help">
                系统优先按对手看牌后实际下注时的底池和成本反推门槛；轮询漏掉该动作时才使用此回退值。
              </span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">范围上限与反诈唬（放松跟注）</div>
            <span class="help">
              看牌后评估胜率时，对手手牌不再默认可能是直到最强的任意牌：平跟/仅看牌对手按[推断门槛, 牌力上限]、
              加注对手按[牌力下限, 100%]估计；反诈唬基线把每个已看牌对手有固定比例视为纯空气牌。整体更敢跟、少弃牌。
              牌力上限设 100% 且反诈唬设 0% 即精确回到旧行为。
            </span>
            <div class="fld">
              <span class="lbl">平跟对手牌力上限：{{ cfg.zjh_call_range_cap }}%</span>
              <input v-model.number="cfg.zjh_call_range_cap" type="range" min="50" max="100" step="5" />
              <span class="help">只平跟/看牌不追加的对手，牌力按[推断门槛, 此上限]估计。100% = 旧行为。</span>
            </div>
            <div class="fld">
              <span class="lbl">加注对手牌力下限：{{ cfg.zjh_raise_range_floor }}%</span>
              <input v-model.number="cfg.zjh_raise_range_floor" type="range" min="50" max="100" step="5" />
              <span class="help">追加过的对手按[max(推断门槛, 此下限), 100%]估计；低于推断门槛时以推断门槛为准。</span>
            </div>
            <div class="fld">
              <span class="lbl">反诈唬基线：{{ cfg.zjh_bluff_rate }}%</span>
              <input v-model.number="cfg.zjh_bluff_rate" type="range" min="0" max="30" step="1" />
              <span class="help">每个已看牌对手有该比例概率是纯空气牌（诈唬），抬高我方胜率。0% = 关闭。</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">通知</div>
            <label class="row switch">
              <input v-model="cfg.zjh_notify_join" type="checkbox" />
              <span>加入牌局</span>
            </label>
            <label class="row switch">
              <input v-model="cfg.zjh_notify_hand" type="checkbox" />
              <span>手牌决策（跟注/弃牌）</span>
            </label>
            <label class="row switch">
              <input v-model="cfg.zjh_notify_fold_confirm" type="checkbox" />
              <span>双击确认弃牌</span>
            </label>
            <label class="row switch">
              <input v-model="cfg.zjh_notify_error" type="checkbox" />
              <span>异常</span>
            </label>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lcfg { display: flex; flex-direction: column; gap: 14px; container-type: inline-size; min-height: 100%; }
.layout { display: flex; gap: 16px; align-items: flex-start; min-height: 100%; }
.sidebar {
  flex: 0 0 150px; display: flex; flex-direction: column; gap: 4px;
  padding: 10px; border-radius: 10px;
  background: var(--bg-elevated, #1a1d27); border: 1px solid var(--border-light, #2a2e3a);
}
.side-title { font-size: 11px; color: var(--text-muted, #7a8291); padding: 4px 8px 6px; }
.side-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: 8px; border: none; cursor: pointer; text-align: left;
  background: none; color: var(--text-secondary, #b9c0cc); font-size: 13px;
  transition: background 0.15s, color 0.15s;
}
.side-item:hover { background: var(--bg-card, #12141c); }
.side-item.on { background: var(--accent-dim, #1e3a5f); color: var(--accent, #6ea8fe); }
.side-icon { font-size: 14px; }

.detail { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.det-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary, #e8ebf0); }

.card {
  display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 10px;
  background: var(--bg-elevated, #1a1d27); border: 1px solid var(--border-light, #2a2e3a);
}
.card-h { font-size: 13px; font-weight: 600; color: var(--accent, #6ea8fe); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px 20px; }
.fld { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lbl { font-size: 13px; color: var(--text-secondary, #b9c0cc); }
.help { font-size: 12px; color: var(--text-muted, #7a8291); }
.row { display: flex; align-items: center; gap: 10px; }
.row.switch { cursor: pointer; font-size: 13px; color: var(--text-primary, #e8ebf0); }
.row.switch input { accent-color: var(--accent, #6ea8fe); }

.inp {
  width: 100%; min-width: 0; box-sizing: border-box;
  padding: 8px 10px; border-radius: 6px; font-size: 13px;
  background: var(--bg-card, #12141c); color: var(--text-primary, #e8ebf0);
  border: 1px solid var(--border-light, #2a2e3a);
  transition: border-color 0.15s;
}
.inp:focus { outline: none; border-color: var(--accent, #6ea8fe); }
.inp[type='number'] { max-width: 150px; }
textarea.inp { resize: vertical; font-family: inherit; }

.btn {
  padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  background: var(--bg-card, #12141c); color: var(--text-secondary, #b9c0cc);
  border: 1px solid var(--border-light, #2a2e3a);
  transition: border-color 0.15s, color 0.15s;
}
.btn:hover { border-color: var(--accent, #6ea8fe); color: var(--accent, #6ea8fe); }
.btn.primary { background: var(--accent-dim, #1e3a5f); border-color: var(--accent, #6ea8fe); color: var(--accent, #6ea8fe); }
.btn.lg { padding: 9px 22px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.savebar { position: sticky; bottom: 0; display: flex; justify-content: flex-end; padding-top: 4px; }
.muted { font-size: 12px; color: var(--text-muted, #7a8291); }

@container (max-width: 620px) {
  .layout { flex-direction: column; }
  .sidebar { flex-basis: auto; width: 100%; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }
  .side-title { display: none; }
  .side-item { flex: 0 1 auto; }
  .detail { width: 100%; }
  .grid { grid-template-columns: 1fr; }
  .inp[type='number'] { max-width: none; width: 100%; }
  .savebar { justify-content: stretch; }
  .savebar .btn.lg { width: 100%; text-align: center; }
}
@container (max-width: 380px) {
  .card { padding: 12px; }
  .sidebar { padding: 8px; gap: 4px; }
  .inp { padding: 7px 8px; }
}
</style>
