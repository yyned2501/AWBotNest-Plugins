# -*- coding: utf-8 -*-
# 天空红包（plugins_v2/skyRedPacket）单元测试
#
# 覆盖：等待时间计算（未发言大延迟）、V2 平台回调参数提取（Telethon 单 event /
# Pyrogram (client, message)）、群聊与发送者手动过滤、按钮点击跨运行时兼容、
# 以及「setup 在没有 ctx.filters 的 V2 运行时下不抛异常」这条启动回归。
# 宿主依赖全部用 fake 隔离，不触碰真实 Telegram。

from __future__ import annotations

import datetime
import time
from typing import Any

import pytest

from plugins_v2 import skyRedPacket


def test_parse_wait_seconds_variants() -> None:
    # 取第一个 N秒："红包前 30 秒" 用于以 msg_ts+30 计算可抢点（与重试主链一致）
    assert skyRedPacket._parse_wait_seconds("红包前 30 秒仅限最近 20 位发言人领取，请在 12 秒后重试") == 30
    assert skyRedPacket._parse_wait_seconds("距红包可抢还有 5 秒") == 5
    assert skyRedPacket._parse_wait_seconds("") is None
    assert skyRedPacket._parse_wait_seconds("没有数字") is None


def test_quiet_extra_disabled_keeps_old_behavior() -> None:
    # 上限 <= 0：关闭大延迟，返回 0（向后兼容旧的“可抢即点”）
    assert skyRedPacket._quiet_extra_delay(0, 0) == 0.0
    assert skyRedPacket._quiet_extra_delay(10, 0) == 0.0


def test_quiet_extra_within_range() -> None:
    for _ in range(100):
        v = skyRedPacket._quiet_extra_delay(10, 40)
        assert 10 <= v <= 40


def test_quiet_extra_normalizes_reversed_bounds() -> None:
    # min/max 写反也能落在正确区间
    for _ in range(100):
        v = skyRedPacket._quiet_extra_delay(40, 10)
        assert 10 <= v <= 40


def test_quiet_extra_negative_min_clamped() -> None:
    for _ in range(50):
        v = skyRedPacket._quiet_extra_delay(-5, 10)
        assert 0 <= v <= 10


def test_retry_wait_without_msg_ts_uses_base_plus_extra() -> None:
    # 拿不到发送时间：从现在起等 wait_seconds，再叠加未发言延迟
    assert skyRedPacket._compute_retry_wait(30, msg_ts=0, retry_offset=1, quiet_extra=5) == 35.0


def test_retry_wait_with_msg_ts_grabs_at_eligibility() -> None:
    now = time.time()
    # 可抢时间已过 20 秒（now-50+30-1）→ 至少等 0.5 秒
    assert skyRedPacket._compute_retry_wait(30, msg_ts=now - 50, retry_offset=1, quiet_extra=0) == 0.5
    # 可抢时间在未来：msg_ts-10+30-offset1 = 距 now 约 19 秒
    w = skyRedPacket._compute_retry_wait(30, msg_ts=now - 10, retry_offset=1, quiet_extra=0)
    assert 18.0 < w <= 19.0
    # 叠加 10 秒未发言延迟 → 约 29 秒
    w2 = skyRedPacket._compute_retry_wait(30, msg_ts=now - 10, retry_offset=1, quiet_extra=10)
    assert 28.0 < w2 <= 29.0


# ─── V2 运行时兼容层 ────────────────────────────────────────────────────────


class _Chat:
    def __init__(self, chat_id: int = -1001326208894, chat_type: str = "group") -> None:
        self.id = chat_id
        self.type = chat_type


class _Btn:
    def __init__(self, text: str) -> None:
        self.text = text


class _Markup:
    def __init__(self, rows: list[list[str]]) -> None:
        self.inline_keyboard = [[_Btn(t) for t in row] for row in rows]


class _TelethonMsg:
    """Telethon 形态：sender_id + click(i=行, j=列, timeout=...)。"""

    def __init__(self, text: str, clicks: list[Any]) -> None:
        self.text = text
        self.caption = None
        self.id = 77
        self.chat = _Chat()
        self.sender_id = skyRedPacket.BOT_ID
        self.date = datetime.datetime.now()  # noqa: DTZ005
        self.link = "https://t.me/c/1326208894/77"
        self.reply_markup = _Markup([["拼手气红包", "抢红包"]])
        self._clicks = clicks

    async def click(self, i: int | None = None, j: int | None = None, timeout: int | None = None) -> Any:
        self._clicks.append((i, j, timeout))
        return _Answer(f"恭喜，你抢到了 {len(self._clicks)} 银元")


