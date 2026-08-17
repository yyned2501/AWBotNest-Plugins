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
    _decide,
    _join_amount,
    _once,
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
    # 样本足够时完全由画像推导：均点 9.5 无爆 → 9.5+0.5=10（夹到 10）
    dealers = {"涛": {"rounds": 9, "totals": [9.5] * 9}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 10
    # 样本不足不采信，退回配置基准
    assert _threshold_for({"tenhalf_stand_threshold": 8}, {"涛": {"rounds": 3, "totals": [9.5] * 3}}, "涛") == 8
    # 爆率 50% 让利 3 点：均点 8 → 8+0.5-3 = 5.5
    dealers = {"涛": {"rounds": 10, "busts": 5, "totals": [8.0] * 8}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 5.5
    # 爆率 80%：8+0.5-4.8=3.7 → 夹到下限 4（爆率高 4 点也敢停，堵庄家爆）
    dealers = {"涛": {"rounds": 10, "busts": 8, "totals": [8.0] * 6}}
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "涛") == 4.0
    # 只有爆牌样本（totals 为空）不推导，退回基准
    assert _threshold_for({"tenhalf_stand_threshold": 8}, {"涛": {"rounds": 12, "busts": 12}}, "涛") == 8


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
