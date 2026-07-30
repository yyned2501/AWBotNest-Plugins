# -*- coding: utf-8 -*-
# 天空答题 · 自动触发（每小时智能触发循环）
#
# 由 interval 状态机驱动（每 20s 一个 tick），状态全部存 ctx.kv，幂等、热重载可恢复。
# 每小时窗口（默认第 5 分起）开始循环：发 /info 校准 → 发「第{n}题{x}」触发 →
# 等答题侧检测到掉落 → 冷却 5-10 分钟 → 下一题，直到达 drops_per_hour 或跨小时。
# 掉落计数由 group=4 的统计 handler 写入共享 kv（合并 skyDropTrigger 的核心收益）。

from __future__ import annotations

import random
import re
import time
from datetime import datetime

from .models import _DROP_REGEX, BOT_ID, TZ, _fmt_ts, _parse_groups, _reply_to_own_filter

# tick 间隔（秒）。状态机靠它推进，不做配置项。
_TICK_SECONDS = 20


def _get_hour_key() -> str:
    """当前小时标识 YYYY-MM-DD-HH（东八区），用于检测跨小时翻转。"""
    return datetime.now(TZ).strftime("%Y-%m-%d-%H")


def _ensure_hour(ctx: object) -> None:
    """跨小时翻转时重置本小时状态（tick 与统计 handler 共用，幂等）。"""
    hour_key = _get_hour_key()
    if ctx.kv.get("trig:hour_key") != hour_key:
        ctx.kv.set("trig:hour_key", hour_key)
        ctx.kv.set("trig:drops_this_hour", 0)
        ctx.kv.set("trig:question", 1)
        ctx.kv.set("trig:attempt", 1)
        ctx.kv.set("trig:phase", "idle")
        ctx.kv.set("trig:info_reply", "")
        ctx.log.info("触发循环：跨小时重置 → %s", hour_key)


def refresh_stats(ctx: object) -> None:
    """把触发统计写回 trig_stats 配置项，供面板 info 字段展示（仅在状态变化时调用）。"""
    trig = int(ctx.kv.get("trig:trigger_count", 0) or 0)
    drop = int(ctx.kv.get("trig:drop_count", 0) or 0)
    drops_hour = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    phase = ctx.kv.get("trig:phase") or "idle"
    last_trig = _fmt_ts(ctx.kv.get("trig:last_trigger_ts", 0))
    last_drop = _fmt_ts(ctx.kv.get("trig:last_drop_ts", 0))
    ctx.update_config(
        {
            "trig_stats": (
                f"阶段: {phase} · 本小时掉落 {drops_hour} 次\n"
                f"累计触发 {trig} 次 · 累计掉落 {drop} 次\n"
                f"最近触发 {last_trig} · 最近掉落 {last_drop}"
            )
        }
    )


async def _send_info(ctx: object, primary_group: int) -> None:
    """向主群发 /info 校准。先把状态切到 await_info，发送失败也靠超时兜底。"""
    ctx.kv.set("trig:info_reply", "")
    ctx.kv.set("trig:info_sent_ts", time.time())
    ctx.kv.set("trig:phase", "await_info")
    try:
        await ctx.user.send(primary_group, "/info")
        ctx.log.info("已发送 /info 到主群 %s", primary_group)
    except Exception as e:
        ctx.log.warning("发送 /info 失败: %r（等待超时后自动兜底发触发）", e)


