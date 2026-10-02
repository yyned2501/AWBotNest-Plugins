# SPEC：天空刮奖（scratch）V1 → V2 移植

> 状态：待落地（assignee=coder）· 作者：architect · 契约优先，冲突以本文件为准

## 0. 一句话

把 2026-09-11 从 V1 树移除的单文件插件 `scratch`（天空刮奖 v1.6.2，Pyrogram 运行时）按 AWBotNest V2 插件契约移植为 `plugins_v2/scratch.py`（Telethon 1.44 运行时），**行为不变**，并带测试、manifest 条目，最后在本机实例装载验证。

## 1. 背景与实测证据

| 事实 | 证据 |
| --- | --- |
| V1 源码可从 git 历史取回 | `git show f4d7914^:plugins/scratch.py` → 495 行，`__plugin__["version"]="1.6.2"`，`name="天空刮奖"`，`scope="user"` |
| 移除时间与提交 | `f4d7914 \| 2026-09-11 16:49 \| chore(plugins): 移除 scratch / battleroyale / learning`（提交信息未写原因） |
| 平台已是 V2 / Telethon | `AWBotNest-v2/requirements.txt: telethon==1.44.0`；`pyproject.toml: "telethon>=1.44,<2"` |
| V2 插件树 | `AWBotNest-Plugins/plugins_v2/{juai_checkin,skyDropAnswer,skyGame,skyRedPacket}` |
| V1 代码在 V2 上必崩（根因） | 实例 `data/plugin_events.jsonl`：`scratch:event:on_scratch_card — AttributeError: 'Message' object has no attribute 'caption'`。Telethon `Message` 无 `caption`，V1 的 `message.text or message.caption` 直接抛错 |
| 实例当前未装 | `GET http://localhost:18001/api/plugins` → 仅 `juai_checkin`、`skyGame`；`data/plugins/scratch/` 为空目录残留；`data/kv/` 无 scratch |
| 图标仍在，无需新建 | `icons/scratch.svg` 存在（`8b4ca9a` 引入，未被移除） |
| 仓库测试基线 | `cd /home/hermes/projects/AWBotNest-Plugins && .venv/bin/python -m pytest tests -q` → **481 passed in 12.45s** |
| 目标群 / Bot（V1 默认配置） | `target_group=-1001326208894`、`bot_id=0`（0 = 不按 Bot 过滤）；开发文档记录 Bot 为 `@lucifer_hdsky_bot`（散财童子），见 `~/.hermes/scripts/scratch_plugin_spec.md` |

玩法（照搬，不改）：群里发 `/scratch` → Bot 回一张 3×3 刮刮乐（每格 100 银元）→ 插件随机逐格点击 → 一旦「累计派奖 ≥ 已刮格数×100」立即点「放弃」停手 → 没停就按冷却连发下一张 `/scratch` → 连续亏损达上限自动停止（关插件重开重置）。

## 2. 组件边界

- 形态：**单文件插件** `plugins_v2/scratch.py`，`__plugin__["id"] = "scratch"`（必须等于文件名）。
- scope：`user`（监听用户账号侧消息；刮刮乐卡片是 Bot 在群里发的 incoming 消息）。
- 状态：**仅模块级内存** —— `_playing`（串行互斥）、`_consecutive_loss`、`_auto_stopped`、`_seen`（去重，TTL 300s）。**不引入 `ctx.storage`/`ctx.kv` 持久化**（与 V1 行为一致；停用/重载即重置，这是 V1 明确写在提示里的语义）。
- 依赖：仅标准库（`asyncio`/`random`/`re`/`time`/`inspect`），`requirements` 省略。
- 配置界面：默认 `render_mode`（schema 表单），**不做 Vue**。
- 边界红线：所有 Telegram 交互经 `ctx`；禁 `import pyrogram` / `import kurigram`；禁 `ctx.filters`（V2 不提供）；禁 `@Client.on_message`；禁 `print`。

## 3. 接口契约（V1 → V2 映射表，逐处必须落到位）

