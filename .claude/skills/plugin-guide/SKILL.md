---
name: plugin-guide
version: 3
description: >-
  Use this skill whenever you write, modify, review, or debug an AWBotNest plugin.
  Single authoritative plugin-authoring skill for this repo — consolidates the platform
  docs (PLUGIN_GUIDE/SPEC/API) and the official awbotnest-plugin-development &
  awbotnest-plugin-pitfalls skills. Covers the workflow (what to read first, local-first
  debugging, spec vs current-repo practice), the plugin contract, the full ctx interface,
  config_schema (all 12 field types), Vue mode, webhook/on_api, browser & AI,
  requirements/deps, group isolation, multi-Bot routing, account scope, and marketplace
  publishing. Load it for ANY task touching AWBotNest plugin code. On-demand references:
  references/pitfalls.md (common pitfalls + checklist — read when debugging),
  references/platform-api.md (remote-manage a live instance: enable/reload/config/kv/
  logs/send), references/minimal-plugin-template.py (starter plugin).
---

# AWBotNest 插件开发

AWBotNest 是「**平台内核 + 单文件插件**」的 Telegram 机器人平台（Python 3.13 + Pyrogram(kurigram) + FastAPI + Vue3）。内核只提供能力，**所有业务功能都是插件**：一个功能 = 一个 `.py` 文件或一个目录包，前端勾选启用即生效，停用即卸载，全程不重启进程。

> 一句话：**想要啥功能，写一个文件丢进去，勾选启用，完事。**

本仓库 `AWdress/AWBotNest-Plugins` 是平台**内置的官方插件市场仓库**——它自动出现在每个平台的「插件商店」里。在此仓库写插件，除了符合插件契约，还要遵守仓库规则（见文末「本仓库专属规则」）。

---

## 0. 工作方式（动手前必读）

**先读这些，再改插件代码**（按序）：
1. 本仓库 `docs/PLUGIN_GUIDE.md`（插件教程）与 `docs/SPEC.md`(规范)——插件契约与可用 API 的权威来源；
2. `plugins/_TEMPLATE.py`（或 `plugins/_TEMPLATE_VUE/`，见 `references/minimal-plugin-template.py`）；
3. 本仓库 `README.md`；
4. **目标插件 + 1–3 个相似的在用插件**——复用已验证的触发/过滤/配置模式；
5. 发布到本仓库时再看 `manifest.json`。

**当运行行为与记忆不符，优先信插件指南与模板**，别从平台内核反推插件规则。

**本地优先调试**：用户在已安装实例上迭代某插件时，默认先改运行实例上的副本（`<平台>/plugins/...`）调试验证；只有用户明确要求发布、或任务本就是发布时，才同步回本仓库。远程操作运行实例用平台开放 API（`references/platform-api.md`）。

**区分「规范硬规则」与「当前仓库实践」**：插件指南/模板写明的是硬规则；某个插件里看到的具体写法（尤其 AI 相关、命令触发风格、图标用法）可能只是当前仓库的做法，不一定可推广。拿不准时先看在用插件怎么做，别把仓库个例当成官方规范。

**调试先查坑清单**：加载失败、命令无响应、配置漂移、热重载异常 → 读 `references/pitfalls.md`。

---

## 1. 一分钟上手

1. 复制 `plugins/_TEMPLATE.py`（Vue 界面用 `plugins/_TEMPLATE_VUE/`），改名为插件名（如 `my_feature.py`）。
2. 改顶部 `__plugin__` 字典，`id` 必须 = 文件名（去扩展名）。
3. 在 `setup(ctx)` 里用 `ctx.on_message` / `ctx.on_callback` 注册处理器。
4. 放进 `plugins/`，前端启用即生效。

## 2. 插件形态

平台自动识别两种形态，同名时**单文件优先**：

- **单文件**：`plugins/<id>.py`。逻辑集中的简单插件。
- **目录包**：`plugins/<id>/__init__.py`。需拆模块/带资源/带 Vue 前端的复杂插件。`__plugin__` 与 `setup` 写在 `__init__.py`，包内可 `from .helper import xxx`。目录名即 `id`。

`_` 开头的文件/目录不被识别为插件（用作模板、私有辅助）。

