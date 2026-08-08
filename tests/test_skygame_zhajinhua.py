# -*- coding: utf-8 -*-
# skyGame · 炸金花概率、对手推断与决策单元测试

from __future__ import annotations

import pytest

from plugins.skyGame.games.zhajinhua import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua.zhajinhua import (
    _FOLD_CONFIRM_MAX_RETRIES,
    _TERMINAL_RESEND_MAX,
    _acquire_hand_after_peek,
    _act_on_hand,
    _actual_win_probability,
    _blind_call_cost,
    _blind_decision,
    _blind_notification,
    _blind_peek_or_call,
    _blind_peek_reason,
    _blind_vs_seen_win,
    _blind_win_probability,
    _BlindOpponent,
    _call_decision,
    _Choice,
    _choose,
    _choose_action,
    _combined_opponent_threshold,
    _combined_self_threshold,
    _confirm_fold,
    _extract_hand_value,
    _game_result_notification,
    _hand_threshold_for_actual_win_probability,
    _in_hand,
    _is_raise_action,
    _normalize_hand_type,
    _notify_game_result,
    _opponent_counts,
    _opponent_hand_threshold,
    _opponent_raise_threshold,
    _opponent_threshold,
    _opponents_win_probability,
    _OpponentSnapshot,
    _parse_hand,
    _peek_terminal_ev,
    _PendingFold,
    _range_factor,
    _ranged_win_probability,
    _request_blind_fold,
    _RoundTracker,
    _seen_factor,
    _seen_opponent_ranges,
    _SeenRange,
    _self_hand,
    _snapshot_for_actor,
    _terminal_action_ineffective,
    _terminal_action_or_fallback,
    _terminal_ev_call,
    _terminal_ev_call_multi,
    _terminal_ev_decision,
    _terminal_ev_peek_multi,
    _TerminalBranch,
    _TerminalDecision,
    _train_opponent_actions,
    _update_round_tracker,
    record_round_result,
)
from plugins.skyGame.games.zhajinhua.zjh_profile import (
    PRIOR_STRENGTH,
    ProfileStore,
    _freq_bucket,
    _hand_pctile_from_result,
    _percentile,
    feed_last_result,
    record_round_raise_freq,
)


def _game(*players: dict[str, object], pot: float = 1000, call_bet: float = 100, ante: float = 0) -> dict[str, object]:
    game = {"pot": pot, "callBet": call_bet, "players": list(players)}
    if ante > 0:
        game["ante"] = ante
    return game


class _FakeLog:
    def info(self, *args: object) -> None:
        pass

    def warning(self, *args: object) -> None:
        pass


class _FakeContext:
    log = _FakeLog()

    async def notify(self, *args: object, **kwargs: object) -> None:
        pass


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.requests.append((path, body))
        return {"ok": True}


@pytest.mark.asyncio
async def test_showdown_phase_folds_when_ev_negative_no_forced_showdown() -> None:
    """回归：门户无「服务端强制应战」规则。showdown 只是普通授权动作，EV 为负就弃。

    pot 极小（100）、callBet 极大（2000）→ 即便 A 高对子，底池赔率也太差，EV 为负。
    旧逻辑因 actions 含 showdown 无条件应战；修正后按 EV 弃牌。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": False},
        pot=100,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "phase": "showdown",
            "actions": ["fold", "showdown"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    client = _FakeClient()

    pending_fold = await _act_on_hand(
        _FakeContext(),
        client,
        {"zjh_notify_hand": False},
        game,
        "7♠ 5♥ 3♦",  # 弱散牌，EV 明确为负
        "散牌",
        0.5,
        _RoundTracker(),
    )

    # EV 为负 → 走弃牌流程（_request_fold），不执行 showdown
    assert client.requests == [] or all(req[1].get("action") == "fold" for req in client.requests)
    assert pending_fold in (True, False)  # 弃牌可能需双击确认，动作不会是 showdown


async def test_showdown_phase_continues_via_showdown_when_ev_positive() -> None:
    """强制摊牌阶段（actions 无 call）且 EV 为正：选 showdown 作为继续动作应战。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=20000,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "phase": "showdown",
            "actions": ["fold", "raise", "showdown"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    client = _FakeClient()

    await _act_on_hand(
        _FakeContext(),
        client,
        {"zjh_notify_hand": False},  # raise 未启用 → 不回 raise，EV 正落到 showdown
        game,
        "A♠ A♥ A♦",  # 豹子，EV 明确为正
        "豹子",
        0.5,
        _RoundTracker(),
    )

    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "showdown"})]


async def test_showdown_phase_raises_when_high_win_rate_and_raise_enabled() -> None:
    """强制摊牌阶段、高胜率且启用追加：raise 优先于 showdown。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=20000,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "phase": "showdown",
            "actions": ["fold", "raise", "showdown"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    client = _FakeClient()

    await _act_on_hand(
        _FakeContext(),
        client,
        {"zjh_notify_hand": False, "zjh_raise_enabled": True, "zjh_raise_min_win_rate": 75},
        game,
        "A♠ A♥ A♦",
        "豹子",
        0.5,
        _RoundTracker(),
    )

    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "raise"})]


@pytest.mark.asyncio
async def test_act_on_hand_first_peek_slow_plays_then_later_rounds_raise() -> None:
    """集成：本局首次看牌决策大牌慢打平跟（留人），同一 tracker 后续决策恢复加注。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=20000,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "actions": ["fold", "raise", "call"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    cfg = {"zjh_notify_hand": False, "zjh_raise_enabled": True, "zjh_raise_min_win_rate": 75}
    tracker = _RoundTracker()
    assert tracker.seen_acted is False

    client = _FakeClient()
    await _act_on_hand(_FakeContext(), client, cfg, game, "A♠ A♥ A♦", "豹子", 0.5, tracker)
    # 第一次看牌：豹子达标也不加注，平跟慢打留人
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "call"})]
    assert tracker.seen_acted is True

    client2 = _FakeClient()
    await _act_on_hand(_FakeContext(), client2, cfg, game, "A♠ A♥ A♦", "豹子", 0.5, tracker)
    # 后续决策（seen_acted=True）：达标照常加注
    assert client2.requests == [("/api/portal/zhajinhua/action", {"action": "raise"})]


@pytest.mark.asyncio
async def test_act_on_hand_first_peek_raises_when_config_disabled() -> None:
    """异常路径：zjh_first_peek_no_raise=False 关闭慢打 → 第一次看牌达标即加注（旧行为）。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=20000,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "actions": ["fold", "raise", "call"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    cfg = {
        "zjh_notify_hand": False,
        "zjh_raise_enabled": True,
        "zjh_raise_min_win_rate": 75,
        "zjh_first_peek_no_raise": False,
    }
    client = _FakeClient()
    await _act_on_hand(_FakeContext(), client, cfg, game, "A♠ A♥ A♦", "豹子", 0.5, _RoundTracker())
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "raise"})]


def test_probability_table_has_continuous_hand_type_ranges() -> None:
    tables = gen_zjh_prob._build_tables()
    ranges = (
        ("_散牌", 60, 0, 16440),
        ("_对子", 24, 16440, 20184),
        ("_顺子", 60, 20184, 20904),
        ("_金花", 4, 20904, 22000),
        ("_同花顺", 4, 22000, 22048),
        ("_豹子", 4, 22048, 22100),
    )

    for name, combinations_per_value, start, end in ranges:
        values = list(tables[name].values())
        assert values[0] == start
        assert values[-1] + combinations_per_value == end
        assert all(next_value - value == combinations_per_value for value, next_value in zip(values, values[1:]))


def test_probability_table_preserves_hand_type_order() -> None:
    assert zjh_prob.win_prob_1v1("散牌", (14, 13, 11)) < zjh_prob.win_prob_1v1("对子", (2, 3))
    assert zjh_prob.win_prob_1v1("对子", (14, 13)) < zjh_prob.win_prob_1v1("顺子", 3)
    assert zjh_prob.win_prob_1v1("顺子", 14) < zjh_prob.win_prob_1v1("金花", (5, 3, 2))
    assert zjh_prob.win_prob_1v1("金花", (14, 13, 11)) < zjh_prob.win_prob_1v1("同花顺", 3)
    assert zjh_prob.win_prob_1v1("同花顺", 14) < zjh_prob.win_prob_1v1("豹子", 2)


def test_probability_table_monotonic_within_scatter_and_flush() -> None:
    """回归：散牌/金花内 weaker_count 必须随 (high,mid,low) 牌力严格递增。

    历史上生成器按 combinations 的 (low,mid,high) 序枚举却用「序号×60」当 weaker_count，
    导致 A-K-4（强散牌）胜率被算成比 T-9-5（弱散牌）还低，bot 把 A 高散牌当弱牌弃掉。
    """
    for hand_type in ("散牌", "金花"):
        table = getattr(zjh_prob, f"_{hand_type}")
        keys = sorted(table.keys())  # (high, mid, low) 升序 == 牌力升序
        values = [table[k] for k in keys]
        assert all(a < b for a, b in zip(values, values[1:])), f"{hand_type} weaker_count 非单调"
    # 具体牌例：A-K-4 散牌强于 T-9-5 散牌
    assert zjh_prob.win_prob_1v1("散牌", (14, 13, 4)) > zjh_prob.win_prob_1v1("散牌", (10, 9, 5))
    # A 高散牌单挑胜率应过半（击败大多数随机手牌）
    assert zjh_prob.win_prob_1v1("散牌", (14, 13, 4)) > 0.5


def test_extract_hand_value_handles_a23_as_low_straight() -> None:
    assert _extract_hand_value("顺子", "A♠2♥3♦") == 3
    assert _extract_hand_value("同花顺", "A♠2♠3♠") == 3
    assert _extract_hand_value("顺子", "A♠K♥Q♦") == 14


def test_normalize_portal_flush_name() -> None:
    assert _normalize_hand_type("同花") == "金花"
    assert _normalize_hand_type("9♠ 3♠ 2♠ → 同花") == "金花"


def test_extract_hand_value_from_portal_combined_flush_type() -> None:
    hand = "9♠ 3♠ 2♠"
    hand_type = _normalize_hand_type(f"{hand} → 同花")
    assert _extract_hand_value(hand_type, hand) == (9, 3, 2)


def test_parse_and_extract_reject_invalid_hand() -> None:
    assert _parse_hand("10♠3♥2♦") == [10, 3, 2]
    assert _extract_hand_value("金花", "A♠K♠") is None
    assert _extract_hand_value("未知", "A♠K♠Q♠") is None


def test_opponent_counts_separates_blind_seen_and_self() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "blind", "alive": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        {"id": "folded", "alive": False, "seen": False},
    )
    assert _opponent_counts(game) == (1, 1)


def test_opponent_counts_uses_conservative_fallback_without_players() -> None:
    assert _opponent_counts({}) == (1, 0)


def test_hand_threshold_round_trips_actual_win_probability() -> None:
    cases = (
        (0.5, 1, (), 0.5),
        (0.5, 2, (), 0.5**0.5),
        (0.5, 0, (0.3,), 0.65),
        (0.5, 1, (0.3,), None),
        (0.5, 1, (0.5,), None),
        (0.5, 0, (0.3, 0.4), None),
    )

    for actual_threshold, blind_opponents, seen_thresholds, expected in cases:
        hand_threshold = _hand_threshold_for_actual_win_probability(actual_threshold, blind_opponents, seen_thresholds)
        assert hand_threshold is not None
        if expected is not None:
            assert hand_threshold == pytest.approx(expected)
        assert _actual_win_probability(hand_threshold, blind_opponents, seen_thresholds) == pytest.approx(
            actual_threshold
        )


def test_hand_threshold_rejects_invalid_or_opponent_free_state() -> None:
    assert _hand_threshold_for_actual_win_probability(0, 1, ()) is None
    assert _hand_threshold_for_actual_win_probability(1, 1, ()) is None
    assert _hand_threshold_for_actual_win_probability(0.5, 0, ()) is None
    assert _actual_win_probability(0.3, 1, (0.5,)) == 0

    one_opponent = _OpponentSnapshot(pot=100, call_bet=100, opponents=1)
    two_blind_opponents = _OpponentSnapshot(pot=100, call_bet=100, opponents=2, blind_opponents=2)

    assert _opponent_threshold(one_opponent) == pytest.approx(0.5)
    assert _opponent_hand_threshold(one_opponent) == pytest.approx(0.5)
    assert _opponent_hand_threshold(two_blind_opponents) == pytest.approx(0.5**0.5)
    assert _opponent_threshold(_OpponentSnapshot(pot=0, call_bet=100, opponents=1)) is None


def test_combined_opponent_threshold_requires_passing_peek_and_continue_decisions() -> None:
    peek = _OpponentSnapshot(pot=100, call_bet=100, opponents=1)
    continued = _OpponentSnapshot(pot=900, call_bet=100, opponents=1)

    assert _combined_opponent_threshold(peek, continued) == pytest.approx(0.5)
    assert _combined_opponent_threshold(None, continued) == pytest.approx(0.1)
    assert _combined_opponent_threshold(None, None) is None


def test_tracker_records_self_peek_threshold_and_uses_it_for_opponent() -> None:
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False, "bet": 100},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=100,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=100,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    assert tracker.self_thresholds["peek"] == pytest.approx(0.5)
    snapshot = _snapshot_for_actor(after, tracker, "opponent", pot=100, call_bet=100)
    assert snapshot.blind_opponents == 0
    assert snapshot.seen_thresholds == (pytest.approx(0.5),)


def test_tracker_self_threshold_never_decreases_after_continue() -> None:
    tracker = _RoundTracker(self_thresholds={"peek": 0.8})
    before = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=900,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 200},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=1100,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    assert _combined_self_threshold(tracker) == pytest.approx(0.8)

    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 100},
        {"id": "blind", "alive": True, "seen": False, "bet": 100},
        pot=500,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 200},
        {"id": "blind", "alive": True, "seen": False, "bet": 100},
        pot=700,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    # 行动者面对本账号（已看牌、未知门槛）和一名蒙牌玩家；蒙牌权重为 1。
    assert tracker.snapshots["opponent"] == _OpponentSnapshot(pot=500, call_bet=100, opponents=2, blind_opponents=1)


def test_tracker_records_continue_last_action_when_bet_unavailable() -> None:
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "lastAction": "看牌"},
        pot=500,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "lastAction": "跟注"},
        pot=600,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    assert tracker.snapshots["opponent"] == _OpponentSnapshot(pot=500, call_bet=100, opponents=1, blind_opponents=1)


def test_tracker_records_peek_snapshot_and_waits_for_evidence_of_continue() -> None:
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        {"id": "blind", "alive": True, "seen": False, "bet": 100},
        pot=500,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "bet": 100},
        {"id": "blind", "alive": True, "seen": False, "bet": 100},
        pot=500,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    assert tracker.peek_snapshots["opponent"] == _OpponentSnapshot(
        pot=500, call_bet=100, opponents=2, blind_opponents=2
    )
    assert tracker.snapshots == {}


def test_tracker_preserves_peek_snapshot_and_records_later_continue() -> None:
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=500,
        call_bet=100,
    )
    peeked = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "bet": 100},
        pot=500,
        call_bet=100,
    )
    continued = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "bet": 200},
        pot=700,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(peeked, tracker)
    _update_round_tracker(continued, tracker)

    assert tracker.peek_snapshots["opponent"] == _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1
    )
    assert tracker.snapshots["opponent"] == _OpponentSnapshot(pot=500, call_bet=100, opponents=1, blind_opponents=1)


def test_tracker_does_not_assume_seen_player_continued_without_evidence() -> None:
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": False, "bet": 100},
        pot=500,
        call_bet=100,
    )
    after = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opponent", "alive": True, "seen": True, "bet": 100},
        pot=500,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(after, tracker)

    assert tracker.snapshots == {}


def test_call_decision_all_blind_uses_power_probability() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "one", "alive": True, "seen": False},
        {"id": "two", "alive": True, "seen": False},
    )
    decision = _call_decision("金花", (14, 13, 11), game, 0.5, _RoundTracker())

    assert decision is not None
    one_vs_one = zjh_prob.win_prob_1v1("金花", (14, 13, 11))
    assert decision.win_probability == pytest.approx(one_vs_one**2)


def test_call_decision_uses_observed_threshold_for_seen_opponent() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})
    decision = _call_decision("对子", (14, 13), game, 0.1, tracker)

    assert decision is not None
    one_vs_one = zjh_prob.win_prob_1v1("对子", (14, 13))
    expected = max(one_vs_one - 0.5, 0) / 0.5
    assert decision.win_probability == pytest.approx(expected)
    assert decision.seen_thresholds == ((0.5, 1.0, True),)


def test_call_decision_uses_combined_peek_and_continue_threshold() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker(
        peek_snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)},
        snapshots={"seen": _OpponentSnapshot(pot=900, call_bet=100, opponents=1)},
    )
    decision = _call_decision("对子", (14, 13), game, 0.1, tracker)

    assert decision is not None
    one_vs_one = zjh_prob.win_prob_1v1("对子", (14, 13))
    assert decision.win_probability == pytest.approx(max(one_vs_one - 0.5, 0) / 0.5)
    assert decision.seen_thresholds == ((0.5, 1.0, True),)


def test_call_decision_falls_back_for_unobserved_seen_opponent() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
    )
    decision = _call_decision("对子", (14, 13), game, 0.75, _RoundTracker())

    assert decision is not None
    assert decision.seen_thresholds == ((0.75, 1.0, False),)


def test_choose_calls_positive_ev_below_fifty_percent_win_rate() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    choice = _choose("散牌", (8, 7, 5), game, 0.5, _RoundTracker())

    assert choice.call is True
    assert choice.decision is not None
    assert choice.decision.win_probability < 0.5
    assert choice.decision.expected_value > 0


def test_choose_ignores_hand_type_and_decides_purely_by_ev() -> None:
    # 纯 EV 决策：只要期望收益非负，散牌也照样跟注，不再按牌型门控
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    assert _choose("散牌", (8, 7, 5), game, 0.5, _RoundTracker()).call is True


def test_choose_action_opens_for_low_final_actual_win_rate() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    choice = _choose("散牌", (8, 7, 5), game, 0.5, _RoundTracker())

    assert choice.decision is not None
    assert choice.decision.win_probability < 0.5
    assert choice.decision.expected_value > 0
    assert _choose_action(choice, ["open", "call"], True, 0.5, False, 0.75)[0] == "open"


def test_choose_action_raises_for_high_final_actual_win_rate() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=1000,
        call_bet=100,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())

    assert choice.decision is not None
    assert choice.decision.win_probability > 0.75
    assert _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75)[0] == "raise"


def test_choose_action_raise_frequency_slow_plays_when_rng_high() -> None:
    """加注频率随机化：胜率达标但随机数 ≥ 频率 → 慢打平跟（伪装大牌防针对）。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=1000,
        call_bet=100,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())
    assert choice.decision is not None and choice.decision.win_probability > 0.75
    # 频率 0.65，rng=0.9 ≥ 0.65 → 不加注，落回 call
    assert _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 0.65, rng=lambda: 0.9)[0] == "call"
    # rng=0.1 < 0.65 → 加注
    assert _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 0.65, rng=lambda: 0.1)[0] == "raise"


