# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 认证与传输由 HdskyClient 封装，本模块只写「接口 + 参数」：
#   - 每 zjh_poll_interval 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 蒙牌按 EV 决策「蒙还是看」：蒙牌跟注成本为已看牌一半，EV ≥ 0 继续盲跟；
#     EV < 0 看牌买信息，牌大再上、牌小弃（不区分单挑/多人）
#   - 看牌后完全按增量期望收益（EV）决策：EV 在弃牌容差内跟注，否则弃牌（不区分单挑/多人）
#   - 无「服务端强制应战」规则：开/加/跟/弃/应战全由 EV 驱动；强制摊牌阶段（actions 无 call）
#     EV 支持继续时选 showdown/raise，该弃就弃
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

from .. import hdsky_auth
from ..hdsky import HdskyClient
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
    _actual_win_probability,
    _blind_call_cost,
    _blind_decision,
    _blind_peek_or_call,
    _blind_peek_reason,
    _blind_vs_seen_win,
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
    _opponent_raise_threshold,
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
    _terminal_ev_call,
    _terminal_ev_decision,
    _TerminalBranch,
    _TerminalDecision,
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
from .zjh_profile import feed_last_result, get_store, reset_store
from .zjh_state import _in_hand, _is_self, _opponent_counts, _player_key, _players

__all__ = [
    "_FOLD_CONFIRM_MAX_RETRIES",
    "_NEUTRAL_RANGE_MODEL",
    "_OpponentSnapshot",
    "_PendingFold",
    "_RangeModel",
    "_RoundTracker",
    "_SeenRange",
    "_Choice",
    "_TerminalBranch",
    "_TerminalDecision",
    "_acquire_hand_after_peek",
    "_act_on_hand",
    "_action_notification",
    "_actual_win_probability",
    "_blind_call_cost",
    "_blind_decision",
    "_blind_notification",
    "_blind_peek_or_call",
    "_blind_peek_reason",
    "_blind_vs_seen_win",
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
    "_opponent_raise_threshold",
    "_opponent_threshold",
    "_parse_hand",
    "_range_factor",
    "_ranged_win_probability",
    "_seen_factor",
    "_seen_opponent_ranges",
    "_self_hand",
    "_snapshot_for_actor",
    "_terminal_ev_call",
    "_terminal_ev_decision",
    "_train_opponent_actions",
    "_update_round_tracker",
    "feed_last_result",
    "get_store",
    "reset_store",
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
    profile: object | None = None,
) -> bool:
    """对已看牌手牌做 EV 决策，并执行服务器允许的动作。

    无「服务端强制应战」规则：开/加/跟/弃/应战全部由 EV 驱动（_choose + _choose_action）。
    强制摊牌阶段（actions 无 call）EV 支持继续时，_choose_action 会选 showdown/raise。
    profile：对手画像（ProfileStore），非空时已看牌胜率接入实测收缩混合 + 逐对手诈唬率。
    """
    rid = game.get("roundId")
    hand_value = _extract_hand_value(hand_type, hand)
    choice = _choose(
        hand_type,
        hand_value,
        game,
        fallback_threshold,
        tracker,
        _RangeModel.from_config(cfg),
        float(cfg.get("zjh_fold_ev_tolerance", 0) or 0),
        profile,
    )
    _log_decision(ctx, hand, hand_type, hand_value, game, choice, tracker)

    decision = choice.decision
    actions = game.get("actions", [])

    if not choice.call:
        return await _request_fold(ctx, client, cfg, game, hand, hand_type, choice, tracker)
    # 本局首次已看牌决策（tracker 每局重建）：大牌慢打不加注，避免第一次看牌就加注吓退对手
    first_peek = not tracker.seen_acted
    tracker.seen_acted = True
    action, reason = _choose_action(
        choice,
        actions if isinstance(actions, list) else [],
        bool(cfg.get("zjh_open_enabled", False)),
        float(cfg.get("zjh_open_max_win_rate", 50)) / 100,
        bool(cfg.get("zjh_raise_enabled", False)),
        float(cfg.get("zjh_raise_min_win_rate", 75)) / 100,
        float(cfg.get("zjh_raise_frequency", 100)) / 100,
        first_peek and bool(cfg.get("zjh_first_peek_no_raise", True)),
    )

    if action in {"call", "raise", "open", "showdown"}:
        _record_self_threshold(game, tracker, "continue", ctx.log)
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