## 3. 插件结构（三段式契约）

```python
__plugin__ = {
    "name": "示例功能",            # 必填：前端显示名
    "id": "my_feature",           # 必填：必须等于文件名/目录名
    "version": "1.0.0",           # 必填
    "scope": "user",              # 必填：user | bot | both
    "author": "",                 # 可选
    "description": "功能说明",     # 可选
    "changelog": "v1.0.0 初始版本\n- 功能说明",  # 可选：版本历史弹窗，多行用 \n
    "icon": "",                   # 可选：图标 URL，空则回退平台 logo
    "default_enabled": False,     # 可选
    "webhook": True,              # 可选：启用 Webhook 入站
    "render_mode": "vue",         # 可选：vue=自带配置界面；缺省 "schema"=自动表单
    "config_schema": { ... },     # 可选：前端据此生成配置表单
    "requirements": ["httpx>=0.27"],  # 可选：第三方依赖，启用时平台代装
}

async def setup(ctx):
    @ctx.on_message(ctx.filters.text)
    async def handler(client, message):
        if ctx.config["keyword"] in (message.text or ""):
            await message.reply("matched")

async def teardown(ctx):
    """可选：释放插件自行申请的资源。ctx.on_*/ctx.schedule 注册的由平台自动清理。"""
```

`__plugin__` 必须是**顶层纯字面量字典**——平台用 AST 静态解析读取，不执行插件代码。缺必填字段、`id` ≠ 文件名、`scope` 非法 → 前端标红禁止启用。

### 3.1 requirements（第三方依赖）

插件**只声明**依赖，**绝不自己调 pip**——启用时由平台 `kernel/deps.py` 统一代装。

- 写法：PEP 508 字符串列表，用宽松范围（`>=`）而非钉死（`==`），减少撞车。
- **必须兼容 Python 3.13**。很多包用 `Requires-Python` 卡了上限（`<3.13`），即使 pypi 有该版本号，3.13 上也会「无匹配版本」装失败。
  - 反例：`rapidocr_onnxruntime>=1.3` 全系列标 `<3.13`，永远装不上；应换 `rapidocr>=2`。
  - **优先复用平台已装库**（OCR `ddddocr`、HTTP `httpx`/`aiohttp`、图像 `Pillow`、解析 `beautifulsoup4`/`lxml`），既免装又零冲突。
  - 声明前自检：`pip install "你的依赖" --dry-run`（3.13 环境）能解出版本再写。
- 平台是**单进程热插拔**，所有插件共用一个解释器，**同一个包只能有一个版本**。冲突（已装不兼容版本）→ **拒绝启用**并报原因，绝不强行覆盖。
- 装进 `data/plugin_deps/`（卷持久化，容器重建不丢）并加到 `sys.path` 末尾（平台自带依赖优先）。
- **出站请求自动走平台代理**：平台导出 `HTTP(S)_PROXY`/`ALL_PROXY`，`httpx`/`requests`/`aiohttp`（默认 `trust_env=True`）自动走代理；`localhost`/`127.0.0.1` 已排除。

---

## 4. ctx 接口（插件唯一能接触的平台 API 面）

插件**禁止** `import pyrogram` / `from config` / `from core|kernel`，一切经 `ctx`。

### 4.1 注册处理器

```python
@ctx.on_message(ctx.filters.text)                      # 收到文字消息
async def h(client, message): ...

@ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-10)  # 自己发的，组内优先级高
async def h2(client, message): ...

@ctx.on_edited_message(ctx.filters.text)               # 仅消息被编辑时触发（on_message 收不到）
async def he(client, message): ...

@ctx.on_callback(ctx.filters.regex("^my_btn$"))        # 内联按钮回调
async def hc(client, callback_query):
    await callback_query.answer("ok")
```

- 常用过滤器：`ctx.filters.text` / `.photo` / `.command("x")` / `.outgoing` / `.incoming` / `.group` / `.user(id)` / `.regex(p)` / `.create(fn)`，支持 `&` `|` `~` 组合。
- `group`：本插件**内部**多个处理器的相对优先级（越小越先）。在 handler 内 `raise ctx.StopPropagation` 可阻止该消息被后续处理。
- `target`：`"auto"`（默认，按 scope）/ `"user"` / `"bot"` / `"both"`。`scope=both` 时可借此把不同处理器分挂到用户账号或 Bot。

