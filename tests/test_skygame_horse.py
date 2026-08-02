# -*- coding: utf-8 -*-
# skyGame · 养马遛马冷却退避与日志语义单元测试

from __future__ import annotations

import datetime

import pytest

from plugins.skyGame.games.horse import _care_once


def _now_ms() -> int:
    return int(datetime.datetime.now().timestamp() * 1000)


def _horse_state(
    walk_count: int = 3,
    walk_max: int = 4,
    can_walk: bool = True,
    satiety: int = 100,
) -> dict[str, object]:
    """构造可触发遛马分支的门户状态（饱腹度拉满以跳过喂食分支）。"""
    return {
        "horse": {
            "profile": {
                "state": {"isDead": False, "canWalk": can_walk, "canFeed": True},
                "satiety": satiety,
                "reviveCost": 300000,
            },
            "stats": {"walkCountToday": walk_count, "walkMax": walk_max, "feedCountToday": 1, "feedMax": 5},
            "balance": 100000,
        }
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

    def keys(self) -> list[str]:
        return list(self._d)

    def __contains__(self, key: str) -> bool:
        return key in self._d


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
        self.notifications: list[tuple[str, str]] = []

    async def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append((message, str(kwargs.get("level", "info"))))


class _FakeClient:
    def __init__(self, state: dict[str, object], action: dict[str, object]) -> None:
        self._state = state
        self._action = action
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def get(self, path: str) -> dict[str, object]:
        return self._state

    async def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, body))
        return self._action

    def reset_csrf(self) -> None:
        pass


@pytest.mark.asyncio
async def test_walk_cooldown_stores_remain_ms_and_stays_silent() -> None:
    # 正向：冷却响应记下 remainMs 退避时间；冷却走 debug，不通知、不误报失败
    ctx = _FakeCtx()
    action = {
        "ok": True,
        "result": {"ok": False, "code": "cooldown", "remainMs": 2811847, "message": "你的马刚遛过，47分钟 后再来。"},
    }
    client = _FakeClient(_horse_state(), action)
    before = _now_ms()

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:walk_cooldown_until") == pytest.approx(before + 2811847, abs=5000)
    assert len(client.posts) == 1
    assert ctx.notifications == []
    assert not any(level == "WARNING" for level, _ in ctx.log.records)
    assert not any("遛马成功" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_walk_in_cooldown_skips_without_posting() -> None:
    # 异常路径：冷却未到就不再发请求，避免每轮轮询撞冷却刷日志
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_cooldown_until", _now_ms() + 600000)
    client = _FakeClient(_horse_state(), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts == []
    assert any(level == "DEBUG" and "冷却中" in msg for level, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_walk_success_logs_once_and_clears_state() -> None:
    # 正向：真成功才打「遛马成功」，清零失败计数并清除冷却标记
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_consecutive_failures", 2)
    action = {"ok": True, "result": {"ok": True, "message": "遛马收获 126 银元"}}
    client = _FakeClient(_horse_state(walk_count=3, walk_max=4), action)

    await _care_once(ctx, {}, client)

    assert any(level == "INFO" and "遛马成功（今日 4/4）" in msg for level, msg in ctx.log.records)
    assert ctx.kv.get("horse:walk_consecutive_failures") == 0
    assert "horse:walk_cooldown_until" not in ctx.kv
    assert len(ctx.notifications) == 1
    assert ctx.notifications[0][1] == "info"


@pytest.mark.asyncio
async def test_walk_genuine_failure_warns_and_counts() -> None:
    # 异常路径：非冷却的真失败累计失败计数并以 warning 记录
    ctx = _FakeCtx()
    action = {"ok": True, "result": {"ok": False, "code": "exhausted", "message": "马匹体力不足"}}
    client = _FakeClient(_horse_state(), action)

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:walk_consecutive_failures") == 1
    assert any(level == "WARNING" and "遛马失败" in msg for level, msg in ctx.log.records)
    assert ctx.notifications and ctx.notifications[0][1] == "warning"


@pytest.mark.asyncio
async def test_walk_skips_after_three_consecutive_failures() -> None:
    # 异常路径：连续失败 3 次后停手，不再发请求
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_consecutive_failures", 3)
    client = _FakeClient(_horse_state(), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts == []
    assert any("连续失败" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_state_request_error_warns_with_readable_fallback() -> None:
    # 异常路径：状态请求失败且异常无消息时，日志兜底为可读文案而非空
    ctx = _FakeCtx()
    client = _FakeClient({"_error": ""}, {})

    await _care_once(ctx, {}, client)

    assert any(level == "WARNING" and "未知网络错误" in msg for level, msg in ctx.log.records)