| 用途 | V1（Pyrogram）写法 | V2（Telethon 1.44）必须改成 |
| --- | --- | --- |
| handler 注册 | `@ctx.on_message(filter, group=-9)` | `@ctx.on_message()` —— **V2 的 `on_message` 签名只有 `pattern/chats/incoming/outgoing/interactive`，没有 `group`、没有 filters** |
| handler 回调 | `async def h(client, message)` | `async def h(*args, **kwargs)`，用 `_extract_message(args, kwargs)` 取 `(message, event)`（单 event 时 `event.message` 才是消息） |
| 取用户 client | 回调第二参数 | `args[0]` 是 event → `client = event.client` |
| 消息文本 | `message.text or message.caption` | `getattr(m,"text",None) or getattr(m,"raw_text",None) or ""`（**Telethon 无 `caption`，这正是崩溃根因**） |
| 内联键盘 | `reply_markup.inline_keyboard[r][c]` | `reply_markup.rows[r].buttons[c]`（Telethon；**保留 `inline_keyboard` 兼容分支无所谓，但主路必须是 rows/buttons**） |
| 按钮 callback data | `btn.callback_data`（str） | `btn.data`（**bytes**）→ 前缀判断 `data.startswith(b"scratch:")`，取部分用 `.decode()` |
| 点击按钮 | `msg.click(x=col, y=row)` | `msg.click(i=row, j=col)`（已在 `.venv/…/telethon/tl/custom/message.py` 核实签名 `async def click(self, i=None, j=None, *, text=None, …)`；位置参数即 (行, 列)）。按签名自适应：`{"i","j"} & params` → `click(i=, j=)`，`{"x","y"} & params` → `click(x=, y=)`，否则位置参数 |
| 点击返回 | `result.message` | 同（`BotCallbackAnswer.message` 是 str）；兜底 `getattr(result, "text", "")` |
| 重拉消息 | `client.get_messages(chat_id, msg_id)` | `await client.get_messages(message.chat_id, ids=msg_id)` —— **Telethon 第二个位置参数是 limit，必须用 `ids=` 关键字**（见 §9.1 回退链） |
| 群 ID | `message.chat.id` | `message.chat_id`（supergroup 为 `-100…`，与配置值同形） |
| 群名 | `message.chat.title` | `getattr(getattr(m,"chat",None),"title","")`（Telethon entity 同样有 title） |
| Bot 过滤 | `ctx.filters.user(bot_id)` | handler 内比对 `_sender_id(message, event)`（`bot_id=0` 时不过滤，与原语义一致） |
| 「回复的是我自己」 | `ctx.owner_id` + `reply_to_message.from_user.id` | **V2 无 `ctx.owner_id`（已核实 `awbotnest/context.py` 无此属性）** → `reply = await event.get_reply_message()`，判 `getattr(reply,"out",False)`；取不到/非自己 → 不处理（宁漏不抢，照抄 `skyDropAnswer/models.py:_replies_to_own`） |
| 发 `/scratch` | `ctx.user.send(chat_id, "/scratch")` | 兜底链：`ctx.user.send` → `ctx.user.raw.send_message` → `ctx.bot.raw.send_message`（照抄 `skyGame/games/drop_guard.py:151-179`） |
| 通知 | `ctx.notify(text, level=…, category=…, account=client)` | **同签名可用**（已核实 `context.py:307`） |
| 消息链接 | `message.link` | Telethon 无 → `getattr(m,"link","")` 兜底（空则显示空串；**不允许为此去调 API**） |
| 配置读取 | `ctx.config.get(k, d)` | 同（`ctx.config` 是同步 dict） |
| 调度/后台任务 | `ctx.create_task` 不适用 | 本插件是事件驱动，**不需要** `ctx.create_task`/`ctx.schedule_*` |

## 4. 数据格式

- 配置项（键名/默认值/语义**全部沿用 V1**，不改）：
  - `target_group`: string，默认 `"-1001326208894"`（多行取首行）
  - `bot_id`: number，默认 `0`（0 = 不按 Bot 过滤）
  - `click_delay`: slider，默认 `0.6`（0.3–2.0，+±20% 抖动）
  - `card_cooldown`: slider，默认 `5`（2–30，另加 0–3s 随机）
  - `max_consecutive_loss`: number，默认 `5`（1–20）
