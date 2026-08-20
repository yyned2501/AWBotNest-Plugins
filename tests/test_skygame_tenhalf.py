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
    _dealer_profile_text,
    _decide,
    _decide_ev,
    _decide_text,
    _ev_play,
    _join_amount,
    _observe_dealer,
    _once,
    _points_dist_text,
    _pop_dealer_obs,
    _pop_decision_log,
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
    self_cards: list[str] | None = None,
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
        game["self"] = {"cards": self_cards or [], "total": self_total, "status": ""}
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
    assert dealers["涛"] == {"name": "涛", "rounds": 3, "busts": 2, "totals": [8.5]}


def test_record_dealer_keys_by_stable_id() -> None:
    """传稳定 id 时画像以 id 为主键，改名后自动归并同一画像（v1.23.5）。"""
    ctx = _FakeCtx()
    _record_dealer(ctx, {"dealerDisplayName": "老名字", "dealerHandLabel": "8点"}, dealer_key="id:201")
    _record_dealer(ctx, {"dealerDisplayName": "新名字", "dealerHandLabel": "8点"}, dealer_key="id:201")
    dealers = json.loads(str(ctx.kv.get("tenhalf:dealers")))
    assert set(dealers) == {"id:201"}  # 只有一个画像，没有按名字拆成两份
    entry = dealers["id:201"]
    assert entry["rounds"] == 2
    assert entry["name"] == "新名字"  # 展示名刷成最新
    assert len(entry["totals"]) == 2  # 改名后的局也计入同一画像


# ── 庄家画像按手牌张数分桶 ──


def test_record_dealer_buckets_by_card_count() -> None:
    """传 cards 时同步计入按张数分桶；爆牌计入桶的 busts、不入桶点数样本。"""
    ctx = _FakeCtx()
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "8点"}, cards=3, dealer_key="id:9")
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "11点"}, cards=3, dealer_key="id:9")  # 爆牌
    _record_dealer(ctx, {"dealerDisplayName": "涛", "dealerHandLabel": "9点"}, cards=4, dealer_key="id:9")
    entry = json.loads(str(ctx.kv.get("tenhalf:dealers")))["id:9"]
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


def test_dealer_profile_text_shows_card_bucket_only() -> None:
    """结算推送庄家行（v1.23.10）：只显示当前手牌张数分桶（点数分布+爆数），不再并列聚合。"""
    dealers = {
        "涛": {
            "rounds": 30,
            "busts": 10,
            "totals": [8.9] * 28,
            "cards": {"4": {"rounds": 3, "busts": 1, "totals": [9.0] * 2}},
        }
    }
    text = _dealer_profile_text(dealers, "涛", cards=4)
    assert text == "4张 3局：9点×2/爆×1"
    # 桶无样本 → 退回聚合画像
    plain = {"涛": {"rounds": 30, "busts": 10, "totals": [8.9] * 28}}
    assert _dealer_profile_text(plain, "涛", cards=4) == "30局·均 8.9 点·爆率 33%"
    assert _dealer_profile_text(plain, "涛") == "30局·均 8.9 点·爆率 33%"
    assert _dealer_profile_text({}, "涛") == ""


def test_points_dist_text_sorted_and_compacted() -> None:
    """逐点数分布：从低到高、同点数合并、×1 省略、爆牌殿后、全爆只显爆。"""
    assert _points_dist_text(1, [7.5, 7.0, 9.0, 7.5]) == "7点/7.5点×2/9点/爆×1"
    assert _points_dist_text(1, []) == "爆×1"
    assert _points_dist_text(0, [8.0]) == "8点"


