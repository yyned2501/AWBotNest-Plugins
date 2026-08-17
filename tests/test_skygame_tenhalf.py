# -*- coding: utf-8 -*-
# skyGame · 十点半报名/决策/结算入账单元测试
#
# POST 契约来自门户前端源码尚未实测，测试固化防御性解析与决策语义，
# 上线后对照门户调试记录（hdsky_debug）校准。

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from plugins.skyGame.games.tenhalf import (
    _bust_prob,
    _catch_up_settlement,
    _dealer_dist,
    _decide,
    _decide_ev,
    _ev_play,
    _join_amount,
    _observe_dealer_cards,
    _once,
    _pop_dealer_cards,
    _record_dealer,
    _stand_ev,
    _threshold_for,
    start,
)


def _game(
    active: bool = True,
    phase: str = "signup",
    actions: list[str] | None = None,
    players: list[dict[str, object]] | None = None,
    amount_cap: int = 500,
    round_id: int = 501,
    last_result: dict[str, object] | None = None,
    self_total: float | None = None,
) -> dict[str, object]:
    """构造 GET /api/portal/tenhalf 响应。"""
    game: dict[str, object] = {
        "active": active,
        "canStart": True,
        "limits": {"minAmount": 100, "maxAmount": 10000, "maxPlayers": 10},
        "roundId": round_id,
        "phase": phase,
        "amount": amount_cap,
        "actions": actions or [],
        "players": players or [],
    }
    if self_total is not None:
        game["self"] = {"cards": [], "total": self_total, "status": ""}
    if last_result is not None:
        game["lastResult"] = last_result
    return {"game": game}


def _last_result(rid: int = 777, delta: int = 198, dealer_label: str = "8.5点") -> dict[str, object]:
    return {
        "roundId": rid,
        "amount": 500,
        "dealer": "麦克格雷涛",
        "settlement": {
            "dealerDisplayName": "麦克格雷涛",
            "dealerHandLabel": dealer_label,
            "dealerDelta": -198,
            "rakeTotal": 2,
            "self": {"displayName": "Yy", "handLabel": "10点", "resultText": "胜", "delta": delta} if delta else {},
            "results": [],
        },
    }


class _FakeKV:
    def __init__(self) -> None:
        self._d: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._d.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._d[key] = value

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class _FakeLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _fmt(self, msg: str, args: tuple[object, ...]) -> str:
        return msg % args if args else msg

    def debug(self, msg: str, *args: object) -> None:
        self.records.append(("DEBUG", self._fmt(msg, args)))

    def info(self, msg: str, *args: object) -> None:
        self.records.append(("INFO", self._fmt(msg, args)))

    def warning(self, msg: str, *args: object) -> None:
        self.records.append(("WARNING", self._fmt(msg, args)))

    def error(self, msg: str, *args: object) -> None:
        self.records.append(("ERROR", self._fmt(msg, args)))


class _FakeCtx:
    def __init__(self) -> None:
        self.kv = _FakeKV()
        self.log = _FakeLog()
        self.notifications: list[tuple[object, str]] = []
        self.tables: list[tuple[list[str], list[list[object]], dict[str, object]]] = []
        self.schedules: list[tuple[object, str, dict[str, object]]] = []

    def schedule(self, fn: object, mode: str, **kwargs: object) -> None:
        self.schedules.append((fn, mode, dict(kwargs)))

    async def notify(self, message: object, *args: object, **kwargs: object) -> None:
        self.notifications.append((message, str(kwargs.get("level", "info"))))

    async def notify_table(
        self,
        headers: list[str],
        rows: list[list[object]],
        *args: object,
        **kwargs: object,
    ) -> None:
        self.tables.append((list(headers), [list(row) for row in rows], dict(kwargs)))
        table = ("table", list(headers), [list(row) for row in rows])
        self.notifications.append((table, str(kwargs.get("level", "info"))))


