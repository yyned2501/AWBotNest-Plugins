# -*- coding: utf-8 -*-
# skyGame · 养马遛马冷却退避与日志语义单元测试

from __future__ import annotations

import datetime
import json

import pytest

from plugins.skyGame.games.horse import _care_once


def _now_ms() -> int:
    return int(datetime.datetime.now().timestamp() * 1000)


def _today() -> str:
    return datetime.date.today().isoformat()


def _yesterday() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _fail_state(count: int, date: str) -> str:
    """构造遛马失败计数 kv 值（JSON 字符串，与生产格式一致）。"""
    return json.dumps({"count": count, "date": date})


def _horse_state(
    walk_count: int = 3,
    walk_max: int = 4,
    can_walk: bool = True,
    satiety: int = 100,
    stamina: int = 100,
    match: dict[str, object] | None = None,
) -> dict[str, object]:
    """构造可触发遛马分支的门户状态（饱腹度拉满以跳过喂食分支）。"""
    state: dict[str, object] = {
        "horse": {
            "profile": {
                "state": {"isDead": False, "canWalk": can_walk, "canFeed": True},
                "satiety": satiety,
                "stamina": stamina,
                "reviveCost": 300000,
            },
            "stats": {"walkCountToday": walk_count, "walkMax": walk_max, "feedCountToday": 1, "feedMax": 5},
            "balance": 100000,
        }
    }
    if match is not None:
        state["horse"]["competitions"] = {"match": match}
    return state


