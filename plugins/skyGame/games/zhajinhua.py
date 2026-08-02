# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 蒙牌按 EV 决策「蒙还是看」：蒙牌跟注成本为已看牌一半，EV ≥ 0 继续盲跟；
#     EV < 0 看牌买信息，牌大再上、牌小弃（不区分单挑/多人）
#   - 看牌后完全按增量期望收益（EV）决策：EV ≥ 0 跟注，否则弃牌（不区分单挑/多人）
#   - 服务端 actions 出现 showdown 时优先应战；这是门户动作授权，不是策略绕行
#   - 胜率按对手看牌状态分开计算：已看牌（手牌确定）对蒙牌对手用 t^B；蒙牌（手牌未知）
#     不能把平均胜率 0.5 当固定手牌，需对未知手牌强度积分（三人全蒙为 1/3 而非 0.5²）；
#     已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛再做条件胜率
#   - 支持双击弃牌确认
#   - 新牌局作废 CSRF（下次 POST 自动重取）

from __future__ import annotations

import asyncio
import math
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

# 双击确认弃牌的最大连续重试次数：超过即放弃本局确认，避免门户持续拒绝时无限重发。
_FOLD_CONFIRM_MAX_RETRIES = 3


@dataclass(frozen=True)
class _OpponentSnapshot:
    """对手某次理性决策前的牌局快照及其面对的对手权重。"""

    pot: float
    call_bet: float
    opponents: int
    blind_opponents: int | None = None
    seen_thresholds: tuple[float, ...] = ()


@dataclass(frozen=True)
class _PlayerState:
    """用于相邻轮询比较的玩家公开状态。"""

    alive: bool
    seen: bool
    bet: float | None
    last_action: str


@dataclass(frozen=True)
class _PendingFold:
    """等待门户二次确认的弃牌通知内容。"""

    rid: Any
    hand: str
    hand_type: str
    choice: _Choice


@dataclass
class _RoundTracker:
    """一局内的对手上牌/下注快照、上一轮公开状态和待确认弃牌。"""

    players: dict[str, _PlayerState] = field(default_factory=dict)
    pot: float | None = None
    call_bet: float | None = None
    peek_snapshots: dict[str, _OpponentSnapshot] = field(default_factory=dict)
    snapshots: dict[str, _OpponentSnapshot] = field(default_factory=dict)
    self_thresholds: dict[str, float] = field(default_factory=dict)
    pending_fold: _PendingFold | None = None


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


def _self_hand(game: dict[str, Any]) -> tuple[str, str]:
    """从牌局状态读取我方手牌与归一牌型；缺失时手牌为空串。"""
    self_state = game.get("self", {})
    hand = str(self_state.get("hand", "") or "")
    hand_type = _normalize_hand_type(str(self_state.get("handType", "") or ""))
    return hand, hand_type


