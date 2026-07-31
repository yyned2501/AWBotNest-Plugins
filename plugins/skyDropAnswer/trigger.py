# -*- coding: utf-8 -*-
# 天空答题 · 自动触发（开启时段内的定时触发循环）
#
# 由 interval 状态机驱动（每 20s 一个 tick），状态全部存 ctx.kv，幂等、热重载可恢复。
# 仅在「开启时段」内工作：私聊 bot 发 /info 校准 → 决定触发后拟人随机延迟一小段 →
# 发「第{n}题{x}」触发 → 等答题侧检测到掉落 → 掉落后定时 trig_interval 分钟后触发下一题，
# 直到达本时段配额（/info 剩余掉落）或跨小时。掉落计数由答题 handler (group=5) 写入共享 kv。

from __future__ import annotations

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
    ctx.kv.set("trig:trigger_today", int(ctx.kv.get("trig:trigger_today", 0) or 0) + 1)
    ctx.kv.set("trig:trigger_this_hour", int(ctx.kv.get("trig:trigger_this_hour", 0) or 0) + 1)
    ctx.kv.set("trig:phase", "await_drop")
    ctx.log.info("触发消息已发送: %s（n=%d x=%d）", msg, n, x)
    refresh_stats(ctx)


def _in_active_window(cfg: dict) -> bool:
    """当前小时是否落在开启时段 [start, end] 内（含端点，支持跨午夜如 22→6）。"""
    start = int(cfg.get("trig_active_start", 8) or 0)
    end = int(cfg.get("trig_active_end", 23) or 0)
    hour = datetime.now(TZ).hour
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end  # 跨午夜


def _arm_send(ctx: object, cfg: dict, now: float) -> None:
    """决定触发后进入「待发」态：拟人随机延迟 0~trig_jitter_max 秒再由 ARMED 阶段真发。

    不在决定时立刻发群消息，避免整点/固定节拍机械刷屏，模拟真人发送时机。
    """
    jitter_max = float(cfg.get("trig_jitter_max", 30) or 0)
    delay = random.uniform(0, jitter_max) if jitter_max > 0 else 0.0
    ctx.kv.set("trig:send_at", now + delay)
    ctx.kv.set("trig:phase", "armed")
    ctx.log.info("决定触发，拟人延迟 %.0f 秒后发送", delay)


def _schedule_next(ctx: object, cfg: dict, now: float) -> None:
    """定时下一次触发：固定 trig_interval 分钟后由 tick 触发下一题（替代随机冷却等待）。"""
    interval = float(cfg.get("trig_interval", 5) or 5)
    wait = interval * 60
    ctx.kv.set("trig:next_trigger_at", now + wait)
    ctx.kv.set("trig:phase", "scheduled")
    ctx.log.info("已定时下一次触发：%.0f 分钟后", wait / 60)


async def _trigger_tick(ctx: object) -> None:
    """状态机主 tick：读 kv 状态 + 当前时间，推进一步。"""
    cfg = ctx.config
    if not cfg.get("trig_enabled", False):
        if (ctx.kv.get("trig:phase") or "idle") != "idle":
            ctx.kv.set("trig:phase", "idle")
        return

    _ensure_day(ctx)
    _ensure_hour(ctx)
    now = time.time()
    phase = ctx.kv.get("trig:phase") or "idle"
    groups = _parse_groups(str(cfg.get("target_groups", "") or ""))
    if not groups:
        return
    drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0)
    # 每小时掉落配额来自 /info 解析（写入 kv）；未解析到用兜底上限
    per_hour = int(ctx.kv.get("trig:drops_per_hour", 0) or 0) or _FALLBACK_DROPS_PER_HOUR

    # 开启时段门控：不在时段内不发起新触发（已在途的 await_* 让它走完）
    if phase in ("idle", "scheduled") and not _in_active_window(cfg):
        return

    # ── ARMED：已决定触发，拟人延迟到点后真发 ──
    if phase == "armed":
        if now < float(ctx.kv.get("trig:send_at", 0) or 0):
            return  # 还在拟人延迟里
        await _send_trigger(ctx, cfg, groups)
        return

    # ── IDLE：决定本小时是否开始/继续触发 ──
    if phase == "idle":
        start_min = int(cfg.get("trig_start_min", 5) or 0)
        if datetime.now(TZ).minute < start_min:
            return  # 还没到触发窗口
        if drops >= per_hour:
            return  # 本小时已达标
        if cfg.get("trig_use_info", True):
            await _send_info(ctx)  # 先私聊 bot 发 /info 校准
        else:
            _arm_send(ctx, cfg, now)  # 决定触发（拟人延迟后真发）
        return

    # ── SCHEDULED：上一次触发完成后定时等待，到点触发下一题 ──
    if phase == "scheduled":
        if now < float(ctx.kv.get("trig:next_trigger_at", 0) or 0):
            return  # 还没到定时时间
        if drops >= per_hour:
            ctx.kv.set("trig:phase", "idle")  # 本时段已达标，回 idle
            return
        if cfg.get("trig_use_info", True):
            await _send_info(ctx)  # 下一题前先 /info 刷新剩余掉落
        else:
            _arm_send(ctx, cfg, now)  # 决定触发（拟人延迟后真发）
        return

    # ── AWAIT_INFO：等 bot 回 /info，超时用本地计数兜底 ──
    if phase == "await_info":
        info_sent = float(ctx.kv.get("trig:info_sent_ts", 0) or 0)
        timeout = float(cfg.get("trig_info_timeout", 60) or 60)
        reply = str(ctx.kv.get("trig:info_reply", "") or "")
        if reply:
            _apply_info_reply(ctx, reply)
            ctx.kv.set("trig:info_reply", "")
            _arm_send(ctx, cfg, now)  # 校准后决定触发（拟人延迟后真发）
        elif info_sent and now - info_sent > timeout:
            ctx.log.info("/info 等待超时，用本地计数兜底（本小时已掉 %d 次）", drops)
            _arm_send(ctx, cfg, now)  # 兜底决定触发（拟人延迟后真发）
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
                ctx.log.info("本时段已达 %d 次上限，停止触发", per_hour)
            else:
                _schedule_next(ctx, cfg, now)  # 定时触发下一题（不再随机冷却）
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
                _schedule_next(ctx, cfg, now)  # 放弃本题后也定时触发下一题
            elif info_every > 0 and failed % info_every == 0 and cfg.get("trig_use_info", True):
                # 连续 info_every 次未掉落 → 私聊 bot 发 /info 检查
                ctx.log.info("连续 %d 次未掉落，私聊 bot 发 /info 检查", failed)
                await _send_info(ctx)
            else:
                _arm_send(ctx, cfg, now)  # 同题重试（n 不变 x 升高，拟人延迟后真发）
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
