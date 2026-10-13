# -*- coding: utf-8 -*-
# 天空游戏 · 刮刮乐兜底（games/scratch.py）单元测试
#
# 覆盖：门户请求体与前端逐字段一致、回本即停、剩余掉落 >0 才刮、每张刮完催 /info 刷剩余、
# 连亏只停当天、逐张流水与收支日报。
#
# 假响应按真机形态造（{ok, scratch:{card, cost}, notice}，卡面 cells 带 position/opened/
# prize/net），不掺 TG 消息字段——门户这条路根本不经过 Telegram。

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

import plugins_v2.skyGame.games.drop_guard as dg
import plugins_v2.skyGame.games.scratch as sc
from tests.test_skygame_drop_guard import _FakeKV, _FakeLog


def _card(opened: int = 0, prizes: list[int] | None = None, status: str = "open", card_id: int = 3390) -> dict:
    """门户卡面：前 `opened` 格已揭晓，prizes 给出这几格的派奖额。"""
    prizes = prizes or []
    cells = []
    for position in range(1, 10):
        is_open = position <= opened
        prize = prizes[position - 1] if is_open and position - 1 < len(prizes) else 0
        cells.append({"position": position, "opened": is_open, "prize": prize, "net": prize - 100 if is_open else 0})
    return {
        "id": card_id,
        "status": status,
        "cells": cells,
        "expiresAt": int(time.time() * 1000) + 30000,
    }


def _payload(card: dict | None, cost: int = 100, notice: str = "", ok: bool = True) -> dict:
    return {"ok": ok, "scratch": {"card": card, "cost": cost}, "notice": notice}


class _Portal:
    """门户桩：GET 固定返回 state，POST 按顺序吐 responses（最后一份重复）。"""

    def __init__(self, state: dict, *responses: dict) -> None:
        self.state = state
        self.responses = list(responses) or [state]
        self.gets: list[str] = []
        self.posts: list[dict] = []
        self.csrf_resets = 0

    async def get(self, path: str) -> dict:
        self.gets.append(path)
        return self.state

    async def post(self, path: str, body: dict) -> dict:
        self.posts.append(body)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def reset_csrf(self) -> None:
        self.csrf_resets += 1

    async def aclose(self) -> None:
        pass

    async def __aenter__(self) -> _Portal:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass


class _ScratchCtx:
    def __init__(self, data_dir: str = "") -> None:
        self.kv = _FakeKV()
        self.log = _FakeLog()
        self.config: dict[str, object] = {}
        self.data_dir = data_dir
        self.notifications: list[tuple[str, dict]] = []
        self.schedules: list[tuple[object, str, dict]] = []

    def schedule(self, fn: object, mode: str, **kwargs: object) -> None:
        self.schedules.append((fn, mode, dict(kwargs)))

    async def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append((message, dict(kwargs)))


@pytest.fixture(autouse=True)
def _reset_state() -> object:
    """模块级互斥与限流日志是进程状态，逐个用例复位，避免串味。"""
    sc._playing = False
    sc._last_skip_log = 0.0
    yield
    sc._playing = False
    sc._last_skip_log = 0.0


def _set_remaining(ctx: _ScratchCtx, remaining: int | None) -> None:
    if remaining is None:
        return
    ctx.kv.set(dg._KV_REMAINING, remaining)
    ctx.kv.set(dg._KV_CHECKED_TS, time.time())


# ── 窗口与判定 ──


def test_fallback_minute_default_and_clamp() -> None:
    assert sc._fallback_minute({}) == 50
    assert sc._fallback_minute({"scratch_fallback_minute": 0}) == 0
    assert sc._fallback_minute({"scratch_fallback_minute": 30}) == 30
    assert sc._fallback_minute({"scratch_fallback_minute": 120}) == 55  # 上限夹住，留得出整点前的窗口
    assert sc._fallback_minute({"scratch_fallback_minute": -5}) == 0
    assert sc._fallback_minute({"scratch_fallback_minute": "abc"}) == 50


