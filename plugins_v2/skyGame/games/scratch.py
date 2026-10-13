# -*- coding: utf-8 -*-
# 天空游戏 · 刮刮乐兜底（门户 API）
#
# 每小时 scratch_fallback_minute（默认 50）起至整点，若本时段「游戏」剩余掉落仍 > 0
# （十点半/炸金花没把掉落打完），就用门户刮刮乐把剩余刮掉；每张刮完立刻催一次 /info
# 刷新剩余，归零或跨整点即停。
#
# 为什么走门户、不在群里发 /scratch：门户刮刮乐与 TG 是同一张卡、同一份额度（门户前端
# 文案「九格惊喜 · 与 TG /scratch 同步」），走 API 既不用往万人群里刷屏，也不用点内联
# 按钮、判「玩家：」归属。剩余掉落数门户没有接口，仍取掉落守卫的 TG /info
# （单一口径，见 drop_guard.remaining / drop_guard.refresh）。
#
# API（2026-10-07 门户前端 portal-scratch.js 源码；未经真机核对的字段一律按「刮不动」
# 处理，不猜）：
#   GET  /api/portal/scratch → scratch{card, cost}
#        card{status, cells[{position, opened, prize, net}], expiresAt}
#   POST /api/portal/scratch {action:"start"|"reveal"|"abandon", cardId?, position?} → 同上
#   规则：开卡免费、刮开时才结算；30 秒无操作结束本张，未刮格子不扣款；
#        有效银元结算可触发游戏掉落（受每小时次数限制）。
#
# kv 键：
#   scratch:loss      连续亏损张数（净 <0 累加，回本清零）
#   scratch:halt_day  连亏达上限后停刮的归属日（北京时间 YYYY-MM-DD，次日自动恢复）
#   scratch:report_day 最近一次推收支日报的日期（同一小时窗口内幂等）

from __future__ import annotations

import asyncio
import datetime
import json
import os
import random
import time
from datetime import timedelta, timezone

from . import drop_guard, hdsky_auth
from .hdsky import HdskyClient, resolve_proxy

_SCRATCH_PATH = "/api/portal/scratch"
_DEFAULT_CELL_COST = 100
_DEFAULT_FALLBACK_MINUTE = 50
_DEFAULT_REPORT_HOUR = 23
_DEFAULT_REPORT_MINUTE = 55
_TICK_SECONDS = 60
_SKIP_LOG_GAP = 600.0  # 「本轮为何不刮」最多 10 分钟提示一次，防刷日志
_INFO_RETRY_GAP = 600.0  # 剩余掉落未知时，最多 10 分钟催一次 /info（bot 不回话也不刷屏）

_TZ_CN = timezone(timedelta(hours=8))
_LEDGER_FILE = "scratch_ledger.jsonl"  # 逐张流水，append-only，跨重载持久
_DAILY_FILE = "scratch_daily.json"  # 按日聚合缓存（原子替换写入）

_KV_LOSS = "scratch:loss"
_KV_HALT_DAY = "scratch:halt_day"
_KV_REPORT_DAY = "scratch:report_day"

# 单张卡的串行互斥：一张 9 格加上网络重试可能超过一个 tick 周期，避免两轮同时刮同一张
_playing = False
_last_skip_log = 0.0


def _enabled(cfg: dict) -> bool:
    return bool(cfg.get("scratch_enabled", True))


def _fallback_minute(cfg: dict) -> int:
    """兜底窗口起始分钟位（0～55），非法值回退 50。"""
    try:
        value = int(cfg.get("scratch_fallback_minute", _DEFAULT_FALLBACK_MINUTE))
    except (TypeError, ValueError):
        return _DEFAULT_FALLBACK_MINUTE
    return min(55, max(0, value))


def _max_loss(cfg: dict) -> int:
    try:
        value = int(cfg.get("scratch_max_consecutive_loss", 5))
    except (TypeError, ValueError):
        return 5
    return min(20, max(1, value))