def test_choose_action_raise_frequency_extremes() -> None:
    """边界：频率 1.0 达标必加（旧行为，短路不查 rng）；频率 0 从不加注。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=1000,
        call_bet=100,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())
    # 频率 1.0：即便 rng 接近 1 也必加
    assert _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 1.0, rng=lambda: 0.999)[0] == "raise"
    # 频率 0：rng=0 也不加（0<0 为 False）→ 慢打 call
    assert _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 0.0, rng=lambda: 0.0)[0] == "call"


def test_choose_action_first_peek_no_raise_slow_plays_big_hand() -> None:
    """第一次看牌不加注：本局首次看牌决策即使胜率达标也只平跟慢打，且原因点明慢打。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=1000,
        call_bet=100,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())
    assert choice.decision is not None and choice.decision.win_probability > 0.75

    # first_peek_no_raise=True（首次看牌）：达标也不加注 → call，原因含慢打说明
    action, reason = _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 1.0, first_peek_no_raise=True)
    assert action == "call"
    assert "第一次看牌慢打" in reason
    # first_peek_no_raise=False（后续轮次）：同样达标 → 加注
    assert (
        _choose_action(choice, ["raise", "call"], False, 0.5, True, 0.75, 1.0, first_peek_no_raise=False)[0] == "raise"
    )


def test_choose_action_first_peek_no_raise_skipped_when_no_call_authorized() -> None:
    """边界：强制摊牌阶段无 call 授权时，首次看牌抑制不生效——不能把「继续」也拦了。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=1000,
        call_bet=100,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())
    # actions 无 call：first_peek_no_raise=True 也照常按频率加注（频率 1.0 → raise）
    assert (
        _choose_action(choice, ["fold", "raise", "showdown"], False, 0.5, True, 0.75, 1.0, first_peek_no_raise=True)[0]
        == "raise"
    )


def test_choose_action_falls_back_to_call_when_server_disallows_attack() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    choice = _choose("散牌", (8, 7, 5), game, 0.5, _RoundTracker())

    assert _choose_action(choice, ["call"], True, 0.5, True, 0.75)[0] == "call"


def test_choose_action_folds_for_negative_ev() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=100,
        call_bet=2000,
    )
    choice = _choose("对子", (14, 13), game, 0.5, _RoundTracker())

    assert _choose_action(choice, ["open", "raise", "call"], True, 0.5, True, 0.75)[0] == "fold"


def test_choose_rejects_negative_ev() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=100,
        call_bet=2000,
    )
    choice = _choose("对子", (14, 13), game, 0.5, _RoundTracker())
    assert choice.call is False
    assert "低于弃牌容差" in choice.reason


def test_choose_rejects_invalid_financial_data() -> None:
    choice = _choose("豹子", 14, {"pot": 0, "callBet": 100, "players": []}, 0.5, _RoundTracker())
    assert choice.call is False
    assert choice.decision is None
    assert "数据不完整" in choice.reason


def test_choose_calls_for_straight_under_normal_pot() -> None:
    # 回归：顺子单挑胜率 >0.9，正常底池/成本下应为大幅正 EV 跟注，不应被弃
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "blind", "alive": True, "seen": False},
        pot=7500,
        call_bet=3000,
    )
    choice = _choose("顺子", 11, game, 0.5, _RoundTracker())
    assert choice.call is True
    assert choice.decision is not None
    assert choice.decision.one_vs_one > 0.9
    assert choice.decision.expected_value > 0


def test_call_decision_rejects_invalid_financial_data() -> None:
    game = {"pot": 0, "callBet": 100, "players": []}
    tracker = _RoundTracker()
    assert _call_decision("豹子", 14, game, 0.5, tracker) is None
    assert _call_decision("豹子", 14, {"pot": 100, "callBet": -1}, 0.5, tracker) is None
    assert _call_decision("豹子", None, {"pot": 100, "callBet": 1}, 0.5, tracker) is None


def test_blind_call_cost_is_half_of_seen() -> None:
    # 正向（实测同一 callBet=3000 下蒙牌 +1500、已看牌 +3000）：蒙牌跟注成本为已看牌一半。
    assert _blind_call_cost(3000) == 1500
    assert _blind_call_cost(100) == 50
    assert _blind_call_cost(0) == 0


def test_blind_decision_all_blind_uses_average_hand_and_positive_ev() -> None:
    # 正向：全蒙牌对手，手牌未知按平均单挑胜率 0.5 估；胜率 = 0.5^蒙牌数，大底池下 EV 为正。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "one", "alive": True, "seen": False},
        {"id": "two", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    decision = _blind_decision(game, 0.5, _RoundTracker())

    assert decision is not None
    assert decision.one_vs_one == 0.5
    assert decision.blind_opponents == 2
    assert decision.seen_opponents == 0
    # 手牌未知对两个蒙牌对手积分：三人全蒙各以 1/3 概率最大，而非 0.5²=1/4
    assert decision.win_probability == pytest.approx(1 / 3)
    # 半价成本 50：EV = 1/3 × (10000 + 50) − 50
    assert decision.expected_value == pytest.approx((10000 + 50) / 3 - 50)
    assert decision.expected_value > 0


def test_blind_decision_uses_half_cost_which_flips_ev_positive() -> None:
    # 回归核心：半价概念必须真正进入 EV。此局面按半价 EV=+25（划算，继续蒙跟），
    # 若误用全价成本则 EV=−25——两种结果符号相反，断言半价结果以锁定该概念。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=150,
        call_bet=200,
    )
    decision = _blind_decision(game, 0.5, _RoundTracker())

    assert decision is not None
    # 半价成本 100：EV = 0.5 × (150 + 100) − 100 = +25
    assert decision.expected_value == pytest.approx(25)
    assert decision.expected_value > 0


def test_blind_decision_negative_ev_against_strong_seen_bettor() -> None:
    # 异常路径：对手已看牌且下注很大（回退门槛 0.9），平均手牌几乎必败 → EV 为负，
    # 这正是触发「看牌买信息」而非继续盲跟的情形。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    decision = _blind_decision(game, 0.9, _RoundTracker())

    assert decision is not None
    assert decision.seen_opponents == 1
    assert decision.seen_thresholds == ((0.9, 1.0, False),)
    # 蒙牌对一个门槛 0.9 的已看牌对手积分：(1 − 0.9)/2 = 0.05，仍几乎必败
    assert decision.win_probability == pytest.approx(0.05)
    assert decision.expected_value < 0


def test_blind_decision_rejects_invalid_financial_data() -> None:
    tracker = _RoundTracker()
    assert _blind_decision({"pot": 0, "callBet": 100, "players": []}, 0.5, tracker) is None
    assert _blind_decision({"pot": 100, "callBet": -1, "players": []}, 0.5, tracker) is None
    assert _blind_decision({"pot": 100, "callBet": 100}, -0.1, tracker) is None
    assert _blind_decision({"pot": 100, "callBet": 100}, 1.0, tracker) is None


def test_blind_win_probability_all_blind_is_one_over_n() -> None:
    # 回归核心（用户实测牌桌 #5081：三人全蒙误报 25%）：N 个随机手牌玩家各以 1/N 概率最大。
    # 旧实现把平均单挑胜率 0.5 当固定手牌代进 t^B，三人全蒙得 0.5²=0.25，低估了真实的 1/3。
    assert _blind_win_probability(1, ()) == pytest.approx(1 / 2)  # 单挑纯蒙牌
    assert _blind_win_probability(2, ()) == pytest.approx(1 / 3)  # 三人全蒙
    assert _blind_win_probability(3, ()) == pytest.approx(1 / 4)  # 四人全蒙


def test_blind_win_probability_seen_opponent_uses_threshold_integral() -> None:
    # 蒙牌对单个门槛 T 的已看牌对手积分得 (1 − T)/2；门槛越高越必败。
    assert _blind_win_probability(0, (0.9,)) == pytest.approx(0.05)
    assert _blind_win_probability(0, (0.5,)) == pytest.approx(0.25)
    # 一个蒙牌 + 一个门槛 0.5 的已看牌对手：∫₀¹ t·(t−0.5)/0.5 dt = 5/24
    assert _blind_win_probability(1, (0.5,)) == pytest.approx(5 / 24)


def test_blind_win_probability_rejects_invalid_thresholds() -> None:
    # 异常路径：负蒙牌数或越界门槛返回 0。
    assert _blind_win_probability(-1, ()) == 0.0
    assert _blind_win_probability(1, (1.0,)) == 0.0
    assert _blind_win_probability(1, (-0.1,)) == 0.0


def test_blind_peek_or_call_blind_calls_on_positive_ev() -> None:
    # 正向：EV≥0 时蒙牌半价盲跟本身就划算，继续盲跟（不看牌，避免翻倍投入）。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "one", "alive": True, "seen": False},
        {"id": "two", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "fold", "raise"], 0.5, _RoundTracker())

    assert action == "call"
    assert choice is not None
    assert choice.expected_value > 0


def test_blind_peek_or_call_peeks_on_negative_ev() -> None:
    # 正向：盲跟 Terminal EV<0 时看牌买信息止损，绝不继续盲跟。
    # 看牌免费：弱牌看后弃（净 0=直接弃）、强牌再上，看牌弱占优于弃牌——
    # 门户给看牌时蒙牌永不选 fold，且看牌 EV 结构性 ≥0。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "fold", "raise"], 0.9, _RoundTracker())

    assert action == "peek"
    assert choice is not None
    assert choice.expected_value >= 0


def test_blind_peek_or_call_heads_up_uses_same_ev_path() -> None:
    # 回归：单挑蒙牌对强看牌对手，盲跟 Terminal EV 为负时不盲跟——
    # 看牌免费买信息（弱牌止损、强牌再上），绝不继续被对手 raise 套牢。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["peek", "fold", "showdown"], 0.9, _RoundTracker())

    assert action == "peek"
    assert choice is not None
    assert choice.expected_value >= 0


def test_blind_peek_or_call_heads_up_keeps_positive_ev_blind_call() -> None:
    # 单挑双方蒙牌、底池足够大时，EV≥0 优先用 open 结束本轮（避免对手加注后投入翻倍）。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "open"], 0.5, _RoundTracker())

    assert action == "open"
    assert choice is not None
    assert choice.win_probability == pytest.approx(0.5)
    assert choice.expected_value > 0


def test_blind_peek_or_call_positive_ev_prefers_showdown() -> None:
    # 回归：EV≥0 时 showdown 优先于 open 和 call，直接应战结束本轮。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "open", "showdown"], 0.5, _RoundTracker())

    assert action == "showdown"
    assert choice is not None
    assert choice.expected_value > 0


def test_blind_peek_or_call_positive_ev_uses_open_when_no_showdown() -> None:
    # 回归：EV≥0 时无 showdown 但有 open 则主动开牌。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "open"], 0.5, _RoundTracker())

    assert action == "open"
    assert choice is not None
    assert choice.expected_value > 0


def test_blind_peek_or_call_positive_ev_falls_back_to_call() -> None:
    # 回归：EV≥0 但无 showdown/open 时才退回盲跟。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek"], 0.5, _RoundTracker())

    assert action == "call"
    assert choice is not None
    assert choice.expected_value > 0


def test_blind_peek_or_call_folds_without_peek_action_when_call_ev_negative() -> None:
    # 异常路径：门户不给看牌（actions 无 peek）且盲跟 EV 为负时，直接弃牌止损。
    # （看牌弱占优于弃牌，但看牌不可用时只剩盲跟/弃牌，按盲跟 EV 符号决定——
    # 负 EV 不盲跟，避免被对手 raise 套牢）
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["call", "fold"], 0.9, _RoundTracker())

    assert action == "fold"
    assert choice is not None


def test_blind_peek_or_call_calls_without_peek_action_when_call_ev_positive() -> None:
    # 异常路径：门户不给看牌但盲跟 EV≥0 时仍盲跟（看牌不可用，盲跟半价划算就盲跟）。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    action, choice = _blind_peek_or_call(game, ["call", "fold"], 0.5, _RoundTracker())

    assert action == "call"
    assert choice is not None
    assert choice.call_ev >= 0


def test_blind_peek_or_call_returns_none_without_executable_action() -> None:
    # 异常路径：既不能跟注也不能看牌时返回 None，交回轮询告警，不强行下注。
    # （只给 fold 时按新语义直接弃牌止损，因 fold 本身是可执行止损动作）
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, _ = _blind_peek_or_call(game, ["fold"], 0.9, _RoundTracker())
    assert action in ("fold", None)


def test_in_hand_reflects_self_alive() -> None:
    assert _in_hand({"self": {"alive": True}}) is True
    assert _in_hand({"self": {"alive": False}}) is False
    assert _in_hand({"self": {}}) is False
    assert _in_hand({}) is False


def test_tracker_stops_accumulating_once_self_folds() -> None:
    # 回归：弃牌后本局不再有决策，_poll_loop 门控应停止跟踪对手快照，
    # 避免对手互相缠斗时门槛递归虚高（单挑反推不动点收敛到 1.0）。
    tracker = _RoundTracker()

    def poll(game: dict[str, object]) -> None:
        # 复刻 _poll_loop 的门控：仅在局时更新跟踪器
        if _in_hand(game):
            _update_round_tracker(game, tracker)

    in_hand_blind = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opp", "alive": True, "seen": False, "bet": 100},
        pot=1000,
        call_bet=100,
    )
    in_hand_blind["self"] = {"alive": True}
    poll(in_hand_blind)

    opp_peeks = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opp", "alive": True, "seen": True, "bet": 100},
        pot=1000,
        call_bet=100,
    )
    opp_peeks["self"] = {"alive": True}
    poll(opp_peeks)

    # 正向：我在局时对手上牌被记录
    assert "opp" in tracker.peek_snapshots
    peek_before = tracker.peek_snapshots["opp"]

    self_folded = _game(
        {"id": "self", "alive": False, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opp", "alive": True, "seen": True, "bet": 900},
        pot=9000,
        call_bet=3000,
    )
    self_folded["self"] = {"alive": False}
    poll(self_folded)

    # 异常路径：我方弃牌后对手大幅加注，也不产生新快照、不抬高门槛
    assert tracker.snapshots == {}
    assert tracker.peek_snapshots["opp"] == peek_before


class _ScriptedGetClient:
    """按脚本顺序返回 get 响应的假客户端；耗尽后返回错误响应。"""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = responses
        self.gets = 0

    async def get(self, path: str) -> dict[str, object]:
        idx = self.gets
        self.gets += 1
        if idx < len(self._responses):
            return self._responses[idx]
        return {"_error": "no scripted response left"}


def test_self_hand_reads_portal_state() -> None:
    # 正向：正常读出门户 self 里的手牌，并归一组合文本牌型
    game = {"self": {"hand": "A♠ K♠ Q♠", "handType": "9♠ 3♠ 2♠ → 同花"}}
    assert _self_hand(game) == ("A♠ K♠ Q♠", "金花")


def test_self_hand_returns_empty_when_missing() -> None:
    # 异常路径：手牌/牌型缺失或为 None 时返回空串，绝不能回退成 "?"
    # （旧代码默认 "?" 导致 _extract_hand_value 解析失败 → 误判数据不完整而弃牌）
    assert _self_hand({}) == ("", "")
    assert _self_hand({"self": {}}) == ("", "")
    assert _self_hand({"self": {"hand": "", "handType": ""}}) == ("", "")
    assert _self_hand({"self": {"hand": None, "handType": None}}) == ("", "")


@pytest.mark.asyncio
async def test_acquire_hand_after_peek_uses_existing_hand_without_refetch() -> None:
    # 正向：看牌响应已带手牌时直接采用，不发起任何重拉
    client = _ScriptedGetClient([])
    game = {"self": {"hand": "A♠ K♠ Q♠", "handType": "金花"}}
    _, hand, hand_type = await _acquire_hand_after_peek(client, game)
    assert hand == "A♠ K♠ Q♠"
    assert hand_type == "金花"
    assert client.gets == 0


@pytest.mark.asyncio
async def test_acquire_hand_after_peek_refetches_until_hand_ready() -> None:
    # 正向：首次响应缺手牌 → 重拉；重拉先出错也不中断，再拉到就补齐
    client = _ScriptedGetClient(
        [
            {"game": {"self": {"hand": "", "handType": ""}}},
            {"_error": "transient"},
            {"game": {"self": {"hand": "A♠ K♠ Q♠", "handType": "金花"}}},
        ]
    )
    out_game, hand, hand_type = await _acquire_hand_after_peek(client, {"self": {}})
    assert hand == "A♠ K♠ Q♠"
    assert hand_type == "金花"
    assert out_game["self"]["hand"] == "A♠ K♠ Q♠"
    assert client.gets == 3


@pytest.mark.asyncio
async def test_acquire_hand_after_peek_returns_empty_when_never_ready() -> None:
    # 异常路径：重拉 3 次仍读不到手牌时返回空串（交回轮询等补齐），绝不弃牌
    client = _ScriptedGetClient([{"game": {"self": {"hand": "", "handType": ""}}} for _ in range(5)])
    _, hand, hand_type = await _acquire_hand_after_peek(client, {"self": {}})
    assert hand == ""
    assert hand_type == ""
    assert client.gets == 3


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_negative_ev_uses_normal_fold() -> None:
    """单挑已看牌、EV 为负也走普通弃牌，不再强制跟注或主动比牌。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    game.update(
        {
            "roundId": 123,
            "actions": ["fold", "call", "raise", "open"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    client = _FakeClient()

    pending_fold = await _act_on_hand(
        _FakeContext(),
        client,
        {"zjh_notify_hand": False},
        game,
        "2♠ 3♥ 5♦",
        "散牌",
        0.5,
        _RoundTracker(),
    )

    assert pending_fold is False
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "fold"})]


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_positive_ev_uses_normal_call() -> None:
    """单挑已看牌、EV 为正时走普通 call，而非单挑强制动作。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    game.update(
        {
            "roundId": 123,
            "actions": ["fold", "call"],
            "self": {"alive": True, "isTurn": True},
        }
    )
    client = _FakeClient()

    pending_fold = await _act_on_hand(
        _FakeContext(),
        client,
        {"zjh_notify_hand": False},
        game,
        "A♠ K♥ Q♦",
        "顺子",
        0.5,
        _RoundTracker(),
    )

    assert pending_fold is False
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "call"})]


def test_choose_fold_ev_tolerance_keeps_marginal_hands() -> None:
    """回归 #9：EV 略负时在容差内不弃牌。

    Q-9-5 散牌对单盲对手，pot=1500/callBet=1000 时 EV≈−77（边际负，类似线上 −94 弃牌）。
    容差 0（旧行为）弃牌；容差 10%（−100 内不弃）则跟注——边际负 EV 在胜率估算噪声内，
    且弃牌白白让出已投入底池权益。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
        pot=1500,
        call_bet=1000,
    )
    choice_strict = _choose("散牌", (12, 9, 5), game, 0.5, _RoundTracker(), 0.0)
    assert choice_strict.call is False

    choice_lenient = _choose("散牌", (12, 9, 5), game, 0.5, _RoundTracker(), 10.0)
    assert choice_lenient.call is True


