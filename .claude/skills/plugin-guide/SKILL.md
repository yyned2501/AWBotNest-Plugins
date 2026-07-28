---
name: plugin-guide
version: 1
description: >-
  Use this skill when you need to write, modify, or understand AWBotNest plugins.
  Covers the full plugin development guide from the platform's PLUGIN_GUIDE.md:
  plugin structure, ctx interface, config_schema, Vue mode, webhook, browser
  automation, AI, scheduling, and publishing. Use whenever the task involves
  AWBotNest plugin code, regardless of which specific plugin.
---

# AWBotNest 插件开发指南

面向开发者的插件编写规范。一个插件即一个独立可热插拔的功能单元，平台在运行时动态加载与卸载，无需重启进程，亦无需改动平台任何文件。

「想要啥功能，写一个文件丢进去，勾选启用，完事。」

## 快速开始

1. 复制 `plugins/_TEMPLATE.py`，重命名为目标插件名（如 `my_feature.py`）。
2. 修改 `__plugin__` 元数据字典，`id` 必须与文件名（去扩展名）一致。
3. 在 `setup(ctx)` 中注册处理器与任务。
4. 通过前端「上传插件」或直接置于 `plugins/` 目录。
5. 在插件列表中启用：处理器即时挂载；停用即时卸载。

## 插件形态

- **单文件**：`plugins/<id>.py`。适用于逻辑集中的插件。
- **目录包**：`plugins/<id>/__init__.py`。适用于需拆分模块或携带资源文件的插件。`__plugin__` 与 `setup` 定义于 `__init__.py`，包内可使用相对导入（`from .helper import xxx`）。目录名即插件 `id`。

同名时单文件优先。`_` 前缀的文件/目录不被识别为插件（用作模板或辅助模块）。

## 插件结构

三段式契约：

```python
__plugin__ = {
    "name": "示例功能",            # 显示名
    "id": "my_feature",           # 必须等于文件名/目录名
    "version": "1.0.0",
    "author": "",
    "description": "功能说明",
    "changelog": "v1.0.0 初始版本\n- 实现基础功能",  # 可选，版本更新说明
    "icon": "",                   # 可选，图标 URL；留空回退平台 logo
    "scope": "user",              # user | bot | both
    "default_enabled": False,
    "config_schema": {            # 可选，前端据此生成配置表单
        "keyword": {"type": "string", "default": "hello", "label": "触发词"},
    },
    "requirements": [             # 可选，第三方依赖；启用时由平台代装
        "httpx>=0.27",
    ],
    "webhook": True,              # 可选，启用 Webhook 接收外部回调
    "render_mode": "vue",         # 可选，vue 模式自带配置界面
}

async def setup(ctx):
    """启用时调用，在此注册处理器与定时任务。"""
    @ctx.on_message(ctx.filters.text)
    async def handler(client, message):
        if ctx.config["keyword"] in (message.text or ""):
            await message.reply("matched")

async def teardown(ctx):
    """停用时调用（可选），释放插件自行申请的资源。"""
    pass
```

`__plugin__` 为顶层字面量字典，平台通过静态 AST 解析读取，不执行插件代码。必填字段：`name`、`id`、`version`、`scope`。

### requirements 注意事项

- **不要在插件里自己调 pip**——只声明，平台在启用时统一代装。
- 建议用宽松范围（`"httpx>=0.27"`）而非钉死版本。
- 声明前在 3.13 环境验证包有对应发行版（`pip install "你的依赖" --dry-run`）。
- 优先复用平台已装的库：OCR 用 `ddddocr`、HTTP 用 `httpx`/`aiohttp`、图像用 `Pillow`、解析用 `beautifulsoup4`/`lxml`。
- 出站请求自动走平台代理（HTTP(S)_PROXY/ALL_PROXY 环境变量），`localhost`/`127.0.0.1` 已排除。

## ctx 接口

插件通过 `ctx` 与平台交互，**不得**直接 `import pyrogram` 或 `config`。

### 注册消息处理器