def _reveal_delay(cfg: dict) -> float:
    try:
        return max(0.0, float(cfg.get("scratch_reveal_delay", 0.6)))
    except (TypeError, ValueError):
        return 0.6


def _in_window(cfg: dict, now: datetime.datetime) -> bool:
    """当前本地时刻是否落在本小时的兜底窗口 [起始分钟, 整点)。"""
    return now.minute >= _fallback_minute(cfg)


def _cn_now() -> datetime.datetime:
    """北京时间（容器时区是 UTC，游戏日界/时段都按 UTC+8，无夏令时）。"""
    return datetime.datetime.now(_TZ_CN)


def _day_key(ts: float | None = None) -> str:
    """归属日期（北京时间 YYYY-MM-DD），跨零点算新的一天。"""
    moment = datetime.datetime.fromtimestamp(ts, _TZ_CN) if ts is not None else _cn_now()
    return moment.strftime("%Y-%m-%d")


def halted_today(kv: object, day: str) -> bool:
    """连亏自动停是否命中今天（北京时间日界，次日自愈，不需要重启插件）。"""
    return str(kv.get(_KV_HALT_DAY, "") or "") == day


def _is_open(card: dict) -> bool:
    """门户卡面是否处于「可刮」状态（前端同样只认 status == 'open'）。"""
    return str(card.get("status") or "").strip().lower() == "open"


def _pick(payload: dict) -> tuple[dict, int, str]:
    """从门户响应取 (卡面, 每格价, 提示文案)。"""
    scratch = payload.get("scratch") if isinstance(payload.get("scratch"), dict) else {}
    card = scratch.get("card") if isinstance(scratch.get("card"), dict) else {}
    try:
        unit = int(scratch.get("cost") or _DEFAULT_CELL_COST)
    except (TypeError, ValueError):
        unit = _DEFAULT_CELL_COST
    return card, unit, str(payload.get("notice") or "")


def card_view(card: dict, unit_cost: int) -> dict:
    """把门户卡面折成插件口径（以门户为准，不自己累计）。

    返回 opened/payout/cost/net 与未刮格位（随机序，防总是刮同一列被摸出规律）。
    净额优先用门户给的逐格 `net`（已计结算手续费），没有该字段才退「派奖−成本」。
    """
    cells = [c for c in (card.get("cells") or []) if isinstance(c, dict)]
    opened = [c for c in cells if c.get("opened")]
    closed: list[int] = []
    for cell in cells:
        position = cell.get("position")
        if not cell.get("opened") and str(position or "").isdigit():
            closed.append(int(position))
    random.shuffle(closed)
    payout = sum(int(c.get("prize") or 0) for c in opened)
    nets = [c.get("net") for c in opened]
    if all(v is not None for v in nets):
        net = sum(int(v or 0) for v in nets)
    else:
        net = payout - len(opened) * unit_cost
    return {
        "opened": len(opened),
        "payout": payout,
        "cost": len(opened) * unit_cost,
        "net": net,
        "closed": closed,
    }


def _breakeven(view: dict, unit_cost: int) -> bool:
    """回本判据沿用 TG 版玩法：累计派奖 ≥ 已刮格数 × 每格价。"""
    return view["opened"] > 0 and view["payout"] >= view["opened"] * unit_cost


async def _post(client: HdskyClient, action: str, card_id: object = None, position: int | None = None) -> dict:
    """提交一次刮奖动作，请求体与门户前端逐字段一致（含 cardId 的出现条件）。"""
    body: dict[str, object] = {"action": action}
    if card_id is not None:
        body["cardId"] = card_id
    if position is not None:
        body["position"] = position
    return await client.post(_SCRATCH_PATH, body)