class _FakeClient:
    def __init__(self, state: dict[str, object], action: dict[str, object] | list[dict[str, object]]) -> None:
        self._state = state
        # 传 list 时按请求顺序依次返回，否则所有 post 返回同一响应
        self._actions = list(action) if isinstance(action, list) else [action]
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def get(self, path: str) -> dict[str, object]:
        return self._state

    async def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, body))
        if len(self._actions) > 1:
            return self._actions.pop(0)
        return self._actions[0]

    def reset_csrf(self) -> None:
        pass


_OK = {"ok": True, "result": {"ok": True}}
_FAIL = {"ok": True, "result": {"ok": False, "message": "银元不足"}}


# ── 调度接线：回调必须零参可调 ──


def test_start_registers_zero_arg_tick() -> None:
    """平台对 ctx.schedule 回调是零参调用；带参签名会每轮 TypeError 并触发调度降级（v1.17.1）。"""
    ctx = _FakeCtx()
    ctx.config = {"tenhalf_poll_interval": 5}
    start(ctx)
    assert len(ctx.schedules) == 1
    fn, mode, kwargs = ctx.schedules[0]
    assert mode == "interval"
    assert kwargs.get("id") == "tenhalf_poll"
    assert kwargs.get("seconds") == 5
    assert len(inspect.signature(fn).parameters) == 0
    asyncio.run(fn())  # 未启用时零参调用直接返回，不抛异常


# ── 纯函数：下注额夹取 / 爆牌概率 / 决策 / 阈值微调 ──


def test_join_amount_clamps_to_limits() -> None:
    game = {"amount": 500}
    limits = {"minAmount": 100, "maxAmount": 10000}
    assert _join_amount({"tenhalf_bet_amount": 50}, game, limits) == 100  # 低于最小下注
    assert _join_amount({"tenhalf_bet_amount": 99999}, game, limits) == 500  # 高于单桌上限
    assert _join_amount({"tenhalf_bet_amount": 300}, game, limits) == 300  # 区间内原样


def test_bust_prob_rises_with_total() -> None:
    # 牌堆先验：J/Q/K=0.5×12 + A-10×4。10 点只有 0.5 安全（12/52）
    assert _bust_prob(10) == pytest.approx(40 / 52)
    assert _bust_prob(8) == pytest.approx(32 / 52)
    assert _bust_prob(5) < _bust_prob(8) < _bust_prob(10)


def test_decide_threshold_hit_stand() -> None:
    actions = ["hit", "stand"]
    action, reason = _decide(8.5, actions, False, None, 8)
    assert action == "stand" and "阈值" in reason
    action, reason = _decide(5, actions, False, None, 8)
    assert action == "hit" and "爆牌概率" in reason


def test_decide_dealer_bust_stands() -> None:
    action, reason = _decide(1, ["hit", "stand"], True, None, 8)
    assert action == "stand" and "爆牌" in reason


def test_decide_chases_dealer_only_when_window_beats_bust() -> None:
    actions = ["hit", "stand"]
    # 总 4 vs 庄 4.5：反败牌 v∈(0.5,6.5] 共 24 张 > 爆牌 v>6.5 共 16 张 → 要牌
    action, reason = _decide(4, actions, False, 4.5, 8)
    assert action == "hit" and "反败" in reason
    # 总 8 vs 庄 9：反败牌仅 2 点×4 张 < 爆牌 32 张 → 停牌止损
    action, _ = _decide(8, actions, False, 9, 8)
    assert action == "stand"
    # 已领先庄家 → 直接停牌
    action, _ = _decide(9.5, actions, False, 9, 8)
    assert action == "stand"


def test_decide_no_available_actions() -> None:
    action, _ = _decide(5, ["status"], False, None, 8)
    assert action is None