async def _send_trigger(ctx: object, cfg: dict, groups: list[int]) -> None:
    """发送「第{n}题{x}」触发消息到所有目标群，切到 await_drop。

    n 取 max(当前题号, 本小时已掉落数+1)，与真实掉落计数对齐（含他人触发的掉落）。
    """
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    question = int(ctx.kv.get("trig:question", 1) or 1)
    attempt = int(ctx.kv.get("trig:attempt", 1) or 1)
    n = max(question, drops + 1)
    x = attempt
    template = str(cfg.get("trig_message_template", "") or "第{n}题{x}")
    try:
        msg = template.format(n=n, x=x)
    except (KeyError, IndexError, ValueError):
        msg = f"第{n}题{x}"
    sent = False
    for gid in groups:
        try:
            await ctx.user.send(gid, msg)
            sent = True
        except Exception as e:
            ctx.log.warning("向群 %s 发送触发消息失败: %r", gid, e)
    if not sent:
        ctx.log.warning("触发消息全部发送失败，回到 idle 下轮重试")
        ctx.kv.set("trig:phase", "idle")
        return
    now = time.time()
    ctx.kv.set("trig:trigger_sent_ts", now)
    ctx.kv.set("trig:last_trigger_ts", now)
    ctx.kv.set("trig:trigger_count", int(ctx.kv.get("trig:trigger_count", 0) or 0) + 1)
    ctx.kv.set("trig:phase", "await_drop")
    ctx.log.info("触发消息已发送: %s（n=%d x=%d）", msg, n, x)
    refresh_stats(ctx)


def _enter_cooldown(ctx: object, cfg: dict, now: float) -> None:
    """进入冷却：随机等待 [cooldown_min, cooldown_max] 分钟后回 idle。"""
    c_min = float(cfg.get("trig_cooldown_min", 5) or 5)
    c_max = float(cfg.get("trig_cooldown_max", 10) or 10)
    if c_max < c_min:
        c_max = c_min
    wait = random.uniform(c_min, c_max) * 60
    ctx.kv.set("trig:cooldown_until", now + wait)
    ctx.kv.set("trig:phase", "cooldown")
    ctx.log.info("进入冷却 %.0f 秒", wait)


async def _trigger_tick(ctx: object) -> None:
    """状态机主 tick：读 kv 状态 + 当前时间，推进一步。"""
    cfg = ctx.config
    if not cfg.get("trig_enabled", False):
        if (ctx.kv.get("trig:phase") or "idle") != "idle":
            ctx.kv.set("trig:phase", "idle")
        return

    _ensure_hour(ctx)
    now = time.time()
    phase = ctx.kv.get("trig:phase") or "idle"
    groups = _parse_groups(str(cfg.get("trig_target_groups", "") or ""))
    if not groups:
        return
    primary = groups[0]
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    per_hour = int(cfg.get("trig_drops_per_hour", 3) or 3)

    # ── IDLE：决定本小时是否开始/继续触发 ──
    if phase == "idle":
        start_min = int(cfg.get("trig_start_min", 5) or 0)
        if datetime.now(TZ).minute < start_min:
            return  # 还没到触发窗口
        if drops >= per_hour:
            return  # 本小时已达标
        if cfg.get("trig_use_info", True):
            await _send_info(ctx, primary)  # 本小时先 /info 校准
        else:
            await _send_trigger(ctx, cfg, groups)
        return

    # ── AWAIT_INFO：等 bot 回 /info，超时用本地计数兜底 ──
    if phase == "await_info":
        info_sent = float(ctx.kv.get("trig:info_sent_ts", 0) or 0)
        timeout = float(cfg.get("trig_info_timeout", 60) or 60)
        reply = str(ctx.kv.get("trig:info_reply", "") or "")
        if reply:
            ctx.log.info("/info 回复（仅校准记录，不覆写本地计数）: %s", reply[:200])
            ctx.kv.set("trig:info_reply", "")
            await _send_trigger(ctx, cfg, groups)
        elif info_sent and now - info_sent > timeout:
            ctx.log.info("/info 等待超时，用本地计数兜底（本小时已掉 %d 次）", drops)
            await _send_trigger(ctx, cfg, groups)
        return

    # ── AWAIT_DROP：等触发后的掉落，超时重试 / 定期检查 ──
    if phase == "await_drop":
        trig_sent = float(ctx.kv.get("trig:trigger_sent_ts", 0) or 0)
        last_drop = float(ctx.kv.get("trig:last_drop_ts", 0) or 0)
        drop_timeout = float(cfg.get("trig_drop_timeout", 120) or 120)
        max_attempts = int(cfg.get("trig_max_attempts", 10) or 10)
        info_every = int(cfg.get("trig_info_every", 5) or 0)
        attempt = int(ctx.kv.get("trig:attempt", 1) or 1)

        if last_drop > trig_sent:
            # 发出触发后有掉落落地（计数已由统计 handler 写入 drops）
            question = int(ctx.kv.get("trig:question", 1) or 1)
            ctx.log.info("触发成功（第%d题第%d次），本小时累计掉落 %d 次", question, attempt, drops)
            ctx.kv.set("trig:question", question + 1)
            ctx.kv.set("trig:attempt", 1)
            if drops >= per_hour:
                ctx.kv.set("trig:phase", "idle")
                ctx.log.info("本小时已达 %d 次上限，停止触发", per_hour)
            else:
                _enter_cooldown(ctx, cfg, now)
            refresh_stats(ctx)
            return

        if trig_sent and now - trig_sent > drop_timeout:
            # 超时未掉落：attempt 为本题已发送次数
            failed = attempt
            ctx.kv.set("trig:attempt", attempt + 1)
            if attempt >= max_attempts:
                question = int(ctx.kv.get("trig:question", 1) or 1)
                ctx.log.warning("第%d题尝试 %d 次仍未掉落，放弃本题", question, attempt)
                ctx.kv.set("trig:question", question + 1)
                ctx.kv.set("trig:attempt", 1)
                _enter_cooldown(ctx, cfg, now)
            elif info_every > 0 and failed % info_every == 0 and cfg.get("trig_use_info", True):
                # 连续 info_every 次未掉落 → 发 /info 检查
                ctx.log.info("连续 %d 次未掉落，发 /info 检查", failed)
                await _send_info(ctx, primary)
            else:
                await _send_trigger(ctx, cfg, groups)  # 同题重试（n 不变 x 升高）
        return

    # ── COOLDOWN：冷却结束回 idle ──
    if phase == "cooldown":
        if now >= float(ctx.kv.get("trig:cooldown_until", 0) or 0):
            ctx.kv.set("trig:phase", "idle")
        return


