# -*- coding: utf-8 -*-
# 天空刮奖（plugins_v2/scratch.py）V2 运行时适配单元测试
#
# 夹具照抄真机形态（SPEC §12 实测，实例 18001 / 账号 yy7221）：
#   - 按钮是 KeyboardInlineButton(text, type, style)，**没有 .data**，回调数据在 button.type.data
#     （另保留 1.44 的 button.data 形态用例，验证双取值器不回归）
#   - 卡片是 Bot 独立发出的消息，reply_to_msg_id=None（不回复任何人的 /scratch）
#   - 归属判定靠卡面「玩家：<本账号显示名>」，不再用 get_reply_message().out
# 覆盖：setup 在无 ctx.filters、on_message 只接受裸装饰器的 V2 运行时下不抛异常；
# 刮刮乐识别/解析；重拉消息用 ids= 关键字并带 get_chat 回退、再失败回退②用事件消息快照点击；
# 点击走 click(i=行, j=列) 并兼容旧签名 click(x=列, y=行)；回本即停+放弃；连亏自动停止；
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
MY_FIRST = "Yy"
MY_LAST = ""
# 真机卡面：Bot 独立发出、含「刮刮乐」与「玩家：Yy」
CARD_TEXT = f"🎰 刮刮乐\n玩家：{MY_FIRST}\n每格 100 银元，点格子刮开"


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


class _TlInlineType:
    """Telethon 1.45+ 的 InlineButtonTypeCallback：callback data 挂在这里。"""

    def __init__(self, data: bytes | str | None) -> None:
        self.data = data


class _TlBtn:
    """真机形态 KeyboardInlineButton(text, type, style)：**没有 .data 属性**（SPEC §12.2）。"""

    def __init__(self, text: str, data: bytes | str | None) -> None:
        self.text = text
        self.type = _TlInlineType(data)
        self.style = None


class _LegacyTlBtn:
    """Telethon 1.44 形态 KeyboardButtonCallback：数据直接在 .data。"""

    def __init__(self, text: str, data: bytes | str | None) -> None:
        self.text = text
        self.data = data


class _TlRow:
    def __init__(self, buttons: list[Any]) -> None:
        self.buttons = list(buttons)


class _TlMarkup:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = [_TlRow(r) for r in rows]


def _card_markup(card_id: int = CARD_ID, *, abandon: bool = True, btn_cls: type = _TlBtn) -> _TlMarkup:
    rows: list[list[Any]] = []
    for base in (1, 4, 7):
        rows.append([btn_cls(str(n), f"scratch:{card_id}:{n}".encode()) for n in (base, base + 1, base + 2)])
    footer = [btn_cls("一键刮开", f"scratch:{card_id}:all".encode())]
    if abandon:
        footer.append(btn_cls("放弃", f"scratch:{card_id}:abandon".encode()))
    rows.append(footer)
    return _TlMarkup(rows)


