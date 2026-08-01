# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 轮到我了 → 第一轮蒙牌（盲跟），第二轮看牌
#   - 看牌后根据牌型 + 剩余人数判断胜率，决定跟注/弃牌
#   - 支持双击弃牌确认
#   - 新牌局作废 CSRF（下次 POST 自动重取）

from __future__ import annotations

import asyncio

from . import hdsky_auth
from .hdsky import HdskyClient
from .zjh_prob import win_prob_n

# 默认跟注牌型（配置缺省/为空时的回退）
_DEFAULT_GOOD_HANDS = ["豹子", "同花顺", "金花", "顺子", "对子"]

# 手牌解析：花色符号和点数映射
_SUIT_SYMBOLS = "♠♥♦♣"
_RANK_MAP = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}
_HAND_TYPE_ALIASES = {"同花": "金花"}

_poll_task: asyncio.Task[None] | None = None


def _normalize_hand_type(hand_type: str) -> str:
    """将门户牌型名称归一为配置和概率表使用的名称。"""
    return _HAND_TYPE_ALIASES.get(hand_type, hand_type)


def _good_hands(cfg: dict) -> list[str]:
    """取配置的跟注牌型；勾选为空则回退默认五种好牌。"""
    selected = [h for h in (cfg.get("zjh_good_hands", _DEFAULT_GOOD_HANDS) or []) if h]
    return selected or _DEFAULT_GOOD_HANDS


def _alive_count(game: dict) -> int:
    """取当前存活玩家数。"""
    players = game.get("players") or game.get("seats") or []
    if players:
        return sum(1 for p in players if p.get("alive", p.get("active", False)))
    # 兜底：从 self 存活反向推断至少 2 人
    return 2


def _parse_hand(hand: str) -> list[int]:
    """解析手牌字符串如 'A♠K♠Q♠' 为降序点数列表 [14, 13, 12]。"""
    cards: list[int] = []
    i = 0
    while i < len(hand):
        if hand[i] in _SUIT_SYMBOLS:
            i += 1
            continue
        if hand[i : i + 2] == "10":
            cards.append(10)
            i += 2
        else:
            r = _RANK_MAP.get(hand[i])
            if r is not None:
                cards.append(r)
            i += 1
    cards.sort(reverse=True)
    return cards


def _extract_hand_value(hand_type: str, hand: str) -> int | tuple[int, ...] | None:
    """根据牌型从手牌字符串提取概率表查表键值。"""
    if not hand:
        return None
    ranks = _parse_hand(hand)
    if len(ranks) < 3:
        return None
    if hand_type in ("豹子", "同花顺", "顺子"):
        if hand_type != "豹子" and ranks == [14, 3, 2]:
            return 3
        return ranks[0]
    if hand_type in ("金花", "散牌"):
        return (ranks[0], ranks[1], ranks[2])
    if hand_type == "对子":
        if ranks[0] == ranks[1]:
            return (ranks[0], ranks[2])
        return (ranks[1], ranks[0])
    return None


def _call_prob(hand_type: str, hand_value: int | tuple[int, ...] | None, alive: int) -> float:
    """根据牌型+具体手牌+剩余人数计算精确胜率（穷举概率表）。"""
    if hand_value is None:
        return 0.0
    opponents = max(alive - 1, 1)
    return win_prob_n(hand_type, hand_value, opponents)


def _should_call(hand_type: str, hand_value: int | tuple[int, ...] | None, alive: int, good_hands: list[str]) -> bool:
    """综合牌型、具体手牌与剩余人数判断是否跟注。"""
    if hand_type not in good_hands:
        return False
    win = _call_prob(hand_type, hand_value, alive)
    # 人数越多门槛越高：2 人时 > 25%，5 人时 > 35%
    opponents = max(alive - 1, 1)
    threshold = 0.25 + min(opponents, 8) * 0.02
    return win >= threshold


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    interval = float(cfg.get("zjh_poll_interval", 2) or 2)
    fold_pending = False
    turns_taken = 0
    last_rid: str | None = None

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
                hand_type = _normalize_hand_type(s.get("handType", ""))
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

                # 轮到我了
                if joined and is_turn and phase == "playing":
                    if hand:
                        # 已经看过牌 → 根据牌型+剩余人数决策
                        alive_n = _alive_count(g)
                        hand_value = _extract_hand_value(hand_type, hand)
                        if _should_call(hand_type, hand_value, alive_n, good_hands):
                            ctx.log.info("跟注（%s，剩余 %d 人）", hand_type, alive_n)
                            await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(f"🃏 跟注: {hand} ({hand_type}) 剩余{alive_n}人")
                        else:
                            ctx.log.info(
                                "弃牌（%s，剩余 %d 人，胜率不足）",
                                hand_type,
                                alive_n,
                            )
                            await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                            if fc:
                                fold_pending = True
                            else:
                                if cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 弃牌: {hand} ({hand_type}) 剩余{alive_n}人")
                    elif turns_taken == 0:
                        # 第一轮蒙牌（盲跟）
                        ctx.log.info("第一轮蒙牌，盲跟")
                        await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                        turns_taken += 1
                    else:
                        # 第二轮看牌
                        ctx.log.info("轮到我了！看牌...")
                        r = await client.post("/api/portal/zhajinhua/action", {"action": "peek"})
                        if r.get("ok"):
                            hand = r.get("game", {}).get("self", {}).get("hand", "?")
                            hand_type = _normalize_hand_type(r.get("game", {}).get("self", {}).get("handType", "?"))
                            fc = r.get("game", {}).get("self", {}).get("foldConfirm", False)
                            ctx.log.info("手牌: %s (%s)", hand, hand_type)

                            alive_n = _alive_count(g)
                            hand_value = _extract_hand_value(hand_type, hand)
                            if _should_call(hand_type, hand_value, alive_n, good_hands):
                                ctx.log.info("跟注（%s，剩余 %d 人）", hand_type, alive_n)
                                await client.post(
                                    "/api/portal/zhajinhua/action",
                                    {"action": "call"},
                                )
                                if cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 跟注: {hand} ({hand_type}) 剩余{alive_n}人")
                            else:
                                ctx.log.info(
                                    "弃牌（%s，剩余 %d 人，胜率不足）",
                                    hand_type,
                                    alive_n,
                                )
                                await client.post(
                                    "/api/portal/zhajinhua/action",
                                    {"action": "fold"},
                                )
                                if fc:
                                    fold_pending = True
                                elif cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 弃牌: {hand} ({hand_type}) 剩余{alive_n}人")

                elif fold_pending and alive and is_turn:
                    # 双击确认弃牌
                    ctx.log.info("确认弃牌...")
                    r = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                    if r.get("ok"):
                        ctx.log.info("确认弃牌成功")
                        if cfg.get("zjh_notify_fold_confirm", False):
                            await ctx.notify("🃏 双击确认弃牌")
                        fold_pending = False

                # 新牌局开始 → 重置轮次计数 + 作废旧 CSRF
                if rid and rid != last_rid:
                    last_rid = rid
                    turns_taken = 0
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
