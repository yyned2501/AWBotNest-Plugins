# =============================================================================
# AWBotNest 插件：天空游戏 (skyGame) v1.0.0
#
# 天空系列游戏的统一入口：Vue 配置界面左侧按游戏分组，各游戏逻辑拆到
# games/ 子模块，互不干扰。当前收录：
#   - 炸金花：轮询 hdsky 门户 API，自动加入/看牌/好牌跟注烂牌弃牌
#   - 养马：占位，逻辑待实现
#
# 代码组织：
#   games/zhajinhua.py  炸金花轮询状态机
#   games/horse.py      养马（stub）
# =============================================================================

from __future__ import annotations

from . import games

__plugin__ = {
    "name": "天空游戏",
    "id": "skyGame",
    "version": "1.0.0",
    "author": "Yy",
    "description": "天空系列游戏统一入口：炸金花自动参与、养马等，左侧按游戏分组配置。",
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
        # ── 养马 ──
        "horse_enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用养马",
            "section": "养马",
            "order": 10,
        },
        "horse_notify": {
            "type": "boolean",
            "default": True,
            "label": "养马通知",
            "section": "养马",
            "order": 11,
        },
        # ── 炸金花 ──
        "zjh_enabled": {
            "type": "boolean",
            "default": True,
            "label": "启用炸金花自动参与",
            "section": "炸金花",
            "order": 20,
        },
        "zjh_cookie_file": {
            "type": "string",
            "default": "/home/hermes/.hermes/cookies/hdsky_cookie.txt",
            "label": "Cookie 文件路径",
            "section": "炸金花",
            "help": "hdsky_portal_session cookie 文件路径",
            "order": 21,
        },
        "zjh_base_url": {
            "type": "string",
            "default": "https://hdsky.supertimi.de:8443",
            "label": "服务器地址",
            "section": "炸金花",
            "order": 22,
        },
        "zjh_poll_interval": {
            "type": "slider",
            "default": 2,
            "label": "轮询间隔(秒)",
            "section": "炸金花",
            "min": 1,
            "max": 10,
            "step": 0.5,
            "order": 23,
        },
        "zjh_good_hands": {
            "type": "multiselect",
            "default": ["豹子", "同花顺", "金花", "顺子", "对子"],
            "label": "跟注牌型",
            "section": "炸金花",
            "options": ["豹子", "同花顺", "金花", "顺子", "对子", "散牌"],
            "help": "勾选的牌型跟注，未勾选的弃牌",
            "order": 24,
        },
        "zjh_notify_join": {
            "type": "boolean",
            "default": True,
            "label": "通知：加入牌局",
            "section": "炸金花",
            "order": 25,
        },
        "zjh_notify_hand": {
            "type": "boolean",
            "default": True,
            "label": "通知：手牌决策",
            "section": "炸金花",
            "order": 26,
        },
        "zjh_notify_fold_confirm": {
            "type": "boolean",
            "default": False,
            "label": "通知：双击确认弃牌",
            "section": "炸金花",
            "order": 27,
        },
        "zjh_notify_error": {
            "type": "boolean",
            "default": True,
            "label": "通知：异常",
            "section": "炸金花",
            "order": 28,
        },
    },
    "changelog": (
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
