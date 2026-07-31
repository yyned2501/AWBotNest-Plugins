# -*- coding: utf-8 -*-
# 天空答题 · 自动触发（低频调度 + 同题整轮触发）
#
# 低频 tick 只负责判断是否该启动新一轮；同一题的多次尝试由一个 asyncio
# 轮次任务连续调度，尝试之间短暂随机等待，检测到掉落后立即停止后续尝试。

from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime

from .models import (
    _DROP_REGEX,
    _FALLBACK_DROPS_PER_HOUR,
    TZ,
    _ensure_day,
    _ensure_hour,
    _parse_bot_ids,
    _parse_groups,
    refresh_stats,
)

# 仅用于检查开启时段、配额和 /info 状态；题内尝试不依赖此轮询频率。
_TICK_SECONDS = 60
_INFO_REMAINING_RE = re.compile(r"当前时段剩余掉落[:：]\s*(\d+)")

# 当前插件实例的整轮任务；热重载/卸载时主动取消，避免旧任务继续发消息。
_round_task: asyncio.Task[None] | None = None


def _apply_info_reply(ctx: object, text: str) -> None:
    """处理 /info 回复并校准本时段总配额。"""
    m = _INFO_REMAINING_RE.search(text)
    if not m:
        ctx.log.warning("/info 回复未解析出「当前时段剩余掉落」: %s", text[:200])
        return
    remaining = int(m.group(1))
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    per_hour = drops + remaining
    ctx.kv.set("trig:drops_per_hour", per_hour)
    ctx.log.info("/info 校准：剩余 %d + 已掉 %d = 本时段配额 %d", remaining, drops, per_hour)


async def _send_info(ctx: object) -> None:
    """私聊 bot 发 /info 校准，不在目标群发送。"""
    ctx.kv.set("trig:info_reply", "")
    ctx.kv.set("trig:info_sent_ts", time.time())
    ctx.kv.set("trig:phase", "await_info")
    bot_ids = _parse_bot_ids(str(ctx.config.get("bot", "") or ""))
    target = bot_ids[0]
    if isinstance(target, str) and not target.startswith("@"):
        target = f"@{target}"
    try:
        await ctx.user.send(target, "/info")
        ctx.log.info("已私聊 bot %s 发送 /info", target)
    except Exception as e:
        ctx.log.warning("私聊 /info 失败: %r（低频 tick 超时后自动继续）", e)


async def _send_trigger(ctx: object, cfg: dict, groups: list[int]) -> bool:
    """发送一次触发消息（随机选模板/背诗/唱歌）；返回是否至少成功发送到一个群。"""
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    question = int(ctx.kv.get("trig:question", 1) or 1)
    attempt = int(ctx.kv.get("trig:attempt", 1) or 1)
    n = max(question, drops + 1)
    msg = _pick_trigger_message(cfg, n, attempt)
    sent = False
    for gid in groups:
        try:
            await ctx.user.send(gid, msg)
            sent = True
        except Exception as e:
            ctx.log.warning("向群 %s 发送触发消息失败: %r", gid, e)
    if not sent:
        ctx.log.warning("触发消息全部发送失败")
        return False
    now = time.time()
    ctx.kv.set("trig:trigger_sent_ts", now)
    ctx.kv.set("trig:last_trigger_ts", now)
    ctx.kv.set("trig:trigger_count", int(ctx.kv.get("trig:trigger_count", 0) or 0) + 1)
    ctx.kv.set("trig:trigger_today", int(ctx.kv.get("trig:trigger_today", 0) or 0) + 1)
    ctx.kv.set("trig:trigger_this_hour", int(ctx.kv.get("trig:trigger_this_hour", 0) or 0) + 1)
    ctx.log.info("触发消息已发送: %s（n=%d x=%d）", msg, n, attempt)
    refresh_stats(ctx)
    return True


