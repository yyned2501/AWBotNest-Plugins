# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：概率模型、门槛推断、轮询跟踪与决策
#
# 胜率按对手看牌状态分开计算：已看牌（手牌确定）对蒙牌对手用 t^B；蒙牌（手牌未知）
# 不能把平均胜率 0.5 当固定手牌，需对未知手牌强度积分（三人全蒙为 1/3 而非 0.5²）；
# 已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛再做条件胜率。
# 看牌后完全按增量期望收益（EV）决策：EV ≥ 0 跟注，否则弃牌（不区分单挑/多人）。

from __future__ import annotations

import math
import random
from collections.abc import Callable
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
    # 本局我方是否已做过「已看牌」决策：首次看牌慢打不加注用（每局随 tracker 重建而重置）
    seen_acted: bool = False


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
    """一个已看牌对手被建模的牌力区间 [lower, upper] 及门槛是否实测反推。

    profile/uid/action 可选：提供时用画像实测分位做胜率收缩混合与逐对手诈唬率，
    缺失则逐值回退纯范围模型（向后兼容、便于 A/B）。
    """

    lower: float
    upper: float
    observed: bool
    profile: Any = None
    uid: str | None = None
    action: str = "call"


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
    """对单个已看牌对手的胜率：范围胜率 blended 反诈唬，再与画像实测胜率收缩混合。

    1. 逐对手诈唬率：画像有该对手数据时用 `profile.bluff_rate(uid, bluff)`（其弱牌
       继续占比向全局基线收缩），否则回退全局基线 bluff。
    2. model_win = (1-bluff_opp)*范围胜率 + bluff_opp*单挑胜率 t（空气牌近似）。
    3. 画像有该对手该动作实测分位时，用 `empirical_win_factor`（我击败其实测手牌的
       比例，按样本数向 model_win 收缩）替代；无画像/无样本逐值返回 model_win。
    """
    range_win = _range_factor(hand_threshold, seen_range.lower, seen_range.upper)
    profile = seen_range.profile
    uid = seen_range.uid
    if profile is not None and uid:
        bluff_opp = profile.bluff_rate(uid, bluff)
    else:
        bluff_opp = bluff
    model_win = (1 - bluff_opp) * range_win + bluff_opp * hand_threshold
    if profile is not None and uid:
        return profile.empirical_win_factor(uid, seen_range.action, hand_threshold, model_win)
    return model_win


def _seen_opponent_ranges(
    game: dict[str, Any],
    tracker: _RoundTracker,
    fallback_threshold: float,
    range_model: _RangeModel,
    profile: Any = None,
) -> tuple[int, list[_SeenRange]]:
    """统计蒙牌对手数，并按动作类型为每个已看牌对手构造牌力区间。

    加注对手：[max(推断门槛, raise_floor), 1.0]；平跟/仅看牌：[推断门槛, call_cap]。
    门槛实测反推优先，缺失才用回退分位；observed 标记来源。
    profile 非空时，把画像引用、对手 uid 与动作类型填入 _SeenRange，并
    用画像的 raise_threshold_floor 调整加注下限、call_threshold_ceiling 调整
    平跟上界——诈唬型对手（常拿弱牌加注）下限被拉低 → 范围扩大 → 我方胜率更高。
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
        action = "raise" if is_raise else "call"
        if is_raise:
            base_floor = max(lower, range_model.raise_floor)
            if profile is not None and key:
                floor = profile.raise_threshold_floor(key, base_floor)
                if floor is not None:
                    base_floor = floor
                else:
                    # 无实测手牌分位时回退加注频率推断
                    blind_count, seen_count = _opponent_counts(game)
                    op_seen = bool(player.get("seen", False))
                    adj_seen = seen_count - (1 if op_seen else 0)
                    adj_blind = blind_count - (0 if op_seen else 1)
                    freq_floor = profile.raise_floor_from_freq_bucket(key, op_seen, adj_seen, adj_blind, base_floor)
                    if freq_floor is not None:
                        base_floor = freq_floor
            ranges.append(_SeenRange(base_floor, 1.0, observed, profile, key, action))
        else:
            base_cap = range_model.call_cap
            if profile is not None and key:
                ceiling = profile.call_threshold_ceiling(key, base_cap)
                if ceiling is not None:
                    base_cap = ceiling
            ranges.append(_SeenRange(lower, base_cap, observed, profile, key, action))
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
    profile: Any = None,
) -> _CallDecision | None:
    """按对手看牌状态及其最近正 EV 行为计算本次跟注的增量 EV。

    range_model 为空时用中性模型（平跟上限 1.0、加注下限 0.0、诈唬率 0），
    此时胜率逐值等于旧的 `_actual_win_probability`，便于回退与 A/B。
    profile 非空时接入对手画像：实测胜率收缩混合 + 逐对手诈唬率。
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
    blind, ranges = _seen_opponent_ranges(game, tracker, fallback_threshold, model, profile)
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