- callback data：`scratch:{卡号}:{格号}`（格号 1–9，行优先 1–3/4–6/7–9），特殊按钮 `all`（一键刮开）、`abandon`（放弃）。V2 侧类型是 bytes。
- 卡片识别：文本含 `刮刮乐` **且** 存在 data 以 `scratch:` 开头的按钮。
- 点击回执解析：`获得\s*(\d+)\s*银元`；解析失败回退消息文本 `已派奖：(\d+) 银元`（差分累计）。
- 通知文案：沿用 V1 模板（🏠 群组 / 🎰 刮奖结果 卡号·格数·累计·成本·净 / 🔗 链接），自动停止通知同样沿用。

## 5. 量级约束

- 单卡成本上限 900 银元（9 格 × 100）；单卡耗时 ≈ 9 × click_delay + 网络往返，秒级。
- 单实例串行：`_playing` 为真时新卡片直接跳过（不支持并发刮多张）。
- 去重：`_seen` TTL 300s；每轮 `_prune_seen()` 清理，防无界增长。
- 冷却：卡间 `card_cooldown + random(0,3)` 秒；连亏 `max_consecutive_loss` 张 → 自动停（不再连锁）。
- handler 走**普通路径**（不传 `interactive=True`）：一次刮卡是 9 次点击 + 数次 re-fetch 的秒级长任务，不属于「延迟敏感短回调」。

## 6. 非目标（这期明确不做）

1. 不重写玩法/策略（随机顺序、回本即停、连亏停止、连锁下一张全部照搬）。
2. 不改配置项键名、默认值、语义；不做 Vue 配置面板。
3. 不引入 kv/持久化统计、不做历史战绩/盈亏报表。
4. 不支持多群并发、不支持多账号实例（`instance_mode` 保持默认 `shared`）。
5. 不改散财童子侧任何东西；不碰其他插件（**不 import 其他插件**）。
6. 不迁移 V1 的存量配置值（V2 实例上由使用者在表单重填）。
7. **不 push（见 §8.6）**：只 commit，推送/上线窗口由主人放行。

## 7. 交付物

1. `plugins_v2/scratch.py`（新文件，单文件插件）
2. `manifest_v2.json` 增加 `plugins.scratch` 条目（`name`/`version`/`author`/`description`/`icon`/`tags`/`scope: "user"`/`plugin_api_version: 2`/`path: "plugins_v2/scratch.py"`），`version` 与 `__plugin__["version"]` 一致
3. `tests/test_scratch_v2.py`（参考 `tests/test_skydropanswer_v2.py` 的写法：纯函数/解析/点击路径用假 message 对象覆盖）
4. 本机实例装载并启用：把 `plugins_v2/scratch.py` 复制到 `/home/hermes/projects/AWBotNest-v2/plugins/scratch.py`，在平台上启用（**不走商店、不 push 也能验证**）

## 8. 验收命令 + 期望值

```bash
# 8.1 测试（基线 481，新增只许加不许减；任何既有用例失败 = 不通过）
cd /home/hermes/projects/AWBotNest-Plugins && .venv/bin/python -m pytest tests -q
# 期望：>= 481 passed, 0 failed

# 8.2 lint（line-length=120）
.venv/bin/ruff check plugins_v2/scratch.py tests/test_scratch_v2.py
# 期望：0 error

# 8.3 契约静态扫描（红线，输出必须为空）
grep -nE "import pyrogram|import kurigram|ctx\.filters|@Client|(^|[^_.a-zA-Z])print\(" plugins_v2/scratch.py
grep -nE "\.caption|\.callback_data|inline_keyboard|click\(x=|group=-" plugins_v2/scratch.py
# 8.3b 必须存在的 V2 写法（每条至少 1 命中）
grep -nE "get_reply_message|rows|\.data|click\(i=|ids=" plugins_v2/scratch.py

# 8.4 manifest 一致性
python3 - <<'PY'
import json
m2 = json.load(open('manifest_v2.json'))['plugins']['scratch']
src = open('plugins_v2/scratch.py', encoding='utf-8').read()
import ast, re
t = ast.literal_eval(re.search(r'__plugin__\s*=\s*(\{.*?\n\})', src, re.S).group(1))
assert m2['version'] == t['version'], (m2['version'], t['version'])
assert m2['path'] == 'plugins_v2/scratch.py'
assert m2['scope'] == t['scope'] == 'user'
print('manifest ok', m2['version'])
PY

# 8.5 实例装载（本机 AWBotNest-v2，端口 18001）
TOKEN=$(curl -s http://localhost:18001/api/auth/login -X POST -H 'Content-Type: application/json' \
  -d '{"username":"yangyang","password":"<见 pass awbotnest/admin>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18001/api/plugins | python3 -c 'import sys,json;print([p["id"] for p in json.load(sys.stdin)])'
# 期望：列表含 "scratch"
# 启用后：GET /api/plugins/scratch → enabled=true；日志出现插件自身「已启用」行、无 traceback
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18001/api/v1/logs/plugins/scratch?limit=50
# 期望：无 error / 无 AttributeError

# 8.6 落盘
git status --short && git log --oneline -1
# 期望：一个 commit（只 commit，不 push）；文件数 = plugins_v2/scratch.py + tests/test_scratch_v2.py + manifest_v2.json（3 个，外加本 spec 若未提交）
```

