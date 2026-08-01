# -*- coding: utf-8 -*-
# skyGame · 炸金花概率与决策单元测试

from __future__ import annotations

import pytest

from plugins.skyGame.games import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua import (
    _call_decision,
    _extract_hand_value,
    _normalize_hand_type,
    _opponent_counts,
    _parse_hand,
    _should_call,
)


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


def test_parse_and_extract_reject_invalid_hand() -> None:
    assert _parse_hand("10♠3♥2♦") == [10, 3, 2]
    assert _extract_hand_value("金花", "A♠K♠") is None
    assert _extract_hand_value("未知", "A♠K♠Q♠") is None


def test_opponent_counts_separates_blind_seen_and_self() -> None:
    game = {
        "players": [
            {"alive": True, "isSelf": True, "seen": True},
            {"alive": True, "seen": False},
            {"alive": True, "seen": True},
            {"alive": False, "seen": False},
        ]
    }
    assert _opponent_counts(game) == (1, 1)


def test_opponent_counts_uses_conservative_fallback_without_players() -> None:
    assert _opponent_counts({}) == (1, 0)


def test_call_decision_all_blind_uses_power_probability() -> None:
    game = {
        "pot": 1000,
        "callBet": 100,
        "players": [
            {"alive": True, "isSelf": True},
            {"alive": True, "seen": False},
            {"alive": True, "seen": False},
        ],
    }
    decision = _call_decision("金花", (14, 13, 11), game, 0.5)

    assert decision is not None
    one_vs_one = zjh_prob.win_prob_1v1("金花", (14, 13, 11))
    assert decision.win_probability == pytest.approx(one_vs_one**2)


def test_call_decision_conditions_seen_opponent_on_threshold() -> None:
    game = {
        "pot": 1000,
        "callBet": 100,
        "players": [
            {"alive": True, "isSelf": True},
            {"alive": True, "seen": False},
            {"alive": True, "seen": True},
        ],
    }
    decision = _call_decision("对子", (14, 13), game, 0.5)

    assert decision is not None
    one_vs_one = zjh_prob.win_prob_1v1("对子", (14, 13))
    expected = one_vs_one * max(one_vs_one - 0.5, 0) / 0.5
    assert decision.win_probability == pytest.approx(expected)


def test_call_decision_cannot_beat_seen_opponent_below_threshold() -> None:
    game = {
        "pot": 1000,
        "callBet": 10,
        "players": [{"alive": True, "isSelf": True}, {"alive": True, "seen": True}],
    }
    decision = _call_decision("对子", (2, 3), game, 0.75)

    assert decision is not None
    assert decision.win_probability == 0
    assert decision.expected_value == -10


def test_should_call_accepts_positive_ev_below_fifty_percent_win_rate() -> None:
    game = {
        "pot": 10000,
        "callBet": 100,
        "players": [{"alive": True, "isSelf": True}, {"alive": True, "seen": False}],
    }
    decision = _should_call("散牌", (8, 7, 5), game, ["散牌"], 0.5)

    assert decision is not None
    assert decision.win_probability < 0.5
    assert decision.expected_value > 0


def test_should_call_rejects_negative_ev_and_unselected_hand_type() -> None:
    game = {
        "pot": 100,
        "callBet": 2000,
        "players": [{"alive": True, "isSelf": True}, {"alive": True, "seen": False}],
    }
    assert _should_call("对子", (14, 13), game, ["对子"], 0.5) is None
    assert _should_call("同花顺", 14, game, ["顺子"], 0.5) is None


def test_call_decision_rejects_invalid_financial_data() -> None:
    game = {"pot": 0, "callBet": 100, "players": []}
    assert _call_decision("豹子", 14, game, 0.5) is None
    assert _call_decision("豹子", 14, {"pot": 100, "callBet": -1}, 0.5) is None
    assert _call_decision("豹子", None, {"pot": 100, "callBet": 1}, 0.5) is None
