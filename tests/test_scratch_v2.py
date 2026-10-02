# -*- coding: utf-8 -*-
# 天空刮奖（plugins_v2/scratch.py）V2 运行时适配单元测试
#
# 覆盖：setup 在无 ctx.filters、on_message 只接受裸装饰器的 V2 运行时下不抛异常；
# 刮刮乐识别/解析走 Telethon 的 rows[].buttons[].data(bytes)；重拉消息用 ids= 关键字
# 并带 get_chat 回退；点击走 click(i=行, j=列)；回本即停+放弃；连亏自动停止；
# 连锁发送的兜底链。宿主依赖全部 fake 隔离，不碰真实 Telegram。

from __future__ import annotations

import types
from collections.abc import Iterator
from typing import Any

import pytest

from plugins_v2 import scratch as scratch_mod

CARD_ID = 77
GROUP = -1001326208894
BOT_ID = 8907007783


# ─── V2 平台假上下文 ────────────────────────────────────────────────────────


class _Log:
    def __init__(self) -> None:
        self.records: list[str] = []

    def _sink(self, level: str, msg: str, *args: Any) -> None:
        self.records.append(f"{level} " + (msg % args if args else msg))

    def info(self, msg: str, *args: Any) -> None:
        self._sink("INFO", msg, *args)

    def warning(self, msg: str, *args: Any) -> None:
        self._sink("WARNING", msg, *args)

    def error(self, msg: str, *args: Any) -> None:
        self._sink("ERROR", msg, *args)

    def debug(self, msg: str, *args: Any) -> None:
        self._sink("DEBUG", msg, *args)

    def exception(self, msg: str, *args: Any) -> None:
        self._sink("EXCEPTION", msg, *args)


class _V2Ctx:
    """V2 平台上下文最小面：没有 filters，on_message 只接受裸装饰器。"""

    def __init__(self, config: dict[str, Any] | None = None, user: Any = None) -> None:
        self.config = dict(config or {})
        self.log = _Log()
        self.user: Any = user
        self.bot: Any = None
        self.handlers: list[Any] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    def on_message(self, *args: Any, **kwargs: Any) -> Any:
        assert not args and not kwargs, "V2 运行时的 on_message 只接受裸装饰器"

        def deco(fn: Any) -> Any:
            self.handlers.append(fn)
            return fn

        return deco

    async def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.notifications.append((message, kwargs))


# ─── Telethon 形态假对象 ────────────────────────────────────────────────────


class _TlBtn:
    def __init__(self, text: str, data: bytes | None) -> None:
        self.text = text
        self.data = data


class _TlRow:
    def __init__(self, buttons: list[_TlBtn]) -> None:
        self.buttons = list(buttons)


class _TlMarkup:
    def __init__(self, rows: list[list[_TlBtn]]) -> None:
        self.rows = [_TlRow(r) for r in rows]


def _card_markup(card_id: int = CARD_ID, *, abandon: bool = True) -> _TlMarkup:
    rows: list[list[_TlBtn]] = []
    for base in (1, 4, 7):
        rows.append([_TlBtn(str(n), f"scratch:{card_id}:{n}".encode()) for n in (base, base + 1, base + 2)])
    footer = [_TlBtn("一键刮开", f"scratch:{card_id}:all".encode())]
    if abandon:
        footer.append(_TlBtn("放弃", f"scratch:{card_id}:abandon".encode()))
    rows.append(footer)
    return _TlMarkup(rows)


class _TlMsg:
    """Telethon Message 形态：只有 rows[].buttons[].data(bytes)，没有 caption/inline_keyboard。"""

    def __init__(
        self,
        text: str = "🎰 刮刮乐 卡片",
        *,
        chat_id: int = GROUP,
        msg_id: int = 900,
        clicks: list[tuple] | None = None,
        markup: Any = None,
        sender_id: int = BOT_ID,
        payout: str | None = None,
    ) -> None:
        self.id = msg_id
        self.chat_id = chat_id
        self.chat = None
        self.text = text
        self.raw_text = text
        self.sender_id = sender_id
        self.reply_markup = markup if markup is not None else _card_markup()
        self._clicks = clicks if clicks is not None else []
        self._payout = payout

    async def click(self, i: int | None = None, j: int | None = None, **kwargs: Any) -> Any:  # Telethon 签名
        self._clicks.append((i, j))
        if self._payout is None:
            return None
        return types.SimpleNamespace(message=self._payout)


class _TlClient:
    def __init__(self, store: dict[int, Any] | None = None) -> None:
        self.store = dict(store or {})
        self.refetches: list[tuple[Any, Any]] = []
        self.sent: list[tuple[Any, Any]] = []

    async def get_messages(self, chat: Any, ids: Any = None, limit: Any = None) -> Any:
        self.refetches.append((chat, ids))
        if ids is None:
            return list(self.store.values())
        return self.store.get(ids)

    async def send_message(self, target: Any, text: Any) -> None:
        self.sent.append((target, text))


