# -*- coding: utf-8 -*-
# 天空答题（plugins_v2/skyDropAnswer）V2 运行时适配单元测试
#
# 覆盖：「setup 在没有 ctx.filters、on_message 只接受裸装饰器的 V2 运行时下不抛
# 异常」这条启动回归；掉落 handler 的手动过滤 + 计数 + 点击；/info 私聊捕获；
# 发送兜底链（user → user.raw → bot.raw）。宿主依赖全部 fake 隔离，不碰真实 Telegram。

from __future__ import annotations

import asyncio
import types
from pathlib import Path
from typing import Any

from plugins_v2 import skyDropAnswer
from plugins_v2.skyDropAnswer import answer as answer_mod
from plugins_v2.skyDropAnswer import trigger as trigger_mod

BOT_ID = 8907007783


# ─── V2 平台假上下文 ────────────────────────────────────────────────────────


class _AsyncKV:
    """模拟 V2 PluginKV：get/set/delete/items 均为协程，没有 keys()。"""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def items(self) -> dict[str, Any]:
        return dict(self.store)


class _SyncKV:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.store[key] = value

    def keys(self) -> list[str]:
        return list(self.store.keys())

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


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


class _V2Ctx:
    """V2 平台上下文最小面：没有 filters，on_message 只接受裸装饰器，kv 是异步的。"""

    def __init__(self, config: dict[str, Any] | None = None, data_dir: Path | None = None) -> None:
        self.config = config if config is not None else {}
        self.kv = _AsyncKV()
        self.log = _Log()
        self.user = None
        self.bot = None
        self.handlers: list[Any] = []
        self.scheduled: list[Any] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.data_dir = str(data_dir or Path("."))

    def on_message(self, *args: Any, **kwargs: Any) -> Any:
        assert not args and not kwargs, "V2 运行时的 on_message 只接受裸装饰器"

        def deco(fn: Any) -> Any:
            self.handlers.append(fn)
            return fn

        return deco

    def on_api(self, *_args: Any, **_kwargs: Any) -> Any:
        def deco(fn: Any) -> Any:
            return fn

        return deco

    def schedule(self, fn: Any, *_args: Any, **_kwargs: Any) -> None:
        self.scheduled.append(fn)

    def create_task(self, coro: Any, *_args: Any, **_kwargs: Any) -> Any:
        return asyncio.ensure_future(coro)

    def update_config(self, patch: dict[str, Any]) -> None:
        self.config.update(patch)

    async def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.notifications.append((message, kwargs))


