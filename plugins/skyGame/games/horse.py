# -*- coding: utf-8 -*-
# 天空游戏 · 养马：hdsky 门户养马自动化
#
# 基于实测门户 API（GET /api/portal/horse + POST /api/portal/horse/action
# + POST /api/portal/horse/race/action）：
#   - 单马账号模型，动作体 {action, requestKey, feedType?}
#   - 每日上限：喂食 feedMax 次 / 遛马 walkMax 次（stats 字段）
#   - 动作有冷却（result.code == "cooldown"）：静默处理，按 remainMs 退避不重复尝试
#   - 普通喂食（weed/fine）与仙草（divine）独立计数、独立冷却（profile 的
#     daily_feed_count 与 daily_divine_feed_count 分开）
#   - 比赛分两类：官方赛（competitions.official，每日免费报名一次）与
#     玩家养马赛（competitions.match，host 玩家开房、其他玩家按报名额加入）
#   - 每轮轮询最多执行一个养护动作，节奏拟人：
#       死亡 → （可选）复活
#       玩家赛可加入且体力足 → 加入（配置开关）
#       玩家赛可加入但体力不足 → 先喂配置草料（精草/杂草），不够再仙草
#       今日普通喂食额度未用完 → 喂配置草料（不再只看饱腹阈值）
#       可遛 且未达上限 → 遛马（赚银元+经验）
#       官方赛可报名 →（可选）免费报名
#   - 喂食通知用结构化表格（notify_table），不把服务端长文案原样推送
#   - 遛马连续失败熔断按「天」自动重置（kv 带日期），避免历史失败永久禁用遛马

from __future__ import annotations

import asyncio
import datetime
import json

from . import hdsky_auth
from .hdsky import HdskyClient, request_key

_task: asyncio.Task[None] | None = None

# 门户 horse.feeds 实测（2026-08-13）：普通喂食每日 5 次，仙草每日 3 次，独立计数。
_FEED_LABELS = {"weed": "杂草", "fine": "精草", "divine": "仙草"}
_FEED_STAMINA = {"weed": 6, "fine": 18, "divine": 50}
_DIVINE_DAILY_MAX = 3
_FEED_CD_KEY = "horse:feed_cooldown_until"
_DIVINE_CD_KEY = "horse:divine_cooldown_until"


async def _horse_action(client: HdskyClient, action: str, **extra: object) -> dict:
    """POST /api/portal/horse/action，自动带 requestKey。"""
    body: dict = {"action": action, "requestKey": request_key(), **extra}
    return await client.post("/api/portal/horse/action", body)


def _feed_label(feed_type: str) -> str:
    return _FEED_LABELS.get(feed_type, feed_type or "草料")


def _stat_pair(current: object, maximum: int) -> str:
    return f"{int(current or 0)}/{maximum}"


def _format_feed_table(payload: dict, fallback: str) -> tuple[list[str], list[list[object]], str]:
    """把喂食结果收成两列表格，不把服务端长文案原样推送。

    实测 feed 成功响应含 feedType/feedLabel/amount/expGain/progressGain/profile，
    旧实现直接推 result.message（十余行说明+规则），平台按「字段：内容」自动拆表后列对不齐。
    """
    result = payload.get("result", {}) or {}
    profile = result.get("profile") or {}
    feed_type = str(result.get("feedType") or "")
    label = str(result.get("feedLabel") or _feed_label(feed_type) or "草料")
    ok = bool(result.get("ok", payload.get("ok", False)))
    caption = f"🐴 {label}喂养成功" if ok else f"🐴 {result.get('message') or fallback}"
    rows: list[list[object]] = [["草料", label]]
    amount = result.get("amount")
    if amount not in (None, ""):
        rows.append(["花费", f"{int(amount):,} 银元"])
    if result.get("expGain") not in (None, ""):
        rows.append(["经验", f"+{int(result.get('expGain') or 0)}"])
    if result.get("progressGain") not in (None, ""):
        rows.append(["长期进度", f"+{result.get('progressGain')}"])
    if profile:
        if profile.get("horse_name"):
            rows.append(["马匹", str(profile.get("horse_name"))])
        if profile.get("level") is not None:
            exp = profile.get("exp")
            level_text = f"Lv.{int(profile.get('level') or 0)}"
            if exp not in (None, ""):
                level_text += f"（经验 {int(exp):,}）"
            rows.append(["等级", level_text])
        if profile.get("stamina") is not None:
            rows.append(["体力", _stat_pair(profile.get("stamina"), 100)])
        if profile.get("mood") is not None:
            rows.append(["心情", _stat_pair(profile.get("mood"), 100)])
        if profile.get("satiety") is not None:
            rows.append(["饱腹", _stat_pair(profile.get("satiety"), 100)])
        if profile.get("daily_feed_count") is not None:
            rows.append(["今日普通喂养", _stat_pair(profile.get("daily_feed_count"), 5)])
        if profile.get("daily_divine_feed_count") is not None:
            rows.append(["今日仙草", _stat_pair(profile.get("daily_divine_feed_count"), _DIVINE_DAILY_MAX)])
    if len(rows) == 1 and not ok:
        rows = [["结果", result.get("message") or fallback]]
    return ["项目", "内容"], rows, caption