**group 隔离（重要）**：Pyrogram 同一 group 内只跑第一个匹配的 handler。平台为**每个插件分配独立 group 基址**（步长 1000），你写的 `group=` 被当作「插件内相对优先级」平移到该区间。所以：不同插件监听同类消息**互不抢占都能收到**；插件内仍可用相对 group 排序。你无需关心别的插件的 group。

### 4.2 发送消息

```python
await ctx.bot.send(chat_id, "text")          # 本插件被平台分配的 Bot（未分配=默认 Bot）
await ctx.user.send(chat_id, "text")         # 用户账号（首个已连接）
await ctx.bot.send_photo(chat_id, "url_or_path")
bot2 = ctx.get_bot("some_bot_id")            # 高级：取指定 Bot 的发送代理（不存在回退默认）
```

- `ctx.user_apps`：所有已连接用户账号列表（多账号逐个操作时用）。
- 目标账号未连接时发送方法抛 `RuntimeError`；可先判 `ctx.bot.connected` / `ctx.user.connected`。
- **多 Bot 对插件透明**：平台在「系统设置→通知」为每个插件分配 Bot，`ctx.bot`/`ctx.notify`/`scope=bot` 的 handler 都自动走分配的那个。插件**不选择** Bot，写 `ctx.bot.send(...)` 即可。

### 4.3 通知管理员

```python
await ctx.notify("有新订单")
await ctx.notify("磁盘不足", level="warning")
await ctx.notify("任务失败", level="error", category="备份")

@ctx.on_message(ctx.filters.text)
async def h(client, message):
    await ctx.notify("已抢到红包", account=client)   # 多账号时标注来源账号名
```

- `level`：`info`/`success`/`warning`/`error`；`category`：可选业务分类；`account`：传入 handler 的 `client`，平台自动标账号名。
- 平台统一格式化并投递（优先分配给本插件的 Bot 私聊管理员，回退主账号收藏夹），同时记运行日志。
- **一律走 `ctx.notify`，禁止自己拼 `ctx.bot.send` 发给 `owner_id`**。`ctx.owner_id` 是管理员 TG 数字 ID（无主账号为 0）。

### 4.4 读写配置

```python
kw = ctx.config["keyword"]                    # 每次读取都是用户保存的最新值
on = ctx.config.get("enabled", True)
ctx.update_config({"last_run": "...", "count": 5})   # 局部合并写回，不触发重载
```

运行内部状态优先用 `ctx.kv`；只有想让状态显示在配置表单（`info` 字段）里才用 `ctx.update_config`。

### 4.5 动作按钮

```python
"config_schema": {"test": {"type": "action", "label": "测试连接", "action": "test"}}

async def setup(ctx):
    @ctx.action("test")
    async def _test():
        ok = await do_check()
        return {"ok": ok, "message": "连接正常" if ok else "连不上"}  # dict/str/None
```

由已登录管理员触发；`danger: True` 的按钮点击前弹确认框。

### 4.6 下载媒体 / 浏览器 / AI

```python
# 下载消息媒体到本插件目录，返回 Path（无媒体抛 ValueError）
path = await ctx.download(message, subdir="imgs")   # data/plugin_data/<id>/imgs/xxx

# 浏览器自动化（引擎优先 CloakBrowser 过反爬，回退 Playwright；首次调用才下内核）
html = await ctx.browser.page_source("https://example.com", timeout=60)
def grab(page):                                      # 同步 action，收到同步 page
    page.click("#more"); return page.inner_text("#list")
data = await ctx.browser.run("https://example.com", grab, headless=True)

# 平台 AI（密钥/模型/权限由平台统一管，插件不要自建 OpenAI 客户端）
if ctx.ai.available:
    ans = await ctx.ai.chat("整理成三条要点：…", system="只输出简洁中文")
desc = await ctx.ai.vision(image_path, "识别图片内容")     # 本地 Path/字节，≤20MB
img  = await ctx.ai.generate_image("极简电影海报")          # 返回 Path
```