def _pick_trigger_message(cfg: dict, n: int, attempt: int) -> str:
    """随机从模板/背诗/唱歌中选一种消息，避免总发「第n题x」被系统检测。"""
    choices = ["template"]
    poems_raw = str(cfg.get("trig_msg_poems", "") or "").strip()
    songs_raw = str(cfg.get("trig_msg_songs", "") or "").strip()
    poems = [ln.strip() for ln in poems_raw.split("\n") if ln.strip()] if poems_raw else []
    songs = [ln.strip() for ln in songs_raw.split("\n") if ln.strip()] if songs_raw else []
    if poems:
        choices.append("poem")
    if songs:
        choices.append("song")
    kind = random.choice(choices)
    if kind == "poem":
        return random.choice(poems)
    if kind == "song":
        return random.choice(songs)
    # 模板消息：第{n}题{x}
    template = str(cfg.get("trig_message_template", "") or "第{n}题{x}")
    try:
        return template.format(n=n, x=attempt)
    except (KeyError, IndexError, ValueError):
        return f"第{n}题{attempt}"


def _in_active_window(cfg: dict) -> bool:
    """当前小时是否落在开启时段 [start, end] 内（含端点，支持跨午夜如 22→6）。"""
    start = int(cfg.get("trig_active_start", 8) or 0)
    end = int(cfg.get("trig_active_end", 23) or 0)
    hour = datetime.now(TZ).hour
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _set_next_round(ctx: object, cfg: dict, now: float) -> None:
    """整轮结束后按配置间隔安排下一题。"""
    interval = float(cfg.get("trig_interval", 5) or 5)
    ctx.kv.set("trig:next_round_at", now + interval * 60)
    ctx.kv.set("trig:phase", "scheduled")
    ctx.log.info("已定时下一次触发：%.0f 分钟后", interval)


async def _wait_for_drop(ctx: object, baseline: int, seconds: float) -> bool:
    """在题内等待期间每秒检查是否已有新掉落，以便立刻停止后续尝试。"""
    deadline = time.monotonic() + seconds
    while True:
        if int(ctx.kv.get("trig:drops_this_hour", 0) or 0) > baseline:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(1, remaining))


async def _question_round(ctx: object, cfg: dict, groups: list[int]) -> None:
    """在一次任务中完成同一题的全部尝试，掉落后立即停止。"""
    baseline = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    question = int(ctx.kv.get("trig:question", 1) or 1)
    max_attempts = int(cfg.get("trig_max_attempts", 10) or 10)
    # 发送前随机延迟模拟真人；同题重试间隔则更短，避免机械刷屏。
    first_delay_max = float(cfg.get("trig_jitter_max", 30) or 0)
    retry_delay_min, retry_delay_max = 5.0, 15.0
    ctx.kv.set("trig:phase", "round")
    ctx.kv.set("trig:attempt", 1)
    try:
        for attempt in range(1, max_attempts + 1):
            if int(ctx.kv.get("trig:drops_this_hour", 0) or 0) > baseline:
                break
            ctx.kv.set("trig:attempt", attempt)
            delay_max = first_delay_max if attempt == 1 else retry_delay_max
            if delay_max > 0:
                delay = random.uniform(0, delay_max) if attempt == 1 else random.uniform(retry_delay_min, delay_max)
                ctx.log.info("第%d题第%d次，拟人延迟 %.0f 秒后发送", question, attempt, delay)
                if await _wait_for_drop(ctx, baseline, delay):
                    break
            sent = await _send_trigger(ctx, cfg, groups)
            if not sent:
                break
            ctx.kv.set("trig:phase", "round")
            if attempt < max_attempts and await _wait_for_drop(ctx, baseline, random.uniform(5, 15)):
                break
        drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
        if drops > baseline:
            ctx.log.info("整轮触发成功（第%d题），本时段累计掉落 %d 次", question, drops)
        else:
            ctx.log.warning("第%d题整轮尝试 %d 次仍未掉落", question, max_attempts)
        ctx.kv.set("trig:question", question + 1)
        ctx.kv.set("trig:attempt", 1)
        per_hour = int(ctx.kv.get("trig:drops_per_hour", 0) or 0) or _FALLBACK_DROPS_PER_HOUR
        if drops >= per_hour:
            ctx.kv.set("trig:phase", "idle")
            ctx.log.info("本时段已达 %d 次上限，停止触发", per_hour)
        else:
            _set_next_round(ctx, cfg, time.time())
        refresh_stats(ctx)
    except asyncio.CancelledError:
        ctx.kv.set("trig:phase", "idle")
        raise


