# -*- coding: utf-8 -*-
# 天空游戏 · 掉落守卫
#
# 天空小秘的银元掉落有时段配额，配额满后参与游戏也领不到掉落奖励，
# 白耗报名银元/体力。本模块定期私聊 bot 发 /info，解析「当前时段剩余掉落」：
# 剩余为 0 → 拦截各游戏的新加入（十点半报名/炸金花入桌/赛马报名），
# 时段切换后剩余回升 → 自动恢复。实现参照 skyDropAnswer 的 /info 校准模式，
# 各插件自行读取，互不依赖（插件间禁止互相 import）。
#
# 时段的切换点是整点（实测按小时轮换）：跨整点即视为新时段、配额必然刷新，
# paused() 直接解除暂停——不用等 interval 周期的 /info 回执才恢复（v1.23.7）；
# /info 回执仅用于刷新剩余数与状态翻转通知。
#
# 对外只有三个入口，全插件的「掉落配额」口径都从这里出（不要再另开一份 /info 解析）：
#   paused(ctx)      各游戏用：满了就别新加入
#   remaining(ctx)   还剩几次可领（None = 数字不可用，该先 refresh）
#   refresh(ctx)     主动催一次 /info（刮奖兜底每张刮完刷剩余）
#
# kv 键：
#   dropguard:remaining   最近一次 /info 解析出的本时段剩余掉落
#   dropguard:checked_ts  最近一次成功解析 /info 回复的时间
#   dropguard:sent_ts     最近一次发送 /info 的时间（防无回复时重复发送、也用于 refresh 节流）
#   dropguard:paused      当前暂停状态（用于状态翻转时只通知一次）

from __future__ import annotations

import re
import time

# /info 回复里的配额行。新格式（2026-08-19 实测）把配额拆成两类：
#   当前时段剩余掉落: 聊天 3 · 游戏 0
# 游戏参与只消耗「游戏」配额；旧格式为纯数字，兼容回退。
_INFO_GAME_RE = re.compile(r"当前时段剩余掉落[:：]\s*聊天\s*\d+\s*·\s*游戏\s*(\d+)")
_INFO_LEGACY_RE = re.compile(r"当前时段剩余掉落[:：]\s*(\d+)")

_KV_REMAINING = "dropguard:remaining"
_KV_CHECKED_TS = "dropguard:checked_ts"
_KV_SENT_TS = "dropguard:sent_ts"
_KV_PAUSED = "dropguard:paused"

_DEFAULT_BOT = 8907007783  # 天空小秘（与 skyDropAnswer 默认值一致；int 避免被当作用户名）
_STALE_AFTER = 3600.0  # /info 结果超过 1 小时视为过期：时段本就按小时轮换，也防一次误判长期锁死
_DEFAULT_INTERVAL_MIN = 10  # 默认 /info 检查间隔（分钟）；cron 表达式 */N 由此生成，整点对齐
_REFRESH_MIN_INTERVAL = 20.0  # refresh() 两次 /info 之间的最小间隔（秒），防私聊刷屏


def _parse_bot_ids(raw: str) -> list[int | str]:
    """解析 bot 配置（@用户名 或 数字ID，逗号分隔）为 filters.user 可用的列表。

    纯数字转 int（pyrogram 按 ID 过滤更快），其余按用户名。留空回退默认天空小秘。
    """
    out: list[int | str] = []
    for part in (raw or "").replace("，", ",").split(","):
        part = part.strip().lstrip("@")
        if not part:
            continue
        out.append(int(part) if part.isdigit() else part)
    return out or [_DEFAULT_BOT]


def _same_hour(ts1: float, ts2: float) -> bool:
    """两个时间戳是否落在同一个整点时段（时段按小时轮换）。"""
    a, b = time.localtime(ts1), time.localtime(ts2)
    return a.tm_year == b.tm_year and a.tm_yday == b.tm_yday and a.tm_hour == b.tm_hour


def remaining(ctx: object) -> int | None:
    """本时段剩余「游戏」掉落数；没查过 / 数据非法 / 结果过期 → None。

    跨整点也返回 None：时段按小时轮换，旧数字必然作废，调用方该先发一次 /info 再决定
    （各游戏的「要不要停」用 paused()，刮奖兜底的「还剩几次可刮」用这个）。
    """
    try:
        value = int(ctx.kv.get(_KV_REMAINING))
    except (TypeError, ValueError):
        return None
    ts = float(ctx.kv.get(_KV_CHECKED_TS, 0) or 0)
    if ts <= 0:
        return None
    if not _same_hour(ts, time.time()):
        return None  # 上次 /info 是上一个整点时段的事，数字作废
    if time.time() - ts > _STALE_AFTER:
        return None
    return value


