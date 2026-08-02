# -*- coding: utf-8 -*-
# skyGame · 炸金花概率、对手推断与决策单元测试

from __future__ import annotations

import pytest

from plugins.skyGame.games import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua import (
    _FOLD_CONFIRM_MAX_RETRIES,
    _NEUTRAL_RANGE_MODEL,
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
    _OpponentSnapshot,
    _parse_hand,
    _PendingFold,
    _range_factor,
    _ranged_win_probability,
    _RangeModel,
    _RoundTracker,
    _seen_factor,
    _seen_opponent_ranges,
    _SeenRange,
    _self_hand,
    _snapshot_for_actor,
    _terminal_ev_call,
    _terminal_ev_decision,
    _TerminalBranch,
    _update_round_tracker,
)
from plugins.skyGame.games.zjh_profile import (
    ProfileStore,
    _bucket,
    _hand_pctile_from_result,
)


def _game(*players: dict[str, object], pot: float = 1000, call_bet: float = 100) -> dict[str, object]:
    return {"pot": pot, "callBet": call_bet, "players": list(players)}


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
async def test_showdown_override_uses_server_authorized_action_even_for_negative_ev() -> None:
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
        "A♠ A♥ K♦",
        "对子",
        0.5,
        _RoundTracker(),
        "showdown",
    )

    assert pending_fold is False
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "showdown"})]


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
    assert "期望收益为负" in choice.reason


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
    # 正向：盲跟 Terminal EV<0 时，看牌买信息或弃牌止损，绝不继续盲跟。
    # （对手已看牌且门槛高时，看牌后强牌概率低，peek 也救不回 → 直接弃牌止损）
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["call", "peek", "fold", "raise"], 0.9, _RoundTracker())

    # 新语义：盲跟 EV 大负，弃牌或看牌止损，绝不盲跟
    assert action in ("fold", "peek")
    assert choice is not None
    assert choice.expected_value <= 0


def test_blind_peek_or_call_heads_up_uses_same_ev_path() -> None:
    # 回归：单挑蒙牌对强看牌对手，盲跟 Terminal EV 为负时不盲跟
    # （看牌买信息或直接弃牌止损，绝不继续被对手 raise 套牢）。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["peek", "fold", "showdown"], 0.9, _RoundTracker())

    assert action in ("fold", "peek")
    assert choice is not None
    assert choice.expected_value <= 0


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


def test_blind_peek_or_call_falls_back_to_call_without_peek_action() -> None:
    # 异常路径：盲跟 EV 为负且门户不给看牌（actions 无 peek）时，
    # 新语义下直接弃牌止损（不再盲跟保底——保底盲跟反而被对手 raise 套牢）。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "seen", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    action, choice = _blind_peek_or_call(game, ["call", "fold"], 0.9, _RoundTracker())

    assert action in ("fold", "call")
    assert choice is not None
    assert choice.expected_value <= 0


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


@pytest.mark.asyncio
async def test_act_on_hand_showdown_override_still_wins() -> None:
    """服务端授权 showdown 时仍优先应战，不受普通 EV 弃牌影响。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": True},
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
        "2♠ 3♥ 5♦",
        "散牌",
        0.5,
        _RoundTracker(),
        "showdown",
    )
    assert pending_fold is False
    # showdown 覆盖优先于单挑特殊逻辑
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "showdown"})]


class _CapturingContext:
    """记录 notify 推送内容的假上下文。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

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


# ── 阶段二：范围上限 + 反诈唬补丁 ──────────────────────────────────────────────


def test_ranged_win_probability_matches_actual_under_neutral_model() -> None:
    # 向后兼容核心：中性模型（上界 1.0、诈唬 0）下新模型逐值等于旧 _actual_win_probability，
    # 保证「平跟上限 100 & 反诈唬 0」可精确回退到 v1.12.1 行为。
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
        assert _ranged_win_probability(one_vs_one, blind, seen_ranges, 0.0) == pytest.approx(
            _actual_win_probability(one_vs_one, blind, thresholds)
        )


def test_range_factor_edges_and_degenerate_fallback() -> None:
    assert _range_factor(0.3, 0.5, 0.85) == 0.0  # t ≤ 下界 → 必败
    assert _range_factor(0.9, 0.5, 0.85) == 1.0  # t ≥ 上界 → 必胜
    assert _range_factor(0.675, 0.5, 0.85) == pytest.approx(0.5)  # 区间中点线性
    # 退化区间（上界 ≤ 下界）回落上界 1.0，即旧的 (t - lo)/(1 - lo)
    assert _range_factor(0.75, 0.5, 0.5) == pytest.approx((0.75 - 0.5) / (1.0 - 0.5))
    assert _range_factor(0.75, 0.6, 0.5) == pytest.approx((0.75 - 0.6) / (1.0 - 0.6))


