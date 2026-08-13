# AWBotNest 插件常见坑

写/修任何插件前：①先读插件指南与模板；②再读 1–3 个相似的在用插件；③复用已验证的触发/过滤/配置模式，别凭 Pyrogram 通用习惯猜。跳过这步是「能加载但行为错」的最快途径。

## 契约类

**`id` 与文件名/目录名不一致** — 插件被判无效/无法启用。单文件 `plugins/foo.py`→`"id":"foo"`；目录包 `plugins/foo/__init__.py`→`"id":"foo"`。

**`__plugin__` 不是纯字面量字典** — 平台用 AST 静态读取，不执行代码。别动态构造、别用辅助函数填必填字段。

**用 `@Client.on_message` 或直接 `import pyrogram`** — 无法热卸载、违反契约。一律 `@ctx.on_message` / `@ctx.on_edited_message` / `@ctx.on_callback`。

**用 `print`** — 日志不一致、难追踪。用 `ctx.log.info/warning/error`。

## 配置类

**业务配置写在 `config_schema` 之外** — 只能靠手动改隐藏配置、配置 UI 缺项。业务设置全进 `__plugin__["config_schema"]`，经 `ctx.config` 读，别依赖平台配置。

**配置字段缺 `default`** — 存取不一致、全新安装行为异常、运行代码取不到值。每个字段都给合理 `default`，运行期回退值与之一致。

**UI 重构时改了字段 key** — 已保存配置失效。纯 UI 重构保持字段 key 稳定。

## 触发类

**命令型用户插件过滤器选错** — 插件加载成功但命令永不触发。对用户命令插件，`ctx.filters.outgoing & ctx.filters.text` + 手动文本匹配往往比猜 `ctx.filters.command(...)` 稳。先看相似在用插件怎么触发。

**`ctx.filters.create()` 传入 `async def` 函数** — 插件加载成功、handler 注册了，但 filter 永远不匹配（因为平台/filters.create 期望同步函数）。`ctx.filters.create(fn)` 的 `fn` 必须是同步 `def`，不能是 `async def`。

**`ctx.filters.outgoing` 在 `ctx.filters.create(fn)` 内部不工作** — 在 filter 函数里调 `ctx.filters.outgoing(_, __, m)` 或类似方式判断消息是否自己发的，结果不可靠。正确做法：用 `message.reply_to_message.from_user.is_self`（Pyrogram 原生属性，同步判断），放在 sync `def` 里经 `ctx.filters.create()` 包装。别用 kv/缓存记录自己发的消息来判断回复。参考模式：

```python
def _reply_to_own_filter(_, __, m):
    return bool(
        m.reply_to_message
        and m.reply_to_message.from_user
        and m.reply_to_message.from_user.is_self
    )

_filter = ctx.filters.text & ctx.filters.create(_reply_to_own_filter)

@ctx.on_message(_filter)
async def handler(client, message):
    ...
```

## Vue 类

**前端配置与后端默认值漂移** — 配置页一套字段/默认值，运行时另一套。以后端 `DEFAULTS` 为权威形状，Vue 字段与之对齐；改键名后复查 `ctx.config.get(...)`。

**改了 Vue 源码没重建 `frontend/dist`** — 源码更新了，安装/发布的 UI 还是旧的。改完 `npm run build` 并提交 `dist/`，核对发布产物与源码一致。

## 发布类

**发布时元数据只改了一处** — 卡片图标/版本/描述/changelog 在某些界面过期。发往 AWBotNest-Plugins 时同步 `__plugin__` 与 `manifest.json` 的重复元数据，尤其 version/icon/description/changelog。

## Vue 前端类

**Vue 配置页与后端默认值不一致** — 配置页显示一套字段/默认值，运行期用的是另一套。前端表单结构与后端 `DEFAULTS` 各自演进导致。修复：后端 `DEFAULTS` 保持权威、Vue 字段与之对齐、改配置后 `ctx.config.get(...)` 检查键是否被改名/删除。

**改了 `frontend/src` 没重新构建 `dist`** — 源码看着更新了，装上去的 UI 还是旧行为。平台加载的是构建产物：Vue 改动后必须 `npm run build` 且提交 `frontend/dist`。

## 资源与依赖类

**插件自有资源没清理** — 停用/重载后残留任务、连接、脏状态。平台只自动清理 ctx 注册的 handler/任务；自管理资源用 `ctx.add_cleanup(...)` 或在 `teardown(ctx)` 释放。

**声明了不支持的依赖** — 启用时依赖安装失败。确认 Python 3.13 兼容、优先用平台已装库、声明进 `requirements`、别在插件里自己装包。

## 本仓库实战补充（skyDropAnswer 等踩过的）

**学习/AI 生成的模板把「会变化的值」写死** — 同类题换个符号/数字就被当成全新题型，重复生成模板（如把 🔺/💎 写进正则与脚本，一符号一模板）。正则要抓题型结构、用 `(.+?)`/`\d+` 占位，脚本里动态解析变量，绝不硬编码具体值。

**去重靠正则字符串精确相等** — AI 每次生成的正则字符串都不同，精确相等判不出同类。应按 filename/题型/归一化正则/样例互配等多信号判同类。

**`manifest.json` 版本落后于 `__plugin__`** — 商店识别不到更新，已安装实例收不到推送。改代码必须同步抬高 manifest 版本。

**用受限 builtins 沙箱执行 AI 生成的模板** — `__import__=None` 会让模板里的 `import re` 直接炸。本仓库模板需要标准库能力，不做沙箱限制。

**重写模板文件时字符串字段直接 f-string 插值** — 含换行/引号/emoji 的 SAMPLE 会生成非法字符串字面量、模板加载失败。字符串字段统一用 `repr`（`!r`）写入。

**`message.click(n)` 单参数点按钮 + 把答案当下标** — 只对「答案=按钮序号」的题型有效；数学题等「答案为按钮上的值」会算出越界下标被静默跳过。应按按钮文本匹配答案（精确>数值>包含），用 `click(x=col, y=row)`。

## 收尾自检

- [ ] `id` = 文件名/目录名
- [ ] `__plugin__` 是纯字面量字典、必填字段齐全
- [ ] handler 都在 `setup(ctx)` 内经 `ctx` 注册，无 `@Client.on_message`、无 `import pyrogram`、无 `print`
- [ ] 配置全在 `config_schema`、字段有 `default`、运行期回退对齐
- [ ] 运行状态用 `ctx.kv`/`ctx.data_dir`，自有资源有清理
- [ ] Vue 默认值与构建产物已同步
- [ ] 依赖已声明、兼容 3.13、未自装
- [ ] 长时调度任务适当时 `ctx.report_progress` 报进度；有 `self_check(ctx)` 则只读、15 秒内完成
- [ ] 发布时 `__plugin__` 与 `manifest.json` 元数据一致