def test_in_window_only_after_start_minute() -> None:
    import datetime

    cfg = {"scratch_fallback_minute": 50}
    assert not sc._in_window(cfg, datetime.datetime(2026, 10, 8, 21, 49))
    assert sc._in_window(cfg, datetime.datetime(2026, 10, 8, 21, 50))
    assert sc._in_window(cfg, datetime.datetime(2026, 10, 8, 21, 59))


def test_halted_today_is_beijing_day_scoped() -> None:
    ctx = _ScratchCtx()
    assert not sc.halted_today(ctx.kv, "2026-10-08")
    ctx.kv.set(sc._KV_HALT_DAY, "2026-10-08")
    assert sc.halted_today(ctx.kv, "2026-10-08")
    assert not sc.halted_today(ctx.kv, "2026-10-09")  # 次日自愈，不用重启插件


# ── 卡面折算 ──


def test_card_view_uses_portal_numbers_not_local_accumulation() -> None:
    view = sc.card_view(_card(opened=3, prizes=[120, 80, 150]), 100)
    assert view["opened"] == 3
    assert view["payout"] == 350
    assert view["cost"] == 300
    assert view["net"] == 50  # Σ(120-100)+(80-100)+(150-100)
    assert sorted(view["closed"]) == [4, 5, 6, 7, 8, 9]


def test_card_view_net_falls_back_to_payout_minus_cost() -> None:
    """门户没给逐格 net（旧版/字段缺失）时按「派奖−成本」算，不当 0 记账。"""
    cells = [{"position": i, "opened": i <= 2, "prize": (120 if i == 1 else 0)} for i in range(1, 10)]
    view = sc.card_view({"status": "open", "cells": cells}, 100)
    assert view["payout"] == 120
    assert view["net"] == -80


def test_card_view_closed_order_is_shuffled_but_complete() -> None:
    views = [sc.card_view(_card(), 100)["closed"] for _ in range(40)]
    assert all(sorted(v) == list(range(1, 10)) for v in views)
    assert any(v != list(range(1, 10)) for v in views)  # 随机序真的会打乱


def test_breakeven_needs_payout_covering_cells() -> None:
    assert sc._breakeven({"opened": 1, "payout": 100}, 100) is True  # 回本即停的临界：刚好打平
    assert sc._breakeven({"opened": 1, "payout": 99}, 100) is False
    assert sc._breakeven({"opened": 0, "payout": 0}, 100) is False  # 没刮格不算回本


# ── 刮一张卡 ──


async def test_scratch_once_books_nothing_when_no_cell_revealed() -> None:
    """卡面已满格 open（重载后的残留状态）：一格都不是本轮刮的，不能把旧卡再记一遍账。"""
    portal = _Portal(_payload(_card(opened=9, prizes=[0] * 9)))
    assert await sc.scratch_once(_ScratchCtx(), {"scratch_reveal_delay": 0}, portal) is None
    assert portal.posts == []


async def test_scratch_once_starts_card_and_stops_at_breakeven() -> None:
    """无卡 → 免费领卡 → 逐格刮 → 累计派奖盖过成本就点「放弃」，未刮格不扣款。"""
    portal = _Portal(
        _payload(None),
        _payload(_card()),  # start
        _payload(_card(opened=1, prizes=[120])),  # reveal
        _payload(_card(opened=1, prizes=[120], status="completed")),  # abandon
    )
    result = await sc.scratch_once(_ScratchCtx(), {"scratch_reveal_delay": 0}, portal)

    assert [p["action"] for p in portal.posts] == ["start", "reveal", "abandon"]
    assert "cardId" not in portal.posts[0]  # 无卡时领卡不带 cardId（与门户前端一致）
    assert portal.posts[1]["cardId"] == 3390 and portal.posts[1]["position"] in range(1, 10)
    assert all("requestKey" not in p for p in portal.posts)  # 前端就不带这个键，别自作聪明加
    assert result == {"card_id": 3390, "cells": 1, "payout": 120, "cost": 100, "net": 20}