async def _acquire_hand_after_peek(client: HdskyClient, game: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """看牌后确保读到我方手牌：响应里缺手牌时重拉状态补齐（最多 3 次短重试）。"""
    hand, hand_type = _self_hand(game)
    for _ in range(3):
        if hand:
            break
        await asyncio.sleep(0.5)
        refetch = await client.get("/api/portal/zhajinhua")
        if "_error" not in refetch:
            game = refetch.get("game", {})
            hand, hand_type = _self_hand(game)
    return game, hand, hand_type


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


def _in_hand(game: dict[str, Any]) -> bool:
    """本账号是否仍在当前牌局（未弃牌/未出局）；只有此时才需跟踪对手快照。"""
    return bool(game.get("self", {}).get("alive", False))


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


def _actual_win_probability(hand_threshold: float, blind_opponents: int, seen_thresholds: tuple[float, ...]) -> float:
    """按蒙牌和已看牌对手权重计算实际胜率。"""
    if not 0 < hand_threshold <= 1 or blind_opponents < 0:
        return 0.0
    probability = hand_threshold**blind_opponents
    for seen_threshold in seen_thresholds:
        if not 0 <= seen_threshold < 1 or hand_threshold <= seen_threshold:
            return 0.0
        probability *= (hand_threshold - seen_threshold) / (1 - seen_threshold)
    return probability


def _blind_win_probability(blind_opponents: int, seen_thresholds: tuple[float, ...]) -> float:
    """蒙牌（手牌未知）时对蒙牌与已看牌对手的实际胜率——对未知手牌强度精确积分。

    手牌未知时不能把平均单挑胜率 0.5 当固定手牌代进 `t^B`，那会低估：「赢对手A」
    「赢对手B」两件事经我方手牌强弱相关，并不独立。三个随机手牌的玩家各以 1/3 概率
    最大，而非 0.5²=1/4。正确做法是把我方手牌强度 t 视为近似 Uniform[0,1] 的随机量积分：

        P = ∫₀¹ t^B · Πᵢ max(0, (t − Tᵢ)/(1 − Tᵢ)) dt

    展开为多项式后逐项精确积分（闭式、无近似）。全蒙牌无看牌对手退化为 1/(B+1)，
    单挑纯蒙牌为 1/2；已看牌对手按其门槛 Tᵢ 进入条件胜率因子。
    """
    if blind_opponents < 0 or any(not 0 <= threshold < 1 for threshold in seen_thresholds):
        return 0.0

    # 分子多项式 P(t) = t^B · Πᵢ (t − Tᵢ)，系数按升幂排列 [c0, c1, ..., cn]。
    poly = [0.0] * blind_opponents + [1.0]
    denominator = 1.0
    for threshold in seen_thresholds:
        poly = [-threshold * poly[0]] + [poly[i - 1] - threshold * poly[i] for i in range(1, len(poly))] + [poly[-1]]
        denominator *= 1.0 - threshold

    lower = max(seen_thresholds, default=0.0)
    integral = sum(coefficient * (1.0 - lower ** (power + 1)) / (power + 1) for power, coefficient in enumerate(poly))
    return max(integral / denominator, 0.0)


def _hand_threshold_for_actual_win_probability(
    actual_threshold: float, blind_opponents: int, seen_thresholds: tuple[float, ...]
) -> float | None:
    """用二分法反推达到实际胜率门槛所需的最低单挑牌力。"""
    if not 0 < actual_threshold < 1 or blind_opponents < 0:
        return None
    if blind_opponents == 0 and not seen_thresholds:
        return None
    if any(not 0 <= threshold < 1 for threshold in seen_thresholds):
        return None
    if blind_opponents == 0 and len(seen_thresholds) == 1:
        threshold = seen_thresholds[0]
        return threshold + actual_threshold * (1 - threshold)

    lower = math.nextafter(max(seen_thresholds, default=0.0), 1.0)
    upper = 1.0
    for _ in range(80):
        middle = (lower + upper) / 2
        if _actual_win_probability(middle, blind_opponents, seen_thresholds) < actual_threshold:
            lower = middle
        else:
            upper = middle
    return upper


def _opponent_threshold(snapshot: _OpponentSnapshot | None) -> float | None:
    """反推对手在该快照下牌局整体胜率的盈亏平衡门槛。"""
    if snapshot is None or snapshot.pot <= 0 or snapshot.call_bet <= 0:
        return None
    return snapshot.call_bet / (snapshot.pot + snapshot.call_bet)


def _opponent_hand_threshold(snapshot: _OpponentSnapshot | None) -> float | None:
    """按蒙牌与已看牌对手权重精确反推对手最低单挑牌力。"""
    actual_threshold = _opponent_threshold(snapshot)
    if actual_threshold is None or snapshot is None:
        return None
    blind_opponents = snapshot.blind_opponents if snapshot.blind_opponents is not None else snapshot.opponents
    return _hand_threshold_for_actual_win_probability(actual_threshold, blind_opponents, snapshot.seen_thresholds)


def _combined_opponent_threshold(
    peek_snapshot: _OpponentSnapshot | None, continue_snapshot: _OpponentSnapshot | None
) -> float | None:
    """按上牌和看牌后继续下注两次决策推导对手的综合最低牌力。"""
    thresholds = [
        threshold
        for snapshot in (peek_snapshot, continue_snapshot)
        if (threshold := _opponent_hand_threshold(snapshot)) is not None
    ]
    return max(thresholds, default=None)


def _combined_self_threshold(tracker: _RoundTracker) -> float | None:
    """返回我方本局已确认行动门槛中的最高值。"""
    return max(tracker.self_thresholds.values(), default=None)


def _self_key(game: dict[str, Any]) -> str | None:
    """返回本账号在本局公开玩家列表中的标识。"""
    return next((_player_key(player, index) for index, player in enumerate(_players(game)) if _is_self(player)), None)


def _record_self_threshold(game: dict[str, Any], tracker: _RoundTracker, action: str, log: Any = None) -> float | None:
    """记录我方一次理性行动对应的最低单挑牌型门槛。"""
    pot = game.get("pot")
    call_bet = game.get("callBet")
    self_key = _self_key(game)
    if not isinstance(pot, (int, float)) or not isinstance(call_bet, (int, float)) or self_key is None:
        return None
    snapshot = _snapshot_for_actor(game, tracker, self_key, float(pot), float(call_bet))
    threshold = _opponent_hand_threshold(snapshot)
    if threshold is not None:
        tracker.self_thresholds[action] = max(threshold, tracker.self_thresholds.get(action, threshold))
    if log:
        combined = _combined_self_threshold(tracker)
        log.info(
            "记录我方%s门槛: 行动前底池=%.0f 成本=%.0f 蒙=%d 看门槛=%s → 综合门槛=%s",
            "上牌" if action == "peek" else "下注",
            snapshot.pot,
            snapshot.call_bet,
            snapshot.blind_opponents,
            snapshot.seen_thresholds,
            f"{combined:.3f}" if combined is not None else "无法推断",
        )
    return threshold


def _snapshot_for_actor(
    game: dict[str, Any], tracker: _RoundTracker, actor_key: str, pot: float, call_bet: float
) -> _OpponentSnapshot:
    """按行动者面对的蒙牌和已看牌对手构造决策快照。"""
    blind_opponents = 0
    seen_thresholds: list[float] = []
    opponents = 0
    for index, player in enumerate(_players(game)):
        key = _player_key(player, index)
        if key == actor_key or not _is_alive(player):
            continue
        opponents += 1
        previous = tracker.players.get(key)
        seen = previous.seen if previous is not None else bool(player.get("seen", False))
        if not seen:
            blind_opponents += 1
            continue
        if _is_self(player):
            threshold = _combined_self_threshold(tracker)
        else:
            threshold = _combined_opponent_threshold(tracker.peek_snapshots.get(key), tracker.snapshots.get(key))
        if threshold is not None:
            seen_thresholds.append(threshold)
    return _OpponentSnapshot(
        pot=pot,
        call_bet=call_bet,
        opponents=max(opponents, 1),
        blind_opponents=blind_opponents,
        seen_thresholds=tuple(seen_thresholds),
    )


def _is_continue_action(last_action: str) -> bool:
    """判断公开动作文本是否表明玩家看牌后继续下注。"""
    action = last_action.lower()
    return any(token in action for token in ("跟", "加", "call", "raise"))


def _update_round_tracker(game: dict[str, Any], tracker: _RoundTracker, log: Any = None) -> None:
    """根据相邻轮询记录双方上牌、继续下注前的快照和牌型门槛。"""
    pot = game.get("pot")
    call_bet = game.get("callBet")
    if not isinstance(pot, (int, float)) or not isinstance(call_bet, (int, float)):
        return

    for index, player in enumerate(_players(game)):
        key = _player_key(player, index)
        current = _player_state(player)
        previous = tracker.players.get(key)
        is_self = _is_self(player)
        if previous and current.alive and current.seen and tracker.pot is not None and tracker.call_bet is not None:
            snapshot = _snapshot_for_actor(game, tracker, key, tracker.pot, tracker.call_bet)
            if not previous.seen:
                threshold = _opponent_hand_threshold(snapshot)
                if is_self:
                    if threshold is not None:
                        tracker.self_thresholds["peek"] = threshold
                    if log:
                        log.info(
                            "记录我方上牌门槛: 上牌前底池=%.0f 成本=%.0f 蒙=%d 看门槛=%s → 门槛=%s",
                            snapshot.pot,
                            snapshot.call_bet,
                            snapshot.blind_opponents,
                            snapshot.seen_thresholds,
                            f"{threshold:.3f}" if threshold is not None else "无法推断",
                        )
                else:
                    tracker.peek_snapshots[key] = snapshot
                    if log:
                        log.info(
                            "记录对手上牌快照 %s: 上牌前底池=%.0f 成本=%.0f 蒙=%d 看门槛=%s → 门槛=%s",
                            key,
                            snapshot.pot,
                            snapshot.call_bet,
                            snapshot.blind_opponents,
                            snapshot.seen_thresholds,
                            f"{threshold:.3f}" if threshold is not None else "无法推断",
                        )
            else:
                bet_increased = previous.bet is not None and current.bet is not None and current.bet > previous.bet
                action_changed = current.last_action != previous.last_action and _is_continue_action(
                    current.last_action
                )
                if bet_increased or action_changed:
                    threshold = _opponent_hand_threshold(snapshot)
                    if is_self:
                        if threshold is not None:
                            tracker.self_thresholds["continue"] = max(
                                threshold, tracker.self_thresholds.get("peek", threshold)
                            )
                        if log:
                            combined = _combined_self_threshold(tracker)
                            log.info(
                                "记录我方下注门槛: 行动前底池=%.0f 成本=%.0f 蒙=%d 看门槛=%s → 综合门槛=%s",
                                snapshot.pot,
                                snapshot.call_bet,
                                snapshot.blind_opponents,
                                snapshot.seen_thresholds,
                                f"{combined:.3f}" if combined is not None else "无法推断",
                            )
                    else:
                        tracker.snapshots[key] = snapshot
                        if log:
                            inferred = _combined_opponent_threshold(tracker.peek_snapshots.get(key), snapshot)
                            log.info(
                                "记录对手下注快照 %s: 行动前底池=%.0f 成本=%.0f 蒙=%d 看门槛=%s → 综合门槛=%s",
                                key,
                                snapshot.pot,
                                snapshot.call_bet,
                                snapshot.blind_opponents,
                                snapshot.seen_thresholds,
                                f"{inferred:.3f}" if inferred is not None else "无法推断",
                            )
        tracker.players[key] = current

    active_keys = {_player_key(player, index) for index, player in enumerate(_players(game)) if _is_alive(player)}
    tracker.players = {key: state for key, state in tracker.players.items() if key in active_keys}
    tracker.peek_snapshots = {key: snapshot for key, snapshot in tracker.peek_snapshots.items() if key in active_keys}
    tracker.snapshots = {key: snapshot for key, snapshot in tracker.snapshots.items() if key in active_keys}
    tracker.pot = float(pot)
    tracker.call_bet = float(call_bet)


def _seen_opponent_thresholds(
    game: dict[str, Any], tracker: _RoundTracker, fallback_threshold: float
) -> tuple[int, list[tuple[float, bool]]]:
    """统计蒙牌对手数，并收集已看牌对手门槛（实测反推优先，缺失才用回退分位）。"""
    blind, _ = _opponent_counts(game)
    seen_thresholds: list[tuple[float, bool]] = []
    for key, player in _opponent_entries(game):
        if not player.get("seen", False):
            continue
        threshold = _combined_opponent_threshold(tracker.peek_snapshots.get(key), tracker.snapshots.get(key))
        observed = threshold is not None
        threshold = threshold if threshold is not None else fallback_threshold
        seen_thresholds.append((threshold, observed))
    return blind, seen_thresholds


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

    blind, seen_thresholds = _seen_opponent_thresholds(game, tracker, fallback_threshold)
    seen = len(seen_thresholds)

    win_probability = _actual_win_probability(one_vs_one, blind, tuple(threshold for threshold, _ in seen_thresholds))

    expected_value = win_probability * (pot + call_bet) - call_bet
    return _CallDecision(one_vs_one, blind, seen, tuple(seen_thresholds), win_probability, expected_value)


# 蒙牌未知手牌按「平均单挑胜率」估计：随机两手牌对称，任一手压过对手的概率为 0.5。
_BLIND_ONE_VS_ONE = 0.5


def _blind_call_cost(call_bet: float) -> float:
    """蒙牌跟注成本为已看牌的一半（实测同一 callBet=3000 下蒙牌 +1500、已看牌 +3000）。"""
    return call_bet / 2


def _blind_decision(game: dict[str, Any], fallback_threshold: float, tracker: _RoundTracker) -> _CallDecision | None:
    """蒙牌（未看牌）决策评估：手牌未知，胜率对未知手牌强度积分，跟注成本按半价计。

    用于「蒙还是看」的 EV 决策——EV ≥ 0 时蒙牌半价跟注本身就划算，继续盲跟；
    EV < 0 时平均手牌已不划算，看牌买信息（牌大再上、牌小弃）。

    胜率不能把平均单挑胜率 0.5 当固定手牌代进 `t^B`（那会低估：三人全蒙应为 1/3 而非
    0.5²=1/4），改用 `_blind_win_probability` 对未知手牌强度精确积分；`one_vs_one` 字段
    仍记平均单挑胜率 0.5 作展示。成本取已看牌半价。
    """
    if not 0 <= fallback_threshold < 1:
        return None

    pot = game.get("pot")
    call_bet = game.get("callBet")
    if not isinstance(pot, (int, float)) or not isinstance(call_bet, (int, float)):
        return None
    if pot <= 0 or call_bet <= 0:
        return None

    blind, seen_thresholds = _seen_opponent_thresholds(game, tracker, fallback_threshold)
    seen = len(seen_thresholds)

    blind_cost = _blind_call_cost(float(call_bet))
    win_probability = _blind_win_probability(blind, tuple(threshold for threshold, _ in seen_thresholds))
    expected_value = win_probability * (pot + blind_cost) - blind_cost
    return _CallDecision(_BLIND_ONE_VS_ONE, blind, seen, tuple(seen_thresholds), win_probability, expected_value)


def _blind_peek_or_call(
    game: dict[str, Any], actions: list[Any], fallback_threshold: float, tracker: _RoundTracker
) -> tuple[str | None, _CallDecision | None]:
    """多人蒙牌时按 EV 决定「盲跟」还是「看牌」，返回动作与蒙牌评估明细。

    蒙牌跟注半价：EV ≥ 0 时盲跟本身就划算，继续盲跟；EV < 0 时平均手牌已不划算，
    看牌买信息（牌大再上、牌小弃）。门户不给看牌才退回盲跟保底；两者都不给返回 None。
    """
    blind_choice = _blind_decision(game, fallback_threshold, tracker)
    if blind_choice is not None and blind_choice.expected_value >= 0 and "call" in actions:
        return "call", blind_choice
    if "peek" in actions:
        return "peek", blind_choice
    if "call" in actions:
        return "call", blind_choice
    return None, blind_choice


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


def _action_override(actions: list[Any]) -> str | None:
    """从服务端授权动作中取优先级最高的应战开牌动作。"""
    return next((action for action in actions if action == "showdown"), None)


def _choose_action(
    choice: _Choice,
    actions: list[Any],
    open_enabled: bool,
    open_threshold: float,
    raise_enabled: bool,
    raise_threshold: float,
) -> tuple[str, str]:
    """按最终实际胜率选择跟注、主动开牌或追加，动作必须获服务端允许。"""
    decision = choice.decision
    if not choice.call or decision is None:
        return "fold", choice.reason
    win_probability = decision.win_probability
    if open_enabled and "open" in actions and win_probability < open_threshold:
        return "open", f"最终实际胜率{win_probability:.1%}低于主动开牌阈值{open_threshold:.1%}"
    if raise_enabled and "raise" in actions and win_probability >= raise_threshold:
        return "raise", f"最终实际胜率{win_probability:.1%}达到追加阈值{raise_threshold:.1%}"
    return "call", choice.reason


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
        peek_snapshot = tracker.peek_snapshots.get(key)
        continue_snapshot = tracker.snapshots.get(key)
        inferred = _combined_opponent_threshold(peek_snapshot, continue_snapshot)
        details = []
        if peek_snapshot is not None:
            details.append(
                f"上牌(底池{peek_snapshot.pot:.0f}/成本{peek_snapshot.call_bet:.0f}/对手{peek_snapshot.opponents})"
            )
        if continue_snapshot is not None:
            details.append(
                f"下注(底池{continue_snapshot.pot:.0f}/成本{continue_snapshot.call_bet:.0f}/对手{continue_snapshot.opponents})"
            )
        seen_detail.append(
            f"{key} 综合门槛={'%.3f' % inferred if inferred is not None else '回退值'} "
            f"{' + '.join(details) if details else '回退(未观测到上牌或下注)'}"
        )
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


def _action_notification(
    action: str,
    rid: Any,
    hand: str,
    hand_type: str,
    decision: _CallDecision,
    pot: float,
    call_bet: float,
    reason: str,
) -> str:
    """生成跟注、主动开牌、追加或应战开牌的通知。"""
    labels = {"call": "跟注", "open": "主动开牌", "raise": "追加", "showdown": "应战开牌"}
    return "\n".join(
        [
            f"🃏 炸金花 · {labels[action]}",
            f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）",
            f"底池 {pot:.0f} · 当前成本 {call_bet:.0f}",
            f"单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}",
            f"最终实际胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}",
            f"原因：{reason}",
        ]
    )


def _fold_notification(rid: Any, hand: str, hand_type: str, reason: str, decision: _CallDecision | None) -> str:
    """生成弃牌通知：手牌、概率明细（若有）与弃牌原因。"""
    lines = ["🃏 炸金花 · 弃牌", f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）"]
    if decision is not None:
        lines.append(f"单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}")
        lines.append(f"最终实际胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}")
    lines.append(f"原因：{reason}")
    return "\n".join(lines)


def _blind_notification(
    action: str,
    rid: Any,
    decision: _CallDecision | None,
    pot: float,
    call_bet: float,
    reason: str,
) -> str:
    """生成多人蒙牌决策通知：盲跟（蒙）或看牌（看），附蒙牌半价 EV 明细。"""
    labels = {"call": "蒙牌盲跟", "peek": "看牌买信息"}
    lines = [f"🃏 炸金花 · {labels.get(action, action)}", f"牌桌 #{rid} · 未看牌"]
    if decision is not None:
        lines.append(f"底池 {pot:.0f} · 半价成本 {_blind_call_cost(call_bet):.0f}")
        lines.append(f"平均单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}")
        lines.append(f"蒙牌胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}")
    lines.append(f"原因：{reason}")
    return "\n".join(lines)


def _game_result_notification(game_data: dict[str, Any], hand: str, hand_type: str) -> str:
    """生成牌局结束通知：本局结果、我方手牌、对手排行与摊牌手牌。"""
    game = game_data.get("game", {})
    s = game.get("self", {})
    alive = s.get("alive", False)
    players = _players(game)
    result_lines = []
    if alive:
        result_lines.append("🃏 炸金花 · 本局获胜")
    else:
        result_lines.append("🃏 炸金花 · 本局结束")
    if hand:
        result_lines.append(f"手牌 {hand}（{hand_type}）")
    # 对手排行
    rank = 1
    for player in players:
        p_alive = _is_alive(player)
        p_self = _is_self(player)
        p_hand = player.get("hand", "")
        p_hand_type = _normalize_hand_type(player.get("handType", ""))
        if p_self:
            label = "你"
        else:
            label = f"对手{rank}"
            rank += 1
        if p_alive:
            p_hand_str = f" · {p_hand}（{p_hand_type}）" if p_hand else ""
            result_lines.append(f"  {label} 存活{p_hand_str}")
        elif p_hand:
            result_lines.append(f"  {label} 出局 · {p_hand}（{p_hand_type}）")
        else:
            result_lines.append(f"  {label} 出局")
    return "\n".join(result_lines)


async def _notify_game_result(
    ctx: object,
    cfg: dict[str, Any],
    game_data: dict[str, Any],
    hand: str,
    hand_type: str,
) -> None:
    """推送牌局结束结果通知。"""
    if not cfg.get("zjh_notify_hand", True):
        return
    notification = _game_result_notification(game_data, hand, hand_type)
    await ctx.notify(notification)


async def _request_fold(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    hand: str,
    hand_type: str,
    choice: _Choice,
    tracker: _RoundTracker,
) -> bool:
    """请求弃牌；需要双击时延后通知，确认完成后只通知一次。"""
    result = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if not result.get("ok"):
        ctx.log.warning("弃牌请求失败: %s", result.get("error"))
        return False

    needs_confirm = bool((result.get("game") or game).get("self", {}).get("foldConfirm", False))
    if needs_confirm:
        tracker.pending_fold = _PendingFold(game.get("roundId"), hand, hand_type, choice)
        ctx.log.info("弃牌等待二次确认，通知将在确认成功后发送")
        return True

    if cfg.get("zjh_notify_hand", True):
        await ctx.notify(_fold_notification(game.get("roundId"), hand, hand_type, choice.reason, choice.decision))
    return False


async def _confirm_fold(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    tracker: _RoundTracker,
) -> bool:
    """尝试一次双击确认弃牌：成功推送弃牌通知并清空待确认状态后返回 True，失败返回 False。

    失败时保留 `tracker.pending_fold`，由调用方按重试计数决定是否继续；
    成功或放弃时才清空，避免门户持续拒绝时每轮无限重发。
    """
    result = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if not result.get("ok"):
        ctx.log.warning("确认弃牌失败: %s", result.get("error"))
        return False

    pending = tracker.pending_fold
    if cfg.get("zjh_notify_hand", True) and pending is not None:
        await ctx.notify(
            _fold_notification(
                pending.rid,
                pending.hand,
                pending.hand_type,
                pending.choice.reason,
                pending.choice.decision,
            )
        )
    if cfg.get("zjh_notify_fold_confirm", False):
        await ctx.notify("🃏 双击确认弃牌")
    tracker.pending_fold = None
    return True


async def _act_on_hand(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    hand: str,
    hand_type: str,
    fallback_threshold: float,
    tracker: _RoundTracker,
    action_override: str | None = None,
) -> bool:
    """对已看牌手牌做 EV 决策，并执行服务器允许的动作。"""
    rid = game.get("roundId")
    hand_value = _extract_hand_value(hand_type, hand)
    choice = _choose(hand_type, hand_value, game, fallback_threshold, tracker)
    _log_decision(ctx, hand, hand_type, hand_value, game, choice, tracker)

    decision = choice.decision
    actions = game.get("actions", [])

    if action_override and action_override in actions:
        action, reason = action_override, "对手发起比牌，服务端要求应战开牌"
    elif not choice.call:
        return await _request_fold(ctx, client, cfg, game, hand, hand_type, choice, tracker)
    else:
        action, reason = _choose_action(
            choice,
            actions if isinstance(actions, list) else [],
            bool(cfg.get("zjh_open_enabled", False)),
            float(cfg.get("zjh_open_max_win_rate", 50)) / 100,
            bool(cfg.get("zjh_raise_enabled", False)),
            float(cfg.get("zjh_raise_min_win_rate", 75)) / 100,
        )

    if action in {"call", "raise", "open"}:
        _record_self_threshold(game, tracker, "continue", ctx.log)
    if action_override:
        ctx.log.info(
            "应战开牌: 牌桌=%s phase=%r alive=%s isTurn=%s actions=%s",
            rid,
            game.get("phase"),
            game.get("self", {}).get("alive"),
            game.get("self", {}).get("isTurn"),
            actions,
        )
    ctx.log.info("执行动作[%s]：%s；服务端可用动作=%s", action, reason, actions)
    result = await client.post("/api/portal/zhajinhua/action", {"action": action})
    if not result.get("ok"):
        ctx.log.warning(
            "动作[%s]请求失败: %s；牌桌=%s phase=%r self=%s actions=%s",
            action,
            result.get("error"),
            rid,
            game.get("phase"),
            game.get("self", {}),
            actions,
        )
        return False
    if cfg.get("zjh_notify_hand", True) and decision is not None:
        await ctx.notify(
            _action_notification(action, rid, hand, hand_type, decision, game["pot"], game["callBet"], reason)
        )
    return False


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    interval = float(cfg.get("zjh_poll_interval", 2) or 2)
    fold_pending = False
    fold_retry = 0
    turns_taken = 0
    last_rid: Any = None
    tracker = _RoundTracker()
    round_joined = False
    last_round_hand = ""
    last_round_hand_type = ""

    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        while True:
            try:
                if not cfg.get("zjh_enabled", True):
                    await asyncio.sleep(interval)
                    continue

                # 每轮读最新配置（cookie 路径/门户地址可能被改）
                client.configure(
                    str(cfg.get("hdsky_cookie_file", "") or ""),
                    str(cfg.get("hdsky_base_url", "") or ""),
                    debug_enabled=bool(cfg.get("hdsky_debug", False)),
                    debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
                )
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
                    # 上一局结束，推送结果
                    if last_rid and round_joined:
                        await _notify_game_result(ctx, cfg, game_data, last_round_hand, last_round_hand_type)
                    last_rid = rid
                    turns_taken = 0
                    # 新一局：待确认弃牌属于上一局，连同重试计数一起重置，
                    # 避免上一局的弃牌确认泄漏到新一局产生异常 fold 动作。
                    fold_pending = False
                    fold_retry = 0
                    tracker = _RoundTracker()
                    round_joined = False
                    last_round_hand = ""
                    last_round_hand_type = ""
                s = g.get("self", {})
                # 弃牌/出局后本局不再有任何决策，停止跟踪对手快照与门槛推导。
                # 否则对手互相缠斗时门槛会递归虚高（单挑反推的不动点在 1.0，
                # 轮流下注单调收敛到 1.0），纯属无用计算还把日志刷花。
                if _in_hand(g):
                    _update_round_tracker(g, tracker, ctx.log)
                phase = g.get("phase", "")
                actions = g.get("actions", [])
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
                if fold_pending and alive and is_turn:
                    # 双击确认弃牌优先于已看牌的常规决策，避免重复发送弃牌请求/通知。
                    if fold_retry >= _FOLD_CONFIRM_MAX_RETRIES:
                        # 连续失败超限：放弃本局确认并清空状态，避免门户持续拒绝时每轮无限重发。
                        ctx.log.warning("确认弃牌连续失败 %d 次，放弃本局确认", fold_retry)
                        fold_pending = False
                        fold_retry = 0
                        tracker.pending_fold = None
                    elif await _confirm_fold(ctx, client, cfg, tracker):
                        ctx.log.info("确认弃牌成功")
                        fold_pending = False
                        fold_retry = 0
                    else:
                        fold_retry += 1

                elif joined and is_turn and isinstance(actions, list) and actions:
                    if hand:
                        # 服务端 actions 是动作授权的唯一来源；showdown 出现时优先应战。
                        action_override = _action_override(actions)
                        fold_pending = await _act_on_hand(
                            ctx,
                            client,
                            cfg,
                            g,
                            hand,
                            hand_type,
                            seen_threshold,
                            tracker,
                            action_override,
                        )
                    else:
                        # 蒙牌：无论单挑还是多人，都按 EV 决定「蒙牌半价盲跟」还是「看牌买信息」。
                        # EV≥0 时盲跟本身划算；EV<0 时看牌获取信息，随后按真实手牌正常决策。
                        blind_action, blind_choice = _blind_peek_or_call(g, actions, seen_threshold, tracker)
                        if blind_choice is not None:
                            ctx.log.info(
                                "蒙牌决策[%s]: 平均胜率=%.4f 蒙=%d 看=%d 底池=%.0f 半价成本=%.0f EV=%+.2f",
                                {"call": "盲跟", "peek": "看牌"}.get(blind_action or "", "无可执行动作"),
                                blind_choice.win_probability,
                                blind_choice.blind_opponents,
                                blind_choice.seen_opponents,
                                g.get("pot", 0),
                                _blind_call_cost(float(g.get("callBet", 0))),
                                blind_choice.expected_value,
                            )
                        if blind_action == "call":
                            await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            turns_taken += 1
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(
                                    _blind_notification(
                                        "call",
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        "蒙牌半价盲跟本身就划算（EV≥0），不看牌避免翻倍投入",
                                    )
                                )
                        elif blind_action == "peek":
                            if blind_choice is None:
                                ctx.log.info("牌局数据不完整，看牌后按实际手牌决策")
                            if cfg.get("zjh_notify_hand", True):
                                peek_reason = (
                                    "牌局数据不完整，先看牌再按实际手牌决策"
                                    if blind_choice is None
                                    else "蒙牌平均手牌不划算（EV<0），看牌买信息——牌大再上、牌小弃"
                                )
                                await ctx.notify(
                                    _blind_notification(
                                        "peek",
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        peek_reason,
                                    )
                                )
                            _record_self_threshold(g, tracker, "peek", ctx.log)
                            r = await client.post("/api/portal/zhajinhua/action", {"action": "peek"})
                            if r.get("ok"):
                                peek_game = r.get("game")
                                if isinstance(peek_game, dict):
                                    g = peek_game
                                # 看牌响应里手牌可能还没就绪：重拉状态补齐，别因读不到手牌就弃牌
                                g, hand, hand_type = await _acquire_hand_after_peek(client, g)
                                if not hand:
                                    # 仍读不到手牌：本轮不决策（绝不弃牌），等下次轮询补齐手牌再走正常决策
                                    ctx.log.warning("看牌后仍读不到手牌，本轮不决策，等下次轮询补齐")
                                else:
                                    ctx.log.info("手牌: %s (%s)", hand, hand_type)
                                    peek_actions = g.get("actions", [])
                                    action_override = _action_override(peek_actions)
                                    fold_pending = await _act_on_hand(
                                        ctx,
                                        client,
                                        cfg,
                                        g,
                                        hand,
                                        hand_type,
                                        seen_threshold,
                                        tracker,
                                        action_override,
                                    )
                        else:
                            ctx.log.warning(
                                "轮到我方但没有可执行的预期动作: 牌桌=%s phase=%r actions=%s hand=%s turns=%d",
                                rid,
                                phase,
                                actions,
                                bool(hand),
                                turns_taken,
                            )

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