```python
@ctx.on_message(ctx.filters.text)
async def h(client, message):
    await message.reply("ok")

@ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-10)
async def h2(client, message):
    ...
```

常用过滤器：`ctx.filters.text`、`ctx.filters.photo`、`ctx.filters.command("xxx")`、`ctx.filters.outgoing`、`ctx.filters.incoming`，支持 `&`、`|`、`~` 组合。

`group` 参数控制本插件内部多个处理器的相对执行优先级，数值越小越先执行。`raise ctx.StopPropagation` 可阻止该消息被后续处理器继续处理。

`target` 参数：`"auto"`（默认，按插件 `scope` 选择）、`"user"`、`"bot"`、`"both"`。

### 注册编辑消息处理器

用法、参数与 `on_message` 完全一致，但**只在消息被编辑时触发**：

```python
@ctx.on_edited_message(ctx.filters.text)
async def on_edit(client, message):
    ...
```

### 注册回调处理器

```python
@ctx.on_callback(ctx.filters.regex("^my_btn$"))
async def on_click(client, callback_query):
    await callback_query.answer("ok")
```

### 发送消息

```python
await ctx.bot.send(chat_id, "text")
await ctx.user.send(chat_id, "text")
await ctx.bot.send_photo(chat_id, "url_or_path")
```

- `ctx.bot`：机器人账号发送代理（自动使用平台为本插件分配的 Bot）。
- `ctx.user`：用户账号发送代理（取首个已连接）。
- `ctx.user_apps`：已连接用户账号的列表，多账号插件需逐个操作时使用。
- 目标账号未连接时，对应代理的发送方法抛 `RuntimeError`；可先判 `ctx.bot.connected` / `ctx.user.connected`。

### 通知平台管理员

```python
await ctx.notify("有新订单")
await ctx.notify("磁盘空间不足", level="warning")
await ctx.notify("任务失败", level="error", category="备份")

@ctx.on_message(ctx.filters.text)
async def h(client, message):
    await ctx.notify("已抢到红包", account=client)
```

- `level`：`info` / `success` / `warning` / `error`。
- `category`：可选业务分类。
- `account`：多账号场景下传入处理器收到的 `client`，平台自动标注来源账号名。
- 推送通知一律走 `ctx.notify`，不要自行调用 `ctx.bot.send` 实现。
- `ctx.owner_id`：管理员的 Telegram 数字 ID（无主账号时为 `0`）。

### 读写配置

```python
# 读取（每次读取均为用户保存的最新值）
kw = ctx.config["keyword"]
on = ctx.config.get("enabled", True)

# 写回自己的配置（局部合并，不触发重载）
ctx.update_config({"last_run": "2026-07-15 10:00", "count": 5})
```

存运行内部状态优先用 `ctx.kv`；只有想让状态在配置表单里显示时才用 `ctx.update_config`。

### 动作按钮

在 `config_schema` 放一个 `action` 字段，用 `ctx.action(name)` 注册同名处理器：

```python
"config_schema": {"test": {"type": "action", "label": "测试连接", "action": "test"}}

async def setup(ctx):
    @ctx.action("test")
    async def _test():
        ok = await do_check()
        return {"ok": ok, "message": "连接正常" if ok else "连不上"}
```

返回 `dict`（含 `ok`/`message`）、`str`（当作提示文字）或 `None`（视为成功）。`danger: True` 的按钮点击前会弹确认框。

### 下载消息媒体

```python
@ctx.on_message(ctx.filters.photo)
async def h(client, message):
    path = await ctx.download(message, subdir="imgs")   # data/plugin_data/<id>/imgs/xxx
    text = await ocr(path)
```

消息无可下载媒体时抛 `ValueError`。

### 浏览器自动化

```python
# 取渲染后的 HTML 源码
html = await ctx.browser.page_source("https://example.com", timeout=60)

# 需要交互时，传一个同步 action(page)
def grab(page):
    page.click("#more")
    return page.inner_text("#list")
data = await ctx.browser.run("https://example.com", grab, headless=True)
```

