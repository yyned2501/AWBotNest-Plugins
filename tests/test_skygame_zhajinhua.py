# -*- coding: utf-8 -*-
# skyGame · 炸金花概率与决策单元测试

from __future__ import annotations

from plugins.skyGame.games import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua import (
    _extract_hand_value,
    _normalize_hand_type,
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


def test_normalize_portal_flush_name_and_call_decision() -> None:
    hand_type = _normalize_hand_type("同花")
    hand_value = _extract_hand_value(hand_type, "A♠K♠J♠")

    assert hand_type == "金花"
    assert _should_call(hand_type, hand_value, 3, ["金花"])


def test_should_call_uses_exact_hand_type_matching() -> None:
    assert not _should_call("同花顺", 14, 2, ["顺子"])
    assert _should_call("同花顺", 14, 2, ["同花顺"])


def test_parse_and_extract_reject_invalid_hand() -> None:
    assert _parse_hand("10♠3♥2♦") == [10, 3, 2]
    assert _extract_hand_value("金花", "A♠K♠") is None
    assert _extract_hand_value("未知", "A♠K♠Q♠") is None
