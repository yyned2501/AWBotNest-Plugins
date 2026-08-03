# -*- coding: utf-8 -*-
# 天空游戏 · 子游戏注册表
#
# 每个游戏是一个模块，约定暴露同步函数：
#   start(ctx)  启动（内部自建 asyncio 长任务）
#   stop(ctx)   停止（取消任务）
# 插件 setup/teardown 遍历本表统一启停。新增游戏：写一个模块 + 加进 _GAMES。

from __future__ import annotations

from . import hdsky_auth, horse
from .zhajinhua import zhajinhua

# 注册顺序即启停顺序（hdsky_auth 是 Cookie 续期看门狗，接口同 start/stop）
_GAMES = [zhajinhua, horse, hdsky_auth]


def start_all(ctx: object) -> None:
    """启动所有子游戏。单个游戏启动失败不影响其它游戏。"""
    for game in _GAMES:
        try:
            game.start(ctx)
        except Exception as e:
            ctx.log.error("游戏 %s 启动失败: %r", getattr(game, "__name__", "?"), e)


def stop_all(ctx: object) -> None:
    """停止所有子游戏。"""
    for game in _GAMES:
        try:
            game.stop(ctx)
        except Exception as e:
            ctx.log.error("游戏 %s 停止失败: %r", getattr(game, "__name__", "?"), e)
