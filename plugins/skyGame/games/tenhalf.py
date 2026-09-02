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
# 倍数机制（2026-08-18 实测）：结算文案带 ×N 倍数（如「下注 100 ×5」）——
# 「玩家/庄家 5 小」（5 张不爆）×5 坐实；爆牌/输局也出现过 ×2/×5，
# 推测倍数由手牌张数成就驱动且全桌适用（具体规则待更多样本确认）。
# 倍数放大了爆牌代价：线上输局 61% 是爆牌，其中五小倍数局一次输 5 倍下注。
#
# 每轮轮询决策链：
#   lastResult 出现新局 → 结算入账：通知 + 累计/当日战绩 + 庄家画像（按 roundId 去重）
#   signup 且可加入 → 按配置下注额报名（夹在门户最小下注与单桌人均上限之间）
# 推送策略：每局只在报名成功与结算时各推一次，要牌/停牌过程不推送（只记日志）
#   结算后若有本局决策轨迹，用平台 AI 在群聊总结「心路历程」（v1.23.15 起、v1.23.16 抽成
#   games/ai_review.py 通用模块）：赢了炫决策、输了吐槽庄家运气好（带庄家简称）；
#   prompt 只喂动作序列与输赢，绝不含 EV 数值；平台无 AI/失败静默跳过，不阻塞结算
#   player_draw 且轮到我方（已报名、未出局）：
#     庄家已爆（total>10.5 实锤；bust 字段轮询时不可见，v1.23.13）→ 停牌即赢
#     庄家点数可见 → 点质量分布进 EV；庄家 5 张 → 画像 EV 递推 + 首手认输门控
#     （v1.23.14：认输只在首手 0 张可选，停牌 EV ≤ -1 才认输止损；要牌奖惩按
#     条件分布加权：庄家五小必输×5——爆损 5-4p、五小互碰也输得 10p-5）
#     庄家画像样本足够 → EV 决策：停牌 EV（画像点数分布 + 爆率）对比要牌 EV
#     （52 张先验递推，含五小 ×5 收益与爆牌损失），择优（v1.21.0）——
#     全程 EV 决策，不再用点数阈值停牌（v1.23.7）；4 张时差一张成五小，
#     EV 递推自然包含（如 8.5 点 4 张：1/2/JQK 共 20 张可成五小 ×5）
#     画像不足 → 退 v1.20.0 阈值逻辑（画像推导阈值受爆牌红线 6.5 夹取）
#   fold（认输）是庄家 5 张时的止损通道（v1.23.14 用户实测）：只在首手（我方 0 张
#   未拿牌）可选——拿了牌就只有拿牌/停牌；停牌 EV ≤ -1（不优于认输 -1）才认输，
#   否则在拿牌/停牌间择优。
#   庄家 5 张≠五小已定（v1.23.13）：他可能继续补牌爆掉，停牌 EV 按「5张」桶条件分布
#   （爆×+0.99/五小×-5）算，五小概率大（爆率≤3/10）时停牌 EV ≤ -1 即首手认输止损
#   每次提交的动作记入本局决策轨迹（点数/手牌/拿牌EV/停牌EV/认输EV），结算推送时
#   每条决策单独一行展示（半角括号，动作在首；v1.23.7）
#
# 庄家画像：按庄家名统计结算点数/爆牌率（kv 持久化），并按庄家终局手牌张数分桶
# （结算只有点数没有张数，张数靠轮询观察 players[].cardCount 按 roundId 暂存配对）。
# 停牌阈值优先用「当前庄家张数」对应分桶（样本≥3），其次聚合画像（样本≥8）——
# 平局算输，目标需压过庄家均点；庄家爆率高则低点数即可停牌（赌庄家爆）。
# 点数分布用全量计数归档（v1.23.20，每档点数一个计数，体积恒定）：修复旧版
# 「最近 60 条样本窗口 vs 全量局数」导致明细与总局数对不上；无牌面详情的局计
# 「未详」，展示恒等：局数 = 爆数 + Σ点数 + 未详。
# v1.20.0 起画像阈值夹在 4～6.5（爆牌红线）：追庄家均点到 7+ 的爆牌代价
# （>50% 爆率 × 倍数惩罚）大于压点收益，早停赌庄家自爆期望更优。
#
# 牌堆先验（未实测，按十点半系惯例）：标准 52 张，A=1、2-10 按面值、J/Q/K=0.5（12 张），
# 仅用于爆牌概率与反败牌数估算，供决策与通知展示。

from __future__ import annotations

import datetime
import json
import re

from . import ai_review, drop_guard, hdsky_auth
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
# 最近一次报名成功的局号：停牌后若活跃局已翻篇而结算没被 lastResult 抓到
# （快速局 settled 窗口短于轮询间隔），按它去 history[] 补扫结算。
_JOINED_ROUND_KEY = "tenhalf:joined_round"
# history 补扫只看最近几条（漏掉的总是紧邻的上一局，不用全量扫）
_HISTORY_SCAN_CAP = 10
# 庄家手牌张数暂存：结算里只有点数没有张数，轮询时按 roundId 记观察到的最大张数，
# 结算时配对计入「按张数分桶」的画像（只增不减，最大值即终局张数）。
_DEALER_CARDS_KEY = "tenhalf:dealer_cards"
_CARDS_STASH_CAP = 30
# 本局决策轨迹暂存：每次要牌/停牌/认输提交成功后记一条（点数/手牌/动作/拿牌EV/停牌EV/认输EV），
# 结算推送时拼进表格（过程不推送，每局只在结算时推一次）。
_DECISION_LOG_KEY = "tenhalf:decision_log"
_DECISION_LOG_CAP = 30
_ACTION_LABELS = {"hit": "要牌", "stand": "停牌", "fold": "认输"}
# 庄家画像样本门槛：不足不采信，退阈值/配置逻辑（按张数桶样本更稀，门槛放低）
_MIN_DEALER_SAMPLES = 8
_MIN_CARD_SAMPLES = 3
# v1.23.20：点数样本由「最近 60 条滑动窗口」改为全量计数（counts）——旧窗口与
# rounds 全量累计口径不一致（线上实例「144 局 vs 明细 60」）；旧 totals 数据在
# 画像下次写入时自动迁移为 counts（见 _counts_of）
# 五小（5 张不爆）直接赢，倍数 ×5（2026-08-18 实测坐实）；EV 递推的收益项
_FIVE_SMALL_MULT = 5.0
# 赢 1 单位下注的净收益 0.99（扣 1% 抽水，与线上「赢 +99」口径一致）
_WIN_NET = 0.99
# 画像推导阈值的夹取范围：爆率再高也至少 4 点；上限 6.5 是爆牌红线（v1.20.0）——
# 7 点要牌爆率 >50%，且线上 61% 输局是爆牌（含五小倍数放大），早停赌庄家自爆
# 的期望全面优于追高点数（模拟：高爆庄家阈值 6 EV +0.10 vs 阈值 8 -0.16）。
_THRESHOLD_MIN = 4.0
_THRESHOLD_MAX = 6.5
# 爆率对阈值的让利系数：每 10% 爆率可少要 0.4 点（赌庄家爆）；
# 爆率 ≥37.5% 时即压到红线下限 6.5（旧系数 6.0 在均值 9 的庄家上推出 9.5，追牌爆率 68%）
_BUST_RATE_DISCOUNT = 4.0
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# 庄家状态文本只信「数字+点」形式（如「9.5点」），避免把无关数字误当点数
_POINT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*点")


