<script setup>
// 天空游戏 · 配置界面
// 左侧按游戏分组：全局设置 / 养马 / 炸金花 / 十点半
// host.getConfig() / host.saveConfig() / host.callApi()
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
})

// AI 评价默认提示词模板（与后端 games/ai_review.py DEFAULT_TEMPLATE 同一文案）；
// 「恢复默认模板」按钮与 DEFAULTS 都从这里取，改坏了随时一键还原
const DEFAULT_AI_REVIEW_PROMPT =
  '本局我先后做了这样的决定：{actions}。对手是「{opponent}」，本局结果：{result}。{tone}。直接输出要说的话，不要解释。'

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
  // 幸运轮盘
  lucky_enabled: true,
  lucky_draw_time: '23:50',
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
  // AI 评价（通用模块）
  ai_review_enabled: true,
  ai_review_games: ['tenhalf'],
  ai_review_groups: '',
  ai_review_prompt: DEFAULT_AI_REVIEW_PROMPT,
}

// 草料选项（与后端 config_schema 一致）
const FEED_TYPES = [
  { value: 'weed', label: '杂草（100银元 +12饱腹 +6体力）' },
  { value: 'fine', label: '精草（300银元 +30饱腹 +18体力）' },
  { value: 'divine', label: '仙草（1000银元 +60饱腹 +50体力）' },
]

// 可 AI 评价的游戏（与后端 config_schema ai_review_games 一致）
const AI_REVIEW_GAMES = [
  { value: 'tenhalf', label: '十点半' },
  { value: 'zjh', label: '炸金花' },
  { value: 'horse', label: '养马' },
  { value: 'lucky', label: '幸运轮盘' },
]