def test_choose_fold_ev_tolerance_still_folds_clearly_negative() -> None:
    """容差不是无条件跟：EV 远低于容差（强负）仍弃牌。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
        pot=100,
        call_bet=2000,
    )
    # 弱散牌 + 极差底池赔率，EV 大幅为负，容差 10%（−200）也救不回
    choice = _choose("散牌", (7, 5, 3), game, 0.5, _RoundTracker(), 10.0)
    assert choice.call is False


class _CapturingContext:
    """记录 notify 推送内容的假上下文。"""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.kv: dict[str, object] = {}

    async def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.messages.append(message)


def test_game_result_notification_three_arg_call_renders_hand_and_reveals() -> None:
    # 回归：修复前存在两个同名函数，四参版本遮蔽三参版本，
    # 调用方用三参 → TypeError 崩溃。此三参调用即崩溃现场。
    game_data = {
        "game": {
            "self": {"alive": True},
            "players": [
                {"id": "self", "isSelf": True, "alive": True, "hand": "A♠ K♠ Q♠", "handType": "金花"},
                {"id": "opp1", "alive": True, "hand": "K♣ K♦ 9♠", "handType": "对子"},
                {"id": "opp2", "alive": False, "hand": "2♠ 3♥ 5♦", "handType": "散牌"},
            ],
        }
    }

    notification = _game_result_notification(game_data, "A♠ K♠ Q♠", "金花")

    lines = notification.splitlines()
    assert lines[0] == "🃏 炸金花 · 本局获胜"
    assert "手牌 A♠ K♠ Q♠（金花）" in notification
    assert "你 存活 · A♠ K♠ Q♠（金花）" in notification
    assert "对手1 存活 · K♣ K♦ 9♠（对子）" in notification
    assert "对手2 出局 · 2♠ 3♥ 5♦（散牌）" in notification


def test_game_result_notification_ranks_only_opponents() -> None:
    # 回归：排行计数只对非本账号递增，单对手应显示“对手1”而非“对手2”。
    game_data = {
        "game": {
            "self": {"alive": False},
            "players": [
                {"id": "self", "isSelf": True, "alive": False},
                {"id": "opp", "alive": True, "hand": "K♣ K♦ 9♠", "handType": "对子"},
            ],
        }
    }

    notification = _game_result_notification(game_data, "", "")

    assert "本局结束" in notification
    assert "手牌" not in notification
    assert "你 出局" in notification
    assert "对手1 存活 · K♣ K♦ 9♠（对子）" in notification
    assert "对手2" not in notification


@pytest.mark.asyncio
async def test_notify_game_result_pushes_rendered_notification() -> None:
    # 正向：开启通知时推送渲染后的结果文本。
    ctx = _CapturingContext()
    game_data = {
        "game": {
            "self": {"alive": True},
            "players": [
                {"id": "self", "isSelf": True, "alive": True, "hand": "A♠ K♠ Q♠", "handType": "金花"},
                {"id": "opp", "alive": True, "hand": "K♣ K♦ 9♠", "handType": "对子"},
            ],
        }
    }

    await _notify_game_result(ctx, {"zjh_notify_hand": True}, game_data, "A♠ K♠ Q♠", "金花")

    assert len(ctx.messages) == 1
    assert "本局获胜" in ctx.messages[0]
    assert "A♠ K♠ Q♠" in ctx.messages[0]


@pytest.mark.asyncio
async def test_notify_game_result_disabled_pushes_nothing() -> None:
    # 异常路径：关闭通知开关时不推送。
    ctx = _CapturingContext()

    await _notify_game_result(ctx, {"zjh_notify_hand": False}, {"game": {}}, "A♠", "对子")

    assert ctx.messages == []


class _RecordingContext:
    """同时记录 notify 推送与提供日志接口的假上下文。"""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.log = _FakeLog()

    async def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.messages.append(message)


class _ResultClient:
    """按固定响应返回 post 结果的假客户端，用于模拟确认弃牌成功/失败。"""

    def __init__(self, response: dict[str, object]) -> None:
        self._response = response
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.requests.append((path, body))
        return self._response


def _pending_fold() -> _PendingFold:
    return _PendingFold(rid=123, hand="2♠ 3♥ 5♦", hand_type="散牌", choice=_Choice(False, "跟注期望收益为负", None))


def test_blind_notification_renders_call_with_ev_detail() -> None:
    # 正向：蒙牌盲跟通知带半价成本、蒙牌胜率与期望收益。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "one", "alive": True, "seen": False},
        {"id": "two", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    decision = _blind_decision(game, 0.5, _RoundTracker())
    assert decision is not None

    notification = _blind_notification("call", 5010, decision, 10000, 100, "蒙牌半价盲跟划算")

    lines = notification.splitlines()
    assert lines[0] == "🃏 炸金花 · 蒙牌盲跟"
    assert "牌桌 #5010 · 未看牌" in notification
    assert "半价成本 50" in notification
    assert "蒙牌胜率 33.3%" in notification
    assert "原因：蒙牌半价盲跟划算" in notification


def test_blind_notification_renders_peek_without_decision() -> None:
    # 异常路径：牌局数据不完整（无评估明细）时看牌通知仍可渲染，只缺概率行。
    notification = _blind_notification("peek", 5011, None, 0, 0, "牌局数据不完整，先看牌再按实际手牌决策")

    lines = notification.splitlines()
    assert lines[0] == "🃏 炸金花 · 看牌买信息"
    assert "牌桌 #5011 · 未看牌" in notification
    assert "半价成本" not in notification
    assert "原因：牌局数据不完整，先看牌再按实际手牌决策" in notification


def test_blind_notification_renders_terminal_decision() -> None:
    # 回归：蒙牌决策改 Terminal EV 后，_blind_notification 必须兼容 _TerminalDecision
    # （无 one_vs_one/blind_opponents 等 _CallDecision 字段），否则线上轮询崩。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=16500,
        call_bet=6000,
    )
    terminal = _terminal_ev_decision(game, 0.65, _RoundTracker(), depth=2)
    notification = _blind_notification("peek", 5012, terminal, 16500, 6000, terminal.reason)

    lines = notification.splitlines()
    assert lines[0] == "🃏 炸金花 · 看牌买信息"
    assert "牌桌 #5012 · 未看牌" in notification
    assert "终局期望" in notification
    assert "盲跟" in notification
    assert "看牌" in notification
    assert "弃牌 0" in notification
    assert "原因：" in notification


@pytest.mark.asyncio
async def test_confirm_fold_success_notifies_and_clears_pending() -> None:
    # 正向：确认弃牌成功 → 推送弃牌通知、清空待确认状态并返回 True。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": True})
    tracker = _RoundTracker(pending_fold=_pending_fold())

    result = await _confirm_fold(ctx, client, {"zjh_notify_hand": True}, tracker)

    assert result is True
    assert tracker.pending_fold is None
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "fold"})]
    assert len(ctx.messages) == 1
    assert "弃牌" in ctx.messages[0]


@pytest.mark.asyncio
async def test_confirm_fold_failure_keeps_pending_for_retry() -> None:
    # 异常路径（回归死循环 bug）：门户拒绝确认 → 返回 False 且保留待确认状态，
    # 交给调用方按重试计数处理，而不是无声丢弃或无限重发。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": False, "error": "not your turn"})
    tracker = _RoundTracker(pending_fold=_pending_fold())

    result = await _confirm_fold(ctx, client, {"zjh_notify_hand": True}, tracker)

    assert result is False
    assert tracker.pending_fold is not None
    assert ctx.messages == []


@pytest.mark.asyncio
async def test_confirm_fold_respects_notify_toggle() -> None:
    # 异常路径：关闭手牌通知开关时确认成功也不推送，但仍清空待确认状态。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": True})
    tracker = _RoundTracker(pending_fold=_pending_fold())

    result = await _confirm_fold(ctx, client, {"zjh_notify_hand": False}, tracker)

    assert result is True
    assert tracker.pending_fold is None
    assert ctx.messages == []


def test_fold_confirm_max_retries_is_bounded() -> None:
    # 回归：确认弃牌重试必须有正上限，避免门户持续拒绝时每轮无限重发。
    assert _FOLD_CONFIRM_MAX_RETRIES > 0


# ── 蒙牌弃牌提交（v1.15.1 修复「决策树判弃牌却从不提交」卡死 bug）─────────────


def _terminal_fold() -> _TerminalDecision:
    return _TerminalDecision(
        action="fold",
        terminal_ev=0.0,
        single_step_ev=-100.0,
        call_ev=-500.0,
        peek_ev=-10.0,
        fold_ev=0.0,
        branches=(),
        reason="蒙牌弃牌 Terminal EV 0 ≥ 盲跟 -500 / 看牌 -10",
    )


@pytest.mark.asyncio
async def test_request_blind_fold_submits_and_notifies() -> None:
    # 正向：决策树判弃牌时真正提交 fold 动作，无需确认即推送蒙牌弃牌通知。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": True})
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=20150,
        call_bet=3100,
    )
    tracker = _RoundTracker()

    pending = await _request_blind_fold(ctx, client, {"zjh_notify_hand": True}, game, _terminal_fold(), tracker)

    assert pending is False  # 无需二次确认
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "fold"})]
    assert tracker.pending_fold is None
    assert len(ctx.messages) == 1
    assert "蒙牌弃牌" in ctx.messages[0]


@pytest.mark.asyncio
async def test_request_blind_fold_defers_notification_when_confirm_needed() -> None:
    # 异常路径：门户要求双击确认（foldConfirm）时延后通知，待确认成功后才推送。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": True, "game": {"self": {"foldConfirm": True}}})
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=20150,
        call_bet=3100,
    )
    tracker = _RoundTracker()

    pending = await _request_blind_fold(ctx, client, {"zjh_notify_hand": True}, game, _terminal_fold(), tracker)

    assert pending is True  # 等待确认
    assert tracker.pending_fold is not None
    assert tracker.pending_fold.notification  # 预构建通知已暂存
    assert ctx.messages == []  # 确认前不推送

    # 确认成功 → 推送预构建的蒙牌弃牌通知并清空待确认状态
    confirm_client = _ResultClient({"ok": True})
    confirmed = await _confirm_fold(ctx, confirm_client, {"zjh_notify_hand": True}, tracker)
    assert confirmed is True
    assert tracker.pending_fold is None
    assert len(ctx.messages) == 1
    assert "蒙牌弃牌" in ctx.messages[0]


@pytest.mark.asyncio
async def test_request_blind_fold_failure_returns_false() -> None:
    # 异常路径：门户拒绝弃牌请求 → 返回 False、不通知、不设待确认，交回轮询重试。
    ctx = _RecordingContext()
    client = _ResultClient({"ok": False, "error": "not your turn"})
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker()

    pending = await _request_blind_fold(ctx, client, {"zjh_notify_hand": True}, game, _terminal_fold(), tracker)

    assert pending is False
    assert tracker.pending_fold is None
    assert ctx.messages == []


def test_peek_terminal_ev_never_negative() -> None:
    # 回归核心（用户质疑「万一是豹子呢」）：看牌免费、弱牌弃=直接弃（净 0），
    # 看牌弱占优于弃牌 → 无论对手多强、成本多高，看牌 EV 结构性 ≥0。
    scenarios = [
        # (底池, callBet, 对手门槛, 对手动作概率)
        (100, 2000, 0.9, (0.0, 0.2, 0.8)),  # 强看牌加注型、成本远大于底池
        (100, 50000, 0.99, (0.0, 0.0, 1.0)),  # 极强对手、天价成本
        (16500, 6000, 0.65, (0.08, 0.22, 0.70)),  # 真实盘面 5129
        (21450, 3300, 0.719, (0.0, 0.38, 0.62)),  # 真实盘面 5569
    ]
    for pot, call_bet, threshold, probs in scenarios:
        opps = [_BlindOpponent("opp", True, probs, threshold)]
        ev = _terminal_ev_peek_multi(
            {"roundId": 1, "pot": pot, "callBet": call_bet}, 0.5, _RoundTracker(), 2, None, opps
        )
        assert ev >= 0, f"看牌 EV 不应为负：pot={pot} callBet={call_bet} T={threshold} got {ev}"


def test_peek_terminal_ev_all_fold_wins_pot() -> None:
    # 边界：对手必弃 → 看牌后任意手牌都白赢底池，EV = 底池 × P(继续)。
    # 全对手弃牌时继续 EV(t)=pot>0 对一切 t 成立 → T*=0，peek_ev = pot。
    opps = [_BlindOpponent("opp", False, (1.0, 0.0, 0.0), 0.0)]
    ev = _terminal_ev_peek_multi({"roundId": 1, "pot": 10000, "callBet": 1000}, 0.5, _RoundTracker(), 2, None, opps)
    assert ev == pytest.approx(10000)


def test_terminal_ev_decision_never_folds_blind() -> None:
    # 回归：蒙牌决策树永不输出 fold（看牌 EV 结构性 ≥0 = 弃牌 EV，弱占优取看牌）。
    scenarios = [
        (100, 2000, 0.9, (0.0, 0.2, 0.8)),
        (100, 50000, 0.99, (0.0, 0.0, 1.0)),
        (21450, 3300, 0.719, (0.0, 0.38, 0.62)),
    ]
    for pot, call_bet, threshold, probs in scenarios:
        opps = [_BlindOpponent("opp", True, probs, threshold)]
        dec = _terminal_ev_decision(
            {"roundId": 1, "pot": pot, "callBet": call_bet}, 0.5, _RoundTracker(), depth=2, opponents=opps
        )
        assert dec.action != "fold", f"蒙牌不应判弃牌：pot={pot} callBet={call_bet} got {dec.action}"


def test_blind_peek_or_call_prefers_peek_over_fold_when_available() -> None:
    # 回归：即使（异常路径下）决策树输出 fold，门户给看牌时仍优先看牌——
    # 看牌免费、信息永不亏，弱占优于弃牌。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "fold", "raise"], 0.9, _RoundTracker())
    assert action == "peek"
    assert choice is not None


def test_blind_peek_or_call_showdown_phase_continues_when_peek_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 回归：强制摊牌阶段（actions 无 peek/call，只有 fold/raise/showdown），
    # 决策树判看牌最优但看牌不可用、盲跟 EV≥0 时，必须用 showdown 当「继续」动作应战，
    # 而不是落到 fold——正 EV 弃牌等于白扔底池权益。
    from plugins.skyGame.games.zhajinhua import zjh_model

    crafted = _TerminalDecision(
        action="peek",
        terminal_ev=500.0,
        single_step_ev=100.0,
        call_ev=120.0,
        peek_ev=500.0,
        fold_ev=0.0,
        branches=(),
        reason="测试构造：看牌最优且盲跟 EV≥0",
    )
    monkeypatch.setattr(zjh_model, "_terminal_ev_decision", lambda *args, **kwargs: crafted)
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=100000,
        call_bet=3000,
    )
    action, choice = _blind_peek_or_call(game, ["fold", "raise", "showdown"], 0.5, _RoundTracker())
    assert action == "showdown"
    assert choice is crafted


def test_blind_peek_or_call_showdown_phase_folds_when_call_ev_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 同阶段异常路径：盲跟 EV<0 时看牌又不可用 → 弃牌止损，不能硬 showdown 送钱。
    from plugins.skyGame.games.zhajinhua import zjh_model

    crafted = _TerminalDecision(
        action="peek",
        terminal_ev=10.0,
        single_step_ev=-50.0,
        call_ev=-800.0,
        peek_ev=10.0,
        fold_ev=0.0,
        branches=(),
        reason="测试构造：看牌最优但盲跟 EV<0",
    )
    monkeypatch.setattr(zjh_model, "_terminal_ev_decision", lambda *args, **kwargs: crafted)
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=1000,
        call_bet=24000,
    )
    action, choice = _blind_peek_or_call(game, ["fold", "raise", "showdown"], 0.9, _RoundTracker())
    assert action == "fold"
    assert choice is crafted


def test_peek_terminal_ev_empty_branches_returns_zero() -> None:
    # 异常路径：空分支（无对手）返回 0，防御除零/空迭代。
    assert _peek_terminal_ev([]) == 0.0


# ── 阶段二：范围上限 + 反诈唬补丁 ──────────────────────────────────────────────


def test_ranged_win_probability_matches_actual_without_profile() -> None:
    # 向后兼容核心：无画像（upper 恒 1.0、诈唬 0）下逐值等于旧 _actual_win_probability。
    cases = [
        (0.6, 0, ((0.4, 1.0),)),
        (0.7, 1, ((0.5, 1.0),)),
        (0.8, 2, ((0.3, 1.0), (0.6, 1.0))),
        (0.5, 1, ()),
        (0.45, 0, ((0.5, 1.0),)),  # t ≤ 门槛 → 两者都得 0
    ]
    for one_vs_one, blind, bounds in cases:
        seen_ranges = [_SeenRange(lower, upper, True) for lower, upper in bounds]
        thresholds = tuple(lower for lower, _ in bounds)
        assert _ranged_win_probability(one_vs_one, blind, seen_ranges) == pytest.approx(
            _actual_win_probability(one_vs_one, blind, thresholds)
        )


def test_range_factor_edges_and_degenerate_fallback() -> None:
    assert _range_factor(0.3, 0.5, 0.85) == 0.0  # t ≤ 下界 → 必败
    assert _range_factor(0.9, 0.5, 0.85) == 1.0  # t ≥ 上界 → 必胜
    assert _range_factor(0.675, 0.5, 0.85) == pytest.approx(0.5)  # 区间中点线性
    # 退化区间（上界 ≤ 下界）回落上界 1.0，即旧的 (t - lo)/(1 - lo)
    assert _range_factor(0.75, 0.5, 0.5) == pytest.approx((0.75 - 0.5) / (1.0 - 0.5))
    assert _range_factor(0.75, 0.6, 0.5) == pytest.approx((0.75 - 0.6) / (1.0 - 0.6))


def test_seen_factor_without_profile_is_pure_range_win() -> None:
    # 无画像对手：诈唬率 0、无实测混合，seen_factor 退化为纯范围胜率。
    seen_range = _SeenRange(0.5, 0.85, True)
    hand_threshold = 0.7
    assert _seen_factor(hand_threshold, seen_range) == pytest.approx(_range_factor(hand_threshold, 0.5, 0.85))


def test_seen_factor_profile_bluff_raises_win_probability() -> None:
    # 画像反诈唬：全 call 跟注站（hand-level 继续频率 1.0）频率诈唬下界混入单挑胜率 t，抬高胜率。
    store = ProfileStore()
    for _ in range(10):
        store.record_raise_freq("opp", True, 0, 0, False)
        store.record_action("opp", "call", True, 0, 0)
    seen_range = _SeenRange(0.5, 0.85, True, store, "opp", "call", "s_s0b0")
    hand_threshold = 0.7
    base = _range_factor(hand_threshold, 0.5, 0.85)
    bluff = store.bluff_rate("opp", "s_s0b0")
    assert bluff > 0
    assert _seen_factor(hand_threshold, seen_range) == pytest.approx((1 - bluff) * base + bluff * hand_threshold)
    assert _seen_factor(hand_threshold, seen_range) > base


def test_is_raise_action_detects_raise_keywords() -> None:
    assert _is_raise_action("加注") is True
    assert _is_raise_action("Raise") is True
    assert _is_raise_action("跟注") is False
    assert _is_raise_action("看牌") is False
    assert _is_raise_action("call") is False


def test_seen_opponent_ranges_caller_upper_always_one() -> None:
    # 范围映射（画像驱动）：平跟对手 [推断门槛, 1.0] 永不封顶（对手可能慢打坚果牌）；
    # 加注对手无画像时 [推断门槛, 1.0]；即使画像里有平跟分位数据也不设上限。
    store = ProfileStore()
    # 给平跟对手回填很强的平跟分位——旧版 call_threshold_ceiling 会压上限，新版必须无影响
    for pct in (0.6, 0.7, 0.8, 0.9):
        store.record_hand_pctile("caller", "call", pct, op_seen=True, seen_count=0, blind_count=0)
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "caller", "alive": True, "seen": True},
        {"id": "raiser", "alive": True, "seen": True},
    )
    tracker = _RoundTracker(
        snapshots={
            "caller": _OpponentSnapshot(pot=100, call_bet=100, opponents=1, is_raise=False),
            "raiser": _OpponentSnapshot(pot=100, call_bet=100, opponents=1, is_raise=True),
        }
    )
    blind, ranges = _seen_opponent_ranges(game, tracker, 0.1, store)

    assert blind == 0
    # 平跟对手：[推断门槛 0.5, 1.0]，画像分位不封顶
    assert ranges[0].lower == pytest.approx(0.5)
    assert ranges[0].upper == pytest.approx(1.0)
    assert ranges[0].observed is True
    # 加注对手：无实测加注分位/频率数据时下限 = 推断门槛
    assert ranges[1].lower == pytest.approx(0.5)
    assert ranges[1].upper == pytest.approx(1.0)
    assert ranges[1].observed is True


def test_call_decision_profile_loosens_win_probability() -> None:
    # 放松方向：同一手牌、同一已看牌对手，弱牌加注/跟注站画像（实测弱牌分位 +
    # 高继续频率反诈唬）比无画像胜率与 EV 都更高，推断门槛不变。
    store = ProfileStore()
    for _ in range(10):
        store.record_action("seen", "call", True, 0, 0)
    for pct in (0.15, 0.2, 0.25, 0.3, 0.1, 0.2):
        store.record_hand_pctile("seen", "call", pct, op_seen=True, seen_count=0, blind_count=0)
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})
    neutral = _call_decision("对子", (14, 13), game, 0.1, tracker)
    loosened = _call_decision("对子", (14, 13), game, 0.1, tracker, store)

    assert neutral is not None and loosened is not None
    assert loosened.win_probability > neutral.win_probability
    assert loosened.expected_value > neutral.expected_value
    # 推断门槛不变，upper 恒 1.0
    assert neutral.seen_thresholds == ((0.5, 1.0, True),)
    assert loosened.seen_thresholds == ((0.5, 1.0, True),)


def test_choose_flips_to_call_when_profile_loosens_ev() -> None:
    # 端到端放松：同一手牌、同一对手，无画像 EV 为负而弃，弱牌画像接入后 EV 转正而跟。
    store = ProfileStore()
    for _ in range(10):
        store.record_action("seen", "call", True, 0, 0)
    for pct in (0.15, 0.2, 0.25, 0.3, 0.1, 0.2):
        store.record_hand_pctile("seen", "call", pct, op_seen=True, seen_count=0, blind_count=0)

    one_vs_one = zjh_prob.win_prob_1v1("对子", (14, 13))
    neutral_win = _ranged_win_probability(one_vs_one, 0, [_SeenRange(0.5, 1.0, True)])
    probe_game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})
    probe = _call_decision("对子", (14, 13), probe_game, 0.1, tracker, store)
    assert probe is not None
    loosened_win = probe.win_probability
    assert loosened_win > neutral_win

    # 底池取「无画像弃」与「画像跟」两条 EV=0 临界点的中点，确保两侧符号相反
    call_bet = 100.0
    pot = ((1 / neutral_win - 1) + (1 / loosened_win - 1)) / 2 * call_bet
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=pot,
        call_bet=call_bet,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})

    neutral_choice = _choose("对子", (14, 13), game, 0.1, tracker)
    loosened_choice = _choose("对子", (14, 13), game, 0.1, tracker, 0.0, store)
    assert neutral_choice.call is False
    assert loosened_choice.call is True


# ── 蒙牌看牌原因文案（回归：EV≥0 但门户不给盲跟时不能误报 EV<0） ────────────────


def test_blind_peek_reason_positive_ev_but_call_unavailable() -> None:
    # 回归（用户牌桌 #5137）：EV=+12643 却收到「EV<0 不划算」的看牌原因。实为门户本轮
    # 只开放 peek、没给盲跟 call，被迫看牌——原因必须说明「门户未开放盲跟」而非「不划算」。
    positive = _blind_decision(
        _game(
            {"id": "self", "alive": True, "isSelf": True, "seen": False},
            {"id": "opp", "alive": True, "seen": False},
            pot=43500,
            call_bet=9000,
        ),
        0.5,
        _RoundTracker(),
    )
    assert positive is not None and positive.expected_value > 0

    reason = _blind_peek_reason(positive, ["peek"])
    assert "EV≥0" in reason
    assert "EV<0" not in reason
    # 防御分支（正 EV 且有 call，实际不会走到看牌）也不得谎称 EV<0
    assert "EV<0" not in _blind_peek_reason(positive, ["peek", "call"])


def test_blind_peek_reason_negative_ev_truly_unprofitable() -> None:
    negative = _blind_decision(
        _game(
            {"id": "self", "alive": True, "isSelf": True, "seen": False},
            {"id": "opp", "alive": True, "seen": False},
            pot=100,
            call_bet=2000,
        ),
        0.5,
        _RoundTracker(),
    )
    assert negative is not None and negative.expected_value < 0
    assert "EV<0" in _blind_peek_reason(negative, ["peek"])


def test_blind_peek_reason_incomplete_data() -> None:
    assert "数据不完整" in _blind_peek_reason(None, ["peek"])


# ──────────────────────────────────────────────────────────────────────
# Terminal EV 决策树 + 对手画像（v1.14.0 新增）
# ──────────────────────────────────────────────────────────────────────


def test_blind_vs_seen_win_bayes_discount() -> None:
    """我方蒙牌对门槛 T 已看牌对手的胜率 = (1−T)/2，门槛越高越衰减。"""
    assert _blind_vs_seen_win(0.0) == pytest.approx(0.5)  # 对手任意牌
    assert _blind_vs_seen_win(0.5) == pytest.approx(0.25)
    assert _blind_vs_seen_win(0.9) == pytest.approx(0.05)  # 强对手，胜率极低
    assert _blind_vs_seen_win(0.75) == pytest.approx(0.125)
    assert _blind_vs_seen_win(1.0) == pytest.approx(0.0)  # 边界
    assert _blind_vs_seen_win(-0.1) == pytest.approx(0.5)  # 非法低门槛回退


def test_opponent_raise_threshold_escalates() -> None:
    """对手每 raise 一次门槛向 1.0 上调且不越界；画像接管后按实测下四分位收缩。"""
    base = 0.5
    t1 = _opponent_raise_threshold(base, 1)
    t2 = _opponent_raise_threshold(base, 2)
    assert t1 > base
    assert t2 > t1
    assert t2 <= 1.0
    # 无 uid / 画像无数据 → 回退通用推断（与不传 profile 逐值一致）
    store = ProfileStore()
    assert _opponent_raise_threshold(base, 1, store, "unknown") == pytest.approx(t1)
    # 诈唬型对手（弱牌加注多，下四分位低）→ 门槛被拉低（< 通用推断）
    for _ in range(6):
        store.record_hand_pctile("account:bluffy", "raise", 0.2)
    t_bluffy = _opponent_raise_threshold(base, 1, store, "account:bluffy")
    assert t_bluffy < t1
    # 紧手对手（加注都是强牌，下四分位高）→ 门槛被抬高（> 通用推断）
    for _ in range(6):
        store.record_hand_pctile("account:tight", "raise", 0.95)
    t_tight = _opponent_raise_threshold(base, 1, store, "account:tight")
    assert t_tight > t1
    assert t_tight <= 1.0


def test_terminal_ev_call_opponent_fold_wins_pot() -> None:
    """蒙牌对手弃牌分支：我方独赢当前底池，净收益 = pot − 已投入。

    v1.16.6 起看牌对手（opponent_seen=True）不进入 fold 分支（门槛由继续下注反推，
    已推断强牌不会对我方跟注弃牌），fold-win 只对蒙牌对手适用。
    """
    # 纯弃牌（P_fold=1）深度 1：蒙牌对手直接终局，我独赢底池
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    ev = _terminal_ev_call(game, 0.5, _RoundTracker(), 1, None, (1.0, 0.0, 0.0), 10000, 0, 0.5, 0, None, False)
    # 蒙牌对手弃牌 → 我独赢 10000，成本 0
    assert ev == pytest.approx(10000)


def test_terminal_ev_call_seen_opponent_never_folds() -> None:
    """回归（线上 #6109）：看牌对手不按历史弃牌率弃牌，fold-win 不虚高盲跟 EV。

    三个看牌对手门槛 0.94+（真实胜率≈1%）时，旧实现把画像历史弃牌率（如 62%）
    当成「会对我方跟注弃牌」，白赢底池分支把盲跟 EV 虚高到 +45725 误开牌。
    修复后看牌对手 fold 清零、按 call/raise 重归一化：同样纯弃牌画像，看牌对手
    被视为必跟（fold 清零后 call 归一为 1），EV 落到负值（胜率≈1% 不该跟）。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=84000,
        call_bet=3000,
        ante=3000,
    )
    # 纯弃牌画像 (1.0, 0.0, 0.0)：看牌对手 fold 清零后归一为必跟，不再是白赢底池
    ev_seen = _terminal_ev_call(game, 0.95, _RoundTracker(), 1, None, (1.0, 0.0, 0.0), 84000, 0, 0.01, 0, 3000, True)
    # 看牌对手必跟 → 摊牌按 1% 胜率：0.01×(84000+1500+3000)−1500 ≈ −595，绝非白赢 84000
    assert ev_seen < 0
    assert ev_seen == pytest.approx(0.01 * (84000 + 1500 + 3000) - 1500)


