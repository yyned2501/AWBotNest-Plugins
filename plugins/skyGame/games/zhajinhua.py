# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 蒙牌按 EV 决策「蒙还是看」：蒙牌跟注成本为已看牌一半，EV ≥ 0 继续盲跟；
#     EV < 0 看牌买信息，牌大再上、牌小弃（不区分单挑/多人）
#   - 看牌后完全按增量期望收益（EV）决策：EV ≥ 0 跟注，否则弃牌（不区分单挑/多人）
#   - 服务端 actions 出现 showdown 时优先应战；这是门户动作授权，不是策略绕行
#   - 胜率按对手看牌状态分开计算：已看牌（手牌确定）对蒙牌对手用 t^B；蒙牌（手牌未知）
#     不能把平均胜率 0.5 当固定手牌，需对未知手牌强度积分（三人全蒙为 1/3 而非 0.5²）；
#     已看牌且继续下注的对手按其行动时底池赔率反推牌力门槛再做条件胜率
#   - 支持双击弃牌确认
#   - 新牌局作废 CSRF（下次 POST 自动重取）
#
# 本文件是轮询编排入口；手牌解析、状态读取、概率模型/决策、通知分别拆到
# zjh_hand / zjh_state / zjh_model / zjh_notify。下方 __all__ 汇总对外（含测试）
# 暴露的名字，保持拆分前的导入面不变。

from __future__ import annotations

import asyncio
from typing import Any

from . import hdsky_auth
from .hdsky import HdskyClient
from .zjh_hand import (
    _acquire_hand_after_peek,
    _extract_hand_value,
    _normalize_hand_type,
    _parse_hand,
    _self_hand,
)
from .zjh_model import (
    _FOLD_CONFIRM_MAX_RETRIES,
    _NEUTRAL_RANGE_MODEL,
    _action_override,
    _actual_win_probability,
    _blind_call_cost,
    _blind_decision,
    _blind_peek_or_call,
    _blind_win_probability,
    _call_decision,
    _Choice,
    _choose,
    _choose_action,
    _combined_opponent_threshold,
    _combined_self_threshold,
    _hand_threshold_for_actual_win_probability,
    _is_raise_action,
    _opponent_hand_threshold,
    _opponent_threshold,
    _OpponentSnapshot,
    _PendingFold,
    _range_factor,
    _ranged_win_probability,
    _RangeModel,
    _record_self_threshold,
    _RoundTracker,
    _seen_factor,
    _seen_opponent_ranges,
    _SeenRange,
    _snapshot_for_actor,
    _update_round_tracker,
)
from .zjh_notify import (
    _action_notification,
    _blind_notification,
    _fold_notification,
    _game_result_notification,
    _log_decision,
    _notify_game_result,
)
from .zjh_state import _in_hand, _opponent_counts

__all__ = [
    "_FOLD_CONFIRM_MAX_RETRIES",
    "_NEUTRAL_RANGE_MODEL",
    "_OpponentSnapshot",
    "_PendingFold",
    "_RangeModel",
    "_RoundTracker",
    "_SeenRange",
    "_Choice",
    "_acquire_hand_after_peek",
    "_act_on_hand",
    "_action_notification",
    "_actual_win_probability",
    "_blind_call_cost",
    "_blind_decision",
    "_blind_notification",
    "_blind_peek_or_call",
    "_blind_win_probability",
    "_call_decision",
    "_choose",
    "_choose_action",
    "_combined_opponent_threshold",
    "_combined_self_threshold",
    "_confirm_fold",
    "_extract_hand_value",
    "_game_result_notification",
    "_hand_threshold_for_actual_win_probability",
    "_in_hand",
    "_is_raise_action",
    "_normalize_hand_type",
    "_notify_game_result",
    "_opponent_counts",
    "_opponent_hand_threshold",
    "_opponent_threshold",
    "_parse_hand",
    "_range_factor",
    "_ranged_win_probability",
    "_seen_factor",
    "_seen_opponent_ranges",
    "_self_hand",
    "_snapshot_for_actor",
    "_update_round_tracker",
    "start",
    "stop",
]

_poll_task: asyncio.Task[None] | None = None