# ── Terminal EV 决策树（蒙牌盲跟的终局期望）──
#
# 旧 _blind_decision 用单步增量 EV：win_prob × (pot + half_cost) − half_cost，
# 隐含「跟这手就摊牌」。实际门户单挑无 open/showdown 就停不下来，对手可每轮
# raise 把 pot 滚大，而蒙牌对强牌胜率只有 (1−T)/2。单步 EV 恒正 → 盲跟到强制
# showdown 巨亏（实测 5129 局蒙牌 10-9-2 输 81000、5136 输 13 万）。
#
# Terminal EV 递归推演未来 depth 轮：对手每个分支动作概率来自画像
# （zjh_profile），条件胜率随对手门槛贝叶斯衰减，求到达终局节点（Showdown /
# 对手弃牌 / 深度截断）时的期望收益。看牌分支（peek 免费）与弃牌分支（止损）
# 一并评估，取 Terminal EV 最高的候选动作。
#
# 向后兼容：depth=1 且无画像时，盲跟分支退化为旧的单步 EV（半价成本），
# 行为与 _blind_decision 一致，便于 A/B 与回退。


@dataclass(frozen=True)
class _TerminalBranch:
    """决策树一条到终局的链路：概率、终局底池、我方总成本、终局胜率、净收益。"""

    probability: float
    pot: float
    cost: float
    win_probability: float
    net: float


@dataclass(frozen=True)
class _TerminalDecision:
    """Terminal EV 决策结果：候选动作、加权终局 EV、链路明细、单步 EV 对照。

    `expected_value` 别名指向 `terminal_ev`（最优候选的终局期望），保持与
    `_CallDecision.expected_value` 的字段形状一致，便于通知/日志复用。
    `win_probability` 返回首条链路的终端胜率（展示用）。
    """

    action: str  # "call" / "peek" / "fold"
    terminal_ev: float
    single_step_ev: float
    branches: tuple[_TerminalBranch, ...]
    reason: str

    @property
    def expected_value(self) -> float:
        """最优候选的终局期望收益（与 _CallDecision.expected_value 同语义的别名）。"""
        return self.terminal_ev

    @property
    def win_probability(self) -> float:
        """首条链路的终端胜率（展示用）。"""
        return self.branches[0].win_probability if self.branches else 0.0


def _opponent_raise_threshold(
    base_threshold: float,
    raise_count: int,
    profile: Any = None,
    opponent_uid: str | None = None,
    game: dict[str, Any] | None = None,
) -> float:
    """对手连续 raise 后其手牌门槛的上调。

    每 raise 一次，把门槛向 1.0 推一步（通用推断）。若画像记录了该对手加注后的
    真实手牌分位（结算回填），用其实测下四分位（最弱加注牌）向通用推断收缩作为
    门槛：诈唬型对手（弱牌加注多）门槛被拉低 → 我方胜率更高。profile 需为
    ProfileStore（提供 raise_threshold_floor），配合 opponent_uid 定位对手。

    无实测手牌分位时，回退加注频率推断（raise_floor_from_freq_bucket）：对手加注
    频率高 → 最小牌力低 → 胜率更高。双方都无数据则用通用推断。
    """
    threshold = base_threshold
    for _ in range(raise_count):
        threshold = threshold + (1.0 - threshold) * 0.25
    # 画像加注分位下界（duck-typed）：有数据则收缩混合，无数据回退通用推断
    if profile is not None and opponent_uid:
        floor = profile.raise_threshold_floor(opponent_uid, threshold)
        if floor is not None:
            threshold = floor
        elif game is not None:
            # 无实测手牌分位时回退加注频率推断
            blind_count, seen_count = _opponent_counts(game)
            op_seen = False
            for key, player in _opponent_entries(game):
                if key == opponent_uid:
                    op_seen = bool(player.get("seen", False))
                    break
            adj_seen = seen_count - (1 if op_seen else 0)
            adj_blind = blind_count - (0 if op_seen else 1)
            freq_floor = profile.raise_floor_from_freq_bucket(opponent_uid, op_seen, adj_seen, adj_blind, threshold)
            if freq_floor is not None:
                threshold = freq_floor
    return min(max(threshold, 0.0), 1.0)


