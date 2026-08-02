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
| `game.actions` | 当前可提交动作的列表；动作授权的唯一来源。已观察到 `join`、`call`、`peek`、`fold`、`open`、`raise`、`showdown`。实测：`open`/`showdown` 仅在单挑局面出现，且只在对手已看牌时给出；单挑双方都蒙牌时仅 `peek/fold/call/raise`（开不了牌）。 |
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
- 单挑对手未看牌 → 直接跟注不自主看牌（`_act_on_hand()` 的 `_is_heads_up()` 分支）。
- 单挑且对手已看牌、EV 为负 → 比牌止损（`showdown`/`open`，门户允许即用）或弃牌止损（无比牌动作时），绝不继续跟注；旧逻辑「EV为负也不弃牌」曾导致终胜率 0% 仍连跟多轮、单局巨亏（`_heads_up_stop_loss_action()`）。
- 单挑且我方仍蒙牌 → 不看牌直接开牌：门户开放 `showdown`/`open` 任一即提交（实测只在对手已看牌时给出），两者都不开放（对手同样蒙牌）才退回盲跟；看牌会让后续投入翻倍，单挑无多人信息可换，直接比大小（`_poll_loop()` 看牌前分支的 `_heads_up_blind_action()`）。
- 多人蒙牌（非单挑）按 EV 决策「蒙还是看」，优先级低于单挑分支（`_blind_peek_or_call()`）：蒙牌手牌未知，按平均单挑胜率 0.5 估计，蒙牌跟注成本取 `callBet/2`（半价）计算增量 EV；EV ≥ 0 继续蒙牌半价盲跟，EV < 0 才看牌买信息（看牌免费，牌大再上、牌小交给看牌后 EV 弃牌）。看牌响应后的实际手牌决策仍走 `_act_on_hand()`。
- 蒙牌跟注成本为已看牌的一半（实测同一 `callBet=3000` 下，蒙牌 `+1500 跟注`、已看牌 `+3000 跟注`）；`peek`（看牌）动作本身不扣费（实测看牌前后 `player.bet` 无增量、`lastAction` 无下注文本），其代价仅是失去后续跟注的半价优惠（看牌后变为 `seen`，每次跟注按全价 `callBet`）。这是“蒙牌 EV 决策”和“单挑蒙牌不看牌直接开”的共同依据。
- 参与的对局结束（`roundId` 变化）时，推送最终结果通知：手牌、牌型、存活状态。
- **开牌动作仅在单挑出现（实测）**：`open`/`showdown` 只在存活玩家=2（单挑）时出现在 `actions`；多人局 actions 只有 `peek`/`fold`/`call`/`raise`。指南「场上>3人不比牌」被门户天然满足，无需插件限人数。
- **强制摊牌（实测）**：单挑约 6-8 轮后 `phase` 变为 `"showdown"`，`actions` 只剩 `fold`/`raise`/`showdown`（不再有 `call`/`open`），必须摊牌结束。单挑期间对手可每轮 `raise`，`callBet` 递增（实测 3000→24000），pot 可滚到 20-29 万。
- **`showdown` 成本 = 当前 `callBet`（单倍）**：实测结算时我方 delta 等于累计投入全额亏损，无双倍比牌费。
- **结算数据源 `game.lastResult`**：`GET /api/portal/zhajinhua` 每轮响应的 `game.lastResult` 含上一局结算：`roundId`、`winner`、`pot`、`winnerReturn`、`rake`（约 0.5%）、`selfDelta`、`players[]`（含 `displayName`、`bet`、`delta`、`result`（获胜/比牌落败/已弃牌）、`handType`、`isWinner`）。`players` 无 `id`，需用牌局 GET 的 `displayName→id` 映射关联（对手画像结算回填依据）。
- **`lastResult.players[]` 只给牌型、不给牌面与动作（已确认）**：每个玩家只有 `handType`（如「顺子」「散牌」），**没有具体牌面点数**（无 `hand` 卡牌文本），也**没有本局是加注还是平跟的动作字段**。因此对手画像：手牌分位只能用牌型分位带中点近似（`zjh_prob.win_prob_1v1_type`，无法定位型内具体点数）；加注/平跟分桶必须靠轮询实时跟踪 `lastAction`（`_train_opponent_actions` 的最激进动作），结算本身无从区分。
- `player.bet` 为**累计投入**（实测：3000 底注 + 1500 跟注 = 4500；单挑每轮随 `callBet` 递增）。
- 遛马动作用于冷却拒绝时返回外层 `ok: true`、`result.code == "cooldown"`、`result.remainMs`（剩余毫秒）、`result.message`；冷却约 45 分钟，且期间 `state.canWalk` 仍为 `true`，不能用来判断是否可遛。插件记下 `remainMs` 换算的到期时间退避，未到不再尝试；`cooldown` 不计入失败计数，连续真失败 3 次后跳过本轮。（`horse.py` 的 `_care_once()`）
- 养马实测字段：`stats.walkCountToday/walkMax`（每日遛马上限）、`stats.feedCountToday/feedMax`、`profile.satiety`（饱腹度）、`horse.balance`（银元）、`profile.state.{isDead,canWalk,canFeed}`。

## 待现场验证

- `showdown` 实测只需 `{ "action": "showdown" }`（多次提交均 `ok: true`，无目标/确认字段）；`open` 同为开牌动作但尚未在实测中单独提交验证。
- 对手发起应战后 `game.phase` 的更多取值；当前插件不会用它阻断行动（仅单挑强制摊牌阶段观察到 `"showdown"`）。

发生应战失败时，记录并保留（脱敏后）`roundId`、`phase`、`actions`、`self` 关键状态与 POST 错误，用于补全本节。