# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：概率模型、门槛推断、轮询跟踪与决策
#
# 胜率按对手看牌状态分开计算：已看牌（手牌确定）对蒙牌对手用 t^B；蒙牌（手牌未知）
# 不能把平均胜率 0.5 当固定手牌，需对未知手牌强度积分（三人全蒙为 1/3 而非 0.5²）；
# 已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛再做条件胜率。
# 看牌后完全按增量期望收益（EV）决策：EV ≥ 0 跟注，否则弃牌（不区分单挑/多人）。

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from .zjh_prob import win_prob_1v1
from .zjh_state import (
    _is_alive,
    _is_self,
    _opponent_counts,
    _opponent_entries,
    _player_key,
    _player_state,
    _players,
    _PlayerState,
    _self_key,
)

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
    is_raise: bool = False


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
    """一次跟注的概率和增量期望收益。

    `seen_thresholds` 每项为 `(下界, 上界, 是否实测)`：已看牌对手被建模为牌力
     uniform[下界, 上界]。中性配置（上界 1.0、无诈唬）时等价旧的单门槛模型。
    """

    one_vs_one: float
    blind_opponents: int
    seen_opponents: int
    seen_thresholds: tuple[tuple[float, float, bool], ...]
    win_probability: float
    expected_value: float


@dataclass(frozen=True)
class _Choice:
    """纯 EV 决策结果：是否跟注、原因与概率明细。"""

    call: bool
    reason: str
    decision: _CallDecision | None


@dataclass(frozen=True)
class _SeenRange:
    """一个已看牌对手被建模的牌力区间 [lower, upper] 及门槛是否实测反推。"""

    lower: float
    upper: float
    observed: bool


@dataclass(frozen=True)
class _RangeModel:
    """范围上限 + 反诈唬基线的可调参数（均为 0~1 分数）。

    - call_cap：平跟/仅看牌对手牌力上界（扣除顶级强牌慢打概率），下界为推断门槛。
    - raise_floor：加注对手牌力下界（加注信号至少这么强），上界恒为 1.0。
    - bluff：任一跟注被视为纯空气牌诈唬的概率，避免把对手范围锁太死而吃诈唬亏。

    中性配置 `(1.0, 0.0, 0.0)` 精确还原旧的单门槛均匀分布模型（v1.12.0 行为）。
    """

    call_cap: float = 1.0
    raise_floor: float = 0.0
    bluff: float = 0.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> _RangeModel:
        """从插件配置（百分比）解析；非法/缺失值回退中性（关闭）。"""
        return cls(
            call_cap=float(cfg.get("zjh_call_range_cap", 100)) / 100,
            raise_floor=float(cfg.get("zjh_raise_range_floor", 0)) / 100,
            bluff=float(cfg.get("zjh_bluff_rate", 0)) / 100,
        )


# 中性范围模型：上界 1.0、无加注下限、无诈唬 —— 逐值等价旧的 _actual_win_probability。
_NEUTRAL_RANGE_MODEL = _RangeModel()


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


def _is_raise_action(last_action: str) -> bool:
    """判断公开动作文本是否为加注（区别于平跟）：含「加」或 raise。"""
    action = last_action.lower()
    return "加" in action or "raise" in action


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
                        tracker.snapshots[key] = replace(snapshot, is_raise=_is_raise_action(current.last_action))
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


def _range_factor(hand_threshold: float, lower: float, upper: float) -> float:
    """我方牌力 t 击败一个 uniform[lower, upper] 对手的条件胜率。

    上界 1.0 时退化为旧的 `(t - lower)/(1 - lower)`；区间退化（upper ≤ lower，
    如推断门槛已高于封顶）回落 upper=1.0，保证健壮且与旧行为一致。
    """
    if upper <= lower:
        upper = 1.0
    if hand_threshold <= lower:
        return 0.0
    if hand_threshold >= upper:
        return 1.0
    return (hand_threshold - lower) / (upper - lower)