def _blind_vs_seen_win(threshold: float) -> float:
    """我方蒙牌（牌力 t~U[0,1]）对门槛 T 已看牌对手的胜率。

    对手牌力 s~U[T,1]，我方胜率 = ∫_{t=0}^{1} P(t > s) dt = ∫_T^1 (1−s) ds / (1−T)
    = (1−T)/2。T 越高我方胜率越低，体现贝叶斯衰减。
    """
    if threshold <= 0:
        return 0.5
    if threshold >= 1:
        return 0.0
    return (1.0 - threshold) / 2


def _terminal_ev_call(
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    depth: int,
    profile: Any = None,
    action_probs: tuple[float, float, float] | None = None,
    pot: float | None = None,
    cost: float | None = None,
    win_prob: float | None = None,
    raise_count: int = 0,
    current_call_bet: float | None = None,
    opponent_seen: bool = True,
    opponent_uid: str | None = None,
) -> float:
    """递归计算「盲跟」路径到达终局的期望净收益。

    - action_probs：对手本轮 (P_fold, P_call, P_raise)，来自画像；缺省用均等先验。
    - pot/cost/win_prob：当前递归深度的累计底池、我方累计成本、条件胜率。
    - raise_count：已累计的对手加注次数，用于门槛上调。
    - current_call_bet：当前轮跟注成本。对手加注时递增（×1.5，实测单挑每轮约 +50%），
      平跟时不变；真实反映「对手持续加注把成本滚大」对蒙牌盲跟的代价。
    - opponent_seen：对手是否已看牌。只有看牌后的加注才是强牌信号（上调门槛、胜率
      贝叶斯衰减）；蒙牌加注可能是诈唬/空气牌，不上调门槛、胜率不额外衰减。
    - opponent_uid：对手画像键。看牌加注上调门槛时用它从画像取实测加注分位下界
      （诈唬型对手门槛更低），缺失则用通用推断。
    终局节点：
      对手弃牌 → 我方独赢，净收益 = pot − cost；
      深度耗尽（截断）→ 按对手动作概率对未来一轮加权（对称期望模型）；
      继续 → 递归下一轮。
    """
    if pot is None:
        pot = float(game.get("pot", 0) or 0)
    if cost is None:
        cost = 0.0
    if win_prob is None:
        win_prob = _BLIND_ONE_VS_ONE  # 未知手牌基础胜率
    if action_probs is None:
        action_probs = (1 / 3, 1 / 3, 1 / 3)
    if current_call_bet is None:
        current_call_bet = float(game.get("callBet", 0) or 0)

    p_fold, p_call, p_raise = action_probs
    if not (p_fold >= 0 and p_call >= 0 and p_raise >= 0):
        return 0.0
    total_p = p_fold + p_call + p_raise
    if total_p <= 0:
        return 0.0
    # 归一化，防御配置/画像脏数据
    p_fold, p_call, p_raise = p_fold / total_p, p_call / total_p, p_raise / total_p

    if depth <= 0:
        # 截断：按对手动作概率对未来一轮加权（与看牌分支对称的期望模型）
        #  - 对手弃牌 → 我方独赢当前底池（概率 p_fold）
        #  - 对手跟/加 → 我方蒙牌半价继续一轮，按当前胜率赢 pot − 累计成本
        # 不再假设「对手必持续 raise 到强制 showdown」（那是最坏情形，不是期望，
        # 会把盲跟 EV 系统性压成负，导致 bot 永远弃/看而不盲跟）。
        ev = 0.0
        if p_fold > 0:
            ev += p_fold * (pot - cost)
        if p_call + p_raise > 0:
            next_cost = cost + _blind_call_cost(current_call_bet)
            next_pot = pot + current_call_bet
            ev += (p_call + p_raise) * (win_prob * next_pot - next_cost)
        return ev

    ev = 0.0
    # 对手弃牌 → 我独赢当前底池
    if p_fold > 0:
        ev += p_fold * (pot - cost)

    # 对手平跟 → callBet 不变，下一轮我方继续盲跟（半价）。
    if p_call > 0:
        next_cost = cost + _blind_call_cost(current_call_bet)
        next_pot = pot + current_call_bet
        ev += p_call * _terminal_ev_call(
            game,
            fallback_threshold,
            tracker,
            depth - 1,
            profile,
            action_probs,
            next_pot,
            next_cost,
            win_prob,
            raise_count,
            current_call_bet,
            opponent_seen,
            opponent_uid,
        )

    # 对手加注 → callBet 递增。看牌后加注是强牌信号：门槛上调、胜率贝叶斯衰减；
    # 蒙牌加注视为诈唬/空气：不上调门槛，胜率维持（只承担 callBet 滚大的代价）。
    if p_raise > 0:
        if opponent_seen:
            new_threshold = _opponent_raise_threshold(fallback_threshold, raise_count + 1, profile, opponent_uid, game)
            new_win = _blind_vs_seen_win(new_threshold)
        else:
            new_win = win_prob
        raised_bet = current_call_bet * 1.5
        next_cost = cost + _blind_call_cost(raised_bet)
        next_pot = pot + raised_bet
        ev += p_raise * _terminal_ev_call(
            game,
            fallback_threshold,
            tracker,
            depth - 1,
            profile,
            action_probs,
            next_pot,
            next_cost,
            new_win,
            raise_count + 1,
            raised_bet,
            opponent_seen,
            opponent_uid,
        )
    return ev


