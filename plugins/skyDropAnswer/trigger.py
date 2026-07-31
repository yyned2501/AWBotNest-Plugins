# -*- coding: utf-8 -*-
# 天空答题 · 自动触发（低频调度 + 同题整轮触发 + 多文案顺序/随机切换）
#
# 低频 tick 只负责判断是否该启动新一轮；同一题的多次尝试由一个 asyncio
# 轮次任务连续调度。每次尝试随机选「模板/背诗/唱歌」三类之一：
#   - 模板：第{n}题{x}（带变量）
#   - 背诗/唱歌：按配置行顺序逐行发，同行按标点拆成多条依次发；
#     中途检测到掉落则跳过本行剩余段，下次轮到该类别从下一行继续。

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


# 用于按标点拆句的正则（中英文常见标点）
_PUNCT_SPLIT_RE = re.compile(r"[，。！？；：、,.!?;:]+")


def _split_by_punct(text: str) -> list[str]:
    """按标点符号把一行拆成多条消息段；无标点则原样返回单段。"""
    parts = [s.strip() for s in _PUNCT_SPLIT_RE.split(text) if s.strip()]
    return parts if parts else [text.strip()] if text.strip() else []


def _pick_trigger_kind(cfg: dict) -> str:
    """随机选一种文案类型（每轮只选一次，轮内不切换）。

    可用类型 = 用户勾选的 trig_kinds ∩ 有内容的文案池；
    背诗/唱歌需对应池非空才生效；若勾选为空或全部池空，回退到模板，
    保证 random.choice 不会拿到空列表。
    """
    selected = set(cfg.get("trig_kinds", ["template", "poem", "song"]) or [])
    choices: list[str] = []
    if "template" in selected:
        choices.append("template")
    if "poem" in selected and str(cfg.get("trig_msg_poems", "") or "").strip():
        choices.append("poem")
    if "song" in selected and str(cfg.get("trig_msg_songs", "") or "").strip():
        choices.append("song")
    if not choices:
        choices = ["template"]
    return random.choice(choices)


def _pick_trigger_segments(ctx: object, cfg: dict, kind: str, n: int, attempt: int) -> list[str]:
    """按指定文案类型返回本次要发的消息段列表（可能多条）。

    模板：第{n}题{x}（单段）。
    背诗/唱歌：按配置行顺序取当前行，按标点拆成多段；
    行号存 kv（trig:poem_idx / trig:song_idx），发完推进，循环使用。
    """
    if kind == "poem":
        poems_raw = str(cfg.get("trig_msg_poems", "") or "").strip()
        poems = [ln.strip() for ln in poems_raw.split("\n") if ln.strip()]
        idx = int(ctx.kv.get("trig:poem_idx", 0) or 0) % len(poems)
        ctx.kv.set("trig:poem_idx", idx + 1)
        line = poems[idx]
        ctx.log.info("背诗第 %d 行: %s", idx + 1, line)
        return _split_by_punct(line)
    if kind == "song":
        songs_raw = str(cfg.get("trig_msg_songs", "") or "").strip()
        songs = [ln.strip() for ln in songs_raw.split("\n") if ln.strip()]
        idx = int(ctx.kv.get("trig:song_idx", 0) or 0) % len(songs)
        ctx.kv.set("trig:song_idx", idx + 1)
        line = songs[idx]
        ctx.log.info("唱歌第 %d 行: %s", idx + 1, line)
        return _split_by_punct(line)

    # 模板消息：第{n}题{x}
    template = str(cfg.get("trig_message_template", "") or "第{n}题{x}")
    try:
        msg = template.format(n=n, x=attempt)
    except (KeyError, IndexError, ValueError):
        msg = f"第{n}题{attempt}"
    return [msg]


async def _send_segments(ctx: object, groups: list[int], segments: list[str], baseline: int) -> bool:
    """逐段发送消息；每段之间检查掉落，检测到则跳过本行剩余段。

    返回是否至少成功发送了一段到一个群。
    """
    sent_any = False
    for i, seg in enumerate(segments):
        # 发送前检查：若已有新掉落，跳过本行剩余段
        if int(ctx.kv.get("trig:drops_this_hour", 0) or 0) > baseline:
            ctx.log.info("第 %d/%d 段发送前检测到掉落，跳过剩余 %d 段", i + 1, len(segments), len(segments) - i)
            break
        ok = False
        for gid in groups:
            try:
                await ctx.user.send(gid, seg)
                ok = True
            except Exception as e:
                ctx.log.warning("向群 %s 发送失败: %r", gid, e)
        if not ok:
            ctx.log.warning("段 %d/%d 全部群发送失败: %s", i + 1, len(segments), seg)
            continue
        sent_any = True
        now = time.time()
        ctx.kv.set("trig:trigger_sent_ts", now)
        ctx.kv.set("trig:last_trigger_ts", now)
        ctx.kv.set("trig:trigger_count", int(ctx.kv.get("trig:trigger_count", 0) or 0) + 1)
        ctx.kv.set("trig:trigger_today", int(ctx.kv.get("trig:trigger_today", 0) or 0) + 1)
        ctx.kv.set("trig:trigger_this_hour", int(ctx.kv.get("trig:trigger_this_hour", 0) or 0) + 1)
        ctx.log.info("触发消息已发送 [%d/%d]: %s", i + 1, len(segments), seg)
        refresh_stats(ctx)
        # 段间短停顿（模拟打字节奏），同时检测掉落
        if i < len(segments) - 1:
            await asyncio.sleep(random.uniform(1, 3))
    return sent_any


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
    """在一次任务中完成同一题的全部尝试，掉落后立即停止。

    每次尝试随机选「模板/背诗/唱歌」之一；背诗/唱歌按行顺序取，
    同行按标点拆成多段依次发，中途掉落则跳过本行剩余段。
    """
    baseline = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    question = int(ctx.kv.get("trig:question", 1) or 1)
    max_attempts = int(cfg.get("trig_max_attempts", 10) or 10)
    # 发送前随机延迟模拟真人；同题重试间隔则更短，避免机械刷屏。
    first_delay_max = float(cfg.get("trig_jitter_max", 30) or 0)
    retry_delay_min, retry_delay_max = 5.0, 15.0
    # 每轮随机选一种文案类型，轮内不切换
    kind = _pick_trigger_kind(cfg)
    ctx.log.info("本轮文案类型: %s", kind)
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
            n = max(question, int(ctx.kv.get("trig:drops_this_hour", 0) or 0) + 1)
            segments = _pick_trigger_segments(ctx, cfg, kind, n, attempt)
            sent = await _send_segments(ctx, groups, segments, baseline)
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
