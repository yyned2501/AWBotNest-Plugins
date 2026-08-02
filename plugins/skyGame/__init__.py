# =============================================================================
# AWBotNest 插件：天空游戏 (skyGame) v1.12.0
#
# 天空系列游戏的统一入口：Vue 配置界面左侧按游戏分组，各游戏逻辑拆到
# games/ 子模块，互不干扰。当前收录：
#   - 炸金花：轮询 hdsky 门户 API，自动加入/看牌/好牌跟注烂牌弃牌
#   - 养马：自动喂食/遛马/官方赛报名/复活提示
#   - Cookie 自动续期：门户会话过期时从 CookieCloud 取浏览器 cookie，
#     读 HDSky 站内信验证码自动重新登录，写回 cookie 文件
#
# 代码组织：
#   games/hdsky.py       门户共享 HTTP（cookie + CSRF + requestKey + 401 自动续期）
#   games/hdsky_auth.py  Cookie 续期（CookieCloud → 站内信抽码 → 登录 → 写 cookie）
#   games/zhajinhua.py   炸金花轮询状态机
#   games/horse.py       养马养护循环
# =============================================================================

from __future__ import annotations

from . import games
from .games import hdsky_auth

__plugin__ = {
    "name": "天空游戏",
    "id": "skyGame",
    "version": "1.12.0",
    "author": "Yy",
    "description": "天空系列游戏统一入口：炸金花自动参与、养马自动养护，左侧按游戏分组配置。",
    "scope": "user",
    "render_mode": "vue",
    "default_enabled": False,
    "requirements": ["httpx>=0.27"],
    "config_schema": {
        # ── 全局设置 ──
        "target_groups": {
            "type": "text",
            "default": "-1001326208894",
            "label": "目标群组（一行一个ID）",
            "section": "全局设置",
            "help": "游戏消息发到的群，一行一个。",
            "order": 1,
        },
        "bot": {
            "type": "string",
            "default": "",
            "label": "天空小秘机器人",
            "section": "全局设置",
            "help": "@用户名 或 数字ID，逗号分隔可填多个。留空=默认天空小秘。",
            "order": 2,
        },
        "hdsky_cookie_file": {
            "type": "string",
            "default": "/app/data/hdsky_cookie.txt",
            "label": "HDSky Cookie 文件路径",
            "section": "全局设置",
            "help": "容器内路径，宿主 appdata/awbotnest/data 目录；12 小时过期需重新覆盖该文件",
            "order": 3,
        },
        "hdsky_base_url": {
            "type": "string",
            "default": "https://hdsky.supertimi.de:8443",
            "label": "HDSky 门户地址",
            "section": "全局设置",
            "order": 4,
        },
        "hdsky_debug": {
            "type": "boolean",
            "default": False,
            "label": "门户调试记录",
            "section": "全局设置",
            "order": 5,
            "help": "开启后把每次门户 API 的请求与响应（脱敏后）追加写入调试文件，"
            "供事后核对实际请求；不改变平台日志级别",
        },
        "hdsky_debug_file": {
            "type": "string",
            "default": "/app/data/hdsky_debug.jsonl",
            "label": "调试记录文件路径",
            "section": "全局设置",
            "order": 6,
            "help": "容器内 JSONL 路径（宿主 appdata/awbotnest/data 目录）；超过 10MB 自动轮转为 .1",
        },
        # ── Cookie 自动续期 ──
        "auth_auto_renew": {
            "type": "boolean",
            "default": True,
            "label": "门户会话过期自动续期",
            "section": "Cookie 自动续期",
            "help": "经 MoviePilot CookieCloud 的浏览器 cookie 快照 → 读 HDSky 站内信验证码 → 自动登录写回 Cookie",
            "order": 30,
        },
        "cc_server": {
            "type": "string",
            "default": "http://192.168.31.10:3000",
            "label": "CookieCloud 地址",
            "section": "Cookie 自动续期",
            "help": "MoviePilot 内置 CookieCloud（http://<主机>:3000）",
            "order": 31,
        },
        "cc_uuid": {
            "type": "string",
            "default": "",
            "label": "CookieCloud UUID",
            "section": "Cookie 自动续期",
            "help": "浏览器 CookieCloud 插件的服务器地址对应 UUID（即 Key）",
            "order": 32,
        },
        "cc_password": {
            "type": "password",
            "default": "",
            "label": "CookieCloud 加密密钥",
            "section": "Cookie 自动续期",
            "help": "浏览器 CookieCloud 插件的加密密钥（即密码/Token）",
            "order": 33,
        },
        "hdsky_uid": {
            "type": "string",
            "default": "105577",
            "label": "HDSky UID",
            "section": "Cookie 自动续期",
            "help": "门户登录用的 HDSky 用户 UID",
            "order": 34,
        },
        "auth_check_interval": {
            "type": "slider",
            "default": 1800,
            "label": "会话体检间隔(秒)",
            "section": "Cookie 自动续期",
            "min": 600,
            "max": 7200,
            "step": 300,
            "help": "定期探测会话有效性并主动续期；游戏轮询遇到 401 也会即时触发",
            "order": 35,
        },
        "auth_notify": {
            "type": "boolean",
            "default": True,
            "label": "续期结果通知",
            "section": "Cookie 自动续期",
            "order": 36,
        },
        # ── 养马 ──
        "horse_enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用养马自动化",
            "section": "养马",
            "order": 10,
        },
        "horse_poll_interval": {
            "type": "slider",
            "default": 120,
            "label": "养护轮询间隔(秒)",
            "section": "养马",
            "min": 30,
            "max": 600,
            "step": 10,
            "help": "每轮最多执行一个养护动作，节奏拟人",
            "order": 11,
        },
        "horse_feed_type": {
            "type": "select",
            "default": "weed",
            "label": "喂食草料",
            "section": "养马",
            "options": [
                {"value": "weed", "label": "杂草（100银元 +12饱腹）"},
                {"value": "fine", "label": "精草（300银元 +30饱腹）"},
                {"value": "divine", "label": "仙草（1000银元 +60饱腹）"},
            ],
            "order": 12,
        },
        "horse_feed_threshold": {
            "type": "slider",
            "default": 60,
            "label": "喂食饱腹度阈值",
            "section": "养马",
            "min": 0,
            "max": 100,
            "step": 5,
            "help": "饱腹度低于此值且今日次数未用完时自动喂食",
            "order": 13,
        },
        "horse_auto_walk": {
            "type": "boolean",
            "default": True,
            "label": "自动遛马",
            "section": "养马",
            "help": "用完每日遛马额度，赚银元+经验（体力耗尽自动停）",
            "order": 14,
        },
        "horse_auto_official_race": {
            "type": "boolean",
            "default": False,
            "label": "自动报名官方赛",
            "section": "养马",
            "help": "每日官方赛开放报名时免费参加",
            "order": 15,
        },
        "horse_auto_revive": {
            "type": "boolean",
            "default": False,
            "label": "死亡自动复活",
            "section": "养马",
            "help": "马匹死亡且余额足够时自动复活（约 30 万银元）",
            "order": 16,
        },
        "horse_notify": {
            "type": "boolean",
            "default": True,
            "label": "养马通知",
            "section": "养马",
            "order": 17,
        },
        # ── 炸金花 ──
        "zjh_enabled": {
            "type": "boolean",
            "default": True,
            "label": "启用炸金花自动参与",
            "section": "炸金花",
            "order": 20,
        },
        "zjh_poll_interval": {
            "type": "slider",
            "default": 2,
            "label": "轮询间隔(秒)",
            "section": "炸金花",
            "min": 1,
            "max": 10,
            "step": 0.5,
            "order": 21,
        },
        "zjh_peeked_threshold": {
            "type": "slider",
            "default": 50,
            "label": "已看牌对手牌力阈值(%)",
            "section": "炸金花",
            "min": 0,
            "max": 95,
            "step": 5,
            "help": "优先按已看牌对手实际下注时的底池和成本反推；未观测到下注时才使用此回退分位。",
            "order": 23,
        },
        "zjh_open_enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用低胜率主动开牌",
            "section": "炸金花",
            "help": "最终实际胜率低于阈值但 EV 为正时，服务器允许 open 才发起比牌；默认关闭以先观察费用。",
            "order": 24,
        },
        "zjh_open_max_win_rate": {
            "type": "slider",
            "default": 50,
            "label": "主动开牌最高实际胜率(%)",
            "section": "炸金花",
            "min": 0,
            "max": 95,
            "step": 5,
            "help": "仅在最终实际胜率低于此值、EV 为正且服务端允许 open 时主动开牌。",
            "order": 25,
        },
        "zjh_raise_enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用高胜率主动追加",
            "section": "炸金花",
            "help": "最终实际胜率达到阈值时，服务器允许 raise 才追加；默认关闭以先观察费用。",
            "order": 26,
        },
        "zjh_raise_min_win_rate": {
            "type": "slider",
            "default": 75,
            "label": "主动追加最低实际胜率(%)",
            "section": "炸金花",
            "min": 5,
            "max": 100,
            "step": 5,
            "help": "仅在最终实际胜率达到此值、EV 为正且服务端允许 raise 时追加。",
            "order": 27,
        },
        "zjh_notify_join": {
            "type": "boolean",
            "default": True,
            "label": "通知：加入牌局",
            "section": "炸金花",
            "order": 24,
        },
        "zjh_notify_hand": {
            "type": "boolean",
            "default": True,
            "label": "通知：手牌决策",
            "section": "炸金花",
            "order": 25,
        },
        "zjh_notify_fold_confirm": {
            "type": "boolean",
            "default": False,
            "label": "通知：双击确认弃牌",
            "section": "炸金花",
            "order": 26,
        },
        "zjh_notify_error": {
            "type": "boolean",
            "default": True,
            "label": "通知：异常",
            "section": "炸金花",
            "order": 27,
        },
    },
    "changelog": (
        "v1.12.0 更新：\n"
        "- 移除炸金花单挑特殊策略：此前单挑蒙牌会绕过 EV 直接开牌/盲跟，已看牌又可能无条件跟注，"
        "会把未知弱牌带进对手已看牌、连续追加后的高成本比牌；现在无论单挑或多人，"
        "蒙牌统一按半价 EV 决定盲跟或看牌，已看牌统一按实际胜率和 EV 决定弃/跟/开/加\n"
        "- 保留服务端 showdown 应战：这是门户授权动作，不属于策略绕行；普通主动 open/raise "
        "仍严格受配置、EV 与服务端 actions 约束\n"
        "v1.11.10 更新：\n"
        "- 修复炸金花蒙牌胜率算错的 bug：手牌未知时不能把平均单挑胜率 0.5 当固定手牌代进 t^B——"
        "「赢对手A」「赢对手B」经我方手牌强弱相关并不独立，三人全蒙真实胜率是 1/3 而非 0.5²=25%"
        "（用户实测牌桌 #5081 发现）。改为对未知手牌强度精确积分：全蒙退化为 1/(B+1)、"
        "单挑纯蒙 1/2、已看牌对手按门槛进条件因子；此前系统性低估蒙牌胜率，让看牌显得比实际更划算\n"
        "v1.11.9 更新：\n"
        "- 炸金花补齐全量决策 TG 通知：此前「蒙牌盲跟/看牌」「单挑蒙牌应战/主动开牌/盲跟」"
        "只记运行日志、不推送，现在和看牌后的跟注/追加/开牌/弃牌一样推送明细"
        "（底池、半价成本、蒙牌胜率、期望收益、原因），每个决策都能在 TG 实时核对\n"
        "- 修复双击确认弃牌死循环：确认弃牌连续失败 3 次后放弃本局并清空待确认状态，"
        "不再每轮无限重发；牌局切换（roundId 变化）时一并重置弃牌确认状态与重试计数，"
        "避免上一局的待确认弃牌泄漏到新一局产生异常 fold 动作\n"
        "v1.11.8 更新：\n"
        "- 炸金花移除「第一轮必蒙」硬策略，改为蒙牌按 EV 决策「蒙还是看」（优先级低于单挑）：\n"
        "  引入蒙牌跟注半价概念（实测同一 callBet 下蒙牌 +1500、已看牌 +3000），蒙牌 EV ≥ 0 继续半价盲跟\n"
        "  （便宜划算，别去看牌翻倍）；EV < 0 才看牌买信息——看牌免费、只是失去后续半价优惠，牌大再上、牌小弃\n"
        "v1.11.7 更新：\n"
        "- 修复炸金花看牌后单挑被碾压仍死跟的亏损 bug：单挑且对手已看牌、EV 为负时不再无脑跟注，"
        "改为比牌止损（门户允许 showdown/open 即用）或弃牌止损（无比牌动作时）——此前曾出现终胜率 0% "
        "仍连跟七轮、单局填进近九万的情况\n"
        "v1.11.6 更新：\n"
        "- 炸金花单挑且我方仍蒙牌时不再看牌：门户开放 showdown/open 即直接开牌比大小，"
        "两者都不开放（对手同样蒙牌）才盲跟——看牌会让后续投入翻倍，单挑已无多人信息可换，没必要看牌加投入\n"
        "v1.11.5 更新：\n"
        "- 全局设置界面新增「调试」卡片：门户调试记录开关与文件路径可在配置页直接设置（补齐 1.11.4 的界面入口）\n"
        "v1.11.4 更新：\n"
        "- 新增门户调试记录开关（全局设置·门户调试记录）：开启后把每次门户 API 的请求与响应"
        "脱敏后追加写入 JSONL 调试文件（默认 /app/data/hdsky_debug.jsonl，超 10MB 轮转），"
        "供事后核对推送与实际请求；不改平台日志级别、不影响其它插件\n"
        "v1.11.3 更新：\n"
        "- 遛马按门户响应的 remainMs 冷却退避：冷却约 45 分钟且期间 canWalk 仍为 true，"
        "记下冷却到期时间、未到就不再尝试，不再每 2 分钟撞一次冷却\n"
        "- 遛马日志改准：只有真成功才打「遛马成功（今日 N/M）」，冷却走 debug，"
        "真失败才 warning；消除之前每次尝试都打「遛马（今日 N/M）」造成的假失败刷屏\n"
        "- 养马状态请求失败日志在异常无消息时兜底为「未知网络错误」，不再打空\n"
        "v1.11.2 更新：\n"
        "- 修复牌局结束通知崩溃：合并被同名函数遮蔽的两份 `_game_result_notification`，"
        "消除调用方三参与定义四参不匹配导致的 TypeError\n"
        "- 结果通知排行只对对手递增，单对手正确显示「对手1」而非「对手2」\n"
        "v1.11.1 更新：\n"
        "- HdskyClient 遇 403「请求来源无效」（CSRF 失效）时自动作废缓存、重取 CSRF 并重试一次，"
        "避免门户 token 提前过期导致遛马/喂食/炸金花动作持续失败；只重试一次不死循环\n"
        "v1.11.0 更新：\n"
        "- 单挑特殊逻辑：对手未看牌时不看直接开，对手已看牌且 EV 为负也跟注不弃牌\n"
        "- 修复 showdown 应战条件：移除 `decision is not None` 门控，应战不受 `_choose()` 数据不完整的影响\n"
        "- 参与的对局结束后推送最终结果（手牌、牌型、存活状态）\n"
        "- 遛马连续失败 3 次后跳过本轮，避免死磕\n"
        "v1.10.0 更新：\n"
        "- 炸金花看牌后读不到手牌时不再直接保守弃牌：重拉牌局状态补齐手牌（最多 3 次短重试），"
        "仍读不到则本轮不决策、等下次轮询补齐，避免把读空误判成烂牌而弃掉\n"
        "v1.9.0 更新：\n"
        "- 炸金花弃牌/出局后停止跟踪对手快照与门槛推导：本局不再有决策，"
        "避免对手互相缠斗时门槛递归虚高（单挑反推不动点收敛到 1.0）做无用计算、刷花日志\n"
        "v1.8.0 更新：\n"
        "- 炸金花门槛改为精确正反向闭环：按蒙牌和已看牌权重从 EV=0 实际胜率二分反解单挑牌型门槛\n"
        "- 我方上牌与后续跟注会记录最低牌型胜率；对手上牌时将该门槛纳入反推，历史门槛只升不降\n"
        "v1.7.0 更新：\n"
        "- 对手从蒙牌切换为上牌时记录行动前快照；结合上牌与后续下注的门槛推导其实际牌力\n"
        "- 轮到我方时以服务端 actions 列表作为唯一动作授权；showdown 出现即优先应战，不再受 phase 限制\n"
        "- 应战失败日志补充牌局阶段、玩家状态和服务端可用动作，便于继续核对门户接口\n"
        "v1.6.0 更新：\n"
        "- 修复双击弃牌前重复推送：首次弃牌仅等待确认，确认成功后才推送一次最终结果\n"
        "- 支持门户应战开牌（showdown）；按最终实际胜率和 EV 决定应战或弃牌\n"
        "- 新增可选主动开牌/追加：严格以最终实际胜率、EV 与服务端 actions 为条件，默认关闭以先观察服务端费用\n"
        "- 决策和推送显式展示单挑胜率、看牌门槛和最终实际胜率\n"
        "v1.5.1 修复：\n"
        "- 兼容门户 peek 返回的「手牌 → 同花」组合 handType 文本，正确归一为金花参与 EV 计算，不再因键值缺失保守弃牌\n"
        "v1.5.0 更新：\n"
        "- 炸金花改为纯 EV 决策：移除「跟注牌型」勾选门控，跟注与否只看增量期望收益（EV≥0 跟注）\n"
        "- 修正看牌对手推断的对手数：行动者面对其余存活对手（不含自己），门槛不再被高估而过度弃牌\n"
        "- 决策链路补充调试日志：打印单挑胜率、蒙/看人数、每个看牌对手的门槛及快照来源、终胜率、EV 与原因\n"
        "- 跟注/弃牌推送改为多行明细：牌桌号、底池、跟注成本、对手构成与门槛、胜率、期望收益；弃牌附原因\n"
        "v1.4.0 更新：\n"
        "- 已看牌对手按其实际跟注时的底池、成本和对手数反推正 EV 牌力门槛\n"
        "- 每局追踪对手看牌后的下注变化；漏采时才回退配置门槛，日志标注实测/回退来源\n"
        "- 炸金花设置页新增动态门槛说明，决策日志展示逐个看牌对手的推断结果\n"
        "v1.3.2 更新：\n"
        "- 炸金花胜率按蒙牌与已看牌对手分开计算，已看牌跟注者按可配置牌力门槛反算\n"
        "- 跟注改为按底池和本次跟注成本计算增量 EV，胜率未过半但正收益时仍会跟注\n"
        "- 新增已看牌对手牌力阈值配置，并在日志和通知中展示概率、成本及 EV\n"
        "v1.3.1 更新：\n"
        "- 修复穷举概率表跨牌型排序：散牌/对子/金花/同花顺胜率值域重新计算，不再倒挂\n"
        "- 新增概率表生成脚本；修复 A23 顺子和同花顺被误当作最大顺子的胜率\n"
        "- 兼容门户返回的「同花」牌型，归一为「金花」后按配置准确跟注\n"
        "- 跟注牌型改为精确匹配，避免「顺子」错误匹配「同花顺」\n"
        "v1.3.0 更新：\n"
        "- 炸金花决策升级为穷举概率表：基于 22100 种牌型枚举精确计算胜率，不再按牌型粗放估算\n"
        "- 手牌解析（如 A♠K♠Q♠ → 点数）查表得出精确胜率，概率随剩余人数动态衰减\n"
        "- 新增 zjh_prob.py 穷举概率表模块（豹子/同花顺/金花/顺子/对子/散牌全量枚举）\n"
        "v1.2.1 更新：\n"
        "- 养马官方赛报名前检查 ctx.kv 今日是否已报名，已报名跳过直到明天\n"
        "v1.2.0 更新：\n"
        "- 门户 Cookie 自动续期：会话过期时从 MoviePilot CookieCloud 拉浏览器 cookie 快照，"
        "优先复用快照内仍有效的门户会话；否则触发门户登录，用 PT 站 cookie 读 HDSky 站内信"
        "验证码并自动验证，写回 cookie 文件，全程无需人工干预\n"
        "- 双触发：游戏轮询遇到 401 即时续期 + 看门狗定期体检主动续期\n"
        "- HdskyClient 支持 401 自动续期重试；续期防抖（10 分钟内不重复发验证码）、失败通知节流\n"
        "- 新增配置区「Cookie 自动续期」（CookieCloud 地址/UUID/密钥、UID、体检间隔）\n"
        "- 配置界面支持手动「立即续期」按钮\n"
        "v1.1.0 更新：\n"
        "- 门户 Cookie 自动续期：会话过期时从 MoviePilot CookieCloud 拉浏览器 cookie 快照，"
        "优先复用快照内仍有效的门户会话；否则触发门户登录，用 PT 站 cookie 读 HDSky 站内信"
        "验证码并自动验证，写回 cookie 文件，全程无需人工干预\n"
        "- 双触发：游戏轮询遇到 401 即时续期 + 看门狗定期体检主动续期\n"
        "- HdskyClient 支持 401 自动续期重试；续期防抖（10 分钟内不重复发验证码）、失败通知节流\n"
        "- 新增配置区「Cookie 自动续期」（CookieCloud 地址/UUID/密钥、UID、体检间隔）\n"
        "- 配置界面支持手动「立即续期」按钮\n"
        "v1.1.0 更新：\n"
        "- 养马自动化落地（基于实测门户 API）：饱腹度低于阈值自动喂食、每日额度自动遛马、"
        "官方赛可选自动报名、死亡复活可选\n"
        "- API 调用抽象为 HdskyClient：游戏模块只填接口与参数，cookie/CSRF/证书/JSON 全内聚；"
        "CSRF 过期自动重取\n"
        "- 动作冷却（cooldown）静默处理，不再刷告警通知\n"
        "- Cookie/门户地址上移到全局设置（hdsky_cookie_file/hdsky_base_url），炸金花与养马共用；"
        "移除 zjh_cookie_file/zjh_base_url\n"
        "v1.0.0 初始版本\n"
        "- 天空游戏统一入口，Vue 左侧按游戏分组配置\n"
        "- 全局设置（目标群组、天空小秘机器人）\n"
        "- 炸金花：自动加入/看牌/好牌跟注烂牌弃牌，支持双击弃牌确认\n"
        "- 养马：占位，逻辑待实现"
    ),
}


async def setup(ctx: object) -> None:
    ctx.log.info("天空游戏插件已加载 (v%s)", __plugin__["version"])
    games.start_all(ctx)

    @ctx.on_api("/renew", methods=["POST"])
    async def renew_now(req: object) -> dict:
        """手动触发一次 Cookie 续期（跳过防抖），配置界面「立即续期」按钮调用。"""
        ok = await hdsky_auth.renewer_for(ctx).renew(force=True)
        return {"ok": ok, "message": "续期成功，新 Cookie 已生效" if ok else "续期失败，详情见运行日志"}

    ctx.log.info("天空游戏已就绪")


async def teardown(ctx: object) -> None:
    games.stop_all(ctx)
    ctx.log.info("天空游戏已卸载")