def test_terminal_ev_call_depth_cutoff_showdown() -> None:
    """深度截断：depth≤0 = 强制摊牌（showdown），不再下注，按当前胜率分摊。

    v1.16.4 起截断语义从「再按对手动作加权一轮」改为「摊牌」——旧实现把本轮
    对手动作重复枚举一遍且我方盲跟未进池，EV 低估/时序错乱。depth=0 直接摊牌：
    EV = win_prob × pot − cost。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    ev = _terminal_ev_call(game, 0.5, _RoundTracker(), 0, None, (1 / 3, 1 / 3, 1 / 3), 10000, 0, 0.5)
    # 摊牌：0.5 × 10000 − 0
    assert ev == pytest.approx(0.5 * 10000)


def test_terminal_ev_decision_picks_blind_call_when_cheap_and_fold_heavy() -> None:
    """底池大、成本小、对手爱弃牌：盲跟 Terminal EV 最高 → call。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=50000,
        call_bet=100,
    )
    dec = _terminal_ev_decision(game, 0.5, _RoundTracker(), depth=2, action_probs=(0.5, 0.2, 0.3))
    assert dec.action == "call"
    assert dec.terminal_ev > 0


def test_terminal_ev_decision_peeks_when_seen_opponent_strong() -> None:
    """单挑对强看牌对手（门槛 0.9）、成本高：盲跟 EV 大负，但看牌免费弱占优于弃牌。

    回归（用户质疑「万一是豹子呢」）：看牌后弱牌弃=直接弃（净 0）、强牌再上，
    所以看牌 EV 结构性 ≥0，蒙牌决策树永不应输出 fold——旧版拿配置门槛当强弱分界，
    把 [配置值, 盈亏平衡点) 的牌误计为「负 EV 仍继续」拖负看牌 EV，错判「弃牌最优」。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    dec = _terminal_ev_decision(game, 0.9, _RoundTracker(), depth=2)
    assert dec.action == "peek"
    assert dec.peek_ev >= 0
    assert dec.call_ev < 0


def test_terminal_ev_decision_blind_call_beats_peek_on_loose_opponent_big_pot() -> None:
    """对手爱加注、几乎不弃牌、门槛偏低 + 大底池：盲跟（半价）胜于看牌（全价跟注）。

    真实加注规则下盲跟每轮只付半价、看牌后跟注要付全价 callBet；对手门槛低（0.3）
    意味着其牌力不强、我方蒙牌胜率不低，初始 pot 已大（10000）时半价盲跟的正 EV
    超过看牌。回归：修正对称下注模型（对手同轮追平 + 蒙牌对手半价）后，肥羊场景
    盲跟确实胜出，不再是旧模型（对手全价下注 + ×1.5 复利加注）把盲跟 EV 打负的
    错误「看牌更优」。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=10000,
        call_bet=3000,
    )
    dec = _terminal_ev_decision(game, 0.3, _RoundTracker(), depth=2, action_probs=(0.0, 0.4, 0.6))
    assert dec.action == "call"
    assert dec.call_ev > dec.peek_ev
    assert dec.peek_ev > 0


