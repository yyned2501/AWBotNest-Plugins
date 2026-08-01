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
from dataclasses import dataclass
from typing import Any

from . import hdsky_auth
from .hdsky import HdskyClient
from .zjh_prob import win_prob_1v1

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


@dataclass(frozen=True)
class _CallDecision:
    """一次跟注的概率和增量期望收益。"""

    blind_opponents: int
    seen_opponents: int
    win_probability: float
    expected_value: float


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


def _opponent_counts(game: dict[str, Any]) -> tuple[int, int]:
    """返回仍在局的蒙牌和已看牌对手数量。"""
    players = game.get("players") or game.get("seats")
    if not isinstance(players, list):
        return 1, 0

    blind = 0
    seen = 0
    for player in players:
        if not isinstance(player, dict):
            continue
        if player.get("isSelf") or player.get("self"):
            continue
        if not player.get("alive", player.get("active", False)):
            continue
        if player.get("seen", False):
            seen += 1
        else:
            blind += 1
    return blind, seen


def _call_decision(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    seen_threshold: float,
) -> _CallDecision | None:
    """按对手看牌状态和底池赔率计算本次跟注的增量 EV。"""
    if hand_value is None or not 0 <= seen_threshold < 1:
        return None

    pot = game.get("pot")
    call_bet = game.get("callBet")
    if not isinstance(pot, (int, float)) or not isinstance(call_bet, (int, float)):
        return None
    if pot <= 0 or call_bet <= 0:
        return None

    one_vs_one = win_prob_1v1(hand_type, hand_value)
    if one_vs_one <= 0:
        return None

    blind, seen = _opponent_counts(game)
    win_probability = one_vs_one**blind
    if seen:
        versus_seen = max(one_vs_one - seen_threshold, 0.0) / (1.0 - seen_threshold)
        win_probability *= versus_seen**seen

    expected_value = win_probability * (pot + call_bet) - call_bet
    return _CallDecision(blind, seen, win_probability, expected_value)


def _should_call(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    good_hands: list[str],
    seen_threshold: float,
) -> _CallDecision | None:
    """仅在牌型已启用且跟注为非负 EV 时返回决策详情。"""
    if hand_type not in good_hands:
        return None
    decision = _call_decision(hand_type, hand_value, game, seen_threshold)
    if decision is None or decision.expected_value < 0:
        return None
    return decision


def _call_notification(hand: str, hand_type: str, decision: _CallDecision) -> str:
    """生成包含对手状态、胜率和 EV 的跟注通知。"""
    opponents = f"蒙{decision.blind_opponents}/看{decision.seen_opponents}"
    return (
        f"🃏 跟注: {hand} ({hand_type}) {opponents} 胜率{decision.win_probability:.1%} EV{decision.expected_value:.0f}"
    )


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
                seen_threshold = float(cfg.get("zjh_peeked_threshold", 50)) / 100

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
                        # 已经看过牌 → 按对手看牌状态、底池和成本决策
                        hand_value = _extract_hand_value(hand_type, hand)
                        decision = _should_call(hand_type, hand_value, g, good_hands, seen_threshold)
                        if decision:
                            ctx.log.info(
                                "跟注（%s，蒙牌%d/看牌%d，胜率%.1f%%，底池%.0f，成本%.0f，EV%.0f）",
                                hand_type,
                                decision.blind_opponents,
                                decision.seen_opponents,
                                decision.win_probability * 100,
                                g["pot"],
                                g["callBet"],
                                decision.expected_value,
                            )
                            await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(_call_notification(hand, hand_type, decision))
                        else:
                            ctx.log.info("弃牌（%s，牌型未启用或跟注 EV 为负）", hand_type)
                            await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                            if fc:
                                fold_pending = True
                            elif cfg.get("zjh_notify_hand", True):
                                await ctx.notify(f"🃏 弃牌: {hand} ({hand_type})")
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
                            peek_game = r.get("game")
                            if isinstance(peek_game, dict):
                                g = peek_game
                            peek_self = g.get("self", {})
                            hand = peek_self.get("hand", "?")
                            hand_type = _normalize_hand_type(peek_self.get("handType", "?"))
                            fc = peek_self.get("foldConfirm", False)
                            ctx.log.info("手牌: %s (%s)", hand, hand_type)

                            hand_value = _extract_hand_value(hand_type, hand)
                            decision = _should_call(hand_type, hand_value, g, good_hands, seen_threshold)
                            if decision:
                                ctx.log.info(
                                    "跟注（%s，蒙牌%d/看牌%d，胜率%.1f%%，底池%.0f，成本%.0f，EV%.0f）",
                                    hand_type,
                                    decision.blind_opponents,
                                    decision.seen_opponents,
                                    decision.win_probability * 100,
                                    g["pot"],
                                    g["callBet"],
                                    decision.expected_value,
                                )
                                await client.post(
                                    "/api/portal/zhajinhua/action",
                                    {"action": "call"},
                                )
                                if cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(_call_notification(hand, hand_type, decision))
                            else:
                                ctx.log.info("弃牌（%s，牌型未启用或跟注 EV 为负）", hand_type)
                                await client.post(
                                    "/api/portal/zhajinhua/action",
                                    {"action": "fold"},
                                )
                                if fc:
                                    fold_pending = True
                                elif cfg.get("zjh_notify_hand", True):
                                    await ctx.notify(f"🃏 弃牌: {hand} ({hand_type})")

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
