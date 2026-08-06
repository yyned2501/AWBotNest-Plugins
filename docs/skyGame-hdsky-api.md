# HDSky 门户 API：天空游戏插件

> 维护规则：本文档只记录由插件实现、运行日志或实测响应证实的接口契约。尚未证实的字段、状态或请求参数必须明确标为“待验证”，不得据此编写猜测性请求。
>
> 每次通过运行日志、抓包或实测确认/更正外部 API 行为时，必须在同一提交更新本文档。

## 认证与传输

炸金花逻辑通过 `plugins/skyGame/games/hdsky.py` 的 `HdskyClient` 访问门户：

- Cookie 文件和门户根地址由插件配置提供；
- 客户端负责 CSRF / requestKey 获取、请求 JSON 编解码，以及遇到 401 时触发 Cookie 续期后重试；
- 遇到 403「请求来源无效」（CSRF 失效）时，客户端作废缓存的 CSRF、重取一次并重试原请求（仅一次，不死循环）；非 CSRF 的 403（如权限不足）不重试；
- **CSRF 实测行为（2026-08-05）**：`GET /api/portal/session` 每次返回**不同的新 csrfToken**，且**新 GET 立即作废旧 token**——门户只认「最近一次 GET 返回的 token」，旧 token 再用于 POST 一律 `403 {"ok":false,"error":"页面安全校验已失效，请刷新后重试"}`。token 本身**非一次性**（同一 token 连续多次 POST 均通过）。因此 CSRF 缓存必须**进程级共享**：养马/炸金花各自独立 `HdskyClient` 若各自缓存 token 会互相作废（A 取 token 后 B 再取作废 A 的，A 的 POST 持续 403，重取又被 B 作废，连续失败直至门户行动超时）。v1.16.5 起 `HdskyClient` 用类变量共享 token，只在判定失效时才刷新；
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
| `player.alive` / `player.active` | 玩家是否仍在局。实测：弃牌动作在**同一快照**就伴随 `alive=false` 出现（`lastAction='弃牌'` 只在出局状态可见，2026-08-04 实测确认），插件对出局玩家只记录 fold 动作。 |
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
- 多人蒙牌（非单挑）按 Terminal EV 决策树决定「盲跟 / 看牌」，优先级低于单挑分支（`_blind_peek_or_call()`）：递归推演 `zjh_terminal_depth` 轮，每轮枚举**所有存活对手**的 fold/call/raise 动作组合（笛卡尔积，`P=0` 的动作剪枝，`zjh_profile` 按对手 ID 独立查画像动作概率，而非旧版「取全部对手平均值当单对手」）；弃牌者移出存活列表、胜率按剩余对手重算（`_blind_win_probability` 对未知手牌精确积分），看牌对手加注上调其门槛、蒙牌加注视为诈唬不上调；全部弃牌则独赢底池。盲跟候选 EV≥0 才盲跟（半价 `callBet/2`），否则看牌。**蒙牌决策树不输出弃牌**（v1.15.1）：看牌免费、弱牌看后弃=直接弃（净 0）、强牌再上，看牌弱占优于弃牌；看牌分支 EV 按内盈亏平衡点积分（旧版拿配置门槛当强弱分界，对手很强时把看牌 EV 拖负、误判「弃牌最优」），结构性 ≥0。仅当门户不给看牌时才按盲跟 EV 符号决定继续或弃牌止损：EV≥0 按 showdown/open/call 优先序继续（强制摊牌阶段 actions 无 peek/call，showdown 即「继续」动作，v1.15.2），EV<0 才弃牌；判弃牌时经 `_request_blind_fold()` 提交 fold（与已看牌弃牌同一动作端点，可能触发 `foldConfirm` 双击确认，通知用蒙牌弃牌样式）。看牌响应后的实际手牌决策仍走 `_act_on_hand()`。
- 蒙牌跟注成本为已看牌的一半（实测同一 `callBet=3000` 下，蒙牌 `+1500 跟注`、已看牌 `+3000 跟注`）；`peek`（看牌）动作本身不扣费（实测看牌前后 `player.bet` 无增量、`lastAction` 无下注文本），其代价仅是失去后续跟注的半价优惠（看牌后变为 `seen`，每次跟注按全价 `callBet`）。这是“蒙牌 EV 决策”和“单挑蒙牌不看牌直接开”的共同依据。
- **加注规则（2026-08-05 用户确认 + hdsky_debug.jsonl 实测吻合）**：`callBet` 随加注次数**线性**增长，`callBet = ante × (1 + raise_count)`（`ante=3000` → raise1 `6000` → raise2 `9000` → raise3 `12000`）；每次 raise = **追平当前 callBet + 加一注底注**（实测 `callBet=3200` 时加注 `+6400`，新 `callBet=6400`）。反推：`raise_count = callBet/ante − 1`，再 raise 一次则 +1。**不是 ×1.5/×2 复利**——复利会让 callBet/底池指数膨胀、盲跟 EV 对深度无界增长（3 人必上时 EV≈满池，用户报障）。蒙牌加注同样半价（新 callBet 的一半）。
- **盲跟 Terminal EV 决策树建模（v1.16.4 修正）**：每轮时序为「我方先盲跟半价入池（用本轮初 `callBet`）→ 存活对手依次行动（弃牌移出/平跟/加注，联合概率笛卡尔积）」，加注把 callBet 抬升一注底注后**同轮后续跟注者追平新值**（含同轮连续加注时从抬升后的 callBet 起算）；深度耗尽 = 强制摊牌不再下注（`win×pot−cost`）。**蒙牌对手下注一律半价**（旧实现按全价算，伪造「我方半价 vs 对手全价」伪优势，3 人全蒙公平局被算成正 EV 接近满池）。供弃用的「fold 衰减」已移除：修正入池/追平/半价后，公平局 EV 随深度自然收敛（pot 1 万、callBet 3 千、两蒙牌必上对手，depth 1→4 收敛 4083→6333，约 pot 三成）。
- **看牌对手不进入 fold 分支（v1.16.6 修正）**：已看牌对手的门槛由「继续下注」反推，既然继续就意味着牌力 ≥ 门槛（强牌），面对我方跟注不会弃牌；画像里的历史弃牌率含「弱牌看牌后弃」样本，不适用于已推断强牌的当前局面。旧实现照用历史弃牌率，把大量「对手弃牌、我方白赢底池」分支计入盲跟 EV——线上 #6109 三个看牌对手门槛 0.94+（真实胜率≈1%）却算出应战 EV +45725 误开牌。修正后看牌对手 fold 清零、按 call/raise 重归一化，EV 收敛到「胜率×底池−成本」量级，改为看牌/弃牌。
- **连续加注对手门槛逐级上调（v1.16.8 修正）**：已看牌对手连续 raise 时，旧实现只按赔率 break-even 反推门槛（`_opponent_hand_threshold`），连续 raise 的强度信号被低估——uniform[门槛,1.0] 假设把约 77% 权重放在「比我方同花小的牌仍连加」上，胜率虚高 → 摸到同花死追对手连加输钱。现 `_update_round_tracker` 累计各对手本局 raise 次数（`_RoundTracker.opponent_raise_counts`，lastAction 变化且含「加」才计一次），`_seen_opponent_ranges` 对加注对手按次数逐级上调门槛（每次关掉剩余区间一半 β=0.5，强于决策树推演的 +25%/次——已确认的连续 raise 是事实信号），且上调后不被画像历史弱牌加注下四分位拉低（取 max）。**强制摊牌阶段（phase=showdown）不升级**：实测该阶段 `actions` 只剩 fold/raise/showdown，raise 是唯一「继续」动作，对手被迫每轮 raise，不代表牌强（单挑实测 6-8 轮 callBet 3000→24000）。
- **终局动作（showdown/open）重试与回退（v1.16.6 修正）**：旧实现用 `last_terminal_action` 永久去重，门户未执行 showdown/open（多人局常不开放、或响应 ok 但状态未推进）时每轮都被「已发送过」拦截、卡死到行动超时（线上 #6109 连续 9 轮判应战全被跳过）。修正：`_terminal_action_ineffective()` 检测「仍是己方回合且动作仍可用」即判未生效、清除去重允许重发；重发达 `_TERMINAL_RESEND_MAX`（3）次仍未生效则由 `_terminal_action_or_fallback()` 回退看牌（看牌免费永不亏），无看牌才退盲跟，防无限重发空转。
- 参与的对局结束（`roundId` 变化）时，推送最终结果通知：手牌、牌型、存活状态。
- **开牌动作主要在单挑出现（实测）**：`open`/`showdown` 绝大多数情况只在存活玩家=2（单挑）时出现在 `actions`。**但 2026-08-03 线上日志观察到例外**：一存活对手=2（含我方共 3 人）的多人局 `actions` 也含 `open`（`phase='playing'`），与「仅单挑」结论冲突，待进一步确认触发条件。插件在盲跟 EV≥0 分支会优先 `showdown`/`open`，若多人局确实给出 `open` 需确认提交是否合法。
- **强制摊牌（实测）**：单挑约 6-8 轮后 `phase` 变为 `"showdown"`，`actions` 只剩 `fold`/`raise`/`showdown`（不再有 `call`/`open`），必须摊牌结束。单挑期间对手可每轮 `raise`，`callBet` 递增（实测 3000→24000），pot 可滚到 20-29 万。
- **`showdown` 成本 = 当前 `callBet`（单倍）**：实测结算时我方 delta 等于累计投入全额亏损，无双倍比牌费。
- **结算数据源 `game.lastResult`**：`GET /api/portal/zhajinhua` 每轮响应的 `game.lastResult` 含上一局结算：`roundId`、`winner`、`pot`、`winnerReturn`、`rake`（约 0.5%）、`selfDelta`、`players[]`（含 `displayName`、`bet`、`delta`、`result`（获胜/比牌落败/已弃牌）、`handType`、`isWinner`）。`players` 无 `id`，需用牌局 GET 的 `displayName→id` 映射关联（对手画像结算回填依据）。**`selfDelta` 为本账号该局净输赢（正=赢、负=输），v1.16.9 起用于战绩统计**：roundId 切换时（`lastResult` 此刻正好是刚结束那局）入账到 kv `zjh:stats`（累计）与 `zjh:stats:day:YYYY-MM-DD`（当日），统计局数/胜/平/负/总赢/总输，对局结束通知展示本局盈亏与累计、当日战绩。
- **`lastResult.players[]` 牌面与动作字段（2026-08-04 实测更正）**：结算**没有**本局加注/平跟的动作字段（动作分桶仍靠轮询实时跟踪 `lastAction`）。但**摊牌/比牌结束的局，每个玩家（含已弃牌者）的 `handType` 给出「牌面 → 牌型」完整组合文本**（如 `J♣ 6♣ 3♦ → 散牌`）；只有全员弃牌直接分 pot 的局无人亮牌（`handType` 为空）。因此弃牌玩家亮牌时也按本轮最激进动作回填手牌分位（「加注后弃牌」的牌是校准加注下限/诈唬率的关键样本）；无牌面则不回填、不虚构。
- **对手范围与反诈唬全画像驱动（v1.16.0，无手动配置）**：已看牌对手范围不再用固定上下限配置——加注对手下限 = 实测加注分位下四分位（无分位回退加注频率推断 `1-raise_rate`，再回退推断门槛）；平跟对手**永不封顶**（upper 恒 1.0，对手可能慢打坚果牌）。反诈唬率逐对手计算、无全局基线：**hand-level 继续频率 c>0.5** 本身蕴含诈唬（理性对手最多用最强 c 分位牌继续，弱牌占比下界 (c−0.5)/c，按手数收缩），再与实测继续手牌弱牌占比混合；无画像对手诈唬率 0。**样本口径（v1.16.1 修正）**：继续频率用 hand-level——结算时每局自愿继续过的对手记一次（`raise_freq.total`），弃牌手数用 fold 实例计数（每手最多弃一次、弃牌即出局，实例数恰等于手数），分母 = 继续手数 + 弃牌手数；实例级动作计数会把「一手牌多次跟注」的分子撑大（5 弃 + 5 手跟到底各 3 轮 → 实例 c=0.75 误判诈唬，hand-level c=0.5 无诈唬），且样本量虚高会让可信度收缩权重失真。
- `player.bet` 为**累计投入**（实测：3000 底注 + 1500 跟注 = 4500；单挑每轮随 `callBet` 递增）。
- 遛马动作用于冷却拒绝时返回外层 `ok: true`、`result.code == "cooldown"`、`result.remainMs`（剩余毫秒）、`result.message`；冷却约 45 分钟，且期间 `state.canWalk` 仍为 `true`，不能用来判断是否可遛。插件记下 `remainMs` 换算的到期时间退避，未到不再尝试；`cooldown` 不计入失败计数，连续真失败 3 次后跳过本轮。（`horse.py` 的 `_care_once()`）
- **遛马失败熔断按「天」自动重置（v1.16.7 修正）**：旧实现失败计数只在成功遛马时清零——但计数到 3 后就不再发遛马请求，形成**永久死锁**（线上 08-01 遗留 count=3，此后每日 4 次遛马额度全浪费、体力始终满，用户误以为「满体力却只喂草」）。现失败计数带日期存储（kv 值 `{"count": N, "date": "YYYY-MM-DD"}`），跨天自动重置为 0 重新尝试；旧版纯数字遗留值（无日期）视为跨天立即恢复。同日连续失败 3 次仍熔断当日，次日自动恢复。
- **体力与饱腹是独立字段**：`profile.stamina`（体力，100 满，24 小时自然回满，遛马消耗）与 `profile.satiety`（饱腹度，喂食恢复，低于 `horse_feed_threshold` 才喂）。「体力满却不遛马」是遛马熔断的症状而非喂食逻辑错误——喂食只在 satiety < 阈值时发生（实测 08-06 00:00 satiety=53 喂 weed，喂后 65）。
- 养马实测字段：`stats.walkCountToday/walkMax`（每日遛马上限）、`stats.feedCountToday/feedMax`、`profile.satiety`（饱腹度）、`horse.balance`（银元）、`profile.state.{isDead,canWalk,canFeed}`。

## 待现场验证

- `showdown` 实测只需 `{ "action": "showdown" }`（多次提交均 `ok: true`，无目标/确认字段）；`open` 同为开牌动作但尚未在实测中单独提交验证。
- 对手发起应战后 `game.phase` 的更多取值；当前插件不会用它阻断行动（仅单挑强制摊牌阶段观察到 `"showdown"`）。

发生应战失败时，记录并保留（脱敏后）`roundId`、`phase`、`actions`、`self` 关键状态与 POST 错误，用于补全本节。