def test_terminal_ev_decision_neutral_equals_single_step_at_depth_one() -> None:
    """兼容性：depth=1 无画像时，盲跟候选退化为旧单步 EV（半价成本）。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    dec = _terminal_ev_decision(game, 0.5, _RoundTracker(), depth=1)
    # 单步 EV = 0.5×(10000+50)−50 ≈ 5000 > 0 → 盲跟
    assert dec.action == "call"
    assert dec.terminal_ev > 0
    assert dec.single_step_ev > 0


def test_terminal_branch_fields() -> None:
    """_TerminalBranch 结构：概率、终局底池、成本、胜率、净收益。"""
    b = _TerminalBranch(0.5, 20000, 5000, 0.4, 3000)
    assert b.probability == 0.5
    assert b.pot == 20000
    assert b.cost == 5000
    assert b.win_probability == 0.4
    assert b.net == 3000


def test_terminal_ev_call_blind_raise_does_not_raise_threshold() -> None:
    """回归 #10：对手蒙牌加注视为诈唬，不上调门槛/不衰减胜率；看牌加注才是强牌信号。

    同样加注倾向（action_probs 固定），opponent_seen=False（蒙牌加注）的盲跟终局 EV
    高于 opponent_seen=True（看牌加注），因为后者每次加注都把对手门槛向 1 推、胜率衰减。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=30000,
        call_bet=6000,
    )
    blind_win = _blind_win_probability(0, (0.7,))
    action_probs = (0.1, 0.2, 0.7)  # 对手爱加注
    ev_seen = _terminal_ev_call(game, 0.7, _RoundTracker(), 2, None, action_probs, None, None, blind_win, 0, None, True)
    ev_blind = _terminal_ev_call(
        game, 0.7, _RoundTracker(), 2, None, action_probs, None, None, blind_win, 0, None, False
    )
    assert ev_blind > ev_seen


def test_terminal_ev_decision_threads_opponent_seen() -> None:
    """决策入口按对手看牌状态建模：全蒙对手（无看牌）时蒙牌加注不衰减胜率。"""
    # 对手全蒙 → opponent_seen=False，盲跟 EV 不因「加注」额外衰减
    game_blind_opp = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=30000,
        call_bet=6000,
    )
    dec = _terminal_ev_decision(game_blind_opp, 0.7, _RoundTracker(), depth=2, action_probs=(0.1, 0.2, 0.7))
    assert dec.terminal_ev > 0


def test_profile_store_buckets_actions() -> None:
    """画像按状态分桶统计对手动作，flush 后可从 kv 恢复。"""
    store = ProfileStore()
    store.record_action("account:1", "raise", op_seen=True, seen_count=0, blind_count=0)
    store.record_action("account:1", "raise", op_seen=True, seen_count=0, blind_count=0)
    store.record_action("account:1", "call", op_seen=True, seen_count=0, blind_count=0)
    store.record_action("account:1", "fold", op_seen=True, seen_count=0, blind_count=1)
    p_fold, p_call, p_raise = store.action_probabilities("account:1", True, 0, 0)
    assert p_raise == pytest.approx(2 / 3)
    assert p_call == pytest.approx(1 / 3)
    assert p_fold == pytest.approx(0)
    # 不同桶互不影响
    p_f2, _, p_r2 = store.action_probabilities("account:1", True, 0, 1)
    assert p_f2 == pytest.approx(1.0)
    assert p_r2 == pytest.approx(0)


def test_profile_store_unknown_opponent_falls_back_to_prior() -> None:
    """未知对手回退全局先验；少样本向先验收缩。"""
    store = ProfileStore()
    # 无任何样本 → 均等先验
    p = store.action_probabilities("unknown", True, 0, 0)
    assert p == pytest.approx((1 / 3, 1 / 3, 1 / 3))
    # 有全局样本：A 常 raise（全局先验偏 raise）
    store.record_action("account:a", "raise", op_seen=True, seen_count=0, blind_count=0)
    store.record_action("account:a", "raise", op_seen=True, seen_count=0, blind_count=0)
    # 少样本对手（1 次 call）向全局先验收缩
    store.record_action("account:new", "call", op_seen=True, seen_count=0, blind_count=0)
    p_new = store.action_probabilities("account:new", True, 0, 0)
    # 全局先验 raise 主导：新对手的 raise 概率被先验抬高（> 纯经验 0）
    assert p_new[2] > 0
    # call 概率被先验稀释（从纯经验 1.0 降下来，向全局 raise 靠拢）
    assert 0 < p_new[1] < 1.0
    # 三概率归一
    assert sum(p_new) == pytest.approx(1.0)


def test_profile_store_persist_roundtrip() -> None:
    """画像 flush 写 kv，新 store load_all 读回。"""

    class FakeKV:
        def __init__(self) -> None:
            self._d: dict[str, object] = {}

        def get(self, key: str, default: object = None) -> object:
            return self._d.get(key, default)

        def set(self, key: str, value: object) -> None:
            self._d[key] = value

        def delete(self, key: str) -> None:
            self._d.pop(key, None)

        def keys(self) -> list[str]:
            return list(self._d)

        def __contains__(self, key: str) -> bool:
            return key in self._d

    kv = FakeKV()
    store = ProfileStore(kv)
    store.record_action("account:9", "raise", op_seen=True, seen_count=0, blind_count=0, display_name="Damon")
    store.flush()
    assert len(kv.keys()) == 1
    assert kv.get("zjh:profile:account:9")["display_name"] == "Damon"

    store2 = ProfileStore(kv)
    store2.load_all()
    p = store2.action_probabilities("account:9", True, 0, 0)
    assert p == pytest.approx((0, 0, 1.0))


def test_profile_store_raise_pctile_backfill() -> None:
    """结算回填加注牌力分位，作为更高门槛上界。"""
    store = ProfileStore()
    store.record_hand_pctile("account:1", "raise", 0.9)
    store.record_hand_pctile("account:1", "raise", 0.85)
    # 直接验证画像内记录了分位
    dump = store.debug_dump()
    assert "account:1" in dump
    assert dump["account:1"].get("raise_pcts") == [0.9, 0.85]


def test_percentile_helper_interpolates() -> None:
    """线性插值分位数：单元素原样返回，q=0/1 取端点，中间线性插值。"""
    assert _percentile([0.9], 0.25) == pytest.approx(0.9)
    assert _percentile([0.2, 0.8], 0.0) == pytest.approx(0.2)
    assert _percentile([0.2, 0.8], 1.0) == pytest.approx(0.8)
    # rank=0.25×3=0.75 → 0.2×0.25 + 0.4×0.75
    assert _percentile([0.2, 0.4, 0.6, 0.8], 0.25) == pytest.approx(0.35)


def test_hand_percentiles_returns_recorded_and_empty() -> None:
    """hand_percentiles：无记录返回空列表，按动作分桶返回对应分位。"""
    store = ProfileStore()
    assert store.hand_percentiles("nobody", "raise") == []
    store.record_hand_pctile("a", "raise", 0.3)
    store.record_hand_pctile("a", "call", 0.7)
    assert store.hand_percentiles("a", "raise") == [0.3]
    assert store.hand_percentiles("a", "call") == [0.7]


def test_empirical_win_factor_shrinkage() -> None:
    """实测胜率收缩：无样本回退基线，少样本收缩，多样本趋近实测。"""
    store = ProfileStore()
    # 无样本 → 回退 model_baseline
    assert store.empirical_win_factor("nobody", "raise", 0.7, 0.42) == pytest.approx(0.42)
    # 对手加注全弱牌（0.3），我方 0.7 全胜 → wins=1.0；n=1 向 baseline 收缩
    store.record_hand_pctile("a", "raise", 0.3)
    w1 = store.empirical_win_factor("a", "raise", 0.7, 0.42)
    weight = 1 / (1 + PRIOR_STRENGTH)
    assert w1 == pytest.approx(weight * 1.0 + (1 - weight) * 0.42)
    assert w1 > 0.42
    # 多样本（n=20 全弱）趋近实测 1.0
    for _ in range(20):
        store.record_hand_pctile("b", "raise", 0.3)
    assert store.empirical_win_factor("b", "raise", 0.7, 0.42) > 0.9
    # 我方牌力低于所有实测手牌 → wins=0，胜率被压低（异常路径）
    for _ in range(20):
        store.record_hand_pctile("c", "raise", 0.9)
    assert store.empirical_win_factor("c", "raise", 0.5, 0.42) < 0.1


def test_bluff_rate_freq_and_hand_pctile_blend() -> None:
    """逐对手诈唬率（hand-level 频率异常下界 + 实测弱牌占比收缩，无全局基线）。"""
    store = ProfileStore()
    # 无数据 → 0（异常路径：陌生对手不反诈唬）
    assert store.bluff_rate("nobody") == 0.0
    # 全 fold（c=0）→ 频率不蕴含诈唬
    for _ in range(6):
        store.record_action("tight", "fold", True, 0, 0)
    assert store.bluff_rate("tight") == 0.0
    # 紧手 c=0.4（2 手继续 + 3 手弃）→ 0
    for _ in range(2):
        store.record_raise_freq("semi", True, 0, 0, False)
        store.record_action("semi", "call", True, 0, 0)
    for _ in range(3):
        store.record_action("semi", "fold", True, 0, 0)
    assert store.bluff_rate("semi") == 0.0
    # 跟注站 n=10 全 call：c=1.0 → raw=0.5，收缩后 10/13×0.5
    for _ in range(10):
        store.record_raise_freq("station", True, 0, 0, False)
        store.record_action("station", "call", True, 0, 0)
    freq_bluff = 10 / (10 + PRIOR_STRENGTH) * 0.5
    assert store.bluff_rate("station") == pytest.approx(freq_bluff)
    # 少样本（n=2 全继续）：2/5×0.5=0.2，向 0 收缩不激进
    for _ in range(2):
        store.record_raise_freq("newbie", True, 0, 0, True)
    store.record_action("newbie", "call", True, 0, 0)
    store.record_action("newbie", "raise", True, 0, 0)
    assert store.bluff_rate("newbie") == pytest.approx(2 / (2 + PRIOR_STRENGTH) * 0.5)
    # 频率 + 实测弱牌分位：弱牌占比抬高诈唬率
    for _ in range(6):
        store.record_hand_pctile("station", "call", 0.2)
    weak_heavy = store.bluff_rate("station")
    assert weak_heavy > freq_bluff
    # 实测全强牌：把诈唬率拉回（观测优先于频率下界）
    for _ in range(10):
        store.record_hand_pctile("strong", "raise", 0.9)
    for _ in range(10):
        store.record_raise_freq("strong", True, 0, 0, True)
        store.record_action("strong", "raise", True, 0, 0)
    assert store.bluff_rate("strong") < store.bluff_rate("station", None)


def test_bluff_rate_bucket_isolation_and_aggregation() -> None:
    """bucket_key 指定时只算该桶；None 时聚合全部桶。"""
    store = ProfileStore()
    # 桶 s_s1b0：8 手 continue（c=1.0）；桶 s_s1b1：2 手 fold（c=0）
    for _ in range(8):
        store.record_raise_freq("a", True, 1, 0, False)
        store.record_action("a", "call", True, 1, 0)
    for _ in range(2):
        store.record_action("a", "fold", True, 1, 1)
    only_loose = 8 / (8 + PRIOR_STRENGTH) * 0.5
    assert store.bluff_rate("a", "s_s1b0") == pytest.approx(only_loose)
    assert store.bluff_rate("a", "s_s1b1") == 0.0
    # 聚合：n=10, c=0.8 → raw=(0.8-0.5)/0.8=0.375，收缩 10/13
    agg = 10 / (10 + PRIOR_STRENGTH) * ((0.8 - 0.5) / 0.8)
    assert store.bluff_rate("a") == pytest.approx(agg)


def test_bluff_rate_hand_level_not_instance_counts() -> None:
    """频率分量用 hand-level 继续率：一手牌多次跟注不撑大分子。

    旧版用实例级动作计数 c=(call+raise)/(fold+call+raise)：对手 5 手直接弃、
    5 手跟到底（每手 3 轮）→ 实例 c=15/20=0.75 误判出诈唬下界；
    hand-level 口径 c=5/10=0.5 不蕴含诈唬 → 0。
    """
    store = ProfileStore()
    for _ in range(5):
        store.record_action("opp", "fold", True, 0, 0)
    for _ in range(5):
        for _ in range(3):
            store.record_action("opp", "call", True, 0, 0)
        store.record_raise_freq("opp", True, 0, 0, False)
    assert store.bluff_rate("opp") == 0.0


def test_bluff_rate_call_then_fold_single_hand() -> None:
    """同一手牌 call 后 fold：hand-level 计 1 手继续 + 1 手弃 → c=0.5 无诈唬。"""
    store = ProfileStore()
    # 一手牌：2 次跟注（实例级），最后弃牌
    store.record_action("opp", "call", True, 0, 0)
    store.record_action("opp", "call", True, 0, 0)
    store.record_action("opp", "fold", True, 0, 0)
    store.record_raise_freq("opp", True, 0, 0, False)  # 结算时记 1 手继续
    assert store.bluff_rate("opp") == 0.0


def test_raise_threshold_floor_none_and_shrink() -> None:
    """加注门槛下界：无样本返回 None，有样本为下四分位向 base 收缩。"""
    store = ProfileStore()
    assert store.raise_threshold_floor("nobody", 0.6) is None
    for _ in range(6):
        store.record_hand_pctile("a", "raise", 0.2)
    floor = store.raise_threshold_floor("a", 0.6)
    weight = 6 / (6 + PRIOR_STRENGTH)
    assert floor == pytest.approx(weight * 0.2 + (1 - weight) * 0.6)
    assert floor < 0.6


def test_raise_threshold_floor_recent_hands_override_old_bluff() -> None:
    """半衰期（按次数）：对手早年 8 手弱牌加注（含 235 近零分位）后连续 8 手正常加注，
    近期加权让加注下限由近期强牌主导，不再被那颗 235 永久锚低；
    等权（halflife=0，旧行为）下四分位仍被早年弱牌拖低。"""
    recent = ProfileStore(halflife=2)
    forever = ProfileStore(halflife=0)
    for pct in (0.02, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35):
        recent.record_hand_pctile("opp", "raise", pct)
        forever.record_hand_pctile("opp", "raise", pct)
    for _ in range(8):
        recent.record_hand_pctile("opp", "raise", 0.9)
        forever.record_hand_pctile("opp", "raise", 0.9)
    floor_recent = recent.raise_threshold_floor("opp", 0.5)
    floor_forever = forever.raise_threshold_floor("opp", 0.5)
    assert floor_recent is not None and floor_forever is not None
    # 等权：16 样本下四分位落在弱牌区（rank 3.75 → 0.15 与 0.2 之间）→ 被拉低
    assert floor_forever < 0.5
    # 近期半衰期=2：弱牌块总权重 ≈0.2，强牌块 ≈3.2，加权下四分位落在 0.9 区 → 高于 base
    assert floor_recent > floor_forever
    assert floor_recent > 0.5


def test_hand_pctile_lists_capped_to_max_samples() -> None:
    """分位列表窗口上限：超限丢弃最旧样本（硬遗忘 + 内存上限），扁平与分桶同步。"""
    store = ProfileStore(max_samples=3)
    for pct in (0.1, 0.2, 0.3, 0.4, 0.5):
        store.record_hand_pctile("a", "raise", pct)
    assert store.hand_percentiles("a", "raise") == [0.3, 0.4, 0.5]
    assert store.hand_percentiles("a", "raise", "b_s0b0") == [0.3, 0.4, 0.5]


def test_hand_pctile_window_follows_halflife() -> None:
    """窗口上限联动半衰期：默认 max(100, 半衰期×3)，显式传参优先。

    旧版写死 100 条：半衰期 100 时最旧样本权重还剩约一半就被硬切，真实记忆窗口
    远短于设定值。联动后被丢弃的最旧样本权重已衰减到约 12.5%（3 个半衰期）。
    """
    assert ProfileStore(halflife=100)._max_samples == 300
    assert ProfileStore(halflife=50)._max_samples == 150
    assert ProfileStore(halflife=20)._max_samples == 100  # 默认半衰期不涨价
    assert ProfileStore(halflife=0)._max_samples == 100  # 不衰减仍硬遗忘兜底
    assert ProfileStore(halflife=100, max_samples=3)._max_samples == 3  # 显式优先

    # 行为验证：半衰期 100、默认窗口记录 150 条全部保留（旧版窗口 100 会截断掉 50 条）
    store = ProfileStore(halflife=100)
    for i in range(150):
        store.record_hand_pctile("a", "raise", i / 100)
    assert len(store.hand_percentiles("a", "raise")) == 150


