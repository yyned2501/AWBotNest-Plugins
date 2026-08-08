# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：通知与决策日志
#
# 生成跟注/弃牌/蒙牌/牌局结束的 TG 通知文本，以及一次决策的完整推导日志。
# 只读牌局数据与决策结果，不产生副作用（推送由调用方经 ctx.notify 完成）。

from __future__ import annotations

import datetime
from typing import Any

from .zjh_hand import _normalize_hand_type
from .zjh_model import (
    _blind_call_cost,
    _CallDecision,
    _Choice,
    _combined_opponent_threshold,
    _RoundTracker,
    _TerminalDecision,
)
from .zjh_state import _is_alive, _is_self, _opponent_entries, _players
from .zjh_stats import format_stats, load_day_stats, load_total_stats


def _threshold_summary(decision: _CallDecision) -> str:
    """格式化已看牌对手的隐含牌力范围（下界~上界）与来源。"""
    return ", ".join(
        f"{lower:.0%}~{upper:.0%}{'实测' if observed else '回退'}"
        for lower, upper, observed in decision.seen_thresholds
    )


def _opponent_brief(decision: _CallDecision) -> str:
    """对手蒙/看构成与看牌门槛的简短描述。"""
    brief = f"蒙{decision.blind_opponents}/看{decision.seen_opponents}"
    if decision.seen_opponents:
        brief += f"（门槛 {_threshold_summary(decision)}）"
    return brief


def _log_decision(
    ctx: object,
    hand: str,
    hand_type: str,
    hand_value: Any,
    game: dict[str, Any],
    choice: _Choice,
    tracker: _RoundTracker,
    fallback_threshold: float,
) -> None:
    """打印一次决策的完整推导，便于核对胜率与 EV。"""
    log = ctx.log
    decision = choice.decision
    pot = game.get("pot")
    call_bet = game.get("callBet")
    if decision is None:
        log.info(
            "决策[弃] %s(%s) 键值=%s 原因=%s 底池=%s 成本=%s", hand, hand_type, hand_value, choice.reason, pot, call_bet
        )
        return
    seen_detail = []
    for key, player in _opponent_entries(game):
        if not player.get("seen", False):
            continue
        peek_snapshot = tracker.peek_snapshots.get(key)
        continue_snapshot = tracker.snapshots.get(key)
        inferred = _combined_opponent_threshold(peek_snapshot, continue_snapshot, fallback_threshold)
        details = []
        if peek_snapshot is not None:
            details.append(
                f"上牌(底池{peek_snapshot.pot:.0f}/成本{peek_snapshot.call_bet:.0f}/对手{peek_snapshot.opponents})"
            )
        if continue_snapshot is not None:
            details.append(
                f"下注(底池{continue_snapshot.pot:.0f}/成本{continue_snapshot.call_bet:.0f}/对手{continue_snapshot.opponents})"
            )
        seen_detail.append(
            f"{key} 综合门槛={'%.3f' % inferred if inferred is not None else '回退值'} "
            f"{' + '.join(details) if details else '回退(未观测到上牌或下注)'}"
        )
    log.info(
        "决策[%s] %s(%s) 键值=%s | 单挑胜率=%.4f 蒙=%d 看=%d | 看牌对手[%s] | "
        "终胜率=%.4f | 底池=%.0f 成本=%.0f | EV=%+.2f | 原因=%s",
        "跟" if choice.call else "弃",
        hand,
        hand_type,
        hand_value,
        decision.one_vs_one,
        decision.blind_opponents,
        decision.seen_opponents,
        "; ".join(seen_detail) or "无",
        decision.win_probability,
        pot,
        call_bet,
        decision.expected_value,
        choice.reason,
    )


def _action_notification(
    action: str,
    rid: Any,
    hand: str,
    hand_type: str,
    decision: _CallDecision,
    pot: float,
    call_bet: float,
    reason: str,
) -> str:
    """生成跟注、主动开牌、追加或应战开牌的通知。"""
    labels = {"call": "跟注", "open": "主动开牌", "raise": "追加", "showdown": "应战开牌"}
    return "\n".join(
        [
            f"🃏 炸金花 · {labels[action]}",
            f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）",
            f"底池 {pot:.0f} · 当前成本 {call_bet:.0f}",
            f"单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}",
            f"最终实际胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}",
            f"原因：{reason}",
        ]
    )


