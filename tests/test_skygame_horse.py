# -*- coding: utf-8 -*-
# skyGame · 养马遛马冷却退避与日志语义单元测试

from __future__ import annotations

import datetime
import json

import pytest

from plugins.skyGame.games.horse import _care_once, _format_feed_table, _format_walk_table, _is_cooldown, _remain_ms


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
    feed_today: int = 5,
    daily_divine: int = 0,
) -> dict[str, object]:
    """构造可触发遛马分支的门户状态（饱腹度拉满以跳过喂食分支）。"""
    state: dict[str, object] = {
        "horse": {
            "profile": {
                "state": {"isDead": False, "canWalk": can_walk, "canFeed": True},
                "satiety": satiety,
                "stamina": stamina,
                "reviveCost": 300000,
                "daily_feed_count": feed_today,
                "daily_divine_feed_count": daily_divine,
            },
            "stats": {
                "walkCountToday": walk_count,
                "walkMax": walk_max,
                "feedCountToday": feed_today,
                "feedMax": 5,
            },
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
        self.notifications: list[tuple[object, str]] = []
        self.tables: list[tuple[list[str], list[list[object]], dict[str, object]]] = []

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
    action = {
        "ok": True,
        "result": {
            "ok": True,
            "expGain": 30,
            "progressGain": 25,
            "bonusAmount": 197,
            "penaltyAmount": 0,
            "eventKind": "reward",
            "eventNote": "心情高涨，遛马时拣到了一点银元马粪。",
            "profile": {"horse_name": "Yy小号", "stamina": 52, "mood": 96, "satiety": 69},
        },
        "horse": {"stats": {"walkCountToday": 4, "walkMax": 4}},
    }
    client = _FakeClient(_horse_state(walk_count=3, walk_max=4), action)

    await _care_once(ctx, {}, client)

    assert any(level == "INFO" and "遛马成功（今日 4/4）" in msg for level, msg in ctx.log.records)
    assert ctx.kv.get("horse:walk_consecutive_failures") == _fail_state(0, _today())
    assert "horse:walk_cooldown_until" not in ctx.kv
    assert ctx.tables
    headers, rows, kwargs = ctx.tables[0]
    assert headers == ["项目", "内容"]
    assert ["随机事件", "心情高涨，遛马时拣到了一点银元马粪。"] in rows
    assert ["奖励", "+197 银元"] in rows
    assert ["今日遛马", "4/4"] in rows
    assert kwargs.get("caption") == "🐴 遛马成功"
    assert ctx.notifications[0][1] == "success"


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
async def test_match_race_feeds_configured_grass_before_divine() -> None:
    # 正向：玩家赛可加入但体力不足（20 < 30），精草还能喂且 +18 就能达标 → 先喂精草，不直接仙草
    ctx = _FakeCtx()
    action = {"ok": True, "result": {"ok": True, "feedType": "fine", "feedLabel": "精草", "amount": 300, "expGain": 8}}
    client = _FakeClient(_horse_state(stamina=20, satiety=80, feed_today=0, match=_active_match()), action)

    await _care_once(ctx, {"horse_feed_type": "fine"}, client)

    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/api/portal/horse/action"
    assert body["action"] == "feed" and body["feedType"] == "fine"
    assert not any("加入玩家养马赛" in msg for _, msg in ctx.log.records)
    assert ctx.tables and ctx.tables[0][0] == ["项目", "内容"]
    assert ["草料", "精草"] in ctx.tables[0][1]


@pytest.mark.asyncio
async def test_match_race_feeds_divine_when_fine_cannot_reach() -> None:
    # 正向：体力 12，精草 +18 仍 < 30 → 才喂仙草补体力
    ctx = _FakeCtx()
    action = {
        "ok": True,
        "result": {
            "ok": True,
            "feedType": "divine",
            "feedLabel": "仙草",
            "amount": 1000,
            "expGain": 20,
            "progressGain": 0,
            "profile": {
                "horse_name": "Yy小号",
                "level": 10,
                "exp": 9442,
                "stamina": 62,
                "mood": 100,
                "satiety": 100,
                "daily_feed_count": 0,
                "daily_divine_feed_count": 3,
            },
        },
    }
    client = _FakeClient(_horse_state(stamina=11, satiety=80, feed_today=0, match=_active_match()), action)

    await _care_once(ctx, {"horse_feed_type": "fine"}, client)

    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/api/portal/horse/action"
    assert body["action"] == "feed" and body["feedType"] == "divine"
    assert ctx.tables
    headers, rows, kwargs = ctx.tables[0]
    assert headers == ["项目", "内容"]
    assert ["草料", "仙草"] in rows
    assert ["体力", "62/100"] in rows
    assert ["今日仙草", "3/3"] in rows
    assert kwargs.get("caption") == "🐴 仙草喂养成功"


@pytest.mark.asyncio
async def test_match_race_feeds_divine_when_fine_on_cooldown() -> None:
    # 异常路径：精草冷却中、仙草还能喂 → 退回仙草补体力
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() + 600000)
    action = {"ok": True, "result": {"ok": True, "feedType": "divine", "feedLabel": "仙草", "amount": 1000}}
    client = _FakeClient(_horse_state(stamina=20, satiety=80, feed_today=0, match=_active_match()), action)

    await _care_once(ctx, {"horse_feed_type": "fine"}, client)

    assert client.posts and client.posts[0][1]["feedType"] == "divine"


@pytest.mark.asyncio
async def test_match_race_skips_when_both_feeds_blocked() -> None:
    # 异常路径：体力不足且精草/仙草都冷却 → 本轮不动作，不遛马消耗体力
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() + 600000)
    ctx.kv.set("horse:divine_cooldown_until", _now_ms() + 600000)
    client = _FakeClient(_horse_state(stamina=12, match=_active_match()), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts == []
    assert any("等待补体力" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_match_race_divine_cooldown_response_stores_backoff() -> None:
    # 正向：喂仙草撞冷却（「刚刚吃过了 xx分钟后再喂」）→ 记录 remainMs 退避，不一直尝试
    ctx = _FakeCtx()
    action = {
        "ok": True,
        "result": {
            "ok": False,
            "code": "feed_cooldown",
            "remainMs": 1800000,
            "message": "你的马刚吃过，30分钟 后再喂。",
        },
    }
    # 精草额度用完，才会走到仙草
    client = _FakeClient(_horse_state(stamina=12, feed_today=5, match=_active_match()), action)
    before = _now_ms()

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:divine_cooldown_until") == pytest.approx(before + 1800000, abs=5000)
    assert ctx.notifications == []  # 冷却静默，不打扰
    assert ctx.tables == []


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
    state = _horse_state(satiety=40, feed_today=1)  # 额度未用完 → 触发喂食
    action = {
        "ok": True,
        "result": {
            "ok": False,
            "code": "feed_cooldown",
            "remainMs": 2700000,
            "message": "你的马刚吃过，45分钟 后再喂。",
        },
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
    client = _FakeClient(_horse_state(satiety=40, feed_today=1), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["action"] == "walk"  # 冷却中不喂，转遛马
    assert not any("喂食" in body.get("action", "") for _, body in client.posts)


@pytest.mark.asyncio
async def test_feed_success_sets_local_backoff() -> None:
    # 正向：喂食成功后本地先按 60 分钟退避，避免下一轮立刻再撞 feed_cooldown
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() - 1000)  # 上次退避已过期
    action = {"ok": True, "result": {"ok": True, "feedType": "fine", "feedLabel": "精草"}}
    client = _FakeClient(_horse_state(satiety=40, feed_today=1), action)
    before = _now_ms()

    await _care_once(ctx, {}, client)

    assert ctx.kv.get("horse:feed_cooldown_until") == pytest.approx(before + 60 * 60 * 1000, abs=5000)
    assert any("喂食 fine" in msg for _, msg in ctx.log.records)


def test_is_cooldown_accepts_feed_and_walk_codes() -> None:
    # 正向：喂食/遛马各自的冷却码都算冷却；普通失败不算
    assert _is_cooldown({"result": {"code": "feed_cooldown"}})
    assert _is_cooldown({"result": {"code": "cooldown"}})
    assert _is_cooldown({"result": {"ok": False, "remainMs": 1000, "message": "你的马刚吃过，20分钟 后再喂。"}})
    assert not _is_cooldown({"result": {"ok": False, "code": "exhausted"}})


def test_remain_ms_falls_back_to_message_minutes() -> None:
    # 异常路径：没有 remainMs 时从文案里抠分钟数
    assert _remain_ms({"result": {"remainMs": 3127469}}) == 3127469
    assert _remain_ms({"result": {"message": "你的马刚吃过，20分钟 后再喂。"}}) == 20 * 60 * 1000
    assert _remain_ms({"result": {"message": "你的马刚遛过，2小时58分钟 后再来。"}}) == (2 * 60 + 58) * 60 * 1000
    assert _remain_ms({"result": {}}) == 0


@pytest.mark.asyncio
async def test_feeds_share_cooldown_but_divine_is_independent() -> None:
    # 回归：普通喂食（weed/fine）共用 feed_cooldown_until，仙草（divine）独立冷却——
    # 精草喂过冷却中仍可喂仙草补体力（用户确认「他们不共享cd」）
    ctx = _FakeCtx()
    ctx.kv.set("horse:feed_cooldown_until", _now_ms() + 600000)  # 精草冷却中
    match_state = _horse_state(stamina=12, match=_active_match())  # 玩家赛体力不足
    action = {"ok": True, "result": {"ok": True, "feedType": "divine", "feedLabel": "仙草"}}
    client = _FakeClient(match_state, action)

    await _care_once(ctx, {}, client)

    assert client.posts and client.posts[0][1]["feedType"] == "divine"  # 精草冷却不影响仙草


@pytest.mark.asyncio
async def test_daily_feed_uses_quota_even_when_satiety_high() -> None:
    # 正向：饱腹 82 高于阈值 70，但今日精草 0/5 → 仍喂精草用额度（攒体力/长期进度）
    ctx = _FakeCtx()
    action = {"ok": True, "result": {"ok": True, "feedType": "fine", "feedLabel": "精草", "amount": 300}}
    client = _FakeClient(_horse_state(satiety=82, stamina=16, feed_today=0), action)

    await _care_once(ctx, {"horse_feed_type": "fine", "horse_feed_threshold": 70}, client)

    assert client.posts and client.posts[0][1]["feedType"] == "fine"
    assert any("喂食 fine" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_daily_feed_skips_when_quota_used() -> None:
    # 异常路径：今日普通喂食已满 5/5，即使饱腹低也不再喂，转遛马
    ctx = _FakeCtx()
    client = _FakeClient(_horse_state(satiety=40, feed_today=5), {"ok": True, "result": {"ok": True}})

    await _care_once(ctx, {"horse_feed_type": "fine"}, client)

    assert client.posts and client.posts[0][1]["action"] == "walk"


def test_format_feed_table_uses_structured_fields_not_server_blob() -> None:
    # 正向：从 result 结构化字段组表，不把服务端长文案原样塞进表格
    payload = {
        "ok": True,
        "result": {
            "ok": True,
            "amount": 1000,
            "feedType": "divine",
            "feedLabel": "仙草",
            "expGain": 20,
            "progressGain": 0,
            "profile": {
                "horse_name": "Yy小号",
                "level": 10,
                "exp": 9442,
                "stamina": 70,
                "mood": 100,
                "satiety": 100,
                "daily_feed_count": 0,
                "daily_divine_feed_count": 3,
            },
            "message": "仙草成功：-1,000 银元，经验 +20，长期进度 +0\n🐴 Yy小号\n等级：Lv.10",
        },
    }
    headers, rows, caption = _format_feed_table(payload, "喂仙草失败")
    assert headers == ["项目", "内容"]
    assert caption == "🐴 仙草喂养成功"
    assert ["草料", "仙草"] in rows
    assert ["花费", "1,000 银元"] in rows
    assert ["经验", "+20"] in rows
    assert ["体力", "70/100"] in rows
    assert ["饱腹", "100/100"] in rows
    assert ["今日普通喂养", "0/5"] in rows
    assert ["今日仙草", "3/3"] in rows
    assert all("满加成节奏" not in str(cell) for row in rows for cell in row)


def test_format_feed_table_falls_back_when_result_empty() -> None:
    # 异常路径：服务端没给结构化字段 → 用兜底文案，不抛
    headers, rows, caption = _format_feed_table({"ok": False, "result": {}}, "喂食失败")
    assert headers == ["项目", "内容"]
    assert caption == "🐴 喂食失败"
    assert rows == [["结果", "喂食失败"]]


def test_format_walk_table_uses_structured_fields_not_server_blob() -> None:
    # 正向：从 walk 成功响应组表，随机事件和银元奖励单独成行，不塞长文案
    payload = {
        "ok": True,
        "result": {
            "ok": True,
            "expGain": 30,
            "progressGain": 25,
            "bonusAmount": 197,
            "penaltyAmount": 0,
            "eventKind": "reward",
            "eventNote": "心情高涨，遛马时拣到了一点银元马粪。",
            "profile": {
                "horse_name": "Yy小号",
                "level": 10,
                "exp": 9780,
                "stamina": 52,
                "mood": 96,
                "satiety": 69,
                "daily_feed_count": 0,
                "daily_divine_feed_count": 0,
            },
            "message": "遛马成功：经验 +30，长期进度 +25\n🐴 Yy小号\n随机事件：心情高涨",
        },
        "horse": {"stats": {"walkCountToday": 1, "walkMax": 4}},
    }
    headers, rows, caption = _format_walk_table(payload, "遛马失败")
    assert headers == ["项目", "内容"]
    assert caption == "🐴 遛马成功"
    assert ["经验", "+30"] in rows
    assert ["长期进度", "+25"] in rows
    assert ["奖励", "+197 银元"] in rows
    assert ["随机事件", "心情高涨，遛马时拣到了一点银元马粪。"] in rows
    assert ["体力", "52/100"] in rows
    assert ["今日遛马", "1/4"] in rows
    assert all("满加成节奏" not in str(cell) for row in rows for cell in row)
    assert all(row[0] != "惩罚" for row in rows)


def test_format_walk_table_falls_back_when_result_empty() -> None:
    # 异常路径：服务端没给结构化字段 → 用兜底文案，不抛
    headers, rows, caption = _format_walk_table({"ok": False, "result": {}}, "遛马失败")
    assert headers == ["项目", "内容"]
    assert caption == "🐴 遛马失败"
    assert rows == [["结果", "遛马失败"]]
