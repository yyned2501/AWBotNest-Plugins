# -*- coding: utf-8 -*-
# skyGame · 炸金花概率、对手推断与决策单元测试

from __future__ import annotations

import pytest

from plugins.skyGame.games import gen_zjh_prob, zjh_prob
from plugins.skyGame.games.zhajinhua import (
    _acquire_hand_after_peek,
    _act_on_hand,
    _actual_win_probability,
    _call_decision,
    _choose,
    _choose_action,
    _combined_opponent_threshold,
    _combined_self_threshold,
    _extract_hand_value,
    _game_result_notification,
    _hand_threshold_for_actual_win_probability,
    _heads_up_blind_action,
    _heads_up_opponent_seen,
    _heads_up_stop_loss_action,
    _in_hand,
    _is_heads_up,
    _normalize_hand_type,
    _notify_game_result,
    _opponent_counts,
    _opponent_hand_threshold,
    _opponent_threshold,
    _OpponentSnapshot,
    _parse_hand,
    _RoundTracker,
    _self_hand,
    _snapshot_for_actor,
    _update_round_tracker,
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
    assert decision.seen_thresholds == ((0.5, True),)


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


def test_is_heads_up_detects_single_opponent() -> None:
    # 单挑：只有一个对手存活
    heads_up = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
    )
    assert _is_heads_up(heads_up) is True


def test_is_heads_up_false_with_multiple_opponents() -> None:
    # 非单挑：多个对手存活
    multi = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp1", "alive": True, "seen": False},
        {"id": "opp2", "alive": True, "seen": False},
    )
    assert _is_heads_up(multi) is False


def test_is_heads_up_false_with_no_opponents() -> None:
    # 无对手（只剩自己）：不是单挑
    alone = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
    )
    assert _is_heads_up(alone) is False


def test_heads_up_opponent_seen_true_when_opponent_has_peeked() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": True},
    )
    assert _heads_up_opponent_seen(game) is True


def test_heads_up_opponent_seen_false_when_opponent_blind() -> None:
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
    )
    assert _heads_up_opponent_seen(game) is False


def test_heads_up_opponent_seen_false_when_no_opponent() -> None:
    assert _heads_up_opponent_seen({}) is False


def _blind_heads_up_game(opp_seen: bool) -> dict[str, object]:
    """构造我方蒙牌的单挑局面（self.seen=False + 一个对手）。"""
    return _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp", "alive": True, "seen": opp_seen},
    )


def test_heads_up_blind_action_prefers_showdown_over_peek() -> None:
    # 正向（实测门户动作集 peek,fold,raise,showdown）：有 showdown 就直接开，绝不看牌
    game = _blind_heads_up_game(opp_seen=True)
    assert _heads_up_blind_action(game, ["peek", "fold", "raise", "showdown"]) == "showdown"


def test_heads_up_blind_action_uses_open_when_no_showdown() -> None:
    # 正向（实测门户动作集 peek,fold,call,raise,open）：无 showdown 时用 open 开牌
    game = _blind_heads_up_game(opp_seen=True)
    assert _heads_up_blind_action(game, ["peek", "fold", "call", "raise", "open"]) == "open"


def test_heads_up_blind_action_prefers_showdown_when_both_available() -> None:
    # 正向：两者都给时优先 showdown（应战开牌）
    game = _blind_heads_up_game(opp_seen=True)
    assert _heads_up_blind_action(game, ["peek", "fold", "call", "raise", "open", "showdown"]) == "showdown"


def test_heads_up_blind_action_calls_when_opponent_also_blind() -> None:
    # 异常路径（实测对手也蒙牌时门户只给 peek,fold,call,raise，开不了牌）：退回盲跟，绝不看牌
    game = _blind_heads_up_game(opp_seen=False)
    assert _heads_up_blind_action(game, ["peek", "fold", "call", "raise"]) == "call"


def test_heads_up_blind_action_never_returns_peek() -> None:
    # 回归核心：即便只有 peek/call 可选，也不能返回 peek（看牌会翻倍投入）
    game = _blind_heads_up_game(opp_seen=False)
    assert _heads_up_blind_action(game, ["peek", "call"]) == "call"


def test_heads_up_blind_action_returns_none_when_not_heads_up() -> None:
    # 异常路径：多对手局面不触发，交回常规看牌决策
    multi = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": False},
        {"id": "opp1", "alive": True, "seen": True},
        {"id": "opp2", "alive": True, "seen": False},
    )
    assert _heads_up_blind_action(multi, ["peek", "fold", "call", "raise", "open"]) is None


def test_heads_up_blind_action_returns_none_without_any_executable_action() -> None:
    # 异常路径：单挑但既不能开牌也不能跟注（仅 peek/fold）时返回 None，不强行看牌
    game = _blind_heads_up_game(opp_seen=False)
    assert _heads_up_blind_action(game, ["peek", "fold"]) is None


def test_heads_up_stop_loss_prefers_compare_over_call() -> None:
    # 正向（实测门户动作集 fold,call,raise,open）：EV 为负时优先比牌止损，绝不返回 call
    assert _heads_up_stop_loss_action(["fold", "call", "raise", "open"]) == "open"
    assert _heads_up_stop_loss_action(["fold", "call", "raise", "showdown"]) == "showdown"
    assert _heads_up_stop_loss_action(["fold", "call", "raise", "open", "showdown"]) == "showdown"


def test_heads_up_stop_loss_folds_when_no_compare_available() -> None:
    # 异常路径：门户不给比牌动作时弃牌止损，即便 call 可用也不跟注
    assert _heads_up_stop_loss_action(["fold", "call", "raise"]) == "fold"
    assert _heads_up_stop_loss_action(["fold"]) == "fold"


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_blind_opponent_calls_without_ev_check() -> None:
    """单挑对手未看牌 → 直接跟注，不检查 EV 正负。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": False},
        pot=100,
        call_bet=2000,
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
        "2♠ 3♥ 5♦",
        "散牌",
        0.5,
        _RoundTracker(),
    )
    assert pending_fold is False
    # EV 为负也应跟注（对手未看牌），不弃牌
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "call"})]


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_seen_opponent_negative_ev_opens_to_stop_loss() -> None:
    """回归：单挑对手已看牌、EV 为负且门户允许 open → 比牌止损，绝不连跟。

    旧逻辑「EV为负也不弃牌」曾强制跟注，导致终胜率 0% 仍连跟多轮、单局巨亏。
    """
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
    # EV 为负 → 比牌止损，而不是继续跟注
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "open"})]


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_seen_opponent_negative_ev_folds_when_no_compare() -> None:
    """单挑对手已看牌、EV 为负但门户不给比牌 → 弃牌止损，仍不跟注。"""
    game = _game(
        {"id": "self", "alive": True, "isSelf": True, "seen": True},
        {"id": "opp", "alive": True, "seen": True},
        pot=100,
        call_bet=2000,
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
        "2♠ 3♥ 5♦",
        "散牌",
        0.5,
        _RoundTracker(),
    )
    # 无比牌动作 → 走弃牌流程（_FakeClient 无 foldConfirm，直接完成）
    assert pending_fold is False
    assert client.requests == [("/api/portal/zhajinhua/action", {"action": "fold"})]


@pytest.mark.asyncio
async def test_act_on_hand_heads_up_showdown_override_still_wins() -> None:
    """单挑对手已看牌时 showdown 覆盖仍优先于单挑特殊逻辑。"""
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