def _round_running() -> bool:
    """判断整轮任务是否仍在运行。"""
    return _round_task is not None and not _round_task.done()


async def _trigger_tick(ctx: object) -> None:
    """低频调度 tick：只决定是否启动一轮，不处理题内每次尝试。"""
    global _round_task
    cfg = ctx.config
    if not cfg.get("trig_enabled", False):
        if (ctx.kv.get("trig:phase") or "idle") != "idle":
            ctx.kv.set("trig:phase", "idle")
        return
    _ensure_day(ctx)
    _ensure_hour(ctx)
    if _round_running():
        return
    phase = ctx.kv.get("trig:phase") or "idle"
    groups = _parse_groups(str(cfg.get("target_groups", "") or ""))
    if not groups or not _in_active_window(cfg):
        return
    now = time.time()
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    per_hour = int(ctx.kv.get("trig:drops_per_hour", 0) or 0) or _FALLBACK_DROPS_PER_HOUR
    if drops >= per_hour:
        ctx.kv.set("trig:phase", "idle")
        return
    if phase == "scheduled" and now < float(ctx.kv.get("trig:next_round_at", 0) or 0):
        return
    start_min = int(cfg.get("trig_start_min", 5) or 0)
    if phase == "idle" and datetime.now(TZ).minute < start_min:
        return
    if cfg.get("trig_use_info", True) and phase in ("idle", "scheduled"):
        await _send_info(ctx)
        return
    if phase == "await_info":
        reply = str(ctx.kv.get("trig:info_reply", "") or "")
        sent_ts = float(ctx.kv.get("trig:info_sent_ts", 0) or 0)
        timeout = float(cfg.get("trig_info_timeout", 60) or 60)
        if reply or (sent_ts and now - sent_ts > timeout):
            if reply:
                _apply_info_reply(ctx, reply)
                ctx.kv.set("trig:info_reply", "")
            _round_task = asyncio.create_task(_question_round(ctx, cfg, groups))
        return
    _round_task = asyncio.create_task(_question_round(ctx, cfg, groups))


def register_info_handler(ctx: object) -> None:
    """捕获私聊 bot 的 /info 回复，排除掉落消息。"""
    bot_ids = _parse_bot_ids(str(ctx.config.get("bot", "") or ""))
    info_filter = ctx.filters.private & ctx.filters.user(bot_ids) & ctx.filters.text

    @ctx.on_message(info_filter, group=6)
    async def _on_info_reply(client: object, message: object) -> None:
        if (ctx.kv.get("trig:phase") or "") != "await_info":
            return
        text = (message.text or "").strip()
        if re.search(_DROP_REGEX, text):
            return
        ctx.kv.set("trig:info_reply", text)
        ctx.log.info("捕获 /info 回复: %s", text[:200])


def start_trigger(ctx: object) -> None:
    """注册低频触发调度 tick。"""
    global _round_task
    _round_task = None

    async def _tick() -> None:
        try:
            await _trigger_tick(ctx)
        except Exception as e:
            ctx.log.error("触发 tick 异常: %r", e)

    ctx.schedule(_tick, "interval", seconds=_TICK_SECONDS, id="trigger_tick")
    ctx.log.info("触发状态机已启动（低频调度，每 %ds 检查一次）", _TICK_SECONDS)


def stop_trigger(ctx: object) -> None:
    """卸载插件时取消正在运行的整轮任务。"""
    global _round_task
    if _round_task and not _round_task.done():
        _round_task.cancel()
    _round_task = None