## 9. 必须实测确认项（不许用「应该可以」替代）

1. **重拉消息（本移植最大不确定项）**：全仓库 grep `get_messages` **0 命中**，V2 插件生态无先例。主写法 `await client.get_messages(message.chat_id, ids=msg_id)`；若抛 `Could not find the input entity` 或返回 None，回退 ①`chat = await event.get_chat()` 再 `get_messages(chat, ids=msg_id)`；仍失败回退 ②用事件里的 message 快照点击（功能降级：按钮位置可能错位，但回执解析失败会用累计值结算，不会崩）。**必须在实例日志里跑出一次真实 re-fetch 成功记录，或给出「两条回退都试过、失败原因」的实测结论**——不许只写不验。
2. **点击返回类型**：Telethon 1.44 `Message.click` 返回 `BotCallbackAnswer`，`.message` 是 str；解析不出「获得 X 银元」时按 §4 回退，仍解析不出按 0 计（V1 行为）。
3. **回复归属**：`event.get_reply_message()` 在 V2 运行时可用（`skyDropAnswer` v2.1.12 已用同款写法跑通，其 changelog 明确写了「改用 Kurigram Event 的 get_reply_message() 取回被回复消息、看它的 out 标记」）。
4. **群 ID 归一化**：Telethon `message.chat_id` 对 supergroup 是 `-100…`，与 V1 配置默认值同形；handler 内比对 `str(message.chat_id) == str(target_group)`（V1 是 int 比较，V2 允许字符串归一化，但**必须在测试里覆盖 `-1001326208894` 这一形**）。
5. 真机跑一张（**真实开销，需主人放行，不在 coder 范围内**）：群里发 `/scratch` → 插件识别并自动刮开 → 通知到账。此项由 architect 在主人放行后验收。

## 10. 参考实现（仓库内已跑通的 V2 代码，照着抄写法）

| 用途 | 位置 |
| --- | --- |
| 回调取参兼容（单 event / (client,message)） | `plugins_v2/skyRedPacket/__init__.py:210` `_extract_message` |
| 发送者 / 群 / 回复归属判定 | `plugins_v2/skyDropAnswer/models.py:135-229` |
| 内联按钮读取（rows/buttons） | `plugins_v2/skyDropAnswer/answer.py:30-45` |
| 点击（按签名自适应 + 结果取文案） | `plugins_v2/skyRedPacket/__init__.py:258-294`、`plugins_v2/skyDropAnswer/answer.py:86-100` |
| 发送兜底链（user → user.raw → bot.raw） | `plugins_v2/skyGame/games/drop_guard.py:151-179` |
| 通知用法 | `plugins_v2/skyDropAnswer/answer.py:184-202` |
| V2 插件测试写法 | `tests/test_skydropanswer_v2.py` |
| V1 原始实现（逻辑源，不必改） | `git show f4d7914^:plugins/scratch.py` |
| V1 期玩法/接口文档 | `~/.hermes/scripts/scratch_plugin_spec.md` |

## 11. 冲突规则

本 spec 与现有代码/参考实现冲突时，**以本 spec 为准**；spec 自身有问题（例如某个 API 在 Telethon 1.44 不存在）→ **停下来把实测证据贴回卡里提问**，不许自行改契约（尤其不许改配置项语义、不许为了绕障碍改玩法）。