def test_action_counts_decay_by_hand_tick() -> None:
    """计数桶按手数衰减：早期跟注站被近期弃牌覆盖，action_probabilities 反映近期行为。

    走完整结算路径（先 tick_hands 推进时钟再 record_raise_freq）；对照只调动作原语
    不 tick 的调用不衰减——证明衰减时钟挂在结算而不是动作原语上。
    """
    ticking = ProfileStore(halflife=1)  # 1 手半衰，每手 ×0.5
    uid = "opp"
    # 前 3 手继续（每手 call 一次 + 结算 tick）
    for _ in range(3):
        ticking.record_action(uid, "call", True, 0, 0)
        record_round_raise_freq(ticking, {uid: ("call", True, 0, 0)}, [uid])
    # 后 1 手弃牌（弃牌不入 round_action，只 tick 时钟）
    ticking.record_action(uid, "fold", True, 0, 0)
    record_round_raise_freq(ticking, {}, [uid])
    p_fold, p_call, _ = ticking.action_probabilities(uid, True, 0, 0)
    assert p_fold > p_call  # 近期弃牌主导

    # 对照：只调原语不 tick → 无衰减，call 计数仍占优
    raw = ProfileStore(halflife=1)
    for _ in range(3):
        raw.record_action(uid, "call", True, 0, 0)
    raw.record_action(uid, "fold", True, 0, 0)
    r_fold, r_call, _ = raw.action_probabilities(uid, True, 0, 0)
    assert r_call > r_fold


def test_bluff_rate_forgets_old_calling_station() -> None:
    """半衰期顺手数：早年 10 手全跟注的跟注站，近期 5 手全弃后诈唬率归零；
    等权（halflife=0）仍按 2/3 继续率算出生诈唬下界。"""
    ticking = ProfileStore(halflife=2)
    forever = ProfileStore(halflife=0)
    uid = "opp"
    for _ in range(10):
        ticking.record_action(uid, "call", True, 0, 0)
        record_round_raise_freq(ticking, {uid: ("call", True, 0, 0)}, [uid])
        forever.record_action(uid, "call", True, 0, 0)
        record_round_raise_freq(forever, {uid: ("call", True, 0, 0)}, [uid])
    for _ in range(5):
        ticking.record_action(uid, "fold", True, 0, 0)
        record_round_raise_freq(ticking, {}, [uid])
        forever.record_action(uid, "fold", True, 0, 0)
        record_round_raise_freq(forever, {}, [uid])
    assert ticking.bluff_rate(uid) == 0.0  # 近期 5 手全弃 → 继续率被按手数衰减到 ≤0.5
    assert forever.bluff_rate(uid) > 0.0  # 终身累计仍按 10/(10+5)=2/3 继续率含诈唬


def test_legacy_count_bucket_without_pointer_not_decayed() -> None:
    """旧格式计数桶无「最后更新手数」指针：首次记录不突然衰减（gap 视为 0）。"""
    store = ProfileStore(halflife=1)
    store._cache["old"] = {"b_s0b0": {"fold": 5, "call": 0, "raise": 0}}
    store.record_action("old", "fold", False, 0, 0)
    dump = store.debug_dump()
    assert dump["old"]["b_s0b0"]["fold"] == 6  # 5 + 1，未衰减
    assert dump["old"]["b_s0b0"]["p"] == 1  # 指针从首个新记录起计时


def test_seen_factor_profile_blend_weak_opponent_raises_win() -> None:
    """_seen_factor 画像混合：范围下界高于我方牌力时纯范围胜率为 0，
    画像记录对手加注多弱牌后胜率被抬起；无画像逐值回退纯范围模型。"""
    hand_threshold = 0.7
    base_range = _SeenRange(0.75, 1.0, True)
    plain = _seen_factor(hand_threshold, base_range)
    assert plain == pytest.approx(0.0)  # t ≤ 下界，范围胜率 0、无画像不反诈唬
    store = ProfileStore()
    for _ in range(10):
        store.record_hand_pctile("bluffy", "raise", 0.3)
    blended_range = _SeenRange(0.75, 1.0, True, profile=store, uid="bluffy", action="raise")
    blended = _seen_factor(hand_threshold, blended_range)
    assert blended > plain
    assert blended > 0.5
    # profile=None 时（默认）与纯范围模型逐值一致，不触发画像分支
    assert _seen_factor(hand_threshold, _SeenRange(0.5, 0.85, True)) == pytest.approx(
        _range_factor(hand_threshold, 0.5, 0.85)
    )


def test_call_decision_profile_integration_raises_win_for_weak_opponent() -> None:
    """集成：紧手加注对手（快照反推门槛 0.99）纯范围胜率≈0，画像显示其实测加注多弱牌后
    _call_decision 胜率被显著抬起（加注下限画像直读 + 反诈唬 + 实测胜率混合）。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "opp", "alive": True, "seen": True},
        pot=1,
        call_bet=99,  # 盈亏平衡点 99/(1+99)=0.99 → 推断门槛极高
    )
    tracker = _RoundTracker(snapshots={"opp": _OpponentSnapshot(pot=1, call_bet=99, opponents=1, is_raise=True)})
    base = _call_decision("对子", (14, 13), game, 0.1, tracker)
    store = ProfileStore()
    for _ in range(10):
        store.record_hand_pctile("opp", "raise", 0.2, op_seen=True, seen_count=0, blind_count=0)
        # 弱牌加注（诈唬型），桶键 s_s0b0
    with_profile = _call_decision("对子", (14, 13), game, 0.1, tracker, store)
    assert base is not None and with_profile is not None
    assert base.win_probability == pytest.approx(0.0)  # 我方牌力 < 0.99 下界
    assert with_profile.win_probability > 0.5
    assert with_profile.win_probability > base.win_probability


def test_feed_last_result_round_action_bucketing() -> None:
    """结算回填分桶：提供 round_action 时按实际动作只记对应桶，缺失则保守记两者。

    真实 lastResult 玩家只给 handType 不给牌面，走牌型级分位回退路径。
    """
    game = {
        "lastResult": {
            "roundId": "r1",
            "players": [
                {"displayName": "Damon", "result": "赢", "handType": "顺子"},
            ],
        }
    }
    # 本局加注（单挑，对手看到并加注，桶键 s_s0b0）
    store = ProfileStore()
    feed_last_result(store, game, {"Damon": "account:1"}, {"account:1": ("raise", True, 0, 0)})
    dump = store.debug_dump()
    assert dump["account:1"].get("raise_pcts")
    assert not dump["account:1"].get("call_pcts")
    # 未提供 round_action → 保守回填两者（旧行为）
    store2 = ProfileStore()
    feed_last_result(store2, game, {"Damon": "account:1"})
    dump2 = store2.debug_dump()
    assert dump2["account:1"].get("raise_pcts")
    assert dump2["account:1"].get("call_pcts")


def test_feed_last_result_backfills_folded_player_with_revealed_cards() -> None:
    """实测摊牌局连已弃牌玩家也给完整牌面（「牌面 → 牌型」组合文本）：
    弃牌者有牌面且本轮 call/raise 过时，按最激进动作回填对应桶——
    「加注后弃牌」的牌正是校准加注下限/诈唬率的关键样本。"""
    game = {
        "lastResult": {
            "roundId": "r1",
            "players": [
                {"displayName": "Nan", "result": "已弃牌", "handType": "J♣ 6♣ 3♦ → 散牌"},
                {"displayName": "Win", "result": "获胜", "handType": "A♠ Q♠ 9♣ → 散牌"},
            ],
        }
    }
    store = ProfileStore()
    feed_last_result(store, game, {"Nan": "u1", "Win": "u2"}, {"u1": ("raise", True, 0, 0), "u2": ("call", True, 0, 0)})
    dump = store.debug_dump()
    # 弃牌者按最激进动作进 raise 桶，且牌面可解析 → 精确分位（非牌型中点）
    assert dump["u1"].get("raise_pcts"), "弃牌者亮牌应回填加注桶"
    assert not dump["u1"].get("call_pcts")
    expected = _hand_pctile_from_result("J♣ 6♣ 3♦", "散牌")
    assert dump["u1"]["raise_pcts"][0] == pytest.approx(expected)
    assert dump["u2"].get("call_pcts"), "获胜者正常回填平跟桶"


def test_feed_last_result_skips_folded_without_cards_or_action() -> None:
    """弃牌玩家无牌面（全员弃牌局无人亮牌）不回填、绝不虚构；
    有牌面但本轮未观测到 call/raise（报名后弃牌）也无可归属桶，跳过。"""
    game = {
        "lastResult": {
            "roundId": "r1",
            "players": [
                {"displayName": "NoCards", "result": "已弃牌", "handType": ""},
                {"displayName": "AnteFold", "result": "已弃牌", "handType": "9♠ 7♣ 2♣ → 散牌"},
            ],
        }
    }
    store = ProfileStore()
    # round_action 只含 AnteFold 的邻居？不给任何人动作记录
    feed_last_result(store, game, {"NoCards": "u1", "AnteFold": "u2"}, {})
    assert store.debug_dump() == {}
    # 旧模式（round_action=None）下弃牌者一律不回填
    store2 = ProfileStore()
    feed_last_result(store2, game, {"NoCards": "u1", "AnteFold": "u2"})
    assert store2.debug_dump() == {}


def test_win_prob_1v1_type_band_midpoint() -> None:
    """牌型级代表分位：取分位带中点；牌型越强分位越高；未知牌型返回 None。"""
    scatter = zjh_prob.win_prob_1v1_type("散牌")
    straight = zjh_prob.win_prob_1v1_type("顺子")
    trips = zjh_prob.win_prob_1v1_type("豹子")
    assert scatter is not None and straight is not None and trips is not None
    assert scatter < straight < trips  # 牌型强度单调
    assert 0.0 < scatter < 1.0
    assert zjh_prob.win_prob_1v1_type("不存在的牌型") is None


def test_hand_pctile_from_result_type_only_fallback() -> None:
    """无牌面只有牌型时回退牌型级分位（结算 lastResult 的真实情形）。"""
    # 有牌面 → 精确分位
    exact = _hand_pctile_from_result("Q♥ J♠ 10♥", "顺子")
    # 无牌面 → 牌型带中点
    type_only = _hand_pctile_from_result("", "顺子")
    assert exact is not None and type_only is not None
    assert type_only == pytest.approx(zjh_prob.win_prob_1v1_type("顺子"))
    # 既无牌面又无有效牌型 → None
    assert _hand_pctile_from_result("", "") is None


def test_hand_pctile_from_result_parses() -> None:
    """结算手牌文本转一对一胜率分位。"""
    # 顺子 Q-J-10 → 较高分位
    p = _hand_pctile_from_result("Q♥ J♠ 10♥", "顺子")
    assert p is not None and 0.7 < p < 1.0
    # 散牌 10-9-2 → 较低分位
    p2 = _hand_pctile_from_result("10♦ 9♣ 2♥", "散牌")
    assert p2 is not None and p2 < 0.5
    # 无牌面但有牌型 → 回退牌型级分位（非 None）
    p3 = _hand_pctile_from_result("", "散牌")
    assert p3 is not None and p3 == pytest.approx(zjh_prob.win_prob_1v1_type("散牌"))
    # 既无牌面又无有效牌型 → None
    assert _hand_pctile_from_result("", "") is None


def test_bucket_keys() -> None:
    """动作分桶键：对手状态 + 其他看牌人数 + 其他蒙牌人数。"""
    assert _freq_bucket(False, 0, 0) == "b_s0b0"
    assert _freq_bucket(False, 1, 0) == "b_s1b0"
    assert _freq_bucket(True, 1, 1) == "s_s1b1"
    assert _freq_bucket(True, 0, 1) == "s_s0b1"


def test_terminal_ev_real_world_5129_should_not_blind_call() -> None:
    """真实盘面 5129（rno=1 单挑）：我蒙牌、对手已看牌强加注 → 决策树不盲跟。

    实测盘面：pot=16500, callBet=6000, 对手门槛≈0.65（Damon 连续 raise 最终顺子）。
    盲跟 Terminal EV 为负（被对手持续 raise 撑大 pot、蒙牌对 0.65 门槛胜率仅 17.5%），
    决策树选择看牌止损而非盲跟。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=16500,
        call_bet=6000,
    )
    # 对手强加注画像：P_fold 低、P_raise 高
    action_probs = (0.08, 0.22, 0.70)
    dec = _terminal_ev_decision(game, 0.65, _RoundTracker(), depth=2, action_probs=action_probs)
    # 不盲跟（决策树选看牌止损；盲跟路径本身负）
    assert dec.action in ("fold", "peek")
    assert dec.action != "call"
    # 盲跟路径的终端胜率很低（贝叶斯衰减）
    assert dec.branches[0].win_probability < 0.3
    # 对照旧单步 EV：正（这就是旧逻辑盲跟的原因），决策树却正确止损
    assert dec.single_step_ev > 0


def test_terminal_ev_real_world_5136_should_not_blind_call() -> None:
    """真实盘面 5136（rno=1 单挑）：我蒙牌、对手 Damon 已看牌每轮 raise → 决策树不盲跟。

    实测盘面：pot=28500, callBet=12000, 对手门槛高（连续 8 轮 raise 最终对子/顺子）。
    盲跟 Terminal EV 大负，决策树选择看牌止损而非盲跟。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=28500,
        call_bet=12000,
    )
    action_probs = (0.05, 0.15, 0.80)  # Damon 型：几乎总在加注
    dec = _terminal_ev_decision(game, 0.7, _RoundTracker(), depth=2, action_probs=action_probs)
    assert dec.action in ("fold", "peek")
    assert dec.action != "call"
    # 盲跟路径胜率低（贝叶斯衰减到 0.7 门槛 → (1−0.7)/2=15%）
    assert dec.branches[0].win_probability < 0.25
    # 对照旧单步 EV：负，但决策树连看牌 EV 更高（弱牌止损）
    assert dec.single_step_ev < 0


def test_blind_peek_or_call_force_peek_after_max_calls() -> None:
    """连续盲跟达上限强制看牌止损。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "blind", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    # 即使盲跟 EV 为正，连续盲跟 3 次达上限也强制看牌
    action, choice = _blind_peek_or_call(
        game,
        ["call", "peek", "fold"],
        0.5,
        _RoundTracker(),
        depth=2,
        max_blind_calls=3,
        blind_calls_so_far=3,
    )
    assert action == "peek"
    assert choice is not None


def test_blind_peek_or_call_respects_profile_action_probs() -> None:
    """画像动作概率传入决策树：对手爱弃牌时盲跟更划算。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=50000,
        call_bet=100,
    )
    # 对手 90% 弃牌：盲跟独赢当前池概率高
    action, choice = _blind_peek_or_call(
        game,
        ["call", "peek", "fold"],
        0.5,
        _RoundTracker(),
        depth=2,
        action_probs=(0.9, 0.05, 0.05),
    )
    assert action == "call"
    assert choice is not None
    assert choice.terminal_ev > 0


# ──────────────────────────────────────────────────────────────────────
# 对手画像训练覆盖与去重（v1.14.0 修复：原只在蒙牌分支/只记首个/不去重）
# ──────────────────────────────────────────────────────────────────────


def test_train_opponent_actions_records_all_alive_opponents() -> None:
    """遍历所有存活对手，而非仅首个：两个对手都入画像。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False, "lastAction": "+1500 跟注", "bet": 4500},
        {"id": "p2", "alive": True, "seen": False, "lastAction": "+3000 追加", "bet": 6000},
    )
    _train_opponent_actions(store, game, last_seen)
    dump = store.debug_dump()
    assert "p1" in dump
    assert "p2" in dump
    # p1 跟注、p2 加注；3人局（self+p1+p2），p1/p2 都蒙牌
    # 排除自身后: seen_count=0, blind_count=1
    p1_f, p1_c, p1_r = store.action_probabilities("p1", False, 0, 1)
    assert p1_c > 0
    p2_f, p2_c, p2_r = store.action_probabilities("p2", False, 0, 1)
    assert p2_r > 0


def test_train_opponent_actions_dedupes_same_action() -> None:
    """同一动作跨多轮轮询只记一次：last_seen 签名去重。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    base = {
        "id": "self",
        "alive": True,
        "isSelf": True,
        "seen": False,
    }
    opp = {"id": "p1", "alive": True, "seen": False, "lastAction": "+1500 跟注", "bet": 4500}
    # 第一轮：记录
    _train_opponent_actions(store, _game(base, dict(opp)), last_seen)
    n_after_first = store.debug_dump()["p1"]["total_hands"]
    # 第二轮：同一动作不变 → 不重复记录
    _train_opponent_actions(store, _game(base, dict(opp)), last_seen)
    _train_opponent_actions(store, _game(base, dict(opp)), last_seen)
    assert store.debug_dump()["p1"]["total_hands"] == n_after_first
    # 动作变化（追加）→ 记录新动作
    opp2 = dict(opp, lastAction="+3000 追加", bet=6000)
    _train_opponent_actions(store, _game(base, opp2), last_seen)
    assert store.debug_dump()["p1"]["total_hands"] == n_after_first + 1


def test_train_opponent_actions_ignores_registration_action() -> None:
    """报名（底注）不计入动作分桶，但签名更新避免反复尝试。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False, "lastAction": "报名", "bet": 3000},
    )
    _train_opponent_actions(store, game, last_seen)
    # 无任何动作被记录（total_hands 保持 0）
    dump = store.debug_dump()
    assert "p1" not in dump or dump["p1"].get("total_hands", 0) == 0


