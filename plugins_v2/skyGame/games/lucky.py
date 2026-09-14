# -*- coding: utf-8 -*-
# 天空游戏 · 幸运轮盘免费抽奖
#
# 门户幸运大转盘的免费次数由当日随机掉落累计兑换（/info 可见「免费抽奖次数」），
# 当天不用隔天作废。本模块每天到配置时刻（默认 23:50）把剩余免费次数一次性抽掉。
#
# API（2026-08-19 实测）：
#   GET  /api/portal/lucky        → lucky.freeSpins 剩余免费次数
#   POST /api/portal/lucky/spin   {count, requestKey} → 免费次数优先抵扣（costAmount=0），
#        result{spinCount/freeSpinCount/costAmount/silverGain/balanceAfter/summary[]}
#
# kv 键：
#   lucky:last_draw_date  最近一次成功抽奖的日期（YYYY-MM-DD，每日幂等）

from __future__ import annotations

import datetime

from . import ai_review, hdsky_auth
from .hdsky import HdskyClient, request_key

_KV_LAST_DRAW_DATE = "lucky:last_draw_date"

_LUCKY_PATH = "/api/portal/lucky"
_SPIN_PATH = "/api/portal/lucky/spin"
_DEFAULT_DRAW_TIME = "23:50"
_TICK_SECONDS = 60


def _draw_minutes(cfg: dict) -> int:
    """解析每日抽奖时刻 lucky_draw_time（HH:MM）为分钟数；非法回退默认 23:50。"""
    raw = str(cfg.get("lucky_draw_time", _DEFAULT_DRAW_TIME) or _DEFAULT_DRAW_TIME).strip()
    try:
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return 23 * 60 + 50


def should_draw(cfg: dict, kv: object, now: datetime.datetime | None = None) -> bool:
    """到了当日抽奖时刻且今天还没抽过 → True。"""
    if not bool(cfg.get("lucky_enabled", True)):
        return False
    now = now or datetime.datetime.now()
    if str(kv.get(_KV_LAST_DRAW_DATE, "") or "") == now.strftime("%Y-%m-%d"):
        return False
    cur = now.hour * 60 + now.minute
    return cur >= _draw_minutes(cfg)


def _format_result(result: dict) -> str:
    """把 spin 响应结构化成推送文案。"""
    lines = [f"🎰 幸运轮盘免费抽奖 ×{result.get('freeSpinCount', 0)} 已执行"]
    for item in result.get("summary") or []:
        label = item.get("label") or "未知奖品"
        count = item.get("count", 1)
        lines.append(f"- {label} ×{count}" if "×" not in label else f"- {label}")
    silver = result.get("silverGain", 0)
    balance = result.get("balanceAfter")
    tail = f"获得银元 {silver:,}" if silver else "未获得银元"
    if balance is not None:
        tail += f"，余额 {balance:,}"
    lines.append(tail)
    return "\n".join(lines)


async def draw_free_spins(ctx: object, cfg: dict, client: HdskyClient) -> bool:
    """查询剩余免费次数并一次抽完；成功返回 True（调用方负责记日期）。"""
    data = await client.get(_LUCKY_PATH)
    if "_error" in data:
        ctx.log.warning("幸运轮盘状态请求失败: %s", data["_error"] or "未知网络错误")
        client.reset_csrf()
        return False
    free = int((data.get("lucky") or {}).get("freeSpins") or 0)
    if free <= 0:
        ctx.log.info("幸运轮盘：今日无免费抽奖次数，跳过")
        return True  # 无次数也算处理完，记日期避免当天反复查询
    resp = await client.post(_SPIN_PATH, {"count": free, "requestKey": request_key()})
    result = resp.get("result") if isinstance(resp, dict) else None
    if not resp.get("ok") or not isinstance(result, dict) or not result.get("ok"):
        err = (result or {}).get("message") or resp.get("_error") or "未知错误"
        ctx.log.warning("幸运轮盘抽奖失败: %s", err)
        return False
    msg = _format_result(result)
    ctx.log.info("幸运轮盘：%s", msg.replace("\n", "；"))
    try:
        await ctx.notify(msg, category="幸运轮盘")
    except Exception as e:
        ctx.log.warning("幸运轮盘通知发送失败（渠道暂不可用）: %r", e)
    # AI 评价（v1.23.16）：抽奖结果有输有赢，开关在「AI 评价」配置
    await ai_review.review(ctx, cfg, "lucky", int(result.get("silverGain", 0) or 0), msg, actions="幸运轮盘免费抽奖")
    return True


async def _lucky_tick(ctx: object) -> None:
    """每分钟检查：到点且今日未抽 → 开客户端抽掉免费次数。"""
    cfg = ctx.config
    if not should_draw(cfg, ctx.kv):
        return
    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        client.configure(
            str(cfg.get("hdsky_cookie_file", "") or ""),
            str(cfg.get("hdsky_base_url", "") or ""),
            debug_enabled=bool(cfg.get("hdsky_debug", False)),
            debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
        )
        if await draw_free_spins(ctx, cfg, client):
            ctx.kv.set(_KV_LAST_DRAW_DATE, datetime.datetime.now().strftime("%Y-%m-%d"))


def start(ctx: object) -> None:
    """注册每日免费抽奖检查调度（60s 一次，幂等由 kv 日期保证）。"""
    cfg = ctx.config
    if not bool(cfg.get("lucky_enabled", True)):
        ctx.log.info("幸运轮盘免费抽奖未启用")
        return

    async def _tick() -> None:
        try:
            await _lucky_tick(ctx)
        except Exception as e:
            ctx.log.error("幸运轮盘 tick 异常: %r", e)

    ctx.schedule(_tick, "interval", seconds=_TICK_SECONDS, id="lucky_tick")
    ctx.log.info(
        "幸运轮盘免费抽奖已启动（每天 %s 后抽掉当日免费次数）",
        str(cfg.get("lucky_draw_time", _DEFAULT_DRAW_TIME) or _DEFAULT_DRAW_TIME),
    )


def stop(ctx: object) -> None:
    """schedule 由平台在卸载时自动清理，无需额外动作。"""
