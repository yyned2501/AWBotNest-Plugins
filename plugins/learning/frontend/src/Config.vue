<script setup>
// learning 插件 · 配置界面（模块联邦暴露为 ./Config，见 vite.config 的 exposes）。
// 平台运行时加载本组件并注入两个 prop：
//   pluginId: 本插件 id
//   host: 平台能力对象
//     host.getConfig()         读取本插件已保存配置（Promise<对象>）
//     host.saveConfig(values)  保存配置（Promise）——存平台统一存储，插件里 ctx.config 可读到
//     host.toast.success/error(msg)  弹平台提示
// 本插件没有后端 API（无 ctx.on_api），故不使用 host.callApi。
// 布局：左侧分组导航 + 右侧明细（master-detail），窄容器时侧栏收为横排 chips。
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  pluginId: { type: String, required: true },
  host: { type: Object, required: true },
})

// 默认配置（与 src/main.js 的 mock 保持一致）
const DEFAULTS = {
  api_key: '', base_url: '', model: 'gpt-3.5-turbo',
  summarize_gap: 10, max_context_lines: 5,
  target_groups: '',
  enable_participation: true, participation_rate: 20,
  participation_context_lines: 5, min_participation_gap: 60, participation_msg_gap: 5,
  keywords: '', max_keywords: 20, keyword_display: '',
  profile_display: '', profile_prompt_template: '',
}

// 左侧分组导航。en=对应启用开关键（有则显示启用小圆点）。
const GROUPS = [
  { key: 'api', label: '接口' },
  { key: 'learn', label: '学习' },
  { key: 'groups', label: '群组' },
  { key: 'participation', label: '参与', en: 'enable_participation' },
  { key: 'keywords', label: '关键词' },
  { key: 'profile', label: '身份模拟' },
]