async def _notify_result(ctx: object, cfg: dict, payload: dict, fallback: str) -> None:
    """喂食走结构化表格；其它动作仍用服务端短消息。cooldown 静默。"""
    result = payload.get("result", {}) or {}
    if result.get("code") == "cooldown":
        ctx.log.debug("养护动作冷却中: %s", result.get("message", ""))
        return
    if not cfg.get("horse_notify", True):
        return
    ok = bool(result.get("ok", payload.get("ok", False)))
    if result.get("feedType") or result.get("feedLabel") or fallback.startswith("喂"):
        headers, rows, caption = _format_feed_table(payload, fallback)
        await ctx.notify_table(headers, rows, caption=caption, level="success" if ok else "warning", category="养马")
        return
    msg = result.get("message") or fallback
    if ok:
        await ctx.notify(f"🐴 {msg}", category="养马")
    else:
        await ctx.notify(f"🐴 {msg}", level="warning", category="养马")


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


def _feed_cooldown_handle(ctx: object, r: dict, key: str, now_ms: int) -> None:
    """feed 撞冷却（「刚刚吃过了 xx分钟后再喂」）→ 记 remainMs 退避，不硬试；非冷却清除。"""
    result = r.get("result", {}) or {}
    if result.get("code") == "cooldown":
        remain_ms = int(result.get("remainMs", 0) or 0)
        if remain_ms > 0:
            ctx.kv.set(key, now_ms + remain_ms)
        ctx.log.debug("%s 冷却中: %s", key, result.get("message", ""))
    else:
        ctx.kv.delete(key)


def _configured_feed_type(cfg: dict) -> str:
    feed_type = str(cfg.get("horse_feed_type", "fine") or "fine")
    return feed_type if feed_type in _FEED_LABELS else "fine"


def _in_cooldown(ctx: object, key: str, now_ms: int) -> bool:
    return now_ms < int(ctx.kv.get(key, 0) or 0)


def _regular_feed_ready(st: dict, stats: dict, profile: dict, now_ms: int, ctx: object) -> bool:
    """普通喂食（weed/fine）额度未用完、可喂、且不在冷却。"""
    feed_count = int(stats.get("feedCountToday", profile.get("daily_feed_count", 0)) or 0)
    feed_max = int(stats.get("feedMax", 5) or 5)
    return bool(st.get("canFeed")) and feed_count < feed_max and not _in_cooldown(ctx, _FEED_CD_KEY, now_ms)


def _divine_feed_ready(st: dict, profile: dict, now_ms: int, ctx: object) -> bool:
    """仙草额度未用完、可喂、且不在冷却。"""
    divine_count = int(profile.get("daily_divine_feed_count", 0) or 0)
    return (
        bool(st.get("canFeed")) and divine_count < _DIVINE_DAILY_MAX and not _in_cooldown(ctx, _DIVINE_CD_KEY, now_ms)
    )