class _Event:
    def __init__(
        self,
        message: Any,
        *,
        client: Any,
        reply_out: bool | None = None,
        chat: Any = None,
    ) -> None:
        self.message = message
        self.client = client
        self._reply_out = reply_out
        self._chat = chat

    async def get_reply_message(self) -> Any:
        if self._reply_out is None:
            return None
        return types.SimpleNamespace(out=self._reply_out)

    async def get_chat(self) -> Any:
        if self._chat is None:
            raise RuntimeError("无 chat 实体")
        return self._chat


# ─── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """模块级状态逐个用例清零，避免串味。"""
    _clear()
    yield
    _clear()


def _clear() -> None:
    scratch_mod._playing = False
    scratch_mod._consecutive_loss = 0
    scratch_mod._auto_stopped = False
    scratch_mod._seen.clear()


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """去掉点击/冷却抖动，测试即时完成。"""
    monkeypatch.setattr(scratch_mod.random, "uniform", lambda a=0.0, b=1.0: 0.0)


def _cfg(**overrides: Any) -> dict[str, Any]:
    base = {
        "target_group": str(GROUP),
        "bot_id": 0,
        "click_delay": 0,
        "card_cooldown": 0,
        "max_consecutive_loss": 5,
    }
    base.update(overrides)
    return base


# ─── 测试 ───────────────────────────────────────────────────────────────────


async def test_setup_survives_v2_runtime() -> None:
    """修复前：V1 依赖 ctx.filters / on_message(filter, group=-9)，V2 直接崩。"""
    ctx = _V2Ctx(config=_cfg())
    assert not hasattr(ctx, "filters")
    await scratch_mod.setup(ctx)
    assert len(ctx.handlers) == 1
    await scratch_mod.teardown(ctx)


def test_is_scratch_card_only_telethon_shape() -> None:
    assert scratch_mod._is_scratch_card(_TlMsg()) is True
    assert scratch_mod._is_scratch_card(_TlMsg(text="普通消息")) is False
    # 有「刮刮乐」但没有 scratch: 按钮
    assert scratch_mod._is_scratch_card(_TlMsg(markup=_TlMarkup([[_TlBtn("x", b"other:1")]]))) is False
    # 只有 Pyrogram 的 inline_keyboard（无 rows）→ 不算卡片
    pyrogram_style = types.SimpleNamespace(
        text="刮刮乐", inline_keyboard=[[types.SimpleNamespace(callback_data="scratch:1:1")]]
    )
    assert scratch_mod._is_scratch_card(pyrogram_style) is False
    # 无 caption 字段也不能炸（V1 崩溃根因）
    assert scratch_mod._is_scratch_card(types.SimpleNamespace(text=None)) is False


def test_parse_card_maps_cells_and_abandon() -> None:
    card_id, cells, abandon_pos = scratch_mod._parse_card(_TlMsg())
    assert card_id == CARD_ID
    assert cells == {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (1, 0), 5: (1, 1), 6: (1, 2), 7: (2, 0), 8: (2, 1), 9: (2, 2)}
    assert abandon_pos == (3, 1)

    _, _, no_abandon = scratch_mod._parse_card(_TlMsg(markup=_card_markup(abandon=False)))
    assert no_abandon is None


def test_parse_cell_payout() -> None:
    assert scratch_mod._parse_cell_payout("获得 5 银元，净收益 -95 银元。") == 5
    assert scratch_mod._parse_cell_payout("获得 100 银元") == 100
    assert scratch_mod._parse_cell_payout("没中奖") is None
    assert scratch_mod._parse_cell_payout("") is None


def test_extract_message_single_event_and_two_arg() -> None:
    msg = _TlMsg()
    event = _Event(msg, client=_TlClient())
    got_msg, got_event = scratch_mod._extract_message((event,), {})
    assert got_msg is msg and got_event is event

    got_msg2, got_event2 = scratch_mod._extract_message((object(), msg), {})
    assert got_msg2 is msg and got_event2 is msg


def test_parse_group_takes_first_line() -> None:
    assert scratch_mod._parse_group(str(GROUP)) == GROUP
    assert scratch_mod._parse_group(f"{GROUP}\n-100999") == GROUP
    assert scratch_mod._parse_group("") is None
    assert scratch_mod._parse_group("abc") is None


