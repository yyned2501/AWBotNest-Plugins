# -*- coding: utf-8 -*-
# 天空游戏 · 十点半：hdsky 门户十点半自动参与
#
# 契约来源：GET /api/portal/tenhalf 实测（2026-08-17）；POST /api/portal/tenhalf/action
# 来自门户前端 portal-games.js（v20260806-19）源码，尚未实测——因此所有响应都防御性解析、
# 失败收敛为日志 + 一次性通知，可配合全局设置的门户调试记录（hdsky_debug）核对实际请求。
#
# 牌局流程：signup(报名下注) → dealer_draw(庄家抓牌) → player_draw(玩家抓牌) → settled
# 规则：目标 10.5 点，超点爆牌，点数大于庄家即赢、赢面扣 1% 抽水；
# 开庄需备本局上限 10 倍本金，插件只玩玩家位、不开庄。
#
# 每轮轮询决策链：
#   lastResult 出现新局 → 结算入账：通知 + 累计/当日战绩 + 庄家画像（按 roundId 去重）
#   signup 且可加入 → 按配置下注额报名（夹在门户最小下注与单桌人均上限之间）
#   player_draw 且轮到我方（已报名、未出局）：
#     庄家爆牌 → 停牌（未爆即赢）
#     庄家当前点数可见 → 领先即停牌；落后仅在反败牌数 > 爆牌数时要牌
#     否则按停牌阈值：点数 ≥ 阈值停牌，否则要牌
#   fold（认输）从不使用：认输与停牌同样损失下注，无收益。
#
# 庄家画像：按庄家名统计结算点数/爆牌率（kv 持久化），样本 ≥ 8 时微调停牌阈值
# ±1.5（庄家均值高 → 阈值上调更激进），并在结算通知中展示画像。
#
# 牌堆先验（未实测，按十点半系惯例）：标准 52 张，A=1、2-10 按面值、J/Q/K=0.5（12 张），
# 仅用于爆牌概率与反败牌数估算，供决策与通知展示。

from __future__ import annotations

import datetime
import json
import re

from . import hdsky_auth
from .hdsky import HdskyClient, request_key

_TARGET = 10.5
_STATE_PATH = "/api/portal/tenhalf"
_ACTION_PATH = "/api/portal/tenhalf/action"

# 牌堆先验：J/Q/K=0.5 共 12 张，A-10 各 4 张
_DECK = [0.5] * 12 + [float(v) for v in range(1, 11) for _ in range(4)]

_STATS_KEY = "tenhalf:stats"
_DEALERS_KEY = "tenhalf:dealers"
_LAST_ROUND_KEY = "tenhalf:last_round"
_LAST_ACTION_KEY = "tenhalf:last_action"
_JOIN_FAIL_KEY = "tenhalf:join_fail_round"
# 庄家画像样本门槛：不足不采信，直接用配置阈值
_MIN_DEALER_SAMPLES = 8
_PRIOR_DEALER_AVG = 8.0
_DEALER_TOTALS_CAP = 60
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# 庄家状态文本只信「数字+点」形式（如「9.5点」），避免把无关数字误当点数
_POINT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*点")


def _bust_prob(total: float) -> float:
    """下一次要牌的爆牌概率（新牌堆先验）。"""
    safe = sum(1 for v in _DECK if total + v <= _TARGET)
    return 1 - safe / len(_DECK)


def _parse_total(text: object) -> float | None:
    """从 handLabel 等结算文本抠数字点数，解析不出返回 None。"""
    m = _NUMBER_RE.search(str(text or ""))
    return float(m.group(0)) if m else None


def _join_amount(cfg: dict, game: dict, limits: dict) -> int:
    """报名下注额：配置值夹在门户最小下注与本桌单人上限之间。"""
    bet = int(cfg.get("tenhalf_bet_amount", 100) or 100)
    lo = int(limits.get("minAmount", 100) or 100)
    hi = int(game.get("amount") or limits.get("maxAmount") or 10000)
    return max(lo, min(bet, hi))


