# -*- coding: utf-8 -*-
# skyGame · 掉落守卫（drop_guard）单元测试
#
# 覆盖：/info 回复解析与暂停状态翻转通知、paused 判定语义（新鲜度/缺省）、
# 低频 tick 的 /info 发送节流、start 接线，以及十点半报名被掉落配额拦截的集成。
# 宿主依赖全部用 fake 隔离，不触碰真实 Telegram。

from __future__ import annotations

import inspect
import json
import time

import pytest

import plugins.skyGame.games.drop_guard as dg
from plugins.skyGame.games.tenhalf import _once
from tests.test_skygame_tenhalf import _OK, _FakeClient, _FakeCtx, _game, _last_result


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


class _FakeUser:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, target: object, text: str) -> None:
        self.sent.append((str(target), text))


class _GuardCtx:
    def __init__(self) -> None:
        self.kv = _FakeKV()
        self.log = _FakeLog()
        self.config: dict[str, object] = {}
        self.user = _FakeUser()
        self.notifications: list[str] = []
        self.schedules: list[tuple[object, str, dict[str, object]]] = []

    def schedule(self, fn: object, mode: str, **kwargs: object) -> None:
        self.schedules.append((fn, mode, dict(kwargs)))

    async def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


def _set_full(ctx: _GuardCtx, remaining: int = 0, age: float = 0.0) -> None:
    """写入 remaining + checked_ts（age 秒前）。"""
    ctx.kv.set(dg._KV_REMAINING, remaining)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time() - age)


# ── 纯函数 ──


def test_parse_bot_ids_defaults_and_formats() -> None:
    assert dg._parse_bot_ids("") == [dg._DEFAULT_BOT]
    assert dg._parse_bot_ids("8907007783") == [8907007783]
    assert dg._parse_bot_ids("@abc，123") == ["abc", 123]


def test_paused_semantics() -> None:
    ctx = _GuardCtx()
    assert dg.paused(ctx) is False  # 从未查过 → 照常参与
    _set_full(ctx, remaining=0)
    assert dg.paused(ctx) is True  # 剩余 0 且结果新鲜 → 暂停
    _set_full(ctx, remaining=0, age=dg._STALE_AFTER + 60)
    assert dg.paused(ctx) is False  # 结果过期 → 自动解锁（防误判锁死）
    _set_full(ctx, remaining=3)
    assert dg.paused(ctx) is False  # 还有剩余 → 照常参与


def test_paused_clears_at_hour_boundary() -> None:
    """v1.23.7：时段按整点轮换，跨整点后配额必然刷新——不等 /info 回执直接恢复。"""
    ctx = _GuardCtx()
    now_ts = time.time()
    # 找「最近的跨整点时刻」：从当前逐秒回退，必然在 1 小时内跨小时（且 < 过期阈值）
    prev = now_ts
    while dg._same_hour(prev, now_ts):
        prev -= 1.0
    _set_full(ctx, remaining=0)
    ctx.kv.set(dg._KV_CHECKED_TS, prev)
    assert now_ts - prev < dg._STALE_AFTER  # 未过期，确保走「跨整点」而非「过期」分支
    assert dg.paused(ctx) is False  # 上次 /info 是上一时段的事 → 已恢复
    # 同时段（未跨整点）仍保持暂停
    _set_full(ctx, remaining=0)
    assert dg.paused(ctx) is True


def test_parse_remaining_new_and_legacy_format() -> None:
    # 新格式（2026-08-19 实测）：配额拆成聊天/游戏两类，守卫只认「游戏」
    assert dg.parse_remaining("当前时段剩余掉落: 聊天 3 · 游戏 0") == 0
    assert dg.parse_remaining("当前时段剩余掉落：聊天 3 · 游戏 5") == 5
    # 旧格式纯数字兼容
    assert dg.parse_remaining("当前时段剩余掉落：2") == 2
    assert dg.parse_remaining("你好") is None