- `ctx.ai.is_available("text"|"vision"|"image")` 分别判断；`ctx.ai.available_models(cap)` 列可用模型；`model=` 填管理员设的「插件调用别名」。主模型失败自动试备用。管理员可关闭/限制某插件的 AI 权限。

### 4.7 存储 / 日志 / 定时 / 清理

```python
ctx.kv.set("count", 10); n = ctx.kv.get("count", 0); ctx.kv.delete("count"); ctx.kv.keys()
# 每插件独立 sqlite（data/kv/<id>.sqlite）。关系型存储表名须带 <plugin_id>_ 前缀。

p = ctx.data_dir / "a.jpg"        # data/plugin_data/<id>/，每插件独享可写目录
p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)

ctx.log.info("done"); ctx.log.warning("odd: %s", e); ctx.log.error("fail: %s", e)  # 禁 print

ctx.schedule(tick, "interval", seconds=60)
ctx.schedule(daily, "cron", hour=9, minute=0, id="每日早报")   # id 自动加 <id>:: 前缀

async def setup(ctx):
    conn = open_something()
    ctx.add_cleanup(conn.close)    # 自管理资源的清理回调
```

### 4.8 Webhook（接收外部回调）

```python
__plugin__ = { ..., "webhook": True }

async def setup(ctx):
    @ctx.on_webhook
    async def on_hook(req):
        data = req.json or {}
        return {"ok": True}        # dict→JSON / str→文本 / None→{"ok": true}
```

入站地址：`http(s)://<平台>/api/v1/plugin/<id>/webhook?apikey=<平台统一 WEBHOOK_SECRET>`。`req`：`.method/.query/.headers/.json/.text/.body`。仅插件启用、已注册、平台已生成密钥时响应。

### 4.9 插件自带后端接口 ctx.on_api（配 Vue 模式）

```python
async def setup(ctx):
    @ctx.on_api("/ping", methods=["GET"])
    async def ping(req):
        return {"ok": True, "message": "pong"}
```

实际地址 `/api/plugins/<id>/api/<path>`，经**管理员 Bearer 令牌**鉴权（前端 `host.callApi` 自动带）。`req` 同 WebhookRequest（多 `.path`）。返回 dict→JSON / str→文本 / None→`{"ok":true}`。

### 4.10 获取会话信息（显示群组名）

配置里存的是 chat_id，界面要显示群名时调平台 API `GET /api/chats/{chat_id}`（可选 `?session=账号名`），返回 `{id, title, type}`。Vue 模式下经 `host.callApi` 自动带令牌。可选增强，失败应回退显示 ID。

---

## 5. config_schema（配置表单）

前端按字段类型自动生成表单（插件卡片「配置」入口）。

| 类型 | 适用 |
|------|------|
| `boolean` | 开关 |
| `string` | 短文本（关键词、地址） |
| `password` | 敏感信息（密钥、Token） |
| `number` | 精确数值（端口、次数） |
| `slider` | 有范围的数值（延迟、百分比）——优先用它而非 number |
| `select` | 单选下拉 |
| `multiselect` | 多选标签 |
| `text` | 多行长文本（模板、JSON） |
| `list` | 可增删行表格（`fields` 定义每行子字段） |
| `chat` | 会话选择器（存 chat_id） |
| `info` | 只读展示（可用 `ctx.update_config` 写回当状态看） |
| `action` | 操作按钮（触发 `ctx.action("名")`） |

| 属性 | 说明 |
|------|------|
| `type` / `default` | 必填（multiselect/list 用 list，slider/number 用数字） |
| `label` / `help` | 显示名 / 字段下方说明 |
| `options` | select/multiselect 候选：`["a","b"]` 或 `[{"value":"a","label":"甲"}]` |
| `min`/`max`/`step` | number/slider 约束（兼作保存校验） |
| `required` | True 时不能为空，否则前端拦下不保存 |
| `section` | 分区标题（同 section 归一组卡片） |
| `order` | 排序权重（越小越靠前） |
| `cols` | 栅格列数（1-12，12=整行 6=半行 4=三分之一） |
| `show_if` | 条件显示，如 `{"enable_x": True}` |
| `fields` / `item_label` | list 专用：每行子字段 / 行标题前缀 |
| `multi` / `chat_types` / `session` | chat 专用：多选 / 过滤类型(private/bot/group/channel) / 枚举账号 |
| `text` | info 专用：固定文字（不填则显示该键当前值） |
| `action` / `danger` | action 专用：动作名 / 点击前弹确认 |

