# HDSky 门户 API：天空游戏插件

> 维护规则：本文档只记录由插件实现、运行日志或实测响应证实的接口契约。尚未证实的字段、状态或请求参数必须明确标为“待验证”，不得据此编写猜测性请求。
>
> 每次通过运行日志、抓包或实测确认/更正外部 API 行为时，必须在同一提交更新本文档。

## 认证与传输

炸金花逻辑通过 `plugins/skyGame/games/hdsky.py` 的 `HdskyClient` 访问门户：

- Cookie 文件和门户根地址由插件配置提供；
- 客户端负责 CSRF / requestKey 获取、请求 JSON 编解码，以及遇到 401 时触发 Cookie 续期后重试；
- 遇到 403「请求来源无效」（CSRF 失效）时，客户端作废缓存的 CSRF、重取一次并重试原请求（仅一次，不死循环）；非 CSRF 的 403（如权限不足）不重试；
- 游戏模块不得自行管理认证头、Cookie 或 CSRF。

## 已确认接口

| 用途 | 方法与路径 | 请求体 | 证据 |
| --- | --- | --- | --- |
| 轮询牌局状态 | `GET /api/portal/zhajinhua` | 无 | `zhajinhua.py` 的 `_poll_loop()` |
| 加入牌桌 | `POST /api/portal/zhajinhua/join` | `{}` | `_poll_loop()` |
| 执行牌局动作 | `POST /api/portal/zhajinhua/action` | `{ "action": "<服务端 actions 中声明的原始值>" }` | `_act_on_hand()`、弃牌和看牌逻辑 |
| 读取养马状态 | `GET /api/portal/horse` | 无 | `horse.py` 的 `_care_once()`，实测响应 |
| 执行养马动作 | `POST /api/portal/horse/action` | `{ "action": "walk"\|"feed"\|"revive", "requestKey": "<web_+32hex>", "feedType"?: "weed"\|"fine"\|"divine" }` | `_horse_action()`，实测响应 |

动作只能在轮询响应的 `game.self.isTurn == true` 时，且动作值出现在 `game.actions` 列表中时提交。插件不得根据本地猜测构造不在该列表中的动作。

## 已确认状态字段

`GET /api/portal/zhajinhua` 的响应含 `game` 对象。插件当前使用以下字段：

| 路径 | 含义 / 用法 |
| --- | --- |
| `game.roundId` | 本局牌局标识；改变时重置本局跟踪状态。 |
| `game.phase` | 门户阶段文本；目前仅记录/诊断，不作为动作授权条件。 |
| `game.pot` | 当前底池。 |
| `game.callBet` | 当前动作成本。 |
| `game.actions` | 当前可提交动作的列表；动作授权的唯一来源。已观察到 `join`、`call`、`peek`、`fold`、`open`、`raise`、`showdown`。 |
| `game.self.joined` | 本账号是否已加入本局。 |
| `game.self.isTurn` | 是否轮到本账号行动。 |
| `game.self.alive` | 本账号是否仍在局。 |
| `game.self.hand` | 已看牌时的手牌文本。 |
| `game.self.handType` | 已看牌时的牌型文本；可能为 `手牌 → 同花` 这类组合文本。 |
| `game.self.foldConfirm` | 弃牌是否需要第二次提交确认。 |
| `game.players` / `game.seats` | 公开玩家列表（门户可能使用任一字段）。 |
| `player.id` | 玩家稳定标识。 |
| `player.isSelf` / `player.self` | 是否为本账号。 |
| `player.alive` / `player.active` | 玩家是否仍在局。 |
| `player.seen` | 是否已看牌。 |
| `player.bet` | 玩家公开下注额；用于相邻轮询识别下注增加。 |
| `player.lastAction` | 最近动作文本；在下注额缺失时辅助识别跟注或加注。 |

## 炸金花跟踪语义

- 对手由蒙牌变为 `seen == true`：记录**上牌快照**，包含上牌前底池、成本，以及其面对的蒙牌对手数和已有牌力门槛的已看牌对手。
- 我方执行 `peek` 前，也按同一行动前状态记录我方上牌门槛；我方后续 `call`、`raise` 或 `open` 前会再次记录，并保留历史最大值。
- 已看牌对手下注增加或最近动作变为跟注/加注：记录**继续下注快照**。
- 每次快照先由 `callBet / (pot + callBet)` 得到该局面的实际胜率盈亏平衡点；再以 `P(t) = t^B × Π((t - tᵢ)/(1 - tᵢ))` 按蒙牌与已看牌对手权重二分反推行动者的单挑牌力门槛。
- 推断看牌对手牌力时，上牌快照和继续下注快照都参与计算，并取两次决策所需的较高单挑门槛；缺少任一已观测阶段时，日志必须标注降级来源。
- 单挑对手未看牌 → 直接跟注不自主看牌；对手已看牌 → EV 为负也跟注不弃牌（`_act_on_hand()` 的 `_is_heads_up()` 分支）。
- 参与的对局结束（`roundId` 变化）时，推送最终结果通知：手牌、牌型、存活状态。
- 遛马动作用于冷却拒绝时返回外层 `ok: true`、`result.code == "cooldown"`、`result.remainMs`（剩余毫秒）、`result.message`；冷却约 45 分钟，且期间 `state.canWalk` 仍为 `true`，不能用来判断是否可遛。插件记下 `remainMs` 换算的到期时间退避，未到不再尝试；`cooldown` 不计入失败计数，连续真失败 3 次后跳过本轮。（`horse.py` 的 `_care_once()`）
- 养马实测字段：`stats.walkCountToday/walkMax`（每日遛马上限）、`stats.feedCountToday/feedMax`、`profile.satiety`（饱腹度）、`horse.balance`（银元）、`profile.state.{isDead,canWalk,canFeed}`。

## 待现场验证

- `showdown` 是否在所有局面都只需 `{ "action": "showdown" }`，或是否需额外目标/确认字段。
- 对手发起应战后 `game.phase` 的实际取值；当前插件不会用它阻断行动。
- `player.bet` 是总投入还是本轮增量，以及门户在蒙牌与看牌阶段的精确费用规则。

发生应战失败时，记录并保留（脱敏后）`roundId`、`phase`、`actions`、`self` 关键状态与 POST 错误，用于补全本节。