def _active_match(joined: bool = False, amount: int = 100) -> dict[str, object]:
    """玩家养马赛 active 状态（portal-horse.js 确认的字段：actions 含 join 才可加入）。"""
    return {
        "active": True,
        "roundId": 1083,
        "host": "元宝",
        "amount": amount,
        "maxEntrants": 10,
        "entrants": [],
        "actions": ["join"] if not joined else [],
        "joined": joined,
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
    ctx.kv.set("horse:walk_consecutive_failures", _fail_state(2, _today()))
    action = {"ok": True, "result": {"ok": True, "message": "遛马收获 126 银元"}}
    client = _FakeClient(_horse_state(walk_count=3, walk_max=4), action)

    await _care_once(ctx, {}, client)

    assert any(level == "INFO" and "遛马成功（今日 4/4）" in msg for level, msg in ctx.log.records)
    assert ctx.kv.get("horse:walk_consecutive_failures") == _fail_state(0, _today())
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

    assert ctx.kv.get("horse:walk_consecutive_failures") == _fail_state(1, _today())
    assert any(level == "WARNING" and "遛马失败" in msg for level, msg in ctx.log.records)
    assert ctx.notifications and ctx.notifications[0][1] == "warning"


@pytest.mark.asyncio
async def test_walk_skips_after_three_consecutive_failures() -> None:
    # 异常路径：当日连续失败 3 次后停手，不再发请求
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_consecutive_failures", _fail_state(3, _today()))
    client = _FakeClient(_horse_state(), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts == []
    assert any("连续失败" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_walk_legacy_plain_number_failure_resets_and_recovers() -> None:
    # 回归：旧版纯数字熔断（无日期，线上 08-01 遗留 count=3）视为跨天自动重置，
    # 今日恢复遛马——否则熔断只在成功时清零、到 3 后又不发请求，形成永久死锁
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_consecutive_failures", 3)
    action = {"ok": True, "result": {"ok": True, "message": "遛马收获 126 银元"}}
    client = _FakeClient(_horse_state(), action)

    await _care_once(ctx, {}, client)

    assert len(client.posts) == 1
    assert client.posts[0][0] == "/api/portal/horse/action"
    assert ctx.kv.get("horse:walk_consecutive_failures") == _fail_state(0, _today())


@pytest.mark.asyncio
async def test_walk_failure_count_resets_next_day() -> None:
    # 回归：昨日熔断 count=3 → 今日自动恢复重试；今日熔断仍跳过
    # 昨日遗留 → 恢复
    ctx = _FakeCtx()
    ctx.kv.set("horse:walk_consecutive_failures", _fail_state(3, _yesterday()))
    client = _FakeClient(_horse_state(), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert len(client.posts) == 1

    # 今日熔断 → 跳过
    ctx2 = _FakeCtx()
    ctx2.kv.set("horse:walk_consecutive_failures", _fail_state(3, _today()))
    client2 = _FakeClient(_horse_state(), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx2, {}, client2)

    assert client2.posts == []
    assert any("连续失败" in msg for _, msg in ctx2.log.records)


@pytest.mark.asyncio
async def test_state_request_error_warns_with_readable_fallback() -> None:
    # 异常路径：状态请求失败且异常无消息时，日志兜底为可读文案而非空
    ctx = _FakeCtx()
    client = _FakeClient({"_error": ""}, {})

    await _care_once(ctx, {}, client)

    assert any(level == "WARNING" and "未知网络错误" in msg for level, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_match_race_joins_when_stamina_enough() -> None:
    # 正向：发现玩家养马赛（active + actions 含 join + 未 joined）且体力足够 → 直接加入
    ctx = _FakeCtx()
    action = {"ok": True, "result": {"ok": True, "message": "已加入养马赛 #1083"}}
    client = _FakeClient(_horse_state(match=_active_match()), action)

    await _care_once(ctx, {}, client)

    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/api/portal/horse/race/action"
    assert body["action"] == "join"
    assert "amount" not in body  # 报名额取服务端 match.amount，请求体只带 action+requestKey


@pytest.mark.asyncio
async def test_match_race_feeds_divine_when_stamina_low() -> None:
    # 正向：玩家赛可加入但体力不足（12 < 参赛最低 30）→ 先喂仙草补体力，不 join
    ctx = _FakeCtx()
    action = {"ok": True, "result": {"ok": True, "message": "仙草喂养成功"}}
    client = _FakeClient(_horse_state(stamina=12, match=_active_match()), action)

    await _care_once(ctx, {}, client)

    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/api/portal/horse/action"
    assert body["action"] == "feed" and body["feedType"] == "divine"
    assert not any("加入玩家养马赛" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_match_race_divine_cooldown_skips_round() -> None:
    # 异常路径：体力不足且仙草冷却中 → 本轮不动作（不遛马消耗体力），等待补体力
    ctx = _FakeCtx()
    ctx.kv.set("horse:divine_cooldown_until", _now_ms() + 600000)
    client = _FakeClient(_horse_state(stamina=12, match=_active_match()), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts == []
    assert any("仙草冷却中" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_match_race_divine_cooldown_response_stores_backoff() -> None:
    # 正向：喂仙草撞冷却（「刚刚吃过了 xx分钟后再喂」）→ 记录 remainMs 退避，不一直尝试
    ctx = _FakeCtx()
    action = {
        "ok": True,
        "result": {"ok": False, "code": "cooldown", "remainMs": 1800000, "message": "刚刚吃过了，30分钟 后再喂。"},
    }
    client = _FakeClient(_horse_state(stamina=12, match=_active_match()), action)
    before = _now_ms()

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:divine_cooldown_until") == pytest.approx(before + 1800000, abs=5000)
    assert ctx.notifications == []  # 冷却静默，不打扰


@pytest.mark.asyncio
async def test_match_race_skips_when_joined_or_inactive() -> None:
    # 异常路径：已加入 / 比赛未开 → 不重复加入，正常走遛马
    ctx = _FakeCtx()
    joined_match = _active_match(joined=True)
    client = _FakeClient(_horse_state(match=joined_match), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["action"] == "walk"  # 未重复 join，走遛马

    ctx2 = _FakeCtx()
    idle = _active_match()
    idle["active"] = False
    idle["actions"] = ["start"]
    client2 = _FakeClient(_horse_state(match=idle), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx2, {}, client2)

    assert client2.posts and client2.posts[0][1]["action"] == "walk"  # 无进行中比赛，不加入


@pytest.mark.asyncio
async def test_feed_cooldown_response_stores_backoff() -> None:
    # 正向：喂食撞冷却（「刚刚吃过了 xx分钟后再喂」）→ 记 remainMs 退避，静默不打扰
    ctx = _FakeCtx()
    state = _horse_state(satiety=40)  # 饱腹 40 < 阈值 60 → 触发喂食
    action = {
        "ok": True,
        "result": {"ok": False, "code": "cooldown", "remainMs": 2700000, "message": "刚刚吃过了，45分钟 后再喂。"},
    }
    client = _FakeClient(state, action)
    before = _now_ms()

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:feed_cooldown_until") == pytest.approx(before + 2700000, abs=5000)
    assert len(client.posts) == 1 and client.posts[0][1]["feedType"] == "fine"  # 默认精草
    assert ctx.notifications == []


@pytest.mark.asyncio
async def test_feed_in_cooldown_skips_without_posting() -> None:
    # 异常路径：喂食冷却未到 → 本轮不喂，继续做下一动作（遛马），不硬试
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() + 600000)
    client = _FakeClient(_horse_state(satiety=40), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["action"] == "walk"  # 冷却中不喂，转遛马
    assert not any("喂食" in body.get("action", "") for _, body in client.posts)


@pytest.mark.asyncio
async def test_feed_success_clears_cooldown() -> None:
    # 正向：喂食成功 → 清除过期冷却标记，下次到点可再喂
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() - 1000)  # 上次退避已过期
    action = {"ok": True, "result": {"ok": True, "message": "精草喂养成功"}}
    client = _FakeClient(_horse_state(satiety=40), action)

    await _care_once(ctx, {}, client)

    assert "horse:feed_cooldown_until" not in ctx.kv
    assert any("喂食 fine" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_feeds_share_cooldown_but_divine_is_independent() -> None:
    # 回归：普通喂食（weed/fine）共用 feed_cooldown_until，仙草（divine）独立冷却——
    # 精草喂过冷却中仍可喂仙草补体力（用户确认「他们不共享cd」）
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() + 600000)  # 精草冷却中
    match_state = _horse_state(stamina=12, match=_active_match())  # 玩家赛体力不足
    action = {"ok": True, "result": {"ok": True, "message": "仙草喂养成功"}}
    client = _FakeClient(match_state, action)

    await _care_once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["feedType"] == "divine"  # 精草冷却不影响仙草
