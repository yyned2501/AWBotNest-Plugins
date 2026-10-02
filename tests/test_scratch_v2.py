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

import json
import tempfile
import time
import types
from collections.abc import Iterator
from pathlib import Path
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

    def __init__(
        self, config: dict[str, Any] | None = None, user: Any = None, data_dir: str | None = None
    ) -> None:
        self.config = dict(config or {})
        self.data_dir = data_dir or tempfile.mkdtemp(prefix="scratch-stats-test-")
        self.log = _Log()
        self.user: Any = user
        self.bot: Any = None
        self.handlers: list[Any] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.scheduled: list[tuple[Any, str, dict[str, Any]]] = []

    def schedule(self, fn: Any, kind: str, **kwargs: Any) -> Any:
        """平台定时器面：V2 支持 kind="interval"（seconds=）与 kind="cron"（minute=）。"""
        self.scheduled.append((fn, kind, kwargs))
        return fn

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
    scratch_mod._group_last_sent = 0.0
    scratch_mod._group_last_skip_log = 0.0
    scratch_mod._drop_game_remaining = None
    scratch_mod._drop_checked_ts = 0.0


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


def test_is_own_card_rejects_prefix_names() -> None:
    """名字边界（规则 A：整行字段相等 + 单个括号注记），别人以本账号名字为前缀的卡不能被认成自己的（宁漏不抢）。"""
    text = "🎰 刮刮乐\n玩家：{}\n每格 100 银元"
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(MY_FIRST)), (MY_FIRST,)) is True
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{MY_FIRST}2")), (MY_FIRST,)) is False
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{MY_FIRST}晴")), (MY_FIRST,)) is False
    # 单候选 'Yy' 时，别人的 `玩家：Yy IX` 不算我的卡；候选含全名时才是（规则 A ①）
    names_ix = (MY_FIRST, f"{MY_FIRST} IX")
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{MY_FIRST} IX")), (MY_FIRST,)) is False
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{MY_FIRST} IX")), names_ix) is True
    # 名字后面跟一整段括号注记，仍算本账号（Bot 追加注记时不能失效）
    assert scratch_mod._is_own_card(_TlMsg(text=f"🎰 刮刮乐\n玩家：{MY_FIRST}（我）"), (MY_FIRST,)) is True
    # 规则 A 已排除的残余变体：别人显示名以「本账号名 + 分隔符」开头 → 一律判 False（不刮 = 零开销）
    full = f"{MY_FIRST} Zhang"
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{full}2")), (MY_FIRST, full)) is False
    # 前缀 + 空格 + 任意内容一律不认：`玩家：Yy IX Zhang` 对候选 ('Yy','Yy IX') → False
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{MY_FIRST} IX Zhang")), names_ix) is False
    # 候选含全名时，整行就是全名 → 自己的卡
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(full)), (MY_FIRST, full)) is True
    # 括号注记不能夹带名字前缀（`玩家：Yy Zhang（我）` 对候选 ('Yy','Yy Zhang') 只在全名相等时成立）
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{full}（我）")), (MY_FIRST, full)) is True
    assert scratch_mod._is_own_card(_TlMsg(text=text.format(f"{full}2（我）")), (MY_FIRST, full)) is False


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


async def test_handler_ignores_prefix_name_card() -> None:
    """别人的卡但名字以本账号为前缀（玩家：Yy2 / 玩家：Yy晴 / 玩家：Yy Zhang2）→ 零点击、不连锁（钱不能花）。"""
    ctx = _V2Ctx(config=_cfg())
    await scratch_mod.setup(ctx)
    handler = ctx.handlers[0]

    for other in (f"{MY_FIRST}2", f"{MY_FIRST}晴", f"{MY_FIRST} Zhang2"):
        clicks: list[tuple] = []
        client = _TlClient()
        msg = _TlMsg(text=f"🎰 刮刮乐\n玩家：{other}\n每格 100 银元，点格子刮开", clicks=clicks)
        await handler(_Event(msg, client=client))

        assert clicks == []  # 一格都没点
        assert client.sent == []  # 没有连锁发 /scratch
        assert not any("识别到刮刮乐" in line for line in ctx.log.records)


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


async def test_handler_plays_until_breakeven_without_group_chain(fast: None) -> None:
    """回本即停：点一格派奖 200 ≥ 成本 100 → 立刻点「放弃」；群聊卡不即时连锁（v1.7.0 定时器控节奏）。"""
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
    # 群聊卡不再即时连锁：群发节奏由 scratch_group_send 定时器控制（SPEC §12.5）
    assert client.sent == []
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


