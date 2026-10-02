# =============================================================================
# AWBotNest 插件：天空刮奖（scratch）· V2（Telethon 1.44 运行时）
#
# 散财童子（@lucifer_hdsky_bot）刮刮乐自动挂机。自 V1 1.6.2 移植，玩法不变：
# 发 /scratch → 检测 Bot 发出的刮刮乐卡片（卡面「玩家：<本账号显示名>」判归属，
# 见 SPEC §12.1）→ 随机逐格刮开 → 回本就停；连续亏损自动停止，关闭插件再开重置。
#
# 双通道（v1.7.0 真机实测）：卡片实测由 Bot **私聊**送达、群聊只贴公告，所以 handler
# 同时认「目标群」与「与 Bot 的私聊」两个会话：
#   · 群聊通道：定时器每 group_send_interval（默认 120 秒）发一次 /scratch 刷「游戏掉落」，
#     本时段掉落满（/info 解析剩余 0）时暂停，整点刷新自动恢复；
#   · 私聊通道：卡片刮完立刻开下一张、不限次数（pm_unlimited），是刮奖收益主通道。
# =============================================================================

from __future__ import annotations

import asyncio
import inspect
import random
import re
import time

__plugin__ = {
    "name": "天空刮奖",
    "id": "scratch",
    "version": "1.7.0",
    "author": "Yy",
    "description": "散财童子刮刮乐自动挂机（V2）：群聊定时刷掉落 + 私聊不限次连锁；按钮+命令双试，卡面归属过滤 Bot。",
    "icon": "https://raw.githubusercontent.com/yyned2501/AWBotNest-Plugins/main/icons/scratch.svg",
    "scope": "user",
    "plugin_api_version": 2,
    "config_schema": {
        "target_group": {
            "type": "string",
            "default": "-1001326208894",
            "label": "目标群组ID",
            "section": "基础",
            "help": "Bot 所在群组，发 /scratch 和监听都在此群。",
        },
        "bot_id": {
            "type": "number",
            "default": 0,
            "label": "Bot 的 Telegram ID",
            "section": "基础",
            "help": "@lucifer_hdsky_bot 的数字 ID。填 0 = 不按 Bot 过滤（会处理群内所有刮刮乐）。",
            "min": 0,
            "max": 9999999999,
        },
        "player_names": {
            "type": "string",
            "default": "",
            "label": "卡片玩家名（逗号分隔）",
            "section": "基础",
            "help": "卡面「玩家：」应匹配的名字，逗号分隔。显示名是花体/别名导致识别不到时在此填写（如 Yy）。",
        },
        "click_delay": {
            "type": "slider",
            "default": 0.6,
            "label": "点击间隔(秒)",
            "section": "防封",
            "min": 0.3,
            "max": 2.0,
            "step": 0.1,
            "help": "每格点击之间的等待时间，加 ±20% 随机抖动。",
        },
        "card_cooldown": {
            "type": "slider",
            "default": 5,
            "label": "卡间冷却(秒)",
            "section": "防封",
            "min": 2,
            "max": 30,
            "step": 1,
            "help": "上一张结束后等 N 秒再发 /scratch，随机加 0~3 秒。",
        },
        "max_consecutive_loss": {
            "type": "number",
            "default": 5,
            "label": "连续亏损自动停止",
            "section": "策略",
            "help": "连续 N 张净亏损后自动停止刮奖。关闭插件再开即可重置。",
            "min": 1,
            "max": 20,
        },
        "group_send_interval": {
            "type": "number",
            "default": 120,
            "label": "群聊发送间隔(秒)",
            "section": "策略",
            "help": "群聊通道自动发 /scratch 的最小间隔，默认 120 秒（每 2 分钟一次）。私聊通道不受此限制。",
            "min": 30,
            "max": 3600,
        },
        "pm_unlimited": {
            "type": "boolean",
            "default": True,
            "label": "私聊通道不限次",
            "section": "策略",
            "help": "勾选：私聊收到的卡片刮完立刻开下一张，不限次、不受群聊间隔限制。取消：私聊卡片不连锁。",
        },
        "drop_guard_enabled": {
            "type": "boolean",
            "default": True,
            "label": "掉落配额守卫",
            "section": "策略",
            "help": "定期私聊发 /info 查「当前时段剩余掉落」；剩余 0 时暂停群聊发送，整点刷新自动恢复。",
        },
        "drop_check_interval": {
            "type": "number",
            "default": 10,
            "label": "掉落检查间隔(分)",
            "section": "策略",
            "help": "每多少分钟私聊发一次 /info 校准掉落配额（整点对齐）。",
            "min": 5,
            "max": 60,
        },
    },
}

