# AWLottery → AWBotNest 插件迁移说明

> **本仓库定位**：把旧项目 `AWLottery`（六边形架构、整体式应用）里的功能，逐个改写成 **AWBotNest 平台规范的单文件 / 文件夹插件**，最终做成一个可被平台「从 GitHub 导入」**以及「插件仓库自动同步」**的插件市场仓库。
>
> **工作方式**：本文档是迁移总纲与进度表。**用户点名哪个功能，就迁移哪个**，迁移完成后回到本文件更新对应状态。未点名的不动手。
>
> **对齐平台规范**：本仓库跟随 `AWbotHub/SPEC.md`（当前 v1.0.0，含 §7.6 插件仓库自动同步）与 `PLUGIN_GUIDE.md`。规范更新时先回读这两份文件再继续迁移。

---

## 1. 两个项目的关系

| | 旧项目 `AWLottery` | 目标平台 `AWbotHub`(AWBotNest) | 本仓库 `AWBotNest-plugins` |
|---|---|---|---|
| 架构 | 六边形：`core/` `adapters/` `infra/` + `plugins/user|bot/` 整体加载 | 平台内核 `kernel/` + 单文件插件 `plugins/*.py` | 只放**符合平台规范的插件**，供平台导入 |
| 处理器注册 | `@Client.on_message(...)` 类级装饰器 | `@ctx.on_message(...)` 实例级，可热卸载 | 同平台 |
| 配置 | `from config.config import PT_GROUP_ID` 等全局配置 | 写进插件 `__plugin__["config_schema"]`，`ctx.config` 读 | 同平台 |
| 依赖 | 直接 `import pyrogram` / `from core import ...` | 一切走 `ctx` | 同平台 |
| 数据 | 直连 `models/` SQLAlchemy、TOML 状态 | `ctx.kv`（每插件独立 sqlite） | 同平台 |

---

## 2. 迁移规则（旧 → 新机械对照）

每迁一个文件，按这张表逐条替换。这是硬规则，来自平台 `SPEC.md` / `PLUGIN_GUIDE.md`。

| 旧写法（AWLottery） | 新写法（AWBotNest 插件） |
|---|---|
| `from core import Client, Message, filters` | 删除。`ctx.filters` 拿过滤器；handler 签名仍是 `(client, message)`，类型不用导入 |
| `@Client.on_message(filters.outgoing & filters.text, group=-12)` | `@ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-12)`，写在 `setup(ctx)` 内 |
| `@Client.on_callback_query(...)` | `@ctx.on_callback(...)` |
| `from config.config import PT_GROUP_ID` | 删。改成 `config_schema` 字段，`ctx.config["xxx"]` 读 |
| `from libs.log import logger` / `logger.xxx` | `ctx.log.xxx` |
| `print(...)` | `ctx.log.info(...)` |
| `from app import get_bot_app` → `bot_app.send_xxx` | `await ctx.bot.send(...)` / `ctx.bot.raw` |
| `from libs import others` 等内部工具 | 工具函数随插件带走：放进文件夹插件的 `_helpers.py`（`_` 开头），或内联 |
| 模块顶层注册处理器、模块顶层副作用 | 全部移进 `setup(ctx)`；纯函数可留模块级 |
| 直接 `models/` 数据库读写 | 简单状态用 `ctx.kv`；关系型必须表名带 `<plugin_id>_` 前缀 |
| 定时任务 `schedulers/` | `ctx.schedule(fn, "interval"/"cron", ...)` |

每个插件产物必须满足三段式：

```python
__plugin__ = { "name":..., "id": <文件名/目录名>, "version":..., "scope": "user|bot|both", ... }
async def setup(ctx): ...      # 注册处理器
async def teardown(ctx): ...   # 可选，仅清理自管理资源
```

**形态选择**：
- 无辅助模块、单一命令 → **单文件** `plugins/<id>.py`（如 `jupai`、`xjj`）。
- 带辅助函数 / 多文件 / 资源 → **文件夹** `plugins/<id>/__init__.py`，辅助放同目录 `_xxx.py`，包内 `from ._xxx import ...`。

**禁止**：插件之间互相 import、`import pyrogram`、读平台 `config.py` 业务键、`@Client.on_*`、`print`。

---

## 3. 功能清单与迁移进度

状态：⬜ 未开始 · 🟡 进行中 · ✅ 已完成 · ⏭️ 跳过(不迁)

> 用户点名后，把对应行状态改掉，并在「产物」列填新插件 id / 形态。

### 3.1 用户账号插件（`plugins/user/`，scope=user）