# ─── §4 / §5 契约：元信息、量级约束边界 ─────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_meta_matches_manifest_and_spec() -> None:
    """元信息与 manifest_v2.json / SPEC §4 一致（商店按清单版本判定更新，漂移即推送失效）。"""
    meta = scratch_mod.__plugin__
    entry = json.loads((ROOT / "manifest_v2.json").read_text(encoding="utf-8"))["plugins"]["scratch"]

    assert meta["id"] == entry["id"] == "scratch"  # id 必须等于文件名
    assert meta["name"] == entry["name"] == "天空刮奖"
    assert meta["scope"] == entry["scope"] == "user"
    assert meta["version"] == entry["version"]
    assert entry["path"] == "plugins_v2/scratch.py"
    assert meta["plugin_api_version"] == entry["plugin_api_version"] == 2
    assert "requirements" not in meta  # §2：只用标准库，不引入依赖

    # §4 配置项：键名 / 默认值 / 边界全部沿用 V1
    schema = meta["config_schema"]
    assert set(schema) == {
        "target_group",
        "bot_id",
        "player_names",
        "click_delay",
        "card_cooldown",
        "max_consecutive_loss",
        "group_send_interval",
        "pm_unlimited",
        "drop_guard_enabled",
        "drop_check_interval",
        "stats_enabled",
        "stats_report_hour",
        "stats_report_minute",
        "stats_retention_days",
    }
    assert schema["player_names"]["default"] == ""
    assert schema["group_send_interval"]["default"] == 120
    assert schema["pm_unlimited"]["default"] is True
    assert schema["drop_guard_enabled"]["default"] is True
    assert (schema["drop_check_interval"]["default"], schema["drop_check_interval"]["min"]) == (10, 5)
    assert schema["stats_enabled"]["default"] is True
    assert schema["stats_retention_days"]["default"] == 90
    assert (schema["stats_report_hour"]["default"], schema["stats_report_hour"]["max"]) == (23, 23)
    assert schema["target_group"]["default"] == "-1001326208894"
    assert schema["bot_id"]["default"] == 0
    delay = schema["click_delay"]
    assert (delay["default"], delay["min"], delay["max"]) == (0.6, 0.3, 2.0)
    cooldown = schema["card_cooldown"]
    assert (cooldown["default"], cooldown["min"], cooldown["max"]) == (5, 2, 30)
    max_loss = schema["max_consecutive_loss"]
    assert (max_loss["default"], max_loss["min"], max_loss["max"]) == (5, 1, 20)


async def test_single_card_cost_ceiling_is_900(fast: None) -> None:
    """§5 量级边界：单卡成本上限 900 = 9 格 × 100；全亏也只刮 9 格，不重复点同一格。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 0 银元，净收益 -100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(max_consecutive_loss=99), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    assert len(clicks) == 9  # 9 格，一格不落
    assert len(set(clicks)) == 9  # 随机顺序下 9 个位置互不相同 → 不会重复花钱
    assert all(0 <= row <= 3 and 0 <= col <= 2 for row, col in clicks)
    assert any("成本900" in text and "净-900" in text for text, _kw in ctx.notifications)


def test_seen_ttl_is_300s_and_prune_drops_only_expired() -> None:
    """§5：去重 TTL 300s，每轮清过期，防无界增长。"""
    assert scratch_mod._SEEN_TTL == 300
    now = time.time()
    scratch_mod._seen["expired"] = now - scratch_mod._SEEN_TTL - 1
    scratch_mod._seen["fresh"] = now - scratch_mod._SEEN_TTL + 1

    scratch_mod._prune_seen()

    assert set(scratch_mod._seen) == {"fresh"}


async def test_dedup_and_playing_guard_skip_card(fast: None) -> None:
    """§5 串行互斥：同一张卡只玩一次；`_playing=True` 时新卡直接跳过（不并发刮）。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)
    handler = ctx.handlers[0]

    await handler(_Event(msg, client=client, chat=object()))
    assert len(clicks) == 2  # 刮一格 + 点「放弃」
    assert scratch_mod._playing is False  # 玩完必须放开互斥

    # 同一条卡（同 chat:msg）再次到达 → 去重命中，零点击
    await handler(_Event(msg, client=client, chat=object()))
    assert len(clicks) == 2
    assert sum("识别到刮刮乐" in line for line in ctx.log.records) == 2  # 认出来了，但止步于去重

    # 正在玩卡时新卡到达 → 跳过，零点击、不连锁
    scratch_mod._playing = True
    fresh_clicks: list[tuple] = []
    fresh = _TlMsg(msg_id=901, clicks=fresh_clicks)
    await handler(_Event(fresh, client=client, chat=object()))
    assert fresh_clicks == []
    assert client.sent == []  # 群聊卡不即时连锁（v1.7.0 双通道）
    assert any("正在玩卡中" in line for line in ctx.log.records)