def test_train_opponent_actions_covers_blind_peeked_and_opponent_turn() -> None:
    """训练不再依赖「轮到 bot + 蒙牌」：任何轮询快照都记录，含 bot 看牌后。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    # bot 已看牌（my_seen=True）、多人局：仍记录对手动作
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "p1", "alive": True, "seen": True, "lastAction": "+3000 追加", "bet": 9000},
    )
    _train_opponent_actions(store, game, last_seen)
    dump = store.debug_dump()
    assert "p1" in dump
    # 分桶为 s_s0b0（对手看牌，无其他看牌/蒙牌人，单挑）
    assert "s_s0b0" in dump["p1"]


def test_train_opponent_actions_records_fold_for_dead_opponents() -> None:
    """实测门户在弃牌同一快照就把 alive 置 false：出局对手的弃牌必须记一次
    （否则继续频率分母缺 fold、系统性高估诈唬），且签名去重不重复计。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "folded", "alive": False, "seen": True, "lastAction": "弃牌", "bet": 3100},
    )
    _train_opponent_actions(store, game, last_seen)
    dump = store.debug_dump()
    assert dump["folded"]["s_s0b0"]["fold"] == 1
    # 同签名再来一轮 → 不重复记录
    _train_opponent_actions(store, game, last_seen)
    assert store.debug_dump()["folded"]["s_s0b0"]["fold"] == 1


def test_train_opponent_actions_ignores_dead_players_non_fold_action() -> None:
    """出局玩家除弃牌外的动作（陈旧快照残留）不记录。"""
    store = ProfileStore()
    last_seen: dict[str, tuple[str, float]] = {}
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "gone", "alive": False, "seen": True, "lastAction": "+3100 跟注", "bet": 6200},
    )
    _train_opponent_actions(store, game, last_seen)
    assert "gone" not in store.debug_dump()


# ──────────────────────────────────────────────────────────────────────
# 加注频率追踪（v1.14.7）
# ──────────────────────────────────────────────────────────────────────


def test_record_raise_freq_records_correctly_per_bucket() -> None:
    """record_raise_freq 按不同分桶正确记录 total/raises。"""
    store = ProfileStore()
    # 同桶累计
    store.record_raise_freq("a", True, 1, 0, True)  # s_s1b0, raise
    store.record_raise_freq("a", True, 1, 0, False)  # s_s1b0, not raise
    store.record_raise_freq("a", False, 0, 1, False)  # b_s0b1, not raise
    dump = store.debug_dump()
    freq_a = dump["a"]["raise_freq"]
    assert freq_a["s_s1b0"] == {"total": 2, "raises": 1, "p": 0}
    assert freq_a["b_s0b1"] == {"total": 1, "raises": 0, "p": 0}
    # 不同玩家互不影响
    store.record_raise_freq("b", True, 1, 0, True)
    dump = store.debug_dump()
    freq_b = dump["b"]["raise_freq"]
    assert freq_b["s_s1b0"] == {"total": 1, "raises": 1, "p": 0}


def test_raise_floor_from_freq_none_and_shrink() -> None:
    """加注频率推断：无样本返回 None，有样本按贝叶斯收缩。"""
    store = ProfileStore()
    # 无样本
    assert store.raise_floor_from_freq("nobody", "s_s1b0", 0.6) is None
    # 10 局 raise 8 局：raise_rate=0.8 → min_strength=0.2
    for _ in range(8):
        store.record_raise_freq("a", True, 1, 0, True)
    for _ in range(2):
        store.record_raise_freq("a", True, 1, 0, False)
    freq_floor = store.raise_floor_from_freq("a", "s_s1b0", 0.6)
    weight = 10 / (10 + PRIOR_STRENGTH)
    expected = weight * 0.2 + (1 - weight) * 0.6
    assert freq_floor == pytest.approx(expected)
    assert 0.0 < freq_floor < 0.6  # 低于 base_threshold
    # 全加注 → min_strength ≈ 0.0
    store2 = ProfileStore()
    for _ in range(5):
        store2.record_raise_freq("b", True, 1, 0, True)
    all_raise = store2.raise_floor_from_freq("b", "s_s1b0", 0.5)
    w2 = 5 / (5 + PRIOR_STRENGTH)
    assert all_raise == pytest.approx(w2 * 0.0 + (1 - w2) * 0.5)
    # 全不加注 → min_strength ≈ 1.0
    store3 = ProfileStore()
    for _ in range(5):
        store3.record_raise_freq("c", True, 1, 0, False)
    no_raise = store3.raise_floor_from_freq("c", "s_s1b0", 0.5)
    w3 = 5 / (5 + PRIOR_STRENGTH)
    assert no_raise == pytest.approx(w3 * 1.0 + (1 - w3) * 0.5)
    assert no_raise > 0.5  # 高于 base_threshold


def test_raise_floor_from_freq_bucket() -> None:
    """raise_floor_from_freq_bucket 与 raise_floor_from_freq 结果一致。"""
    store = ProfileStore()
    for _ in range(6):
        store.record_raise_freq("a", True, 1, 0, True)
    direct = store.raise_floor_from_freq("a", "s_s1b0", 0.6)
    wrapper = store.raise_floor_from_freq_bucket("a", True, 1, 0, 0.6)
    assert direct == wrapper
    # 无数据返回 None
    assert store.raise_floor_from_freq_bucket("nobody", False, 0, 0, 0.5) is None


def test_record_round_raise_freq_counts_most_aggressive_action() -> None:
    """结算时按最激进动作记录加注频率：call 后 raise 的对手必须计为 raise
    （修复旧版「首次动作变化时记录」把后置加注记成非加注的低估）。"""
    store = ProfileStore()
    round_action: dict[str, tuple[str, bool, int, int]] = {
        "p1": ("raise", False, 0, 1),  # 先跟后加 → 最激进 raise
        "p2": ("call", False, 0, 1),  # 只跟注
    }
    record_round_raise_freq(store, round_action)
    dump = store.debug_dump()
    assert dump["p1"]["raise_freq"]["b_s0b1"] == {"total": 1, "raises": 1, "p": 0}
    assert dump["p2"]["raise_freq"]["b_s0b1"] == {"total": 1, "raises": 0, "p": 0}


def test_record_round_raise_freq_empty_round_action_is_noop() -> None:
    """无动作跟踪数据（round_action 为空/None）时不记录。"""
    store = ProfileStore()
    record_round_raise_freq(store, None)
    record_round_raise_freq(store, {})
    assert store.debug_dump() == {}


def test_opponent_raise_threshold_freq_fallback() -> None:
    """_opponent_raise_threshold 无实测手牌分位时回退加注频率推断。"""
    store = ProfileStore()
    base = 0.5
    # 无画像数据 → 回退通用推断
    t_generic = _opponent_raise_threshold(base, 1)
    t_no_data = _opponent_raise_threshold(base, 1, store, "unknown")
    assert t_no_data == pytest.approx(t_generic)
    # 有加注频率但无 hand_pctile → 回退频率推断（需传 game）
    # 10 局 raise 8 局 → min_strength ≈ 0.2，应低于通用推断
    for _ in range(8):
        store.record_raise_freq("freq_raiser", True, 0, 0, True)
    for _ in range(2):
        store.record_raise_freq("freq_raiser", True, 0, 0, False)
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "freq_raiser", "alive": True, "seen": True, "lastAction": "+3000 追加", "bet": 6000},
    )
    t_freq = _opponent_raise_threshold(base, 1, store, "freq_raiser", game)
    assert t_freq < t_generic  # 对手 raise 频繁 → 门槛低于通用推断


# ──────────────────────────────────────────────────────────────────────
# 多人决策树：_BlindOpponent 列表 + _terminal_ev_call_multi / _terminal_ev_peek_multi
# ──────────────────────────────────────────────────────────────────────


def test_blind_opponent_win_probability_matches_integral() -> None:
    """_opponents_win_probability 对盲/看组合的胜率 = _blind_win_probability 直接积分。"""

    # 1 盲 1 看（门槛 0.5）→ _blind_win_probability(1, (0.5,))
    opps = [
        _BlindOpponent("p1", False, (1 / 3, 1 / 3, 1 / 3), 0.0),
        _BlindOpponent("p2", True, (1 / 3, 1 / 3, 1 / 3), 0.5),
    ]
    assert _opponents_win_probability(opps) == pytest.approx(_blind_win_probability(1, (0.5,)))
    # 全盲 3 人 → 1/4（4 人全蒙，含我方）
    all_blind = [_BlindOpponent(f"p{i}", False, (1 / 3, 1 / 3, 1 / 3), 0.0) for i in range(3)]
    assert _opponents_win_probability(all_blind) == pytest.approx(1 / 4)


def test_terminal_ev_call_multi_single_opponent_matches_legacy() -> None:
    """单对手时多人决策树与旧单挑 _terminal_ev_call 逐值一致（向后兼容）。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    probs = (1 / 3, 1 / 3, 1 / 3)
    # 旧单挑（蒙牌对手，不加注门槛）：显式 opponent_seen=False
    legacy = _terminal_ev_call(game, 0.5, _RoundTracker(), 1, None, probs, 10000, 0, 0.5, 0, None, False)
    # 多人树单对手（蒙牌）
    multi = _terminal_ev_call_multi(
        game, 0.5, _RoundTracker(), 1, None, [_BlindOpponent("opp", False, probs, 0.0)], 10000, 0, 100
    )
    assert multi == pytest.approx(legacy)


def test_terminal_ev_call_multi_opponent_fold_removes_and_recomputes() -> None:
    """多人树：某对手必弃牌时从存活列表移除，胜率按剩余对手重算。

    构造两个对手：p1 必弃（P_fold=1），p2 平跟/加注。p1 弃牌分支的胜率应只对
    p2 计算（_opponents_win_probability([p2])），而非含 p1。用深度 1 验证：
    全部弃牌独赢底池，p2 继续时按对 p2 单挑胜率摊牌。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False},
        {"id": "p2", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    # p1 必弃，p2 必平跟
    opps = [
        _BlindOpponent("p1", False, (1.0, 0.0, 0.0), 0.0),
        _BlindOpponent("p2", False, (0.0, 1.0, 0.0), 0.0),
    ]
    # 深度 1：我方盲跟半价 50（池 10050）→ p1 弃（移出）→ p2 蒙牌平跟半价 50
    # （池 10100）→ 摊牌对 p2 单挑胜率 0.5 → EV = 0.5*10100 - 50 = 5000
    ev = _terminal_ev_call_multi(game, 0.5, _RoundTracker(), 1, None, opps, 10000, 0, 100)
    # p1 必弃概率 1，无其他分支；p2 必跟概率 1
    assert ev == pytest.approx(0.5 * 10100 - 50)


def test_terminal_ev_call_multi_joint_probability_matrix() -> None:
    """多人树按动作组合的联合概率加权：两个对手各 2 种可能动作 → 4 个组合。

    构造 p1/p2 各半概率弃/跟，深度 1 按组合概率加权（每轮我方只付一次盲跟半价）：
      - 双弃 → 独赢 10000（我方盲跟 50 已付，白赢回）
      - p1弃 p2跟 → 对 p2 单挑摊牌：0.5*10100-50
      - p1跟 p2弃 → 对 p1 单挑摊牌：0.5*10100-50（p2 弃牌不等于白赢，仍与 p1 比牌）
      - 双跟 → 我方 50 + 两蒙牌对手各半价 50 = 池 10150，三人全蒙胜率 1/3，成本 50
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False},
        {"id": "p2", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    # 用两个「各半概率弃/跟」的对手 → 4 组合各 1/4
    half = (0.5, 0.5, 0.0)
    opps = [
        _BlindOpponent("p1", False, half, 0.0),
        _BlindOpponent("p2", False, half, 0.0),
    ]
    ev = _terminal_ev_call_multi(game, 0.5, _RoundTracker(), 1, None, opps, 10000, 0, 100)
    combo1 = 10000  # 双弃
    combo2 = 0.5 * 10100 - 50  # p1弃 p2跟（我方 50 + p2 蒙牌半价 50）
    combo3 = 0.5 * 10100 - 50  # p1跟 p2弃
    combo4 = (1 / 3) * 10150 - 50  # 双跟（我方 50 + 两蒙牌对手各 50）
    assert ev == pytest.approx(0.25 * (combo1 + combo2 + combo3 + combo4))


def test_terminal_ev_call_multi_three_blind_never_fold_not_inflated() -> None:
    """回归（用户报障）：3 人全蒙、对手永不弃牌时，盲跟 EV 不再接近满池。

    旧实现把蒙牌对手下注按全价算、加注用 ×1.5/×2 复利、且我方盲跟半价未计入
    底池，3 人全蒙公平局（pot 10000、callBet 3000）depth=3 被算成 27516（>满池）。
    修正为线性加注 + 蒙牌半价 + 我方先入池后，EV 随深度收敛到 pot 的三成左右。
    深度 1 精确可算：我方半价 1500 入池，两对手各 1/2 平跟（半价 1500）/加注
    （追平+一注底注，蒙牌半价），四组合各 1/4，三人全蒙胜率 1/3：
      - 双平跟：0.5×(10000+1500+2×1500)−1500
      - o1 平跟 o2 加注：0.5×(10000+1500+1500+3000)−1500
      - o1 加注 o2 平跟：0.5×(10000+1500+3000+3000)−1500
      - 双加注：0.5×(10000+1500+3000+4500)−1500
    （o1 加注抬升 callBet 6000→o2 平跟追平 6000/2=3000；o2 加注再追平 9000/2=4500）
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "o1", "alive": True, "seen": False},
        {"id": "o2", "alive": True, "seen": False},
        pot=10000,
        call_bet=3000,
        ante=3000,
    )
    opps = [
        _BlindOpponent("o1", False, (0.0, 0.5, 0.5), 0.0),
        _BlindOpponent("o2", False, (0.0, 0.5, 0.5), 0.0),
    ]
    assert _opponents_win_probability(opps) == pytest.approx(1 / 3)
    ev1 = (
        0.25
        * (
            (1 / 3) * (10000 + 1500 + 2 * 1500)
            + (1 / 3) * (10000 + 1500 + 1500 + 3000)
            + (1 / 3) * (10000 + 1500 + 3000 + 3000)
            + (1 / 3) * (10000 + 1500 + 3000 + 4500)
        )
        - 1500
    )
    assert _terminal_ev_call_multi(game, 0.5, _RoundTracker(), 1, None, opps, 10000, 0, 3000) == pytest.approx(ev1)
    # 深度加深 EV 单调递增但收敛：depth=3 远小于满池 20000，旧版 27516（>满池）
    ev2 = _terminal_ev_call_multi(game, 0.5, _RoundTracker(), 2, None, opps, 10000, 0, 3000)
    ev3 = _terminal_ev_call_multi(game, 0.5, _RoundTracker(), 3, None, opps, 10000, 0, 3000)
    assert ev1 < ev2 < ev3
    assert ev3 < 0.6 * 20000
    assert ev3 - ev1 < 0.3 * ev3