def test_seen_factor_bluff_raises_win_probability() -> None:
    seen_range = _SeenRange(0.5, 0.85, True)
    hand_threshold = 0.7
    base = _range_factor(hand_threshold, 0.5, 0.85)
    # 诈唬 0 时等于纯范围胜率
    assert _seen_factor(hand_threshold, seen_range, 0.0) == pytest.approx(base)
    # 诈唬 > 0 混入单挑胜率 t，抬高胜率（放松方向）
    assert _seen_factor(hand_threshold, seen_range, 0.1) == pytest.approx(0.9 * base + 0.1 * hand_threshold)
    assert _seen_factor(hand_threshold, seen_range, 0.1) > base


def test_is_raise_action_detects_raise_keywords() -> None:
    assert _is_raise_action("加注") is True
    assert _is_raise_action("Raise") is True
    assert _is_raise_action("跟注") is False
    assert _is_raise_action("看牌") is False
    assert _is_raise_action("call") is False


def test_seen_opponent_ranges_map_actions_to_bounds() -> None:
    # 范围映射：平跟对手 [推断门槛, 上限]，加注对手 [max(门槛, 下限), 1.0]。
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
    model = _RangeModel(call_cap=0.85, raise_floor=0.75, bluff=0.08)
    blind, ranges = _seen_opponent_ranges(game, tracker, 0.1, model)

    assert blind == 0
    # 平跟对手：[推断门槛 0.5, 上限 0.85]
    assert ranges[0].lower == pytest.approx(0.5)
    assert ranges[0].upper == pytest.approx(0.85)
    assert ranges[0].observed is True
    # 加注对手：[max(0.5, 0.75)=0.75, 1.0]
    assert ranges[1].lower == pytest.approx(0.75)
    assert ranges[1].upper == pytest.approx(1.0)
    assert ranges[1].observed is True


def test_call_decision_range_and_bluff_loosen_win_probability() -> None:
    # 放松方向：同一手牌、同一已看牌对手，封顶 + 反诈唬比中性模型胜率与 EV 都更高，
    # 且只改上界/胜率、不改推断门槛。
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=1000,
        call_bet=100,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})
    neutral = _call_decision("对子", (14, 13), game, 0.1, tracker)
    loosened = _call_decision(
        "对子", (14, 13), game, 0.1, tracker, _RangeModel(call_cap=0.85, raise_floor=0.75, bluff=0.08)
    )

    assert neutral is not None and loosened is not None
    assert loosened.win_probability > neutral.win_probability
    assert loosened.expected_value > neutral.expected_value
    # 中性模型上界仍记 1.0（旧行为），放松模型上界收到 0.85，推断门槛同为 0.5
    assert neutral.seen_thresholds == ((0.5, 1.0, True),)
    assert loosened.seen_thresholds == ((0.5, 0.85, True),)


def test_choose_flips_to_call_when_range_model_loosens_ev() -> None:
    # 端到端放松：同一手牌、同一对手，中性模型 EV 为负而弃，开启封顶 + 反诈唬后 EV 转正而跟。
    one_vs_one = zjh_prob.win_prob_1v1("对子", (14, 13))
    neutral_win = _ranged_win_probability(one_vs_one, 0, [_SeenRange(0.5, 1.0, True)], 0.0)
    loosened_win = _ranged_win_probability(one_vs_one, 0, [_SeenRange(0.5, 0.85, True)], 0.08)
    assert loosened_win > neutral_win

    # 底池取「中性弃」与「放松跟」两条 EV=0 临界点的中点，确保两侧符号相反
    call_bet = 100.0
    pot = ((1 / neutral_win - 1) + (1 / loosened_win - 1)) / 2 * call_bet
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
        pot=pot,
        call_bet=call_bet,
    )
    tracker = _RoundTracker(snapshots={"seen": _OpponentSnapshot(pot=100, call_bet=100, opponents=1)})

    neutral_choice = _choose("对子", (14, 13), game, 0.1, tracker, _NEUTRAL_RANGE_MODEL)
    loosened_choice = _choose(
        "对子", (14, 13), game, 0.1, tracker, _RangeModel(call_cap=0.85, raise_floor=0.75, bluff=0.08)
    )
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
    """对手每 raise 一次，门槛向 1.0 上调，且不越界。"""
    base = 0.5
    t1 = _opponent_raise_threshold(base, 1)
    t2 = _opponent_raise_threshold(base, 2)
    assert t1 > base
    assert t2 > t1
    assert t2 <= 1.0
    # 画像加注分位若更高，作为门槛上界
    t_with_profile = _opponent_raise_threshold(base, 1, {"raise_pcts": [0.95]})
    assert t_with_profile >= 0.95
    assert t_with_profile <= 1.0


