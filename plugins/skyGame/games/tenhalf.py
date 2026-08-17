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
#   推送策略：每局只在报名成功与结算时各推一次，要牌/停牌过程不推送（只记日志）
#   player_draw 且轮到我方（已报名、未出局）：
#     庄家爆牌 → 停牌（未爆即赢）
#     庄家当前点数可见 → 领先即停牌；落后仅在反败牌数 > 爆牌数时要牌
#     否则按停牌阈值：点数 ≥ 阈值停牌，否则要牌
#   fold（认输）从不使用：认输与停牌同样损失下注，无收益。
#
# 庄家画像：按庄家名统计结算点数/爆牌率（kv 持久化），并按庄家终局手牌张数分桶
# （结算只有点数没有张数，张数靠轮询观察 players[].cardCount 按 roundId 暂存配对）。
# 停牌阈值优先用「当前庄家张数」对应分桶（样本≥3），其次聚合画像（样本≥8）——
# 平局算输，目标需压过庄家均点；庄家爆率高则低点数即可停牌（赌庄家爆）。
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
# 庄家手牌张数暂存：结算里只有点数没有张数，轮询时按 roundId 记观察到的最大张数，
# 结算时配对计入「按张数分桶」的画像（只增不减，最大值即终局张数）。
_DEALER_CARDS_KEY = "tenhalf:dealer_cards"
_CARDS_STASH_CAP = 30
# 庄家画像样本门槛：不足不采信，直接用配置阈值（按张数桶样本更稀，门槛放低）
_MIN_DEALER_SAMPLES = 8
_MIN_CARD_SAMPLES = 3
_DEALER_TOTALS_CAP = 60
# 画像推导阈值的夹取范围：爆率再高也至少 4 点，不爆的庄家最多追到 10
_THRESHOLD_MIN = 4.0
_THRESHOLD_MAX = 10.0
# 爆率对阈值的让利系数：每 10% 爆率可少要 0.6 点（赌庄家爆）
_BUST_RATE_DISCOUNT = 6.0
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


def _record_dealer(ctx: object, settlement: dict, cards: int | None = None) -> str:
    """累计一条庄家结算（局数/爆牌数/近期点数样本），返回庄家名。

    爆牌判定：文案含「爆」或点数 > 10.5（实测爆牌局的 handLabel 常不含「爆」字、
    直接显示超点点数，如「11点」），爆牌不入点数样本。

    传入 cards（本局庄家终局手牌张数）时，同步计入按张数分桶的画像。
    """
    name = str(settlement.get("dealerDisplayName") or settlement.get("dealer") or "").strip()
    if not name:
        return ""
    label = settlement.get("dealerHandLabel")
    total = _parse_total(label)
    bust = "爆" in str(label or "") or (total is not None and total > _TARGET)
    dealers = _load_json(ctx.kv, _DEALERS_KEY)
    entry = dealers.get(name) or {}
    entry["rounds"] = int(entry.get("rounds", 0) or 0) + 1
    if bust:
        entry["busts"] = int(entry.get("busts", 0) or 0) + 1
    elif total is not None:
        totals = list(entry.get("totals") or [])
        totals.append(total)
        entry["totals"] = totals[-_DEALER_TOTALS_CAP:]
    if isinstance(cards, int) and cards > 0:
        cards_map = dict(entry.get("cards") or {})
        bucket = dict(cards_map.get(str(cards)) or {})
        bucket["rounds"] = int(bucket.get("rounds", 0) or 0) + 1
        if bust:
            bucket["busts"] = int(bucket.get("busts", 0) or 0) + 1
        elif total is not None:
            bt = list(bucket.get("totals") or [])
            bt.append(total)
            bucket["totals"] = bt[-_DEALER_TOTALS_CAP:]
        cards_map[str(cards)] = bucket
        entry["cards"] = cards_map
    dealers[name] = entry
    ctx.kv.set(_DEALERS_KEY, json.dumps(dealers, ensure_ascii=False))
    return name


