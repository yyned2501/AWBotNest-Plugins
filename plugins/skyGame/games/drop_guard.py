# -*- coding: utf-8 -*-
# 天空游戏 · 掉落守卫
#
# 天空小秘的银元掉落有时段配额，配额满后参与游戏也领不到掉落奖励，
# 白耗报名银元/体力。本模块定期私聊 bot 发 /info，解析「当前时段剩余掉落」：
# 剩余为 0 → 拦截各游戏的新加入（十点半报名/炸金花入桌/赛马报名），
# 时段切换后剩余回升 → 自动恢复。实现参照 skyDropAnswer 的 /info 校准模式，
# 各插件自行读取，互不依赖（插件间禁止互相 import）。
#
# kv 键：
#   dropguard:remaining   最近一次 /info 解析出的本时段剩余掉落
#   dropguard:checked_ts  最近一次成功解析 /info 回复的时间
#   dropguard:sent_ts     最近一次发送 /info 的时间（防无回复时重复发送）
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
_TICK_SECONDS = 60  # 低频检查；实际发 /info 的间隔由 drop_guard_interval 配置控制


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


def paused(ctx: object) -> bool:
    """掉落配额已满且 /info 结果新鲜 → True，各游戏用它拦截新加入。

    未查过/数据非法/结果过期一律 False（照常参与，宁可多打不误停）。
    """
    try:
        remaining = int(ctx.kv.get(_KV_REMAINING))
    except (TypeError, ValueError):
        return False
    if remaining > 0:
        return False
    ts = float(ctx.kv.get(_KV_CHECKED_TS, 0) or 0)
    return time.time() - ts < _STALE_AFTER


def parse_remaining(text: str) -> int | None:
    """从 /info 回复解析本时段剩余「游戏」掉落配额；无法解析返回 None。"""
    m = _INFO_GAME_RE.search(text)
    if m:
        return int(m.group(1))
    m = _INFO_LEGACY_RE.search(text)
    return int(m.group(1)) if m else None


async def apply_reply(ctx: object, text: str) -> bool:
    """解析 /info 回复更新剩余数；暂停状态翻转时通知一次。返回是否解析成功。"""
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
    """掉落守卫专用 bot（读 drop_guard_bot）；留空回退默认天空小秘。

    不复用全局 bot 配置——线上曾把那里配成 HDSky 验证 bot，发 /info 无掉落回复。
    """
    return _parse_bot_ids(str(cfg.get("drop_guard_bot", "") or ""))


async def _guard_tick(ctx: object) -> None:
    """低频 tick：间隔到了就私聊 bot 发一次 /info（回复由 handler 捕获解析）。"""
    if not _guard_enabled(ctx):
        return
    interval = max(5, int(ctx.config.get("drop_guard_interval", 10) or 10)) * 60
    now = time.time()
    last = max(float(ctx.kv.get(_KV_CHECKED_TS, 0) or 0), float(ctx.kv.get(_KV_SENT_TS, 0) or 0))
    if now - last < interval:
        return
    bot_ids = _guard_bot_ids(ctx.config)
    target = bot_ids[0]
    if isinstance(target, str) and not target.startswith("@"):
        target = f"@{target}"
    try:
        await ctx.user.send(target, "/info")
        ctx.kv.set(_KV_SENT_TS, now)
        ctx.log.info("掉落守卫：已私聊 bot %s 发送 /info", target)
    except Exception as e:
        ctx.log.warning("掉落守卫 /info 发送失败: %r", e)


def start(ctx: object) -> None:
    """注册 /info 回复捕获 handler + 低频检查调度。"""
    bot_ids = _guard_bot_ids(ctx.config)
    info_filter = ctx.filters.private & ctx.filters.user(bot_ids) & ctx.filters.text

    @ctx.on_message(info_filter, group=7)
    async def _on_info_reply(client: object, message: object) -> None:
        if not _guard_enabled(ctx):
            return
        text = (message.text or "").strip()
        if "银元奖励" in text:  # 掉落消息不是 /info 回复
            return
        if await apply_reply(ctx, text):
            ctx.log.debug("掉落守卫：捕获 /info 回复 msg=%s", message.id)
        else:
            # 观测点：handler 触发但无配额行——用于区分「filter 没匹配」与「回复格式变了」
            ctx.log.info("掉落守卫：捕获 bot 私聊消息但未匹配配额行: %s", text[:200])

    async def _tick() -> None:
        try:
            await _guard_tick(ctx)
        except Exception as e:
            ctx.log.error("掉落守卫 tick 异常: %r", e)

    ctx.schedule(_tick, "interval", seconds=_TICK_SECONDS, id="drop_guard_tick")
    ctx.log.info("掉落守卫已启动（每 %ds 检查一次 /info 是否到期，监听 bot=%s）", _TICK_SECONDS, bot_ids)


def stop(ctx: object) -> None:
    """schedule 与 handler 由平台在卸载时自动清理，无需额外动作。"""