async def test_scratch_once_reuses_existing_open_card() -> None:
    """已有可刮的卡（重载/上轮中断）直接接着刮，不再领卡。"""
    portal = _Portal(
        _payload(_card(opened=2, prizes=[50, 60])),
        _payload(_card(opened=3, prizes=[50, 60, 200], status="completed")),
    )
    result = await sc.scratch_once(_ScratchCtx(), {"scratch_reveal_delay": 0}, portal)

    assert [p["action"] for p in portal.posts] == ["reveal"]
    assert result is not None and result["cells"] == 3 and result["payout"] == 310


async def test_scratch_once_reveals_all_when_never_breakeven() -> None:
    """一张都不回本 → 刮满 9 格收尾，不点放弃（没得省了）。"""
    states = [_payload(_card(opened=n)) for n in range(1, 10)]
    portal = _Portal(_payload(_card()), *states)
    result = await sc.scratch_once(_ScratchCtx(), {"scratch_reveal_delay": 0}, portal)

    assert [p["action"] for p in portal.posts].count("abandon") == 0
    assert [p["action"] for p in portal.posts].count("reveal") == 9
    assert result is not None and result["cells"] == 9 and result["cost"] == 900 and result["net"] == -900


async def test_scratch_once_stops_when_portal_ends_card() -> None:
    """门户 30 秒无操作自动结束本张：不再点放弃，按已刮格子结算。"""
    portal = _Portal(
        _payload(_card()),
        _payload(_card(opened=1, prizes=[50], status="completed")),
    )
    result = await sc.scratch_once(_ScratchCtx(), {"scratch_reveal_delay": 0}, portal)

    assert [p["action"] for p in portal.posts] == ["reveal"]
    assert result is not None and result["cells"] == 1 and result["net"] == -50


async def test_scratch_once_no_card_after_start_returns_none() -> None:
    """领卡后被拒（如时段已用完，notice 给原因）：什么都不刮、不记账。"""
    portal = _Portal(_payload(None), {"ok": False, "error": "请稍后再试", "notice": "每小时次数已用完"})
    assert await sc.scratch_once(_ScratchCtx(), {}, portal) is None
    assert len(portal.posts) == 1


async def test_scratch_once_error_response_makes_no_post() -> None:
    portal = _Portal({"_error": "All connection attempts failed"})
    assert await sc.scratch_once(_ScratchCtx(), {}, portal) is None
    assert portal.posts == []
    assert portal.csrf_resets == 1  # 网络失败作废 CSRF，下一轮重取


async def test_scratch_once_response_without_scratch_is_not_played() -> None:
    """网关 200 + 门户 HTML/空 JSON：没有 scratch 就什么都不做（不猜字段）。"""
    portal = _Portal({"ok": True, "profile": {"account": {"id": 1}}})
    assert await sc.scratch_once(_ScratchCtx(), {}, portal) is None
    assert portal.posts == []


# ── 兜底 tick ──


async def test_tick_skips_outside_window(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(sc, "_open_client", _spy_client(opened))
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 59}
    _set_remaining(ctx, 3)
    await sc.fallback_tick(ctx)
    assert opened == []


async def test_tick_skips_when_disabled_and_when_halted(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(sc, "_open_client", _spy_client(opened))
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": False, "scratch_fallback_minute": 0}
    _set_remaining(ctx, 3)
    await sc.fallback_tick(ctx)
    assert opened == []

    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 0}
    ctx.kv.set(sc._KV_HALT_DAY, sc._day_key())
    await sc.fallback_tick(ctx)
    assert opened == []  # 今日连亏停刮生效


