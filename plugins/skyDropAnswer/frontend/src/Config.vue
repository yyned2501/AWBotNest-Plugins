<script setup>
// 天空答题 · 配置界面
// host.getConfig() / host.saveConfig() / host.callApi()
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
})

const DEFAULTS = {
  enable_reward_answer: false,
  reward_bot_ids: '',
  reward_delay_min: 2,
  reward_delay_max: 5,
  use_ai_fallback: true,
  enable_template_learning: true,
}

const GROUPS = [
  { key: 'reward', label: '答题奖励' },
  { key: 'templates', label: '学习模板' },
]

const group = ref('reward')
const loading = ref(true)
const saving = ref(false)
const cfg = reactive({ ...DEFAULTS })
const templates = ref([])
const tplLoading = ref(false)

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
        <!-- ============ 答题奖励 ============ -->
        <template v-if="group === 'reward'">
          <h3 class="det-title">答题奖励</h3>

          <section class="card">
            <div class="card-h">基础设置</div>
            <label class="row switch">
              <input v-model="cfg.enable_reward_answer" type="checkbox" />
              <span>开启答题奖励</span>
            </label>
            <div class="fld">
              <span class="lbl">答题机器人</span>
              <input v-model="cfg.reward_bot_ids" class="inp" placeholder="@机器人用户名，逗号分隔" />
              <span class="help">@机器人用户名，逗号分隔。留空=不限</span>
            </div>
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

        <!-- ============ 学习模板 ============ -->
        <template v-else-if="group === 'templates'">
          <h3 class="det-title">学习模板</h3>
          <div class="card">
            <div class="card-h" style="display:flex;justify-content:space-between;align-items:center">
              <span>已学模板（{{ templates.length }}）</span>
              <button v-if="templates.length > 0" class="btn sm danger" @click="clearTemplates">清空全部</button>
            </div>

            <div v-if="tplLoading" class="muted">加载中…</div>
            <div v-else-if="templates.length === 0" class="muted" style="padding:24px 0;text-align:center">
              暂无学习模板<br />
              <span style="font-size:12px;color:#7a8291">AI智能答题后自动生成，下次同类题直接命中</span>
            </div>
            <div v-else class="tpl-list">
              <div v-for="tpl in templates" :key="tpl.id" class="tpl-card">
                <div class="tpl-header">
                  <span class="tpl-type">{{ tpl.type || '未知' }}</span>
                  <span class="tpl-count">命中 {{ tpl.count || 0 }} 次</span>
                  <button class="btn xs" @click="deleteTemplate(tpl)">删除</button>
                </div>
                <div class="tpl-row">
                  <span class="tpl-label">正则</span>
                  <code class="tpl-regex">{{ tpl.regex }}</code>
                </div>
                <div class="tpl-row">
                  <span class="tpl-label">示例</span>
                  <span class="tpl-sample">{{ tpl.sample || '—' }}</span>
                </div>
                <div class="tpl-row">
                  <span class="tpl-label">答案</span>
                  <span class="tpl-answer">{{ tpl.answer || '—' }}</span>
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

/* 模板卡片 */
.tpl-list { display: flex; flex-direction: column; gap: 8px; }
.tpl-card {
  display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 8px;
  background: var(--bg-card, #12141c); border: 1px solid var(--border-light, #2a2e3a);
}
.tpl-header { display: flex; align-items: center; gap: 8px; }
.tpl-type {
  font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
  background: var(--accent-dim, #1e3a5f); color: var(--accent, #6ea8fe);
}
.tpl-count { font-size: 12px; color: var(--text-muted, #7a8291); margin-left: auto; }
.tpl-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; }
.tpl-label { color: var(--text-muted, #7a8291); flex: 0 0 40px; }
.tpl-regex {
  flex: 1; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; color: #b5bd68; word-break: break-all; line-height: 1.5;
}
.tpl-sample { flex: 1; color: var(--text-secondary, #b9c0cc); word-break: break-all; }
.tpl-answer { flex: 1; color: var(--text-primary, #e8ebf0); font-weight: 600; }

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