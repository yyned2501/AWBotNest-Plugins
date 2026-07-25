<script setup>
// 大逃杀助手 · 配置界面（模块联邦暴露为 ./Config）
// 接收 pluginId 和 host 两个 prop。
// host.getConfig() / host.saveConfig() 读写配置
// host.callApi(path) 调用后端 API
import { ref, reactive, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
})

const DEFAULTS = {
  chat_id: '', bot_id: 8835151149,
  auto_bet: true, bet_timing: 5, bet_strategy: '少',
  notify_round: true, notify_summary: true,
}

const loading = ref(true)
const saving = ref(false)
const cfg = reactive({ ...DEFAULTS })
const status = ref(null)
const history = ref([])
const statusLoading = ref(false)
const historyLoading = ref(false)
let pollTimer = null

// ── 配置读写 ──

onMounted(async () => {
  try {
    const saved = await props.host.getConfig()
    Object.assign(cfg, DEFAULTS, saved || {})
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
  fetchStatus()
  fetchHistory()
  // 每 5 秒轮询状态
  pollTimer = setInterval(fetchStatus, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
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

// ── API 调用 ──

async function fetchStatus() {
  statusLoading.value = true
  try {
    const res = await props.host.callApi('/status')
    status.value = res
  } catch {
    // 静默失败，轮询不用每次都弹
  } finally {
    statusLoading.value = false
  }
}

async function fetchHistory() {
  historyLoading.value = true
  try {
    const res = await props.host.callApi('/history')
    history.value = res || []
  } catch (e) {
    props.host.toast.error('获取历史失败：' + (e.message || e))
  } finally {
    historyLoading.value = false
  }
}

async function forceBet() {
  try {
    await props.host.callApi('/force_bet', { method: 'POST' })
    props.host.toast.success('下注指令已发送')
    fetchStatus()
  } catch (e) {
    props.host.toast.error('下注失败：' + (e.message || e))
  }
}

async function resetGame() {
  try {
    await props.host.callApi('/reset', { method: 'POST' })
    props.host.toast.success('游戏状态已重置')
    fetchStatus()
  } catch (e) {
    props.host.toast.error('重置失败：' + (e.message || e))
  }
}

function fmtDeadline(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const now = Date.now()
  const diff = d.getTime() - now
  if (diff <= 0) return '已过期'
  const min = Math.floor(diff / 60000)
  const sec = Math.floor((diff % 60000) / 1000)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')} (剩余${min}分${sec}秒)`
}
</script>

<template>
  <div class="brcfg">
    <div v-if="loading" class="muted">加载配置…</div>
    <div v-else class="layout">

      <!-- ============ 左侧：实时状态 ============ -->
      <aside class="left-panel">
        <h3 class="panel-title">实时状态</h3>

        <section class="card">
          <div class="card-h">游戏状态</div>
          <div class="status-row">
            <span class="lbl">状态</span>
            <span v-if="status" :class="['tag', status.is_active ? 'active' : 'idle']">
              {{ status.is_active ? '进行中' : '空闲' }}
            </span>
            <span v-else class="tag idle">未知</span>
          </div>
          <div v-if="status && status.is_active" class="status-detail">
            <div class="status-row">
              <span class="lbl">当前圈数</span>
              <span class="val">第{{ status.round }}圈</span>
            </div>
            <div class="status-row">
              <span class="lbl">选项</span>
              <span class="val">{{ status.options?.join(' / ') || '—' }}</span>
            </div>
            <div class="status-row">
              <span class="lbl">投票统计</span>
              <span class="val">
                <template v-if="status.votes && Object.keys(status.votes).length">
                  <span v-for="(cnt, opt) in status.votes" :key="opt" class="vote-chip">
                    {{ opt }}: {{ cnt }}票
                  </span>
                </template>
                <span v-else>暂无投票</span>
              </span>
            </div>
            <div class="status-row">
              <span class="lbl">结算时间</span>
              <span class="val">{{ fmtDeadline(status.deadline_ts) }}</span>
            </div>
            <div class="status-row">
              <span class="lbl">自动下注</span>
              <span :class="['tag', status.bet_placed ? 'done' : 'wait']">
                {{ status.bet_placed ? '已下注' : '等待中' }}
              </span>
            </div>
          </div>
          <div v-else class="status-row">
            <span class="val muted">等待游戏开始…</span>
          </div>
          <div v-if="status && status.is_active" class="action-row">
            <button class="btn sm" @click="forceBet">手动下注</button>
            <button class="btn sm danger" @click="resetGame">重置</button>
          </div>
        </section>

        <!-- ============ 历史记录 ============ -->
        <section class="card">
          <div class="card-h">
            历史记录
            <button class="btn sm" @click="fetchHistory" :disabled="historyLoading">刷新</button>
          </div>
          <div v-if="history.length === 0" class="muted">暂无记录</div>
          <div v-else class="hist-list">
            <div v-for="h in [...history].reverse()" :key="h.round + h.time" class="hist-item">
              <span class="hist-round">第{{ h.round }}圈</span>
              <span class="hist-result">结果: {{ h.result }}</span>
              <span v-if="h.mutation" class="hist-mut">基因突变</span>
              <span class="hist-votes">
                {{ Object.entries(h.votes).map(([k, v]) => `${k}=${v}`).join(' ') }}
              </span>
            </div>
          </div>
        </section>
      </aside>

      <!-- ============ 右侧：配置区 ============ -->
      <div class="right-panel">
        <h3 class="panel-title">配置</h3>

        <!-- 监听 -->
        <section class="card">
          <div class="card-h">监听</div>
          <div class="fld">
            <span class="lbl">监听群组</span>
            <input v-model="cfg.chat_id" class="inp" type="text" placeholder="如 -1003808371287" />
            <span class="help">监听的群组 chat_id</span>
          </div>
          <div class="fld">
            <span class="lbl">游戏 Bot ID</span>
            <input v-model.number="cfg.bot_id" class="inp" type="number" />
            <span class="help">@NextFunBot 的 user_id</span>
          </div>
        </section>

        <!-- 自动下注 -->
        <section class="card">
          <div class="card-h">自动下注</div>
          <label class="row switch">
            <input v-model="cfg.auto_bet" type="checkbox" />
            <span>启用自动下注</span>
          </label>
          <div v-if="cfg.auto_bet" class="grid">
            <div class="fld">
              <span class="lbl">结算前下注(秒)</span>
              <input v-model.number="cfg.bet_timing" class="inp" type="number" min="0" max="30" />
              <span class="help">距结算多少秒时下注</span>
            </div>
            <div class="fld">
              <span class="lbl">下注策略</span>
              <select v-model="cfg.bet_strategy" class="inp">
                <option value="少">人少（以少胜多规则）</option>
                <option value="多">人多（跟风策略）</option>
              </select>
            </div>
          </div>
        </section>

        <!-- 通知 -->
        <section class="card">
          <div class="card-h">通知</div>
          <label class="row switch">
            <input v-model="cfg.notify_round" type="checkbox" />
            <span>每圈结算通知</span>
          </label>
          <label class="row switch">
            <input v-model="cfg.notify_summary" type="checkbox" />
            <span>游戏结束总结</span>
          </label>
        </section>

        <div class="savebar">
          <button class="btn primary lg" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存配置' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.brcfg { display: flex; flex-direction: column; gap: 14px; container-type: inline-size; min-height: 100%; }

.layout { display: flex; gap: 16px; align-items: flex-start; min-height: 100%; }

/* 左状态 / 右配置 */
.left-panel { flex: 0 0 340px; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.right-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }

.panel-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary, #e8ebf0); }

.card {
  display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 10px;
  background: var(--bg-elevated, #1a1d27); border: 1px solid var(--border-light, #2a2e3a);
}
.card-h {
  font-size: 13px; font-weight: 600; color: var(--accent, #6ea8fe);
  display: flex; align-items: center; justify-content: space-between;
}

.status-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.status-detail { display: flex; flex-direction: column; gap: 8px; }
.lbl { color: var(--text-muted, #7a8291); flex: 0 0 auto; }
.val { color: var(--text-primary, #e8ebf0); }
.val.muted { color: var(--text-muted, #7a8291); }

.tag {
  font-size: 11px; padding: 2px 10px; border-radius: 10px; font-weight: 600;
  display: inline-block;
}
.tag.active { background: #1a3a2a; color: #6ee7a8; }
.tag.idle { background: #2a2e3a; color: #7a8291; }
.tag.done { background: #1a3a2a; color: #6ee7a8; }
.tag.wait { background: #3a2a1a; color: #fbbf24; }

.vote-chip { display: inline-block; padding: 2px 8px; border-radius: 6px; background: var(--bg-card, #12141c); margin: 2px; }

.action-row { display: flex; gap: 8px; margin-top: 4px; }

/* 历史记录 */
.hist-list { display: flex; flex-direction: column; gap: 6px; max-height: 300px; overflow-y: auto; }
.hist-item {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  padding: 8px; border-radius: 6px; font-size: 12px;
  background: var(--bg-card, #12141c);
}
.hist-round { color: var(--accent, #6ea8fe); font-weight: 600; }
.hist-result { color: var(--text-primary, #e8ebf0); }
.hist-mut { color: #fbbf24; font-size: 11px; }
.hist-votes { color: var(--text-muted, #7a8291); }

/* 表单 */
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px 20px; }
.fld { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
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
select.inp { cursor: pointer; }

.btn {
  padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  background: var(--bg-card, #12141c); color: var(--text-secondary, #b9c0cc);
  border: 1px solid var(--border-light, #2a2e3a);
  transition: border-color 0.15s, color 0.15s;
}
.btn:hover { border-color: var(--accent, #6ea8fe); color: var(--accent, #6ea8fe); }
.btn.sm { padding: 4px 10px; font-size: 12px; }
.btn.danger:hover { border-color: #f87171; color: #f87171; }
.btn.primary { background: var(--accent-dim, #1e3a5f); border-color: var(--accent, #6ea8fe); color: var(--accent, #6ea8fe); }
.btn.lg { padding: 9px 22px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.savebar { display: flex; justify-content: flex-end; padding-top: 4px; }

.muted { font-size: 12px; color: var(--text-muted, #7a8291); }

/* 窄屏自适应 */
@container (max-width: 720px) {
  .layout { flex-direction: column; }
  .left-panel { flex-basis: auto; width: 100%; }
  .right-panel { width: 100%; }
  .grid { grid-template-columns: 1fr; }
  .inp[type='number'] { max-width: none; width: 100%; }
  .savebar { justify-content: stretch; }
  .savebar .btn.lg { width: 100%; text-align: center; }
}

@container (max-width: 380px) {
  .card { padding: 12px; }
  .inp { padding: 7px 8px; }
}
</style>