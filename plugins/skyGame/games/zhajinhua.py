# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 轮到我了 → 第一轮蒙牌（盲跟），第二轮看牌
#   - 看牌后完全按增量期望收益（EV）决策：EV ≥ 0 跟注，否则弃牌
#   - 胜率按对手看牌状态分开计算：蒙牌对手用 p^n，已看牌且继续下注的对手
#     按其行动时底池赔率反推牌力门槛再做条件胜率
#   - 支持双击弃牌确认
#   - 新牌局作废 CSRF（下次 POST 自动重取）

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from . import hdsky_auth
from .hdsky import HdskyClient
from .zjh_prob import win_prob_1v1

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
class _OpponentSnapshot:
    """对手看牌后最近一次继续下注前的牌局快照。"""

    pot: float
    call_bet: float
    opponents: int


@dataclass(frozen=True)
class _PlayerState:
    """用于相邻轮询比较的玩家公开状态。"""

    alive: bool
    seen: bool
    bet: float | None
    last_action: str


@dataclass
class _RoundTracker:
    """一局内的对手下注快照与上一轮公开状态。"""

    players: dict[str, _PlayerState] = field(default_factory=dict)
    pot: float | None = None
    call_bet: float | None = None
    snapshots: dict[str, _OpponentSnapshot] = field(default_factory=dict)


@dataclass(frozen=True)
class _CallDecision:
    """一次跟注的概率和增量期望收益。"""

    one_vs_one: float
    blind_opponents: int
    seen_opponents: int
    seen_thresholds: tuple[tuple[float, bool], ...]
    win_probability: float
    expected_value: float


@dataclass(frozen=True)
class _Choice:
    """纯 EV 决策结果：是否跟注、原因与概率明细。"""

    call: bool
    reason: str
    decision: _CallDecision | None


_poll_task: asyncio.Task[None] | None = None


def _normalize_hand_type(hand_type: str) -> str:
    """将门户牌型名称或“手牌 → 牌型”组合文本归一为概率表名称。"""
    normalized = hand_type.rsplit("→", 1)[-1].strip()
    return _HAND_TYPE_ALIASES.get(normalized, normalized)


def _parse_hand(hand: str) -> list[int]:
    """解析手牌字符串如 'A♠ K♠ Q♠' 为降序点数列表 [14, 13, 12]。"""
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


def _players(game: dict[str, Any]) -> list[dict[str, Any]]:
    """返回牌局公开玩家列表，缺失时为空。"""
    players = game.get("players") or game.get("seats")
    return [player for player in players if isinstance(player, dict)] if isinstance(players, list) else []


def _player_key(player: dict[str, Any], index: int) -> str:
    """优先以服务端玩家 ID 标识，缺失时仅在本局内使用座位索引。"""
    player_id = player.get("id")
    return str(player_id) if player_id else f"seat:{index}"


def _is_alive(player: dict[str, Any]) -> bool:
    """读取玩家是否仍在局。"""
    return bool(player.get("alive", player.get("active", False)))


def _is_self(player: dict[str, Any]) -> bool:
    """读取玩家是否是本账号。"""
    return bool(player.get("isSelf") or player.get("self"))


def _player_state(player: dict[str, Any]) -> _PlayerState:
    """提取用于轮询比较的公开状态。"""
    bet = player.get("bet")
    return _PlayerState(
        alive=_is_alive(player),
        seen=bool(player.get("seen", False)),
        bet=float(bet) if isinstance(bet, (int, float)) else None,
        last_action=str(player.get("lastAction", "")),
    )