def _decide(
    total: float,
    actions: list[str],
    dealer_bust: bool,
    dealer_total: float | None,
    threshold: float,
) -> tuple[str | None, str]:
    """要牌/停牌决策，返回 (action, reason)；action 为 None 表示本轮不动作。"""
    can_hit = "hit" in actions
    can_stand = "stand" in actions
    if not can_hit and not can_stand:
        return None, "门户未开放 hit/stand"
    if dealer_bust:
        if can_stand:
            return "stand", "庄家已爆牌，停牌即赢"
        return None, "庄家已爆牌但未开放停牌"
    if dealer_total is not None:
        if total > dealer_total:
            if can_stand:
                return "stand", f"点数 {total:g} 已超庄家 {dealer_total:g}"
            return None, "已领先庄家但未开放停牌"
        if can_hit:
            window = sum(1 for v in _DECK if dealer_total < total + v <= _TARGET)
            bust = sum(1 for v in _DECK if total + v > _TARGET)
            if window > bust:
                return "hit", f"落后庄家 {dealer_total:g}，反败牌数 {window} > 爆牌数 {bust}"
        if can_stand:
            return "stand", f"落后庄家 {dealer_total:g} 但要牌无反败优势，停牌"
        return None, "要牌无反败优势但未开放停牌"
    if total >= threshold:
        if can_stand:
            return "stand", f"点数 {total:g} ≥ 阈值 {threshold:g}，停牌（爆牌概率 {_bust_prob(total):.0%}）"
        return None, "达到阈值但未开放停牌"
    if not can_hit:
        if can_stand:
            return "stand", "未开放要牌，停牌"
        return None, "要牌/停牌均未开放"
    return "hit", f"点数 {total:g} < 阈值 {threshold:g}，爆牌概率 {_bust_prob(total):.0%}"


def _load_json(kv: object, key: str) -> dict:
    raw = kv.get(key, None)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _record_dealer(ctx: object, settlement: dict) -> str:
    """累计一条庄家结算（局数/爆牌数/近期点数样本），返回庄家名。"""
    name = str(settlement.get("dealerDisplayName") or settlement.get("dealer") or "").strip()
    if not name:
        return ""
    dealers = _load_json(ctx.kv, _DEALERS_KEY)
    entry = dealers.get(name) or {}
    entry["rounds"] = int(entry.get("rounds", 0) or 0) + 1
    label = settlement.get("dealerHandLabel")
    if "爆" in str(label or ""):
        entry["busts"] = int(entry.get("busts", 0) or 0) + 1
    else:
        total = _parse_total(label)
        if total is not None:
            totals = list(entry.get("totals") or [])
            totals.append(total)
            entry["totals"] = totals[-_DEALER_TOTALS_CAP:]
    dealers[name] = entry
    ctx.kv.set(_DEALERS_KEY, json.dumps(dealers, ensure_ascii=False))
    return name


def _threshold_for(cfg: dict, dealers: dict, dealer_name: str) -> float:
    """停牌阈值 = 配置基准 ± 庄家画像微调（限幅 ±1.5，样本不足不采信）。"""
    base = float(cfg.get("tenhalf_stand_threshold", 8) or 8)
    entry = dealers.get(dealer_name) or {}
    totals = entry.get("totals") or []
    if len(totals) < _MIN_DEALER_SAMPLES:
        return base
    avg = sum(totals) / len(totals)
    adj = max(-1.5, min(1.5, avg - _PRIOR_DEALER_AVG))
    rounds = int(entry.get("rounds", 0) or 0)
    if rounds and int(entry.get("busts", 0) or 0) / rounds >= 0.4:
        adj -= 0.5  # 高爆牌率庄家无需高点数即可赢，阈值下调更稳
    return max(5.0, min(10.0, round((base + adj) * 2) / 2))


def _dealer_profile_text(dealers: dict, name: str) -> str:
    entry = dealers.get(name) or {}
    rounds = int(entry.get("rounds", 0) or 0)
    if not rounds:
        return ""
    parts = [f"{rounds}局"]
    totals = entry.get("totals") or []
    if totals:
        parts.append(f"均 {sum(totals) / len(totals):.1f} 点")
    busts = int(entry.get("busts", 0) or 0)
    if busts:
        parts.append(f"爆率 {busts / rounds:.0%}")
    return "·".join(parts)


def _bump(bucket: dict, delta: int) -> None:
    bucket["rounds"] = int(bucket.get("rounds", 0) or 0) + 1
    bucket["net"] = int(bucket.get("net", 0) or 0) + delta
    bucket["wins"] = int(bucket.get("wins", 0) or 0) + (1 if delta > 0 else 0)
    bucket["losses"] = int(bucket.get("losses", 0) or 0) + (1 if delta < 0 else 0)


def _stats_text(bucket: dict) -> str:
    rounds = int(bucket.get("rounds", 0) or 0)
    wins = int(bucket.get("wins", 0) or 0)
    losses = int(bucket.get("losses", 0) or 0)
    net = int(bucket.get("net", 0) or 0)
    return f"{rounds}局 {wins}胜/{losses}负 {'+' if net >= 0 else ''}{net:,}"