async def test_handler_ignores_other_group_and_non_own_reply() -> None:
    clicks: list[tuple] = []
    client = _TlClient({900: _TlMsg(clicks=clicks)})
    ctx = _V2Ctx(config=_cfg())
    await scratch_mod.setup(ctx)
    handler = ctx.handlers[0]

    # 别的群
    other = _TlMsg(chat_id=-100555, clicks=clicks)
    await handler(_Event(other, client=client, reply_out=True))
    assert clicks == []

    # 是本群卡片，但不是回复我自己 → 不处理
    await handler(_Event(_TlMsg(clicks=clicks), client=client, reply_out=False))
    await handler(_Event(_TlMsg(clicks=clicks), client=client, reply_out=None))
    assert clicks == []

    # bot_id 过滤：发送者不是目标 Bot → 不处理
    ctx2 = _V2Ctx(config=_cfg(bot_id=BOT_ID))
    await scratch_mod.setup(ctx2)
    await ctx2.handlers[0](_Event(_TlMsg(sender_id=12345, clicks=clicks), client=client, reply_out=True))
    assert clicks == []


async def test_handler_plays_until_breakeven_and_chains(fast: None) -> None:
    """回本即停：点一格派奖 200 ≥ 成本 100 → 立刻点「放弃」，并连锁下一张。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, reply_out=True, chat=object()))

    # 主写法必须用 ids= 关键字（第二位置参数是 limit）
    assert client.refetches and all(ids == 900 for _chat, ids in client.refetches)
    # 点了一格后立刻点「放弃」按钮 (row=3, col=1)
    assert clicks[-1] == (3, 1)
    assert len(clicks) == 2
    assert any("回本就停" in text for text, _kw in ctx.notifications)
    # 赢后连锁发送 /scratch
    assert client.sent == [(GROUP, "/scratch")]
    assert scratch_mod._consecutive_loss == 0


async def test_handler_auto_stops_after_max_loss(fast: None) -> None:
    """连亏达上限 → 自动停止，且不再连锁发送。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 0 银元，净收益 -100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(max_consecutive_loss=1), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, reply_out=True, chat=object()))

    assert len(clicks) == 9  # 全刮完仍未回本，没有「放弃」点击
    assert any("自动停止" in text for text, _kw in ctx.notifications)
    assert client.sent == []
    assert scratch_mod._auto_stopped is True

    # 自动停止后新的卡片直接跳过
    clicks.clear()
    await ctx.handlers[0](_Event(_TlMsg(clicks=clicks, payout="获得 0 银元"), client=client, reply_out=True))
    assert clicks == []


async def test_refetch_card_falls_back_to_get_chat() -> None:
    """主写法抛「找不到实体」时，回退先 await event.get_chat() 再拉。"""

    class _PickyClient(_TlClient):
        async def get_messages(self, chat: Any, ids: Any = None, limit: Any = None) -> Any:
            self.refetches.append((chat, ids))
            if isinstance(chat, int):
                raise RuntimeError("Could not find the input entity")
            return self.store.get(ids)

    msg = _TlMsg()
    client = _PickyClient({900: msg})
    ctx = _V2Ctx()
    got = await scratch_mod._refetch_card(ctx, client, GROUP, 900, _Event(msg, client=client, chat=object()))
    assert got is msg
    assert any("回退 get_chat" in line for line in ctx.log.records)


async def test_refetch_card_returns_none_when_both_fail() -> None:
    class _DeadClient(_TlClient):
        async def get_messages(self, chat: Any, ids: Any = None, limit: Any = None) -> Any:
            self.refetches.append((chat, ids))
            raise RuntimeError("nope")

    msg = _TlMsg()
    client = _DeadClient({900: msg})
    ctx = _V2Ctx()
    got = await scratch_mod._refetch_card(ctx, client, GROUP, 900, _Event(msg, client=client, chat=object()))
    assert got is None

    # 没有 event 时也只试主写法
    assert await scratch_mod._refetch_card(ctx, client, GROUP, 900, None) is None


async def test_send_scratch_falls_back_to_bot_send_message(fast: None) -> None:
    ctx = _V2Ctx()
    ctx.user = types.SimpleNamespace()  # 既无 send 也无 send_message
    bot = _TlClient()
    ctx.bot = bot
    ok = await scratch_mod._send_scratch(ctx, GROUP, "test")
    assert ok is True
    assert bot.sent == [(GROUP, "/scratch")]


async def test_click_uses_ids_and_handles_missing_button() -> None:
    """按钮位置超出当前键盘 → 视为失效，返回 None，不误点别的按钮。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, markup=_TlMarkup([[_TlBtn("1", b"scratch:77:1")]]))
    client = _TlClient({900: msg})
    ctx = _V2Ctx()
    out = await scratch_mod._click_btn(ctx, client, GROUP, 900, 5, 0, "格5", None)
    assert out is None
    assert clicks == []
