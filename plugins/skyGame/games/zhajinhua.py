# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 轮到我了 → 看牌 → 好牌跟注 / 烂牌弃牌
#   - 支持双击弃牌确认
#   - 新牌局作废 CSRF（下次 POST 自动重取）
#   - 跟注牌型由配置 zjh_good_hands 勾选驱动

from __future__ import annotations

import asyncio

from . import hdsky_auth
from .hdsky import HdskyClient

# 默认跟注牌型（配置缺省/为空时的回退）
_DEFAULT_GOOD_HANDS = ["豹子", "同花顺", "金花", "顺子", "对子"]

_poll_task: asyncio.Task[None] | None = None


def _good_hands(cfg: dict) -> list[str]:
    """取配置的跟注牌型；勾选为空则回退默认五种好牌。"""
    selected = [h for h in (cfg.get("zjh_good_hands", _DEFAULT_GOOD_HANDS) or []) if h]
    return selected or _DEFAULT_GOOD_HANDS


def _good_hand(hand_type: str, good_hands: list[str]) -> bool:
    """判断手牌是否值得继续。"""
    return any(h in hand_type for h in good_hands)


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    interval = float(cfg.get("zjh_poll_interval", 2) or 2)
    fold_pending = False

    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        while True:
            try:
                if not cfg.get("zjh_enabled", True):
                    await asyncio.sleep(interval)
                    continue

                # 每轮读最新配置（cookie 路径/门户地址可能被改）
                client.configure(str(cfg.get("hdsky_cookie_file", "") or ""), str(cfg.get("hdsky_base_url", "") or ""))
                good_hands = _good_hands(cfg)

                # 获取牌局状态
                game_data = await client.get("/api/portal/zhajinhua")
                if "_error" in game_data:
                    ctx.log.warning("API 请求失败: %s", game_data["_error"])
                    client.reset_csrf()
                    await asyncio.sleep(interval)
                    continue

                g = game_data.get("game", {})
                rid = g.get("roundId")
                phase = g.get("phase", "")
                actions = g.get("actions", [])
                s = g.get("self", {})
                joined = s.get("joined", False)
                is_turn = s.get("isTurn", False)
                alive = s.get("alive", False)
                hand = s.get("hand", "")
                hand_type = s.get("handType", "")
                fc = s.get("foldConfirm", False)

                # 没加入且可加入 → 加入
                if not joined and "join" in actions:
                    ctx.log.info("加入牌桌 #%s...", rid)
                    r = await client.post("/api/portal/zhajinhua/join", {})
                    if r.get("ok"):
                        ctx.log.info("加入成功！")
                        if cfg.get("zjh_notify_join", True):
                            await ctx.notify(f"🃏 加入牌桌 #{rid}")
                    else:
                        ctx.log.warning("加入失败: %s", r.get("error"))

                # 轮到我了 → 看牌或操作
                if joined and is_turn and phase == "playing":
                    if not hand:
                        # 还没看牌
                        ctx.log.info("轮到我了！看牌...")
                        r = await client.post("/api/portal/zhajinhua/action", {"action": "peek"})
                        if r.get("ok"):
                            hand = r.get("game", {}).get("self", {}).get("hand", "?")
                            hand_type = r.get("game", {}).get("self", {}).get("handType", "?")
                            fc = r.get("game", {}).get("self", {}).get("foldConfirm", False)
                            ctx.log.info("手牌: %s (%s)", hand, hand_type)

                            if _good_hand(hand_type, good_hands):
                                ctx.log.info("好牌！跟注")
                                await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                                ctx.log.info("已跟注，等待下一轮")
                                if cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 好牌跟注: {hand} ({hand_type})")
                            else:
                                ctx.log.info("烂牌！弃牌")
                                await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                                if fc:
                                    fold_pending = True
                                else:
                                    ctx.log.info("已弃牌")
                                    if cfg.get("zjh_notify_hand", True):
                                        await ctx.notify(f"🃏 烂牌弃牌: {hand} ({hand_type})")
                    else:
                        # 已经看过牌了，直接决策
                        if hand and not _good_hand(hand_type, good_hands):
                            ctx.log.info("牌不好，弃牌...")
                            await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                            if fc:
                                fold_pending = True
                            else:
                                ctx.log.info("已弃牌")
                                if cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 烂牌弃牌: {hand} ({hand_type})")

                elif fold_pending and alive and is_turn:
                    # 双击确认弃牌
                    ctx.log.info("确认弃牌...")
                    r = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                    if r.get("ok"):
                        ctx.log.info("确认弃牌成功")
                        if cfg.get("zjh_notify_fold_confirm", False):
                            await ctx.notify("🃏 双击确认弃牌")
                        fold_pending = False

                # 新牌局开始 → 作废旧 CSRF
                if phase == "waiting" and rid and not joined:
                    client.reset_csrf()

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                ctx.log.error("轮询异常: %r", e)
                if cfg.get("zjh_notify_error", True):
                    await ctx.notify(f"⚠️ 炸金花轮询异常: {e}", level="warning")
                await asyncio.sleep(interval * 2)


def start(ctx: object) -> None:
    """启动炸金花轮询任务。"""
    global _poll_task
    _poll_task = asyncio.create_task(_poll_loop(ctx))
    ctx.log.info("炸金花已启动")


def stop(ctx: object) -> None:
    """停止炸金花轮询任务。"""
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        _poll_task = None
    ctx.log.info("炸金花已停止")
