# -*- coding: utf-8 -*-
# 天空游戏 · 养马：hdsky 门户养马自动化
#
# 基于实测门户 API（GET /api/portal/horse + POST /api/portal/horse/action）：
#   - 单马账号模型，动作体 {action, requestKey, feedType?}
#   - 每日上限：喂食 feedMax 次 / 遛马 walkMax 次（stats 字段）
#   - 动作有冷却（result.code == "cooldown"）：静默处理不刷通知
#   - 每轮轮询最多执行一个养护动作，节奏拟人：
#       死亡 → （可选）复活
#       饱腹度 < 阈值 且可喂 → 喂食（feedType 可配）
#       可遛 且未达上限 → 遛马（赚银元+经验）
#       官方赛可报名 →（可选）免费报名
#   - 结果通知用服务端返回的 result.message
#   - 遛马连续失败熔断按「天」自动重置（kv 带日期），避免历史失败永久禁用遛马

from __future__ import annotations

import asyncio
import datetime
import json

from . import hdsky_auth
from .hdsky import HdskyClient, request_key

_task: asyncio.Task[None] | None = None


async def _horse_action(client: HdskyClient, action: str, **extra: object) -> dict:
    """POST /api/portal/horse/action，自动带 requestKey。"""
    body: dict = {"action": action, "requestKey": request_key(), **extra}
    return await client.post("/api/portal/horse/action", body)


async def _notify_result(ctx: object, cfg: dict, payload: dict, fallback: str) -> None:
    """用服务端返回的消息通知。cooldown 是预期内拒绝，只记 debug 不打扰。"""
    result = payload.get("result", {}) or {}
    if result.get("code") == "cooldown":
        ctx.log.debug("养护动作冷却中: %s", result.get("message", ""))
        return
    if not cfg.get("horse_notify", True):
        return
    msg = result.get("message") or fallback
    ok = result.get("ok", payload.get("ok", False))
    if ok:
        await ctx.notify(f"🐴 {msg}")
    else:
        await ctx.notify(f"🐴 {msg}", level="warning")


def _walk_fail_count(kv: object, key: str, today: str) -> int:
    """读取遛马连续失败计数，跨天自动重置为 0。

    kv 存 JSON 字符串 ``{"count": N, "date": "YYYY-MM-DD"}``；兼容旧版纯数字
    （无日期，历史遗留熔断）——视为跨天自动重置。否则熔断后只能在成功遛马时
    清零，而计数到 3 就不再发 walk，形成永久死锁（线上 08-01 遗留 count=3，
    之后遛马永不执行、体力一直满）。
    """
    raw = kv.get(key, None)
    count, date = 0, ""
    if isinstance(raw, dict):
        count = int(raw.get("count", 0) or 0)
        date = str(raw.get("date", "") or "")
    elif isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            parsed = json.loads(raw)
            count = int(parsed.get("count", 0) or 0)
            date = str(parsed.get("date", "") or "")
        except (ValueError, TypeError):
            count, date = 0, ""
    elif raw:
        count = int(raw)
    return 0 if date != today else count