def _hand_text(cards: object) -> str:
    """手牌显示文本（如「6♣ 3♣」）；格式未知的牌面元素忽略，空手牌返回空串。"""
    if not isinstance(cards, list) or not cards:
        return ""
    parts = []
    for c in cards:
        if isinstance(c, str) and c.strip():
            parts.append(c.strip())
        elif isinstance(c, dict):
            v = c.get("value") or c.get("symbol") or c.get("card") or ""
            if isinstance(v, (str, int, float)) and str(v).strip():
                parts.append(str(v).strip())
    return " ".join(parts)


def _decide_text(
    total: float,
    cards: object,
    action: str | None,
    ev_hit: float | None,
    ev_stand: float | None,
    ev_fold: float | None = None,
) -> str:
    """一条决策轨迹文本：动作为首、点数与手牌居中、EV 对比收尾（半角括号）。

    庄家5张（v1.23.11 起）追加认输 EV 第三值，如「认输 0：拿牌ev(-435)>停牌ev(-81) 认输ev(-100)」。
    """
    label = _ACTION_LABELS.get(action or "", str(action or ""))
    head = f"{label} {total:g}"
    hand = _hand_text(cards)
    if hand:
        head += f"({hand})"
    if ev_hit is None or ev_stand is None:
        return head
    cmp = ">" if ev_hit > ev_stand else ("<" if ev_hit < ev_stand else "=")
    text = f"{head}：拿牌ev({ev_hit * 100:.0f}){cmp}停牌ev({ev_stand * 100:.0f})"
    if ev_fold is not None:
        text += f" 认输ev({ev_fold * 100:.0f})"
    return text


def _record_decision(
    ctx: object,
    rid: object,
    total: float,
    cards: object,
    action: str,
    ev_hit: float | None,
    ev_stand: float | None,
    ev_fold: float | None = None,
) -> None:
    """暂存一手决策轨迹；同局同点数同动作的重复提交由 _LAST_ACTION_KEY 去重挡住。"""
    if rid in (None, ""):
        return
    log = _load_json(ctx.kv, _DECISION_LOG_KEY)
    steps = list(log.get(str(rid)) or [])
    steps.append([total, _hand_text(cards), action, ev_hit, ev_stand, ev_fold])
    log[str(rid)] = steps
    if len(log) > _DECISION_LOG_CAP:  # 防未结算局堆积，按插入顺序裁掉最旧
        for k in list(log)[: len(log) - _DECISION_LOG_CAP]:
            log.pop(k, None)
    ctx.kv.set(_DECISION_LOG_KEY, json.dumps(log, ensure_ascii=False))


def _pop_decision_log(ctx: object, rid: object) -> list[list[object]]:
    """取出并移除某局暂存的决策轨迹；未记录返回空列表。"""
    if rid in (None, ""):
        return []
    log = _load_json(ctx.kv, _DECISION_LOG_KEY)
    steps = log.pop(str(rid), None)
    if steps is not None:
        ctx.kv.set(_DECISION_LOG_KEY, json.dumps(log, ensure_ascii=False))
    return list(steps) if isinstance(steps, list) else []


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


def _stand_ev(total: float, p_bust: float, samples: list[float]) -> float:
    """停牌 EV（单位下注）：庄家爆牌或点数低于我赢，同点庄家赢。"""
    if not samples:
        return 2.0 * p_bust - 1.0  # 只有爆率没有点数样本：爆即赢、否则输
    below = sum(1 for x in samples if x < total)
    p_win = p_bust + (1.0 - p_bust) * below / len(samples)
    return 2.0 * p_win - 1.0


def _five_stand_ev(
    five_small: bool, five_bust_p: float | None, total: float, p_bust: float, samples: list[float]
) -> float:
    """庄家 5 张时的停牌 EV（v1.23.13）：决策时庄家爆否不可知，与普通对局一样按
    「5张」桶条件分布赌：P(爆)×赢 +0.99 - P(五小)×输 -5；桶无样本才保守按五小
    定局 -5（此时认输 -1 兜底）；非五小场景回归 _stand_ev。"""
    if not five_small:
        return _stand_ev(total, p_bust, samples)
    if five_bust_p is not None:
        return _WIN_NET * five_bust_p - _FIVE_SMALL_MULT * (1.0 - five_bust_p)
    return -_FIVE_SMALL_MULT


def _ev_play(
    total: float,
    cards: int,
    p_bust: float,
    samples: list[float],
    memo: dict,
    five_small: bool = False,
    five_bust_p: float | None = None,
) -> float:
    """状态 (total, cards) 起最优打法的 EV（单位下注），memo 记忆化。

    状态空间小（点数为 0.5 的整数倍、张数 ≤5），递推即精确解，
    等价于无限次蒙特卡洛且零随机、可测试；要牌按 52 张先验逐张期望：
    一般场景爆牌 -1（玩家爆牌只输本金 ×1）、拿到第 5 张未爆 → 五小 +5，
    否则递推下一状态。
    five_small（庄家 5 张，v1.23.11）：停牌判负走 _five_stand_ev；要牌奖惩按
    「5张」桶条件分布加权（v1.23.14，用户实测）：庄家五小时不管拿什么都是输
    ×5（爆牌损失 5-4×five_bust_p、五小互碰也输 5 倍得 10×five_bust_p-5），
    庄家爆才恢复正常（爆 -1、五小 +5）——p=1 退化普通、p=0 退化五小定局；
    five_bust_p=None（无样本）时爆牌/五小按普通、停牌保守五小定局 -5。
    """
    key = (round(total * 2), cards)
    if key in memo:
        return memo[key]
    if cards >= 5:
        memo[key] = _FIVE_SMALL_MULT  # 五小直接赢 ×5
        return _FIVE_SMALL_MULT
    ev_stand = _five_stand_ev(five_small, five_bust_p, total, p_bust, samples)
    conditioned = five_small and five_bust_p is not None
    ev_hit = 0.0
    for v in _DECK:
        t2 = total + v
        if t2 > _TARGET:
            if conditioned:
                # 庄家五小必输 ×5、庄家爆才正常赔 ×1（5-4×p 是 1×p + 5×(1-p) 的归并）
                ev_hit -= 5.0 - 4.0 * five_bust_p
            else:
                ev_hit -= 1.0
        elif cards + 1 >= 5:
            if conditioned:
                # 成五小：庄家爆才 +5，五小互碰庄家通吃输 ×5（10×p-5 是 5×p - 5×(1-p)）
                ev_hit += 10.0 * five_bust_p - 5.0
            else:
                ev_hit += _FIVE_SMALL_MULT
        else:
            ev_hit += _ev_play(t2, cards + 1, p_bust, samples, memo, five_small=five_small, five_bust_p=five_bust_p)
    ev_hit /= len(_DECK)
    best = max(ev_stand, ev_hit)
    memo[key] = best
    return best