def register_stats_handler(ctx: object) -> None:
    """统计 handler（group=4，宽匹配：统计所有掉落，不要求回复自己）。

    掉落计数的唯一写入点：把 last_drop_ts 与本小时掉落数写进共享 kv，
    供触发状态机读取（合并的核心协同点）。
    """
    stats_filter = ctx.filters.group & ctx.filters.user(BOT_ID) & ctx.filters.text & ctx.filters.regex(_DROP_REGEX)

    @ctx.on_message(stats_filter, group=4)
    async def _on_drop(client: object, message: object) -> None:
        _ensure_hour(ctx)
        drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0) + 1
        ctx.kv.set("trig:drops_this_hour", drops)
        ctx.kv.set("trig:last_drop_ts", time.time())
        total = int(ctx.kv.get("trig:drop_count", 0) or 0) + 1
        ctx.kv.set("trig:drop_count", total)
        ctx.log.info("检测到天空掉落（本小时第 %d 次 · 累计 %d 次）msg=%s", drops, total, getattr(message, "id", "?"))
        refresh_stats(ctx)


def register_info_handler(ctx: object) -> None:
    """/info 回复捕获 handler（group=6）：等待 /info 时捕获 bot 回复，排除掉落消息。"""
    info_filter = (
        ctx.filters.group & ctx.filters.user(BOT_ID) & ctx.filters.text & ctx.filters.create(_reply_to_own_filter)
    )

    @ctx.on_message(info_filter, group=6)
    async def _on_info_reply(client: object, message: object) -> None:
        if (ctx.kv.get("trig:phase") or "") != "await_info":
            return
        text = (message.text or "").strip()
        if re.search(_DROP_REGEX, text):
            return  # 是掉落答题消息，交给答题/统计 handler
        ctx.kv.set("trig:info_reply", text)
        ctx.log.info("捕获 /info 回复: %s", text[:200])


def start_trigger(ctx: object) -> None:
    """注册 interval 状态机 tick。"""

    async def _tick() -> None:
        try:
            await _trigger_tick(ctx)
        except Exception as e:  # 单个 tick 异常不应中断整个调度
            ctx.log.error("触发 tick 异常: %r", e)

    ctx.schedule(_tick, "interval", seconds=_TICK_SECONDS, id="trigger_tick")