@pytest.mark.asyncio
async def test_apply_reply_toggles_pause_and_notifies_once() -> None:
    ctx = _GuardCtx()

    assert await dg.apply_reply(ctx, "📊 统计\n当前时段剩余掉落: 聊天 3 · 游戏 0\n今日掉落 12") is True
    assert dg.paused(ctx) is True
    assert len(ctx.notifications) == 1 and "暂停" in ctx.notifications[0]

    # 状态不变不重复通知
    await dg.apply_reply(ctx, "当前时段剩余掉落: 聊天 1 · 游戏 0")
    assert len(ctx.notifications) == 1

    # 时段刷新恢复：再通知一次
    await dg.apply_reply(ctx, "当前时段剩余掉落: 聊天 3 · 游戏 5")
    assert dg.paused(ctx) is False
    assert len(ctx.notifications) == 2 and "恢复" in ctx.notifications[1]

    # 无关消息不解析、不改动状态
    assert await dg.apply_reply(ctx, "你好，需要什么帮助？") is False
    assert ctx.kv.get(dg._KV_REMAINING) == 5


# ── 低频 tick：/info 发送节流 ──


@pytest.mark.asyncio
async def test_guard_tick_sends_info_every_fire() -> None:
    """cron 模式：每次触发都发 /info（频率由调度器保证，tick 内不再自算间隔节流）。"""
    ctx = _GuardCtx()
    ctx.config = {"drop_guard_enabled": True, "drop_guard_interval": 10}

    await dg._guard_tick(ctx)  # 纯数字 ID 转 int，不带 @
    assert ctx.user.sent == [("8907007783", "/info")]
    assert ctx.kv.get(dg._KV_SENT_TS)

    # cron 再次触发（即使刚发过）→ 再发，不再节流
    await dg._guard_tick(ctx)
    assert len(ctx.user.sent) == 2

    # 关闭开关 → 不发
    ctx.config["drop_guard_enabled"] = False
    await dg._guard_tick(ctx)
    assert len(ctx.user.sent) == 2


@pytest.mark.asyncio
async def test_guard_ignores_global_bot_config() -> None:
    # 全局 bot 配置可能是别的 bot（如 HDSky 验证 bot），守卫只认 drop_guard_bot，
    # 留空回退默认天空小秘（v1.22.1）
    ctx = _GuardCtx()
    ctx.config = {"drop_guard_enabled": True, "bot": "@HDSkyVerify_bot"}
    await dg._guard_tick(ctx)
    assert ctx.user.sent == [("8907007783", "/info")]


@pytest.mark.asyncio
async def test_guard_tick_send_failure_does_not_raise() -> None:
    ctx = _GuardCtx()
    ctx.config = {"drop_guard_enabled": True}

    async def _broken_send(target: object, text: str) -> None:
        raise RuntimeError("网络错误")

    ctx.user.send = _broken_send  # type: ignore[method-assign]
    await dg._guard_tick(ctx)  # 吞异常只记日志
    assert any("发送失败" in msg for _, msg in ctx.log.records)


# ── start 接线 ──


class _F:
    def __and__(self, other: object) -> "_F":
        return self


def test_start_registers_handler_and_zero_arg_tick() -> None:
    ctx = _GuardCtx()
    registered: list[tuple[object, int]] = []

    class _Filters:
        private = _F()
        text = _F()

        @staticmethod
        def user(ids: object) -> _F:
            return _F()

    ctx.filters = _Filters  # type: ignore[attr-defined]

    def _on_message(f: object, group: int = 0) -> object:
        def deco(fn: object) -> object:
            registered.append((fn, group))
            return fn

        return deco

    ctx.on_message = _on_message  # type: ignore[attr-defined]

    dg.start(ctx)

    assert len(registered) == 1 and registered[0][1] == 7
    assert len(ctx.schedules) == 1
    fn, mode, kwargs = ctx.schedules[0]
    assert mode == "cron" and kwargs.get("id") == "drop_guard_tick"
    assert kwargs.get("minute") == "*/10"  # drop_guard_interval 默认 10 → cron */10 整点对齐
    assert len(inspect.signature(fn).parameters) == 0


