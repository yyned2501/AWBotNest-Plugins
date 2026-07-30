# -*- coding: utf-8 -*-
# 天空答题 · 自动触发（每小时智能触发循环）
#
# 由 interval 状态机驱动（每 20s 一个 tick），状态全部存 ctx.kv，幂等、热重载可恢复。
# 每小时窗口（默认第 5 分起）开始循环：私聊 bot 发 /info 校准 → 发「第{n}题{x}」触发 →
# 等答题侧检测到掉落 → 冷却 5-10 分钟 → 下一题，直到达 drops_per_hour 或跨小时。
# 掉落计数由答题 handler (group=5) 写入共享 kv。

from __future__ import annotations

import random
import re
import time
from datetime import datetime

from .models import (
    _DROP_REGEX,
    _FALLBACK_DROPS_PER_HOUR,
    TZ,
    _ensure_hour,
    _parse_bot_ids,
    _parse_groups,
    refresh_stats,
)

# tick 间隔（秒）。状态机靠它推进，不做配置项。
_TICK_SECONDS = 20

# bot /info 回复里的「当前时段剩余掉落: N」——本时段配额 = 已落地 + 剩余
_INFO_REMAINING_RE = re.compile(r"当前时段剩余掉落[:：]\s*(\d+)")


def _apply_info_reply(ctx: object, text: str) -> None:
    """处理 /info 回复：从「当前时段剩余掉落: N」提取本时段配额。

    bot 返回的是「剩余」次数；本时段总配额 = 本小时已落地 + 剩余，
    写入 trig:drops_per_hour 供 tick 的达标判断（drops >= per_hour 即停）。
    未解析到时不改 kv，tick 继续用 _FALLBACK_DROPS_PER_HOUR 兜底。
    """
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
    """私聊 bot 发 /info 校准（不进群，减少对群内干扰）。失败靠超时兜底。"""
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
        ctx.log.warning("私聊 /info 失败: %r（等待超时后自动兜底发触发）", e)


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
    groups = _parse_groups(str(cfg.get("target_groups", "") or ""))
    if not groups:
        return
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    # 每小时掉落配额来自 /info 解析（写入 kv）；未解析到用兜底上限
    per_hour = int(ctx.kv.get("trig:drops_per_hour", 0) or 0) or _FALLBACK_DROPS_PER_HOUR

    # ── IDLE：决定本小时是否开始/继续触发 ──
    if phase == "idle":
        start_min = int(cfg.get("trig_start_min", 5) or 0)
        if datetime.now(TZ).minute < start_min:
            return  # 还没到触发窗口
        if drops >= per_hour:
            return  # 本小时已达标
        if cfg.get("trig_use_info", True):
            await _send_info(ctx)  # 本小时先私聊 bot 发 /info 校准
        else:
            await _send_trigger(ctx, cfg, groups)
        return

    # ── AWAIT_INFO：等 bot 回 /info，超时用本地计数兜底 ──
    if phase == "await_info":
        info_sent = float(ctx.kv.get("trig:info_sent_ts", 0) or 0)
        timeout = float(cfg.get("trig_info_timeout", 60) or 60)
        reply = str(ctx.kv.get("trig:info_reply", "") or "")
        if reply:
            _apply_info_reply(ctx, reply)
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
            # 发出触发后有掉落落地（计数已由答题 handler 写入 drops）
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
                # 连续 info_every 次未掉落 → 私聊 bot 发 /info 检查
                ctx.log.info("连续 %d 次未掉落，私聊 bot 发 /info 检查", failed)
                await _send_info(ctx)
            else:
                await _send_trigger(ctx, cfg, groups)  # 同题重试（n 不变 x 升高）
        return

    # ── COOLDOWN：冷却结束回 idle ──
    if phase == "cooldown":
        if now >= float(ctx.kv.get("trig:cooldown_until", 0) or 0):
            ctx.kv.set("trig:phase", "idle")
        return


def register_info_handler(ctx: object) -> None:
    """/info 回复捕获 handler（group=6）：私聊 bot 时捕获其回复，排除掉落消息。

    /info 走私聊（不进群），所以这里监听 private 聊天里 bot 发来的文本；
    仅在 await_info 阶段记录，其他时候的 bot 私聊消息一律忽略。
    """
    bot_ids = _parse_bot_ids(str(ctx.config.get("bot", "") or ""))
    info_filter = ctx.filters.private & ctx.filters.user(bot_ids) & ctx.filters.text

    @ctx.on_message(info_filter, group=6)
    async def _on_info_reply(client: object, message: object) -> None:
        if (ctx.kv.get("trig:phase") or "") != "await_info":
            return
        text = (message.text or "").strip()
        if re.search(_DROP_REGEX, text):
            return  # 是掉落答题消息，交给答题 handler
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
    ctx.log.info("触发状态机已启动（每 %ds 一个 tick）", _TICK_SECONDS)
