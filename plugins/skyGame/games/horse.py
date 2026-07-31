# -*- coding: utf-8 -*-
# 天空游戏 · 养马：占位 stub
#
# 养马的具体玩法规则尚未确认，这里先建好配置与启停骨架，逻辑待补充。
# 不臆造规则：horse_enabled 开启时只记录一条提示，不做任何自动操作。

from __future__ import annotations

import asyncio


async def _stub(ctx: object) -> None:
    """养马逻辑占位：启用时仅提示，等待规则实现。"""
    notified = False
    while True:
        if ctx.config.get("horse_enabled", False) and not notified:
            ctx.log.info("养马已启用（逻辑开发中，暂无自动操作）")
            if ctx.config.get("horse_notify", True):
                await ctx.notify("🐴 养马已启用（逻辑开发中）", level="info")
            notified = True
        elif not ctx.config.get("horse_enabled", False):
            notified = False
        await asyncio.sleep(60)


_task: asyncio.Task[None] | None = None


def start(ctx: object) -> None:
    """启动养马占位任务。"""
    global _task
    _task = asyncio.create_task(_stub(ctx))
    ctx.log.info("养马已启动（逻辑开发中）")


def stop(ctx: object) -> None:
    """停止养马占位任务。"""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
    ctx.log.info("养马已停止")