def _update_stats(ctx: object, delta: int) -> tuple[dict, dict]:
    """入账一局战绩（累计 + 当日，跨天重置当日），返回两份统计。"""
    stats = _load_json(ctx.kv, _STATS_KEY)
    total = dict(stats.get("total") or {})
    daily = dict(stats.get("daily") or {})
    today = datetime.date.today().isoformat()
    if daily.get("date") != today:
        daily = {"date": today}
    _bump(total, delta)
    _bump(daily, delta)
    ctx.kv.set(_STATS_KEY, json.dumps({"total": total, "daily": daily}, ensure_ascii=False))
    return total, daily


async def _handle_settlement(ctx: object, cfg: dict, game: dict) -> None:
    """lastResult 每局只处理一次：记庄家画像；我方参局才入账战绩并推送。"""
    last = game.get("lastResult") or {}
    rid = last.get("roundId")
    if rid in (None, "") or str(ctx.kv.get(_LAST_ROUND_KEY, "")) == str(rid):
        return
    ctx.kv.set(_LAST_ROUND_KEY, str(rid))
    settlement = last.get("settlement") or {}
    dealer_name = _record_dealer(ctx, settlement)
    me = settlement.get("self") or {}
    if not me:
        return  # 本局未参与：只记庄家画像
    delta = int(me.get("delta", 0) or 0)
    total, daily = _update_stats(ctx, delta)
    ctx.log.info("十点半 #%s 结算 %+d 银元（%s）", rid, delta, me.get("resultText") or "")
    if not cfg.get("tenhalf_notify", True):
        return
    rows: list[list[object]] = []
    if dealer_name:
        profile = _dealer_profile_text(_load_json(ctx.kv, _DEALERS_KEY), dealer_name)
        rows.append(["庄家", f"{dealer_name}（{profile}）" if profile else dealer_name])
    if me.get("handLabel"):
        rows.append(["我方牌面", str(me.get("handLabel"))])
    if me.get("resultText"):
        rows.append(["结果", str(me.get("resultText"))])
    rows.append(["盈亏", f"{'+' if delta >= 0 else ''}{delta:,} 银元"])
    rows.append(["📊 累计", _stats_text(total)])
    rows.append(["📅 今日", _stats_text(daily)])
    caption = f"🎲 十点半 #{rid} 结算 {'+' if delta >= 0 else ''}{delta:,} 银元"
    await ctx.notify_table(
        ["项目", "内容"], rows, caption=caption, level="success" if delta >= 0 else "warning", category="十点半"
    )


async def _try_join(ctx: object, cfg: dict, client: HdskyClient, game: dict, limits: dict) -> None:
    """报名下注。失败后本局不再重试（避免每轮轮询撞同一个拒绝）。"""
    rid = game.get("roundId")
    amount = _join_amount(cfg, game, limits)
    r = await client.post(_ACTION_PATH, {"action": "join", "amount": amount, "requestKey": request_key()})
    result = r.get("result", {}) or {}
    if result.get("ok", r.get("ok", False)):
        ctx.log.info("加入十点半 #%s（下注 %s，单桌上限 %s）", rid, amount, game.get("amount"))
        if cfg.get("tenhalf_notify", True):
            await ctx.notify(
                f"🎲 加入十点半 #{rid}，下注 {amount:,} 银元（单桌上限 {game.get('amount')}）", category="十点半"
            )
        return
    ctx.kv.set(_JOIN_FAIL_KEY, str(rid))
    msg = result.get("message") or r.get("error") or "未知"
    ctx.log.warning("十点半报名失败 #%s: %s", rid, msg)
    if cfg.get("tenhalf_notify", True):
        await ctx.notify(f"🎲 十点半报名失败: {msg}", level="warning", category="十点半")


async def _submit_action(
    ctx: object, cfg: dict, client: HdskyClient, game: dict, action: str, reason: str, total: float
) -> None:
    """提交要牌/停牌。同局同点数同动作去重，避免响应未更新前重复提交。"""
    rid = game.get("roundId")
    sig = f"{rid}:{action}:{total:g}"
    if ctx.kv.get(_LAST_ACTION_KEY, "") == sig:
        ctx.log.debug("十点半决策未变化（%s），不重复提交", sig)
        return
    r = await client.post(_ACTION_PATH, {"action": action, "requestKey": request_key()})
    result = r.get("result", {}) or {}
    if not result.get("ok", r.get("ok", False)):
        msg = result.get("message") or r.get("error") or "未知"
        ctx.log.warning("十点半 %s 失败 #%s: %s", action, rid, msg)
        return
    ctx.kv.set(_LAST_ACTION_KEY, sig)
    label = "要牌" if action == "hit" else "停牌"
    ctx.log.info("十点半 #%s %s（点数 %g，%s）", rid, label, total, reason)
    if cfg.get("tenhalf_notify", True):
        await ctx.notify(f"🎲 十点半 #{rid} {label}：点数 {total:g}，{reason}", category="十点半")