class _TlMsg:
    """Telethon Message 形态：rows[].buttons[].type.data(bytes)，没有 caption/inline_keyboard。"""

    def __init__(
        self,
        text: str = CARD_TEXT,
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
        self.reply_to_msg_id = None  # 真机实测：卡片不回复任何人（SPEC §12.1）
        self.reply_to = None
        self.reply_markup = markup if markup is not None else _card_markup()
        self._clicks = clicks if clicks is not None else []
        self._payout = payout

    async def click(self, i: int | None = None, j: int | None = None, **kwargs: Any) -> Any:  # Telethon 签名
        self._clicks.append((i, j))
        if self._payout is None:
            return None
        return types.SimpleNamespace(message=self._payout)


class _TlClient:
    def __init__(
        self,
        store: dict[int, Any] | None = None,
        *,
        first_name: str = MY_FIRST,
        last_name: str = MY_LAST,
    ) -> None:
        self.store = dict(store or {})
        self.refetches: list[tuple[Any, Any]] = []
        self.sent: list[tuple[Any, Any]] = []
        self.me_calls = 0
        self.me_error: Exception | None = None
        self.first_name = first_name
        self.last_name = last_name

    async def get_messages(self, chat: Any, ids: Any = None, limit: Any = None) -> Any:
        self.refetches.append((chat, ids))
        if ids is None:
            return list(self.store.values())
        return self.store.get(ids)

    async def get_me(self) -> Any:
        self.me_calls += 1
        if self.me_error is not None:
            raise self.me_error
        return types.SimpleNamespace(first_name=self.first_name, last_name=self.last_name)

    async def send_message(self, target: Any, text: Any) -> None:
        self.sent.append((target, text))


class _Event:
    """Telethon NewMessage.Event 形态：单 event、event.message 才是消息。"""

    def __init__(self, message: Any, *, client: Any, chat: Any = None) -> None:
        self.message = message
        self.client = client
        self._chat = chat

    async def get_reply_message(self) -> Any:
        # 真机：卡片没有 reply_to，Telethon 直接返回 None
        return None

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
    scratch_mod._self_names.clear()


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


def test_button_data_supports_both_runtime_shapes() -> None:
    """双取值器（SPEC §12.2）：1.45 读 type.data，1.44 回退 .data，两者都要取到。"""
    assert scratch_mod._button_data(_TlBtn("1", b"scratch:77:1")) == "scratch:77:1"
    assert scratch_mod._button_data(_LegacyTlBtn("1", b"scratch:77:1")) == "scratch:77:1"
    assert scratch_mod._button_data(_TlBtn("1", "scratch:77:1")) == "scratch:77:1"  # str 形态
    assert scratch_mod._button_data(_TlBtn("1", None)) == ""
    assert scratch_mod._button_data(types.SimpleNamespace()) == ""
    assert scratch_mod._button_data(types.SimpleNamespace(type=None)) == ""


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

    # 1.44 按钮形态（.data）同样解析得出来 —— 双取值器不挑运行时
    legacy_id, legacy_cells, legacy_abandon = scratch_mod._parse_card(_TlMsg(markup=_card_markup(btn_cls=_LegacyTlBtn)))
    assert legacy_id == CARD_ID
    assert len(legacy_cells) == 9
    assert legacy_abandon == (3, 1)


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


def test_is_own_card_requires_player_name() -> None:
    """归属判定（SPEC §12.1）：卡面必须含「玩家：<本账号显示名>」。"""
    assert scratch_mod._is_own_card(_TlMsg(), (MY_FIRST,)) is True
    assert scratch_mod._is_own_card(_TlMsg(text="🎰 刮刮乐\n玩家：别人"), (MY_FIRST,)) is False
    assert scratch_mod._is_own_card(_TlMsg(), ()) is False
    assert scratch_mod._is_own_card(_TlMsg(text="🎰 刮刮乐\n玩家："), ("",)) is False
    # 带 last_name 时，全名候选也命中
    full = f"{MY_FIRST} Zhang"
    assert scratch_mod._is_own_card(_TlMsg(text=f"🎰 刮刮乐\n玩家：{full}"), (MY_FIRST, full)) is True


async def test_self_display_names_caches_and_degrades() -> None:
    ctx = _V2Ctx()
    client = _TlClient()
    assert await scratch_mod._self_display_names(ctx, client) == (MY_FIRST,)
    assert client.me_calls == 1
    # 第二次走缓存，不再打扰 Telegram
    assert await scratch_mod._self_display_names(ctx, client) == (MY_FIRST,)
    assert client.me_calls == 1

    # first+last 两个候选
    both = _TlClient(first_name="Yy", last_name="Zhang")
    assert await scratch_mod._self_display_names(ctx, both) == ("Yy", "Yy Zhang")

    # 取不到 → 空元组 + 警告（调用方按「不处理」走）
    broken = _TlClient()
    broken.me_error = RuntimeError("not connected")
    assert await scratch_mod._self_display_names(ctx, broken) == ()
    assert any("取本账号信息失败" in line for line in ctx.log.records)
    # 没有 get_me 的 client / None 也不能炸
    assert await scratch_mod._self_display_names(ctx, types.SimpleNamespace()) == ()
    assert await scratch_mod._self_display_names(ctx, None) == ()


async def test_handler_ignores_other_group_and_other_players_card() -> None:
    clicks: list[tuple] = []
    client = _TlClient({900: _TlMsg(clicks=clicks)})
    ctx = _V2Ctx(config=_cfg())
    await scratch_mod.setup(ctx)
    handler = ctx.handlers[0]

    # 别的群
    other = _TlMsg(chat_id=-100555, clicks=clicks)
    await handler(_Event(other, client=client))
    assert clicks == []

    # 本群但不是我的卡（别人发的 /scratch 开出来的卡，reply 也是 None）→ 不动
    await handler(_Event(_TlMsg(text="🎰 刮刮乐\n玩家：别人", clicks=clicks), client=client))
    assert clicks == []

    # bot_id 过滤：发送者不是目标 Bot → 不处理
    ctx2 = _V2Ctx(config=_cfg(bot_id=BOT_ID))
    await scratch_mod.setup(ctx2)
    await ctx2.handlers[0](_Event(_TlMsg(sender_id=12345, clicks=clicks), client=client))
    assert clicks == []


async def test_handler_skips_when_self_name_unavailable() -> None:
    """取不到本账号显示名 → 跳过并留警告（宁漏不抢：绝不误点别人的卡花钱）。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks)
    client = _TlClient({900: msg})
    client.me_error = RuntimeError("no user client")
    ctx = _V2Ctx(config=_cfg())
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client))

    assert clicks == []
    assert client.sent == []
    assert any("取不到本账号显示名" in line for line in ctx.log.records)
    assert not any("识别到刮刮乐" in line for line in ctx.log.records)


async def test_handler_plays_until_breakeven_and_chains(fast: None) -> None:
    """回本即停：点一格派奖 200 ≥ 成本 100 → 立刻点「放弃」，并连锁下一张。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    # 归属判定先认人：真机卡面「玩家：Yy」，get_me 只打一次
    assert client.me_calls == 1
    assert any("识别到刮刮乐" in line for line in ctx.log.records)
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

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    assert len(clicks) == 9  # 全刮完仍未回本，没有「放弃」点击
    assert any("自动停止" in text for text, _kw in ctx.notifications)
    assert client.sent == []
    assert scratch_mod._auto_stopped is True

    # 自动停止后新的卡片直接跳过
    clicks.clear()
    await ctx.handlers[0](_Event(_TlMsg(clicks=clicks, payout="获得 0 银元"), client=client))
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


# ─── §9.1 回退②（事件消息快照）与点击签名自适应 ──────────────────────────────


class _DeadClient(_TlClient):
    """两条重拉路都失败的 client（模拟实体解析失败 / 网络断）。"""

    async def get_messages(self, chat: Any, ids: Any = None, limit: Any = None) -> Any:
        self.refetches.append((chat, ids))
        raise RuntimeError("Could not find the input entity")


async def test_click_btn_falls_back_to_event_snapshot(fast: None) -> None:
    """回退②：主写法与 get_chat 都失败 → 改用事件消息快照点击（功能降级，不崩）。"""
    clicks: list[tuple] = []
    snapshot = _TlMsg(clicks=clicks, payout="获得 5 银元，净收益 -95 银元。")
    client = _DeadClient({900: snapshot})
    ctx = _V2Ctx()
    event = _Event(snapshot, client=client, chat=None)  # get_chat 抛错 → 回退①也失败

    out = await scratch_mod._click_btn(ctx, client, GROUP, 900, 0, 0, "格1", event, snapshot=snapshot)
    assert out == "获得 5 银元，净收益 -95 银元。"
    assert clicks == [(0, 0)]
    assert any("回退②用事件快照点击" in line for line in ctx.log.records)

    # 没给快照时仍返回 None（调用方按累计值结算）
    assert await scratch_mod._click_btn(ctx, client, GROUP, 900, 0, 0, "格1", event) is None


async def test_play_card_degrades_to_snapshot(fast: None) -> None:
    """重拉全失败时 _play_card 走快照，仍能刮完整张卡并结算，不抛异常。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 0 银元，净收益 -100 银元。")
    client = _DeadClient({900: msg})
    ctx = _V2Ctx(config=_cfg())

    result = await scratch_mod._play_card(ctx, client, msg, _cfg())

    assert result is not None
    assert result["cells"] == 9
    assert result["cost"] == 900
    assert result["net"] == -900
    assert len(clicks) == 9
    assert any("回退②用事件快照" in line for line in ctx.log.records)


async def test_click_index_adapts_to_pyrogram_xy_signature() -> None:
    """旧签名 click(x=列, y=行)：必须按列行传，不能当成行列。"""
    calls: list[tuple[Any, Any]] = []

    class _XyMsg:
        async def click(self, x: Any = None, y: Any = None, **kwargs: Any) -> Any:
            calls.append((x, y))
            return types.SimpleNamespace(message="获得 1 银元")

    out = await scratch_mod._click_index(_XyMsg(), 2, 1)
    assert calls == [(1, 2)]
    assert out == "获得 1 银元"


def test_send_candidates_chain_order_and_dedup() -> None:
    ctx = _V2Ctx()
    user = types.SimpleNamespace(raw=types.SimpleNamespace())
    ctx.user = user
    ctx.bot = types.SimpleNamespace(raw=types.SimpleNamespace())
    chain = scratch_mod._send_candidates(ctx)
    assert chain[0] is user
    assert chain[1] is user.raw
    assert chain[2] is ctx.bot.raw

    # user.raw 与 bot.raw 是同一个 client → raw 只入链一次
    ctx2 = _V2Ctx()
    shared = types.SimpleNamespace()
    ctx2.user = types.SimpleNamespace(raw=shared)
    ctx2.bot = types.SimpleNamespace(raw=shared)
    chain2 = scratch_mod._send_candidates(ctx2)
    assert chain2.count(shared) == 1
    assert len(chain2) == 3  # user + 去重后的共享 raw + 裸 bot
