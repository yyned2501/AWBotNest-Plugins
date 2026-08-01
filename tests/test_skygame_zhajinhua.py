# -*- coding: utf-8 -*-
# skyGame · 炸金花概率、对手推断与决策单元测试

from __future__ import annotations

import pytest

from plugins.skyGame.games import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua import (
    _call_decision,
    _choose,
    _extract_hand_value,
    _normalize_hand_type,
    _opponent_counts,
    _opponent_threshold,
    _OpponentSnapshot,
    _parse_hand,
    _RoundTracker,
    _update_round_tracker,
)


def _game(*players: dict[str, object], pot: float = 1000, call_bet: float = 100) -> dict[str, object]:
    return {"pot": pot, "callBet": call_bet, "players": list(players)}


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


def test_opponent_threshold_reflects_ev_zero_pot_odds() -> None:
    one_opponent = _OpponentSnapshot(pot=100, call_bet=100, opponents=1)
    two_opponents = _OpponentSnapshot(pot=100, call_bet=100, opponents=2)

    assert _opponent_threshold(one_opponent) == pytest.approx(0.5)
    assert _opponent_threshold(two_opponents) == pytest.approx(0.5**0.5)
    assert _opponent_threshold(_OpponentSnapshot(pot=0, call_bet=100, opponents=1)) is None


def test_tracker_records_seen_opponent_bet_increase_using_prior_snapshot() -> None:
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

    # 行动者面对的是其余存活对手（不含自己）：self + opponent + blind 中对手面对 1 人
    assert tracker.snapshots["opponent"] == _OpponentSnapshot(pot=500, call_bet=100, opponents=1)


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

    assert tracker.snapshots["opponent"] == _OpponentSnapshot(pot=500, call_bet=100, opponents=1)


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
    assert decision.seen_thresholds == ((0.5, True),)


def test_call_decision_falls_back_for_unobserved_seen_opponent() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True},
        {"id": "seen", "alive": True, "seen": True},
    )
    decision = _call_decision("对子", (14, 13), game, 0.75, _RoundTracker())

    assert decision is not None
    assert decision.seen_thresholds == ((0.75, False),)


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