| 旧文件 | 功能 | 建议形态 | 产物 id | 状态 |
|---|---|---|---|---|
| `jupai.py` | 文字转举牌图 `/jupai` | 单文件 | `jupai` | ⬜ |
| `xjj.py` | 小姐姐视频 `/xjj` | 单文件 | `xjj` | ✅ |
| `zpr.py` | P站二次元图搜索 `/zpr` `/zp` | 单文件 | `zpr` | ⬜ |
| `self_delatemessage.py` | 删除自己消息 `/dme` | 单文件 | `self_delete` | ⬜ |
| `Plugins_function_summary.py` | `/zf` 转发 `/getmsg` 取消息 `/id` 查ID | 单文件(拆/合) | `util_tools` | 🟡 `.id`已拆出为 `id`，`/zf`/`/getmsg` 未迁 |
| `trans115search.py` | 115 网盘搜索 | 单文件 | `trans115search` | ⬜ |
| `movie_monitor_for115.py` | 115 电影监控 `/dyjk` | 文件夹 | `movie_monitor_115` | ⬜ |
| `keyword_auto_reply_listener.py` | 关键词自动回复监听 | 单文件 | `keyword_auto_reply` | ✅ |
| `blacklist_quick_ban.py` | 黑名单快速封禁 | 单文件 | `blacklist_quick_ban` | ⬜ |
| `calc_starting_bet.py` | 起始投注计算 | 单文件 | `calc_starting_bet` | ⬜ |
| `ai_human_reply.py` | AI 人形自动回复 | 文件夹 | `ai_human_reply` | ⬜ |
| `ai_explain.py` | AI 解释 | 文件夹 | `ai_explain` | ⬜ |
| `auto_prize_sender.py` + `_prize_sender_helpers.py` | 自动发奖 | 文件夹 | `auto_prize_sender` | ⬜ |
| `bomb_game_handler.py` | 数字炸弹（用户侧） | 文件夹 | `bomb_game` | ⬜ |
| `quiz_handler.py` | 答题游戏（用户侧） | 文件夹 | `quiz_game` | ⬜ |
| `games/red_packet.py` + `_red_packet_ocr.py` | 拼手气红包抢包 + OCR | 文件夹 | `red_packet_grab` | ⬜ |
| `hdhive_lottery.py` | HDHive 抽奖 | 文件夹 | `hdhive_lottery` | ⬜ |
| `auto_lottery_common.py` / `auto_lottery_for_xiaocai.py` | 通用/小菜自动抽奖 | 文件夹 | `auto_lottery` | ⬜ |
| `lottery/` (getInfo/raiding/redpocket_pie/spinThePrizeWheel/transform/ydx + handler) | 朱雀系列（查询/大劫/红包雨/转盘/转账/YDX） | 文件夹 | `zhuque_lottery` | ⬜ |
| `red_packet/` (button/dianyingpai/integration/handler) | 红包集成（按钮红包/电影派红包） | 文件夹 | `red_packet_integration` | ⬜ |
| `transfer/` (audiences/azusa/hddolby/ptvicomo/springsunday/u2_dmhy/zm/mock + handler) | 多站点转账排行榜 | 文件夹(每站点一插件 或 合一) | `transfer_*` | ⬜ |

### 3.2 Bot 账号插件（`plugins/bot/`，scope=bot）

| 旧目录 | 功能 | 建议形态 | 产物 id | 状态 |
|---|---|---|---|---|
| `commands/basic.py` `setup.py` `state.py` | 基础命令 `/start` 状态 | 文件夹 | `bot_basic` | ⬜ |
| `commands/login.py` | 交互式登录（平台内核已接管账号生命周期，**多半不迁**） | — | — | ⏭️ |
| `commands/ai_chat.py` | AI 对话命令 | 文件夹 | `bot_ai_chat` | ⬜ |
| `commands/*_set.py` / `*_config.py` | 各功能配置命令（举牌/抽奖/红包/陷阱/通知…） | **多半不迁**：配置改由前端 `config_schema` UI | ⏭️/按需 | ⬜ |
| `commands/mysql_backup.py` `mysql_restore.py` `db_to_excel_execute.py` | 数据库备份/恢复/导出 | 文件夹 | `db_backup` | ⬜ |
| `commands/update_restart.py` `scheduler_control.py` | 更新重启/调度控制（平台职责，**多半不迁**） | — | — | ⏭️ |
| `games/number_bomb.py` + helpers + `bomb_game_monitor.py` `bomb_config_set.py` | 数字炸弹游戏（Bot 侧） | 文件夹 | `bomb_game_bot` | ⬜ |
| `games/quiz_game.py` `quiz_config_set.py` | 答题游戏（Bot 侧） | 文件夹 | `quiz_game_bot` | ⬜ |
| `menus/*` (main/ai/help_me/leaderboard/interactive) | Bot 菜单系统 | 文件夹 | `bot_menus` | ⬜ |