# ── 模块级状态（仅内存，停用/重载即重置，与 V1 语义一致）──────────
_playing: bool = False  # 防止同时玩多张卡
_consecutive_loss: int = 0  # 连续亏损计数
_auto_stopped: bool = False  # 连续亏损后自动停止

# 去重
_seen: dict[str, float] = {}
_SEEN_TTL: float = 300

# 本账号显示名缓存（client → 候选名元组），仅内存，停用/重载即重置
_self_names: dict[int, tuple[str, ...]] = {}

# ── 双通道 / 掉落守卫状态（仅内存，停用/重载即重置）──────────
_group_last_sent: float = 0.0  # 上次群聊发 /scratch 的时间戳
_group_last_skip_log: float = 0.0  # 上次「掉落已满跳过」日志时间（防刷屏）
_drop_game_remaining: int | None = None  # 最近一次 /info 解析出的本时段「游戏」剩余掉落
_drop_checked_ts: float = 0.0  # 最近一次成功解析 /info 回复的时间

_DROP_STALE_AFTER: float = 3600.0  # /info 结果超过 1 小时视为过期（时段本就按小时轮换）
_INFO_IGNORE_TEXT = "银元奖励"  # 掉落消息不是 /info 回复（照抄 skyGame/games/drop_guard.py）
_DROP_LINE_RE = re.compile(r"当前时段剩余掉落[:：]\s*聊天\s*(\d+)\s*·\s*游戏\s*(\d+)")
_DROP_LINE_LEGACY_RE = re.compile(r"当前时段剩余掉落[:：]\s*(\d+)")


# ── 工具函数 ────────────────────────────────────────