class _Answer:
    def __init__(self, message: str) -> None:
        self.message = message


class _Event:
    """Telethon NewMessage：真实消息挂在 .message 上。"""

    def __init__(self, message: Any, is_group: bool = True) -> None:
        self.message = message
        self.is_group = is_group


def test_extract_message_telethon_event() -> None:
    msg = object()
    event = _Event(msg)
    assert skyRedPacket._extract_message((event,), {}) == (msg, event)


def test_extract_message_pyrogram_client_message() -> None:
    msg = object()
    assert skyRedPacket._extract_message((object(), msg), {}) == (msg, msg)


def test_extract_message_kwargs_and_empty() -> None:
    msg = object()
    assert skyRedPacket._extract_message((), {"event": msg})[0] is msg
    assert skyRedPacket._extract_message((), {}) == (None, None)


def test_sender_id_variants() -> None:
    class Peer:
        user_id = 42

    assert skyRedPacket._sender_id(_TelethonMsg("x", []), None) == skyRedPacket.BOT_ID

    class PyroMsg:
        from_user = type("U", (), {"id": 42})()

    assert skyRedPacket._sender_id(PyroMsg(), None) == 42

    class PeerMsg:
        from_id = Peer()

    assert skyRedPacket._sender_id(PeerMsg(), None) == 42
    assert skyRedPacket._sender_id(object(), None) is None


def test_is_group_chat_prefers_event_flag() -> None:
    msg = _TelethonMsg("x", [])
    assert skyRedPacket._is_group_chat(msg, _Event(msg, is_group=True)) is True
    assert skyRedPacket._is_group_chat(msg, _Event(msg, is_group=False)) is False
    # 无 is_group 时退回 chat.type
    assert skyRedPacket._is_group_chat(msg, object()) is True
    msg.chat = _Chat(chat_type="private")
    assert skyRedPacket._is_group_chat(msg, object()) is False
    # 两个字段都拿不到时按群聊放行（宁可多判不误杀）
    assert skyRedPacket._is_group_chat(object(), object()) is True


def test_result_text_variants() -> None:
    assert skyRedPacket._result_text(_Answer("已过期")) == "已过期"
    assert skyRedPacket._result_text(type("M", (), {"text": "抢到 5 银元"})()) == "抢到 5 银元"
    assert skyRedPacket._result_text(None) is None
    assert skyRedPacket._result_text(type("M", (), {"message": None, "text": None})()) is None


async def test_try_snatch_telethon_positional() -> None:
    clicks: list[Any] = []
    msg = _TelethonMsg("拼手气红包", clicks)
    assert await skyRedPacket._try_snatch(msg, 0, 1) == "恭喜，你抢到了 1 银元"
    assert clicks == [(0, 1, 10)]  # 行/列顺序不被调换，带 timeout


async def test_try_snatch_falls_back_when_timeout_unsupported() -> None:
    clicks: list[Any] = []

    class NoTimeoutClick:
        text = "拼手气红包"
        reply_markup = _Markup([["抢红包"]])

        async def click(self, x: int | None = None, y: int | None = None) -> Any:
            clicks.append((x, y))
            return _Answer("抢到 3 银元")

    assert await skyRedPacket._try_snatch(NoTimeoutClick(), 1, 2) == "抢到 3 银元"
    assert clicks == [(1, 2)]