async def _once(ctx: object, cfg: dict, client: HdskyClient) -> None:
    """单次轮询：先消化上一局结算，再按当前阶段做一个动作。"""
    data = await client.get(_STATE_PATH)
    if "_error" in data:
        ctx.log.warning("十点半状态请求失败: %s", data["_error"] or "未知网络错误")
        client.reset_csrf()
        return
    game = data.get("game") or {}
    await _handle_settlement(ctx, cfg, game)
    if not game.get("active"):
        return

    phase = game.get("phase")
    actions = game.get("actions") or []
    players = game.get("players") or []
    limits = game.get("limits") or {}
    self_p = next((p for p in players if isinstance(p, dict) and p.get("isSelf")), None)
    dealer_p = next((p for p in players if isinstance(p, dict) and p.get("dealer")), None)
    rid = game.get("roundId")

    # 报名阶段：未报名且可加入 → 按配置下注
    if phase == "signup":
        if self_p is not None or "join" not in actions:
            return
        if ctx.kv.get(_JOIN_FAIL_KEY, "") == str(rid):
            ctx.log.debug("十点半 #%s 本局报名失败过，不再重试", rid)
            return
        await _try_join(ctx, cfg, client, game, limits)
        return

    # 玩家抓牌阶段：已报名且未出局才决策
    if phase != "player_draw" or self_p is None or self_p.get("folded") or self_p.get("bust"):
        return
    self_info = game.get("self") or {}
    if self_info.get("total") in (None, ""):
        ctx.log.debug("十点半 #%s 读不到我方点数，跳过本轮", rid)
        return
    total = float(self_info.get("total") or 0)
    dealers = _load_json(ctx.kv, _DEALERS_KEY)
    dealer_name = str((dealer_p or {}).get("displayName") or "")
    dealer_bust = bool((dealer_p or {}).get("bust"))
    raw_dealer_total = (dealer_p or {}).get("total")
    if isinstance(raw_dealer_total, (int, float)):
        dealer_total: float | None = float(raw_dealer_total)
    else:
        m = _POINT_RE.search(str((dealer_p or {}).get("status") or ""))
        dealer_total = float(m.group(1)) if m else None
    threshold = _threshold_for(cfg, dealers, dealer_name)
    action, reason = _decide(total, actions, dealer_bust, dealer_total, threshold)
    if action is None:
        ctx.log.debug("十点半 #%s 本轮不动作: %s", rid, reason)
        return
    await _submit_action(ctx, cfg, client, game, action, reason, total)


async def _tick(ctx: object) -> None:
    """单次调度 tick：未启用直接返回；启用则开客户端跑一轮（有限工作）。

    常驻轮询走 ctx.schedule（平台统一治理：停用/重载自动取消跟踪），
    不用裸 asyncio.create_task 无限循环——SPEC 硬规则，也避免重载后残留双份轮询。
    """
    cfg = ctx.config
    if not cfg.get("tenhalf_enabled", False):
        return
    try:
        async with HdskyClient(log=ctx.log) as client:
            client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
            client.configure(
                str(cfg.get("hdsky_cookie_file", "") or ""),
                str(cfg.get("hdsky_base_url", "") or ""),
                debug_enabled=bool(cfg.get("hdsky_debug", False)),
                debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
            )
            await _once(ctx, cfg, client)
    except Exception as e:
        ctx.log.error("十点半轮询异常: %r", e)
        if cfg.get("tenhalf_notify", True):
            await ctx.notify(f"🎲 十点半轮询异常: {e}", level="warning")


def start(ctx: object) -> None:
    """注册十点半轮询调度。间隔取启动时配置，改动后重载生效。"""
    cfg = ctx.config
    interval = float(cfg.get("tenhalf_poll_interval", 5) or 5)
    ctx.schedule(_tick, "interval", seconds=interval, id="tenhalf_poll")
    ctx.log.info("十点半已启动（每 %.0f 秒轮询）", interval)


def stop(ctx: object) -> None:
    """停止十点半：ctx.schedule 注册的调度由平台自动清理。"""
    ctx.log.info("十点半已停止")