async def test_tick_fetches_remaining_before_playing(monkeypatch: pytest.MonkeyPatch) -> None:
    """剩余掉落未知（没查过/跨整点）：先催 /info 拿数字，本轮不空刮。"""
    opened: list[str] = []
    calls: list[float] = []

    async def _fake_refresh(ctx: object, min_interval: float = dg._REFRESH_MIN_INTERVAL) -> bool:
        calls.append(min_interval)
        return True

    monkeypatch.setattr(sc, "_open_client", _spy_client(opened))
    monkeypatch.setattr(sc.drop_guard, "refresh", _fake_refresh)
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 0}
    await sc.fallback_tick(ctx)

    assert opened == []  # 没数字不开门户请求
    assert calls == [sc._INFO_RETRY_GAP]  # 按 10 分钟催一次，bot 不回话也不刷私聊


async def test_tick_skips_when_quota_used_up(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(sc, "_open_client", _spy_client(opened))
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 0}
    _set_remaining(ctx, 0)
    await sc.fallback_tick(ctx)
    assert opened == []  # 掉落已领完，兜底无意义，等整点刷新


async def test_tick_plays_one_card_and_refreshes_remaining(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """核心链路：窗口内 + 剩余 >0 → 刮一张 → 记账 → 立刻催 /info 刷新游戏剩余。"""
    opened: list[str] = []
    refreshes: list[float] = []

    async def _fake_refresh(ctx: object, min_interval: float = dg._REFRESH_MIN_INTERVAL) -> bool:
        refreshes.append(min_interval)
        return True

    portal = _Portal(
        _payload(None),
        _payload(_card()),
        _payload(_card(opened=1, prizes=[300], status="completed")),  # 一格回本
    )

    async def _client(ctx: object, cfg: dict) -> _Portal:
        opened.append("client")
        return portal

    monkeypatch.setattr(sc, "_open_client", _client)
    monkeypatch.setattr(sc.drop_guard, "refresh", _fake_refresh)
    ctx = _ScratchCtx(str(tmp_path))
    ctx.config = {
        "scratch_enabled": True,
        "scratch_fallback_minute": 0,
        "scratch_reveal_delay": 0,
        "scratch_stats_enabled": True,
    }
    _set_remaining(ctx, 2)

    await sc.fallback_tick(ctx)

    assert opened == ["client"]
    assert refreshes == [dg._REFRESH_MIN_INTERVAL]  # 刮完刷一次，下一轮按新数字决定
    rows = [json.loads(line) for line in (tmp_path / sc._LEDGER_FILE).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["payout"] == 300 and rows[0]["net"] == 200 and rows[0]["outcome"] == "breakeven"
    daily = json.loads((tmp_path / sc._DAILY_FILE).read_text(encoding="utf-8"))
    assert daily[sc._day_key()]["cards"] == 1 and daily[sc._day_key()]["breakeven"] == 1


async def test_tick_does_not_stack_second_card_while_playing(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(sc, "_open_client", _spy_client(opened))
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 0}
    _set_remaining(ctx, 3)
    sc._playing = True
    await sc.fallback_tick(ctx)
    assert opened == []


def _spy_client(bucket: list[str]) -> Callable[..., Awaitable[_Portal]]:
    async def _open(ctx: object, cfg: dict) -> _Portal:
        bucket.append("client")
        return _Portal(_payload(_card(status="completed")))

    return _open


# ── 连亏停刮 ──


async def test_loss_streak_resets_on_breakeven() -> None:
    ctx = _ScratchCtx()
    await sc.apply_loss_streak(ctx, {"scratch_max_consecutive_loss": 3}, -50)
    await sc.apply_loss_streak(ctx, {"scratch_max_consecutive_loss": 3}, -50)
    assert ctx.kv.get(sc._KV_LOSS) == 2 and ctx.kv.get(sc._KV_HALT_DAY) is None
    await sc.apply_loss_streak(ctx, {"scratch_max_consecutive_loss": 3}, 20)
    assert ctx.kv.get(sc._KV_LOSS) == 0  # 回本清零


async def test_loss_streak_halts_for_the_day_only() -> None:
    ctx = _ScratchCtx()
    cfg = {"scratch_max_consecutive_loss": 3}
    for _ in range(3):
        await sc.apply_loss_streak(ctx, cfg, -50)
    day = sc._day_key()
    assert ctx.kv.get(sc._KV_HALT_DAY) == day
    assert ctx.kv.get(sc._KV_LOSS) == 0  # 计数清零，避免恢复后第一张就再触发
    assert ctx.notifications and "今日停刮" in ctx.notifications[0][0]


async def test_loss_streak_notify_failure_does_not_break_halt() -> None:
    ctx = _ScratchCtx()

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("渠道不可用")

    ctx.notify = _boom  # type: ignore[assignment]
    await sc.apply_loss_streak(ctx, {"scratch_max_consecutive_loss": 1}, -50)
    assert ctx.kv.get(sc._KV_HALT_DAY) == sc._day_key()  # 推不出去也照样停刮


# ── 收支日报 ──


def test_record_card_skipped_when_stats_disabled(tmp_path: Path) -> None:
    ctx = _ScratchCtx(str(tmp_path))
    sc.record_card(ctx, {"scratch_stats_enabled": False},
                     {"card_id": 1, "cells": 3, "payout": 100, "cost": 300, "net": -200})
    assert not (tmp_path / sc._LEDGER_FILE).exists()


def test_report_text_books_only_scratch_income(tmp_path: Path) -> None:
    """日报口径只有刮奖本身的派奖/成本/净额，账号级总额一律不记账。"""
    day = "2026-10-08"
    bucket = {"cards": 2, "cells": 7, "cost": 700, "payout": 810, "net": 60, "breakeven": 1, "loss": 1}
    prev = {"cards": 3, "cells": 9, "cost": 900, "payout": 700, "net": -200, "breakeven": 1, "loss": 2}
    history = {day: bucket, "2026-10-07": prev}
    text = sc.report_text(day, bucket, history)
    assert "派奖 810 / 成本 700 → 净 +60" in text
    assert "回本 1 张 · 亏损 1 张" in text
    assert "2026-10-07: 3 张 → 净 -200" in text
    assert "余额" not in text and "今日收入" not in text  # 不混账号级总额


async def test_report_tick_once_per_day_at_configured_hour(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ScratchCtx(str(tmp_path))
    day = sc._day_key()
    ctx.kv.set(sc._KV_REPORT_DAY, day)  # 今天已经推过
    monkeypatch.setattr(sc, "_report_hour", lambda cfg: sc._cn_now().hour)
    await sc.report_tick(ctx)
    assert ctx.notifications == []

    ctx.kv.delete(sc._KV_REPORT_DAY)
    ctx.config = {"scratch_stats_enabled": True, "scratch_stats_retention_days": 90}
    await sc.report_tick(ctx)
    assert len(ctx.notifications) == 1 and ctx.kv.get(sc._KV_REPORT_DAY) == day

    ctx.config = {"scratch_stats_enabled": False}
    ctx.kv.delete(sc._KV_REPORT_DAY)
    await sc.report_tick(ctx)
    assert len(ctx.notifications) == 1  # 关掉统计不再推


# ── 调度接线 ──


def test_start_registers_zero_arg_ticks() -> None:
    import inspect

    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_fallback_minute": 50}
    sc.start(ctx)

    assert len(ctx.schedules) == 2
    tick = next(item for item in ctx.schedules if item[2].get("id") == "scratch_fallback")
    assert tick[1] == "interval" and tick[2]["seconds"] == sc._TICK_SECONDS
    assert len(inspect.signature(tick[0]).parameters) == 0  # 平台零参调用


def test_start_skips_everything_when_disabled() -> None:
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": False}
    sc.start(ctx)
    assert ctx.schedules == []


def test_start_omits_report_schedule_when_stats_disabled() -> None:
    ctx = _ScratchCtx()
    ctx.config = {"scratch_enabled": True, "scratch_stats_enabled": False}
    sc.start(ctx)
    assert [item[2].get("id") for item in ctx.schedules] == ["scratch_fallback"]