async def _care_once(ctx: object, cfg: dict, client: HdskyClient) -> None:
    """单次养护决策：最多执行一个动作。"""
    data = await client.get("/api/portal/horse")
    if "_error" in data:
        ctx.log.warning("养马状态请求失败: %s", data["_error"] or "未知网络错误")
        client.reset_csrf()
        return
    horse = data.get("horse") or {}
    profile = horse.get("profile")
    if not profile:
        # 账号还没有马：只提示一次，领养需用户到门户手动选名
        if not ctx.kv.get("horse:no_horse_notified"):
            ctx.kv.set("horse:no_horse_notified", 1)
            ctx.log.info("账号尚无马匹，需手动领养")
            if cfg.get("horse_notify", True):
                await ctx.notify("🐴 账号还没有马，请到门户页面手动领养")
        return
    ctx.kv.delete("horse:no_horse_notified")

    st = profile.get("state", {}) or {}
    stats = horse.get("stats", {}) or {}
    balance = horse.get("balance", 0) or 0

    # 死亡处理：复活昂贵（约 30 万银元），默认只提示不动作
    if st.get("isDead"):
        if cfg.get("horse_auto_revive", False) and balance >= int(profile.get("reviveCost", 0) or 0):
            r = await _horse_action(client, "revive")
            await _notify_result(ctx, cfg, r, "复活失败")
        elif not ctx.kv.get("horse:death_notified"):
            ctx.kv.set("horse:death_notified", 1)
            ctx.log.warning("马匹已死亡（未开启自动复活）")
            if cfg.get("horse_notify", True):
                await ctx.notify("🐴 马匹已死亡，请处理（可开启自动复活）", level="error")
        return
    ctx.kv.delete("horse:death_notified")

    # 喂食：饱腹度低于阈值且今日次数未到上限
    satiety = int(profile.get("satiety", 100) or 0)
    threshold = int(cfg.get("horse_feed_threshold", 60) or 0)
    feed_count = int(stats.get("feedCountToday", 0) or 0)
    feed_max = int(stats.get("feedMax", 0) or 0)
    if st.get("canFeed") and satiety < threshold and feed_count < feed_max:
        feed_type = str(cfg.get("horse_feed_type", "weed") or "weed")
        r = await _horse_action(client, "feed", feedType=feed_type)
        ctx.log.info("喂食 %s（饱腹 %d < %d，今日 %d/%d）", feed_type, satiety, threshold, feed_count + 1, feed_max)
        await _notify_result(ctx, cfg, r, "喂食失败")
        return

    # 遛马：消耗体力赚银元+经验，用完每日额度
    walk_count = int(stats.get("walkCountToday", 0) or 0)
    walk_max = int(stats.get("walkMax", 0) or 0)
    if cfg.get("horse_auto_walk", True) and st.get("canWalk") and walk_count < walk_max:
        walk_fail_key = "horse:walk_consecutive_failures"
        today = datetime.date.today().isoformat()
        walk_fail_count = _walk_fail_count(ctx.kv, walk_fail_key, today)
        if walk_fail_count >= 3:
            ctx.log.debug("遛马今日连续失败 %d 次，跳过本轮（次日自动恢复）", walk_fail_count)
            return
        # 门户遛马冷却约 45 分钟，冷却期间 canWalk 仍为 true；靠上次响应的 remainMs 退避，
        # 避免每轮轮询都撞冷却、刷出大量看似失败的「遛马」日志
        cooldown_until_key = "horse:walk_cooldown_until"
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        cooldown_until = int(ctx.kv.get(cooldown_until_key, 0) or 0)
        if now_ms < cooldown_until:
            ctx.log.debug("遛马冷却中，剩余 %d 分钟，跳过本轮", (cooldown_until - now_ms) // 60000)
            return
        r = await _horse_action(client, "walk")
        result = r.get("result", {}) or {}
        if result.get("code") == "cooldown":
            remain_ms = int(result.get("remainMs", 0) or 0)
            if remain_ms > 0:
                ctx.kv.set(cooldown_until_key, now_ms + remain_ms)
            ctx.log.debug("遛马冷却中，不计数: %s", result.get("message", ""))
        elif result.get("ok", r.get("ok", False)):
            ctx.kv.set(walk_fail_key, json.dumps({"count": 0, "date": today}))
            ctx.kv.delete(cooldown_until_key)
            ctx.log.info("遛马成功（今日 %d/%d）", walk_count + 1, walk_max)
        else:
            ctx.kv.set(walk_fail_key, json.dumps({"count": walk_fail_count + 1, "date": today}))
            ctx.log.warning("遛马失败: %s", result.get("message") or result.get("code") or "未知")
        await _notify_result(ctx, cfg, r, "遛马失败")
        return

    # 官方赛：每日免费报名一次（kv 持久化，避免重复报名）
    official = (horse.get("competitions", {}) or {}).get("official", {}) or {}
    eligibility = official.get("eligibility", {}) or {}
    today = datetime.date.today().isoformat()
    if official.get("joined"):
        ctx.kv.set("horse:race_last_signup_date", today)
        ctx.log.debug("官方赛今日已报名（服务端状态），跳过")
    elif ctx.kv.get("horse:race_last_signup_date") == today:
        ctx.log.debug("今日已报名官方赛，明天再检查")
    elif cfg.get("horse_auto_official_race", False) and official.get("signupOpen") and eligibility.get("canRace"):
        r = await client.post("/api/portal/horse/race/action", {"action": "official_join", "requestKey": request_key()})
        ctx.log.info("报名官方赛马")
        if r.get("ok", False):
            ctx.kv.set("horse:race_last_signup_date", today)
        await _notify_result(ctx, cfg, r, "官方赛报名失败")
        return


async def _care_loop(ctx: object) -> None:
    """养护主循环：轮询状态 + 每轮最多一个动作。"""
    cfg = ctx.config
    interval = float(cfg.get("horse_poll_interval", 120) or 120)

    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        while True:
            try:
                if not cfg.get("horse_enabled", False):
                    await asyncio.sleep(interval)
                    continue

                # 每轮读最新配置（cookie 路径/门户地址可能被改）
                client.configure(
                    str(cfg.get("hdsky_cookie_file", "") or ""),
                    str(cfg.get("hdsky_base_url", "") or ""),
                    debug_enabled=bool(cfg.get("hdsky_debug", False)),
                    debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
                )
                await _care_once(ctx, cfg, client)
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                ctx.log.error("养马轮询异常: %r", e)
                client.reset_csrf()
                if cfg.get("horse_notify", True):
                    await ctx.notify(f"🐴 养马轮询异常: {e}", level="warning")
                await asyncio.sleep(interval)


def start(ctx: object) -> None:
    """启动养马养护任务。"""
    global _task
    _task = asyncio.create_task(_care_loop(ctx))
    ctx.log.info("养马已启动")


def stop(ctx: object) -> None:
    """停止养马养护任务。"""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
    ctx.log.info("养马已停止")