// 左侧分组：按游戏归类
const GROUPS = [
  { key: 'global', label: '全局设置', icon: '⚙️' },
  { key: 'horse', label: '养马', icon: '🐴' },
  { key: 'zjh', label: '炸金花', icon: '🃏' },
  { key: 'tenhalf', label: '十点半', icon: '🎲' },
  { key: 'lucky', label: '幸运轮盘', icon: '🎰' },
  { key: 'ai', label: 'AI 评价', icon: '🤖' },
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
            <div class="card-h">掉落配额守卫</div>
            <label class="row switch">
              <input v-model="cfg.drop_guard_enabled" type="checkbox" />
              <span>掉落满时暂停游戏参与</span>
            </label>
            <span class="help" style="margin-top:-4px">
              定期私聊天空小秘发 /info 查「当前时段剩余掉落」，剩余为 0 时暂停十点半报名/炸金花入桌/赛马报名
              （养马喂食/遛马不受影响），时段刷新后自动恢复；状态切换会通知一次
            </span>
            <div class="fld">
              <span class="lbl">掉落检查间隔(分钟)</span>
              <input v-model.number="cfg.drop_guard_interval" class="inp" type="number" min="5" max="60" step="5" />
              <span class="help">多久私聊 bot 发一次 /info；越短对配额满的反应越快</span>
            </div>
            <div class="fld">
              <span class="lbl">掉落查询机器人</span>
              <input v-model="cfg.drop_guard_bot" class="inp" placeholder="@用户名 或 数字ID，留空=默认天空小秘" />
              <span class="help">/info 发给它查剩余掉落；独立于「目标与机器人」里的全局 bot 配置</span>
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
            <span class="help" style="margin-top:-4px">每轮最多一个动作：参赛补体力（先精草后仙草）→ 喂食额度 → 遛马 → 官方赛</span>
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
              <div class="fld">
                <span class="lbl">掉落控制</span>
                <label class="row switch">
                  <input v-model="cfg.horse_drop_guard" type="checkbox" />
                  <span>受游戏掉落控制</span>
                </label>
                <span class="help">默认关：掉落配额满时养马照常；勾选后参赛也随守卫暂停</span>
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
                <span class="lbl">体力阈值</span>
                <input v-model.number="cfg.horse_feed_threshold" class="inp" type="number" min="0" max="100" step="5" />
                <span class="help">体力低于此值才喂；优先配置草料，普通草冷却/额度用尽才喂仙草</span>
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
              <input v-model="cfg.horse_auto_match_race" type="checkbox" />
              <span>自动加入玩家养马赛</span>
            </label>
            <span class="help" style="margin-top:-4px">发现玩家开的 Horse2 时自动加入，报名额取房主设定</span>
            <div class="fld">
              <span class="lbl">参赛最低体力</span>
              <input v-model.number="cfg.horse_race_min_stamina" class="inp" type="number" min="0" max="100" step="5" />
              <span class="help">体力不够时喂一个仙草(+50)立即参赛（仙草每日 3 次）</span>
            </div>
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
              已看牌完全按期望收益（EV）决策：胜率 ×（底池 + 跟注成本）− 跟注成本 ≥ 0 即跟注，否则弃牌。
              胜率随剩余对手数衰减；已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛，再做条件胜率。
            </span>
            <span class="help" style="margin-top:8px">
              蒙牌用「终局 EV 决策树」：递归推演未来数轮对手的跟注/加注/弃牌，条件胜率随对手加注贝叶斯衰减，
              求到达摊牌/弃牌时的终局期望，再和看牌、弃牌比较。避免单步 EV 把「跟这手就摊牌」当事实——
              实际门户单挑对手可持续加注把底池滚大，蒙牌闭眼跟到强制摊牌常常巨亏。
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
                <span class="lbl">信号混合：{{ cfg.zjh_signal_mix_prob }}%</span>
                <input v-model.number="cfg.zjh_signal_mix_prob" type="range" min="0" max="50" step="5" />
                <span class="help">
                  双向混合防读牌：弱牌该开牌止损时小概率改跟注慢打、强牌该继续时小概率直接开牌——
                  对手统计不出「开牌=弱牌、继续=强牌」。0=关（旧行为：低于开牌阈值必开）。
                </span>
              </div>
              <div class="fld">
                <label class="row switch">
                  <input v-model="cfg.zjh_raise_enabled" type="checkbox" />
                  <span>启用高胜率主动追加</span>
                </label>
                <span class="help">正 EV 且最终实际胜率达到阈值时，若允许 raise 则追加。</span>
                <span class="lbl">最低实际胜率：{{ cfg.zjh_raise_min_win_rate }}%</span>
                <input v-model.number="cfg.zjh_raise_min_win_rate" type="range" min="5" max="100" step="5" />
                <template v-if="cfg.zjh_raise_enabled">
                  <span class="lbl">达标加注频率：{{ cfg.zjh_raise_frequency }}%</span>
                  <input v-model.number="cfg.zjh_raise_frequency" type="range" min="0" max="100" step="5" />
                  <span class="help">达阈值时按此概率加注、其余慢打平跟做伪装；100=达标必加。</span>
                  <label class="row switch">
                    <input v-model="cfg.zjh_first_peek_no_raise" type="checkbox" />
                    <span>第一次看牌不加注（慢打留人）</span>
                  </label>
                  <span class="help">本局首次看牌即使达阈值也平跟不加注，避免吓退对手；后续轮次才按频率加注。</span>
                </template>
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
            <div class="card-h">对手范围与反诈唬（画像自动驱动）</div>
            <span class="help">
              看牌后评估胜率时，对手手牌范围与反诈唬全部由对手画像自动推断，无需手动设置：
              加注对手按实测加注牌力下限估计，平跟对手永不封顶（可能慢打坚果牌）；
              继续频率异常高的对手自动计入诈唬概率。无画像对手按推断门槛、不反诈唬。
            </span>
            <div class="fld">
              <span class="lbl">弃牌 EV 容差：{{ cfg.zjh_fold_ev_tolerance }}% callBet</span>
              <input v-model.number="cfg.zjh_fold_ev_tolerance" type="range" min="0" max="30" step="1" />
              <span class="help">跟注 EV 只是略负（≥ −此比例×callBet）时不弃牌。0% = 旧行为（EV&lt;0 即弃）。</span>
            </div>
            <div class="fld">
              <span class="lbl">画像半衰期：{{ cfg.zjh_profile_halflife }} 手</span>
              <input v-model.number="cfg.zjh_profile_halflife" type="range" min="0" max="200" step="5" />
              <span class="help">
                画像按对手已完成手数衰减：每结算一手，历史计数与手牌样本权重减半（半衰期手数见上）。
                高频对手自然衰减快、低频慢；0 = 不衰减（永久保留全部历史，旧行为）。
                手牌样本窗口自动跟随半衰期（3 个半衰期、最少 100 条），调大半衰期不会缩短真实记忆窗口。
              </span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">蒙牌决策（终局 EV 决策树）</div>
            <span class="help">
              蒙牌不再只看当前一步的期望收益，而是推演未来几轮：对手每轮跟/加/弃（概率来自对手画像），
              我方蒙牌胜率随对手连续加注衰减（门槛贝叶斯上调），求到达摊牌/弃牌的终局期望。
              连续盲跟过多会被强制看牌止损，避免像单步 EV 那样闭眼跟到强制摊牌巨亏。
            </span>
            <div class="fld">
              <span class="lbl">决策树深度：{{ cfg.zjh_terminal_depth }} 轮</span>
              <input v-model.number="cfg.zjh_terminal_depth" type="range" min="1" max="3" step="1" />
              <span class="help">推演未来 N 轮对手动作再算终局 EV。1 = 退回旧单步 EV 行为。</span>
            </div>
            <div class="fld">
              <span class="lbl">连续盲跟上限：{{ cfg.zjh_blind_max_calls }} 轮</span>
              <input v-model.number="cfg.zjh_blind_max_calls" type="range" min="0" max="10" step="1" />
              <span class="help">蒙牌连续盲跟达该轮数后强制看牌止损。0 = 不限，纯按终局 EV。</span>
            </div>
            <label class="row switch">
              <input v-model="cfg.zjh_profile_enabled" type="checkbox" />
              <span>启用对手画像</span>
            </label>
            <span class="help">按玩家 ID 跨局统计每个对手的动作频率与实测手牌分位：决策树据此预测动作，已看牌胜率据此定对手范围与反诈唬。未知对手用全局先验、不反诈唬。</span>
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

        <!-- ============ 十点半 ============ -->
        <template v-else-if="group === 'tenhalf'">
          <h3 class="det-title">十点半</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.tenhalf_enabled" type="checkbox" />
              <span>启用自动参与</span>
            </label>
            <span class="help" style="margin-top:-4px">
              有桌开局时报名下注 → 抓牌阶段要牌/停牌 → 结算推送战绩。只玩玩家位不开庄。
              动作契约来自门户前端尚未实测，首次启用建议同时开启「全局设置 · 门户调试记录」核对
            </span>
            <div class="grid">
              <div class="fld">
                <span class="lbl">轮询间隔(秒)</span>
                <input v-model.number="cfg.tenhalf_poll_interval" class="inp" type="number" min="2" max="60" step="1" />
                <span class="help">报名阶段有倒计时，轮询太慢会错过报名</span>
              </div>
              <div class="fld">
                <span class="lbl">十点半通知</span>
                <label class="row switch">
                  <input v-model="cfg.tenhalf_notify" type="checkbox" />
                  <span>报名/结算推送</span>
                </label>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-h">参与策略</div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">报名下注额</span>
                <input v-model.number="cfg.tenhalf_bet_amount" class="inp" type="number" min="100" max="10000" step="100" />
                <span class="help">自动夹在门户最小下注与本桌单人上限之间</span>
              </div>
              <div class="fld">
                <span class="lbl">停牌点数阈值（基准）</span>
                <input v-model.number="cfg.tenhalf_stand_threshold" class="inp" type="number" min="4" max="10" step="0.5" />
                <span class="help">仅画像样本不足时的回退基准；样本足够时走 EV 决策（停牌 EV 对要牌 EV 递推择优）</span>
              </div>
            </div>
            <span class="help">
              决策优先序：庄家爆牌→停牌 ｜ 我方/庄家五小→立即停牌 ｜ 庄家画像样本足够→EV 决策：
              按画像点数分布+爆率算停牌 EV，对比 52 张先验递推的要牌 EV（含五小 ×5），择优要/停，
              张数是一等公民（4 张低点数追五小、高点数早停）｜ 画像不足→退停牌阈值。
              从不认输（fold 与停牌同样损失下注）
            </span>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 幸运轮盘 ============ -->
        <template v-else-if="group === 'lucky'">
          <h3 class="det-title">幸运轮盘</h3>

          <section class="card">
            <div class="card-h">免费抽奖</div>
            <label class="row switch">
              <input v-model="cfg.lucky_enabled" type="checkbox" />
              <span>每天自动抽掉免费次数</span>
            </label>
            <span class="help" style="margin-top:-4px">免费次数由当日随机掉落累计兑换，当天不用隔天作废</span>
            <div class="grid">
              <div class="fld">
                <span class="lbl">每日抽奖时刻</span>
                <input v-model="cfg.lucky_draw_time" class="inp" type="text" placeholder="23:50" />
                <span class="help">格式 HH:MM，到点后的第一次检查执行，当天只抽一次</span>
              </div>
            </div>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ AI 评价 ============ -->
        <template v-else-if="group === 'ai'">
          <h3 class="det-title">AI 评价（心路历程）</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.ai_review_enabled" type="checkbox" />
              <span>启用 AI 评价</span>
            </label>
            <span class="help" style="margin-top:-4px">
              各游戏结算/结果后用平台 AI 在群聊总结心路历程：赢了炫耀决策、输了吐槽对手运气好，
              不会出现 EV 数值；平台未接入 AI 时自动跳过
            </span>
            <div class="fld">
              <span class="lbl">评价的游戏（各游戏独立开关）</span>
              <div class="ai-check-group">
                <label v-for="g in AI_REVIEW_GAMES" :key="g.value" class="row switch ai-check">
                  <input
                    type="checkbox"
                    :value="g.value"
                    v-model="cfg.ai_review_games"
                  />
                  <span>{{ g.label }}</span>
                </label>
              </div>
              <span class="help">勾选哪些游戏结算后生成 AI 评价消息</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">发送目标</div>
            <div class="fld">
              <span class="lbl">发送到的群（一行一个ID）</span>
              <textarea v-model="cfg.ai_review_groups" class="inp" rows="3" spellcheck="false"></textarea>
              <span class="help">支持 -100 开头数字 ID 或 @用户名；留空=走通知中心原渠道（管理员私聊）</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">提示词模板</div>
            <div class="fld">
              <textarea v-model="cfg.ai_review_prompt" class="inp" rows="4" spellcheck="false"></textarea>
              <span class="help">
                已预填内置默认模板，可自由修改；占位符：{'{game}'} 游戏名、{'{actions}'} 动作序列、
                {'{opponent}'} 对手简称、{'{result}'} 结果文本、{'{tone}'} 语气指令（按输赢自动生成）；留空也等价于默认模板
              </span>
              <div class="row" style="justify-content:flex-end">
                <button class="btn" @click="cfg.ai_review_prompt = DEFAULT_AI_REVIEW_PROMPT">恢复默认模板</button>
              </div>
            </div>
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
.ai-check-group { display: flex; flex-wrap: wrap; gap: 8px 18px; }
.ai-check { gap: 6px; }
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