def _observe_dealer_cards(ctx: object, rid: object, dealer_p: dict | None) -> None:
    """轮询中观察庄家手牌张数，按 roundId 取最大值暂存（只增不减，即终局张数）。"""
    if rid in (None, "") or not dealer_p:
        return
    cc = dealer_p.get("cardCount")
    if not isinstance(cc, (int, float)) or isinstance(cc, bool) or cc <= 0:
        return
    stash = _load_json(ctx.kv, _DEALER_CARDS_KEY)
    key = str(rid)
    prev = stash.get(key)
    if not isinstance(prev, (int, float)) or cc > prev:
        stash[key] = int(cc)
        if len(stash) > _CARDS_STASH_CAP:  # 防未结算局堆积，按插入顺序裁掉最旧
            for k in list(stash)[: len(stash) - _CARDS_STASH_CAP]:
                stash.pop(k, None)
        ctx.kv.set(_DEALER_CARDS_KEY, json.dumps(stash, ensure_ascii=False))


def _pop_dealer_cards(ctx: object, rid: object) -> int | None:
    """取出并移除某局暂存的庄家终局张数；未观察到返回 None。"""
    if rid in (None, ""):
        return None
    stash = _load_json(ctx.kv, _DEALER_CARDS_KEY)
    cc = stash.pop(str(rid), None)
    ctx.kv.set(_DEALER_CARDS_KEY, json.dumps(stash, ensure_ascii=False))
    if isinstance(cc, (int, float)) and not isinstance(cc, bool) and cc > 0:
        return int(cc)
    return None


def _dealer_effective(entry: dict) -> tuple[int, int, list[float]]:
    """清洗后的庄家统计 (局数, 爆牌数, 点数样本)。

    兼容旧版写入的脏数据：点数 > 10.5 的样本必是爆牌（当时爆牌局被误当高点点数），
    读出时改计爆牌并从均点样本剔除，避免均点虚高把阈值顶到上限。
    """
    rounds = int(entry.get("rounds", 0) or 0)
    busts = int(entry.get("busts", 0) or 0)
    totals: list[float] = []
    for v in entry.get("totals") or []:
        try:
            t = float(v)
        except (TypeError, ValueError):
            continue
        if t > _TARGET:
            busts += 1
        else:
            totals.append(t)
    return rounds, busts, totals


def _threshold_from_stats(rounds: int, busts: int, totals: list[float], min_samples: int) -> float | None:
    """由 (局数/爆牌数/点数样本) 推导停牌阈值；样本不足或无点数样本返回 None。

    平局算输：目标需压过庄家均点（+0.5）；爆率高则按比例降低点数要求。
    """
    if rounds < min_samples or not totals:
        return None
    avg = sum(totals) / len(totals)
    bust_rate = busts / rounds
    threshold = avg + 0.5 - bust_rate * _BUST_RATE_DISCOUNT
    return max(_THRESHOLD_MIN, min(_THRESHOLD_MAX, round(threshold * 2) / 2))


def _threshold_for(cfg: dict, dealers: dict, dealer_name: str, dealer_cards: int | None = None) -> float:
    """停牌阈值：优先用「当前庄家手牌张数」对应分桶的画像，其次聚合画像，都不够退配置基准。

    平局算输、爆率高可低停（赌庄家爆）的推导见 _threshold_from_stats。
    """
    base = float(cfg.get("tenhalf_stand_threshold", 8) or 8)
    entry = dealers.get(dealer_name) or {}
    if isinstance(dealer_cards, int) and dealer_cards > 0:
        bucket = (entry.get("cards") or {}).get(str(dealer_cards)) or {}
        r, b, t = _dealer_effective(bucket)
        v = _threshold_from_stats(r, b, t, _MIN_CARD_SAMPLES)
        if v is not None:
            return v
    r, b, t = _dealer_effective(entry)
    v = _threshold_from_stats(r, b, t, _MIN_DEALER_SAMPLES)
    return base if v is None else v