async def _do_feed(ctx: object, cfg: dict, client: HdskyClient, feed_type: str, reason: str) -> dict:
    """执行一次喂食并处理冷却/通知。"""
    cd_key = _DIVINE_CD_KEY if feed_type == "divine" else _FEED_CD_KEY
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    r = await _horse_action(client, "feed", feedType=feed_type)
    ctx.log.info("喂食 %s（%s）", feed_type, reason)
    _feed_cooldown_handle(ctx, r, cd_key, now_ms)
    await _notify_result(ctx, cfg, r, f"喂{_feed_label(feed_type)}失败")
    return r


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
    stamina = int(profile.get("stamina", 100) or 100)
    now_ms = int(datetime.datetime.now().timestamp() * 1000)

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

    # 玩家养马赛（competitions.match）：host 开房后 active，actions 含 join 即可加入。
    # 契约来自门户前端 portal-horse.js（实测 2026-08-08）：可加入才给 join 动作，
    # 加入请求体仅 {action: "join", requestKey}，报名额取服务端 match.amount。
    comps = horse.get("competitions", {}) or {}
    match = comps.get("match", {}) or {}
    match_joinable = (
        bool(cfg.get("horse_auto_match_race", True))
        and bool(match.get("active"))
        and "join" in (match.get("actions") or [])
        and not bool(match.get("joined"))
    )
    min_stamina = int(cfg.get("horse_race_min_stamina", 30) or 30)

    # 玩家赛：体力足够 → 直接加入
    if match_joinable and stamina >= min_stamina:
        r = await client.post("/api/portal/horse/race/action", {"action": "join", "requestKey": request_key()})
        ctx.log.info(
            "加入玩家养马赛 #%s（报名额 %s 银元，体力 %d）", match.get("roundId"), match.get("amount"), stamina
        )
        await _notify_result(ctx, cfg, r, "玩家赛加入失败")
        return

    # 补体力：玩家赛可加入但体力不足。优先喂配置草料（精草/杂草），只有配置草料
    # 不够达标 / 额度用完 / 冷却中才动仙草。两边都喂不了则本轮空手，等冷却，不遛马耗体力。
    if match_joinable and stamina < min_stamina:
        feed_type = _configured_feed_type(cfg)
        if feed_type != "divine" and _regular_feed_ready(st, stats, profile, now_ms, ctx):
            gain = _FEED_STAMINA.get(feed_type, 0)
            if stamina + gain >= min_stamina:
                await _do_feed(
                    ctx,
                    cfg,
                    client,
                    feed_type,
                    f"玩家赛体力不足（{stamina} < {min_stamina}），{_feed_label(feed_type)}+{gain} 可达标",
                )
                return
        if _divine_feed_ready(st, profile, now_ms, ctx):
            await _do_feed(ctx, cfg, client, "divine", f"玩家赛体力不足（{stamina} < {min_stamina}），喂仙草补体力")
            return
        ctx.log.debug(
            "玩家赛体力不足（%d < %d）且草料暂不可喂，等待补体力",
            stamina,
            min_stamina,
        )
        return

    # 日常喂食：今日普通额度没用完就喂配置草料（用满 5 次攒体力/长期进度）。
    # 饱腹阈值只作下限提示，不再挡住额度未用完的精草。
    satiety = int(profile.get("satiety", 100) or 0)
    threshold = int(cfg.get("horse_feed_threshold", 60) or 0)
    feed_count = int(stats.get("feedCountToday", profile.get("daily_feed_count", 0)) or 0)
    feed_max = int(stats.get("feedMax", 5) or 5)
    feed_type = _configured_feed_type(cfg)
    if feed_type == "divine":
        if _divine_feed_ready(st, profile, now_ms, ctx) and satiety < threshold:
            await _do_feed(ctx, cfg, client, "divine", f"饱腹 {satiety} < {threshold}")
            return
    elif _regular_feed_ready(st, stats, profile, now_ms, ctx):
        await _do_feed(ctx, cfg, client, feed_type, f"今日普通喂养 {feed_count}/{feed_max}，饱腹 {satiety}")
        return
    elif st.get("canFeed") and feed_count < feed_max and _in_cooldown(ctx, _FEED_CD_KEY, now_ms):
        remain = (int(ctx.kv.get(_FEED_CD_KEY, 0) or 0) - now_ms) // 60000
        ctx.log.debug("喂食冷却中，剩余 %d 分钟，本轮跳过不重复尝试", remain)

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
    official = comps.get("official", {}) or {}
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