def _terminal_ev_peek(
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    depth: int,
    profile: Any = None,
    action_probs: tuple[float, float, float] | None = None,
) -> float:
    """看牌分支的终局期望：peek 免费，看牌后信息充分再决策。

    看牌后我方手牌 t~U[0,1]，对手门槛 T：
      - 我方 t < T（弱牌）→ 弃牌，增量成本 0，概率 = T；
      - 我方 t ≥ T（强牌）→ 看牌后全价跟注，与对手摊牌，
        条件胜率 `_blind_vs_seen_win(T) = (1−T)/2`（我方 t≥T 对对手 s∈[T,1]
        的期望胜率），需付看牌后跟注成本 call_bet。
    与盲跟分支对称：强牌分支内同样按对手动作概率（action_probs）对未来轮次
    加权，对手弃牌时白赢当前底池，对手跟/加时进入下一轮继续推演。
    避免旧实现的乐观高估（把 threshold 当弱牌概率、假设必摊牌不扣对手加注成本）。
    """
    threshold = fallback_threshold if 0 <= fallback_threshold < 1 else 0.5
    if action_probs is None:
        action_probs = (1 / 3, 1 / 3, 1 / 3)
    p_fold, p_call, p_raise = action_probs
    total_p = p_fold + p_call + p_raise
    if total_p <= 0:
        return 0.0
    p_fold, p_call, p_raise = p_fold / total_p, p_call / total_p, p_raise / total_p

    pot = float(game.get("pot", 0) or 0)
    call_bet = float(game.get("callBet", 0) or 0)

    # 弱牌（t<T）弃牌：净收益 0
    weak_prob = threshold
    # 强牌（t≥T）概率
    strong_prob = 1.0 - threshold
    # 强牌条件胜率：我方 t≥T 对对手 s∈[T,1] 的期望胜率
    strong_win = _blind_vs_seen_win(threshold)

    # 强牌分支内部：按对手动作概率加权未来一轮
    #  - 对手弃牌：白赢当前底池（无需再投入）
    #  - 对手跟/加：我方全价跟注 call_bet 后摊牌，赢底池
    branch_ev = 0.0
    if p_fold > 0:
        branch_ev += p_fold * pot
    if p_call + p_raise > 0:
        # 强牌 vs 对手范围，条件胜率；赢 pot+call，扣我方全价跟注成本
        branch_ev += (p_call + p_raise) * (strong_win * (pot + call_bet) - call_bet)

    return weak_prob * 0 + strong_prob * branch_ev


