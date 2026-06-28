# AWBotNest-Plugins

> AWBotNest 官方插件仓库 —— 平台**内置**此仓库，它会自动出现在每个平台的「插件商店」里。这里的每个插件都遵循平台「**单文件 / 文件夹插件**」规范。

- 平台仓库：[AWdress/AWBotNest](https://github.com/AWdress/AWBotNest)

---

## 一分钟上手

1. 复制平台的 `plugins/_TEMPLATE.py`（或本仓库任一插件），改名成你的功能名，如 `my_feature.py`。文件名就是插件 ID。
2. 改顶部的 `__plugin__` 字典（`id` 必须等于文件名）。
3. 在 `setup(ctx)` 里写逻辑，处理器一律用 `ctx.on_message` / `ctx.on_callback` 注册。
4. 把插件放进平台 `plugins/`，或上传、或从本仓库导入。
5. 在平台插件列表打开开关 → 立即生效；关掉 → 立即卸载。**不用重启，不用改其它文件。**

---

## 插件规范

### 1. 三段式契约

每个插件必须有这三段（`teardown` 可选）：

```python
# ① 元数据：平台靠它在前端显示。必须是纯字面量字典（平台用 AST 静态解析）
__plugin__ = {
    "name": "我的功能",        # 必填：前端显示名
    "id": "my_feature",        # 必填：必须 = 文件名/目录名（去 .py）
    "version": "1.0.0",        # 必填：插件商店靠它判断有没有更新
    "scope": "user",           # 必填：user(用户账号) | bot(机器人) | both
    "author": "你",            # 可选
    "description": "干啥的",    # 可选
    "default_enabled": False,  # 可选：放入本地 plugins/ 时是否默认启用
    "config_schema": { ... },  # 可选：前端自动生成配置表单
}

# ② 启用时调用：在这里注册处理器（可 async 可同步）
async def setup(ctx):
    @ctx.on_message(ctx.filters.text)
    async def handler(client, message):
        await message.reply("收到")

# ③ 停用时调用（可选）：只清理你自己开的资源
async def teardown(ctx):
    pass
```

### 2. 两种形态

- **单文件**：`plugins/<id>.py` —— 简单插件，文件名 = ID。
- **文件夹**：`plugins/<id>/__init__.py` —— 复杂插件（多模块/资源），目录名 = ID，`__plugin__` 与 `setup` 写在 `__init__.py`，包内可 `from ._helper import ...`。
- 同名时单文件优先；以 `_` 开头的文件/目录不会被识别为插件（用作模板/私有辅助）。

### 3. `ctx` 能力速查

插件**只能**通过 `ctx` 访问平台，要什么都从它拿：

| 能力 | 用法 |
|------|------|
| 过滤器 | `ctx.filters.text` / `.photo` / `.command("x")` / `.outgoing` / `.incoming` / `.group`，可 `& \| ~` 组合 |
| 注册消息 | `@ctx.on_message(filter, group=0, target="auto")` |
| 注册回调 | `@ctx.on_callback(filter, group=0, target="auto")` |
| Bot 发送 | `await ctx.bot.send(chat_id, text)` / `ctx.bot.send_photo(...)` |
| 用户发送 | `await ctx.user.send(chat_id, text)` |
| 全部用户账号 | `ctx.user_apps`（多账号场景） |
| 通知平台主人 | `await ctx.notify(text, level=, category=, account=)`（平台自动加插件名/级别图标/账号名并投递；别自己拼格式或用 `ctx.bot.send`） |
| 主人 ID | `ctx.owner_id`（平台主人 Telegram 数字 ID，无主账号为 0） |
| 配置 | `ctx.config["字段名"]`（每次读取都是前端最新值） |
| 键值存储 | `ctx.kv.get/set/delete/keys`（每插件独立 sqlite，互不干扰） |
| 文件目录 | `ctx.data_dir`（`Path`，每插件独享可写目录，存图片/素材等实际文件） |
| 日志 | `ctx.log.info/debug/warning/error` |
| 定时任务 | `ctx.schedule(fn, "interval", seconds=60)` / `(fn, "cron", hour=3, id="名称")` |
| 清理回调 | `ctx.add_cleanup(fn)` |

`target`：`"user"` / `"bot"` / `"both"` / `"auto"`（按插件 scope 自动选择）。

### 4. config_schema（插件配置）

插件的**所有业务参数都写在这里**，前端「配置」按钮据此自动生成设置界面，值用 `ctx.config[...]` 读：

```python
"config_schema": {
    "enable_x": {"type": "boolean", "default": True, "label": "启用X", "section": "功能开关"},
    "keyword":  {"type": "string",  "default": "",   "label": "触发词", "section": "参数",
                 "help": "字段下方说明", "show_if": {"enable_x": True}},
    "secret":   {"type": "password", "default": "",  "label": "密钥",  "section": "参数"},
    "volume":   {"type": "slider",  "default": 5, "min": 0, "max": 10, "step": 1, "section": "参数"},
    "mode":     {"type": "select",  "default": "a", "options": ["a","b"], "section": "参数"},
}
```

字段属性：
- `type`：`string` / `password` / `number` / `boolean` / `select` / `multiselect` / `slider` / `text`(多行)
- `default`：默认值（必填；multiselect 用列表，slider/number 用数字）
- `label` 显示名 · `help` 说明 · `options`（select/multiselect 用）· `min`/`max`/`step`（number/slider 用）
- `section`：分区标题（同 section 归一组卡片）
- `show_if`：条件联动，如 `{"enable_x": True}` 仅当该字段为真才显示本字段

> 需要多条规则/多项内容时，优先用普通字段组合（开关 + `select` + `show_if` 联动）把界面拆清楚；确实需要不定条数时，可用多行 `text` 字段让用户一行一条填写，插件内解析（参考 `keyword_auto_reply` 的「关键词=回复」写法）。

### 5. 必须遵守的规矩

1. **一个文件一个插件**，文件名 = `id`，全局唯一。
2. **不要 `import pyrogram` / `config` / 内核模块**，一切走 `ctx`。
3. **不要用 `@Client.on_message`**，用 `@ctx.on_message`（否则关不掉，破坏热插拔）。
4. **不要 `print`**，用 `ctx.log`。
5. **插件之间不要互相 import**。共用逻辑写成 `_` 开头的辅助文件，或下沉到平台。
6. **业务配置只进 `config_schema`**，禁止读写平台配置；持久化用 `ctx.kv`（关系型存储表名须带 `<plugin_id>_` 前缀）。
7. 自管理资源（后台 task、连接等）必须在 `teardown` 或 `ctx.add_cleanup` 里释放；`ctx.on_message` / `ctx.schedule` 注册的由平台自动清理。

---

## manifest.json（插件市场清单）

仓库根的 [manifest.json](manifest.json) 是插件市场清单，key = 插件 id。平台据此渲染市场，并靠 `version` 判断更新：

```json
{
  "my_feature": {
    "name": "我的功能",
    "version": "1.0.0",
    "author": "你",
    "description": "...",
    "path": "plugins/my_feature.py"
  }
}
```

- `path`：单文件以 `.py` 结尾，文件夹以 `/` 结尾。
- **改了插件代码 → 必须同步抬高 `version`**，否则插件商店识别不到更新、已安装的平台收不到推送。
- 商店里的插件**只在用户点「安装」时落盘，且绝不自动启用**（安全铁律），需用户在平台手动开启。

---

## 在平台中使用

本仓库是平台**内置的官方仓库**，无需手动添加：

1. 打开平台「插件管理 → 插件商店」，本仓库的插件会自动列在其中。
2. 找到想要的插件点「安装」（落盘到本地，**不会自动启用**）。
3. 到「我的插件」打开开关启用。需要的话点「配置」调参数。

平台会定时刷新商店列表，并对**已安装**插件按 `manifest.json` 的版本号推送更新（更新后手动「重载」生效）。新插件不会自动安装，始终由你在商店里手动选择。

---

完整平台规范见本仓库 [`docs/SPEC.md`](docs/SPEC.md) 与 [`docs/PLUGIN_GUIDE.md`](docs/PLUGIN_GUIDE.md)。