**布局**：12 列栅格，桌面约 1000px、窄屏（≤768px）自动全屏单列。默认：大字段（text/list/multiselect/chat）占整行，短字段半行并排。用 `cols`+`order` 精调（开关常 `cols:3` 并排，`order` 从 1 起；参数 order 从 10 起）。

```python
"config_schema": {
    "enable_x":   {"type": "boolean", "default": True, "label": "启用X", "section": "功能开关", "cols": 4, "order": 1},
    "keyword":    {"type": "string", "default": "", "label": "关键词", "section": "参数", "show_if": {"enable_x": True}, "order": 10},
    "delay":      {"type": "slider", "default": 5, "label": "延迟(秒)", "min": 0, "max": 30, "step": 1, "section": "参数"},
    "mode":       {"type": "select", "default": "a", "label": "模式", "options": ["a","b"], "section": "参数"},
    "items":      {"type": "list", "default": [], "label": "规则", "section": "参数", "item_label": "规则",
                   "fields": {"name": {"type": "string", "label": "名称"}, "on": {"type": "boolean", "label": "启用", "default": True}}},
    "target":     {"type": "chat", "default": 0, "label": "转发到", "section": "会话", "chat_types": ["group","channel"]},
    "tip":        {"type": "info", "label": "说明", "text": "先填密钥再启用", "section": "会话"},
    "test":       {"type": "action", "label": "测试连接", "action": "test", "section": "会话"},
}
```

插件全部配置走 `config_schema`，**禁止读写平台配置**。

---

## 6. Vue 模式（自带配置界面）

需要图表/可视化/复杂交互时，插件自带 Vue 配置界面（模块联邦）。仅**目录包**可用，起步复制 `plugins/_TEMPLATE_VUE/`。

```python
__plugin__ = { ..., "render_mode": "vue" }   # vue 模式无需 config_schema
```

```
my_plugin/
├── __init__.py
└── frontend/
    ├── package.json
    ├── vite.config.js      # 模块联邦：暴露 ./Config，shared.vue generate:false 复用宿主
    ├── src/Config.vue      # 必须暴露为 ./Config
    └── dist/               # 构建产物，必须随插件提交
```

- `vite.config.js`：`base: '/api/plugins/<id>/fe/'`，`@originjs/vite-plugin-federation` 暴露 `./Config`，`vue` 声明 `shared: { singleton: true, generate: false }`。
- **发布前必须** `cd frontend && npm install && npm run build`，产物入口 `dist/assets/remoteEntry.js`。

组件契约：

```js
const props = defineProps({ pluginId: String, host: Object })
await props.host.getConfig()                 // 读已保存配置
await props.host.saveConfig(values)          // 保存（存平台统一存储，ctx.config 可读）
await props.host.callApi('/ping')            // 调 ctx.on_api 接口（自动带令牌）
await props.host.callApi('/x', { method: 'POST', body: {...} })
props.host.toast.success('已保存')            // 平台提示（success/error）
```

vue 模式无平台「保存」按钮，由组件自己调 `host.saveConfig`。画布桌面约 1000px、窄屏全屏——用响应式布局，别写死窄宽度。

---

## 7. scope / 多账号 / 多 Bot

| scope | 处理器挂载 | 适用 |
|-------|-----------|------|
| `user` | 用户账号 | 监听群消息、自动抢红包/抽奖 |
| `bot` | 机器人账号 | 菜单、命令、应答 |
| `both` | 两者 | 双端响应 |

- **账号范围**：`scope=user`/`both` 默认挂到**所有**已连接用户账号；用户可在插件卡片「账号」里限定部分账号（`account_scope`）。该范围对 handler 挂载、`ctx.user`、`ctx.user_apps` **一致生效**。
- **多 Bot**：平台为每个插件分配 Bot（`bot_choice`），对 `ctx.notify`/`ctx.bot`/`scope=bot` handler 一致生效。插件不感知、不选择。

---

## 8. 约束（铁律）