def paused(ctx: object) -> bool:
    """掉落配额已满且 /info 结果新鲜 → True，各游戏用它拦截新加入。

    未查过/数据非法/结果过期一律 False（照常参与，宁可多打不误停）。
    跨整点（时段刷新）也返回 False：新时段配额必然恢复，不等 /info 回执（v1.23.7）。
    """
    value = remaining(ctx)
    return value is not None and value <= 0


def parse_remaining(text: str) -> int | None:
    """从 /info 回复解析本时段剩余「游戏」掉落配额；无法解析返回 None。"""
    m = _INFO_GAME_RE.search(text)
    if m:
        return int(m.group(1))
    m = _INFO_LEGACY_RE.search(text)
    return int(m.group(1)) if m else None


async def apply_reply(ctx: object, text: str, announce: bool = True) -> bool:
    """解析 /info 回复更新剩余数；暂停状态翻转时通知一次。返回是否解析成功。

    announce=False 用于「守卫没开但有人主动查了 /info」（刮奖兜底要数字）：照常入账，
    只是不播报「已暂停游戏参与」——那时游戏根本没被暂停，报了是假消息。
    """
    remaining = parse_remaining(text)
    if remaining is None:
        return False
    was_paused = bool(ctx.kv.get(_KV_PAUSED, False))
    ctx.kv.set(_KV_REMAINING, remaining)
    ctx.kv.set(_KV_CHECKED_TS, time.time())
    now_paused = remaining <= 0
    if now_paused == was_paused:
        ctx.log.info(
            "掉落守卫：本时段剩余掉落 %d（%s）", remaining, "已满，保持暂停" if now_paused else "未满，照常参与"
        )
        return True
    ctx.kv.set(_KV_PAUSED, now_paused)
    if not announce:
        ctx.log.info("掉落守卫：本时段剩余掉落转为 %d", remaining)
        return True
    msg = (
        "🪙 天空小秘游戏掉落配额已满（本时段游戏剩余 0），十点半/炸金花暂停轮询与新加入"
        "（养马不受影响），时段刷新后自动恢复"
        if now_paused
        else f"🪙 天空小秘游戏掉落剩余 {remaining}，恢复游戏参与"
    )
    ctx.log.info(msg)
    try:
        await ctx.notify(msg, category="掉落守卫")
    except Exception as e:
        ctx.log.warning("掉落守卫通知发送失败（渠道暂不可用）: %r", e)
    return True


def _guard_enabled(ctx: object) -> bool:
    return bool(ctx.config.get("drop_guard_enabled", True))


def _guard_bot_ids(cfg: dict) -> list[int | str]:
    """解析统一的天空小秘 bot 配置；留空回退默认天空小秘。"""
    return _parse_bot_ids(str(cfg.get("bot", "") or ""))


def _guard_interval_minutes(ctx: object) -> int:
    """/info 检查间隔（分钟）：读 drop_guard_interval，clamp 到 [5, 60]，用于生成 cron */N。"""
    try:
        n = int(ctx.config.get("drop_guard_interval", _DEFAULT_INTERVAL_MIN) or _DEFAULT_INTERVAL_MIN)
    except (TypeError, ValueError):
        n = _DEFAULT_INTERVAL_MIN
    return min(60, max(5, n))


async def _send_info(ctx: object) -> bool:
    """私聊天空小秘发一次 /info，回执由 handler 捕获解析进 kv。返回是否发送成功。"""
    bot_ids = _guard_bot_ids(ctx.config)
    target = bot_ids[0]
    if isinstance(target, str) and not target.startswith("@"):
        target = f"@{target}"
    sent = False
    last_err: Exception | None = None
    senders: list[tuple[str, object]] = []
    user_obj = getattr(ctx, "user", None)
    user_client = getattr(user_obj, "raw", None) if user_obj is not None else None
    if user_obj is not None:
        senders.append(("user", user_obj))
    if user_client is not None:
        senders.append(("user.raw", user_client))
    bot_obj = getattr(ctx, "bot", None)
    bot_client = getattr(bot_obj, "raw", None) if bot_obj is not None else None
    if bot_client is not None and bot_client is not user_client:
        senders.append(("bot.raw", bot_client))
    for label, client_obj in senders:
        try:
            send = getattr(client_obj, "send", None)
            if callable(send):
                await send(target, "/info")
                sent = True
                break
            if hasattr(client_obj, "send_message"):
                await client_obj.send_message(target, "/info")  # type: ignore[attr-returns-value]
                sent = True
                break
        except Exception as exc:
            last_err = exc
    if not sent:
        ctx.log.warning(
            "掉落守卫 /info 发送失败: target=%s senders=%s last_err=%r",
            target, [label for label, _ in senders], last_err,
        )
        return False
    ctx.kv.set(_KV_SENT_TS, time.time())
    ctx.log.info("掉落守卫：已私聊 bot %s 发送 /info", target)
    return True