const group = ref('api')
const loading = ref(true)
const saving = ref(false)
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
          <span v-if="g.en && cfg[g.en]" class="dot" title="已启用"></span>
        </button>
      </aside>

      <div class="detail">
        <!-- ============ 接口 ============ -->
        <template v-if="group === 'api'">
          <h3 class="det-title">接口</h3>
          <section class="card">
            <div class="card-h">LLM 接口（OpenAI 兼容）</div>
            <div class="fld">
              <span class="lbl">API Key</span>
              <input v-model="cfg.api_key" class="inp" type="password" placeholder="sk-…" autocomplete="off" />
              <span class="help">OpenAI 兼容接口的密钥</span>
            </div>
            <div class="fld">
              <span class="lbl">接口地址(Base URL)</span>
              <input v-model="cfg.base_url" class="inp" type="text" placeholder="https://api.openai.com/v1" />
              <span class="help">OpenAI 兼容接口地址，留空用官方默认</span>
            </div>
            <div class="fld">
              <span class="lbl">模型</span>
              <input v-model="cfg.model" class="inp" type="text" placeholder="gpt-3.5-turbo" />
              <span class="help">用于关键词风格分析和参与回复</span>
            </div>
          </section>
        </template>

        <!-- ============ 学习 ============ -->
        <template v-else-if="group === 'learn'">
          <h3 class="det-title">学习</h3>
          <section class="card">
            <div class="card-h">自动总结</div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">总结间隔(条)</span>
                <input v-model.number="cfg.summarize_gap" class="inp" type="number" min="3" max="100" />
                <span class="help">每发这么多条消息就总结一次</span>
              </div>
              <div class="fld">
                <span class="lbl">总结上下文行数</span>
                <input v-model.number="cfg.max_context_lines" class="inp" type="number" min="1" max="20" />
                <span class="help">总结时读取每条消息前 N 条上下文</span>
              </div>
            </div>
          </section>
        </template>

        <!-- ============ 群组 ============ -->
        <template v-else-if="group === 'groups'">
          <h3 class="det-title">群组</h3>
          <section class="card">
            <div class="card-h">监听范围</div>
            <div class="fld">
              <span class="lbl">监听群组</span>
              <textarea v-model="cfg.target_groups" class="inp" rows="5"
                        placeholder="每行一个群 ID&#10;也兼容逗号分隔&#10;留空 = 不监听任何群"></textarea>
              <span class="help">每个群 ID 一行，也兼容逗号分隔。留空=不监听</span>
            </div>
          </section>
        </template>

        <!-- ============ 参与 ============ -->
        <template v-else-if="group === 'participation'">
          <h3 class="det-title">参与</h3>
          <section class="card">
            <div class="card-h">智能参与</div>
            <label class="row switch">
              <input v-model="cfg.enable_participation" type="checkbox" />
              <span>启用智能参与</span>
            </label>
            <div v-if="cfg.enable_participation" class="grid">
              <div class="fld">
                <span class="lbl">参与概率(%)</span>
                <input v-model.number="cfg.participation_rate" class="inp" type="number" min="1" max="100" />
              </div>
              <div class="fld">
                <span class="lbl">参与时读取上文(条)</span>
                <input v-model.number="cfg.participation_context_lines" class="inp" type="number" min="1" max="20" />
              </div>
            </div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">发言冷却(秒)</span>
                <input v-model.number="cfg.min_participation_gap" class="inp" type="number" min="10" max="600" step="10" />
              </div>
              <div class="fld">
                <span class="lbl">消息条数间隔</span>
                <input v-model.number="cfg.participation_msg_gap" class="inp" type="number" min="1" max="50" />
              </div>
            </div>
          </section>
        </template>

        <!-- ============ 关键词 ============ -->
        <template v-else-if="group === 'keywords'">
          <h3 class="det-title">关键词</h3>
          <section class="card">
            <div class="card-h">关键词管理</div>
            <div class="fld">
              <span class="lbl">关键词（手动补充）</span>
              <textarea v-model="cfg.keywords" class="inp" rows="3"
                        placeholder="每行一个，或逗号分隔"></textarea>
              <span class="help">每行或逗号分隔，与自动学习的合并</span>
            </div>
            <div class="grid">
              <div class="fld">
                <span class="lbl">关键词上限</span>
                <input v-model.number="cfg.max_keywords" class="inp" type="number" min="5" max="100" step="5" />
              </div>
            </div>
            <div class="fld">
              <span class="lbl">已学关键词</span>
              <textarea class="inp ro" :value="cfg.keyword_display" readonly rows="4"
                        placeholder="（暂无，运行后自动学习）"></textarea>
              <span class="help">自动学习，按命中次数降序</span>
            </div>
          </section>
        </template>

        <!-- ============ 身份模拟 ============ -->
        <template v-else-if="group === 'profile'">
          <h3 class="det-title">身份模拟</h3>
          <section class="card">
            <div class="card-h">风格画像</div>
            <div class="fld">
              <span class="lbl">当前画像（自动累积）</span>
              <textarea class="inp ro" :value="cfg.profile_display" readonly rows="5"
                        placeholder="（暂无，学习后自动生成）"></textarea>
              <span class="help">每次学习后自动更新，仅供参考</span>
            </div>
            <div class="fld">
              <span class="lbl">画像总结模板</span>
              <textarea v-model="cfg.profile_prompt_template" class="inp mono" rows="12"
                        placeholder="留空 = 使用插件内置默认模板"></textarea>
              <span class="help">占位符: {context}=上下文, {my_messages}=我的发言</span>
            </div>
          </section>
        </template>

        <div class="savebar">
          <button class="btn primary lg" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 用平台主题变量（有则跟随暗色主题），带回退值以便本地 npm run dev 预览。
   container-type：让 @container 按「本组件(=配置弹窗)实际宽度」自适应，
   而非浏览器视口宽度——平台弹窗被 max-width 夹窄时也能正确收起侧栏。 */
.lcfg { display: flex; flex-direction: column; gap: 14px; container-type: inline-size; }

/* master-detail 布局 */
.layout { display: flex; gap: 16px; align-items: flex-start; }
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
.dot { width: 7px; height: 7px; border-radius: 50%; background: #6ee7a8; flex: 0 0 auto; }

.detail { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.det-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary, #e8ebf0); }

.card {
  display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 10px;
  background: var(--bg-elevated, #1a1d27); border: 1px solid var(--border-light, #2a2e3a);
}
.card-h { font-size: 13px; font-weight: 600; color: var(--accent, #6ea8fe); }

/* 表单自适应：窄容器单列，够宽才两列 */
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
.inp.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.inp.ro { color: var(--text-secondary, #b9c0cc); }

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

/* 弹窗较窄时：分组栏从左侧竖排改为顶部横排 chips，把整宽让给明细。 */
@container (max-width: 620px) {
  .layout { flex-direction: column; }
  .sidebar { flex-basis: auto; width: 100%; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }
  .side-title { display: none; }
  .side-item { flex: 0 1 auto; }
}
</style>