async def _request_fold(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    hand: str,
    hand_type: str,
    choice: _Choice,
    tracker: _RoundTracker,
) -> bool:
    """请求弃牌；需要双击时延后通知，确认完成后只通知一次。"""
    result = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if not result.get("ok"):
        ctx.log.warning("弃牌请求失败: %s", result.get("error"))
        return False

    needs_confirm = bool((result.get("game") or game).get("self", {}).get("foldConfirm", False))
    if needs_confirm:
        tracker.pending_fold = _PendingFold(game.get("roundId"), hand, hand_type, choice)
        ctx.log.info("弃牌等待二次确认，通知将在确认成功后发送")
        return True

    if cfg.get("zjh_notify_hand", True):
        await ctx.notify(_fold_notification(game.get("roundId"), hand, hand_type, choice.reason, choice.decision))
    return False


async def _confirm_fold(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    tracker: _RoundTracker,
) -> bool:
    """尝试一次双击确认弃牌：成功推送弃牌通知并清空待确认状态后返回 True，失败返回 False。

    失败时保留 `tracker.pending_fold`，由调用方按重试计数决定是否继续；
    成功或放弃时才清空，避免门户持续拒绝时每轮无限重发。
    """
    result = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if not result.get("ok"):
        ctx.log.warning("确认弃牌失败: %s", result.get("error"))
        return False

    pending = tracker.pending_fold
    if cfg.get("zjh_notify_hand", True) and pending is not None:
        await ctx.notify(
            _fold_notification(
                pending.rid,
                pending.hand,
                pending.hand_type,
                pending.choice.reason,
                pending.choice.decision,
            )
        )
    if cfg.get("zjh_notify_fold_confirm", False):
        await ctx.notify("🃏 双击确认弃牌")
    tracker.pending_fold = None
    return True