def _terminal_ev_decision(
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    depth: int = 2,
    profile: Any = None,
    action_probs: tuple[float, float, float] | None = None,
    opponent_uid: str | None = None,
) -> _TerminalDecision:
    """蒙牌「盲跟 / 看牌 / 弃牌」三候选的 Terminal EV，取最优。

    - 盲跟：决策树递归推演 depth 轮，对手动作概率来自 action_probs（画像查询）。
    - 看牌：peek 免费，弱牌止损 + 强牌开牌。
    - 弃牌：立即止损，净收益 0。
    profile 用于对手连续 raise 时的门槛上调（画像加注牌力分位）。
    action_probs 为 (P_fold, P_call, P_raise)，来自对手画像；缺省用均等先验。
    depth=1 且无画像时，盲跟分支退化为旧单步 EV（半价成本），便于回退。
    """
    pot = float(game.get("pot", 0) or 0)
    call_bet = float(game.get("callBet", 0) or 0)

    # 蒙牌精确积分胜率：按对手蒙/看状态（含门槛）计算，已看牌强对手会自然衰减。
    # 作为盲跟决策树的初始胜率，保证截断/递归对强对手场景反映门槛衰减。
    seen_threshold_list = _seen_opponent_thresholds(game, tracker, fallback_threshold)[1]
    blind_win_rate = _blind_win_probability(
        _opponent_counts(game)[0],
        tuple(th for th, _ in seen_threshold_list),
    )
    # 对手是否已看牌：有任一已看牌对手即视为看牌对手建模（其加注才是强牌信号）。
    opponent_seen = len(seen_threshold_list) >= 1
    # 盲跟候选
    call_ev = _terminal_ev_call(
        game,
        fallback_threshold,
        tracker,
        depth,
        profile,
        action_probs,
        None,
        None,
        blind_win_rate,
        0,
        None,
        opponent_seen,
        opponent_uid,
    )
    # 看牌候选
    peek_ev = _terminal_ev_peek(game, fallback_threshold, tracker, depth, profile, action_probs)
    # 弃牌候选
    fold_ev = 0.0

    # 单步 EV 对照（旧行为，深度 1、无画像）：蒙牌精确积分胜率 × 半价成本
    single_step_ev = blind_win_rate * (pot + _blind_call_cost(call_bet)) - _blind_call_cost(call_bet)

    branches: list[_TerminalBranch] = []
    # 首条链路代表盲跟主路径（胜率用当前蒙牌精确积分胜率，便于与旧模型对照）
    branches.append(_TerminalBranch(1.0, pot, _blind_call_cost(call_bet), blind_win_rate, call_ev))

    if call_ev >= peek_ev and call_ev >= fold_ev:
        action = "call"
        reason = f"蒙牌盲跟 Terminal EV {call_ev:+.0f} ≥ 看牌 {peek_ev:+.0f} / 弃牌 0"
    elif peek_ev >= fold_ev:
        action = "peek"
        reason = f"蒙牌看牌 Terminal EV {peek_ev:+.0f} > 盲跟 {call_ev:+.0f} / 弃牌 0，弱牌止损"
    else:
        action = "fold"
        reason = f"蒙牌弃牌 Terminal EV 0 ≥ 盲跟 {call_ev:+.0f} / 看牌 {peek_ev:+.0f}"
    return _TerminalDecision(action, max(call_ev, peek_ev, fold_ev), single_step_ev, tuple(branches), reason)


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
    game: dict[str, Any],
    actions: list[Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    profile: Any = None,
    depth: int = 2,
    max_blind_calls: int = 0,
    blind_calls_so_far: int = 0,
    action_probs: tuple[float, float, float] | None = None,
    opponent_uid: str | None = None,
) -> tuple[str | None, _TerminalDecision | _CallDecision | None]:
    """多人蒙牌时按 Terminal EV 决定「盲跟」「看牌」「弃牌」或直接比牌。

    用 Terminal EV 决策树评估盲跟/看牌/弃牌三候选：
    - 盲跟最优且 EV≥0 → 先看门户是否开放 showdown/open 可直接结束本轮
      （避免盲跟后对手加注导致后续投入翻倍）；都不开放才盲跟。
    - 看牌最优，或连续盲跟次数达到上限（max_blind_calls）→ 看牌买信息。
    - 弃牌最优 → 弃牌。
    action_probs 为对手本轮 (P_fold, P_call, P_raise)（画像查询），透传给决策树。
    门户不给看牌才退回盲跟保底；两者都不给返回 None。

    兼容旧行为：depth=1 且 profile=None 时等价旧 _blind_peek_or_call
    （纯单步 EV 决策蒙还是看）。
    """
    blind_choice = _blind_decision(game, fallback_threshold, tracker)
    terminal = _terminal_ev_decision(game, fallback_threshold, tracker, depth, profile, action_probs, opponent_uid)

    # 1. 连续盲跟达上限 → 强制看牌（避免「蒙牌闭眼跟」被对手 raise 套牢）
    if max_blind_calls > 0 and blind_calls_so_far >= max_blind_calls:
        if "peek" in actions:
            return "peek", terminal
        if "showdown" in actions:
            return "showdown", terminal
        if "open" in actions:
            return "open", terminal
        if "call" in actions:
            return "call", terminal
        return None, terminal

    # 2. Terminal EV 判定盲跟最优且 EV 非负 → 盲跟
    if terminal.action == "call" and terminal.terminal_ev >= 0:
        # 盲跟 EV≥0：优先用 showdown/open 结束本轮，避免盲跟后对手加注导致投入翻倍
        if "showdown" in actions:
            return "showdown", terminal
        if "open" in actions:
            return "open", terminal
        if "call" in actions:
            return "call", terminal
        if "peek" in actions:
            return "peek", terminal
        return None, terminal

    # 3. Terminal EV 判定看牌最优 → 看牌
    if terminal.action == "peek":
        if "peek" in actions:
            return "peek", terminal
        if "call" in actions:
            return "call", terminal
        return None, terminal

    # 4. Terminal EV 判定弃牌最优 → 弃牌
    if terminal.action == "fold":
        if "fold" in actions:
            return "fold", terminal
        if "peek" in actions:
            return "peek", terminal
        if "call" in actions:
            return "call", terminal
        return None, terminal

    # 5. 兜底（异常路径）：沿用旧单步 EV 决策
    if blind_choice is not None and blind_choice.expected_value >= 0:
        if "showdown" in actions:
            return "showdown", blind_choice
        if "open" in actions:
            return "open", blind_choice
        if "call" in actions:
            return "call", blind_choice
    if "peek" in actions:
        return "peek", blind_choice
    if "call" in actions:
        return "call", blind_choice
    return None, blind_choice


