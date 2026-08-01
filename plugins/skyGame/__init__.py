# =============================================================================
# AWBotNest 插件：天空游戏 (skyGame) v1.2.0
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
    "version": "1.3.0",
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
        "zjh_good_hands": {
            "type": "multiselect",
            "default": ["豹子", "同花顺", "金花", "顺子", "对子"],
            "label": "跟注牌型",
            "section": "炸金花",
            "options": ["豹子", "同花顺", "金花", "顺子", "对子", "散牌"],
            "help": "勾选的牌型跟注，未勾选的弃牌",
            "order": 22,
        },
        "zjh_notify_join": {
            "type": "boolean",
            "default": True,
            "label": "通知：加入牌局",
            "section": "炸金花",
            "order": 23,
        },
        "zjh_notify_hand": {
            "type": "boolean",
            "default": True,
            "label": "通知：手牌决策",
            "section": "炸金花",
            "order": 24,
        },
        "zjh_notify_fold_confirm": {
            "type": "boolean",
            "default": False,
            "label": "通知：双击确认弃牌",
            "section": "炸金花",
            "order": 25,
        },
        "zjh_notify_error": {
            "type": "boolean",
            "default": True,
            "label": "通知：异常",
            "section": "炸金花",
            "order": 26,
        },
    },
    "changelog": (
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