1. 一个文件/目录一个插件，文件名/目录名 = `id`，全局唯一。
2. 禁止 `import pyrogram` / `config` / 内核模块，一切经 `ctx`。
3. 禁止类级 `@Client.on_message`，须用 `@ctx.on_message`（否则无法热卸载）。
4. 禁止 `print`，用 `ctx.log`。
5. 插件之间禁止互相 import。共用逻辑下沉平台，或放本插件目录内/`_` 前缀辅助文件。
6. `_` 前缀文件/目录不被识别为插件。
7. 业务配置只进 `config_schema`，禁止读写平台配置；持久化用 `ctx.kv`（关系型表名带 `<id>_` 前缀）。
8. 自管理资源（连接、后台 task）必须在 `teardown` 或 `ctx.add_cleanup` 释放。

**热插拔容错**：单个插件 `setup` 抛异常只标记该插件 `error`，不影响内核与其它插件。

---

## 9. 发布到 GitHub 插件市场

仓库根放 `manifest.json`（带版本号，平台据此识别更新）：

```json
{
  "my_feature": {"name":"示例功能","version":"1.0.0","author":"","description":"...","icon":"https://.../i.png","path":"my_feature.py"},
  "big_plugin": {"name":"大型插件","version":"2.0.0","path":"big_plugin/"}
}
```

- key = 插件 `id`；`path` 单文件以 `.py` 结尾、目录包以 `/` 结尾（递归下载整目录）。
- 无清单则目录扫描（仓库根或 `plugins/` 下的 `<id>.py` / `<id>/__init__.py`，忽略 `_` 前缀）。
- 仅支持公开仓库。导入 = 下载落盘 + 静态校验，**绝不自动启用**（启用=服务器执行远程代码，须用户手动开）。
- **商店自动轮询**（默认 20 分钟）做两件事：①刷新商店列表；②对**已安装**插件，manifest 版本变化则下载覆盖，**正在运行的自动热重载**生效（未运行的只更新文件不启用）。

---

## 10. 平台开放 API（远程管理/调试插件）

平台提供 `X-API-Key` 鉴权的 REST API（base `/api/v1`），可远程列/启用/停用/重载插件、读写配置与 KV、发消息、查日志、看状态——适合 AI 工具与脚本调试插件。完整端点见 `references/platform-api.md`。

常用：`GET /plugins`、`POST /plugins/{id}/enable|disable|reload`、`GET|PUT /plugins/{id}/config`、`GET /plugins/{id}/source`、`GET|PUT|DELETE /plugins/{id}/kv/{key}`、`POST /messages/send`、`GET /chats/{chat_id}`、`GET /logs/plugins/{id}`、`GET /status`。

> 注意：`PUT /plugins/{id}/source`（改源码）已因安全禁用——改代码须经 Web 编辑器或直接改服务器文件。

---

## 11. 本仓库专属规则（AWBotNest-Plugins）

- 这是**插件市场仓库**，不是平台仓库——**不改平台内核**。
- **改插件代码必须同步抬高 `manifest.json` 的 `version`**，否则商店识别不到更新、已安装实例收不到推送。建议同时更新 `__plugin__["changelog"]`。
- 新插件先确认 `manifest.json` 里没有同 `id`，再加进去。
- Vue 插件改了 `frontend/src` 必须 `npm run build` 重新生成 `dist/` 并提交（平台加载的是构建产物）。
- 同步机制：直接操作远程 `AWdress/AWBotNest-Plugins`（非 fork）。

## 12. 故障排查 & 数据位置

- **插件标红**：缺 `__plugin__` / `id` ≠ 文件名 / `scope` 非法 / 语法错误。
- **改动生效**：前端「重载」，或停用再启用（运行中插件被商店更新会自动热重载）。
- **单插件异常**不影响其它插件与平台。
- 数据：`ctx.kv` → `data/kv/<id>.sqlite`；文件 → `data/plugin_data/<id>/`；依赖 → `data/plugin_deps/`；浏览器内核 → `data/browser_cache/`。

完整硬性规范见仓库 `docs/SPEC.md`；教程见 `docs/PLUGIN_GUIDE.md`；模板 `plugins/_TEMPLATE.py` / `plugins/_TEMPLATE_VUE/`。