def _parse_group(raw: object) -> int | None:
    """解析目标群 ID（多行取首行），非法返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return int(text.split("\n")[0].strip())
    except ValueError:
        return None


def _extract_message(args: tuple[object, ...], kwargs: dict[str, object]) -> tuple[object | None, object | None]:
    """从平台回调参数中取出 (message, event)。

    V2 平台底层是 Telethon：回调只收到单个 event（event.message 才是消息）。
    Pyrogram 适配期为 (client, message) 双参数，第二参数即消息本身。
    """
    if args and not kwargs and len(args) == 1:
        raw = args[0]
    elif len(args) >= 2:
        raw = args[1]
    else:
        raw = kwargs.get("event") or kwargs.get("message") or kwargs.get("update")
    if raw is None:
        return None, None
    return (getattr(raw, "message", None) or raw), raw


def _client_of(event: object, args: tuple[object, ...]) -> object | None:
    """取用户 client：V2 单 event 时是 event.client；双参数形态是 args[0]。"""
    client = getattr(event, "client", None)
    if client is None and args:
        client = getattr(args[0], "client", None)
    return client


def _message_text(message: object) -> str:
    """取消息文本。Telethon 无 caption，只能用 text/raw_text。"""
    return str(getattr(message, "text", None) or getattr(message, "raw_text", None) or "")


def _button_rows(message: object) -> list[list[object]]:
    """取内联键盘按钮矩阵（行 → 列）。

    V2/Telethon：reply_markup.rows[r].buttons[c]（V1 的内联键盘结构已不可用）。
    """
    markup = getattr(message, "reply_markup", None)
    rows = getattr(markup, "rows", None)
    if not rows:
        return []
    return [list(getattr(row, "buttons", None) or []) for row in rows]


def _button_data(button: object) -> str:
    """取按钮 callback data（bytes → str），兼容两个运行时的按钮形态。

    - Telethon 1.44：回调数据在 ``button.data``（``KeyboardButtonCallback``）
    - Telethon 1.45+：``KeyboardInlineButton`` **没有 ``.data``**，数据在 ``button.type.data``
      （SPEC §12.2 真机实测）

    先取 ``type.data``、回退 ``data``，两个版本都不坏。
    """
    for holder in (getattr(button, "type", None), button):
        data = getattr(holder, "data", None)
        if isinstance(data, bytes):
            return data.decode("utf-8", "ignore")
        if isinstance(data, str):
            return data
    return ""


def _sender_id(message: object, event: object) -> int | None:
    """取发送者 ID，兼容 Telethon（sender_id/from_id）与 Pyrogram（from_user.id）。"""
    for obj in (message, event):
        sid = getattr(obj, "sender_id", None)
        if isinstance(sid, int):
            return sid
        sender = getattr(obj, "from_user", None) or getattr(obj, "sender", None)
        fid = getattr(sender, "id", None)
        if isinstance(fid, int):
            return fid
        peer = getattr(obj, "from_id", None)
        pid = getattr(peer, "user_id", None)
        if isinstance(pid, int):
            return pid
    return None


def _is_scratch_card(message: object) -> bool:
    """卡片识别：文本含「刮刮乐」且存在 data 以 scratch: 开头的按钮。"""
    if "刮刮乐" not in _message_text(message):
        return False
    for row in _button_rows(message):
        for button in row:
            if _button_data(button).startswith("scratch:"):
                return True
    return False


def _is_own_card(message: object, names: tuple[str, ...]) -> bool:
    """归属判定（SPEC §12.1 真机实测 + 规则 A）：卡面「玩家：」字段是本账号显示名。

    卡片是 Bot 独立发出的消息（实测 ``reply_to_msg_id=None``，不回复任何人的 ``/scratch``），
    所以 ``event.get_reply_message()`` 的 ``out`` 标记恒为 None，**不能**用来判归属。

    取「玩家：」之后的**整行字段**（``strip()``）后只认两种形态：

    ① 字段与某个候选名**完全相等** —— 真机卡面 ``玩家：Yy`` 走这条；
    ② 字段是「候选名 + 一整段括号注记」（``玩家：Yy（我）``），Bot 追加注记时仍算本账号。

    不允许「候选名 + 空格 + 任意内容」：``玩家：Yy Zhang2`` 与真机 ``玩家：Yy IX``（自己）在
    字符串上同形，任何前缀规则都必然二选一；漏判 = 不刮 = 零开销，误判 = 点别人的卡 = 真花钱，
    所以取最保守的整行字段族（本插件原则「宁漏不抢」）。
    """
    text = _message_text(message)
    for raw_line in text.splitlines():
        if "玩家：" not in raw_line:
            continue
        field = raw_line.split("玩家：", 1)[1].strip()
        for name in names:
            if not name:
                continue
            if field == name:
                return True
            if re.fullmatch(re.escape(name) + r"\s*[（(][^（()）]*[)）]", field):
                return True
    return False


async def _self_display_names(ctx: object, client: object) -> tuple[str, ...]:
    """取本账号显示名的候选集合（first_name、first_name+last_name），按 client 缓存在内存里。

    只服务归属判定；不落 kv，停用/重载即重置。Telethon 1.44/1.45 的 client
    没有 ``.me`` 缓存属性，只能 ``await get_me()``。
    """
    if client is None:
        return ()
    key = id(client)
    cached = _self_names.get(key)
    if cached:
        return cached
    get_me = getattr(client, "get_me", None)
    if not callable(get_me):
        return ()
    try:
        me = await get_me()
    except Exception as exc:  # noqa: BLE001 - 取不到名字按不处理，不拖垮 handler
        ctx.log.warning("取本账号信息失败，跳过卡片：%r", exc)
        return ()
    first = str(getattr(me, "first_name", "") or "").strip()
    last = str(getattr(me, "last_name", "") or "").strip()
    names = tuple(dict.fromkeys(part for part in (first, f"{first} {last}".strip()) if part))
    if names:
        _self_names[key] = names
    return names


def _parse_card(message: object) -> tuple[int | None, dict[int, tuple[int, int]], tuple[int, int] | None]:
    """解析卡片：返回 (卡号, {格号: (行,列)}, 放弃按钮位置)。"""
    card_id: int | None = None
    cells: dict[int, tuple[int, int]] = {}
    abandon_pos: tuple[int, int] | None = None

    for r, row in enumerate(_button_rows(message)):
        for c, button in enumerate(row):
            data = _button_data(button)
            if not data.startswith("scratch:"):
                continue
            parts = data.split(":")
            if len(parts) < 3:
                continue
            if card_id is None:
                try:
                    card_id = int(parts[1])
                except ValueError:
                    pass
            action = parts[2]
            if action == "abandon":
                abandon_pos = (r, c)
            elif action == "all":
                continue
            else:
                try:
                    cell_num = int(action)
                    if 1 <= cell_num <= 9:
                        cells[cell_num] = (r, c)
                except ValueError:
                    pass
    return card_id, cells, abandon_pos


def _parse_cell_payout(cb_text: str) -> int | None:
    """从 callback_answer.message 解析单格点数。例: "获得 5 银元，净收益 -95 银元。" → 5"""
    if not cb_text:
        return None
    match = re.search(r"获得\s*(\d+)\s*银元", cb_text)
    return int(match.group(1)) if match else None


def _prune_seen() -> None:
    """清理过期的去重记录，防无界增长。"""
    now = time.time()
    for key in [k for k, ts in _seen.items() if now - ts > _SEEN_TTL]:
        _seen.pop(key, None)


def _parse_drop_line(text: str) -> int | None:
    """从 /info 回执（或半小时状态卡）解析本时段「游戏」剩余掉落；解析不出返回 None。

    真机格式（2026-10-02 实测）：``当前时段剩余掉落: 聊天 3 · 游戏 0``。
    只看「游戏」——群聊发 /scratch 消耗的是游戏配额；「聊天」配额与发命令无关。
    """
    body = str(text or "")
    match = _DROP_LINE_RE.search(body)
    if match:
        return int(match.group(2))
    legacy = _DROP_LINE_LEGACY_RE.search(body)
    return int(legacy.group(1)) if legacy else None


def _update_drop_remaining(ctx: object, remaining: int) -> None:
    """记录 /info 解析出的剩余掉落；状态翻转时各提示一次。"""
    global _drop_game_remaining, _drop_checked_ts
    prev = _drop_game_remaining
    _drop_game_remaining = remaining
    _drop_checked_ts = time.time()
    if prev != remaining:
        ctx.log.info(
            "掉落守卫：本时段剩余掉落 %d（%s）",
            remaining,
            "已满，暂停群聊发送" if remaining <= 0 else "未满，照常群聊发送",
        )


def _drop_exhausted(now: float | None = None) -> bool:
    """本时段「游戏」掉落是否已满（剩余 0）→ 群聊发送该暂停。

    跨整点直接返回 False：时段按小时轮换、配额必然刷新，不等 /info 回执
    （照抄 skyGame/games/drop_guard.py 的 v1.23.7 语义）；/info 结果本身 1 小时后也失效。
    """
    ts = time.time() if now is None else now
    if _drop_game_remaining is None or _drop_checked_ts <= 0:
        return False
    if int(ts // 3600) != int(_drop_checked_ts // 3600):
        return False  # 跨整点：新时段配额已刷新
    if ts - _drop_checked_ts > _DROP_STALE_AFTER:
        return False
    return _drop_game_remaining <= 0


def _result_text(result: object) -> str:
    """从点击返回里取回调文案（Telethon BotCallbackAnswer.message 是 str）。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    for attr in ("message", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    return ""


# ── 重拉消息 / 点击 / 发送 ──────────────────────────


async def _refetch_card(
    ctx: object, client: object, chat_id: object, msg_id: int, event: object = None
) -> object | None:
    """重拉消息拿最新键盘。

    主写法：Telethon ``get_messages(msg.chat_id, ids=msg_id)``（第二个位置参数是 limit，必须用 ``ids=``）。
    回退①：先 ``await event.get_chat()`` 取回实体再拉。
    两条都失败返回 None（调用方按累计值结算，不崩）。
    """
    try:
        message = await client.get_messages(chat_id, ids=msg_id)
        if message:
            return message
        ctx.log.warning("重拉消息返回空 msg=%s", msg_id)
    except Exception as exc:  # noqa: BLE001 - 网络/实体解析失败都要回退
        ctx.log.warning("重拉消息失败（主写法 chat_id=%s）msg=%s: %r", chat_id, msg_id, exc)

    get_chat = getattr(event, "get_chat", None) if event is not None else None
    if callable(get_chat):
        try:
            chat = await get_chat()
            message = await client.get_messages(chat, ids=msg_id)
            if message:
                ctx.log.info("重拉消息成功（回退 get_chat）msg=%s", msg_id)
                return message
        except Exception as exc:  # noqa: BLE001 - 回退链最后一跳
            ctx.log.warning("重拉消息失败（回退 get_chat）msg=%s: %r", msg_id, exc)
    return None


async def _click_index(message: object, row: int, col: int) -> str:
    """点击内联按钮，返回回调文案。

    V2/Telethon 1.44 签名是 ``click(i=行, j=列)``；拿不到签名时退回位置参数
    ``click(行, 列)``，避免位置参数被别的运行时解释成行列互换。
    """
    click = getattr(message, "click", None)
    if not callable(click):
        return ""
    try:
        params = set(inspect.signature(click).parameters)
    except (TypeError, ValueError):
        params = set()
    if {"i", "j"} & params:
        result = await click(i=row, j=col)
    elif {"x", "y"} & params:
        # Pyrogram 时代的签名把列放在 x、行放在 y：用 kwargs 传，避免位置参数被当成行列互换
        result = await click(**{"x": col, "y": row})
    else:
        result = await click(row, col)
    return _result_text(result)


async def _click_btn(
    ctx: object,
    client: object,
    chat_id: object,
    msg_id: int,
    row: int,
    col: int,
    label: str = "格子",
    event: object = None,
    snapshot: object = None,
) -> str | None:
    """点击按钮，带重试。返回 callback_answer 文本（含「获得 X 银元」），失败返回 None。

    重拉消息的两条路都失败时回退②：改用事件里的 message 快照点击（功能降级，
    按钮位置可能错位；回执解析不出就按累计值结算，不会崩）。
    """
    for attempt in range(3):
        try:
            message = await _refetch_card(ctx, client, chat_id, msg_id, event)
            if not message and snapshot is not None:
                ctx.log.warning("重拉失败，回退②用事件快照点击 (%s) msg=%s", label, msg_id)
                message = snapshot
            if not message:
                ctx.log.warning("get_messages 返回空且无可用快照 (%s) msg=%s", label, msg_id)
                return None

            rows = _button_rows(message)
            if row >= len(rows) or col >= len(rows[row]):
                ctx.log.warning("按钮 (%d,%d) 已消失 msg=%s", row, col, msg_id)
                return None

            return await _click_index(message, row, col)
        except Exception as exc:  # noqa: BLE001 - 点击失败按类别重试或放弃
            err_s = str(exc).upper()
            if "FLOOD_WAIT" in err_s:
                match = re.search(r"(\d+)", str(exc))
                wait = int(match.group(1)) if match else 3
                ctx.log.warning("⏳ FloodWait %ss (%s)", wait, label)
                await asyncio.sleep(wait)
                continue
            if "BUTTON_DATA_INVALID" in err_s or "MESSAGE_ID_INVALID" in err_s:
                ctx.log.warning("消息已失效 msg=%s (%s)", msg_id, label)
                return None
            if attempt < 2:
                ctx.log.warning("点击%s失败 (attempt %d/3): %s，1s后重试", label, attempt + 1, exc)
                await asyncio.sleep(1)
            else:
                ctx.log.warning("点击%s失败 (attempt %d/3): %s", label, attempt + 1, exc)
    return None


def _send_candidates(ctx: object) -> list[object]:
    """发送兜底链：ctx.user → ctx.user.raw → ctx.bot.raw → ctx.bot。

    链条照抄 skyGame/games/drop_guard.py:151；末尾的裸 ``ctx.bot`` 是必要的补充——
    V2 的 ``ctx.bot`` 本身就是 Telethon client（awbotnest/context.py:153），
    没有 ``.raw``，只有它才带 ``send_message``。
    """
    candidates: list[object] = []
    user = getattr(ctx, "user", None)
    if user is not None:
        candidates.append(user)
        if getattr(user, "raw", None) is not None:
            candidates.append(user.raw)
    bot = getattr(ctx, "bot", None)
    bot_raw = getattr(bot, "raw", None) if bot is not None else None
    if bot_raw is not None and bot_raw is not getattr(user, "raw", None):
        candidates.append(bot_raw)
    if bot is not None and bot is not bot_raw:
        candidates.append(bot)
    return candidates


async def _send_command(ctx: object, chat_id: object, command: str, label: str = "") -> bool:
    """向指定会话发送命令（/scratch、/info），带重试与发送兜底链。返回 True=成功。"""
    for attempt in range(3):
        last_err: Exception | None = None
        for client_obj in _send_candidates(ctx):
            try:
                send = getattr(client_obj, "send", None)
                if callable(send):
                    await send(chat_id, command)
                    return True
                send_message = getattr(client_obj, "send_message", None)
                if callable(send_message):
                    await send_message(chat_id, command)
                    return True
            except Exception as exc:  # noqa: BLE001 - 依次尝试下一个发送端
                last_err = exc
        if last_err is not None and "FLOOD_WAIT" in str(last_err).upper():
            match = re.search(r"(\d+)", str(last_err))
            wait = int(match.group(1)) if match else 3
            ctx.log.warning("⏳ 发送 /scratch FloodWait %ss", wait)
            await asyncio.sleep(wait)
            continue
        ctx.log.warning("发送 %s 失败 (attempt %d/3)%s: %s", command, attempt + 1, label, last_err)
        if attempt < 2:
            await asyncio.sleep(2)
    return False


async def _send_scratch(ctx: object, chat_id: object, label: str = "") -> bool:
    """发送 /scratch（保留旧名：既有调用方与测试不变）。"""
    return await _send_command(ctx, chat_id, "/scratch", label)


# ── 刮奖策略 ────────────────────────────────────────


async def _play_card(ctx: object, client: object, message: object, cfg: dict, event: object = None) -> dict | None:
    """刮一张卡：随机顺序逐格点击，累计派奖 ≥ 已刮格数×100 立即点「放弃」停手。"""
    chat_id = getattr(message, "chat_id", None)
    msg_id = int(getattr(message, "id", 0) or 0)
    chat_title = getattr(getattr(message, "chat", None), "title", "")
    msg_link = getattr(message, "link", "")

    card_id, cells, _ = _parse_card(message)
    if not card_id or not cells:
        ctx.log.warning("无法解析刮刮乐 msg=%s", msg_id)
        return None

    ctx.log.info("刮奖开始 卡#%s msg=%s", card_id, msg_id)

    remaining = list(range(1, 10))
    random.shuffle(remaining)

    cells_revealed = 0
    cum_payout = 0
    click_delay = float(cfg.get("click_delay", 0.6) or 0)

    for cell_num in remaining:
        # 重新拉消息看当前键盘状态；两条路都失败则回退②用事件快照（功能降级）
        refetched = await _refetch_card(ctx, client, chat_id, msg_id, event)
        if not refetched:
            ctx.log.warning("重拉消息失败，回退②用事件快照 格%s msg=%s", cell_num, msg_id)
            refetched = message
        if not refetched:
            continue

        _, current_cells, _ = _parse_card(refetched)
        if cell_num not in current_cells:
            continue

        row, col = current_cells[cell_num]

        await asyncio.sleep(click_delay * random.uniform(0.8, 1.2))

        cb_text = await _click_btn(ctx, client, chat_id, msg_id, row, col, f"格{cell_num}", event, snapshot=message)
        if cb_text is None:
            # 按钮失效 → 当前卡报废，用累计值结算
            cost = cells_revealed * 100
            net = cum_payout - cost
            ctx.log.warning("卡#%s 中断 格%s失效 累计%d 净%d", card_id, cell_num, cum_payout, net)
            if cells_revealed > 0:
                return {
                    "card_id": card_id,
                    "cells": cells_revealed,
                    "payout": cum_payout,
                    "cost": cost,
                    "net": net,
                }
            return None

        # 从回调文本解析单格点数
        cell_val = _parse_cell_payout(cb_text)
        if cell_val is not None:
            cum_payout += cell_val
        else:
            # 解析失败 → 尝试从消息文本回退（差分累计）
            ctx.log.debug("回调文本解析失败，回退到消息文本: %s", cb_text[:80])
            refetched = await _refetch_card(ctx, client, chat_id, msg_id, event)
            if refetched:
                match = re.search(r"已派奖：(\d+) 银元", _message_text(refetched))
                if match:
                    new_total = int(match.group(1))
                    diff = new_total - cum_payout
                    if diff > 0:
                        cell_val = diff
                        cum_payout = new_total
        if cell_val is None:
            cell_val = 0

        cells_revealed += 1

        ctx.log.info(
            "卡#%s 格%s %d/9 获得%d 累计%d 成本%d",
            card_id,
            cell_num,
            cells_revealed,
            cell_val,
            cum_payout,
            cells_revealed * 100,
        )

        if cum_payout >= cells_revealed * 100:
            ctx.log.info("✅ 回本 卡#%s %d格 累计%d", card_id, cells_revealed, cum_payout)

            # 点「放弃」按钮（重新拉消息拿最新位置；失败回退②用事件快照）
            refetched = await _refetch_card(ctx, client, chat_id, msg_id, event) or message
            _, _, abandon_pos = _parse_card(refetched)
            if abandon_pos:
                await _click_btn(
                    ctx,
                    client,
                    chat_id,
                    msg_id,
                    abandon_pos[0],
                    abandon_pos[1],
                    "放弃",
                    event,
                    snapshot=message,
                )
            else:
                ctx.log.warning("找不到「放弃」按钮 卡#%s msg=%s", card_id, msg_id)

            net = cum_payout - cells_revealed * 100
            await ctx.notify(
                f"🏠 群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"🎰 刮奖结果\n   卡#{card_id} | 刮{cells_revealed}格\n"
                f"   累计{cum_payout} | 成本{cells_revealed * 100} | 净{net:+d}\n"
                f"   ✅ 回本就停\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="success",
                category="回本",
                account=client,
            )
            return {
                "card_id": card_id,
                "cells": cells_revealed,
                "payout": cum_payout,
                "cost": cells_revealed * 100,
                "net": net,
            }

    # 全刮完或中断
    cost = cells_revealed * 100
    net = cum_payout - cost
    emoji = "❌" if net < 0 else "⚠️"
    tag = "亏损" if net < 0 else "中断"

    ctx.log.info("卡#%s %s %d格 累计%d 成本%d 净%d", card_id, tag, cells_revealed, cum_payout, cost, net)

    await ctx.notify(
        f"🏠 群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
        f"🎰 刮奖结果\n   卡#{card_id} | 刮{cells_revealed}格\n"
        f"   累计{cum_payout} | 成本{cost} | 净{net:+d}\n"
        f"   {emoji} {tag}\n\n"
        f"🔗 消息链接\n   {msg_link}",
        level="success" if net >= 0 else "warning",
        category=tag,
        account=client,
    )
    return {
        "card_id": card_id,
        "cells": cells_revealed,
        "payout": cum_payout,
        "cost": cost,
        "net": net,
    }


# ── setup / teardown ────────────────────────────────


async def setup(ctx: object) -> None:
    """注册处理器。V2 的 on_message 只接受裸装饰器，无 filters、无 group。"""
    global _playing, _consecutive_loss, _auto_stopped
    global _group_last_sent, _group_last_skip_log, _drop_game_remaining, _drop_checked_ts

    _playing = False
    _auto_stopped = False
    _consecutive_loss = 0
    _seen.clear()
    _self_names.clear()
    _group_last_sent = 0.0
    _group_last_skip_log = 0.0
    _drop_game_remaining = None
    _drop_checked_ts = 0.0

    cfg = ctx.config
    bot_id = int(cfg.get("bot_id", 0) or 0)

    ctx.log.info("天空刮奖插件已启用 bot_id=%s", bot_id)
    if bot_id:
        ctx.log.info("Bot 过滤已启用 bot_id=%s", bot_id)
    else:
        ctx.log.warning("bot_id=0，将处理目标群内所有刮刮乐（不按 Bot 过滤）")

    @ctx.on_message()
    async def on_scratch_card(*args: object, **kwargs: object) -> None:
        global _playing, _consecutive_loss, _auto_stopped

        message, event = _extract_message(args, kwargs)
        if message is None:
            return

        target = _parse_group(cfg.get("target_group", ""))
        if not target:
            return

        chat_id = getattr(message, "chat_id", None)
        if chat_id is None:
            chat_id = getattr(getattr(message, "chat", None), "id", None)
        # 双通道（v1.7.0 真机实测）：卡片由 Bot 私聊送达，群聊只贴公告 → 两个会话都要认
        allowed_chats = {str(target)}
        if bot_id:
            allowed_chats.add(str(bot_id))
        if chat_id is None or str(chat_id) not in allowed_chats:
            return
        is_pm = bool(bot_id) and str(chat_id) == str(bot_id)

        if bot_id:
            sender = _sender_id(message, event)
            if sender is not None and sender != bot_id:
                return

        # Bot 回执校准（双通道共用）：/info 回执与半小时状态卡都带「当前时段剩余掉落」
        remaining = _parse_drop_line(_message_text(message))
        if remaining is not None:
            _update_drop_remaining(ctx, remaining)
            return

        if _auto_stopped:
            return

        if not _is_scratch_card(message):
            return

        client = _client_of(event, args)

        # 归属判定（SPEC §12.1 真机实测，推翻原 §9.3）：卡片是 Bot 独立发出的消息，
        # reply_to_msg_id=None，所以 event.get_reply_message() 的 out 标记恒为 None，
        # 不能用来判归属；改为核对卡面「玩家：<本账号显示名>」（取不到名字 → 不处理，宁漏不抢）。
        names = await _self_display_names(ctx, client)
        # 显式别名优先：显示名改成花体/别名后（如 𝐘𝐲 𝐈𝐗）自动探测拿不到卡面玩家名，
        # 由配置补进候选集合；_is_own_card 仍走严格相等，不引入前缀误配（宁漏不抢）。
        extra_names = tuple(
            n.strip() for n in str(cfg.get("player_names", "") or "").split(",") if n.strip()
        )
        if extra_names:
            names = tuple(dict.fromkeys(extra_names + tuple(names)))
        if not names:
            ctx.log.warning(
                "⚠️ 取不到本账号显示名（也未配置 player_names），无法判定归属，跳过 msg=%s",
                getattr(message, "id", None),
            )
            return
        if not _is_own_card(message, names):
            return

        ctx.log.info("🎰 识别到刮刮乐 msg=%s", getattr(message, "id", None))

        # 去重
        _prune_seen()
        key = f"{chat_id}:{getattr(message, 'id', None)}"
        if key in _seen:
            return
        _seen[key] = time.time()

        if _playing:
            ctx.log.info("⏳ 正在玩卡中，跳过 msg=%s", getattr(message, "id", None))
            return

        _playing = True
        try:
            result = await _play_card(ctx, client, message, cfg, event)
            if not result:
                return

            if result["net"] >= 0:
                _consecutive_loss = 0
            else:
                _consecutive_loss += 1
                ctx.log.info("📉 连续亏损 %d 张", _consecutive_loss)

            max_loss = int(cfg.get("max_consecutive_loss", 5) or 5)
            if _consecutive_loss >= max_loss:
                _auto_stopped = True
                ctx.log.warning("🛑 连续亏损达上限，自动停止")
                chat_title = getattr(getattr(message, "chat", None), "title", "")
                await ctx.notify(
                    f"🛑 天空刮奖已自动停止\n\n"
                    f"🏠 群组\n   {chat_title}\n   群ID: {target}\n\n"
                    f"⚠️ 原因\n   连续 {_consecutive_loss} 张亏损\n\n"
                    f"💡 重新开始\n   在插件管理关闭再开启「🎰天空刮奖」",
                    level="warning",
                    category="自动停止",
                    account=client,
                )
                return  # 不连锁

            # 连锁分流：私聊通道不限次（刮完立刻开下一张）；群聊通道**不在此连锁**——
            # 群发节奏交给 group_send_interval 定时器，避免群里每几秒刷一条 /scratch。
            if is_pm and bool(cfg.get("pm_unlimited", True)):
                cooldown = int(cfg.get("card_cooldown", 5) or 5)
                wait = cooldown + random.uniform(0, 3)
                ctx.log.info("🔄 %.1fs 后私聊发送 /scratch（连续亏损=%d）", wait, _consecutive_loss)
                await asyncio.sleep(wait)
                if await _send_scratch(ctx, chat_id, f" 私聊 连续亏损={_consecutive_loss}"):
                    ctx.log.info("📤 已在私聊发送 /scratch")
        except Exception:  # noqa: BLE001 - 单卡异常不拖垮 handler
            ctx.log.exception("刮奖流程异常")
        finally:
            _playing = False

    schedule = getattr(ctx, "schedule", None)
    if not callable(schedule):
        ctx.log.warning("平台无 ctx.schedule，群聊定时发送与掉落守卫均不启动")
        return

    # 群聊定时器在 setup 作用域发命令，必须在此解析一次目标群（handler 里的是局部变量）
    group_target = _parse_group(cfg.get("target_group", ""))
    if not group_target:
        ctx.log.error("target_group 未配置，群聊定时发送不启动")
        return

    async def _group_tick() -> None:
        """群聊通道：每 group_send_interval 秒发一次 /scratch 刷掉落；本时段掉落满则暂停。"""
        global _group_last_sent, _group_last_skip_log
        if _auto_stopped:
            return
        interval = max(30, int(cfg.get("group_send_interval", 120) or 120))
        now = time.time()
        if now - _group_last_sent < interval * 0.9:  # 定时器抖动保护，不重复发
            return
        if bool(cfg.get("drop_guard_enabled", True)) and _drop_exhausted(now):
            if now - _group_last_skip_log > 600:  # 每 10 分钟最多提示一次，防刷日志
                _group_last_skip_log = now
                ctx.log.info("🪙 本时段掉落已满（剩余 %s），暂停群聊发送到整点", _drop_game_remaining)
            return
        _group_last_sent = now
        if await _send_scratch(ctx, group_target, " 群聊定时"):
            ctx.log.info("📤 已在群内发送 /scratch（定时 %ds）", interval)

    async def _info_tick() -> None:
        """掉落守卫：私聊 Bot 发 /info，回执由 on_scratch_card 解析校准配额。"""
        if not bot_id or not bool(cfg.get("drop_guard_enabled", True)):
            return
        if await _send_command(ctx, bot_id, "/info", " 掉落查询"):
            ctx.log.info("🪙 已私聊 Bot 发送 /info 查询本时段剩余掉落")

    group_interval = max(30, int(cfg.get("group_send_interval", 120) or 120))
    check_minutes = max(5, min(60, int(cfg.get("drop_check_interval", 10) or 10)))
    schedule(_group_tick, "interval", seconds=group_interval, id="scratch_group_send")
    if bot_id:
        schedule(_info_tick, "cron", minute=f"*/{check_minutes}", id="scratch_drop_check")
    ctx.log.info(
        "双通道已启动：群聊每 %ds 发一次 /scratch（掉落满自动暂停）、私聊%s、掉落守卫每 %d 分查一次",
        group_interval,
        "不限次连锁" if bool(cfg.get("pm_unlimited", True)) else "不自动连锁",
        check_minutes,
    )


async def teardown(ctx: object) -> None:
    ctx.log.info("天空刮奖插件已停用")