def _opponent_entries(game: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """返回仍在局且非自身的对手标识与公开信息。"""
    return [
        (_player_key(player, index), player)
        for index, player in enumerate(_players(game))
        if not _is_self(player) and _is_alive(player)
    ]


def _opponent_counts(game: dict[str, Any]) -> tuple[int, int]:
    """返回仍在局的蒙牌和已看牌对手数量。"""
    opponents = _opponent_entries(game)
    if not opponents and not _players(game):
        return 1, 0
    seen = sum(1 for _, player in opponents if player.get("seen", False))
    return len(opponents) - seen, seen


def _opponent_threshold(snapshot: _OpponentSnapshot | None) -> float | None:
    """按对手行动前的底池赔率反推其最小单挑牌力。"""
    if snapshot is None or snapshot.pot <= 0 or snapshot.call_bet <= 0:
        return None
    pot_odds = snapshot.call_bet / (snapshot.pot + snapshot.call_bet)
    return pot_odds ** (1 / max(snapshot.opponents, 1))


def _is_continue_action(last_action: str) -> bool:
    """判断公开动作文本是否表明玩家看牌后继续下注。"""
    action = last_action.lower()
    return any(token in action for token in ("跟", "加", "call", "raise"))


def _update_round_tracker(game: dict[str, Any], tracker: _RoundTracker, log: Any = None) -> None:
    """根据相邻轮询记录对手看牌后继续下注时的行动前快照。"""
    pot = game.get("pot")
    call_bet = game.get("callBet")
    if not isinstance(pot, (int, float)) or not isinstance(call_bet, (int, float)):
        return

    opponents = _opponent_entries(game)
    # 上一轮存活对手数（不含自己）；行动者面对的是其余对手，需再减自身一人
    previous_opponents = sum(1 for state in tracker.players.values() if state.alive)
    faced_opponents = max(previous_opponents - 1, 1)
    for index, player in enumerate(_players(game)):
        if _is_self(player):
            continue
        key = _player_key(player, index)
        current = _player_state(player)
        previous = tracker.players.get(key)
        if previous and current.alive and current.seen:
            bet_increased = previous.bet is not None and current.bet is not None and current.bet > previous.bet
            action_changed = current.last_action != previous.last_action and _is_continue_action(current.last_action)
            if previous.seen and (bet_increased or action_changed):
                if tracker.pot is not None and tracker.call_bet is not None:
                    snapshot = _OpponentSnapshot(
                        pot=tracker.pot,
                        call_bet=tracker.call_bet,
                        opponents=faced_opponents,
                    )
                    tracker.snapshots[key] = snapshot
                    if log:
                        inferred = _opponent_threshold(snapshot)
                        log.info(
                            "记录对手下注快照 %s: 行动前底池=%.0f 成本=%.0f 面对对手=%d → 推断门槛=%s",
                            key,
                            snapshot.pot,
                            snapshot.call_bet,
                            snapshot.opponents,
                            f"{inferred:.3f}" if inferred is not None else "无法推断",
                        )
        tracker.players[key] = current

    active_keys = {key for key, _ in opponents}
    tracker.players = {key: state for key, state in tracker.players.items() if key in active_keys}
    tracker.snapshots = {key: snapshot for key, snapshot in tracker.snapshots.items() if key in active_keys}
    tracker.pot = float(pot)
    tracker.call_bet = float(call_bet)


def _call_decision(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
) -> _CallDecision | None:
    """按对手看牌状态及其最近正 EV 行为计算本次跟注的增量 EV。"""
    if hand_value is None or not 0 <= fallback_threshold < 1:
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
    seen_thresholds: list[tuple[float, bool]] = []
    for key, player in _opponent_entries(game):
        if not player.get("seen", False):
            continue
        threshold = _opponent_threshold(tracker.snapshots.get(key))
        observed = threshold is not None
        threshold = threshold if threshold is not None else fallback_threshold
        versus_seen = max(one_vs_one - threshold, 0.0) / (1.0 - threshold)
        win_probability *= versus_seen
        seen_thresholds.append((threshold, observed))

    expected_value = win_probability * (pot + call_bet) - call_bet
    return _CallDecision(one_vs_one, blind, seen, tuple(seen_thresholds), win_probability, expected_value)


def _choose(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
) -> _Choice:
    """纯 EV 决策：跟注当且仅当数据有效且增量期望收益非负。"""
    decision = _call_decision(hand_type, hand_value, game, fallback_threshold, tracker)
    if decision is None:
        return _Choice(False, "牌局数据不完整，保守弃牌", None)
    if decision.expected_value < 0:
        return _Choice(False, "跟注期望收益为负", decision)
    return _Choice(True, "期望收益非负", decision)


def _threshold_summary(decision: _CallDecision) -> str:
    """格式化已看牌对手的隐含牌力门槛与来源。"""
    return ", ".join(
        f"{threshold:.1%}{'实测' if observed else '回退'}" for threshold, observed in decision.seen_thresholds
    )


def _opponent_brief(decision: _CallDecision) -> str:
    """对手蒙/看构成与看牌门槛的简短描述。"""
    brief = f"蒙{decision.blind_opponents}/看{decision.seen_opponents}"
    if decision.seen_opponents:
        brief += f"（门槛 {_threshold_summary(decision)}）"
    return brief


def _log_decision(
    ctx: object,
    hand: str,
    hand_type: str,
    hand_value: Any,
    game: dict[str, Any],
    choice: _Choice,
    tracker: _RoundTracker,
) -> None:
    """打印一次决策的完整推导，便于核对胜率与 EV。"""
    log = ctx.log
    decision = choice.decision
    pot = game.get("pot")
    call_bet = game.get("callBet")
    if decision is None:
        log.info(
            "决策[弃] %s(%s) 键值=%s 原因=%s 底池=%s 成本=%s", hand, hand_type, hand_value, choice.reason, pot, call_bet
        )
        return
    seen_detail = []
    for key, player in _opponent_entries(game):
        if not player.get("seen", False):
            continue
        snap = tracker.snapshots.get(key)
        inferred = _opponent_threshold(snap)
        if snap is not None:
            src = f"实测 快照(底池{snap.pot:.0f}/成本{snap.call_bet:.0f}/对手{snap.opponents})"
        else:
            src = "回退(未观测到下注)"
        seen_detail.append(f"{key} 门槛={'%.3f' % inferred if inferred is not None else '回退值'} {src}")
    log.info(
        "决策[%s] %s(%s) 键值=%s | 单挑胜率=%.4f 蒙=%d 看=%d | 看牌对手[%s] | "
        "终胜率=%.4f | 底池=%.0f 成本=%.0f | EV=%+.2f | 原因=%s",
        "跟" if choice.call else "弃",
        hand,
        hand_type,
        hand_value,
        decision.one_vs_one,
        decision.blind_opponents,
        decision.seen_opponents,
        "; ".join(seen_detail) or "无",
        decision.win_probability,
        pot,
        call_bet,
        decision.expected_value,
        choice.reason,
    )


def _call_notification(
    rid: Any, hand: str, hand_type: str, decision: _CallDecision, pot: float, call_bet: float
) -> str:
    """生成跟注通知：牌桌、手牌、底池成本、对手构成、胜率与期望收益。"""
    return "\n".join(
        [
            "🃏 炸金花 · 跟注",
            f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）",
            f"底池 {pot:.0f} · 跟注 {call_bet:.0f}",
            f"对手 {_opponent_brief(decision)} · 胜率 {decision.win_probability:.1%}",
            f"期望收益 {decision.expected_value:+.0f}",
        ]
    )


def _fold_notification(rid: Any, hand: str, hand_type: str, reason: str, decision: _CallDecision | None) -> str:
    """生成弃牌通知：手牌、概率明细（若有）与弃牌原因。"""
    lines = ["🃏 炸金花 · 弃牌", f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）"]
    if decision is not None:
        lines.append(f"对手 {_opponent_brief(decision)} · 胜率 {decision.win_probability:.1%}")
        lines.append(f"期望收益 {decision.expected_value:+.0f}")
    lines.append(f"原因：{reason}")
    return "\n".join(lines)


async def _act_on_hand(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    hand: str,
    hand_type: str,
    fallback_threshold: float,
    tracker: _RoundTracker,
) -> bool:
    """对已看牌手牌做纯 EV 决策并执行，返回是否需要双击确认弃牌。"""
    rid = game.get("roundId")
    hand_value = _extract_hand_value(hand_type, hand)
    choice = _choose(hand_type, hand_value, game, fallback_threshold, tracker)
    _log_decision(ctx, hand, hand_type, hand_value, game, choice, tracker)

    if choice.call:
        decision = choice.decision
        await client.post("/api/portal/zhajinhua/action", {"action": "call"})
        if cfg.get("zjh_notify_hand", True) and decision is not None:
            await ctx.notify(_call_notification(rid, hand, hand_type, decision, game["pot"], game["callBet"]))
        return False

    await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if cfg.get("zjh_notify_hand", True):
        await ctx.notify(_fold_notification(rid, hand, hand_type, choice.reason, choice.decision))
    return bool(game.get("self", {}).get("foldConfirm", False))


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    interval = float(cfg.get("zjh_poll_interval", 2) or 2)
    fold_pending = False
    turns_taken = 0
    last_rid: Any = None
    tracker = _RoundTracker()

    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        while True:
            try:
                if not cfg.get("zjh_enabled", True):
                    await asyncio.sleep(interval)
                    continue

                # 每轮读最新配置（cookie 路径/门户地址可能被改）
                client.configure(str(cfg.get("hdsky_cookie_file", "") or ""), str(cfg.get("hdsky_base_url", "") or ""))
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
                if rid and rid != last_rid:
                    last_rid = rid
                    turns_taken = 0
                    tracker = _RoundTracker()
                _update_round_tracker(g, tracker, ctx.log)
                phase = g.get("phase", "")
                actions = g.get("actions", [])
                s = g.get("self", {})
                joined = s.get("joined", False)
                is_turn = s.get("isTurn", False)
                alive = s.get("alive", False)
                hand = s.get("hand", "")
                hand_type = _normalize_hand_type(s.get("handType", ""))

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
                        # 已经看过牌 → 纯 EV 决策
                        fold_pending = await _act_on_hand(ctx, client, cfg, g, hand, hand_type, seen_threshold, tracker)
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
                            ctx.log.info("手牌: %s (%s)", hand, hand_type)
                            fold_pending = await _act_on_hand(
                                ctx, client, cfg, g, hand, hand_type, seen_threshold, tracker
                            )

                elif fold_pending and alive and is_turn:
                    # 双击确认弃牌
                    ctx.log.info("确认弃牌...")
                    r = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
                    if r.get("ok"):
                        ctx.log.info("确认弃牌成功")
                        if cfg.get("zjh_notify_fold_confirm", False):
                            await ctx.notify("🃏 双击确认弃牌")
                        fold_pending = False

                # 新牌局 CSRF 作废（轮次状态已在本轮开头完成重置）
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