# ─── V1 → V2 属性访问红线（SPEC §3 / §12）───────────────────────────────────


class _V1TrapBtn(_TlBtn):
    """V1 时代按钮才有 callback_data（str）；一旦被读就炸。"""

    @property
    def callback_data(self) -> str:
        raise AssertionError("V1 属性 button.callback_data 不应再被访问")


class _V1TrapMarkup(_TlMarkup):
    """V1 的内联键盘是 inline_keyboard；V2 必须走 rows/buttons，读旧属性即炸。"""

    @property
    def inline_keyboard(self) -> list[Any]:
        raise AssertionError("V1 属性 reply_markup.inline_keyboard 不应再被访问")


class _V1TrapMsg(_TlMsg):
    """真机 Telethon 形态 + V1 独有属性陷阱：caption / reply_to_message 一旦被读就炸。"""

    @property
    def caption(self) -> str:
        raise AssertionError("V1 属性 message.caption 不应再被访问（V1 崩溃根因）")

    @property
    def reply_to_message(self) -> Any:
        raise AssertionError("V1 属性 message.reply_to_message 不应再被访问（归属改判卡面「玩家：」）")


def _trap_markup(card_id: int = CARD_ID) -> _V1TrapMarkup:
    """真机布局（4 行 11 键），按钮与键盘全用 V1 陷阱形态。"""
    rows: list[list[Any]] = []
    for base in (1, 4, 7):
        rows.append([_V1TrapBtn(str(base + n), f"scratch:{card_id}:{base + n}".encode()) for n in range(3)])
    rows.append(
        [
            _V1TrapBtn("一键刮开", f"scratch:{card_id}:all".encode()),
            _V1TrapBtn("放弃", f"scratch:{card_id}:abandon".encode()),
        ]
    )
    return _V1TrapMarkup(rows)


def test_v1_only_attributes_are_never_touched() -> None:
    """V1→V2 替换后：caption / callback_data / inline_keyboard / reply_to_message 一律不再被访问。"""
    msg = _V1TrapMsg(markup=_trap_markup())

    assert scratch_mod._message_text(msg) == CARD_TEXT
    assert scratch_mod._is_scratch_card(msg) is True
    card_id, cells, abandon_pos = scratch_mod._parse_card(msg)
    assert card_id == CARD_ID
    assert sorted(cells) == list(range(1, 10))
    assert abandon_pos == (3, 1)
    assert scratch_mod._button_data(_V1TrapBtn("1", b"scratch:77:1")) == "scratch:77:1"

    # 文本为空时（真机的 raw_text 兜底）也只能读 raw_text，不许回落 caption
    textless = _V1TrapMsg(text="", markup=_trap_markup())
    textless.raw_text = "🎰 刮刮乐"
    assert scratch_mod._message_text(textless) == "🎰 刮刮乐"

    # 陷阱必须真会炸（否则这条红线等于没测）
    with pytest.raises(AssertionError, match="caption"):
        _ = msg.caption
    with pytest.raises(AssertionError, match="inline_keyboard"):
        _ = getattr(msg.reply_markup, "inline_keyboard")
    with pytest.raises(AssertionError, match="callback_data"):
        _ = _V1TrapBtn("1", b"scratch:77:1").callback_data


async def test_handler_plays_trap_card_end_to_end(fast: None) -> None:
    """整条 handler 路径在「V1 属性陷阱」消息上跑通：能识别、能刮、能回本停。"""
    clicks: list[tuple] = []
    msg = _V1TrapMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。", markup=_trap_markup())
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    assert len(clicks) == 2
    assert clicks[-1] == (3, 1)  # 回本后点「放弃」（第 4 行第 2 列）
    assert any("回本就停" in text for text, _kw in ctx.notifications)