def _dealer_lookup(dealers: dict, name: str, dealer_key: str) -> dict:
    """画像 entry 查询：稳定 id 键优先，displayName 兑底（老数据/未观察到 id 的局）。"""
    if dealer_key:
        entry = dealers.get(dealer_key) or {}
        if entry:
            return entry
    return dealers.get(name) or {}


def _global_dealer_entry(dealers: dict, dealer_key: str, name: str) -> dict:
    """其余所有庄家的画像合计（排除本人），样本不足的新庄家用它代表（v1.23.10）。

    v1.23.20：点数计数按 counts 全量合并（旧 totals 数据经 _holder_counts 动态转换）。
    """
    merged: dict = {}
    skip = dealer_key or name
    for key, entry in dealers.items():
        if key == skip or key == name or (entry.get("name") or "") == name:
            continue  # 排除本人（稳定 id 键 / displayName 键 / 展示名）
        merged["rounds"] = int(merged.get("rounds", 0) or 0) + int(entry.get("rounds", 0) or 0)
        merged["busts"] = int(merged.get("busts", 0) or 0) + int(entry.get("busts", 0) or 0)
        merged["counts"] = _merge_counts(merged.get("counts"), _holder_counts(entry))
        cards = dict(merged.get("cards") or {})
        for n, bucket in (entry.get("cards") or {}).items():
            b = dict(cards.get(n) or {})
            b["rounds"] = int(b.get("rounds", 0) or 0) + int(bucket.get("rounds", 0) or 0)
            b["busts"] = int(b.get("busts", 0) or 0) + int(bucket.get("busts", 0) or 0)
            b["counts"] = _merge_counts(b.get("counts"), _holder_counts(bucket))
            cards[n] = b
        merged["cards"] = cards
    return merged


def _counts_of(holder: dict, exclude_current: int = 0) -> dict:
    """旧版 totals 样本列表 → 全量点数计数（v1.23.20）。

    旧格式点数样本只留最近 _DEALER_TOTALS_CAP 条（滑动窗口）而 rounds 全量累计，
    明细与总局数对不上（线上实例「144 局 vs 明细 60」）；迁移成按点数归档的全量
    计数（0.5～10.5 共 21 档，体积恒定无需裁剪），并把窗口裁掉/缺失牌面详情的
    局补计 unseen（rounds = busts + Σcounts + unseen 恒等）。超点脏样本仍留在
    计数里，读取端（_dealer_effective）按 >10.5 归位 busts。
    exclude_current：调用方已把当前局计入 rounds 时传 1，gap 只反映旧数据缺口。"""
    counts: dict = {}
    for v in holder.get("totals") or []:
        try:
            t = float(v)
        except (TypeError, ValueError):
            continue  # 脏样本不计（与旧 _dealer_effective 清洗一致）
        key = f"{t:g}"
        counts[key] = int(counts.get(key, 0) or 0) + 1
    gap = int(holder.get("rounds", 0) or 0) - exclude_current - int(holder.get("busts", 0) or 0)
    gap -= sum(int(c) for c in counts.values())
    if gap > 0:
        counts["unseen"] = int(counts.get("unseen", 0) or 0) + gap
    return counts


def _holder_counts(holder: dict) -> dict:
    """画像/分桶的点数计数：新格式直接取 counts，旧格式（totals 列表）动态转换。"""
    counts = holder.get("counts")
    return counts if isinstance(counts, dict) else _counts_of(holder)


def _merge_counts(a: dict, b: dict) -> dict:
    """两个点数计数 dict 求和（unseen 一并合并）。"""
    out = dict(a or {})
    for k, c in (b or {}).items():
        out[k] = int(out.get(k, 0) or 0) + int(c or 0)
    return out


def _five_bust_prob(dealers: dict, name: str, dealer_key: str) -> float | None:
    """庄家「5张」桶的条件爆率（本庄 → 全局，样本≥3）：庄家 5 张后最终爆牌的经验概率。

    v1.23.13：HDSky 庄家 5 张≠五小已定（还会继续补牌），bust 字段在轮询中几乎
    不可见（5000 条日志 0 命中），只有画像「5张」桶的 busts/rounds 能给出这个
    条件分布；无样本返回 None（决策侧保守按五小定局计）。
    """
    for src in (_dealer_lookup(dealers, name, dealer_key), _global_dealer_entry(dealers, dealer_key, name)):
        bucket = (src.get("cards") or {}).get("5") or {}
        r, b, _t = _dealer_effective(bucket)
        if r >= _MIN_CARD_SAMPLES:
            return min(1.0, b / r)
    return None


def _dealer_dist(dealers: dict, name: str, cards: int | None, dealer_key: str = "") -> tuple[float, list[float]] | None:
    """庄家终局分布 (爆率, 非爆点数样本)：本庄桶(≥3) → 本庄聚合(≥8) → 全局桶(≥3) → 全局聚合(≥8)。

    v1.23.10 起样本不足时用其余所有庄家的画像合计代表，直到本庄画像达标。
    """
    entry = _dealer_lookup(dealers, name, dealer_key)
    if isinstance(cards, int) and cards > 0:
        bucket = (entry.get("cards") or {}).get(str(cards)) or {}
        r, b, t = _dealer_effective(bucket)
        if r >= _MIN_CARD_SAMPLES and t:
            return min(1.0, b / r), list(t)
    r, b, t = _dealer_effective(entry)
    if r >= _MIN_DEALER_SAMPLES and t:
        return min(1.0, b / r), list(t)
    g = _global_dealer_entry(dealers, dealer_key, name)
    if isinstance(cards, int) and cards > 0:
        bucket = (g.get("cards") or {}).get(str(cards)) or {}
        r, b, t = _dealer_effective(bucket)
        if r >= _MIN_CARD_SAMPLES and t:
            return min(1.0, b / r), list(t)
    r, b, t = _dealer_effective(g)
    if r >= _MIN_DEALER_SAMPLES and t:
        return min(1.0, b / r), list(t)
    return None