def test_start_cron_minute_follows_interval() -> None:
    """cron 表达式由 drop_guard_interval 生成，并 clamp 到 [5, 60]。"""

    class _Filters:
        private = _F()
        text = _F()

        @staticmethod
        def user(ids: object) -> _F:
            return _F()

    def _minute_for(cfg_interval: object) -> object:
        ctx = _GuardCtx()
        ctx.config = {"drop_guard_interval": cfg_interval}
        ctx.filters = _Filters  # type: ignore[attr-defined]
        ctx.on_message = lambda f, group=0: lambda fn: fn  # type: ignore[attr-defined]
        dg.start(ctx)
        return ctx.schedules[0][2].get("minute")

    assert _minute_for(30) == "*/30"
    assert _minute_for(2) == "*/5"  # 低于下限 clamp 到 5
    assert _minute_for(999) == "*/60"  # 高于上限 clamp 到 60
    assert _minute_for(None) == "*/10"  # 缺省回退 10


# ── 集成：十点半报名被掉落配额拦截 ──


@pytest.mark.asyncio
async def test_tenhalf_signup_blocked_when_drop_full() -> None:
    ctx = _FakeCtx()
    ctx.kv.set(dg._KV_REMAINING, 0)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time())
    client = _FakeClient(_game(phase="signup", actions=["join"]), _OK)

    await _once(ctx, {"tenhalf_bet_amount": 200}, client)

    assert client.posts == []  # 配额满且未参与 → _once 顶部直接返回，不报名

    # 配额恢复（剩余 > 0）→ 照常报名
    ctx.kv.set(dg._KV_REMAINING, 2)
    await _once(ctx, {"tenhalf_bet_amount": 200}, client)
    assert client.posts and client.posts[0][1]["action"] == "join"


@pytest.mark.asyncio
async def test_tenhalf_paused_not_joined_stops_settlement_and_actions() -> None:
    # v1.23.1：配额满且未参与当前局 → 停心跳：不结算不推送不动作
    ctx = _FakeCtx()
    ctx.kv.set(dg._KV_REMAINING, 0)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time())
    state = _game(phase="signup", actions=["join"], players=[{"isSelf": False, "displayName": "别人"}])
    client = _FakeClient(state, _OK)

    await _once(ctx, {"tenhalf_bet_amount": 200}, client)

    assert client.posts == []  # 不报名也不做任何动作
    assert ctx.notifications == []


@pytest.mark.asyncio
async def test_tenhalf_paused_still_plays_joined_round() -> None:
    # v1.23.1：配额满但已报名 → 照常打完本局（决策/结算不受暂停影响）
    ctx = _FakeCtx()
    ctx.kv.set(dg._KV_REMAINING, 0)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time())
    state = _game(
        phase="player_draw",
        actions=["hit", "stand"],
        players=[{"isSelf": True, "displayName": "我"}],
        self_total=3,
    )
    client = _FakeClient(state, _OK)

    await _once(ctx, {"tenhalf_bet_amount": 200}, client)

    assert client.posts and client.posts[0][1]["action"] == "hit"  # 低点数照常要牌


@pytest.mark.asyncio
async def test_tenhalf_paused_settlement_of_finished_round_not_swallowed() -> None:
    # v1.23.3 回归：刚结束那局的结算不得被暂停检查吞掉——局结束瞬间切到
    # 新局（self_p 已空）时，lastResult 结算仍要入账推送，然后才停心跳
    ctx = _FakeCtx()
    ctx.kv.set(dg._KV_REMAINING, 0)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time())
    ctx.kv.set("tenhalf:joined_round", "4244")
    state = _game(phase="signup", round_id=4245, actions=["join"], last_result=_last_result(rid=4244, delta=-100))
    client = _FakeClient(state, _OK)

    await _once(ctx, {}, client)

    assert ctx.tables, "结算表格推送丢失"
    assert ctx.kv.get("tenhalf:last_round") == "4244"
    stats = json.loads(str(ctx.kv.get("tenhalf:stats")))
    assert stats["total"]["net"] == -100
    assert client.posts == []  # 暂停下仍不新报名