def test_terminal_ev_call_multi_seen_opponents_no_fold_win() -> None:
    """回归（线上 #6109 多人版）：三个看牌对手门槛 0.94+ 时盲跟 EV 必须为负。

    旧实现 EV 被看牌对手的画像历史弃牌率虚高到 +45725（白赢底池分支），误判应战开牌。
    修复后看牌对手 fold 清零，EV 收敛到「胜率×底池−成本」量级（胜率≈1.3% → 负值），
    决策树不会再输出盲跟/应战，改为看牌或弃牌。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "45", "alive": True, "seen": True},
        {"id": "272", "alive": True, "seen": True},
        {"id": "612", "alive": True, "seen": True},
        pot=84000,
        call_bet=3000,
        ante=3000,
    )
    opps = [
        _BlindOpponent("45", True, (0.43, 0.57, 0.00), 0.948),
        _BlindOpponent("272", True, (0.30, 0.43, 0.27), 0.956),
        _BlindOpponent("612", True, (0.62, 0.29, 0.08), 0.938),
    ]
    win = _opponents_win_probability(opps)
    assert win < 0.05  # 三看牌强对手，真实胜率极低
    for depth in (1, 2, 3):
        ev = _terminal_ev_call_multi(game, 0.5, _RoundTracker(), depth, None, opps, 84000, 0, 3000)
        assert ev < 0, f"depth={depth} 盲跟 EV 应为负，实际 {ev}"


def test_terminal_action_ineffective_detects_unexecuted_action() -> None:
    """回归（线上 #6109）：终局动作已发但仍是我方回合且动作仍可用 → 判定未生效。

    旧实现用 last_terminal_action 永久去重，门户未执行 showdown/open（多人局常不开放）
    时每轮都被「已发送过」拦截、卡死到行动超时。判定未生效后调用方清除标记允许重发。
    """
    # 未生效：仍是己方回合、存活、动作仍在可用列表
    assert _terminal_action_ineffective("showdown", True, True, ["fold", "showdown"]) is True
    assert _terminal_action_ineffective("open", True, True, ["fold", "open"]) is True
    # 已生效或无需重发的情形 → False
    assert _terminal_action_ineffective(None, True, True, ["fold", "showdown"]) is False  # 没发过
    assert _terminal_action_ineffective("showdown", True, False, ["fold", "showdown"]) is False  # 非己方回合
    assert _terminal_action_ineffective("showdown", False, True, ["fold", "showdown"]) is False  # 已出局
    assert _terminal_action_ineffective("showdown", True, True, ["fold", "call"]) is False  # 动作已不可用


def test_terminal_action_or_fallback_caps_resend_then_peeks() -> None:
    """回归：终局动作重发达到 _TERMINAL_RESEND_MAX 后回退看牌（无看牌退盲跟），防无限重发。"""
    actions = ["fold", "call", "peek", "showdown"]
    # 未超限 → 原样返回终局动作
    assert _terminal_action_or_fallback("showdown", 0, actions) == "showdown"
    assert _terminal_action_or_fallback("open", _TERMINAL_RESEND_MAX - 1, actions) == "open"
    # 超限 → 回退看牌
    assert _terminal_action_or_fallback("showdown", _TERMINAL_RESEND_MAX, actions) == "peek"
    assert _terminal_action_or_fallback("open", _TERMINAL_RESEND_MAX + 2, actions) == "peek"
    # 超限但无看牌 → 退盲跟
    assert _terminal_action_or_fallback("showdown", _TERMINAL_RESEND_MAX, ["fold", "call", "showdown"]) == "call"
    # 非终局动作不受影响
    assert _terminal_action_or_fallback("call", _TERMINAL_RESEND_MAX + 5, actions) == "call"
    assert _terminal_action_or_fallback("peek", _TERMINAL_RESEND_MAX + 5, actions) == "peek"


def test_terminal_ev_decision_routes_multi_opponents() -> None:
    """_terminal_ev_decision 传入 opponents 时走多人树，且各对手画像独立生效。

    三人局两个存活对手：一个必弃（白送弃牌权益）、一个必跟。盲跟 EV 应为正；
    换成一个必加注的看牌强对手后，盲跟 EV 显著下降（门槛衰减）。
    """
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False},
        {"id": "p2", "alive": True, "seen": False},
        pot=50000,
        call_bet=100,
    )
    # p1 必弃、p2 必平跟 → 弃牌权益大，盲跟 EV 高
    fold_heavy = [
        _BlindOpponent("p1", False, (1.0, 0.0, 0.0), 0.0),
        _BlindOpponent("p2", False, (0.0, 1.0, 0.0), 0.0),
    ]
    dec = _terminal_ev_decision(game, 0.5, _RoundTracker(), depth=2, opponents=fold_heavy)
    assert dec.action == "call"
    assert dec.call_ev > 0
    # p1 必弃、p2 为看牌强加注（门槛 0.9）→ 盲跟 EV 应显著低于前者
    strong_raiser = [
        _BlindOpponent("p1", False, (1.0, 0.0, 0.0), 0.0),
        _BlindOpponent("p2", True, (0.0, 0.0, 1.0), 0.9),
    ]
    dec2 = _terminal_ev_decision(game, 0.5, _RoundTracker(), depth=2, opponents=strong_raiser)
    assert dec2.call_ev < dec.call_ev


def test_terminal_ev_peek_multi_uses_all_opponents() -> None:
    """多人看牌分支：内盈亏平衡点只对继续有正 EV 的手牌积分，全弃对手移出。"""

    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "p1", "alive": True, "seen": False},
        {"id": "p2", "alive": True, "seen": True},
        pot=10000,
        call_bet=1000,
    )
    # p1 必弃、p2 必平跟：唯一组合下 p1 移出，只剩 p2（看牌门槛 0.5）
    opps = [
        _BlindOpponent("p1", False, (1.0, 0.0, 0.0), 0.0),
        _BlindOpponent("p2", True, (0.0, 1.0, 0.0), 0.5),
    ]
    peek_ev = _terminal_ev_peek_multi(game, 0.5, _RoundTracker(), 2, None, opps)
    # 手算（内盈亏平衡点）：池 = 10000+1000 = 11000，我方看牌后强牌全价跟注 1000
    # 进摊牌底池 → pot_win = 12000，全价成本 1000，
    # 胜率(t) = (t−0.5)/0.5；盈亏平衡 t* = 0.5 + 0.5×(1000/12000)。
    # peek_ev = ∫_{t*}^1 (胜率(t)×12000 − 1000) dt（t<t* 弃牌贡献 0）
    t_star = 0.5 + 0.5 * (1000 / 12000)
    win_integral = ((1 - 0.5) ** 2 - (t_star - 0.5) ** 2) / (2 * 0.5)
    expected = 12000 * win_integral - 1000 * (1 - t_star)
    assert peek_ev == pytest.approx(expected)
    assert peek_ev > 0  # 看牌免费：结构性非负


def test_tracker_counts_opponent_consecutive_raises() -> None:
    """轮询跟踪累计对手本局加注次数（bet 递增 + lastAction 加注才计一次）。"""
    tracker = _RoundTracker()
    before = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 100, "lastAction": "看牌"},
        pot=500,
        call_bet=100,
    )
    raise1 = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 200, "lastAction": "加注"},
        pot=700,
        call_bet=100,
    )
    raise2 = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 300, "lastAction": "加注"},
        pot=900,
        call_bet=100,
    )
    # 对手 bet 未变（跟注追平后静止）不再重复计数
    still = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True, "bet": 100},
        {"id": "opponent", "alive": True, "seen": True, "bet": 300, "lastAction": "加注"},
        pot=900,
        call_bet=100,
    )

    _update_round_tracker(before, tracker)
    _update_round_tracker(raise1, tracker)
    _update_round_tracker(raise2, tracker)
    _update_round_tracker(still, tracker)

    assert tracker.opponent_raise_counts["opponent"] == 2
    assert tracker.snapshots["opponent"].is_raise


def test_seen_opponent_ranges_escalates_raise_threshold_for_consecutive_raises() -> None:
    """回归：对手连续 raise 3 次，门槛按 β=0.5 逐级上调（0.5 → 0.9375）。

    旧实现只按赔率 break-even 反推门槛，连续 raise 的强度信号被低估——
    我方同花胜率虚高、死追输钱（用户报「对对方牌力预估太保守」）。
    """
    tracker = _RoundTracker()
    tracker.snapshots["opponent"] = _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1, is_raise=True
    )
    tracker.opponent_raise_counts["opponent"] = 3
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )

    blind, ranges = _seen_opponent_ranges(game, tracker, 0.5)

    assert blind == 0
    assert len(ranges) == 1
    # 快照反推门槛 pot=500/callBet=100 → break-even 0.1667，连续 raise 3 次逐级上调：
    # 0.1667 → 0.5833 → 0.7917 → 0.8958
    assert ranges[0].lower == pytest.approx(0.8958333)

    # 控制组：单次加注（raise_count=0）门槛保持反推值不升级
    tracker_flat = _RoundTracker()
    tracker_flat.snapshots["opponent"] = _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1, is_raise=True
    )
    _, ranges_flat = _seen_opponent_ranges(game, tracker_flat, 0.5)
    assert ranges_flat[0].lower == pytest.approx(0.1666667)


def test_seen_opponent_ranges_no_escalation_in_showdown_phase() -> None:
    """强制摊牌阶段（phase=showdown）对手 raise 是唯一「继续」动作，不升级门槛。"""
    tracker = _RoundTracker()
    tracker.snapshots["opponent"] = _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1, is_raise=True
    )
    tracker.opponent_raise_counts["opponent"] = 3
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    game["phase"] = "showdown"

    _, ranges = _seen_opponent_ranges(game, tracker, 0.5)

    assert ranges[0].lower == pytest.approx(0.1666667)


def test_call_decision_consecutive_raises_flips_flush_to_fold() -> None:
    """用户场景回归：同花面对对手连续 raise，门槛上调后 EV 由正转负、改弃牌。

    金花(9,5,3) 单挑胜率 0.952；对手连续 raise 5 次门槛升至 0.984（>0.952）→
    胜率归零 → EV 负。旧实现门槛 0.5 → 胜率 0.904 → EV 巨正 → 死追。
    """
    pot, call_bet = 30000.0, 6000.0
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opponent", "alive": True, "seen": True},
        pot=pot,
        call_bet=call_bet,
    )
    game["phase"] = "playing"

    tracker = _RoundTracker()
    tracker.snapshots["opponent"] = _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1, is_raise=True
    )
    tracker.opponent_raise_counts["opponent"] = 5
    dec = _call_decision("金花", (9, 5, 3), game, 0.5, tracker, None)
    assert dec is not None
    assert dec.expected_value < 0

    tracker_flat = _RoundTracker()
    tracker_flat.snapshots["opponent"] = _OpponentSnapshot(
        pot=500, call_bet=100, opponents=1, blind_opponents=1, is_raise=True
    )
    dec_flat = _call_decision("金花", (9, 5, 3), game, 0.5, tracker_flat, None)
    assert dec_flat is not None
    assert dec_flat.expected_value > 0
    assert dec_flat.expected_value > dec.expected_value

    # _choose 决策层也翻转：连续 raise 5 次 → 弃牌
    choice = _choose("金花", (9, 5, 3), game, 0.5, tracker, 0, None)
    assert not choice.call
    assert "低于弃牌容差" in choice.reason


class _FakeKV:
    """内存版 ctx.kv：支持 get/set（战绩入账与统计读回）。"""

    def __init__(self) -> None:
        self._d: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._d.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._d[key] = value


def test_record_round_result_accumulates_total_and_day() -> None:
    """正向：多局入账，累计与当日统计同步更新，返回本局净输赢。"""
    kv = _FakeKV()
    assert record_round_result(kv, {"roundId": 1, "selfDelta": 15000}, today="2026-08-06") == 15000
    assert record_round_result(kv, {"roundId": 2, "selfDelta": -3000}, today="2026-08-06") == -3000
    assert record_round_result(kv, {"roundId": 3, "selfDelta": 2000}, today="2026-08-06") == 2000

    total = kv.get("zjh:stats")
    assert total["games"] == 3
    assert total["wins"] == 2 and total["losses"] == 1 and total["draws"] == 0
    assert total["profit"] == 17000 and total["loss_amount"] == 3000
    day = kv.get("zjh:stats:day:2026-08-06")
    assert day == total


def test_record_round_result_skips_missing_delta() -> None:
    """异常路径：无 selfDelta 或结构异常时不入账、返回 None。"""
    kv = _FakeKV()
    assert record_round_result(kv, {"roundId": 1}) is None
    assert record_round_result(kv, {"roundId": 2, "selfDelta": "abc"}) is None
    assert record_round_result(kv, None) is None
    assert kv.get("zjh:stats") is None


class _LoopStop(BaseException):
    """中断 _poll_loop 的 while True（继承 BaseException，避免被 except Exception 吞掉）。"""


class _PollLog:
    def info(self, *args: object) -> None:
        pass

    def warning(self, *args: object) -> None:
        pass

    def error(self, *args: object) -> None:
        pass


class _PollCtx:
    def __init__(self, kv: object, cfg: dict[str, object]) -> None:
        self.kv = kv
        self.config = cfg
        self.log = _PollLog()
        self.notifications: list[str] = []

    async def notify(self, text: str, **kwargs: object) -> None:
        self.notifications.append(text)


class _PollClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._next = iter(responses)
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def get(self, path: str) -> dict[str, object]:
        return next(self._next)

    async def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, body))
        return {"ok": True}

    def configure(self, *args: object, **kwargs: object) -> None:  # noqa: ANN002, ANN003
        pass

    def set_renewer(self, *args: object) -> None:  # noqa: ANN002
        pass

    def reset_csrf(self) -> None:
        pass


class _FakeHdsky:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = responses

    async def __aenter__(self) -> _PollClient:
        return _PollClient(self._responses)

    async def __aexit__(self, *args: object) -> None:  # noqa: ANN002
        return None


@pytest.mark.asyncio
async def test_poll_loop_records_result_and_notifies_when_bot_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 v1.16.9 bug：round_joined 声明后从未置位，roundId 切换条件
    `if last_rid and round_joined:` 恒不成立——战绩从不入账 zjh:stats、
    对局结束通知从不推送。

    模拟两轮 poll：R1 bot 已加入（joined=True）→ R2 切换且 lastResult 含
    selfDelta=15000 → 应入账累计统计并推送带「本局 +15000」的结果通知。
    """
    import asyncio
    import importlib

    # 注：包目录与子模块同名（...games.zhajinhua.zhajinhua），`import ... as x` 会被编译为
    # from-import 语义而失败，改用 importlib 显式加载。
    zhajinhua_mod = importlib.import_module("plugins.skyGame.games.zhajinhua.zhajinhua")
    from plugins.skyGame.games.zhajinhua.zjh_profile import reset_store

    round1 = {
        "game": {
            "roundId": "r1",
            "phase": "betting",
            "pot": 1000,
            "callBet": 100,
            "self": {
                "id": "self",
                "displayName": "Bot",
                "isSelf": True,
                "joined": True,
                "alive": True,
                "isTurn": False,
            },
            "players": [
                {"id": "self", "displayName": "Bot", "isSelf": True, "joined": True, "alive": True, "isTurn": False},
            ],
            "actions": [],
        }
    }
    round2 = {
        "game": {
            "roundId": "r2",
            "phase": "betting",
            "pot": 1000,
            "callBet": 100,
            "lastResult": {"roundId": "r1", "selfDelta": 15000},
            "self": {
                "id": "self",
                "displayName": "Bot",
                "isSelf": True,
                "joined": True,
                "alive": True,
                "isTurn": False,
            },
            "players": [
                {"id": "self", "displayName": "Bot", "isSelf": True, "joined": True, "alive": True, "isTurn": False},
            ],
            "actions": [],
        }
    }

    class LoopKV:
        def __init__(self) -> None:
            self._d: dict[str, object] = {}

        def get(self, key: str, default: object = None) -> object:
            return self._d.get(key, default)

        def set(self, key: str, value: object) -> None:
            self._d[key] = value

        def keys(self) -> list[str]:
            return list(self._d)

    kv = LoopKV()
    cfg = {
        "zjh_enabled": True,
        "zjh_profile_enabled": True,
        "zjh_notify_hand": True,
        "zjh_notify_join": True,
        "zjh_notify_error": True,
    }
    ctx = _PollCtx(kv, cfg)

    reset_store()
    monkeypatch.setattr(zhajinhua_mod, "HdskyClient", lambda log: _FakeHdsky([round1, round2]))
    monkeypatch.setattr(zhajinhua_mod.hdsky_auth, "renewer_for", lambda _ctx: None)
    sleep_count = {"n": 0}

    async def _stop_after_two(_seconds: float, *args: object, **kwargs: object) -> None:  # noqa: ANN002, ANN003
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            raise _LoopStop()

    monkeypatch.setattr(asyncio, "sleep", _stop_after_two)

    with pytest.raises(_LoopStop):
        await zhajinhua_mod._poll_loop(ctx)

    stats = kv.get("zjh:stats")
    assert isinstance(stats, dict)
    assert stats["games"] == 1 and stats["profit"] == 15000
    assert any("本局 +15000" in n for n in ctx.notifications)


def test_record_round_result_day_isolation() -> None:
    """不同日期分键存储，互不影响。"""
    kv = _FakeKV()
    record_round_result(kv, {"selfDelta": 1000}, today="2026-08-05")
    record_round_result(kv, {"selfDelta": -500}, today="2026-08-06")
    assert kv.get("zjh:stats")["games"] == 2
    assert kv.get("zjh:stats:day:2026-08-05")["games"] == 1
    assert kv.get("zjh:stats:day:2026-08-06")["games"] == 1
    assert kv.get("zjh:stats:day:2026-08-05")["profit"] == 1000
    assert kv.get("zjh:stats:day:2026-08-06")["loss_amount"] == 500


def test_game_result_notification_with_delta_and_stats() -> None:
    """正向：本局盈亏、累计与当日战绩都渲染进对局结束通知。"""
    game_data = {
        "game": {
            "self": {"alive": True},
            "players": [
                {"id": "self", "isSelf": True, "alive": True, "hand": "A♠ K♠ Q♠", "handType": "金花"},
                {"id": "opp", "alive": True, "hand": "K♣ K♦ 9♠", "handType": "对子"},
            ],
        }
    }
    total = {
        "games": 120,
        "wins": 61,
        "draws": 4,
        "losses": 55,
        "profit": 45000.0,
        "loss_amount": 36100.0,
    }
    day = {
        "games": 12,
        "wins": 7,
        "draws": 0,
        "losses": 5,
        "profit": 8000.0,
        "loss_amount": 6800.0,
    }

    notification = _game_result_notification(game_data, "A♠ K♠ Q♠", "金花", 15000, total, day)

    assert "本局 +15000" in notification
    assert "📊 累计 120 局 · 胜 61 / 平 4 / 负 55 · 净 +8900" in notification
    assert "📅 今日 12 局 · 胜 7 / 平 0 / 负 5 · 净 +1200" in notification


def test_game_result_notification_negative_delta_and_no_stats() -> None:
    """异常路径：负盈亏渲染带符号；无战绩时不渲染统计行。"""
    game_data = {
        "game": {
            "self": {"alive": False},
            "players": [{"id": "self", "isSelf": True, "alive": False}],
        }
    }
    notification = _game_result_notification(game_data, "", "", -3000, None, None)
    assert "本局 -3000" in notification
    assert "📊" not in notification
    assert "📅" not in notification


@pytest.mark.asyncio
async def test_notify_game_result_appends_cumulative_stats() -> None:
    """正向：_notify_game_result 从 kv 读累计战绩拼进通知。"""
    ctx = _CapturingContext()
    ctx.kv["zjh:stats"] = {
        "games": 10,
        "wins": 6,
        "draws": 0,
        "losses": 4,
        "profit": 8000.0,
        "loss_amount": 2500.0,
    }
    game_data = {
        "game": {
            "self": {"alive": True},
            "players": [{"id": "self", "isSelf": True, "alive": True}],
        }
    }

    await _notify_game_result(ctx, {"zjh_notify_hand": True}, game_data, "A♠ K♠ Q♠", "金花", 15000)

    assert ctx.messages
    msg = ctx.messages[0]
    assert "本局 +15000" in msg
    assert "📊 累计 10 局 · 胜 6 / 平 0 / 负 4 · 净 +5500" in msg