def test_threshold_for_derived_from_dealer_profile() -> None:
    # 样本足够时由画像推导，但受爆牌红线夹取（≤6.5）：均点 9.5 无爆 → 10 夹到 6.5
    dealers = {"涛": {"rounds": 9, "totals": [9.5] * 9}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 6.5
    # 样本不足不采信，退回配置基准（基准不受红线限制，用户显式选择优先）
    assert _threshold_for({"tenhalf_stand_threshold": 8}, {"涛": {"rounds": 3, "totals": [9.5] * 3}}, "涛") == 8
    assert _threshold_for({"tenhalf_stand_threshold": 9}, {}, "涛") == 9
    # 爆率 50% 让利 2 点：均点 8 → 8+0.5-2 = 6.5
    dealers = {"涛": {"rounds": 10, "busts": 5, "totals": [8.0] * 8}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 6.5
    # 爆率 80%：8+0.5-3.2=5.3→5.5（爆率高 5.5 点就停，赌庄家爆）
    dealers = {"涛": {"rounds": 10, "busts": 8, "totals": [8.0] * 6}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 5.5
    # 只有爆牌样本（totals 为空）不推导，退回基准
    assert _threshold_for({"tenhalf_stand_threshold": 8}, {"涛": {"rounds": 12, "busts": 12}}, "涛") == 8
    # 旧版脏数据清洗：>10.5 的样本改计爆牌（爆率 20%）：均点 8 → 8+0.5-0.8=7.7→7.5 夹到 6.5
    dealers = {"涛": {"rounds": 10, "totals": [11.5, 11.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 6.5


def test_record_dealer_counts_over_target_as_bust() -> None:
    """实测爆牌局 handLabel 不含「爆」字（如「11点」）：>10.5 计爆牌不入点数样本。"""
    ctx = _FakeCtx()
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "11点"})
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "爆牌"})
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "8.5点"})
    dealers = json.loads(str(ctx.kv.get("tenhalf:dealers")))
    assert dealers["涛"] == {"rounds": 3, "busts": 2, "totals": [8.5]}


# ── 庄家画像按手牌张数分桶 ──


def test_record_dealer_buckets_by_card_count() -> None:
    """传 cards 时同步计入按张数分桶；爆牌计入桶的 busts、不入桶点数样本。"""
    ctx = _FakeCtx()
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "8点"}, cards=3)
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "11点"}, cards=3)  # 爆牌
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "9点"}, cards=4)
    entry = json.loads(str(ctx.kv.get("tenhalf:dealers")))["涛"]
    assert entry["rounds"] == 3 and entry["busts"] == 1
    assert entry["cards"]["3"] == {"rounds": 2, "busts": 1, "totals": [8.0]}
    assert entry["cards"]["4"] == {"rounds": 1, "totals": [9.0]}