def test_observe_and_pop_dealer_obs() -> None:
    """按 roundId 暂存观察：张数取最大（只增不减）、id 直接写入；弹出后清空。"""
    ctx = _FakeCtx()
    _observe_dealer(ctx, 777, {"cardCount": 2, "accountId": 201})
    _observe_dealer(ctx, 777, {"cardCount": 3, "accountId": 201})
    _observe_dealer(ctx, 777, {"cardCount": 1, "accountId": 201})  # 不回退
    assert _pop_dealer_obs(ctx, 777) == (3, "id:201")
    assert _pop_dealer_obs(ctx, 777) == (None, None)  # 已弹出
    _observe_dealer(ctx, 778, {})  # 无 cardCount 无 id 不记录
    assert _pop_dealer_obs(ctx, 778) == (None, None)
    _observe_dealer(ctx, 779, {"accountId": 202})  # 仅 id（无张数）也记录
    assert _pop_dealer_obs(ctx, 779) == (None, "id:202")


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
    action, reason, _, _, _ = _decide_ev(5, 0, ["hit", "stand"], True, None, dist)
    assert action == "stand" and "爆牌" in reason  # 庄家已爆优先
    action, _, _, _, _ = _decide_ev(5, 5, ["hit", "stand"], False, None, dist)
    assert action == "stand"  # 已五小直接赢 ×5
    action, _, ev_hit, ev_stand, _ = _decide_ev(5, 0, ["hit", "stand"], False, None, dist)
    assert action == "hit"  # 要牌 EV -0.37 > 停牌 -0.40
    assert ev_hit > ev_stand  # EV 数值随决策返回（供轨迹展示）
    action, _, _, _, _ = _decide_ev(9.5, 2, ["hit", "stand"], False, None, dist)
    assert action == "stand"  # 9.5 点几乎稳赢，要牌只会招爆
    action, _, _, _, _ = _decide_ev(4, 4, ["hit", "stand"], False, None, dist)
    assert action == "hit"  # 4 张低点数追五小 ×5（EV +3.15）
    action, _, ev_hit, ev_stand, _ = _decide_ev(8.5, 4, ["hit", "stand"], False, None, dist)
    # 4 张 8.5 差一张成五小：1/2/JQK 共 20 张可成（≈5/13），要牌 EV 为正
    assert action == "hit" and isinstance(ev_hit, float) and isinstance(ev_stand, float)
    action, _, _, _, _ = _decide_ev(10.5, 4, ["hit", "stand"], False, None, dist)
    assert action == "stand"  # 4 张 10.5 已至目标，再拿必爆
    action, _, _, _, _ = _decide_ev(4, 2, ["hit", "stand"], False, 9.0, dist)
    assert action == "hit"  # 庄家 9 点可见：点质量分布，反败优于停牌
    assert _decide_ev(5, 0, [], False, None, dist)[0] is None


def test_decide_ev_five_small_three_way_choice() -> None:
    """庄家疑似五小（v1.23.11）：停牌/爆牌按 ×5 判负，认输 EV(-1) 第三选项三方择优。"""
    # 0 张：要牌 -4.35 < 认输 -1 < 停牌 -5 → 认输止损（只亏本金 ×1）
    action, reason, ev_hit, ev_stand, ev_fold = _decide_ev(
        0, 0, ["hit", "stand", "fold"], False, None, (0.0, []), dealer_five_small=True
    )
    assert action == "fold" and ev_fold == -1.0 and ev_stand == -5.0
    assert ev_hit == pytest.approx(-4.3492, abs=1e-4) and ev_fold > ev_hit > ev_stand
    assert "认输" in reason
    # 4 张 4.5 点：成五小牌 36/52 ≈ 69%，追五小 EV +1.92 最优（停牌 -5/认输 -1 殿后）
    action, _, ev_hit, ev_stand, ev_fold = _decide_ev(
        4.5, 4, ["hit", "stand", "fold"], False, None, (0.0, []), dealer_five_small=True
    )
    assert action == "hit" and ev_hit == pytest.approx(1.9231, abs=1e-4) and ev_fold == -1.0
    # 9.5 点 2 张：要牌必爆 -5、停牌 -5，认输 -1 保本
    action, _, _, _, ev_fold = _decide_ev(
        9.5, 2, ["hit", "stand", "fold"], False, None, (0.0, []), dealer_five_small=True
    )
    assert action == "fold" and ev_fold == -1.0
    # 门户未开放认输：无第三选项，要牌/停牌照常择优（9 点 3 张：要牌 -4.11 > 停牌 -5）
    action, _, ev_hit, ev_stand, ev_fold = _decide_ev(
        9, 3, ["hit", "stand"], False, None, (0.0, []), dealer_five_small=True
    )
    assert action == "hit" and ev_fold is None and ev_hit > ev_stand
    # 庄家实际已爆（5 张 bust 先行拦截）：停牌即赢，认输选项不生效
    action, _, _, _, ev_fold = _decide_ev(5, 0, ["hit", "stand", "fold"], True, None, (0.0, []), dealer_five_small=True)
    assert action == "stand" and ev_fold is None