def _dealer_profile_text(dealers: dict, name: str, cards: int | None = None) -> str:
    entry = dealers.get(name) or {}
    rounds, busts, totals = _dealer_effective(entry)
    if not rounds:
        return ""
    parts = [f"{rounds}局"]
    if totals:
        parts.append(f"均 {sum(totals) / len(totals):.1f} 点")
    if busts:
        parts.append(f"爆率 {busts / rounds:.0%}")
    text = "·".join(parts)
    if isinstance(cards, int) and cards > 0:
        bucket = (entry.get("cards") or {}).get(str(cards)) or {}
        br, bb, _bt = _dealer_effective(bucket)
        if br:
            text += f"｜{cards}张 {br}局爆率 {bb / br:.0%}"
    return text


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
    dealer_cards = _pop_dealer_cards(ctx, rid)
    dealer_name = _record_dealer(ctx, settlement, cards=dealer_cards)
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
        profile = _dealer_profile_text(_load_json(ctx.kv, _DEALERS_KEY), dealer_name, dealer_cards)
        rows.append(["庄家", f"{dealer_name}（{profile}）" if profile else dealer_name])
    if me.get("handLabel"):
        rows.append(["我方牌面", str(me.get("handLabel"))])
    if me.get("resultText"):
        rows.append(["结果", str(me.get("resultText"))])
    rows.append(["盈亏", f"{'+' if delta >= 0 else ''}{delta:,} 银元"])
    rows.append(["📊 累计", _stats_text(total)])
    rows.append(["📅 今日", _stats_text(daily)])
    caption = f"🎲 十点半 #{rid} 结算 {'+' if delta >= 0 else ''}{delta:,} 银元"
    # 输赢都走 success：正常结算不算异常，不用 warning 刷屏
    await ctx.notify_table(["项目", "内容"], rows, caption=caption, level="success", category="十点半")


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


async def _submit_action(ctx: object, client: HdskyClient, game: dict, action: str, reason: str, total: float) -> None:
    """提交要牌/停牌。同局同点数同动作去重；过程不推送，每局只在结算时推一次。"""
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
    # 观察庄家手牌张数（按 roundId 取最大值暂存，供结算时配对计入按张数分桶的画像）
    _observe_dealer_cards(ctx, rid, dealer_p)

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
    raw_dealer_cards = (dealer_p or {}).get("cardCount")
    dealer_cards_now = (
        int(raw_dealer_cards)
        if isinstance(raw_dealer_cards, (int, float))
        and not isinstance(raw_dealer_cards, bool)
        and raw_dealer_cards > 0
        else None
    )
    dealer_bust = bool((dealer_p or {}).get("bust"))
    raw_dealer_total = (dealer_p or {}).get("total")
    if isinstance(raw_dealer_total, (int, float)):
        dealer_total: float | None = float(raw_dealer_total)
    else:
        m = _POINT_RE.search(str((dealer_p or {}).get("status") or ""))
        dealer_total = float(m.group(1)) if m else None
    threshold = _threshold_for(cfg, dealers, dealer_name, dealer_cards=dealer_cards_now)
    action, reason = _decide(total, actions, dealer_bust, dealer_total, threshold)
    if action is None:
        ctx.log.debug("十点半 #%s 本轮不动作: %s", rid, reason)
        return
    await _submit_action(ctx, client, game, action, reason, total)


def start(ctx: object) -> None:
    """注册十点半轮询调度。间隔取启动时配置，改动后重载生效。

    平台对 ctx.schedule 回调是**零参调用**（参考 skyDropAnswer/trigger.py），
    ctx 经闭包捕获；带参签名会每 5 秒 TypeError 一次并触发调度降级。
    """
    cfg = ctx.config
    interval = float(cfg.get("tenhalf_poll_interval", 5) or 5)

    async def _tick() -> None:
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

    ctx.schedule(_tick, "interval", seconds=interval, id="tenhalf_poll")
    ctx.log.info("十点半已启动（每 %.0f 秒轮询）", interval)


def stop(ctx: object) -> None:
    """停止十点半：ctx.schedule 注册的调度由平台自动清理。"""
    ctx.log.info("十点半已停止")