async def _call(
    ctx: object,
    client: HdskyClient,
    action: str,
    card_id: object = None,
    position: int | None = None,
) -> dict | None:
    """发一次请求并把门户的失败形态收敛干净：拿不到可用卡面就返回 None。"""
    if action == "get":
        data = await client.get(_SCRATCH_PATH)
    else:
        data = await _post(client, action, card_id, position)
    if "_error" in data:
        ctx.log.warning("刮奖 %s 请求失败: %s", action, data["_error"] or "未知网络错误")
        client.reset_csrf()
        return None
    if not isinstance(data.get("scratch"), dict):
        # 网关抖动/未登录会给出没有 scratch 的响应（HTTP 200 也算失败），此时什么都不刮最安全
        ctx.log.warning(
            "刮奖 %s 响应异常: ok=%s error=%s keys=%s",
            action, data.get("ok"), data.get("error") or data.get("notice") or "", sorted(data)[:8],
        )
        return None
    if not data.get("ok", True):
        ctx.log.warning("刮奖 %s 被拒: %s", action, data.get("error") or "未知错误")
        return None
    return data


async def scratch_once(ctx: object, cfg: dict, client: HdskyClient) -> dict | None:
    """刮一张卡：没有可刮的卡就免费领取一张 → 随机逐格刮 → 回本即「放弃」收尾。

    返回 {card_id, cells, payout, cost, net}；一张都没刮开返回 None（不记账、不算连亏）。
    """
    payload = await _call(ctx, client, "get")
    if payload is None:
        return None
    card, unit, notice = _pick(payload)
    if not _is_open(card):
        started = await _call(ctx, client, "start", card.get("id") if card else None)
        if started is None:
            return None
        card, unit, notice = _pick(started)
        if not _is_open(card):
            ctx.log.info("刮奖：领卡后仍不可刮（status=%s notice=%s）", card.get("status"), notice)
            return None

    delay = _reveal_delay(cfg)
    reveals = 0
    for position in card_view(card, unit)["closed"]:
        if delay:
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))
        revealed = await _call(ctx, client, "reveal", card.get("id"), position)
        if revealed is None:
            break
        reveals += 1
        card, unit, notice = _pick(revealed)
        view = card_view(card, unit)
        if not _is_open(card):
            ctx.log.info("刮奖：门户已结束本张（status=%s %d格）", card.get("status"), view["opened"])
            break
        if _breakeven(view, unit):
            ctx.log.info(
                "✅ 回本 卡#%s %d格 派奖%d 成本%d 净%+d",
                card.get("id"), view["opened"], view["payout"], view["cost"], view["net"],
            )
            abandoned = await _call(ctx, client, "abandon", card.get("id"))
            if abandoned is not None:
                card, unit, notice = _pick(abandoned)
            break

    view = card_view(card, unit)
    if reveals == 0:
        # 一格都没刮成（没有可刮格 / 首个 reveal 就被拒）：不记账，否则会把旧卡重记一遍
        ctx.log.warning("刮奖：本张没刮开任何格子（status=%s notice=%s）", card.get("status"), notice)
        return None
    return {
        "card_id": card.get("id"),
        "cells": view["opened"],
        "payout": view["payout"],
        "cost": view["cost"],
        "net": view["net"],
    }


# ── 收支统计（逐张流水 + 每日收支日报）─────────────────────────────────


def _stats_enabled(cfg: dict) -> bool:
    return bool(cfg.get("scratch_stats_enabled", True))


def _report_hour(cfg: dict) -> int:
    try:
        return min(23, max(0, int(cfg.get("scratch_stats_report_hour", _DEFAULT_REPORT_HOUR))))
    except (TypeError, ValueError):
        return _DEFAULT_REPORT_HOUR


def _report_minute(cfg: dict) -> int:
    try:
        return min(59, max(0, int(cfg.get("scratch_stats_report_minute", _DEFAULT_REPORT_MINUTE))))
    except (TypeError, ValueError):
        return _DEFAULT_REPORT_MINUTE


def _stats_path(ctx: object, name: str) -> str:
    """统计文件路径：ctx.data_dir 不可写时退 /tmp（不让统计把游戏循环搞崩）。"""
    base = str(getattr(ctx, "data_dir", "") or "") or "/tmp"
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = "/tmp"
    return os.path.join(base, name)


def _empty_bucket() -> dict:
    return {"cards": 0, "cells": 0, "cost": 0, "payout": 0, "net": 0, "breakeven": 0, "loss": 0}