def test_decide_text_appends_fold_ev() -> None:
    """决策轨迹追加认输 EV 第三值（半角括号、动态符号、×100 取整）。"""
    assert _decide_text(0, [], "fold", -4.3492, -5.0, -1.0) == "认输 0：拿牌ev(-435)>停牌ev(-500) 认输ev(-100)"
    assert _decide_text(4.5, ["A♥", "3♣", "J♥", "Q♣"], "hit", 1.9231, -5.0, -1.0).endswith(
        "拿牌ev(192)>停牌ev(-500) 认输ev(-100)"
    )
    # 常规路径（无认输选项）：保持两值对比，不带认输 EV
    assert _decide_text(5, [], "hit", -0.37, -0.4) == "要牌 5：拿牌ev(-37)>停牌ev(-40)"


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


def _draw_state_top_dealer(total: float, dealer: dict[str, object]) -> dict[str, object]:
    """线上真实结构：庄家是顶层 game.dealer，players 里每人 dealer 都是 False。"""
    state = _draw_state(total)
    state["game"]["dealer"] = dealer
    state["game"]["players"] = [p for p in state["game"]["players"] if not p.get("dealer")]
    return state


@pytest.mark.asyncio
async def test_player_draw_uses_ev_with_top_level_dealer() -> None:
    """v1.23.4 回归：线上庄家在 game.dealer 顶层字段，必须能命中画像走 EV。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:dealers", json.dumps({"麦克格雷涛": _EV_DEALER}))
    state = _draw_state_top_dealer(9.5, {"displayName": "麦克格雷涛", "cardCount": 2, "bust": False, "total": None})
    client = _FakeClient(state, _OK)

    await _once(ctx, {"tenhalf_stand_threshold": 20}, client)  # 阈值故意给高，验证没走阈值路径

    assert client.posts and client.posts[0][1]["action"] == "stand"
    assert any("EV" in msg for _, msg in ctx.log.records)


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


@pytest.mark.asyncio
async def test_player_draw_ev_choices_when_dealer_five_small() -> None:
    """庄家 5 张（疑似五小，v1.23.11）：照常 EV 择优；0 张认输止损、4 张追五小、已爆停牌。"""
    # 0 张 + fold 开放：认输 EV -1 最优（要牌 -4.35/停牌 -5.00），止损只亏本金 ×1
    ctx = _FakeCtx()
    client = _FakeClient(
        _game(
            phase="player_draw",
            actions=["fold", "hit", "stand"],
            players=[
                {"isSelf": True, "betAmount": 100, "cardCount": 0},
                {"dealer": True, "displayName": "涛", "cardCount": 5},
            ],
            self_total=0,
        ),
        _OK,
    )
    await _once(ctx, {}, client)
    assert client.posts and client.posts[0][1]["action"] == "fold"
    assert any("认输" in msg for _, msg in ctx.log.records)
    steps = _pop_decision_log(ctx, 501)
    assert steps and steps[0][2] == "fold" and steps[0][5] == -1.0  # 认输进决策轨迹并带 EV
    # 4 张 4.5 点 + fold 开放：追五小 EV +1.92 最优，不认输（新行为：不再硬编码停牌认亏）
    client = _FakeClient(
        _game(
            phase="player_draw",
            actions=["fold", "hit", "stand"],
            players=[
                {"isSelf": True, "betAmount": 100, "cardCount": 4},
                {"dealer": True, "displayName": "涛", "cardCount": 5},
            ],
            self_total=4.5,
        ),
        _OK,
    )
    await _once(ctx, {}, client)
    assert client.posts and client.posts[0][1]["action"] == "hit"
    # 庄家实际已爆（5 张 bust=True）：停牌即赢，认输选项不生效
    client = _FakeClient(
        _game(
            phase="player_draw",
            actions=["fold", "hit", "stand"],
            players=[
                {"isSelf": True, "betAmount": 100, "cardCount": 0},
                {"dealer": True, "displayName": "涛", "cardCount": 5, "bust": True},
            ],
            self_total=0,
        ),
        _OK,
    )
    await _once(ctx, {}, client)
    assert client.posts and client.posts[0][1]["action"] == "stand"
    assert any("爆牌" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_player_draw_records_decision_trace() -> None:
    """EV 决策提交成功后记入本局决策轨迹（点数/手牌/拿牌EV/停牌EV）。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:dealers", json.dumps({"麦克格雷涛": _EV_DEALER}))
    state = _draw_state_top_dealer(9.5, {"displayName": "麦克格雷涛", "cardCount": 2, "bust": False, "total": None})
    state["game"]["self"] = {"cards": ["6♣", "3♣"], "total": 9.5, "status": ""}
    client = _FakeClient(state, _OK)

    await _once(ctx, {"tenhalf_stand_threshold": 20}, client)

    steps = _pop_decision_log(ctx, 501)
    assert len(steps) == 1
    total, hand, action, ev_hit, ev_stand, ev_fold = steps[0]
    assert action == "stand" and total == 9.5 and hand == "6♣ 3♣"
    assert isinstance(ev_hit, float) and isinstance(ev_stand, float) and ev_fold is None
    text = _decide_text(total, hand.split(), action, ev_hit, ev_stand, ev_fold)
    assert text.startswith("停牌 9.5(6♣ 3♣)") and "拿牌ev(" in text and "停牌ev(" in text