def _seen_factor(hand_threshold: float, seen_range: _SeenRange, bluff: float) -> float:
    """对单个已看牌对手的胜率：范围胜率 blended 反诈唬基线。

    以概率 bluff 视对手为纯空气牌（随机弱牌，我方胜率≈单挑胜率 t），
    其余概率按 uniform[lower, upper] 范围计算。bluff=0 时即纯范围胜率。
    """
    range_win = _range_factor(hand_threshold, seen_range.lower, seen_range.upper)
    return (1 - bluff) * range_win + bluff * hand_threshold


def _seen_opponent_ranges(
    game: dict[str, Any], tracker: _RoundTracker, fallback_threshold: float, range_model: _RangeModel
) -> tuple[int, list[_SeenRange]]:
    """统计蒙牌对手数，并按动作类型为每个已看牌对手构造牌力区间。

    加注对手：[max(推断门槛, raise_floor), 1.0]；平跟/仅看牌：[推断门槛, call_cap]。
    门槛实测反推优先，缺失才用回退分位；observed 标记来源。
    """
    blind, _ = _opponent_counts(game)
    ranges: list[_SeenRange] = []
    for key, player in _opponent_entries(game):
        if not player.get("seen", False):
            continue
        threshold = _combined_opponent_threshold(tracker.peek_snapshots.get(key), tracker.snapshots.get(key))
        observed = threshold is not None
        lower = threshold if threshold is not None else fallback_threshold
        continue_snapshot = tracker.snapshots.get(key)
        is_raise = bool(continue_snapshot.is_raise) if continue_snapshot is not None else False
        if is_raise:
            ranges.append(_SeenRange(max(lower, range_model.raise_floor), 1.0, observed))
        else:
            ranges.append(_SeenRange(lower, range_model.call_cap, observed))
    return blind, ranges


def _ranged_win_probability(
    hand_threshold: float, blind_opponents: int, seen_ranges: list[_SeenRange], bluff: float
) -> float:
    """带范围上限与反诈唬基线的实际胜率：蒙牌对手 t^B，已看牌对手连乘各自 seen_factor。"""
    if not 0 < hand_threshold <= 1 or blind_opponents < 0:
        return 0.0
    probability = hand_threshold**blind_opponents
    for seen_range in seen_ranges:
        probability *= _seen_factor(hand_threshold, seen_range, bluff)
    return probability


def _call_decision(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    range_model: _RangeModel | None = None,
) -> _CallDecision | None:
    """按对手看牌状态及其最近正 EV 行为计算本次跟注的增量 EV。

    range_model 为空时用中性模型（平跟上限 1.0、加注下限 0.0、诈唬率 0），
    此时胜率逐值等于旧的 `_actual_win_probability`，便于回退与 A/B。
    """
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

    model = range_model if range_model is not None else _NEUTRAL_RANGE_MODEL
    blind, ranges = _seen_opponent_ranges(game, tracker, fallback_threshold, model)
    seen = len(ranges)

    win_probability = _ranged_win_probability(one_vs_one, blind, ranges, model.bluff)

    expected_value = win_probability * (pot + call_bet) - call_bet
    seen_thresholds = tuple((rng.lower, rng.upper, rng.observed) for rng in ranges)
    return _CallDecision(one_vs_one, blind, seen, seen_thresholds, win_probability, expected_value)


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
    # 蒙牌胜率仍走精确积分（范围/诈唬只作用于已看牌真金决策），门槛上界记 1.0 保持字段形状一致
    seen_threshold_ranges = tuple((threshold, 1.0, observed) for threshold, observed in seen_thresholds)
    return _CallDecision(_BLIND_ONE_VS_ONE, blind, seen, seen_threshold_ranges, win_probability, expected_value)


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
    range_model: _RangeModel | None = None,
) -> _Choice:
    """纯 EV 决策：跟注当且仅当数据有效且增量期望收益非负。"""
    decision = _call_decision(hand_type, hand_value, game, fallback_threshold, tracker, range_model)
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