async def _guard_tick(ctx: object) -> None:
    """cron 整点对齐触发：私聊 bot 发一次 /info（回复由 handler 捕获解析）。

    发送频率完全交给 cron 调度器保证，这里不再自算「距上次满间隔」——旧的
    60s tick + 节流模式会因 /info 回复时间戳漂移导致实际间隔不精确（约 11 分钟）、
    每次发送时刻乱跳（v1.24.1 改 cron 整点对齐）。
    """
    if not _guard_enabled(ctx):
        return
    await _send_info(ctx)


async def refresh(ctx: object, min_interval: float = _REFRESH_MIN_INTERVAL) -> bool:
    """按需立刻催一次 /info（刮奖兜底每张刮完刷剩余用），min_interval 内不重发。

    发送本身不受 drop_guard_enabled 影响：守卫关掉只是不再定期查，谁主动要数字就该给。
    """
    if min_interval > 0:
        last = float(ctx.kv.get(_KV_SENT_TS, 0) or 0)
        if time.time() - last < min_interval:
            return False
    return await _send_info(ctx)


def start(ctx: object) -> None:
    """注册 /info 回复捕获 handler + 低频检查调度。"""
    bot_ids = _guard_bot_ids(ctx.config)

    @ctx.on_message()
    async def _on_info_reply(*args: object, **kwargs: object) -> None:
        # 平台 PluginRuntime 把装饰器返回的回调用 lambda: callback(*args, **kwargs) 调用。
        # V2 平台底层是 Telethon：回调签名 = (event)，event.message / event.is_private。
        # Pyrogram 适配期：也兼容 (client, message) 形式。统一提取真实消息对象。
        event: object | None = None
        if args and not kwargs and len(args) == 1:
            event = args[0]
        elif args and len(args) >= 2:
            event = args[1]
        else:
            event = kwargs.get("event") or kwargs.get("message") or kwargs.get("update")
        if event is None:
            ctx.log.warning("掉落守卫收到非预期消息回调，args=%r kwargs=%r", args, kwargs)
            return
        message = getattr(event, "message", None) or event
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "")) if chat is not None else ""
        is_private = getattr(event, "is_private", None)
        if is_private is False:
            return
        if chat_type and chat_type not in ("private", "ChatType.PRIVATE"):
            return
        if is_private is None and chat_type and "PRIVATE" not in chat_type.upper():
            return
        sender = (
            getattr(message, "sender", None)
            or getattr(event, "sender", None)
            or getattr(message, "from_user", None)
        )
        sender_id = getattr(sender, "id", None) or getattr(sender, "user_id", None)
        sender_username = str(
            getattr(sender, "username", "") if sender is not None else ""
        ).lstrip("@").casefold()
        if not any(
            (isinstance(bot_id, int) and sender_id == bot_id)
            or (isinstance(bot_id, str) and sender_username == bot_id.lstrip("@").casefold())
            for bot_id in bot_ids
        ):
            return
        text = (message.text or message.message or "").strip()
        if "银元奖励" in text:  # 掉落消息不是 /info 回复
            return
        if await apply_reply(ctx, text, announce=_guard_enabled(ctx)):
            ctx.log.debug("掉落守卫：捕获 /info 回复 msg=%s", message.id)
        elif _guard_enabled(ctx):
            # 观测点：handler 触发但无配额行——用于区分「filter 没匹配」与「回复格式变了」
            ctx.log.info("掉落守卫：捕获 bot 私聊消息但未匹配配额行: %s", text[:200])

    async def _tick() -> None:
        try:
            await _guard_tick(ctx)
        except Exception as e:
            ctx.log.error("掉落守卫 tick 异常: %r", e)

    minutes = _guard_interval_minutes(ctx)
    ctx.schedule(_tick, "cron", minute=f"*/{minutes}", id="drop_guard_tick")
    ctx.log.info("掉落守卫已启动（cron 每 %d 分整点对齐发 /info，监听 bot=%s）", minutes, bot_ids)


def stop(ctx: object) -> None:
    """schedule 与 handler 由平台在卸载时自动清理，无需额外动作。"""