- 引擎优先 **CloakBrowser**（过 Cloudflare/指纹检测），不可用时自动回退 **Playwright Chromium**。
- `ctx.browser.engine` 返回当前引擎名（`"cloakbrowser"` / `"playwright"` / `None`）。
- 浏览器内核在**插件首次调用时**才下载到 `data/browser_cache`，随卷持久化。

### 平台 AI

```python
if ctx.ai.available:
    answer = await ctx.ai.chat("把下面内容整理成三条要点：……", system="只输出简洁的中文。")

# 图片识别
image_path = await ctx.download(message, subdir="imgs")
description = await ctx.ai.vision(image_path, "识别图片中的文字和主要内容")

# 生图
generated_path = await ctx.ai.generate_image("一张蓝绿色的极简电影海报")
```

- `ctx.ai.is_available("text" | "vision" | "image")` 分别判断能力。
- `ctx.ai.available_models(capability)` 返回可用模型列表。
- `model=` 填管理员在模型库中设置的“插件调用别名”。
- 主模型调用失败时自动尝试备用模型。
- 管理员可关闭某个插件的全部 AI 权限、只允许部分能力，或指定模型。

### 键值存储

```python
ctx.kv.set("count", 10)
n = ctx.kv.get("count", 0)
ctx.kv.delete("count")
ctx.kv.keys()
```

### 文件存储

```python
p = ctx.data_dir / "avatars" / "a.jpg"   # data/plugin_data/<id>/avatars/a.jpg
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(img_bytes)
```

### 日志

```python
ctx.log.info("processed one message")
ctx.log.warning("unexpected: %s", err)
ctx.log.error("failed: %s", err)
```

### 定时任务

```python
ctx.schedule(tick, "interval", seconds=60)
ctx.schedule(tick, "cron", hour=3, minute=0)
ctx.schedule(daily_report, "cron", hour=9, id="每日早报")
```

### Webhook（接收外部回调）

```python
__plugin__ = { ..., "webhook": True }

async def setup(ctx):
    @ctx.on_webhook
    async def on_hook(req):
        data = req.json or {}
        await ctx.notify(f"收到事件：{data}", category="Webhook")
        return {"ok": True}
```

入站地址：`http(s)://<平台地址>/api/v1/plugin/<插件id>/webhook?apikey=<密钥>`

### 资源清理

通过 `ctx.on_message`、`ctx.on_edited_message`、`ctx.on_callback`、`ctx.schedule` 注册的处理器与任务由平台在停用时自动清理。若插件自行申请了其它资源，用 `ctx.add_cleanup(fn)` 注册清理回调：

```python
async def setup(ctx):
    conn = open_something()
    ctx.add_cleanup(conn.close)
```

## config_schema（配置表单）

### 字段类型速查

| 类型 | 适用场景 |
|------|---------|
| `boolean` | 开关功能 |
| `string` | 短文本输入（关键词、API地址） |
| `password` | 敏感信息（API密钥、Token） |
| `number` | 精确数值（端口号、重试次数） |
| `slider` | 有范围的数值调节（延迟、音量、百分比） |
| `select` | 单选下拉（模式选择、日志级别） |
| `multiselect` | 多选标签（通知类型、过滤标签） |
| `text` | 多行长文本（消息模板、脚本、JSON配置） |
| `list` | 可增删的列表（规则列表、白名单） |
| `chat` | 会话选择器（转发到的群组、通知频道） |
| `info` | 只读说明（使用提示、当前状态显示） |
| `action` | 操作按钮（测试连接、立即执行） |

### 字段属性