# ─── v1.7.0 双通道 / 群聊节流 / 掉落守卫（SPEC §12.5）────────────────────────


def test_drop_line_parses_new_legacy_and_rejects_noise() -> None:
    """掉落配额行：新格式取「游戏」数，旧格式回退，非配额文本返回 None。"""
    assert scratch_mod._parse_drop_line("当前时段剩余掉落: 聊天 3 · 游戏 0") == 0
    assert scratch_mod._parse_drop_line("当前时段剩余掉落：聊天 1 · 游戏 12") == 12
    assert scratch_mod._parse_drop_line("当前时段剩余掉落: 5") == 5
    assert scratch_mod._parse_drop_line(f"🎰 刮刮乐\n玩家：{MY_FIRST}") is None
    assert scratch_mod._parse_drop_line("") is None


def test_drop_exhausted_only_zero_in_same_hour() -> None:
    """掉落满判据：剩余 0、且 /info 结果落在同一小时；跨整点视为刷新，不再拦。"""
    base = 3600 * 100000 + 30
    scratch_mod._drop_game_remaining = 0
    scratch_mod._drop_checked_ts = base
    assert scratch_mod._drop_exhausted(base + 5) is True
    assert scratch_mod._drop_exhausted(base + 3700) is False  # 跨整点 → 配额刷新
    scratch_mod._drop_game_remaining = 3
    assert scratch_mod._drop_exhausted(base + 5) is False
    scratch_mod._drop_game_remaining = None
    assert scratch_mod._drop_exhausted(base + 5) is False  # 从没校准过 → 不拦


async def test_info_reply_calibrates_quota_and_is_not_a_card() -> None:
    """私聊 /info 回执（与半小时状态卡同格式）校准配额，且不会被当成卡片刮。"""
    info = _TlMsg(
        text="当前时段剩余掉落: 聊天 3 · 游戏 0\n当前银元: 8.49W",
        msg_id=901,
        markup=_TlMarkup([]),
    )
    client = _TlClient({901: info})
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(info, client=client, chat=object()))

    assert scratch_mod._drop_game_remaining == 0
    assert client.sent == []  # 不是卡片 → 不刮不连锁
    assert any("本时段剩余掉落 0" in line for line in ctx.log.records)


async def test_group_tick_throttles_and_pauses_when_drops_full() -> None:
    """群聊定时器：按间隔发 /scratch；间隔内不重发；本时段掉落满则暂停。"""
    client = _TlClient()
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)
    tick = next((fn for fn, _kind, kw in ctx.scheduled if kw.get("id") == "scratch_group_send"), None)
    assert tick is not None

    await tick()
    assert client.sent == [(GROUP, "/scratch")]

    await tick()  # 间隔内触发 → 不重发
    assert len(client.sent) == 1

    scratch_mod._group_last_sent = 0.0
    scratch_mod._drop_game_remaining = 0
    scratch_mod._drop_checked_ts = time.time()
    await tick()
    assert len(client.sent) == 1  # 掉落满 → 暂停群发
    assert any("掉落已满" in line for line in ctx.log.records)


async def test_pm_card_chains_unlimited(fast: None) -> None:
    """私聊通道（SPEC §12.5）：刮完立刻私聊再发 /scratch，不限次数。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, chat_id=BOT_ID, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    assert client.sent == [(BOT_ID, "/scratch")]
    assert any("已在私聊发送 /scratch" in line for line in ctx.log.records)


async def test_pm_chain_can_be_disabled(fast: None) -> None:
    """关掉「私聊通道不限次」→ 私聊卡照常刮，但刮完不连锁。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, chat_id=BOT_ID, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID, pm_unlimited=False), user=client)
    await scratch_mod.setup(ctx)

    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    assert len(clicks) == 2  # 刮一格 + 放弃
    assert client.sent == []