def _stats_load(ctx: object) -> dict:
    try:
        with open(_stats_path(ctx, _DAILY_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _stats_save(ctx: object, data: dict) -> None:
    path = _stats_path(ctx, _DAILY_FILE)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)  # 原子替换，防写一半把日汇总写坏
    except OSError as exc:
        ctx.log.warning("刮奖收益统计写盘失败: %s", exc)


def _stats_append(ctx: object, row: dict) -> None:
    try:
        with open(_stats_path(ctx, _LEDGER_FILE), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        ctx.log.warning("刮奖收益流水写盘失败: %s", exc)


def record_card(ctx: object, cfg: dict, result: dict) -> None:
    """逐张记账：写流水 + 更新当日聚合 + 一行可 grep 的汇总日志（不推送到通知）。"""
    if not _stats_enabled(cfg) or not isinstance(result, dict):
        return
    now = time.time()
    day = _day_key(now)
    outcome = "breakeven" if int(result.get("net", 0) or 0) >= 0 else "loss"
    _stats_append(ctx, {
        "type": "card", "ts": round(now, 3), "date": day,
        "card_id": result.get("card_id"), "cells": int(result.get("cells", 0) or 0),
        "cost": int(result.get("cost", 0) or 0), "payout": int(result.get("payout", 0) or 0),
        "net": int(result.get("net", 0) or 0), "outcome": outcome,
    })
    data = _stats_load(ctx)
    bucket = data.get(day)
    if not isinstance(bucket, dict):  # 旧版按通道分桶的日汇总结构不同，今天重开一份
        bucket = _empty_bucket()
        data[day] = bucket
    bucket["cards"] = int(bucket.get("cards", 0) or 0) + 1
    bucket["cells"] = int(bucket.get("cells", 0) or 0) + int(result.get("cells", 0) or 0)
    bucket["cost"] = int(bucket.get("cost", 0) or 0) + int(result.get("cost", 0) or 0)
    bucket["payout"] = int(bucket.get("payout", 0) or 0) + int(result.get("payout", 0) or 0)
    bucket["net"] = int(bucket.get("net", 0) or 0) + int(result.get("net", 0) or 0)
    bucket[outcome] = int(bucket.get(outcome, 0) or 0) + 1
    _stats_save(ctx, data)
    ctx.log.info(
        "📊 刮奖记账 卡#%s %d格 派奖%d 成本%d 净%+d｜当日 %d张 累计净%+d",
        result.get("card_id"), int(result.get("cells", 0) or 0), int(result.get("payout", 0) or 0),
        int(result.get("cost", 0) or 0), int(result.get("net", 0) or 0), bucket["cards"], bucket["net"],
    )


def report_text(day: str, bucket: dict, history: dict, trend_days: int = 7) -> str:
    """刮奖收支日报：只记刮奖本身的派奖/成本/净额（账号级总额不记账）。"""
    bucket = bucket if isinstance(bucket, dict) else _empty_bucket()
    cards = int(bucket.get("cards", 0) or 0)
    lines = [f"📊 天空刮奖 · 刮奖收支日报（{day}）", "", "门户刮刮乐（兜底时段）"]
    lines.append(f"  {cards} 张 · 刮 {int(bucket.get('cells', 0) or 0)} 格")
    lines.append(
        f"  派奖 {int(bucket.get('payout', 0) or 0)} / 成本 {int(bucket.get('cost', 0) or 0)}"
        f" → 净 {int(bucket.get('net', 0) or 0):+d} 银元"
    )
    lines.append(f"  回本 {int(bucket.get('breakeven', 0) or 0)} 张 · 亏损 {int(bucket.get('loss', 0) or 0)} 张")
    if not cards:
        lines.append("  （当日无卡片结算）")
    days = [k for k in history if str(k) <= day and isinstance(history.get(k), dict)]
    recent = sorted(days)[-max(1, min(trend_days, 14)):]
    if len(recent) > 1:
        lines.append("")
        lines.append("近几日刮奖净额")
        for key in recent:
            row = history.get(key) or _empty_bucket()
            lines.append(f"  {key}: {int(row.get('cards', 0) or 0)} 张 → 净 {int(row.get('net', 0) or 0):+d}")
    return "\n".join(lines)


def _stats_prune(ctx: object, days: int) -> None:
    """裁剪逐张流水到最近 days 天，并同步清掉超期的日汇总。"""
    keep = max(1, int(days or 90))
    cutoff = _day_key(time.time() - keep * 86400)
    path = _stats_path(ctx, _LEDGER_FILE)
    kept: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except ValueError:
                    continue
                if str(row.get("date", "")) >= cutoff:
                    kept.append(text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(kept) + ("\n" if kept else ""))
    except OSError as exc:
        ctx.log.warning("刮奖收益流水裁剪失败: %s", exc)
        return
    data = _stats_load(ctx)
    trimmed = {k: v for k, v in data.items() if k >= cutoff}
    if len(trimmed) != len(data):
        _stats_save(ctx, trimmed)
    ctx.log.info("📊 刮奖流水已裁剪至 %d 天（保留 %d 行）", keep, len(kept))


# ── 连亏停刮 ─────────────────────────────────────────────────────────


async def apply_loss_streak(ctx: object, cfg: dict, net: int) -> None:
    """净亏累加、回本清零；达上限只停当天（次日自动恢复，不必重启插件）。"""
    loss = 0 if net >= 0 else int(ctx.kv.get(_KV_LOSS, 0) or 0) + 1
    if loss < _max_loss(cfg):
        ctx.kv.set(_KV_LOSS, loss)
        if loss:
            ctx.log.info("📉 刮奖连续亏损 %d 张", loss)
        return
    day = _cn_now().strftime("%Y-%m-%d")
    ctx.kv.set(_KV_HALT_DAY, day)
    ctx.kv.set(_KV_LOSS, 0)
    ctx.log.warning("🛑 刮奖连续亏损 %d 张，%s 停刮（次日自动恢复）", loss, day)
    try:
        await ctx.notify(
            f"🛑 天空刮奖今日停刮\n\n连续亏损 {loss} 张（上限 {_max_loss(cfg)}），次日自动恢复；"
            "想现在就继续，调大「连亏自动停止上限」并等下个整点时段",
            level="warning",
            category="刮奖",
        )
    except Exception as exc:  # noqa: BLE001 - 推送失败不影响停刮判定
        ctx.log.warning("刮奖停刮通知发送失败（渠道暂不可用）: %r", exc)


# ── 调度 ─────────────────────────────────────────────────────────────


async def _open_client(ctx: object, cfg: dict) -> HdskyClient:
    client = HdskyClient(log=ctx.log, cookie_provider=lambda: hdsky_auth.cookie_provider(ctx))
    if cfg.get("auth_auto_renew", True):
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
    client.configure(
        str(cfg.get("hdsky_cookie_file", "") or ""),
        str(cfg.get("hdsky_base_url", "") or ""),
        debug_enabled=bool(cfg.get("hdsky_debug", False)),
        debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
        proxy=resolve_proxy(ctx, cfg),
    )
    return client


def _skip_log(ctx: object, reason: str) -> None:
    """「本轮为何不刮」限流提示（每 10 分钟最多一条），窗口内静默跳过会让人以为没生效。"""
    global _last_skip_log
    now = time.time()
    if now - _last_skip_log < _SKIP_LOG_GAP:
        return
    _last_skip_log = now
    ctx.log.info("刮奖兜底：%s", reason)


async def fallback_tick(ctx: object) -> None:
    """每 60 秒一次：只在兜底窗口内、且本时段游戏剩余 > 0 时刮一张。"""
    global _playing
    cfg = ctx.config
    if not _enabled(cfg):
        return
    now = datetime.datetime.now()
    if not _in_window(cfg, now):
        return
    if halted_today(ctx.kv, _day_key(now.timestamp())):
        _skip_log(ctx, "今日已连亏停刮，跳过")
        return
    remaining = drop_guard.remaining(ctx)
    if remaining is None:
        # 数字不可用（没查过/跨整点/过期）：去要一次 /info，本轮不空刮。
        # 按 10 分钟节流（正好覆盖一个兜底窗口）：bot 不回话时不至于每分钟私聊刷屏。
        _skip_log(ctx, "本时段剩余掉落未知，已催 /info，本轮不刮")
        await drop_guard.refresh(ctx, min_interval=_INFO_RETRY_GAP)
        return
    if remaining <= 0:
        _skip_log(ctx, "本时段游戏剩余 0，掉落已领完，等整点刷新")
        return
    if _playing:
        ctx.log.info("刮奖：上一张还没刮完，跳过本轮")
        return
    _playing = True
    try:
        async with await _open_client(ctx, cfg) as client:
            result = await scratch_once(ctx, cfg, client)
    finally:
        _playing = False
    if not result:
        return
    record_card(ctx, cfg, result)
    await apply_loss_streak(ctx, cfg, int(result["net"]))
    # 刮完及时刷新游戏剩余：下一轮按新数字决定继续刮还是收手（不等 cron 的 */N 周期）
    await drop_guard.refresh(ctx)


async def report_tick(ctx: object) -> None:
    """收支日报：cron 每小时的第 N 分触发，只有北京时间的日报整点才真发。

    容器时区不可信（平台宿主可能是 UTC），所以不用 hour= 换算，按北京小时自判。
    """
    cfg = ctx.config
    if not _stats_enabled(cfg) or _cn_now().hour != _report_hour(cfg):
        return
    day = _day_key()
    if str(ctx.kv.get(_KV_REPORT_DAY, "") or "") == day:
        return
    data = _stats_load(ctx)
    bucket = data.get(day)
    text = report_text(day, bucket if isinstance(bucket, dict) else _empty_bucket(), data)
    ctx.kv.set(_KV_REPORT_DAY, day)
    ctx.log.info("📊 刮奖日报 %s", text.replace("\n", " ｜ ")[:600])
    try:
        await ctx.notify(text, level="info", category="刮奖")
    except Exception as exc:  # noqa: BLE001 - 推送失败不影响统计
        ctx.log.warning("刮奖日报推送失败: %r", exc)
    try:
        _stats_prune(ctx, int(cfg.get("scratch_stats_retention_days", 90) or 90))
    except Exception as exc:  # noqa: BLE001 - 裁剪失败不影响刮奖
        ctx.log.warning("刮奖流水裁剪异常: %r", exc)


def start(ctx: object) -> None:
    """注册兜底 tick（60 秒）与收支日报（cron 分钟位对齐）。"""
    cfg = ctx.config
    if not _enabled(cfg):
        ctx.log.info("刮奖兜底未启用")
        return
    if not callable(getattr(ctx, "schedule", None)):
        ctx.log.warning("平台无 ctx.schedule，刮奖兜底与日报均不启动")
        return

    async def _tick() -> None:
        try:
            await fallback_tick(ctx)
        except Exception as exc:  # noqa: BLE001 - 单轮异常不拖垮调度
            ctx.log.error("刮奖兜底 tick 异常: %r", exc)

    async def _report() -> None:
        try:
            await report_tick(ctx)
        except Exception as exc:  # noqa: BLE001 - 日报异常不拖垮调度
            ctx.log.error("刮奖日报 tick 异常: %r", exc)

    ctx.schedule(_tick, "interval", seconds=_TICK_SECONDS, id="scratch_fallback")
    if _stats_enabled(cfg):
        ctx.schedule(_report, "cron", minute=_report_minute(cfg), id="scratch_report")
    ctx.log.info(
        "刮奖兜底已启动（每小时 %d 分起，游戏剩余 >0 就用门户刮刮乐刮到归零，每张刮完催一次 /info）",
        _fallback_minute(cfg),
    )


def stop(ctx: object) -> None:
    """schedule 由平台在卸载时自动清理，无需额外动作。"""