| 属性 | 说明 |
|------|------|
| `type` | 字段类型 |
| `default` | 默认值（必填。`multiselect`/`list` 为列表，`slider`/`number` 为数字） |
| `label` | 显示名 |
| `help` | 字段下方说明文字（可选） |
| `options` | `select`/`multiselect` 候选项，`["a","b"]` 或 `[{"value":"a","label":"甲"}]` |
| `min`/`max`/`step` | `number`/`slider` 取值约束（可选） |
| `required` | 保存前校验：为 `True` 时该项不能为空 |
| `section` | 分区标题（可选），同一 `section` 归为一组 |
| `order` | 排序权重（可选，数字），越小越靠前 |
| `cols` | 栅格列数（可选，1-12），控制字段宽度 |
| `show_if` | 条件显示，如 `{"enable_x": True}` |
| `fields` | `list` 专用：每行的子字段 `{子键: 子 spec}` |
| `item_label` | `list` 专用：每行标题前缀（默认「项」） |
| `multi` | `chat` 专用：`True` 为多选（存 id 数组），默认单选 |
| `chat_types` | `chat` 专用：过滤会话类型，`private`/`bot`/`group`/`channel` |
| `session` | `chat` 专用：指定用哪个账号枚举会话 |
| `text` | `info` 专用：要展示的固定文字；不填则显示该键的当前值 |
| `action` | `action` 专用：动作名，须与 `ctx.action("名字")` 一致 |
| `danger` | `action` 专用：`True` 时点击前弹确认框 |

### 完整示例

```python
"config_schema": {
    "enable_x":    {"type": "boolean", "default": True,  "label": "启用X功能", "section": "功能开关"},
    "enable_y":    {"type": "boolean", "default": False, "label": "启用Y功能", "section": "功能开关"},
    "text_field":  {"type": "string",  "default": "",    "label": "文本", "section": "参数", "help": "说明", "show_if": {"enable_x": True}},
    "secret":      {"type": "password","default": "",    "label": "密钥", "section": "参数"},
    "number_field":{"type": "number",  "default": 0,     "label": "数字", "section": "参数", "min": 0, "max": 100},
    "volume":      {"type": "slider",  "default": 5,     "label": "滑块", "section": "参数", "min": 0, "max": 10, "step": 1},
    "choice":      {"type": "select",  "default": "a",   "label": "单选", "options": ["a","b","c"], "section": "参数"},
    "tags":        {"type": "multiselect", "default": [], "label": "多选", "options": ["x","y","z"], "section": "参数"},
    "long_text":   {"type": "text",    "default": "",    "label": "多行文本", "section": "参数"},
    "required_key":{"type": "password","default": "",    "label": "密钥", "section": "参数", "required": True},
    "items":       {"type": "list",    "default": [],    "label": "列表", "section": "参数",
                    "item_label": "项",
                    "fields": {
                        "name":    {"type": "string",  "label": "名称"},
                        "value":   {"type": "string",  "label": "值"},
                        "tags":    {"type": "multiselect", "label": "标签", "options": ["a","b","c"], "default": []},
                        "enabled": {"type": "boolean", "label": "启用", "default": True},
                    }},
    "target":      {"type": "chat",    "default": 0,     "label": "转发到", "section": "会话",
                    "multi": False, "chat_types": ["group", "channel"]},
    "tip":         {"type": "info",    "label": "使用说明", "text": "先填密钥再启用", "section": "会话"},
    "last_run":    {"type": "info",    "default": "",    "label": "上次运行", "section": "会话"},
    "test":        {"type": "action",  "label": "测试连接", "action": "test", "section": "会话"},
}
```

### 表单布局

配置弹窗采用 **12 列栅格系统**，通过 `cols` 和 `order` 精确控制字段排版。

**自动布局（默认）**：
- 大字段（`text`/`list`/`multiselect`/`chat`）自动占 12 列（整行）
- 短字段（`string`/`password`/`number`/`boolean`/`select`/`slider`）自动占 6 列（半行）

**推荐排版**：
```python
"config_schema": {
    # 开关并排：每个占 4 列（三分之一行）
    "enable_plugin": {"type": "boolean", "label": "启用插件", "cols": 4, "order": 1, "section": "功能开关"},
    "auto_delete":   {"type": "boolean", "label": "自动删除", "cols": 4, "order": 2, "section": "功能开关"},
    "send_notify":   {"type": "boolean", "label": "发送通知", "cols": 4, "order": 3, "section": "功能开关"},
    # 参数字段（order 从 10 开始）
    "api_key":       {"type": "password", "label": "API密钥", "order": 10, "section": "基本配置"},
    "interval":      {"type": "slider", "label": "间隔(分钟)", "min": 1, "max": 60, "default": 10, "order": 11, "section": "基本配置"},
}
```