def _decide_ev(
    total: float,
    cards: int,
    actions: list[str],
    dealer_bust: bool,
    dealer_total: float | None,
    dist: tuple[float, list[float]],
    dealer_five_small: bool = False,
    five_bust_p: float | None = None,
) -> tuple[str | None, str, float | None, float | None, float | None]:
    """EV 决策（v1.21.0）：停牌 EV 对要牌 EV 递推择优，返回 (action, reason, ev_hit, ev_stand, ev_fold)。

    ev_* 为各选择的单位下注期望（供结算推送决策轨迹展示）；
    非 EV 路径（庄家已爆/我方已五小/门户未开放）无 EV 数值，返回 None。
    dist 是庄家终局分布；庄家点数可见时退化为点质量分布（结果确定）。
    dealer_five_small（庄家 5 张，v1.23.11）：停牌 EV 按「5张」桶条件分布
    （P(爆)×+0.99 - P(五小)×-5，v1.23.13）算；要牌递推奖惩同样按条件分布加权
    （v1.23.14：爆牌 5-4×p、成五小 10×p-5——五小互碰庄家通吃输 ×5）。
    认输是止损通道不是常规选项（v1.23.14 用户实测）：只在首手（我方 0 张未拿牌）
    可选——拿了牌就只有拿牌/停牌；且只有停牌 EV ≤ -1（不优于认输）才认输，
    停牌 EV > -1 时在拿牌/停牌间择优；five_bust_p=None（桶无样本）时停牌保守
    按五小定局 -5（≤ -1 → 首手认输 -1 兜底）、要牌按普通。
    """
    can_hit = "hit" in actions
    can_stand = "stand" in actions
    if not can_hit and not can_stand and "fold" not in actions:
        return None, "门户未开放任何动作", None, None, None
    if dealer_bust:
        if can_stand:
            return "stand", "庄家已爆牌，停牌即赢", None, None, None
        return None, "庄家已爆牌但未开放停牌", None, None, None
    if cards >= 5:
        if can_stand:
            return "stand", "已五小（5张未爆），直接赢 ×5，停牌", None, None, None
        return None, "已五小但未开放停牌", None, None, None
    if dealer_total is not None:
        p_bust, samples = 0.0, [dealer_total]
    else:
        p_bust, samples = dist
    memo: dict = {}
    ev_stand = _five_stand_ev(dealer_five_small, five_bust_p, total, p_bust, samples)
    # v1.23.14 认输时机（用户实测规则）：①拿了牌就没有认输了（只有继续拿牌/停牌）
    # → 认输只在首手（我方 0 张）可选；②只有停牌 EV ≤ -1（不优于认输）才认输止损，
    # 停牌 EV > -1 时在拿牌/停牌间择优，认输不参与对比
    can_fold = dealer_five_small and cards == 0 and "fold" in actions
    ev_fold = -1.0 if can_fold else None
    conditioned = dealer_five_small and five_bust_p is not None
    ev_hit = 0.0
    for v in _DECK:
        t2 = total + v
        if t2 > _TARGET:
            if conditioned:
                # 庄家五小必输 ×5、庄家爆才正常赔 ×1（5-4×p 是 1×p + 5×(1-p) 的归并）
                ev_hit -= 5.0 - 4.0 * five_bust_p
            else:
                ev_hit -= 1.0
        elif cards + 1 >= 5:
            if conditioned:
                # 成五小：庄家爆才 +5，五小互碰庄家通吃输 ×5（10×p-5 是 5×p - 5×(1-p)）
                ev_hit += 10.0 * five_bust_p - 5.0
            else:
                ev_hit += _FIVE_SMALL_MULT
        else:
            ev_hit += _ev_play(
                t2, cards + 1, p_bust, samples, memo, five_small=dealer_five_small, five_bust_p=five_bust_p
            )
    ev_hit /= len(_DECK)
    if can_fold and ev_stand <= -1.0:
        return (
            "fold",
            f"EV 认输 {ev_fold:+.2f} 最优：要牌 {ev_hit:+.2f}/停牌 {ev_stand:+.2f}"
            "（庄家5张五小概率大，认输只亏本金×1）",
            ev_hit,
            ev_stand,
            ev_fold,
        )
    # 停牌 EV > -1：拿牌/停牌择优（同分追牌优先；认输已门控不参与）
    options: list[tuple[float, str]] = [(ev_hit, "hit")] if can_hit else []
    if can_stand:
        options.append((ev_stand, "stand"))
    if not options:
        return None, "EV 无可用动作（要牌/停牌均未开放）", ev_hit, ev_stand, ev_fold
    # 元组比 max：EV 相同时 "hit" > "stand" → 同分追牌优先
    action = max(options)[1]
    fold_desc = f" 认输 {ev_fold:+.2f}" if ev_fold is not None else ""
    if action == "hit":
        tail = "·庄家5张，按画像赌爆，追五小）" if dealer_five_small else "）"
        return (
            "hit",
            f"EV 要牌 {ev_hit:+.2f} > 停牌 {ev_stand:+.2f}{fold_desc}（{cards}张·爆率 {_bust_prob(total):.0%}{tail}",
            ev_hit,
            ev_stand,
            ev_fold,
        )
    return (
        "stand",
        f"EV 停牌 {ev_stand:+.2f} ≥ 要牌 {ev_hit:+.2f}{fold_desc}（{cards}张）",
        ev_hit,
        ev_stand,
        ev_fold,
    )


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


def _dealer_key_of(dealer_p: dict | None) -> str:
    """庄家画像主键：服务端稳定 id（改名不丢统计）。accountId 优先，userId 兑底。"""
    if not dealer_p:
        return ""
    aid = dealer_p.get("accountId")
    if aid not in (None, ""):
        return f"id:{aid}"
    uid = dealer_p.get("userId")
    if uid not in (None, ""):
        return f"id:{uid}"
    return ""