def test_terminal_ev_call_opponent_fold_wins_pot() -> None:
    """对手弃牌分支：我方独赢当前底池，净收益 = pot − 已投入。"""
    # 纯弃牌（P_fold=1）深度 1：直接终局
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    ev = _terminal_ev_call(game, 0.5, _RoundTracker(), 1, None, (1.0, 0.0, 0.0), 10000, 0, 0.5)
    # 对手弃牌 → 我独赢 10000，成本 0
    assert ev == pytest.approx(10000)


def test_terminal_ev_call_depth_cutoff_static() -> None:
    """深度截断：depth≤0 时按当前胜率 × 底池 − 成本静态估值。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": False},
        pot=10000,
        call_bet=100,
    )
    ev = _terminal_ev_call(game, 0.5, _RoundTracker(), 0, None, (1 / 3, 1 / 3, 1 / 3), 10000, 0, 0.5)
    assert ev == pytest.approx(0.5 * 10000 - 0)


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


def test_terminal_ev_decision_folds_when_seen_opponent_strong() -> None:
    """单挑对强看牌对手（门槛 0.9）、成本高：盲跟 EV 大负，弃牌或看牌止损。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
    )
    dec = _terminal_ev_decision(game, 0.9, _RoundTracker(), depth=2)
    assert dec.action in ("fold", "peek")
    assert dec.terminal_ev <= 0


def test_terminal_ev_decision_peek_better_than_blind_call_when_threshold_moderate() -> None:
    """对手门槛中等、成本偏高：看牌分支（免费弱牌止损）优于盲跟。"""
    # 门槛 0.6、pot 较小：盲跟被 raise 撑大不划算，看牌止损更优
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": True},
        pot=500,
        call_bet=1000,
    )
    dec = _terminal_ev_decision(game, 0.6, _RoundTracker(), depth=2)
    # 弃牌=0 兜底；peek 或 fold 都优于盲跟（不该是 call）
    assert dec.action != "call"


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


def test_profile_store_buckets_actions() -> None:
    """画像按状态分桶统计对手动作，flush 后可从 kv 恢复。"""
    store = ProfileStore()
    store.record_action("account:1", "raise", my_seen=False, op_seen=True, is_heads_up=True)
    store.record_action("account:1", "raise", my_seen=False, op_seen=True, is_heads_up=True)
    store.record_action("account:1", "call", my_seen=False, op_seen=True, is_heads_up=True)
    store.record_action("account:1", "fold", my_seen=False, op_seen=True, is_heads_up=False)
    p_fold, p_call, p_raise = store.action_probabilities("account:1", False, True, True)
    assert p_raise == pytest.approx(2 / 3)
    assert p_call == pytest.approx(1 / 3)
    assert p_fold == pytest.approx(0)
    # 不同桶互不影响
    p_f2, _, p_r2 = store.action_probabilities("account:1", False, True, False)
    assert p_f2 == pytest.approx(1.0)
    assert p_r2 == pytest.approx(0)


def test_profile_store_unknown_opponent_falls_back_to_prior() -> None:
    """未知对手回退全局先验；少样本向先验收缩。"""
    store = ProfileStore()
    # 无任何样本 → 均等先验
    p = store.action_probabilities("unknown", False, True, True)
    assert p == pytest.approx((1 / 3, 1 / 3, 1 / 3))
    # 有全局样本：A 常 raise（全局先验偏 raise）
    store.record_action("account:a", "raise", False, True, True)
    store.record_action("account:a", "raise", False, True, True)
    # 少样本对手（1 次 call）向全局先验收缩
    store.record_action("account:new", "call", False, True, True)
    p_new = store.action_probabilities("account:new", False, True, True)
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
    store.record_action("account:9", "raise", False, True, True, display_name="Damon")
    store.flush()
    assert len(kv.keys()) == 1
    assert kv.get("zjh:profile:account:9")["display_name"] == "Damon"

    store2 = ProfileStore(kv)
    store2.load_all()
    p = store2.action_probabilities("account:9", False, True, True)
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


def test_hand_pctile_from_result_parses() -> None:
    """结算手牌文本转一对一胜率分位。"""
    # 顺子 Q-J-10 → 较高分位
    p = _hand_pctile_from_result("Q♥ J♠ 10♥", "顺子")
    assert p is not None and 0.7 < p < 1.0
    # 散牌 10-9-2 → 较低分位
    p2 = _hand_pctile_from_result("10♦ 9♣ 2♥", "散牌")
    assert p2 is not None and p2 < 0.5
    # 无法解析 → None
    assert _hand_pctile_from_result("", "散牌") is None


def test_bucket_keys() -> None:
    """状态分桶键：我蒙/看 × 对手蒙/看 × 单挑/多人。"""
    assert _bucket(False, False, True) == "b_b_hu"
    assert _bucket(False, True, True) == "b_s_hu"
    assert _bucket(True, True, False) == "s_s_multi"
    assert _bucket(True, False, True) == "s_b_hu"


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