def _blind_peek_reason(blind_choice: _TerminalDecision | _CallDecision | None, actions: list[Any]) -> str:
    """蒙牌选择看牌时的通知原因，按真实情形区分，避免把「门户不给盲跟」误报成「EV<0」。

    看牌由 `_blind_peek_or_call` 在几种情形返回：① Terminal EV 判定看牌最优（弱牌止损）；
    ② 连续盲跟达上限强制看牌；③ 盲跟 EV≥0 但服务端 actions 没有盲跟 call（只有 peek），
    被迫看牌；④ 数据不完整。文案须分开，不能一概说「EV<0」。
    """
    if blind_choice is None:
        return "牌局数据不完整，先看牌再按实际手牌决策"
    # Terminal EV 决策返回（新增）
    if isinstance(blind_choice, _TerminalDecision):
        if blind_choice.action == "peek":
            return "蒙牌 Terminal EV 看牌最优：弱牌止损、强牌再上，避免盲跟被对手加注套牢"
        if blind_choice.action == "fold":
            return "蒙牌 Terminal EV 弃牌最优：继续盲跟终局期望为负"
        return "看牌买信息——牌大再上、牌小弃"
    # 旧单步 EV 决策返回（兜底）
    if blind_choice.expected_value < 0:
        return "蒙牌平均手牌不划算（EV<0），看牌买信息——牌大再上、牌小弃"
    if "call" not in actions:
        return "蒙牌盲跟本身划算（EV≥0）但门户本轮未开放盲跟动作，只能先看牌、按实际手牌再决策"
    return "看牌买信息——牌大再上、牌小弃"