def _dealer_whitelist(cfg: dict) -> list[str]:
    """「指定庄家」名单（逗号/换行分隔，displayName 或 id:xxx）；空=不限（所有庄家都打）。

    非空时进入「专打指定庄家」模式：signup 只在这些庄家开局时报名，且豁免掉落
    配额暂停（用户明确要打这些庄家，掉落奖励与否无所谓，不受掉落守卫拦截）。
    """
    raw = str(cfg.get("tenhalf_dealer_whitelist", "") or "")
    return [p.strip() for p in re.split(r"[,\n，]+", raw) if p.strip()]


def _dealer_matches(dealer_p: dict | None, whitelist: list[str]) -> bool:
    """当前庄家是否命中名单：displayName / 稳定 id（id:xxx）/ 纯 accountId·userId，大小写不敏感。

    名单留空视为不限制（返回 True 由调用方短路，这里 whitelist 空直接 False 交由调用方判断）。
    """
    if not dealer_p or not whitelist:
        return False
    norm = {w.lower() for w in whitelist}
    name = str(dealer_p.get("displayName") or "").strip()
    if name and name.lower() in norm:
        return True
    key = _dealer_key_of(dealer_p)  # id:{accountId|userId}
    if key and key.lower() in norm:
        return True
    for field in ("accountId", "userId"):
        v = dealer_p.get(field)
        if v not in (None, "") and str(v).strip().lower() in norm:
            return True
    return False


def _record_dealer(ctx: object, settlement: dict, cards: int | None = None, dealer_key: str = "") -> str:
    """累计一条庄家结算（局数/爆牌数/点数计数），返回画像主键。

    爆牌判定：文案含「爆」或点数 > 10.5（实测爆牌局的 handLabel 常不含「爆」字、
    直接显示超点点数，如「11点」），爆牌不入点数计数。结算囊不到牌面（无点数且
    非爆）的局只计局数、计入 counts 的 unseen，保证「局数 = 爆数 + Σ点数 + 未详」
    恒等（v1.23.20）。

    传入 cards（本局庄家终局手牌张数）时，同步计入按张数分桶的画像。
    传入 dealer_key（稳定 id）时以 id 为主键、displayName 仅作展示名（改名自动归并）；
    未传则兑底用 displayName 做键（老数据兼容）。
    """
    name = str(settlement.get("dealerDisplayName") or settlement.get("dealer") or "").strip()
    if not name:
        return ""
    key = dealer_key or name
    label = settlement.get("dealerHandLabel")
    total = _parse_total(label)
    bust = "爆" in str(label or "") or (total is not None and total > _TARGET)
    dealers = _load_json(ctx.kv, _DEALERS_KEY)
    entry = dealers.get(key) or {}
    entry["name"] = name
    entry["rounds"] = int(entry.get("rounds", 0) or 0) + 1
    if "counts" not in entry:  # 旧 totals 列表一次性迁移为全量计数（v1.23.20）
        entry["counts"] = _counts_of(entry, exclude_current=1)  # rounds 已含当前局，gap 需扣除
        entry.pop("totals", None)
    counts: dict = entry["counts"]
    if bust:
        entry["busts"] = int(entry.get("busts", 0) or 0) + 1
    elif total is not None:
        pkey = f"{total:g}"
        counts[pkey] = int(counts.get(pkey, 0) or 0) + 1
    else:
        counts["unseen"] = int(counts.get("unseen", 0) or 0) + 1
    entry["counts"] = counts
    if isinstance(cards, int) and cards > 0:
        cards_map = dict(entry.get("cards") or {})
        bucket = dict(cards_map.get(str(cards)) or {})
        bucket["rounds"] = int(bucket.get("rounds", 0) or 0) + 1
        if "counts" not in bucket:
            bucket["counts"] = _counts_of(bucket, exclude_current=1)
            bucket.pop("totals", None)
        bcounts: dict = bucket["counts"]
        if bust:
            bucket["busts"] = int(bucket.get("busts", 0) or 0) + 1
        elif total is not None:
            pkey = f"{total:g}"
            bcounts[pkey] = int(bcounts.get(pkey, 0) or 0) + 1
        else:
            bcounts["unseen"] = int(bcounts.get("unseen", 0) or 0) + 1
        bucket["counts"] = bcounts
        cards_map[str(cards)] = bucket
        entry["cards"] = cards_map
    dealers[key] = entry
    ctx.kv.set(_DEALERS_KEY, json.dumps(dealers, ensure_ascii=False))
    return key


def _observe_dealer(ctx: object, rid: object, dealer_p: dict | None) -> None:
    """轮询中观察庄家（手牌张数 + 稳定 id），按 roundId 暂存：张数只增不减（终局
    张数）、id 直接写入。结算时 _pop_dealer_obs 取走配对（改名归并靠 id）。"""
    if rid in (None, "") or not dealer_p:
        return
    cc = dealer_p.get("cardCount")
    has_cards = isinstance(cc, (int, float)) and not isinstance(cc, bool) and cc > 0
    key = _dealer_key_of(dealer_p)
    if not has_cards and not key:
        return
    stash = _load_json(ctx.kv, _DEALER_CARDS_KEY)
    entry = dict(stash.get(str(rid)) or {})
    if has_cards and (not isinstance(entry.get("cards"), (int, float)) or int(cc) > entry["cards"]):
        entry["cards"] = int(cc)
    if key:
        entry["key"] = key
    stash[str(rid)] = entry
    if len(stash) > _CARDS_STASH_CAP:  # 防未结算局堆积，按插入顺序裁掉最旧
        for k in list(stash)[: len(stash) - _CARDS_STASH_CAP]:
            stash.pop(k, None)
    ctx.kv.set(_DEALER_CARDS_KEY, json.dumps(stash, ensure_ascii=False))


def _pop_dealer_obs(ctx: object, rid: object) -> tuple[int | None, str | None]:
    """取出并移除某局暂存的庄家观察（终局张数, 稳定 id 键）；未观察到返回 (None, None)。"""
    if rid in (None, ""):
        return None, None
    stash = _load_json(ctx.kv, _DEALER_CARDS_KEY)
    raw = stash.pop(str(rid), None)
    ctx.kv.set(_DEALER_CARDS_KEY, json.dumps(stash, ensure_ascii=False))
    if isinstance(raw, dict):
        cards = raw.get("cards")
        cc = int(cards) if isinstance(cards, (int, float)) and not isinstance(cards, bool) and cards > 0 else None
        return cc, (str(raw.get("key") or "") or None)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:  # 兼容旧结构
        return int(raw), None
    return None, None