async def test_player_names_alias_claims_fancy_display_name_card(fast: None) -> None:
    """显示名是花体（𝐘𝐲 𝐈𝐗）时，配置 player_names=Yy 仍能认领卡面「玩家：Yy」。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg}, first_name="𝐘𝐲", last_name="𝐈𝐗")

    # 不配别名 → 严格相等失配，零点击
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)
    await ctx.handlers[0](_Event(msg, client=client, chat=object()))
    assert clicks == []

    # 配上别名 → 认领并刮开
    ctx2 = _V2Ctx(config=_cfg(player_names="Yy"), user=client)
    await scratch_mod.setup(ctx2)
    await ctx2.handlers[0](_Event(msg, client=client, chat=object()))
    assert len(clicks) == 2


async def test_setup_registers_both_timers_only_with_bot_id() -> None:
    """setup 注册群聊发送（interval）与掉落查询（cron）；没有 bot_id 时不注册掉落查询。"""
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID))
    await scratch_mod.setup(ctx)
    kinds = {kw.get("id"): kind for _fn, kind, kw in ctx.scheduled}
    assert kinds.get("scratch_group_send") == "interval"
    assert kinds.get("scratch_drop_check") == "cron"
    assert kinds.get("scratch_report") == "cron"

    ctx2 = _V2Ctx(config=_cfg())
    await scratch_mod.setup(ctx2)
    assert {kw.get("id") for _fn, _kind, kw in ctx2.scheduled} == {"scratch_group_send", "scratch_report"}

    ctx3 = _V2Ctx(config=_cfg(stats_enabled=False))
    await scratch_mod.setup(ctx3)
    assert {kw.get("id") for _fn, _kind, kw in ctx3.scheduled} == {"scratch_group_send"}


async def test_group_tick_skipped_when_auto_stopped() -> None:
    """连亏自动停止后，群聊定时器也不发（与卡片 handler 同一熔断）。"""
    client = _TlClient()
    ctx = _V2Ctx(config=_cfg(), user=client)
    await scratch_mod.setup(ctx)
    tick = next(fn for fn, _kind, kw in ctx.scheduled if kw.get("id") == "scratch_group_send")

    scratch_mod._auto_stopped = True
    await tick()
    assert client.sent == []


# ─── v1.7.1 收益统计（SPEC §12.6）─────────────────────────────────────────


def test_day_key_uses_beijing_timezone() -> None:
    """日界按北京时间（UTC+8）：UTC 16:30 已是北京次日——容器时区不可信，不用它分日。"""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    assert scratch_mod._day_key(_dt(2026, 10, 2, 15, 59, tzinfo=_tz.utc).timestamp()) == "2026-10-02"
    assert scratch_mod._day_key(_dt(2026, 10, 2, 16, 30, tzinfo=_tz.utc).timestamp()) == "2026-10-03"


def test_money_parser_handles_wan_commas_and_negative() -> None:
    """/info 回执金额形态：8.39W / 5.36万 / 1,368 / 负数。"""
    assert scratch_mod._money("当前银元: 8.39W", "当前银元") == 83900
    assert scratch_mod._money("今日支出: 5.36万", "今日支出") == 53600
    assert scratch_mod._money("今日净收入: 1,368", "今日净收入") == 1368
    assert scratch_mod._money("今日净收入: -1,110", "今日净收入") == -1110
    assert scratch_mod._money("没这个字段", "今日收入") is None


async def test_group_card_lands_in_ledger_and_daily_rollup(tmp_path: Path) -> None:
    """群聊通道每张卡落 JSONL 流水 + 当日聚合（成本/派奖/净额可归因）。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(), user=client, data_dir=str(tmp_path))
    await scratch_mod.setup(ctx)
    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    rows = [
        json.loads(line)
        for line in (tmp_path / "scratch_ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cards = [row for row in rows if row["type"] == "card"]
    assert len(cards) == 1
    assert cards[0]["channel"] == "group"
    assert (cards[0]["cells"], cards[0]["cost"], cards[0]["payout"], cards[0]["net"]) == (1, 100, 200, 100)
    assert cards[0]["outcome"] == "breakeven"

    day = scratch_mod._day_key()
    daily = json.loads((tmp_path / "scratch_daily.json").read_text(encoding="utf-8"))
    assert daily[day]["group"]["cards"] == 1
    assert daily[day]["group"]["net"] == 100
    assert daily[day]["group"]["breakeven"] == 1


async def test_pm_card_counted_in_pm_bucket(tmp_path: Path) -> None:
    """私聊通道卡片单独归桶，不与群聊收益混算。"""
    clicks: list[tuple] = []
    msg = _TlMsg(chat_id=BOT_ID, clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID, pm_unlimited=False), user=client, data_dir=str(tmp_path))
    await scratch_mod.setup(ctx)
    await ctx.handlers[0](_Event(msg, client=client, chat=object()))

    day = scratch_mod._day_key()
    daily = json.loads((tmp_path / "scratch_daily.json").read_text(encoding="utf-8"))
    assert daily[day]["pm"]["cards"] == 1
    assert daily[day]["pm"]["net"] == 100
    assert daily[day]["group"]["cards"] == 0


async def test_stats_disabled_writes_no_files(tmp_path: Path) -> None:
    """stats_enabled=false → 完全不落盘（可一键关统计）。"""
    clicks: list[tuple] = []
    msg = _TlMsg(clicks=clicks, payout="获得 200 银元，净收益 100 银元。")
    client = _TlClient({900: msg})
    ctx = _V2Ctx(config=_cfg(stats_enabled=False), user=client, data_dir=str(tmp_path))
    await scratch_mod.setup(ctx)
    await ctx.handlers[0](_Event(msg, client=client, chat=object()))
    assert not (tmp_path / "scratch_ledger.jsonl").exists()
    assert not (tmp_path / "scratch_daily.json").exists()


async def test_info_reply_records_account_snapshot(tmp_path: Path) -> None:
    """/info 回执的账号级数字（游戏自算）进日报做对照。"""
    info = _TlMsg(
        text=(
            "💰 账户\n当前银元: 8.39W\n今日收入: 5.49W\n今日支出: 5.36W\n今日净收入: 1,368\n"
            "当前时段剩余掉落: 聊天 3 · 游戏 2"
        ),
        msg_id=901,
        chat_id=BOT_ID,
        markup=_TlMarkup([]),
    )
    client = _TlClient({901: info})
    ctx = _V2Ctx(config=_cfg(bot_id=BOT_ID), user=client, data_dir=str(tmp_path))
    await scratch_mod.setup(ctx)
    await ctx.handlers[0](_Event(info, client=client, chat=object()))

    day = scratch_mod._day_key()
    daily = json.loads((tmp_path / "scratch_daily.json").read_text(encoding="utf-8"))
    account = daily[day]["account"]
    assert account["net_income"] == 1368
    assert account["balance"] == 83900
    assert account["game_drop"] == 2


def test_report_text_covers_group_channel_and_account() -> None:
    """日报文案：群聊张数/派奖/成本/净额 + 账号级对照 + 差值（掉落奖励等）。"""
    day = "2026-10-02"
    entry = {
        "group": {"cards": 3, "cells": 5, "cost": 300, "payout": 420, "net": 120, "breakeven": 1, "loss": 2},
        "pm": scratch_mod._stats_empty_bucket(),
        "account": {"income": 54900, "expense": 53600, "net_income": 1368, "balance": 83900},
    }
    text = scratch_mod._report_text(day, entry, {day: entry})
    assert "群聊通道" in text
    assert "派奖 420 / 成本 300 → 净 +120 银元" in text
    assert "今日净收入 1368" in text
    assert "差值（掉落奖励等）= +1248 银元" in text


async def test_report_tick_pushes_only_in_report_hour(tmp_path: Path) -> None:
    """日报 cron 每小时一次、内部按北京小时自判：不是日报整点就不发。"""
    hour = scratch_mod._cn_now().hour
    ctx = _V2Ctx(config=_cfg(stats_report_hour=hour, stats_report_minute=0), data_dir=str(tmp_path))
    await scratch_mod.setup(ctx)
    tick = next(fn for fn, _kind, kw in ctx.scheduled if kw.get("id") == "scratch_report")
    await tick()
    assert any("收益日报" in text for text, _kw in ctx.notifications)

    ctx2 = _V2Ctx(config=_cfg(stats_report_hour=(hour + 1) % 24, stats_report_minute=0), data_dir=str(tmp_path))
    await scratch_mod.setup(ctx2)
    tick2 = next(fn for fn, _kind, kw in ctx2.scheduled if kw.get("id") == "scratch_report")
    await tick2()
    assert ctx2.notifications == []


def test_stats_prune_keeps_window(tmp_path: Path) -> None:
    """流水裁剪只留保留窗内的行。"""
    path = tmp_path / "scratch_ledger.jsonl"
    today = scratch_mod._day_key()
    path.write_text(
        "\n".join([
            json.dumps({"type": "card", "date": "2020-01-01", "net": 1}),
            json.dumps({"type": "card", "date": today, "net": 2}),
        ]) + "\n",
        encoding="utf-8",
    )
    ctx = _V2Ctx(config=_cfg(), data_dir=str(tmp_path))
    scratch_mod._stats_prune(ctx, 90)
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["net"] for row in rows] == [2]
