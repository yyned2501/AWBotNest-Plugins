# -*- coding: utf-8 -*-
# 幸运轮盘免费抽奖测试：时刻解析/每日幂等、免费次数批量抽取、错误容错。
#
# 宿主依赖全部用 fake 隔离（复用 tenhalf 测试的 _FakeClient/_FakeCtx），不触碰真实门户。

from __future__ import annotations

import datetime
import inspect

import pytest

import plugins.skyGame.games.lucky as lucky
from tests.test_skygame_tenhalf import _FakeClient, _FakeCtx

# ── 时刻解析 ──


def test_draw_minutes_parsing_and_fallback() -> None:
    assert lucky._draw_minutes({}) == 23 * 60 + 50
    assert lucky._draw_minutes({"lucky_draw_time": "00:05"}) == 5
    assert lucky._draw_minutes({"lucky_draw_time": "22:30"}) == 22 * 60 + 30
    # 非法格式/越界 → 回退默认 23:50
    assert lucky._draw_minutes({"lucky_draw_time": "abc"}) == 23 * 60 + 50
    assert lucky._draw_minutes({"lucky_draw_time": "24:00"}) == 23 * 60 + 50
    assert lucky._draw_minutes({"lucky_draw_time": ""}) == 23 * 60 + 50


def test_should_draw_time_window_and_daily_idempotent() -> None:
    ctx = _FakeCtx()
    at_2349 = datetime.datetime(2026, 8, 19, 23, 49)
    at_2350 = datetime.datetime(2026, 8, 19, 23, 50)
    assert not lucky.should_draw({}, ctx.kv, now=at_2349)  # 未到点
    assert lucky.should_draw({}, ctx.kv, now=at_2350)  # 到点且今日未抽
    # 今天已抽过 → 不再抽
    ctx.kv.set(lucky._KV_LAST_DRAW_DATE, "2026-08-19")
    assert not lucky.should_draw({}, ctx.kv, now=at_2350)
    # 隔天 → 恢复可抽
    assert lucky.should_draw({}, ctx.kv, now=datetime.datetime(2026, 8, 20, 23, 50))
    # 禁用 → 不抽
    assert not lucky.should_draw({"lucky_enabled": False}, ctx.kv, now=at_2350)
    # 自定义时刻
    assert lucky.should_draw({"lucky_draw_time": "12:00"}, _FakeCtx().kv, now=at_2349)


# ── 抽奖执行 ──


def _spin_ok(count: int) -> dict[str, object]:
    return {
        "ok": True,
        "result": {
            "ok": True,
            "spinCount": count,
            "freeSpinCount": count,
            "costAmount": 0,
            "silverGain": 810,
            "balanceAfter": 117730,
            "summary": [{"label": "🤙 TG铁牌勋章 ×1（折算810银元）", "count": 1}],
        },
    }


@pytest.mark.asyncio
async def test_draw_free_spins_draws_all_in_one_batch() -> None:
    ctx = _FakeCtx()
    client = _FakeClient({"ok": True, "lucky": {"freeSpins": 3}}, _spin_ok(3))

    assert await lucky.draw_free_spins(ctx, {}, client)

    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == lucky._SPIN_PATH and body["count"] == 3  # 一次批量抽完
    assert "requestKey" in body
    assert ctx.notifications and "免费抽奖 ×3" in ctx.notifications[0][0]
    assert "TG铁牌勋章" in ctx.notifications[0][0] and "117,730" in ctx.notifications[0][0]


@pytest.mark.asyncio
async def test_draw_free_spins_no_free_returns_true_without_post() -> None:
    ctx = _FakeCtx()
    client = _FakeClient({"ok": True, "lucky": {"freeSpins": 0}}, {})

    assert await lucky.draw_free_spins(ctx, {}, client)

    assert client.posts == []  # 无免费次数不请求 spin，但记日期避免当天反复查询


@pytest.mark.asyncio
async def test_draw_free_spins_state_error_returns_false() -> None:
    ctx = _FakeCtx()
    client = _FakeClient({"_error": "门户 Cookie 已过期"}, {})

    assert not await lucky.draw_free_spins(ctx, {}, client)
    assert client.posts == []


@pytest.mark.asyncio
async def test_draw_free_spins_spin_failure_returns_false_no_notify() -> None:
    ctx = _FakeCtx()
    fail = {"ok": True, "result": {"ok": False, "message": "服务繁忙"}}
    client = _FakeClient({"ok": True, "lucky": {"freeSpins": 2}}, fail)

    assert not await lucky.draw_free_spins(ctx, {}, client)
    assert ctx.notifications == []  # 失败不推送，也不记日期（下分钟重试）


@pytest.mark.asyncio
async def test_draw_free_spins_notify_failure_swallowed() -> None:
    ctx = _FakeCtx()

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("渠道不可用")

    ctx.notify = _boom
    client = _FakeClient({"ok": True, "lucky": {"freeSpins": 1}}, _spin_ok(1))

    assert await lucky.draw_free_spins(ctx, {}, client)  # 通知失败不影响抽奖结果


# ── 调度接线 ──


def test_start_registers_zero_arg_tick() -> None:
    ctx = _FakeCtx()
    ctx.config = {}
    lucky.start(ctx)

    assert len(ctx.schedules) == 1
    fn, kind, kwargs = ctx.schedules[0]
    assert kind == "interval" and kwargs.get("seconds") == lucky._TICK_SECONDS
    assert inspect.signature(fn).parameters == {}  # 平台零参调用


def test_start_skips_schedule_when_disabled() -> None:
    ctx = _FakeCtx()
    ctx.config = {"lucky_enabled": False}

    lucky.start(ctx)

    assert ctx.schedules == []
