# =============================================================================
# AWBotNest 插件：天空游戏 (skyGame) v1.1.0
#
# 天空系列游戏的统一入口：Vue 配置界面左侧按游戏分组，各游戏逻辑拆到
# games/ 子模块，互不干扰。当前收录：
#   - 炸金花：轮询 hdsky 门户 API，自动加入/看牌/好牌跟注烂牌弃牌
#   - 养马：自动喂食/遛马/官方赛报名/复活提示
#
# 代码组织：
#   games/hdsky.py      门户共享 HTTP（cookie + CSRF + requestKey）
#   games/zhajinhua.py  炸金花轮询状态机
#   games/horse.py      养马养护循环
# =============================================================================

from __future__ import annotations

from . import games

__plugin__ = {
    "name": "天空游戏",
    "id": "skyGame",
    "version": "1.1.0",
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
    ctx.log.info("天空游戏已就绪")


async def teardown(ctx: object) -> None:
    games.stop_all(ctx)
    ctx.log.info("天空游戏已卸载")