def _dealer_effective(entry: dict) -> tuple[int, int, list[float]]:
    """清洗后的庄家统计 (局数, 爆牌数, 点数样本)。

    counts 全量计数（v1.23.20）：unseen 计局不计点；爆点计数（旧版超点脏数据
    迁移而来）读出时归位 busts，避免均点虚高把阈值顶到上限。兼容旧版 totals
    列表：点数 > 10.5 的样本必是爆牌（当时爆牌局被误当高点点数），同口径清洗。
    """
    rounds = int(entry.get("rounds", 0) or 0)
    busts = int(entry.get("busts", 0) or 0)
    totals: list[float] = []
    counts = entry.get("counts")
    if isinstance(counts, dict):
        for raw, c in counts.items():
            if raw == "unseen":
                continue
            try:
                t = float(raw)
            except (TypeError, ValueError):
                continue
            n = int(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else 0
            if t > _TARGET:
                busts += n
            else:
                totals.extend([t] * n)
    else:
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

    平局算输：目标需压过庄家均点（+0.5）；爆率高则按比例降低点数要求，
    但夹取上限是爆牌红线 6.5：追庄家均点到 7+ 的爆牌成本（含五小倍数）
    大于压点收益，早停赌庄家自爆期望更优（v1.20.0）。
    """
    if rounds < min_samples or not totals:
        return None
    avg = sum(totals) / len(totals)
    bust_rate = busts / rounds
    threshold = avg + 0.5 - bust_rate * _BUST_RATE_DISCOUNT
    return max(_THRESHOLD_MIN, min(_THRESHOLD_MAX, round(threshold * 2) / 2))


def _threshold_for(
    cfg: dict, dealers: dict, dealer_name: str, dealer_cards: int | None = None, dealer_key: str = ""
) -> float:
    """停牌阈值：本庄桶 → 本庄聚合 → 全局桶 → 全局聚合，都不够才退配置基准（v1.23.10）。

    平局算输、爆率高可低停（赌庄家爆）的推导见 _threshold_from_stats；
    画像推导受爆牌红线夹取（≤6.5），配置基准不受红线限制（用户显式选择优先）。
    """
    base = float(cfg.get("tenhalf_stand_threshold", 8) or 8)
    entry = _dealer_lookup(dealers, dealer_name, dealer_key)
    if isinstance(dealer_cards, int) and dealer_cards > 0:
        bucket = (entry.get("cards") or {}).get(str(dealer_cards)) or {}
        r, b, t = _dealer_effective(bucket)
        v = _threshold_from_stats(r, b, t, _MIN_CARD_SAMPLES)
        if v is not None:
            return v
    r, b, t = _dealer_effective(entry)
    v = _threshold_from_stats(r, b, t, _MIN_DEALER_SAMPLES)
    if v is not None:
        return v
    g = _global_dealer_entry(dealers, dealer_key, dealer_name)
    if isinstance(dealer_cards, int) and dealer_cards > 0:
        bucket = (g.get("cards") or {}).get(str(dealer_cards)) or {}
        r, b, t = _dealer_effective(bucket)
        v = _threshold_from_stats(r, b, t, _MIN_CARD_SAMPLES)
        if v is not None:
            return v
    r, b, t = _dealer_effective(g)
    v = _threshold_from_stats(r, b, t, _MIN_DEALER_SAMPLES)
    return base if v is None else v


def _dealer_display_name(dealers: dict, name: str, dealer_key: str) -> str:
    """展示用庄家名：id 键画像记录的最新 displayName，无则用结算里带的。"""
    if dealer_key:
        shown = (dealers.get(dealer_key) or {}).get("name")
        if shown:
            return str(shown)
    return name


def _profile_core(rounds: int, busts: int, totals: list[float]) -> str:
    """单份画像文本：局数，有点数样本拼均点，有爆牌拼爆率。"""
    parts = [f"{rounds}局"]
    if totals:
        parts.append(f"均 {sum(totals) / len(totals):.1f} 点")
    if busts:
        parts.append(f"爆率 {busts / rounds:.0%}")
    return "·".join(parts)


def _points_dist_text(busts: int, totals: list[float], unseen: int = 0) -> str:
    """逐点数出现次数分布：7点×2/7.5点×1/8点×2…/爆×3/未详×2（从低到高，×1 省略）。

    unseen（v1.23.20）：结算没抓到牌面/旧窗口裁掉的局，只计局数不计点，补齐
    「局数 = 爆数 + Σ点数 + 未详」的恒等展示。"""
    counts: dict[float, int] = {}
    for t in totals:
        counts[t] = counts.get(t, 0) + 1
    items = [f"{p:g}点×{c}" if c > 1 else f"{p:g}点" for p, c in sorted(counts.items())]
    if busts:
        items.append(f"爆×{busts}")
    if unseen:
        items.append(f"未详×{unseen}")
    return "/".join(items)


def _profile_text_for(entry: dict, cards: int | None) -> str:
    """画像展示文本：只展示当前手牌张数分桶（点数分布+爆数+未详，v1.23.10/v1.23.20）；
    桶无样本退聚合画像。"""
    rounds, busts, totals = _dealer_effective(entry)
    if not rounds:
        return ""
    if isinstance(cards, int) and cards > 0:
        bucket = (entry.get("cards") or {}).get(str(cards)) or {}
        br, bb, bt = _dealer_effective(bucket)
        if br:
            bu = int(_holder_counts(bucket).get("unseen", 0) or 0)
            return f"{cards}张 {br}局：{_points_dist_text(bb, bt, bu)}"
    return _profile_core(rounds, busts, totals)


def _dealer_profile_text(dealers: dict, name: str, cards: int | None = None, dealer_key: str = "") -> str:
    """结算推送的庄家画像：本庄有样本用本庄；否则用其余用户合计代表并标注「全局画像」（v1.23.10）。"""
    text = _profile_text_for(_dealer_lookup(dealers, name, dealer_key), cards)
    if text:
        return text
    text = _profile_text_for(_global_dealer_entry(dealers, dealer_key, name), cards)
    return f"全局画像 {text}" if text else ""


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


async def _safe_notify(ctx: object, message: str, **kwargs: object) -> None:
    """通知失败只记日志不抛出：断网窗口通知渠道不可用时，避免异常冒泡到调度层触发降级。"""
    try:
        await ctx.notify(message, **kwargs)
    except Exception as e:
        ctx.log.warning("十点半通知发送失败（渠道暂不可用）: %r", e)


async def _safe_notify_table(ctx: object, header: list, rows: list, **kwargs: object) -> None:
    """_safe_notify 的表格版，同样吞异常只记日志。"""
    try:
        await ctx.notify_table(header, rows, **kwargs)
    except Exception as e:
        ctx.log.warning("十点半通知发送失败（渠道暂不可用）: %r", e)


async def _settle_round(ctx: object, cfg: dict, rid: object, settlement: dict) -> None:
    """入账一局结算：记庄家画像；我方参局才入账战绩并推送（输赢统一 success）。"""
    dealer_cards, observed_key = _pop_dealer_obs(ctx, rid)
    dealer_key = _record_dealer(ctx, settlement, cards=dealer_cards, dealer_key=observed_key or "")
    dealer_name = str(settlement.get("dealerDisplayName") or settlement.get("dealer") or "").strip()
    me = settlement.get("self") or {}
    if not me:
        return  # 本局未参与：只记庄家画像
    delta = int(me.get("delta", 0) or 0)
    total, daily = _update_stats(ctx, delta)
    ctx.log.info("十点半 #%s 结算 %+d 银元（%s）", rid, delta, me.get("resultText") or "")
    if not cfg.get("tenhalf_notify", True):
        return
    rows: list[list[object]] = []
    if dealer_key:
        shown = _dealer_display_name(_load_json(ctx.kv, _DEALERS_KEY), dealer_name, dealer_key)
        profile = _dealer_profile_text(_load_json(ctx.kv, _DEALERS_KEY), dealer_name, dealer_cards, dealer_key)
        rows.append(["庄家", f"{shown}（{profile}）" if profile else shown])
    dealer_label = settlement.get("dealerHandLabel")
    if dealer_label:
        rows.append(["庄家牌面", str(dealer_label)])
    if me.get("handLabel"):
        rows.append(["我方牌面", str(me.get("handLabel"))])
    steps = _pop_decision_log(ctx, rid)
    if steps:
        rows.append(["📜 决策轨迹", _decide_text(*steps[0])])
        for s in steps[1:]:  # 每条决策单独一行，不拼进同一格（表格折行效果差）
            rows.append(["", _decide_text(*s)])
    if me.get("resultText"):
        rows.append(["结果", str(me.get("resultText"))])
    rows.append(["盈亏", f"{'+' if delta >= 0 else ''}{delta:,} 银元"])
    rows.append(["📊 累计", _stats_text(total)])
    rows.append(["📅 今日", _stats_text(daily)])
    caption = f"🎲 十点半 #{rid} 结算 {'+' if delta >= 0 else ''}{delta:,} 银元"
    # 输赢都走 success：正常结算不算异常，不用 warning 刷屏
    await _safe_notify_table(ctx, ["项目", "内容"], rows, caption=caption, level="success", category="十点半")
    # AI 评价（v1.23.15 起，v1.23.16 移交 games/ai_review.py 通用模块）：本局有决策轨迹才总结，
    # 赢/输/平各自口吻，不涉及 EV；开关/目标群/提示词在「AI 评价」配置分组统一控制
    if steps:
        await ai_review.review(
            ctx,
            cfg,
            "tenhalf",
            delta,
            str(me.get("resultText") or ""),
            opponent=dealer_name,
            actions=steps,
            rid=rid,
            labels=_ACTION_LABELS,
        )


async def _handle_settlement(ctx: object, cfg: dict, game: dict) -> None:
    """lastResult 每局只处理一次（roundId 去重），委托 _settle_round 入账。"""
    last = game.get("lastResult") or {}
    rid = last.get("roundId")
    if rid in (None, "") or str(ctx.kv.get(_LAST_ROUND_KEY, "")) == str(rid):
        return
    ctx.kv.set(_LAST_ROUND_KEY, str(rid))
    await _settle_round(ctx, cfg, rid, last.get("settlement") or {})


def _round_no(v: object) -> int:
    """局号转数字（单调递增）；非法值返回 -1 不参与比较。"""
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return -1


async def _catch_up_settlement(ctx: object, cfg: dict, game: dict) -> None:
    """用 history[] 补扫被 lastResult 漏掉的结算（v1.19.1）。

    快速局停牌后 5 秒内就开下一局报名，settled 窗口可能短于轮询间隔：
    lastResult 只在窗口内可见，错过就永久错过（线上 08-18 连丢 5 局结算推送）。
    history[] 带完整结算数据，按最近报名局号回查；history 也没有时降级推送
    兜底（盈亏未知，战绩不入账），保证每局报名后必有结束推送。
    """
    joined = ctx.kv.get(_JOINED_ROUND_KEY, "")
    # 数字比较而非相等比较：_handle_settlement 可能已入账更大的局号（lastResult 推进），
    # 相等比较会永远不成立——history 里还有 joined 时每轮重复入账，
    # 翻篇后每轮兜底推送并把 last_round 回退成小值（v1.23.2 修复重复统计）
    if not joined or _round_no(joined) <= _round_no(ctx.kv.get(_LAST_ROUND_KEY, "")):
        return
    active_rid = game.get("roundId") if game.get("active") else None
    if active_rid is not None and str(active_rid) == str(joined):
        return  # 报名的局还在进行中
    for entry in (game.get("history") or [])[-_HISTORY_SCAN_CAP:]:
        if not isinstance(entry, dict) or str(entry.get("roundId")) != str(joined):
            continue
        ctx.kv.set(_LAST_ROUND_KEY, str(joined))
        await _settle_round(ctx, cfg, joined, entry.get("settlement") or {})
        return
    # history 也没有该条（窗口太短/响应缺字段）：标记已处理并降级推送
    ctx.kv.set(_LAST_ROUND_KEY, str(joined))
    ctx.log.warning("十点半 #%s 已翻篇但 lastResult/history 均未见结算，推送兜底", joined)
    if cfg.get("tenhalf_notify", True):
        await _safe_notify(ctx, f"🎲 十点半 #{joined} 已结算（未抓到结算详情，盈亏未知）", category="十点半")


async def _try_join(ctx: object, cfg: dict, client: HdskyClient, game: dict, limits: dict) -> None:
    """报名下注。失败后本局不再重试（避免每轮轮询撞同一个拒绝）。"""
    rid = game.get("roundId")
    amount = _join_amount(cfg, game, limits)
    r = await client.post(_ACTION_PATH, {"action": "join", "amount": amount, "requestKey": request_key()})
    result = r.get("result", {}) or {}
    if result.get("ok", r.get("ok", False)):
        ctx.kv.set(_JOINED_ROUND_KEY, str(rid))  # 记录报名局号，供结算补扫定位
        ctx.log.info("加入十点半 #%s（下注 %s，单桌上限 %s）", rid, amount, game.get("amount"))
        if cfg.get("tenhalf_notify", True):
            await _safe_notify(
                ctx,
                f"🎲 加入十点半 #{rid}，下注 {amount:,} 银元（单桌上限 {game.get('amount')}）",
                category="十点半",
            )
        return
    ctx.kv.set(_JOIN_FAIL_KEY, str(rid))
    msg = result.get("message") or r.get("error") or "未知"
    ctx.log.warning("十点半报名失败 #%s: %s", rid, msg)
    if cfg.get("tenhalf_notify", True):
        await _safe_notify(ctx, f"🎲 十点半报名失败: {msg}", level="warning", category="十点半")


async def _submit_action(
    ctx: object,
    client: HdskyClient,
    game: dict,
    action: str,
    reason: str,
    total: float,
    ev_hit: float | None = None,
    ev_stand: float | None = None,
    ev_fold: float | None = None,
) -> None:
    """提交要牌/停牌/认输。同局同点数同动作去重；过程不推送，每局只在结算时推一次。"""
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
    label = _ACTION_LABELS.get(action, action)
    ctx.log.info("十点半 #%s %s（点数 %g，%s）", rid, label, total, reason)
    _record_decision(ctx, rid, total, (game.get("self") or {}).get("cards"), action, ev_hit, ev_stand, ev_fold)


async def _once(ctx: object, cfg: dict, client: HdskyClient) -> None:
    """单次轮询：先消化上一局结算，再按当前阶段做一个动作。"""
    data = await client.get(_STATE_PATH)
    if "_error" in data:
        ctx.log.warning("十点半状态请求失败: %s", data["_error"] or "未知网络错误")
        client.reset_csrf()
        return
    game = data.get("game") or {}
    players = game.get("players") or []
    self_p = next((p for p in players if isinstance(p, dict) and p.get("isSelf")), None)
    await _handle_settlement(ctx, cfg, game)
    # lastResult 漏掉的结算用 history[] 回查（快速局 settled 窗口短于轮询间隔）
    await _catch_up_settlement(ctx, cfg, game)
    # 「指定庄家」名单非空 → 专打模式：只在这些庄家开局时报名，且豁免掉落配额暂停
    whitelist = _dealer_whitelist(cfg)
    if drop_guard.paused(ctx) and self_p is None and not whitelist:
        # 配额满且未参与当前局、又没配置专打庄家：结算已消化完，停心跳（不再新报名）；
        # 已报名则照常打完本局。注意此检查必须在结算消化之后——否则刚结束那局切到
        # 新局后 self_p 为空，结算会被暂停检查吞掉永不入账（v1.23.3 修复）
        return
    if not game.get("active"):
        return

    phase = game.get("phase")
    actions = game.get("actions") or []
    limits = game.get("limits") or {}
    dealer_p = game.get("dealer")
    if not isinstance(dealer_p, dict):
        # 兼容旧结构：庄家作为 players 成员标记 dealer=True（线上实际是顶层 game.dealer）
        dealer_p = next((p for p in players if isinstance(p, dict) and p.get("dealer")), None)
    rid = game.get("roundId")
    # 观察庄家手牌张数（按 roundId 取最大值暂存，供结算时配对计入按张数分桶的画像）
    _observe_dealer(ctx, rid, dealer_p)

    # 报名阶段：未报名且可加入 → 按配置下注
    if phase == "signup":
        if self_p is not None or "join" not in actions:
            return
        if whitelist and not _dealer_matches(dealer_p, whitelist):
            ctx.log.debug(
                "十点半 #%s 庄家 %s 不在指定名单，跳过报名", rid, (dealer_p or {}).get("displayName") or "未知"
            )
            return
        # 配额满时不新报名的拦截在 _once 顶部（paused 且未参与直接返回）
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
    raw_self_cards = self_info.get("cards")
    if isinstance(raw_self_cards, list) and raw_self_cards:
        self_cards = len(raw_self_cards)
    else:
        cc = (self_p or {}).get("cardCount")
        self_cards = int(cc) if isinstance(cc, (int, float)) and not isinstance(cc, bool) and cc > 0 else 0
    dealers = _load_json(ctx.kv, _DEALERS_KEY)
    dealer_name = str((dealer_p or {}).get("displayName") or "")
    dealer_key = _dealer_key_of(dealer_p)
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
    # v1.23.13：bust 字段轮询时几乎不可见（5000 条日志 0 命中），total 可见且超
    # 10.5 才是实锤已爆；否则一律当「未知」按画像分布赌，与普通对局一致
    dealer_bust = dealer_bust or (dealer_total is not None and dealer_total > _TARGET)
    # 庄家 5 张（v1.23.13）：≠五小已定，他可能继续补牌爆掉（5822 实证 5小3/爆7）；
    # 唯一区别是停牌判负按「5张」桶条件分布（P(五小)×-5 + P(爆)×+0.99）；认输是
    # 止损通道（v1.23.14）：首手（0 张）且停牌 EV ≤ -1 才认输，否则拿牌/停牌择优
    five_small = dealer_cards_now == 5 and not dealer_bust
    five_bust_p = _five_bust_prob(dealers, dealer_name, dealer_key) if five_small else None
    dist = _dealer_dist(dealers, dealer_name, dealer_cards_now, dealer_key=dealer_key)
    if dist is not None or dealer_bust or dealer_total is not None or five_small:
        # 庄家信息足够（画像/已爆/点数可见/庄家 5 张）→ EV 递推决策（v1.21.0）
        action, reason, ev_hit, ev_stand, ev_fold = _decide_ev(
            total,
            self_cards,
            actions,
            dealer_bust,
            dealer_total,
            dist or (0.0, []),
            dealer_five_small=five_small,
            five_bust_p=five_bust_p,
        )
    else:
        # 画像与点数都不可见才退阈值（此路径无认输选项）
        threshold = _threshold_for(cfg, dealers, dealer_name, dealer_cards=dealer_cards_now, dealer_key=dealer_key)
        action, reason = _decide(total, actions, dealer_bust, dealer_total, threshold)
        ev_hit = ev_stand = ev_fold = None
    if action is None:
        ctx.log.debug("十点半 #%s 本轮不动作: %s", rid, reason)
        return
    await _submit_action(ctx, client, game, action, reason, total, ev_hit=ev_hit, ev_stand=ev_stand, ev_fold=ev_fold)


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
        # 掉落配额满的暂停逻辑在 _once 内：未参与才停心跳，已报名的局照常打完
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
                await _safe_notify(ctx, f"🎲 十点半轮询异常: {e}", level="warning")

    ctx.schedule(_tick, "interval", seconds=interval, id="tenhalf_poll")
    ctx.log.info("十点半已启动（每 %.0f 秒轮询）", interval)


def stop(ctx: object) -> None:
    """停止十点半：ctx.schedule 注册的调度由平台自动清理。"""
    ctx.log.info("十点半已停止")