## Vue 模式

需要图表、可视化编辑器或非表单式复杂交互时，插件自带 Vue 配置界面（基于模块联邦 Module Federation）。

### 开启

仅**目录包**插件可用。在 `__plugin__` 声明：

```python
__plugin__ = {
    ..., "render_mode": "vue",     # 配置界面由插件自带的 Vue 组件渲染
    # vue 模式无需 config_schema
}
```

### 目录结构

```
my_plugin/
├── __init__.py
└── frontend/
    ├── package.json
    ├── vite.config.js        # 模块联邦：暴露 ./Config，共享宿主 Vue
    ├── src/Config.vue        # ← 配置界面（必须暴露为 ./Config）
    └── dist/                 # 构建产物，发布时一并提交
```

### 组件契约

```js
const props = defineProps({ pluginId: String, host: Object })

// host 提供的能力：
await props.host.getConfig()                 // 读取已保存配置
await props.host.saveConfig(values)          // 保存配置
await props.host.callApi('/ping')            // 调用插件后端接口
await props.host.callApi('/echo', { method: 'POST', body: {...} })
props.host.toast.success('已保存')            // 弹平台提示
```

### 后端接口 ctx.on_api

```python
async def setup(ctx):
    @ctx.on_api("/ping", methods=["GET"])
    async def ping(req):
        return {"ok": True, "message": "pong"}

    @ctx.on_api("/save_rule", methods=["POST"])
    async def save_rule(req):
        data = req.json or {}
        ctx.kv.set("rules", data.get("rules", []))
        return {"ok": True}
```

- 实际地址 `/api/plugins/<id>/api/<path>`，经管理员登录态鉴权。
- `req` 是 `WebhookRequest`：`req.method` / `req.query` / `req.headers` / `req.json` / `req.text` / `req.path`。
- 返回 `dict`→JSON、`str`→文本、`None`→`{"ok": true}`。

## scope

| scope | 处理器挂载目标 | 适用场景 |
|-------|---------------|---------|
| `user` | 用户账号 | 监听群消息、自动抢红包、自动抽奖等 |
| `bot` | 机器人账号 | 菜单、命令、面向用户应答 |
| `both` | 两者 | 需双端响应的功能 |

## 约束

1. 一个文件对应一个插件，文件名即 `id`，全局唯一。
2. 不得 `import pyrogram` / `config` / 内核模块，全部能力经 `ctx` 获取。
3. 不得使用 `@Client.on_message`，须使用 `@ctx.on_message`，否则无法热卸载。
4. 不得使用 `print`，须使用 `ctx.log`。
5. 插件之间不得相互 import。共用逻辑应抽为 `_` 前缀的辅助文件，或下沉至平台。
6. `_` 前缀的文件不被识别为插件（用作模板或辅助模块）。

## 发布到 GitHub 仓库

在仓库根目录提供 `manifest.json`：

```json
{
  "my_feature": {"name":"示例功能","version":"1.0.0","author":"","description":"...","icon":"https://.../i.png","path":"my_feature.py"},
  "big_plugin": {"name":"大型插件","version":"2.0.0","path":"big_plugin/"}
}
```

- key 为插件 `id`；`path` 单文件以 `.py` 结尾，目录包以 `/` 结尾。
- 无 `manifest.json` 时，将 `<id>.py` 或 `<id>/__init__.py` 置于仓库根或 `plugins/` 目录，平台自动扫描。

## 故障排查

- **插件标红**：缺少 `__plugin__`、`id` 与文件名不一致、`scope` 非法或语法错误。
- **代码改动生效**：前端点击「重载」，或停用后重新启用。
- **单个插件异常**：不影响其它插件与平台运行。
- **数据存储位置**：`ctx.kv` → `data/kv/<id>.sqlite`，文件 → `data/plugin_data/<id>/`。