async def test_try_snatch_returns_none_on_error() -> None:
    class Boom:
        async def click(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("FLOOD_WAIT")

    assert await skyRedPacket._try_snatch(Boom(), 0, 0) is None
    assert await skyRedPacket._try_snatch(object(), 0, 0) is None


# ─── setup / handler 接线 ───────────────────────────────────────────────────


class _Log:
    def __init__(self) -> None:
        self.records: list[str] = []

    def debug(self, msg: str, *args: Any) -> None:
        self.records.append("DEBUG " + (msg % args if args else msg))

    def info(self, msg: str, *args: Any) -> None:
        self.records.append("INFO " + (msg % args if args else msg))

    def warning(self, msg: str, *args: Any) -> None:
        self.records.append("WARNING " + (msg % args if args else msg))

    def error(self, msg: str, *args: Any) -> None:
        self.records.append("ERROR " + (msg % args if args else msg))


class _V2Ctx:
    """V2 平台上下文最小面：没有 filters，也不接受 on_message 的位置/关键字参数。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else {}
        self.log = _Log()
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.handlers: list[Any] = []

    def on_message(self, *args: Any, **kwargs: Any) -> Any:
        assert not args and not kwargs, "V2 运行时的 on_message 只接受裸装饰器"

        def deco(fn: Any) -> Any:
            self.handlers.append(fn)
            return fn

        return deco

    async def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        assert "account" not in kwargs, "V2 handler 没有 client，不应再传 account"
        self.notifications.append((message, kwargs))


def _packet_ctx(**overrides: Any) -> _V2Ctx:
    cfg: dict[str, Any] = {
        "enabled_groups": "-1001326208894",
        "initial_delay": 0,
        "random_delay_max": 0,
        "retry_offset": 1,
        "quiet_retry_min": 0,
        "quiet_retry_max": 0,
    }
    cfg.update(overrides)
    return _V2Ctx(cfg)


async def test_setup_registers_handler_without_filters() -> None:
    ctx = _packet_ctx()
    assert not hasattr(ctx, "filters")
    await skyRedPacket.setup(ctx)  # 修复前：这里抛 AttributeError: 'X' object has no attribute 'filters'
    assert len(ctx.handlers) == 1


async def test_handler_snatches_on_first_click() -> None:
    ctx = _packet_ctx()
    await skyRedPacket.setup(ctx)
    clicks: list[Any] = []
    msg = _TelethonMsg("🧧 拼手气红包 份数: 10 总银元: 100", clicks)
    await ctx.handlers[0](_Event(msg))

    assert clicks == [(0, 1, 10)]
    assert len(ctx.notifications) == 1
    text, kwargs = ctx.notifications[0]
    assert kwargs == {"level": "success", "category": "已抢"}
    assert "抢到了" in text


async def test_handler_snatches_when_sender_id_unresolved() -> None:
    # 某些运行时拿不到 sender id：此时靠「拼手气文案 + 抢红包按钮」判定，不能静默漏抢
    ctx = _packet_ctx()
    await skyRedPacket.setup(ctx)
    clicks: list[Any] = []

    class NoSender(_TelethonMsg):
        sender_id = None

    await ctx.handlers[0](_Event(NoSender("拼手气红包 总银元: 20", clicks)))
    assert clicks
    assert ctx.notifications and "抢到" in ctx.notifications[0][0]


async def test_handler_skips_non_group_and_other_sender() -> None:
    ctx = _packet_ctx()
    await skyRedPacket.setup(ctx)
    handler = ctx.handlers[0]

    private = _TelethonMsg("拼手气红包", [])
    private.chat = _Chat(chat_type="private")
    await handler(_Event(private, is_group=False))

    other = _TelethonMsg("拼手气红包", [])
    other.sender_id = 123456
    await handler(_Event(other))

    other_group = _TelethonMsg("拼手气红包", [])
    other_group.chat = _Chat(chat_id=-1001111111111)
    await handler(_Event(other_group))

    assert ctx.notifications == []


async def test_handler_retries_until_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _packet_ctx(quiet_retry_min=0, quiet_retry_max=0)
    await skyRedPacket.setup(ctx)

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(skyRedPacket.asyncio, "sleep", fake_sleep)

    answers = iter(
        [
            "红包前 30 秒仅限最近 20 位发言人领取",
            "红包前 30 秒仅限最近 20 位发言人领取",
            "恭喜，抢到 8 银元",
        ]
    )

    class Retry:
        text = "拼手气红包 份数: 5"
        id = 88
        chat = _Chat()
        sender_id = skyRedPacket.BOT_ID
        date = datetime.datetime.now()  # noqa: DTZ005
        link = ""
        caption = None
        reply_markup = _Markup([["抢红包"]])
        clicks = 0

        async def click(self, *args: Any, **kwargs: Any) -> Any:
            self.clicks += 1
            return _Answer(next(answers))

    msg = Retry()
    await ctx.handlers[0](_Event(msg))

    assert msg.clicks == 3
    assert len(ctx.notifications) == 1
    assert "抢到 8 银元" in ctx.notifications[0][0]
    assert all(s >= 0.5 for s in slept)


async def test_handler_gives_up_on_ended_packet() -> None:
    ctx = _packet_ctx()
    await skyRedPacket.setup(ctx)

    class Ended:
        text = "拼手气红包 总银元: 50"
        id = 99
        chat = _Chat()
        sender_id = skyRedPacket.BOT_ID
        date = None
        link = ""
        caption = None
        reply_markup = _Markup([["抢红包"]])

        async def click(self, *args: Any, **kwargs: Any) -> Any:
            return _Answer("红包已结束")

    await ctx.handlers[0](_Event(Ended()))
    text, kwargs = ctx.notifications[0]
    assert kwargs == {"level": "warning", "category": "已结束"}
    assert "已结束" in text