def _fold_notification(rid: Any, hand: str, hand_type: str, reason: str, decision: _CallDecision | None) -> str:
    """生成弃牌通知：手牌、概率明细（若有）与弃牌原因。"""
    lines = ["🃏 炸金花 · 弃牌", f"牌桌 #{rid} · 手牌 {hand}（{hand_type}）"]
    if decision is not None:
        lines.append(f"单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}")
        lines.append(f"最终实际胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}")
    lines.append(f"原因：{reason}")
    return "\n".join(lines)


def _blind_notification(
    action: str,
    rid: Any,
    decision: _TerminalDecision | _CallDecision | None,
    pot: float,
    call_bet: float,
    reason: str,
) -> str:
    """生成多人蒙牌决策通知：盲跟（蒙）、看牌（看）、应战（showdown）或主动开牌（open）。

    decision 可为 Terminal EV 决策（v1.14.0，含 reason/terminal_ev）或旧单步 EV 决策
    （_CallDecision，含 one_vs_one/对手构成）。两者展示字段不同，分别处理。
    """
    labels = {
        "call": "蒙牌盲跟",
        "peek": "看牌买信息",
        "showdown": "蒙牌应战",
        "open": "蒙牌主动开牌",
        "fold": "蒙牌弃牌",
    }
    lines = [f"🃏 炸金花 · {labels.get(action, action)}", f"牌桌 #{rid} · 未看牌"]
    if decision is not None:
        lines.append(f"底池 {pot:.0f} · 半价成本 {_blind_call_cost(call_bet):.0f}")
        if isinstance(decision, _TerminalDecision):
            # Terminal EV 决策：展示各候选 EV 分解
            lines.append(
                f"终局期望 {decision.terminal_ev:+.0f} （盲跟 {decision.call_ev:+.0f} "
                f"· 看牌 {decision.peek_ev:+.0f} · 弃牌 0）"
            )
        else:
            # 旧单步 EV 决策：展示胜率与对手构成
            lines.append(f"平均单挑 {decision.one_vs_one:.1%} · 对手 {_opponent_brief(decision)}")
            lines.append(f"蒙牌胜率 {decision.win_probability:.1%} · 期望收益 {decision.expected_value:+.0f}")
    lines.append(f"原因：{reason}")
    return "\n".join(lines)


def _game_result_notification(
    game_data: dict[str, Any],
    hand: str,
    hand_type: str,
    delta: float | None = None,
    total_stats: dict[str, int | float] | None = None,
    day_stats: dict[str, int | float] | None = None,
) -> str:
    """生成牌局结束通知：本局结果、我方手牌、对手排行，以及本局盈亏与累计战绩。"""
    game = game_data.get("game", {})
    s = game.get("self", {})
    alive = s.get("alive", False)
    players = _players(game)
    result_lines = []
    if alive:
        result_lines.append("🃏 炸金花 · 本局获胜")
    else:
        result_lines.append("🃏 炸金花 · 本局结束")
    if hand:
        result_lines.append(f"手牌 {hand}（{hand_type}）")
    # 对手排行
    rank = 1
    for player in players:
        p_alive = _is_alive(player)
        p_self = _is_self(player)
        p_hand = player.get("hand", "")
        p_hand_type = _normalize_hand_type(player.get("handType", ""))
        if p_self:
            label = "你"
        else:
            label = f"对手{rank}"
            rank += 1
        if p_alive:
            p_hand_str = f" · {p_hand}（{p_hand_type}）" if p_hand else ""
            result_lines.append(f"  {label} 存活{p_hand_str}")
        elif p_hand:
            result_lines.append(f"  {label} 出局 · {p_hand}（{p_hand_type}）")
        else:
            result_lines.append(f"  {label} 出局")
    # 本局盈亏与战绩（结算自 game.lastResult.selfDelta，由调用方入账后传入）
    if delta is not None:
        result_lines.append(f"本局 {delta:+.0f}")
    if total_stats and total_stats.get("games"):
        result_lines.append(f"📊 累计 {format_stats(total_stats)}")
    if day_stats and day_stats.get("games"):
        result_lines.append(f"📅 今日 {format_stats(day_stats)}")
    return "\n".join(result_lines)


async def _notify_game_result(
    ctx: object,
    cfg: dict[str, Any],
    game_data: dict[str, Any],
    hand: str,
    hand_type: str,
    delta: float | None = None,
) -> None:
    """推送牌局结束结果通知，附带累计与当日战绩。"""
    if not cfg.get("zjh_notify_hand", True):
        return
    total_stats = load_total_stats(ctx.kv)
    day_stats = load_day_stats(ctx.kv, datetime.date.today().isoformat())
    notification = _game_result_notification(game_data, hand, hand_type, delta, total_stats, day_stats)
    await ctx.notify(notification)
