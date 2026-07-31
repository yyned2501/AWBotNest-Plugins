<script setup>
// 天空答题 · 配置界面
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
  trig_jitter_max: 30,
  trig_active_start: 8,
  trig_active_end: 23,
  trig_info_timeout: 60,
  trig_drop_timeout: 120,
  trig_use_info: true,
  trig_message_template: '第{n}题{x}',
  trig_stats: '',
}

const GROUPS = [
  { key: 'global', label: '全局设置' },
  { key: 'trigger', label: '自动触发' },
  { key: 'reward', label: '自动答题' },
  { key: 'templates', label: '学习模板' },
]

const group = ref('global')
const loading = ref(true)
const saving = ref(false)
const cfg = reactive({ ...DEFAULTS })
const templates = ref([])
const tplLoading = ref(false)
// 模板编辑态
const editingId = ref(null)
const editSaving = ref(false)
const editError = ref('')
const editForm = reactive({ regex: '', script_code: '' })

onMounted(async () => {
  try {
    const saved = await props.host.getConfig()
    Object.assign(cfg, DEFAULTS, saved || {})
  } catch (e) {
    props.host.toast.error('读取配置失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
  loadTemplates()
})

async function loadTemplates() {
  tplLoading.value = true
  try {
    const res = await props.host.callApi('/api/templates')
    templates.value = (res && res.data) || []
  } catch (e) {
    props.host.toast.error('加载模板失败：' + (e.message || e))
  } finally {
    tplLoading.value = false
  }
}

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

async function deleteTemplate(tpl) {
  try {
    await props.host.callApi('/api/templates', {
      method: 'DELETE',
      body: { id: tpl.id },
    })
    props.host.toast.success('已删除')
    loadTemplates()
  } catch (e) {
    props.host.toast.error('删除失败：' + (e.message || e))
  }
}

async function clearTemplates() {
  try {
    await props.host.callApi('/api/templates/clear', { method: 'POST' })
    props.host.toast.success('已清空')
    loadTemplates()
  } catch (e) {
    props.host.toast.error('清空失败：' + (e.message || e))
  }
}

function isBuiltin(tpl) {
  return String(tpl.id || '').startsWith('builtin_')
}

function startEdit(tpl) {
  editingId.value = tpl.id
  editError.value = ''
  editForm.regex = tpl.regex || ''
  editForm.script_code = tpl.script_code || ''
}

function cancelEdit() {
  editingId.value = null
  editError.value = ''
}

async function saveEdit(tpl) {
  editSaving.value = true
  editError.value = ''
  try {
    const res = await props.host.callApi('/api/templates/save', {
      method: 'POST',
      body: { id: tpl.id, regex: editForm.regex, script_code: editForm.script_code },
    })
    if (res && res.ok) {
      props.host.toast.success(res.message || '已保存')
      editingId.value = null
      loadTemplates()
    } else {
      editError.value = (res && res.message) || '保存失败'
    }
  } catch (e) {
    editError.value = e.message || String(e)
  } finally {
    editSaving.value = false
  }
}
</script>

<template>
  <div class="lcfg">
    <div v-if="loading" class="muted">加载配置…</div>
    <div v-else class="layout">
      <aside class="sidebar">
        <div class="side-title">设置分组</div>
        <button v-for="g in GROUPS" :key="g.key"
                :class="['side-item', { on: group === g.key }]" @click="group = g.key">
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
              <span class="help">触发消息发到这些群，一行一个（/info 校准走私聊 bot，不占群）</span>
            </div>
            <div class="fld">
              <span class="lbl">天空小秘机器人</span>
              <input v-model="cfg.bot" class="inp" placeholder="@用户名 或 数字ID，逗号分隔可填多个" />
              <span class="help">留空=默认天空小秘。答题过滤与掉落统计都认这个</span>
            </div>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 自动答题 ============ -->
        <template v-else-if="group === 'reward'">
          <h3 class="det-title">自动答题</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.enable_reward_answer" type="checkbox" />
              <span>开启自动答题</span>
            </label>
            <div class="grid">
              <div class="fld">
                <span class="lbl">延迟最小(秒)</span>
                <input v-model.number="cfg.reward_delay_min" class="inp" type="number" min="1" max="30" />
              </div>
              <div class="fld">
                <span class="lbl">延迟最大(秒)</span>
                <input v-model.number="cfg.reward_delay_max" class="inp" type="number" min="1" max="60" />
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-h">智能答题</div>
            <label class="row switch">
              <input v-model="cfg.use_ai_fallback" type="checkbox" />
              <span>AI智能答题</span>
            </label>
            <span class="help" style="margin-top:-4px">未知题型时使用AI分析并回答</span>
            <label class="row switch">
              <input v-model="cfg.enable_template_learning" type="checkbox" />
              <span>AI学习模板</span>
            </label>
            <span class="help" style="margin-top:-4px">AI答完题后自动提取模板，下次同类题直接脚本答</span>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 自动触发 ============ -->
        <template v-else-if="group === 'trigger'">
          <h3 class="det-title">自动触发</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.trig_enabled" type="checkbox" />
              <span>启用自动触发</span>
            </label>
            <span class="help" style="margin-top:-4px">开启时段内定时循环：/info 校准 → 发「第n题x」触发掉落 → 定时触发下一题</span>
            <span class="help" style="margin-top:-4px">每小时掉落目标自动从 /info 读取（私聊 bot，读「当前时段剩余掉落」），无需手动设置</span>
            <div class="fld">
              <span class="lbl">触发消息模板</span>
              <input v-model="cfg.trig_message_template" class="inp" placeholder="第{n}题{x}" />
              <span class="help">{n}=本小时题号 {x}=本题尝试次数</span>
            </div>
          </section>

          <section class="card">
            <div class="card-h">循环节奏</div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">触发窗口起始分</span>
                <input v-model.number="cfg.trig_start_min" class="inp" type="number" min="0" max="30" />
                <span class="help">每小时第几分开始触发</span>
              </div>
              <div class="fld">
                <span class="lbl">单题最大尝试次数</span>
                <input v-model.number="cfg.trig_max_attempts" class="inp" type="number" min="1" max="20" />
                <span class="help">超过就放弃该题</span>
              </div>
              <div class="fld">
                <span class="lbl">每几次未掉落查/info</span>
                <input v-model.number="cfg.trig_info_every" class="inp" type="number" min="0" max="10" />
                <span class="help">0=不检查</span>
              </div>
              <div class="fld">
                <span class="lbl">触发间隔(分钟)</span>
                <input v-model.number="cfg.trig_interval" class="inp" type="number" min="1" max="60" />
                <span class="help">一次触发完成后定时这么久再触发下一题</span>
              </div>
              <div class="fld">
                <span class="lbl">拟人延迟上限(秒)</span>
                <input v-model.number="cfg.trig_jitter_max" class="inp" type="number" min="0" max="120" />
                <span class="help">决定触发后随机延迟0~此值再发，0=不延迟</span>
              </div>
              <div class="fld">
                <span class="lbl">开启时段·开始(点)</span>
                <input v-model.number="cfg.trig_active_start" class="inp" type="number" min="0" max="23" />
                <span class="help">每天这个点起才触发</span>
              </div>
              <div class="fld">
                <span class="lbl">开启时段·结束(点)</span>
                <input v-model.number="cfg.trig_active_end" class="inp" type="number" min="0" max="23" />
                <span class="help">到这个点停止；开始>结束=跨午夜</span>
              </div>
              <div class="fld">
                <span class="lbl">/info等待超时(秒)</span>
                <input v-model.number="cfg.trig_info_timeout" class="inp" type="number" min="10" max="300" />
              </div>
              <div class="fld">
                <span class="lbl">等掉落超时(秒)</span>
                <input v-model.number="cfg.trig_drop_timeout" class="inp" type="number" min="30" max="600" />
                <span class="help">超时视为本次失败</span>
              </div>
            </div>
            <label class="row switch">
              <input v-model="cfg.trig_use_info" type="checkbox" />
              <span>发送/info校准</span>
            </label>
            <span class="help" style="margin-top:-4px">每小时私聊 bot 发 /info 校准；连续失败时也用它检查</span>
          </section>

          <section class="card">
            <div class="card-h">触发统计</div>
            <div class="stats-box">{{ cfg.trig_stats || '暂无统计（启用后自动刷新）' }}</div>
          </section>

          <div class="savebar">
            <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
          </div>
        </template>

        <!-- ============ 回答模板 ============ -->
        <template v-else-if="group === 'templates'">
          <h3 class="det-title">回答模板</h3>
          <div class="card">
            <div class="card-h tpl-bar">
              <span>模板（{{ templates.length }}）</span>
              <button v-if="templates.length > 0" class="btn sm danger" @click="clearTemplates">清空学习模板</button>
            </div>
            <p class="tpl-tip">AI 学会的与内置的模板都在此。正则匹配不上或答案不对时，点「编辑」直接微调正则与脚本，保存后立即生效。</p>

            <div v-if="tplLoading" class="muted">加载中…</div>
            <div v-else-if="templates.length === 0" class="muted empty">
              暂无模板<br />
              <span>AI 智能答题后自动生成，下次同类题直接命中</span>
            </div>
            <div v-else class="tpl-list">
              <div v-for="tpl in templates" :key="tpl.id" class="tpl-card" :class="{ editing: editingId === tpl.id }">
                <div class="tpl-header">
                  <span class="tpl-type">{{ tpl.type || '未知' }}</span>
                  <span class="badge" :class="tpl.status === 'verified' ? 'b-ok' : 'b-learn'">
                    {{ tpl.status === 'verified' ? '已验证' : '学习中' }}
                  </span>
                  <span v-if="isBuiltin(tpl)" class="badge b-builtin">内置</span>
                  <span class="tpl-count">命中 {{ tpl.count || 0 }}</span>
                  <span class="tpl-actions">
                    <button v-if="editingId !== tpl.id" class="btn xs" @click="startEdit(tpl)">编辑</button>
                    <button v-if="!isBuiltin(tpl) && editingId !== tpl.id" class="btn xs danger" @click="deleteTemplate(tpl)">删除</button>
                  </span>
                </div>

                <!-- 查看态 -->
                <template v-if="editingId !== tpl.id">
                  <div class="tpl-row">
                    <span class="tpl-label">正则</span>
                    <code class="tpl-regex">{{ tpl.regex }}</code>
                  </div>
                  <div class="tpl-row">
                    <span class="tpl-label">示例</span>
                    <span class="tpl-sample">{{ (tpl.sample || '—').replace(/\n/g, ' ⏎ ') }}</span>
                  </div>
                </template>

                <!-- 编辑态 -->
                <div v-else class="editor">
                  <label class="ed-fld">
                    <span class="ed-lbl">正则表达式</span>
                    <input v-model="editForm.regex" class="inp mono" spellcheck="false" />
                  </label>
                  <label class="ed-fld">
                    <span class="ed-lbl">提取脚本 extract(text) —— 返回字符串答案</span>
                    <textarea v-model="editForm.script_code" class="inp mono code" rows="9" spellcheck="false"></textarea>
                  </label>
                  <div v-if="editError" class="ed-error">⚠ {{ editError }}</div>
                  <div class="ed-bar">
                    <button class="btn sm" :disabled="editSaving" @click="cancelEdit">取消</button>
                    <button class="btn sm primary" :disabled="editSaving" @click="saveEdit(tpl)">
                      {{ editSaving ? '校验保存中…' : '保存' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
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
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; border-radius: 8px; border: none; cursor: pointer; text-align: left;
  background: none; color: var(--text-secondary, #b9c0cc); font-size: 13px;
  transition: background 0.15s, color 0.15s;
}
.side-item:hover { background: var(--bg-card, #12141c); }
.side-item.on { background: var(--accent-dim, #1e3a5f); color: var(--accent, #6ea8fe); }

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
.btn.sm { padding: 5px 10px; font-size: 12px; }
.btn.xs { padding: 3px 8px; font-size: 11px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.danger { border-color: #e5534b; color: #e5534b; }
.btn.danger:hover { background: #2d1b1a; }
.savebar { position: sticky; bottom: 0; display: flex; justify-content: flex-end; padding-top: 4px; }
.muted { font-size: 12px; color: var(--text-muted, #7a8291); }
.stats-box {
  font-size: 12px; line-height: 1.8; white-space: pre-line;
  color: var(--text-secondary, #b9c0cc);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* 模板卡片 */
.tpl-bar { display: flex; justify-content: space-between; align-items: center; }
.tpl-tip { margin: 0; font-size: 12px; color: var(--text-muted, #7a8291); line-height: 1.6; }
.empty { padding: 24px 0; text-align: center; }
.empty span { font-size: 12px; color: #7a8291; }
.tpl-list { display: flex; flex-direction: column; gap: 8px; }
.tpl-card {
  display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 8px;
  background: var(--bg-card, #12141c); border: 1px solid var(--border-light, #2a2e3a);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.tpl-card.editing { border-color: var(--accent, #6ea8fe); box-shadow: 0 0 0 1px var(--accent-dim, #1e3a5f); }
.tpl-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tpl-type {
  font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
  background: var(--accent-dim, #1e3a5f); color: var(--accent, #6ea8fe);
}
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; font-weight: 500; }
.b-ok { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
.b-learn { background: rgba(210, 153, 34, 0.15); color: #d29922; }
.b-builtin { background: rgba(110, 168, 254, 0.15); color: #6ea8fe; }
.tpl-count { font-size: 12px; color: var(--text-muted, #7a8291); }
.tpl-actions { margin-left: auto; display: flex; gap: 6px; }
.tpl-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; }
.tpl-label { color: var(--text-muted, #7a8291); flex: 0 0 40px; }
.tpl-regex {
  flex: 1; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; color: #b5bd68; word-break: break-all; line-height: 1.5;
}
.tpl-sample { flex: 1; color: var(--text-secondary, #b9c0cc); word-break: break-all; }

/* 模板编辑器 */
.editor {
  display: flex; flex-direction: column; gap: 10px; margin-top: 4px;
  padding-top: 12px; border-top: 1px dashed var(--border-light, #2a2e3a);
}
.ed-fld { display: flex; flex-direction: column; gap: 6px; }
.ed-lbl { font-size: 12px; color: var(--text-secondary, #b9c0cc); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.code { resize: vertical; line-height: 1.55; font-size: 12.5px; white-space: pre; overflow: auto; tab-size: 4; }
.ed-error {
  font-size: 12px; color: #e5534b; background: rgba(229, 83, 75, 0.1);
  border: 1px solid rgba(229, 83, 75, 0.3); padding: 6px 10px; border-radius: 6px;
  white-space: pre-wrap; word-break: break-all;
}
.ed-bar { display: flex; justify-content: flex-end; gap: 8px; }

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