def test_threshold_prefers_card_bucket_then_aggregate() -> None:
    # 张数桶样本足（≥3）→ 用桶：3 张桶均 4 点 → 4.5（聚合均 5 → 5.5 不用）
    dealers = {"涛": {"rounds": 9, "totals": [5.0] * 9, "cards": {"3": {"rounds": 3, "totals": [4.0] * 3}}}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛", dealer_cards=3) == 4.5
    # 该张数桶样本不足 → 退回聚合（均 5 → 5.5）
    dealers = {"涛": {"rounds": 9, "totals": [5.0] * 9, "cards": {"3": {"rounds": 1, "totals": [4.0]}}}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛", dealer_cards=3) == 5.5
    # 未提供张数 → 直接用聚合
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 5.5


def test_observe_and_pop_dealer_cards() -> None:
    """按 roundId 取最大张数暂存（只增不减）；弹出后清空；无 cardCount 不记录。"""
    ctx = _FakeCtx()
    _observe_dealer_cards(ctx, 777, {"cardCount": 2})
    _observe_dealer_cards(ctx, 777, {"cardCount": 3})
    _observe_dealer_cards(ctx, 777, {"cardCount": 1})  # 不回退
    assert _pop_dealer_cards(ctx, 777) == 3
    assert _pop_dealer_cards(ctx, 777) is None  # 已弹出
    _observe_dealer_cards(ctx, 778, {})  # 无 cardCount 不记录
    assert _pop_dealer_cards(ctx, 778) is None


# ── EV 决策（v1.21.0）：停牌 EV 对要牌 EV 递推，庄家画像分布驱动 ──

# 样本庄家：爆率 30%、非爆样本全 8 点（停牌 EV 手算可验）
_EV_DEALER = {"rounds": 10, "busts": 3, "totals": [8.0] * 7}


def test_stand_ev_counts_bust_and_lower_totals() -> None:
    # 庄家爆牌或点数低于我赢，同点庄家赢；无样本时只看爆率
    assert _stand_ev(9, 0.3, [8.0] * 7) == pytest.approx(1.0)
    assert _stand_ev(8, 0.3, [8.0] * 7) == pytest.approx(-0.4)  # 同点输
    assert _stand_ev(7, 0.3, [8.0] * 7) == pytest.approx(-0.4)  # 只能赌庄家爆
    assert _stand_ev(5, 0.5, []) == pytest.approx(0.0)


def test_ev_play_five_small_and_optimality() -> None:
    assert _ev_play(4, 5, 0.0, [9.0], {}) == pytest.approx(5.0)  # 五小直接赢 ×5
    # 最优打法 EV 永不低于停牌 EV（递推取 max）
    assert _ev_play(2, 0, 0.3, [8.0] * 7, {}) >= _stand_ev(2, 0.3, [8.0] * 7)


def test_dealer_dist_prefers_card_bucket_then_aggregate() -> None:
    dealers = {"涛": {**_EV_DEALER, "cards": {"3": {"rounds": 3, "busts": 1, "totals": [6.0] * 2}}}}
    p_bust, samples = _dealer_dist(dealers, "涛", 3)
    assert p_bust == pytest.approx(1 / 3) and samples == [6.0, 6.0]  # 桶样本足优先
    p_bust, samples = _dealer_dist(dealers, "涛", None)
    assert p_bust == pytest.approx(3 / 10) and samples == [8.0] * 7  # 退回聚合
    assert _dealer_dist({"涛": {"rounds": 2, "totals": [8.0, 8.0]}}, "涛", None) is None  # 样本不足
    assert _dealer_dist({}, "涛", 3) is None


def test_decide_ev_prefers_higher_ev_action() -> None:
    dist = (0.3, [8.0] * 7)
    action, reason = _decide_ev(5, 0, ["hit", "stand"], True, None, dist)
    assert action == "stand" and "爆牌" in reason  # 庄家已爆优先
    action, _ = _decide_ev(5, 5, ["hit", "stand"], False, None, dist)
    assert action == "stand"  # 已五小直接赢 ×5
    action, _ = _decide_ev(5, 0, ["hit", "stand"], False, None, dist)
    assert action == "hit"  # 要牌 EV -0.37 > 停牌 -0.40
    action, _ = _decide_ev(9.5, 2, ["hit", "stand"], False, None, dist)
    assert action == "stand"  # 9.5 点几乎稳赢，要牌只会招爆
    action, _ = _decide_ev(4, 4, ["hit", "stand"], False, None, dist)
    assert action == "hit"  # 4 张低点数追五小 ×5（EV +3.15）
    action, _ = _decide_ev(4, 2, ["hit", "stand"], False, 9.0, dist)
    assert action == "hit"  # 庄家 9 点可见：点质量分布，反败优于停牌
    assert _decide_ev(5, 0, [], False, None, dist)[0] is None


@pytest.mark.asyncio
async def test_settlement_pairs_observed_card_count() -> None:
    """活跃局观察庄家 3 张 → 结算配对计入分桶并清空暂存。"""
    ctx = _FakeCtx()
    active = _game(
        active=True,
        phase="player_draw",
        round_id=777,
        players=[
            {"isSelf": True, "betAmount": 100, "cardCount": 2},
            {"dealer": True, "displayName": "麦克格雷涛", "cardCount": 3},
        ],
        self_total=9,
    )
    await _once(ctx, {}, _FakeClient(active, _OK))
    settled = _game(active=False, last_result=_last_result(rid=777, delta=198, dealer_label="11点"))
    await _once(ctx, {}, _FakeClient(settled, _OK))
    entry = json.loads(str(ctx.kv.get("tenhalf:dealers")))["麦克格雷涛"]
    assert entry["cards"]["3"]["busts"] == 1  # 11点>10.5 计爆
    assert json.loads(str(ctx.kv.get("tenhalf:dealer_cards"))) == {}


# ── 报名阶段 ──


@pytest.mark.asyncio
async def test_signup_joins_with_clamped_amount() -> None:
    ctx = _FakeCtx()
    client = _FakeClient(_game(phase="signup", actions=["join"]), _OK)

    await _once(ctx, {"tenhalf_bet_amount": 99999}, client)

    assert client.posts and client.posts[0][0] == "/api/portal/tenhalf/action"
    body = client.posts[0][1]
    assert body["action"] == "join" and body["amount"] == 500  # 夹到单桌上限
    assert "requestKey" in body
    assert any("加入十点半" in str(msg) for msg, _ in ctx.notifications)


@pytest.mark.asyncio
async def test_signup_skipped_when_already_joined_or_not_joinable() -> None:
    ctx = _FakeCtx()
    joined = _game(phase="signup", actions=[], players=[{"isSelf": True, "betAmount": 100}])
    client = _FakeClient(joined, _OK)
    await _once(ctx, {}, client)
    assert client.posts == []

    # actions 无 join（满员/已截止）
    client = _FakeClient(_game(phase="signup", actions=["status"]), _OK)
    await _once(ctx, {}, client)
    assert client.posts == []


@pytest.mark.asyncio
async def test_join_failure_not_retried_same_round() -> None:
    # 报名失败后本局不再重试，避免每轮轮询撞同一个拒绝
    ctx = _FakeCtx()
    client = _FakeClient(_game(phase="signup", actions=["join"]), [_FAIL, _OK])

    await _once(ctx, {}, client)
    await _once(ctx, {}, client)

    assert len(client.posts) == 1
    assert any(level == "warning" for _, level in ctx.notifications)


# ── 玩家抓牌阶段 ──


def _draw_state(total: float, actions: list[str] | None = None) -> dict[str, object]:
    return _game(
        phase="player_draw",
        actions=actions or ["hit", "stand"],
        players=[
            {"isSelf": True, "betAmount": 100, "cardCount": 2},
            {"dealer": True, "displayName": "麦克格雷涛", "cardCount": 2},
        ],
        self_total=total,
    )


@pytest.mark.asyncio
async def test_player_draw_hits_below_threshold() -> None:
    ctx = _FakeCtx()
    client = _FakeClient(_draw_state(5), _OK)

    await _once(ctx, {"tenhalf_stand_threshold": 8}, client)

    assert client.posts and client.posts[0][1]["action"] == "hit"
    # 要牌/停牌过程不推送，每局只在结算时推一次（v1.17.2），动作只记日志
    assert ctx.notifications == []
    assert any("要牌" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_player_draw_stands_above_threshold() -> None:
    ctx = _FakeCtx()
    client = _FakeClient(_draw_state(9), _OK)

    await _once(ctx, {"tenhalf_stand_threshold": 8}, client)

    assert client.posts and client.posts[0][1]["action"] == "stand"


@pytest.mark.asyncio
async def test_player_draw_uses_ev_when_profile_present() -> None:
    """画像样本足够时 EV 递推取代阈值（决策日志带 EV 理由）。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:dealers", json.dumps({"麦克格雷涛": _EV_DEALER}))
    client = _FakeClient(_draw_state(9.5), _OK)

    await _once(ctx, {"tenhalf_stand_threshold": 20}, client)  # 阈值故意给高，验证没走阈值路径

    assert client.posts and client.posts[0][1]["action"] == "stand"
    assert any("EV" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_player_draw_stands_when_dealer_five_small() -> None:
    """庄家 5 张未爆 = 五小已定（全桌 ×5 判负），停牌早了结。"""
    ctx = _FakeCtx()
    state = _game(
        phase="player_draw",
        actions=["hit", "stand"],
        players=[
            {"isSelf": True, "betAmount": 100, "cardCount": 3},
            {"dealer": True, "displayName": "涛", "cardCount": 5},
        ],
        self_total=9,
    )
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["action"] == "stand"
    assert any("五小" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_notify_failure_does_not_break_poll() -> None:
    """通知渠道不可用（断网窗口）时吞异常只记日志，不冒泡到调度层（线上 08-18 事故）。"""

    class _BrokenCtx(_FakeCtx):
        async def notify(self, message: object, *args: object, **kwargs: object) -> None:
            raise RuntimeError("无可用通知渠道")

        async def notify_table(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("无可用通知渠道")

    ctx = _BrokenCtx()
    state = _game(active=False, last_result=_last_result(delta=198))
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)  # 不抛异常

    assert any("通知发送失败" in msg for _, msg in ctx.log.records)
    # 战绩照常入账，只有通知丢失
    stats = json.loads(str(ctx.kv.get("tenhalf:stats")))
    assert stats["total"]["rounds"] == 1


@pytest.mark.asyncio
async def test_player_draw_same_decision_not_resubmitted() -> None:
    # 服务端状态未变化（同局同点数同动作）时不重复提交
    ctx = _FakeCtx()
    client = _FakeClient(_draw_state(5), _OK)

    await _once(ctx, {}, client)
    await _once(ctx, {}, client)

    assert len(client.posts) == 1


@pytest.mark.asyncio
async def test_player_draw_skipped_when_not_joined_or_out() -> None:
    ctx = _FakeCtx()
    # 未报名（players 无 isSelf）
    state = _game(phase="player_draw", actions=["hit", "stand"], self_total=5)
    client = _FakeClient(state, _OK)
    await _once(ctx, {}, client)
    assert client.posts == []

    # 已爆牌出局
    state = _game(
        phase="player_draw",
        actions=["hit", "stand"],
        players=[{"isSelf": True, "bust": True}],
        self_total=11,
    )
    client = _FakeClient(state, _OK)
    await _once(ctx, {}, client)
    assert client.posts == []


# ── 结算入账 ──


@pytest.mark.asyncio
async def test_settlement_notifies_once_and_records_stats() -> None:
    ctx = _FakeCtx()
    state = _game(active=False, last_result=_last_result(delta=198))
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)
    await _once(ctx, {}, client)  # 第二次轮询同一条 lastResult 不重复入账

    assert len(ctx.tables) == 1
    headers, rows, kwargs = ctx.tables[0]
    assert kwargs.get("category") == "十点半" and kwargs.get("level") == "success"
    flat = [cell for row in rows for cell in row]
    assert "麦克格雷涛" in str(flat[1]) and "1局" in str(flat[-3])  # 庄家行与累计行
    stats = json.loads(str(ctx.kv.get("tenhalf:stats")))
    assert stats["total"] == {"rounds": 1, "net": 198, "wins": 1, "losses": 0}
    # 庄家画像入账：8.5 点一局
    dealers = json.loads(str(ctx.kv.get("tenhalf:dealers")))
    assert dealers["麦克格雷涛"] == {"rounds": 1, "totals": [8.5]}


@pytest.mark.asyncio
async def test_settlement_loss_notifies_success_level() -> None:
    """输局也按 success 推送：正常结算不算异常，不用 warning（v1.17.2）。"""
    ctx = _FakeCtx()
    state = _game(active=False, last_result=_last_result(delta=-100))
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)

    assert len(ctx.tables) == 1
    _, _, kwargs = ctx.tables[0]
    assert kwargs.get("level") == "success"


@pytest.mark.asyncio
async def test_settlement_without_self_only_records_dealer() -> None:
    # 未参与的局（self 为空）：不通知不计战绩，仍记庄家画像
    ctx = _FakeCtx()
    last = _last_result(delta=0)
    last["settlement"]["dealerHandLabel"] = "爆牌"
    state = _game(active=False, last_result=last)
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)

    assert ctx.tables == [] and ctx.kv.get("tenhalf:stats") is None
    dealers = json.loads(str(ctx.kv.get("tenhalf:dealers")))
    assert dealers["麦克格雷涛"] == {"rounds": 1, "busts": 1}


@pytest.mark.asyncio
async def test_state_error_resets_csrf_and_skips() -> None:
    ctx = _FakeCtx()
    client = _FakeClient({"_error": "timeout"}, _OK)

    await _once(ctx, {}, client)

    assert client.posts == []
    assert any(level == "WARNING" for level, _ in ctx.log.records)


# ── 结算补扫：快速局 settled 窗口短于轮询间隔，lastResult 错过后用 history 回查（v1.19.1）──


def _history_entry(rid: int, delta: int = -100) -> dict[str, object]:
    return {
        "roundId": rid,
        "amount": 500,
        "dealer": "麦克格雷涛",
        "settledAtMs": 1,
        "settlement": {
            "dealerDisplayName": "麦克格雷涛",
            "dealerHandLabel": "9点",
            "self": {"displayName": "Yy", "handLabel": "8点", "resultText": "点数小于庄家", "delta": delta},
            "results": [],
        },
    }


@pytest.mark.asyncio
async def test_catch_up_settles_missed_round_from_history() -> None:
    """停牌后轮询直接撞上新开局（lastResult 已翻篇）：history 补扫入账并推送。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    new_round = _game(phase="signup", round_id=1904, actions=["join"])
    new_round["game"]["history"] = [_history_entry(1903, delta=-100)]

    await _once(ctx, {}, _FakeClient(new_round, _OK))

    assert len(ctx.tables) == 1  # 结算推送没丢
    assert ctx.kv.get("tenhalf:last_round") == "1903"
    stats = json.loads(str(ctx.kv.get("tenhalf:stats")))
    assert stats["total"]["net"] == -100


@pytest.mark.asyncio
async def test_catch_up_once_then_no_duplicate() -> None:
    """补扫过一次后 last_round 已标记，后续轮询不重复入账。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    new_round = _game(phase="signup", round_id=1904, actions=["join"])
    new_round["game"]["history"] = [_history_entry(1903)]
    client = _FakeClient(new_round, _OK)

    await _once(ctx, {}, client)
    await _once(ctx, {}, client)

    assert len(ctx.tables) == 1


@pytest.mark.asyncio
async def test_catch_up_fallback_when_history_empty() -> None:
    """history 也没有该条：降级推送兜底（盈亏未知），不重复触发。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    new_round = _game(phase="signup", round_id=1904, actions=["join"])

    await _once(ctx, {}, _FakeClient(new_round, _OK))

    assert ctx.tables == []  # 无详情不组表
    assert any("盈亏未知" in str(msg) for msg, _ in ctx.notifications)
    assert ctx.kv.get("tenhalf:last_round") == "1903"
    assert ctx.kv.get("tenhalf:stats") is None  # 盈亏未知不入账战绩


@pytest.mark.asyncio
async def test_catch_up_waits_while_round_still_active() -> None:
    """报名的局还在进行中（active roundId == joined）不触发补扫。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    ongoing = _game(phase="player_draw", round_id=1903, actions=["hit", "stand"], self_total=5)

    await _catch_up_settlement(ctx, {}, ongoing["game"])

    assert ctx.notifications == [] and ctx.kv.get("tenhalf:last_round") is None


@pytest.mark.asyncio
async def test_join_records_round_for_catch_up() -> None:
    """报名成功时记下局号，供后续补扫定位。"""
    ctx = _FakeCtx()
    await _once(ctx, {}, _FakeClient(_game(phase="signup", actions=["join"]), _OK))
    assert ctx.kv.get("tenhalf:joined_round") == "501"