async def _act_on_hand(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    hand: str,
    hand_type: str,
    fallback_threshold: float,
    tracker: _RoundTracker,
    action_override: str | None = None,
) -> bool:
    """对已看牌手牌做 EV 决策，并执行服务器允许的动作。"""
    rid = game.get("roundId")
    hand_value = _extract_hand_value(hand_type, hand)
    choice = _choose(hand_type, hand_value, game, fallback_threshold, tracker, _RangeModel.from_config(cfg))
    _log_decision(ctx, hand, hand_type, hand_value, game, choice, tracker)

    decision = choice.decision
    actions = game.get("actions", [])

    if action_override and action_override in actions:
        action, reason = action_override, "对手发起比牌，服务端要求应战开牌"
    elif not choice.call:
        return await _request_fold(ctx, client, cfg, game, hand, hand_type, choice, tracker)
    else:
        action, reason = _choose_action(
            choice,
            actions if isinstance(actions, list) else [],
            bool(cfg.get("zjh_open_enabled", False)),
            float(cfg.get("zjh_open_max_win_rate", 50)) / 100,
            bool(cfg.get("zjh_raise_enabled", False)),
            float(cfg.get("zjh_raise_min_win_rate", 75)) / 100,
        )

    if action in {"call", "raise", "open"}:
        _record_self_threshold(game, tracker, "continue", ctx.log)
    if action_override:
        ctx.log.info(
            "应战开牌: 牌桌=%s phase=%r alive=%s isTurn=%s actions=%s",
            rid,
            game.get("phase"),
            game.get("self", {}).get("alive"),
            game.get("self", {}).get("isTurn"),
            actions,
        )
    ctx.log.info("执行动作[%s]：%s；服务端可用动作=%s", action, reason, actions)
    result = await client.post("/api/portal/zhajinhua/action", {"action": action})
    if not result.get("ok"):
        ctx.log.warning(
            "动作[%s]请求失败: %s；牌桌=%s phase=%r self=%s actions=%s",
            action,
            result.get("error"),
            rid,
            game.get("phase"),
            game.get("self", {}),
            actions,
        )
        return False
    if cfg.get("zjh_notify_hand", True) and decision is not None:
        await ctx.notify(
            _action_notification(action, rid, hand, hand_type, decision, game["pot"], game["callBet"], reason)
        )
    return False


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    interval = float(cfg.get("zjh_poll_interval", 2) or 2)
    fold_pending = False
    fold_retry = 0
    turns_taken = 0
    last_rid: Any = None
    tracker = _RoundTracker()
    round_joined = False
    last_round_hand = ""
    last_round_hand_type = ""

    async with HdskyClient(log=ctx.log) as client:
        client.set_renewer(hdsky_auth.renewer_for(ctx))  # 401 时自动续期并重试
        while True:
            try:
                if not cfg.get("zjh_enabled", True):
                    await asyncio.sleep(interval)
                    continue

                # 每轮读最新配置（cookie 路径/门户地址可能被改）
                client.configure(
                    str(cfg.get("hdsky_cookie_file", "") or ""),
                    str(cfg.get("hdsky_base_url", "") or ""),
                    debug_enabled=bool(cfg.get("hdsky_debug", False)),
                    debug_file=str(cfg.get("hdsky_debug_file", "") or ""),
                )
                seen_threshold = float(cfg.get("zjh_peeked_threshold", 50)) / 100

                # 获取牌局状态
                game_data = await client.get("/api/portal/zhajinhua")
                if "_error" in game_data:
                    ctx.log.warning("API 请求失败: %s", game_data["_error"])
                    client.reset_csrf()
                    await asyncio.sleep(interval)
                    continue

                g = game_data.get("game", {})
                rid = g.get("roundId")
                if rid and rid != last_rid:
                    # 上一局结束，推送结果
                    if last_rid and round_joined:
                        await _notify_game_result(ctx, cfg, game_data, last_round_hand, last_round_hand_type)
                    last_rid = rid
                    turns_taken = 0
                    # 新一局：待确认弃牌属于上一局，连同重试计数一起重置，
                    # 避免上一局的弃牌确认泄漏到新一局产生异常 fold 动作。
                    fold_pending = False
                    fold_retry = 0
                    tracker = _RoundTracker()
                    round_joined = False
                    last_round_hand = ""
                    last_round_hand_type = ""
                s = g.get("self", {})
                # 弃牌/出局后本局不再有任何决策，停止跟踪对手快照与门槛推导。
                # 否则对手互相缠斗时门槛会递归虚高（单挑反推的不动点在 1.0，
                # 轮流下注单调收敛到 1.0），纯属无用计算还把日志刷花。
                if _in_hand(g):
                    _update_round_tracker(g, tracker, ctx.log)
                phase = g.get("phase", "")
                actions = g.get("actions", [])
                joined = s.get("joined", False)
                is_turn = s.get("isTurn", False)
                alive = s.get("alive", False)
                hand = s.get("hand", "")
                hand_type = _normalize_hand_type(s.get("handType", ""))

                # 没加入且可加入 → 加入
                if not joined and "join" in actions:
                    ctx.log.info("加入牌桌 #%s...", rid)
                    r = await client.post("/api/portal/zhajinhua/join", {})
                    if r.get("ok"):
                        ctx.log.info("加入成功！")
                        if cfg.get("zjh_notify_join", True):
                            await ctx.notify(f"🃏 加入牌桌 #{rid}")
                    else:
                        ctx.log.warning("加入失败: %s", r.get("error"))

                # 轮到我了
                if fold_pending and alive and is_turn:
                    # 双击确认弃牌优先于已看牌的常规决策，避免重复发送弃牌请求/通知。
                    if fold_retry >= _FOLD_CONFIRM_MAX_RETRIES:
                        # 连续失败超限：放弃本局确认并清空状态，避免门户持续拒绝时每轮无限重发。
                        ctx.log.warning("确认弃牌连续失败 %d 次，放弃本局确认", fold_retry)
                        fold_pending = False
                        fold_retry = 0
                        tracker.pending_fold = None
                    elif await _confirm_fold(ctx, client, cfg, tracker):
                        ctx.log.info("确认弃牌成功")
                        fold_pending = False
                        fold_retry = 0
                    else:
                        fold_retry += 1

                elif joined and is_turn and isinstance(actions, list) and actions:
                    if hand:
                        # 服务端 actions 是动作授权的唯一来源；showdown 出现时优先应战。
                        action_override = _action_override(actions)
                        fold_pending = await _act_on_hand(
                            ctx,
                            client,
                            cfg,
                            g,
                            hand,
                            hand_type,
                            seen_threshold,
                            tracker,
                            action_override,
                        )
                    else:
                        # 蒙牌：无论单挑还是多人，都按 EV 决定「蒙牌半价盲跟」还是「看牌买信息」。
                        # EV≥0 时盲跟本身划算；EV<0 时看牌获取信息，随后按真实手牌正常决策。
                        blind_action, blind_choice = _blind_peek_or_call(g, actions, seen_threshold, tracker)
                        if blind_choice is not None:
                            ctx.log.info(
                                "蒙牌决策[%s]: 平均胜率=%.4f 蒙=%d 看=%d 底池=%.0f 半价成本=%.0f EV=%+.2f",
                                {"call": "盲跟", "peek": "看牌"}.get(blind_action or "", "无可执行动作"),
                                blind_choice.win_probability,
                                blind_choice.blind_opponents,
                                blind_choice.seen_opponents,
                                g.get("pot", 0),
                                _blind_call_cost(float(g.get("callBet", 0))),
                                blind_choice.expected_value,
                            )
                        if blind_action == "call":
                            await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            turns_taken += 1
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(
                                    _blind_notification(
                                        "call",
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        "蒙牌半价盲跟本身就划算（EV≥0），不看牌避免翻倍投入",
                                    )
                                )
                        elif blind_action == "peek":
                            if blind_choice is None:
                                ctx.log.info("牌局数据不完整，看牌后按实际手牌决策")
                            if cfg.get("zjh_notify_hand", True):
                                peek_reason = (
                                    "牌局数据不完整，先看牌再按实际手牌决策"
                                    if blind_choice is None
                                    else "蒙牌平均手牌不划算（EV<0），看牌买信息——牌大再上、牌小弃"
                                )
                                await ctx.notify(
                                    _blind_notification(
                                        "peek",
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        peek_reason,
                                    )
                                )
                            _record_self_threshold(g, tracker, "peek", ctx.log)
                            r = await client.post("/api/portal/zhajinhua/action", {"action": "peek"})
                            if r.get("ok"):
                                peek_game = r.get("game")
                                if isinstance(peek_game, dict):
                                    g = peek_game
                                # 看牌响应里手牌可能还没就绪：重拉状态补齐，别因读不到手牌就弃牌
                                g, hand, hand_type = await _acquire_hand_after_peek(client, g)
                                if not hand:
                                    # 仍读不到手牌：本轮不决策（绝不弃牌），等下次轮询补齐手牌再走正常决策
                                    ctx.log.warning("看牌后仍读不到手牌，本轮不决策，等下次轮询补齐")
                                else:
                                    ctx.log.info("手牌: %s (%s)", hand, hand_type)
                                    peek_actions = g.get("actions", [])
                                    action_override = _action_override(peek_actions)
                                    fold_pending = await _act_on_hand(
                                        ctx,
                                        client,
                                        cfg,
                                        g,
                                        hand,
                                        hand_type,
                                        seen_threshold,
                                        tracker,
                                        action_override,
                                    )
                        else:
                            ctx.log.warning(
                                "轮到我方但没有可执行的预期动作: 牌桌=%s phase=%r actions=%s hand=%s turns=%d",
                                rid,
                                phase,
                                actions,
                                bool(hand),
                                turns_taken,
                            )

                # 新牌局 CSRF 作废（轮次状态已在本轮开头完成重置）
                if phase == "waiting" and rid and not joined:
                    client.reset_csrf()

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                ctx.log.error("轮询异常: %r", e)
                if cfg.get("zjh_notify_error", True):
                    await ctx.notify(f"⚠️ 炸金花轮询异常: {e}", level="warning")
                await asyncio.sleep(interval * 2)


def start(ctx: object) -> None:
    """启动炸金花轮询任务。"""
    global _poll_task
    _poll_task = asyncio.create_task(_poll_loop(ctx))
    ctx.log.info("炸金花已启动")


def stop(ctx: object) -> None:
    """停止炸金花轮询任务。"""
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        _poll_task = None
    ctx.log.info("炸金花已停止")