class _HandlerCtx:
    """直接测 handler 注册函数用的同步 kv 上下文（模拟外观层接管之后的运行期）。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else {}
        self.kv = _SyncKV()
        self.log = _Log()
        self.handlers: list[Any] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.user = None
        self.bot = None

    def on_message(self, *args: Any, **kwargs: Any) -> Any:
        assert not args and not kwargs, "V2 运行时的 on_message 只接受裸装饰器"

        def deco(fn: Any) -> Any:
            self.handlers.append(fn)
            return fn

        return deco

    def create_task(self, coro: Any, *_args: Any, **kwargs: Any) -> Any:
        return asyncio.ensure_future(coro)

    def update_config(self, patch: dict[str, Any]) -> None:
        self.config.update(patch)

    async def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.notifications.append((message, kwargs))


# ─── Telethon 风格假事件 ────────────────────────────────────────────────────


class _Btn:
    def __init__(self, text: str) -> None:
        self.text = text


class _Markup:
    def __init__(self, rows: list[list[str]]) -> None:
        self.inline_keyboard = [[_Btn(t) for t in row] for row in rows]


class _Chat:
    def __init__(self, chat_id: int = -100200, title: str = "天空群") -> None:
        self.id = chat_id
        self.title = title


class _OwnMsg:
    def __init__(self, self_flag: str) -> None:
        # self_flag: 'pyrogram' → from_user.is_self；'telethon' → outgoing
        if self_flag == "pyrogram":
            self.from_user = type("U", (), {"is_self": True})()
        else:
            self.outgoing = True


class _Msg:
    def __init__(self, text: str, *, clicks: list[tuple], reply_own: str | None = None) -> None:
        self.id = 555
        self.text = text
        self.chat = _Chat()
        self.sender_id = BOT_ID
        self.reply_markup = _Markup([["16", "23", "42"]])
        self.reply_to_message = _OwnMsg(reply_own) if reply_own else None
        self._clicks = clicks

    async def click(self, i: int | None = None, j: int | None = None) -> None:  # Telethon 签名
        self._clicks.append((i, j))


class _Event:
    def __init__(self, message: _Msg, *, is_group: bool = True, is_private: bool = False) -> None:
        self.message = message
        self.id = message.id
        self.is_group = is_group
        self.is_channel = False
        self.is_private = is_private
        self.client = object()


class _RawClient:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send_message(self, target: Any, text: Any) -> None:
        self.sent.append((target, text))


# ─── 测试 ───────────────────────────────────────────────────────────────────


async def test_setup_survives_v2_runtime(tmp_path: Path) -> None:
    """修复前：setup 抛 AttributeError: 'PluginContext' object has no attribute 'filters'。"""
    ctx = _V2Ctx(config={"bot": str(BOT_ID)}, data_dir=tmp_path)
    assert not hasattr(ctx, "filters")
    await skyDropAnswer.setup(ctx)  # 同步 kv 外观层 + 裸 on_message 注册
    assert len(ctx.handlers) == 2
    assert isinstance(ctx.kv.keys(), list)  # ctx.kv 已被同步外观接管
    await skyDropAnswer.teardown(ctx)


async def test_reward_handler_filters_counts_and_clicks() -> None:
    ctx = _HandlerCtx(config={"enable_reward_answer": True, "bot": str(BOT_ID), "use_ai_fallback": False})
    tpl = {
        "id": "t1",
        "type": "math",
        "regex": r"小秘想给你 (\d+) 银元奖励",
        "status": "verified",
        "count": 0,
        "extract": lambda text: "23",
    }
    answer_mod.register_answer_handler(ctx, [tpl])
    handler = ctx.handlers[0]

    clicks: list[tuple] = []
    msg = _Msg("小秘想给你 10 银元奖励。", clicks=clicks, reply_own="telethon")
    await handler(_Event(msg))
    assert clicks == [(0, 1)]  # Telethon click(i=行, j=列)，答案 23 在第 2 列
    assert ctx.kv.get("trig:drop_count") == 1
    assert ctx.kv.get("trig:drops_this_hour") == 1
    assert tpl["count"] == 1

    # 非掉落文案 / 未回复自己 / 私聊消息都不计数
    await handler(_Event(_Msg("无关消息", clicks=clicks, reply_own="telethon")))
    await handler(_Event(_Msg("小秘想给你 10 银元奖励。", clicks=clicks)))
    private_drop = _Event(
        _Msg("小秘想给你 10 银元奖励。", clicks=clicks, reply_own="telethon"), is_group=False, is_private=True
    )
    await handler(private_drop)
    assert ctx.kv.get("trig:drop_count") == 1
    assert len(clicks) == 1  # 没有新点击


async def test_reward_handler_pyrogram_two_arg_form() -> None:
    ctx = _HandlerCtx(config={"enable_reward_answer": True, "bot": str(BOT_ID), "use_ai_fallback": False})
    answer_mod.register_answer_handler(ctx, [])
    clicks: list[tuple] = []
    msg = _Msg("小秘想给你 10 银元奖励。", clicks=clicks, reply_own="pyrogram")
    await ctx.handlers[0](object(), msg)  # (client, message) 双参数形态
    assert ctx.kv.get("trig:drop_count") == 1


async def test_info_handler_captures_private_reply() -> None:
    ctx = _HandlerCtx(config={"bot": str(BOT_ID)})
    ctx.kv.set("trig:phase", "await_info")
    trigger_mod.register_info_handler(ctx)
    handler = ctx.handlers[0]

    class _PrivateMsg:
        id = 77
        text = "当前时段剩余掉落: 5"
        sender_id = BOT_ID
        is_private = True

    await handler(_Event(_PrivateMsg(), is_group=False, is_private=True))
    assert ctx.kv.get("trig:info_reply") == "当前时段剩余掉落: 5"

    # 掉落文案不当作 /info 回复；非 bot 私聊不捕获
    ctx.kv.set("trig:info_reply", "")

    class _DropMsg(_PrivateMsg):
        text = "小秘想给你 10 银元奖励。"

    class _OtherMsg(_PrivateMsg):
        sender_id = 12345

    await handler(_Event(_DropMsg(), is_group=False, is_private=True))
    await handler(_Event(_OtherMsg(), is_group=False, is_private=True))
    assert ctx.kv.get("trig:info_reply") == ""


async def test_send_text_falls_back_to_user_raw() -> None:
    ctx = _HandlerCtx()
    ctx.user = types.SimpleNamespace()  # 没有 send / send_message 的包装对象
    raw = _RawClient()
    ctx.user.raw = raw
    ok, err = await trigger_mod._send_text(ctx, 123, "hello")
    assert ok and err is None
    assert raw.sent == [(123, "hello")]

    ok, err = await trigger_mod._send_text(_HandlerCtx(), 123, "hello")
    assert not ok and err is None