def _choose(
    hand_type: str,
    hand_value: int | tuple[int, ...] | None,
    game: dict[str, Any],
    fallback_threshold: float,
    tracker: _RoundTracker,
    range_model: _RangeModel | None = None,
    fold_ev_tolerance_pct: float = 0.0,
    profile: Any = None,
) -> _Choice:
    """纯 EV 决策：跟注当且仅当数据有效且增量期望收益不低于弃牌容差。

    fold_ev_tolerance_pct：弃牌容差（callBet 的百分比）。EV 只是略负（≥ −容差）时
    不弃牌——边际负 EV 在胜率估算噪声内，且弃牌白白让出已投入底池权益。默认 0
    保持旧行为；配置 zjh_fold_ev_tolerance 打开（推荐 5，即 −5%×callBet 内不弃）。
    profile：对手画像（ProfileStore），非空时已看牌胜率接入实测收缩混合 + 逐对手诈唬率。
    """
    decision = _call_decision(hand_type, hand_value, game, fallback_threshold, tracker, range_model, profile)
    if decision is None:
        return _Choice(False, "牌局数据不完整，保守弃牌", None)
    call_bet = float(game.get("callBet", 0) or 0)
    tolerance = abs(fold_ev_tolerance_pct) / 100.0 * call_bet
    if decision.expected_value < -tolerance:
        return _Choice(False, f"跟注期望收益{decision.expected_value:+.0f}低于弃牌容差{-tolerance:.0f}", decision)
    return _Choice(True, "期望收益在弃牌容差内", decision)


def _action_override(actions: list[Any]) -> str | None:
    """已废弃：门户并无「服务端强制应战开牌」规则，showdown 仅是普通授权动作。

    保留签名以兼容旧调用点，恒返回 None——应战与否改由 _choose_action 按 EV 决策：
    EV 支持继续且无 call 授权（强制摊牌阶段）时才选 showdown/raise，否则该弃就弃。
    """
    return None


def _choose_action(
    choice: _Choice,
    actions: list[Any],
    open_enabled: bool,
    open_threshold: float,
    raise_enabled: bool,
    raise_threshold: float,
    raise_frequency: float = 1.0,
    first_peek_no_raise: bool = False,
    rng: Callable[[], float] = random.random,
) -> tuple[str, str]:
    """按最终实际胜率选择跟注、主动开牌、追加或应战摊牌，动作必须获服务端允许。

    强制摊牌阶段 actions 只有 fold/raise/showdown（无 call/open）：EV 支持继续时，
    showdown 作为「继续」动作（相当于全价跟注到摊牌）；胜率达标且允许则 raise。

    raise_frequency：胜率达标时的加注概率（0~1，默认 1.0 即达标必加）。大牌不必加、
    以概率 raise_frequency 加注、其余时候慢打平跟，做混合策略伪装——避免「bot 加注=怪兽」
    被对手摸透后弃牌，导致大牌只赢小底池。rng 供测试注入确定性随机源。

    first_peek_no_raise：本局首次看牌决策（tracker.seen_acted 为 False 时由 _act_on_hand
    传入 True）即使胜率达标也不加注，平跟慢打留人——第一次看牌就加注会把对手吓跑，
    后续轮次（seen_acted 为 True）再按 raise_frequency 加注。无 call 授权（强制摊牌）时
    不拦截，落入 showdown 继续。
    """
    decision = choice.decision
    if not choice.call or decision is None:
        return "fold", choice.reason
    win_probability = decision.win_probability
    if open_enabled and "open" in actions and win_probability < open_threshold:
        return "open", f"最终实际胜率{win_probability:.1%}低于主动开牌阈值{open_threshold:.1%}"
    if raise_enabled and "raise" in actions and win_probability >= raise_threshold:
        if first_peek_no_raise and "call" in actions:
            # 本局第一次看牌：大牌慢打平跟留人，不加注（加注会吓退对手，只赢小底池）
            return "call", (
                f"第一次看牌慢打：胜率{win_probability:.1%}虽达追加阈值{raise_threshold:.1%}，首次看牌不加注留人"
            )
        if raise_frequency >= 1.0 or rng() < raise_frequency:
            return (
                "raise",
                f"最终实际胜率{win_probability:.1%}达到追加阈值{raise_threshold:.1%}（加注频率{raise_frequency:.0%}）",
            )
        # 达标但本次随机慢打：伪装大牌不加注，落入跟注/应战（混合策略防针对）
    if "call" in actions:
        return "call", choice.reason
    if "showdown" in actions:
        return "showdown", f"强制摊牌阶段无 call 授权，EV 支持继续，应战开牌（胜率{win_probability:.1%}）"
    return "call", choice.reason