### 3.3 定时任务（`schedulers/`，多为 scope=user/both）

| 旧文件 | 功能 | 产物 id | 状态 |
|---|---|---|---|
| `universal/auto_avatar.py` | 定时换头像 | `auto_avatar` | ⬜ |
| `universal/auto_changename.py` | 定时换昵称 | `auto_changename` | ⬜ |
| `universal/custom_auto_reply.py` | 自定义定时回复 | `custom_auto_reply` | ✅ |
| `universal/log_cleaner.py` | 日志清理（平台或插件，待定） | `log_cleaner` | ⬜ |
| `universal/supervisor_monitor.py` | Supervisor 监控（平台职责） | — | ⏭️ |
| `zhuque/fireGenshinCharacterMagic.py` | 朱雀魔法卡定时 | 并入 `zhuque_lottery` | ⬜ |

### 3.4 明确不迁（平台底座 / 内核已覆盖）

`core/` `adapters/` `infra/` `libs/`(平台基础) `models/database.py` `main.py` `app.py` `login.py` `migrations/` `tests/` `scripts/` `docker*` —— 这些是旧项目的应用底座，平台 `kernel/` + `core/` 已提供等价能力，**不作为插件迁移**。其中具体的业务工具函数（如 `libs/others.py` 里某个被某插件用到的 helper）在迁移该插件时**随插件带走**。

---

## 4. 每个插件的迁移检查清单（Definition of Done）

迁移单个插件完成的标准：

- [ ] `__plugin__` 字典完整：`name` / `id`(=文件名或目录名) / `version` / `scope`，建议补 `author` `description` `default_enabled`
- [ ] 所有处理器在 `setup(ctx)` 内用 `ctx.on_message` / `ctx.on_callback` 注册
- [ ] 无 `import pyrogram`、无 `from core/config/kernel import`、无 `@Client.on_*`、无 `print`
- [ ] 旧的全局配置项 → `config_schema` 字段（带 `label`/`section`/`show_if`），代码用 `ctx.config[...]` 读
- [ ] 日志走 `ctx.log`；定时任务走 `ctx.schedule`；持久化走 `ctx.kv`（或带前缀的表）
- [ ] 辅助模块以 `_` 开头放在文件夹插件内，包内相对导入；不跨插件 import
- [ ] 关键逻辑有中文注释，尽量带类型提示
- [ ] 在平台 `.venv` 中能被识别、启用、热卸载（导入与 `setup` 不报错）
- [ ] 本文件 3.x 进度表对应行更新状态 + 产物 id

---

## 5. 仓库结构（产物）

```
AWBotNest-plugins/
├── MIGRATION.md          # ← 本文件
├── manifest.json         # 插件市场清单（迁移过程中逐步补充）
└── plugins/
    ├── jupai.py          # 单文件插件示例
    ├── xjj.py
    └── <id>/             # 文件夹插件
        ├── __init__.py   # __plugin__ + setup
        └── _helpers.py   # 私有辅助
```

> `manifest.json` 格式（key = 插件 id），平台据此渲染插件市场：
> ```json
> { "jupai": {"name":"举牌","version":"1.0.0","author":"AW","description":"...","path":"plugins/jupai.py"} }
> ```

### 5.1 关于「插件仓库自动同步」（SPEC §7.6）

本仓库可被平台配置为**自动同步源**（系统设置 → 插件仓库），平台按间隔轮询、自动拉取新增/更新的插件。因此：

- **每个迁移完成的插件都必须登记进 `manifest.json`，并写准 `version`**。平台靠版本号判断「有没有更新」：版本号变了才重新下载覆盖；本地已存在且无版本信号则跳过。
- 改了某插件代码 → **必须同步抬高它在 manifest 里的 `version`**，否则自动同步端拉不到更新。
- 自动同步**只下载、不启用**（安全铁律），用户仍需在平台手动开启。所以 `default_enabled` 在导入场景下不生效，主要供本地直接放入 `plugins/` 时用。

---

## 6. 进度日志

> 每次迁移在此追加一行（日期 · 插件 · 说明）。

- 2026-06-27 创建迁移总纲，完成功能盘点。等待用户点名首个迁移目标。
- 2026-06-27 对齐 SPEC v1.0.0（新增 §7.6 自动同步说明）。
- 2026-06-27 迁移首批 4 个插件并登记 manifest.json：
  - `id`（查ID，从 Plugins_function_summary.py 的 get_id 拆出）
  - `xjj`（小姐姐视频）
  - `keyword_auto_reply`（关键词自动回复，多规则改用 config 内 JSON）
  - `custom_auto_reply`（定时自动回复，多任务改用 config 内 JSON，每任务一个 cron）
  - 均在平台 .venv 通过：AST 元数据校验 + 真实 import + setup(mock ctx) 无错。