@pytest.mark.asyncio
async def test_settlement_push_includes_decision_trace() -> None:
    """结算推送表格带本局决策轨迹，每条决策单独一行（动作在首、EV 对比收尾）。"""
    ctx = _FakeCtx()
    # 局 501：先走一手要牌（EV 路径），再走一手停牌（EV 路径），共两条轨迹
    ctx.kv.set("tenhalf:dealers", json.dumps({"麦克格雷涛": _EV_DEALER}))
    state = _draw_state_top_dealer(6, {"displayName": "麦克格雷涛", "cardCount": 2, "bust": False, "total": None})
    state["game"]["self"] = {"cards": ["3♣"], "total": 3, "status": ""}
    await _once(ctx, {"tenhalf_stand_threshold": 20}, _FakeClient(state, _OK))
    state["game"]["self"] = {"cards": ["6♣", "3♣"], "total": 9.5, "status": ""}
    await _once(ctx, {"tenhalf_stand_threshold": 20}, _FakeClient(state, _OK))
    settled = _game(active=False, last_result=_last_result(rid=501, delta=99))
    await _once(ctx, {}, _FakeClient(settled, _OK))

    assert len(ctx.tables) == 1
    headers, rows, _ = ctx.tables[0]
    labels = [str(row[0]) for row in rows]
    assert "📜 决策轨迹" in labels
    trace_rows = [row for row in rows if str(row[0]).startswith("📜 决策轨迹") or row[0] == ""]
    # 首行带标题、后续行空 label，且不含 \n 拼接（每条单独成行）
    assert len(trace_rows) >= 2
    assert str(trace_rows[0][1]).startswith("要") and "拿牌ev(" in str(trace_rows[0][1])
    assert str(trace_rows[1][1]).startswith("停牌") and "停牌ev(" in str(trace_rows[1][1])
    assert "\n" not in str(trace_rows[0][1])
    assert _pop_decision_log(ctx, 501) == []  # 推送后轨迹已取走


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
    assert dealers["麦克格雷涛"] == {"name": "麦克格雷涛", "rounds": 1, "totals": [8.5]}


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
    assert dealers["麦克格雷涛"] == {"name": "麦克格雷涛", "rounds": 1, "busts": 1}


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
async def test_catch_up_skipped_when_last_round_already_advanced() -> None:
    """v1.23.2 回归：_handle_settlement 已入账更大局号（lastResult 推进）后，
    joined 局号即使还在 history 里也不重复入账（旧相等比较每轮都会重记）。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    ctx.kv.set("tenhalf:last_round", "1905")
    state = _game(phase="signup", round_id=1906, actions=["join"])
    state["game"]["history"] = [_history_entry(1903)]

    await _catch_up_settlement(ctx, {}, state["game"])

    assert ctx.tables == [] and ctx.notifications == []
    assert ctx.kv.get("tenhalf:last_round") == "1905"  # 不回退成小值
    assert ctx.kv.get("tenhalf:stats") is None  # 不重复入账


@pytest.mark.asyncio
async def test_catch_up_no_repeated_fallback_after_advanced() -> None:
    """v1.23.2 回归：joined 局号已落后且不在 history —— 不每轮兜底推送。"""
    ctx = _FakeCtx()
    ctx.kv.set("tenhalf:joined_round", "1903")
    ctx.kv.set("tenhalf:last_round", "1905")

    await _catch_up_settlement(ctx, {}, _game(phase="signup", round_id=1906)["game"])

    assert ctx.notifications == []
    assert ctx.kv.get("tenhalf:last_round") == "1905"


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


# ── 全局画像兜底（v1.23.10）：本庄样本不足用其余所有庄家的画像合计代表 ──


def test_dealer_dist_falls_back_to_global_aggregate() -> None:
    """新庄家（无画像）用全体庄家合计分布；本人样本不足查全局时排除本人。"""
    dealers = {
        "甲": {"rounds": 6, "busts": 1, "totals": [8.0] * 5},  # 聚合不足 8
        "乙": {"rounds": 7, "busts": 2, "totals": [9.0] * 5},  # 聚合不足 8
    }
    p_bust, samples = _dealer_dist(dealers, "丙", None)
    assert p_bust == pytest.approx(3 / 13) and sorted(samples) == sorted([8.0] * 5 + [9.0] * 5)
    # 查「甲」（本庄 6 局不足）→ 全局排除甲后只剩乙 7 局，仍不足 → None
    assert _dealer_dist(dealers, "甲", None) is None
    # 稳定 id 键 + 展示名都能正确排除本人
    dealers2 = {"id:9": {"name": "丙", "rounds": 6, "totals": [8.0] * 6}, "乙": {"rounds": 10, "totals": [9.0] * 8}}
    p_bust, samples = _dealer_dist(dealers2, "丙", None, dealer_key="id:9")
    assert p_bust == 0.0 and samples == [9.0] * 8


def test_dealer_dist_global_bucket_then_aggregate() -> None:
    """本庄无样本时全局分桶优先于全局聚合（桶样本≥3 用桶）。"""
    dealers = {
        "甲": {"rounds": 5, "totals": [7.0] * 5, "cards": {"3": {"rounds": 2, "totals": [6.0]}}},
        "乙": {"rounds": 5, "totals": [7.0] * 5, "cards": {"3": {"rounds": 2, "busts": 1, "totals": [6.0]}}},
    }
    p_bust, samples = _dealer_dist(dealers, "丙", 3)
    assert p_bust == pytest.approx(1 / 4) and samples == [6.0, 6.0]  # 全局 3 张桶合计 4 局
    p_bust, samples = _dealer_dist(dealers, "丙", None)
    assert p_bust == 0.0 and samples == [7.0] * 10  # 无张数 → 全局聚合


def test_threshold_for_falls_back_to_global() -> None:
    """本庄样本不足 → 全局画像推导阈值；全局也不足才退配置基准。"""
    dealers = {
        "甲": {"rounds": 10, "busts": 8, "totals": [9.0] * 2},
        "乙": {"rounds": 10, "busts": 8, "totals": [9.0] * 2},
    }
    # 全局合计 20 局爆 16：均 9 → 9+0.5-3.2=6.3 → 6.5（红线上限夹取后也到 6.5）
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "丙") == 6.5
    # 全局只有本人 → 无兜底，退配置基准
    assert _threshold_for({"tenhalf_stand_threshold": 8}, {"甲": {"rounds": 3, "totals": [9.5] * 3}}, "甲") == 8


def test_threshold_global_bucket_lower_bound() -> None:
    """全局 3 张桶均 5 无爆 → 阈值 5.5（无红线问题，直接生效）。"""
    dealers = {
        "甲": {"rounds": 10, "totals": [9.5] * 9, "cards": {"3": {"rounds": 3, "totals": [5.0] * 3}}},
        "乙": {"rounds": 10, "totals": [9.5] * 9, "cards": {"3": {"rounds": 3, "totals": [5.0] * 3}}},
    }
    assert _threshold_for({"tenhalf_stand_threshold": 8}, dealers, "丙", dealer_cards=3) == 5.5


def test_dealer_profile_text_marks_global_representative() -> None:
    """本庄无画像时用全局当前张数桶代表并标注「全局画像」；全体为空返回空串。"""
    dealers = {
        "甲": {
            "rounds": 10,
            "busts": 3,
            "totals": [8.0] * 7,
            "cards": {"3": {"rounds": 3, "busts": 1, "totals": [6.0] * 2}},
        },
        "乙": {
            "rounds": 10,
            "busts": 3,
            "totals": [8.0] * 7,
            "cards": {"3": {"rounds": 3, "busts": 1, "totals": [6.0] * 2}},
        },
    }
    assert _dealer_profile_text(dealers, "丙", cards=3) == "全局画像 3张 6局：6点×4/爆×2"
    assert _dealer_profile_text(dealers, "丙") == "全局画像 20局·均 8.0 点·爆率 30%"
    assert _dealer_profile_text({}, "丙") == ""


def test_decide_text_uses_proper_comparison_symbol() -> None:
    """决策轨迹 EV 对比符号跟随大小：拿牌大用 >，停牌大用 <，相等用 =。"""
    assert "拿牌ev(50)>停牌ev(20)" in _decide_text(6, [], "hit", 0.5, 0.2)
    assert "拿牌ev(20)<停牌ev(50)" in _decide_text(6, [], "stand", 0.2, 0.5)
    assert "拿牌ev(40)=停牌ev(40)" in _decide_text(6, [], "stand", 0.4, 0.4)