def _train_opponent_actions(
    store: object,
    game: dict[str, Any],
    last_seen: dict[str, tuple[str, float]],
    round_action: dict[str, str] | None = None,
    raise_freq_recorded: set[str] | None = None,
) -> None:
    """每轮训练画像：遍历所有存活对手，检测动作变化并去重记录。

    与旧 `_train_opponent_action`（只在蒙牌分支、只记首个对手、不去重）相比：
    - 覆盖所有时机（bot 看牌后、对手行动中、多人局全部对手）；
    - 用 last_seen 签名（lastAction + bet）去重：同一动作只在变化时记一次，
      避免轮询重复计数把跟注/加注频率撑高。
    last_seen 由调用方在 `_poll_loop` 维护（跨局重置），键为对手 uid，
    值为 (lastAction, bet) 签名。
    round_action：本轮各对手最激进动作 {uid: "raise"|"call"}（raise 覆盖 call），
    供结算回填按实际动作分桶；None 时不维护。
    raise_freq_recorded：本轮已记录加注频率的对手 uid 集合，防止同局多次调用
    record_raise_freq；None 时不记录加注频率。
    """
    for index, player in enumerate(_players(game)):
        if _is_self(player):
            continue
        if not (player.get("alive") or player.get("active", False)):
            continue
        uid = _player_key(player, index)
        current_action = str(player.get("lastAction", "") or "")
        current_bet = player.get("bet")
        current_bet_f = float(current_bet) if isinstance(current_bet, (int, float)) else 0.0
        signature = (current_action, current_bet_f)
        if last_seen.get(uid) == signature:
            continue  # 动作未变，不重复记录
        last_seen[uid] = signature
        action: str | None = None
        if "追加" in current_action or "raise" in current_action.lower():
            action = "raise"
        elif "跟注" in current_action or "call" in current_action.lower():
            action = "call"
        elif "弃" in current_action or "fold" in current_action.lower():
            action = "fold"
        if action is None:
            continue  # 报名等非决策动作不计入（但已更新签名，避免反复尝试）
        op_seen = bool(player.get("seen", False))
        blind_count, seen_count = _opponent_counts(game)  # (蒙牌数, 看牌数)
        # 排除当前对手自身
        adj_seen = seen_count - (1 if op_seen else 0)
        adj_blind = blind_count - (0 if op_seen else 1)
        if round_action is not None and action in ("raise", "call"):
            # 最激进动作优先：加注覆盖平跟（结算回填据此区分加注/平跟手牌分位）
            # 同时存储当时牌局状态桶参数 (action, op_seen, adj_seen, adj_blind)
            if action == "raise" or round_action.get(uid) is None or round_action[uid][0] != "raise":  # type: ignore[index]
                round_action[uid] = (action, op_seen, adj_seen, adj_blind)
        store.record_action(
            uid,
            action,
            op_seen,
            adj_seen,
            adj_blind,
            display_name=str(player.get("displayName", "") or ""),
        )
        # 每局每个对手只记一次加注频率（首次动作变更时）
        if raise_freq_recorded is not None and uid not in raise_freq_recorded:
            blind_count, seen_count = _opponent_counts(game)  # (蒙牌数, 看牌数)
            # 排除当前对手自身
            adj_seen = seen_count - (1 if op_seen else 0)
            adj_blind = blind_count - (0 if op_seen else 1)
            store.record_raise_freq(uid, op_seen, adj_seen, adj_blind, action == "raise")
            raise_freq_recorded.add(uid)


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
    # 对手画像：进程内缓存 + 延迟写 kv（get_store 首次调用加载已有画像）
    profile_store = get_store(ctx.kv)
    # 连续盲跟计数：同一 roundId 内累计，达上限强制看牌
    blind_calls_so_far = 0
    # 本局 displayName→id 映射（结算回填画像用）
    uid_by_display: dict[str, str] = {}
    # 对手动作去重签名：uid → (lastAction, bet)，跨局重置
    last_opponent_seen: dict[str, tuple[str, float]] = {}
    # 本轮各对手最激进动作 uid → (action, op_seen, seen_count, blind_count)（结算回填分桶用）
    round_opponent_action: dict[str, tuple[str, bool, int, int]] = {}
    # 本轮已记录加注频率的对手 uid（同局只记一次，避免重复计）
    round_raise_freq_recorded: set[str] = set()
    # 刚结束那局（lastResult 待回填）的对手动作快照：lastResult 滞后一局，
    # roundId 切换时把当前轮动作移入此变量，供随后到达的 lastResult 回填取用
    settled_round_action: dict[str, tuple[str, bool, int, int]] = {}
    # 已回填的结算局 roundId（同一局 lastResult 每轮重复出现，只回填一次）
    last_fed_result_rid: Any = None

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
                    blind_calls_so_far = 0
                    last_round_hand = ""
                    last_round_hand_type = ""
                    uid_by_display = {}
                    last_opponent_seen = {}
                    last_fed_result_rid = None
                    # 上一局动作移入 settled，供随后到达的 lastResult 回填；本轮重新累计
                    settled_round_action = round_opponent_action
                    round_opponent_action = {}
                    round_raise_freq_recorded = set()

                # 每轮更新 displayName→id 映射；新一局结算回填对手真实手牌分位到画像
                for index, player in enumerate(_players(g)):
                    pid = _player_key(player, index)
                    display = player.get("displayName")
                    if pid and display:
                        uid_by_display[display] = pid
                last_result = game_data.get("game", {}).get("lastResult")
                last_result_rid = last_result.get("roundId") if isinstance(last_result, dict) else None
                if last_result_rid and last_result_rid != last_fed_result_rid:
                    feed_last_result(profile_store, game_data, uid_by_display, settled_round_action)
                    last_fed_result_rid = last_result_rid
                if cfg.get("zjh_profile_enabled", True):
                    profile_store.flush()
                s = g.get("self", {})
                # 每轮公共训练画像：遍历所有存活对手，检测动作变化去重记录
                if cfg.get("zjh_profile_enabled", True):
                    _train_opponent_actions(
                        profile_store,
                        g,
                        last_opponent_seen,
                        round_opponent_action,
                        round_raise_freq_recorded,
                    )
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
                        # 已看牌：EV 决策开/加/跟/弃/应战，无服务端强制应战规则。
                        fold_pending = await _act_on_hand(
                            ctx,
                            client,
                            cfg,
                            g,
                            hand,
                            hand_type,
                            seen_threshold,
                            tracker,
                            profile_store if cfg.get("zjh_profile_enabled", True) else None,
                        )
                    else:
                        # 蒙牌：用 Terminal EV 决策树决定「盲跟 / 看牌 / 弃牌」。
                        # 连续盲跟达上限强制看牌；对手动作概率来自画像。
                        # 取第一个存活对手 uid 作为画像键（单挑即为唯一对手，多人取首个）
                        opponent_uid: str | None = None
                        for index, player in enumerate(_players(g)):
                            if _is_self(player):
                                continue
                            if player.get("alive") or player.get("active", False):
                                opponent_uid = _player_key(player, index)
                                break
                        # 画像动作概率：遍历所有存活对手，分别查画像然后取平均
                        # 多人局中各对手动作倾向不同，仅取第一个对手的代表性不足
                        action_probs: tuple[float, float, float] | None = None
                        if cfg.get("zjh_profile_enabled", True):
                            blind_count, seen_count = _opponent_counts(g)
                            collected: list[tuple[float, float, float]] = []
                            for index, player in enumerate(_players(g)):
                                if _is_self(player):
                                    continue
                                if not (player.get("alive") or player.get("active", False)):
                                    continue
                                uid = _player_key(player, index)
                                op_seen = bool(player.get("seen", False))
                                adj_seen = seen_count - (1 if op_seen else 0)
                                adj_blind = blind_count - (0 if op_seen else 1)
                                collected.append(profile_store.action_probabilities(uid, op_seen, adj_seen, adj_blind))
                            if collected:
                                avg_fold = sum(p[0] for p in collected) / len(collected)
                                avg_call = sum(p[1] for p in collected) / len(collected)
                                avg_raise = sum(p[2] for p in collected) / len(collected)
                                action_probs = (avg_fold, avg_call, avg_raise)
                        blind_action, blind_choice = _blind_peek_or_call(
                            g,
                            actions,
                            seen_threshold,
                            tracker,
                            profile=profile_store if cfg.get("zjh_profile_enabled", True) else None,
                            depth=int(cfg.get("zjh_terminal_depth", 2) or 2),
                            max_blind_calls=int(cfg.get("zjh_blind_max_calls", 0) or 0),
                            blind_calls_so_far=blind_calls_so_far,
                            action_probs=action_probs,
                            opponent_uid=opponent_uid,
                        )
                        if blind_choice is not None:
                            _action_label = {
                                "call": "盲跟",
                                "peek": "看牌",
                                "showdown": "应战",
                                "open": "主动开牌",
                                "fold": "弃牌",
                            }.get(blind_action or "", "无可执行动作")
                            if isinstance(blind_choice, _TerminalDecision):
                                ev_val = blind_choice.terminal_ev
                                ctx.log.info(
                                    "蒙牌决策[%s]: 终局EV=%+.2f（盲跟%+.2f · 看牌%+.2f · 弃牌0）"
                                    " 底池=%.0f 半价成本=%.0f 对手动作概率=%s",
                                    _action_label,
                                    ev_val,
                                    blind_choice.call_ev,
                                    blind_choice.peek_ev,
                                    g.get("pot", 0),
                                    _blind_call_cost(float(g.get("callBet", 0))),
                                    f"{action_probs[0]:.2f}/{action_probs[1]:.2f}/{action_probs[2]:.2f}"
                                    if action_probs
                                    else "先验",
                                )
                            else:
                                ev_val = blind_choice.expected_value
                        if blind_action in ("showdown", "open"):
                            await client.post("/api/portal/zhajinhua/action", {"action": blind_action})
                            turns_taken += 1
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(
                                    _blind_notification(
                                        blind_action,
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        "蒙牌终局EV≥0，直接开牌结束本轮避免对手加注后投入翻倍",
                                    )
                                )
                        elif blind_action == "call":
                            await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            turns_taken += 1
                            blind_calls_so_far += 1
                            if cfg.get("zjh_notify_hand", True):
                                await ctx.notify(
                                    _blind_notification(
                                        "call",
                                        rid,
                                        blind_choice,
                                        float(g.get("pot", 0) or 0),
                                        float(g.get("callBet", 0) or 0),
                                        "蒙牌终局EV盲跟最优（EV≥0），不看牌避免翻倍投入",
                                    )
                                )
                        elif blind_action == "peek":
                            if isinstance(blind_choice, _TerminalDecision):
                                ctx.log.info(
                                    "蒙牌决策[看牌]: 终局EV=%+.2f（盲跟%+.2f · 看牌%+.2f · 弃牌0）"
                                    " 底池=%.0f 半价成本=%.0f 对手动作概率=%s",
                                    blind_choice.terminal_ev,
                                    blind_choice.call_ev,
                                    blind_choice.peek_ev,
                                    g.get("pot", 0),
                                    _blind_call_cost(float(g.get("callBet", 0))),
                                    f"{action_probs[0]:.2f}/{action_probs[1]:.2f}/{action_probs[2]:.2f}"
                                    if action_probs
                                    else "先验",
                                )
                            elif blind_choice is None:
                                ctx.log.info("牌局数据不完整，看牌后按实际手牌决策")
                            if cfg.get("zjh_notify_hand", True):
                                peek_reason = _blind_peek_reason(blind_choice, actions)
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
                                    fold_pending = await _act_on_hand(
                                        ctx,
                                        client,
                                        cfg,
                                        g,
                                        hand,
                                        hand_type,
                                        seen_threshold,
                                        tracker,
                                        profile_store if cfg.get("zjh_profile_enabled", True) else None,
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
