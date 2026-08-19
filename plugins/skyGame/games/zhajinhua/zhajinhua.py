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

from .. import drop_guard, hdsky_auth
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
    _TERMINAL_RESEND_MAX,
    _actual_win_probability,
    _blind_call_cost,
    _blind_decision,
    _blind_peek_or_call,
    _blind_peek_reason,
    _blind_vs_seen_win,
    _blind_win_probability,
    _BlindOpponent,
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
    _opponents_win_probability,
    _OpponentSnapshot,
    _peek_terminal_ev,
    _PendingFold,
    _range_factor,
    _ranged_win_probability,
    _record_self_threshold,
    _RoundTracker,
    _seen_factor,
    _seen_opponent_ranges,
    _SeenRange,
    _self_action_probs,
    _snapshot_for_actor,
    _terminal_ev_call,
    _terminal_ev_call_multi,
    _terminal_ev_decision,
    _terminal_ev_peek_multi,
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
from .zjh_profile import (
    HALF_LIFE_SAMPLES,
    feed_last_result,
    get_store,
    record_round_raise_freq,
    reset_store,
)
from .zjh_state import _in_hand, _is_self, _opponent_counts, _player_key, _players
from .zjh_stats import record_round_result

__all__ = [
    "_FOLD_CONFIRM_MAX_RETRIES",
    "_TERMINAL_RESEND_MAX",
    "_OpponentSnapshot",
    "_PendingFold",
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
    "_opponents_win_probability",
    "_parse_hand",
    "_peek_terminal_ev",
    "_range_factor",
    "_ranged_win_probability",
    "_request_blind_fold",
    "_seen_factor",
    "_seen_opponent_ranges",
    "_self_hand",
    "_self_action_probs",
    "_snapshot_for_actor",
    "_terminal_action_ineffective",
    "_terminal_action_or_fallback",
    "_terminal_ev_call",
    "_terminal_ev_call_multi",
    "_terminal_ev_decision",
    "_terminal_ev_peek_multi",
    "_train_opponent_actions",
    "_update_round_tracker",
    "feed_last_result",
    "get_store",
    "record_round_raise_freq",
    "record_round_result",
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


async def _request_blind_fold(
    ctx: object,
    client: HdskyClient,
    cfg: dict,
    game: dict[str, Any],
    terminal: _TerminalDecision,
    tracker: _RoundTracker,
) -> bool:
    """蒙牌决策树判定弃牌最优时提交 fold（线上曾漏：只打告警不提交，卡死到门户超时）。

    与已看牌弃牌同一动作端点与双击确认机制：需要 foldConfirm 时把预构建的
    蒙牌弃牌通知存入 `tracker.pending_fold`，由 `_confirm_fold` 确认后推送。
    返回 True 表示弃牌已提交且正在等待确认（调用方置 fold_pending）。
    """
    result = await client.post("/api/portal/zhajinhua/action", {"action": "fold"})
    if not result.get("ok"):
        ctx.log.warning("蒙牌弃牌请求失败: %s", result.get("error"))
        return False

    notification = _blind_notification(
        "fold",
        game.get("roundId"),
        terminal,
        float(game.get("pot", 0) or 0),
        float(game.get("callBet", 0) or 0),
        terminal.reason,
    )
    needs_confirm = bool((result.get("game") or game).get("self", {}).get("foldConfirm", False))
    if needs_confirm:
        tracker.pending_fold = _PendingFold(game.get("roundId"), "", "", None, notification)
        ctx.log.info("蒙牌弃牌等待二次确认，通知将在确认成功后发送")
        return True

    if cfg.get("zjh_notify_hand", True):
        await ctx.notify(notification)
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
        if pending.notification:
            # 蒙牌弃牌：通知文本已在请求时预构建（未看牌无手牌，不走已看牌弃牌样式）
            await ctx.notify(pending.notification)
        elif pending.choice is not None:
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
    # 深度 EV 反推对手门槛（v1.16.20）：深度与 zjh_terminal_depth 一致，我方已看牌
    # 全价下注，我方行动概率查我方账号画像（把我也作为一个用户）。
    depth = int(cfg.get("zjh_terminal_depth", 2) or 2)
    choice = _choose(
        hand_type,
        hand_value,
        game,
        fallback_threshold,
        tracker,
        float(cfg.get("zjh_fold_ev_tolerance", 0) or 0),
        profile,
        depth,
        True,
    )
    _log_decision(ctx, hand, hand_type, hand_value, game, choice, tracker, fallback_threshold, depth, profile, True)

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
        float(cfg.get("zjh_open_max_win_rate", 50)) / 100,
        bool(cfg.get("zjh_raise_enabled", False)),
        float(cfg.get("zjh_raise_min_win_rate", 75)) / 100,
        float(cfg.get("zjh_raise_frequency", 100)) / 100,
        first_peek and bool(cfg.get("zjh_first_peek_no_raise", True)),
        float(cfg.get("zjh_signal_mix_prob", 10)) / 100,
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
        client.reset_csrf()
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
    round_action: dict[str, tuple[str, bool, int, int, bool]] | None = None,
) -> None:
    """每轮训练画像：遍历所有玩家（含我方），检测动作变化并去重记录。

    - 我方动作也入画像（v1.16.20「把我也作为一个用户」）：反推对手门槛时站在
      对手视角，我方的 call/raise 倾向决定对手后续轮次的追平/加注成本，查询
      我方账号自己的画像得到行动概率。我方不在 _opponent_counts 计数内，
      adj_seen/adj_blind 直接用其返回的对手蒙/看数（不减自己）。
    - 覆盖所有时机（bot 看牌后、对手行动中、多人局全部玩家）；
    - 用 last_seen 签名（lastAction + bet）去重：同一动作只在变化时记一次，
      避免轮询重复计数把跟注/加注频率撑高。
    - 已出局（alive=False）玩家只记录 fold：实测门户在弃牌的同一快照就把
      alive 置 false（lastAction='弃牌' 只在死人状态可见），若跳过死人，
      fold 永远进不了画像，继续频率分母缺失会系统性高估诈唬率。
    last_seen 由调用方在 `_poll_loop` 维护（跨局重置），键为玩家 uid，
    值为 (lastAction, bet) 签名。
    round_action：本轮各玩家最激进动作 {uid: "raise"|"call"}（raise 覆盖 call），
    供结算回填按实际动作分桶；None 时不维护。
    """
    for index, player in enumerate(_players(game)):
        is_self = _is_self(player)
        alive = bool(player.get("alive") or player.get("active", False))
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
        if not alive and action != "fold":
            continue  # 出局玩家只有弃牌这一种新动作值得记录
        op_seen = bool(player.get("seen", False))
        blind_count, seen_count = _opponent_counts(game)  # (蒙牌数, 看牌数)，不含我方
        if is_self:
            # 我方不在对手计数里，邻接计数就是全部对手的蒙/看数，无需排除自己
            adj_seen = seen_count
            adj_blind = blind_count
        elif alive:
            # 存活对手计入计数，排除当前对手自身
            adj_seen = seen_count - (1 if op_seen else 0)
            adj_blind = blind_count - (0 if op_seen else 1)
        else:
            # 出局玩家已被 _opponent_counts 排除在计数外，当前存活的其他对手
            # 即近似其弃牌时刻的牌局上下文（首条观察到弃牌的轮询快照）
            adj_seen = seen_count
            adj_blind = blind_count
        if round_action is not None and action in ("raise", "call"):
            # 最激进动作优先：加注覆盖平跟（结算回填据此区分加注/平跟手牌分位）
            # 同时存储当时牌局状态桶参数 (action, op_seen, adj_seen, adj_blind, forced)
            # forced：摊牌阶段（phase=showdown）的 raise/call 标记。摊牌阶段 raise 是
            # 强牌信号（弱牌玩家有 fold/showdown 便宜出口不会白 raise，牌好才不想开、
            # 用 raise 榨取价值——用户确认 2026-08-08），因此动作桶照记、分位照回填；
            # forced 仅用于 record_round_raise_freq 豁免（continue 率的诈唬下界解读
            # 不适用于强牌 raise，v1.16.16 保留 v1.16.14 此一处豁免）。
            forced = game.get("phase") == "showdown"
            if action == "raise" or round_action.get(uid) is None or round_action[uid][0] != "raise":  # type: ignore[index]
                round_action[uid] = (action, op_seen, adj_seen, adj_blind, forced)
        # 动作桶照记（含摊牌阶段 raise/call——真实加注信号）；fold 记录照常
        store.record_action(
            uid,
            action,
            op_seen,
            adj_seen,
            adj_blind,
            display_name=str(player.get("displayName", "") or ""),
        )


def _terminal_action_ineffective(
    last_terminal_action: str | None, alive: bool, is_turn: bool, actions: list[Any]
) -> bool:
    """上一轮发送的终局动作（showdown/open）是否未生效。

    判据：仍是我方回合、仍存活、且该动作仍在可用列表里——说明门户没有执行
    （如多人局不支持 open、或响应 ok 但状态未推进）。此时应清除去重标记允许重发，
    否则会一直被「已发送过」拦截、卡死到门户行动超时（线上 #6109 连续 9 轮判应战全被跳过）。
    真正生效后 roundId 变化会重建 tracker、或不再 isTurn，不会误判。
    """
    return bool(last_terminal_action and alive and is_turn and last_terminal_action in actions)


def _terminal_action_or_fallback(blind_action: str | None, terminal_resent: int, actions: list[Any]) -> str | None:
    """终局动作重发超限（_TERMINAL_RESEND_MAX）时回退看牌/盲跟。

    门户持续不执行 showdown/open（多人局常不开放）时，继续重发只会空转到行动超时；
    看牌免费、信息永不亏，是安全回退；无看牌才退盲跟。未超限或非终局动作原样返回。
    """
    if blind_action in ("showdown", "open") and terminal_resent >= _TERMINAL_RESEND_MAX:
        if "peek" in actions:
            return "peek"
        if "call" in actions:
            return "call"
    return blind_action


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
    # 对手画像：进程内缓存 + 延迟写 kv（get_store 首次调用加载已有画像，半衰期按次数/手数）
    profile_store = get_store(ctx.kv, float(cfg.get("zjh_profile_halflife", HALF_LIFE_SAMPLES) or 0))
    # 连续盲跟计数：同一 roundId 内累计，达上限强制看牌
    blind_calls_so_far = 0
    # 终局动作（showdown/open）未生效重发计数：达上限回退看牌，防门户持续不执行时无限重发
    terminal_resent = 0
    # 本局 displayName→id 映射（结算回填画像用）
    uid_by_display: dict[str, str] = {}
    # 对手动作去重签名：uid → (lastAction, bet)，跨局重置
    last_opponent_seen: dict[str, tuple[str, float]] = {}
    # 本轮各对手最激进动作 uid → (action, op_seen, seen_count, blind_count)（结算回填分桶用）
    round_opponent_action: dict[str, tuple[str, bool, int, int, bool]] = {}
    # 刚结束那局（lastResult 待回填）的对手动作快照：lastResult 滞后一局，
    # roundId 切换时把当前轮动作移入此变量，供随后到达的 lastResult 回填取用
    settled_round_action: dict[str, tuple[str, bool, int, int, bool]] = {}
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
                    # 新一局开始：重置本局状态。战绩入账与结果通知不在此处——
                    # 线上结算后 roundId 直接变 None、lastResult 只出现在结算态响应
                    # （新局响应里已被清空），入账改由下方 lastResult 去重块驱动。
                    last_rid = rid
                    turns_taken = 0
                    # 新一局：待确认弃牌属于上一局，连同重试计数一起重置，
                    # 避免上一局的弃牌确认泄漏到新一局产生异常 fold 动作。
                    fold_pending = False
                    fold_retry = 0
                    tracker = _RoundTracker()
                    round_joined = False
                    blind_calls_so_far = 0
                    terminal_resent = 0
                    last_round_hand = ""
                    last_round_hand_type = ""
                    uid_by_display = {}
                    last_opponent_seen = {}
                    last_fed_result_rid = None
                    # 上一局动作移入 settled，供随后到达的 lastResult 回填；本轮重新累计
                    settled_round_action = round_opponent_action
                    round_opponent_action = {}

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
                    # 加注频率按结算时的最激进动作记录（修复 call 后 raise 被记成非加注），
                    # 并推进全场对手的衰减时钟（半衰期按手数，弃牌对手也按手数遗忘）
                    record_round_raise_freq(profile_store, settled_round_action, list(uid_by_display.values()))
                    last_fed_result_rid = last_result_rid
                    # 战绩入账 + 对局结果通知：与画像回填同步，正是结算到达时刻
                    # （lastResult 每轮重复出现，靠 last_fed_result_rid 每局去重一次）。
                    # 旧 v1.16.9 等 roundId 切换时入账，但线上结算态 roundId 变 None、
                    # 新局响应 lastResult 已被清空——从不入账、从不推送（用户反馈）。
                    if round_joined:
                        last_delta = record_round_result(ctx.kv, last_result)
                        await _notify_game_result(
                            ctx, cfg, game_data, last_round_hand, last_round_hand_type, last_delta
                        )
                if cfg.get("zjh_profile_enabled", True):
                    profile_store.flush()
                s = g.get("self", {})
                # 每轮公共训练画像：遍历所有对手，检测动作变化去重记录（死人只记 fold）
                if cfg.get("zjh_profile_enabled", True):
                    _train_opponent_actions(
                        profile_store,
                        g,
                        last_opponent_seen,
                        round_opponent_action,
                    )
                # 弃牌/出局后本局不再有任何决策，停止跟踪对手快照与门槛推导。
                # 否则对手互相缠斗时门槛会递归虚高（单挑反推的不动点在 1.0，
                # 轮流下注单调收敛到 1.0），纯属无用计算还把日志刷花。
                if _in_hand(g):
                    _update_round_tracker(g, tracker, ctx.log)
                phase = g.get("phase", "")
                actions = g.get("actions", [])
                joined = s.get("joined", False)
                # bot 已参局 → 置位 round_joined：战绩入账与对局结果通知的前提。
                # v1.16.9 曾只声明条件变量却从不置位，roundId 切换条件
                # `if last_rid and round_joined:` 恒不成立——战绩从不入账、结果通知从不推送。
                # joined 在参局期间持续为 True，幂等置位即可（每局切换时统一重置为 False）。
                if joined:
                    round_joined = True
                is_turn = s.get("isTurn", False)
                alive = s.get("alive", False)
                hand = s.get("hand", "")
                hand_type = _normalize_hand_type(s.get("handType", ""))

                # 终局动作（showdown/open）未生效检测：上一轮已发送过，但本局仍是我方回合
                # 且该动作仍在可用列表里——说明门户未执行（如多人局不支持 open、或响应 ok
                # 但状态未推进）。此时清除去重标记允许重发，否则会一直被「已发送过」拦截、
                # 卡死到门户行动超时（线上 #6109：连续 9 轮判应战全被跳过）。真正生效后
                # roundId 变化会重建 tracker、或不再 isTurn，不会误重发。
                if _terminal_action_ineffective(tracker.last_terminal_action, alive, is_turn, actions):
                    terminal_resent += 1
                    ctx.log.info(
                        "终局动作[%s]上轮已发但未生效（仍是我方回合且动作仍可用），清除去重允许重发（第%d次）",
                        tracker.last_terminal_action,
                        terminal_resent,
                    )
                    tracker.last_terminal_action = None

                # 没加入且可加入 → 加入
                if not joined and "join" in actions:
                    if drop_guard.paused(ctx):
                        ctx.log.debug("掉落配额已满，跳过炸金花牌桌 #%s 加入", rid)
                    else:
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
                        # 遍历所有存活对手，分别查画像构建决策树节点（每人独立动作概率），
                        # 而非旧版「取平均当单对手」——多人局各对手动作倾向不同。
                        blind_opponents: list[_BlindOpponent] = []
                        profile_enabled = cfg.get("zjh_profile_enabled", True)
                        if profile_enabled:
                            blind_count, seen_count = _opponent_counts(g)
                            for index, player in enumerate(_players(g)):
                                if _is_self(player):
                                    continue
                                if not (player.get("alive") or player.get("active", False)):
                                    continue
                                uid = _player_key(player, index)
                                op_seen = bool(player.get("seen", False))
                                adj_seen = seen_count - (1 if op_seen else 0)
                                adj_blind = blind_count - (0 if op_seen else 1)
                                probs = profile_store.action_probabilities(uid, op_seen, adj_seen, adj_blind)
                                # 深度 EV 反推对手门槛（v1.16.20）：我方蒙牌半价，
                                # 我方行动概率查我方账号画像（把我也作为一个用户）。
                                threshold = _combined_opponent_threshold(
                                    tracker.peek_snapshots.get(uid),
                                    tracker.snapshots.get(uid),
                                    None,
                                    int(cfg.get("zjh_terminal_depth", 2) or 2),
                                    _self_action_probs(g, profile_store, False),
                                    False,
                                    g.get("ante") if isinstance(g.get("ante"), (int, float)) else 0,
                                )
                                blind_opponents.append(
                                    _BlindOpponent(
                                        uid,
                                        op_seen,
                                        probs,
                                        threshold if threshold is not None else seen_threshold,
                                    )
                                )
                        blind_action, blind_choice = _blind_peek_or_call(
                            g,
                            actions,
                            seen_threshold,
                            tracker,
                            profile=profile_store if profile_enabled else None,
                            depth=int(cfg.get("zjh_terminal_depth", 2) or 2),
                            max_blind_calls=int(cfg.get("zjh_blind_max_calls", 0) or 0),
                            blind_calls_so_far=blind_calls_so_far,
                            opponents=blind_opponents or None,
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
                                    " 底池=%.0f 半价成本=%.0f 存活对手=%d 动作概率=%s",
                                    _action_label,
                                    ev_val,
                                    blind_choice.call_ev,
                                    blind_choice.peek_ev,
                                    g.get("pot", 0),
                                    _blind_call_cost(float(g.get("callBet", 0))),
                                    len(blind_opponents),
                                    " | ".join(
                                        f"{o.uid.split(':')[-1]}={o.action_probs[0]:.2f}/"
                                        f"{o.action_probs[1]:.2f}/{o.action_probs[2]:.2f}"
                                        for o in blind_opponents
                                    )
                                    if blind_opponents
                                    else "先验",
                                )
                            else:
                                ev_val = blind_choice.expected_value
                        # 终局动作重发超限：门户可能不支持该动作（多人局 open 不可用/未执行），
                        # 继续重发只会空转到行动超时——回退看牌买信息（看牌免费、永不亏）。
                        fallback_action = _terminal_action_or_fallback(blind_action, terminal_resent, actions)
                        if fallback_action != blind_action:
                            ctx.log.warning(
                                "终局动作[%s]重发 %d 次仍未生效，回退[%s]",
                                blind_action,
                                terminal_resent,
                                fallback_action,
                            )
                            blind_action = fallback_action
                        if blind_action in ("showdown", "open"):
                            # 去重：同一轮相同终局动作已发送过(CSRF失效后循环)则跳过
                            if tracker.last_terminal_action == blind_action:
                                ctx.log.warning(
                                    "终局动作[%s]已在本轮发送过(可能CSRF失效)，跳过重复请求",
                                    blind_action,
                                )
                            else:
                                r = await client.post("/api/portal/zhajinhua/action", {"action": blind_action})
                                if r.get("ok"):
                                    tracker.last_terminal_action = blind_action
                                    turns_taken += 1
                                else:
                                    ctx.log.warning(
                                        "终局动作[%s]请求失败: %s, 重置CSRF",
                                        blind_action,
                                        r.get("error") or r.get("_error", "未知错误"),
                                    )
                                    client.reset_csrf()
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
                            r = await client.post("/api/portal/zhajinhua/action", {"action": "call"})
                            if not r.get("ok"):
                                ctx.log.warning("盲跟请求失败: %s, 重置CSRF", r.get("error"))
                                client.reset_csrf()
                            else:
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
                        elif blind_action == "fold" and isinstance(blind_choice, _TerminalDecision):
                            # 决策树判定弃牌最优 → 立即提交（此前无此分支，
                            # fold 掉进尾部告警不提交，线上卡死到门户超时）
                            fold_pending = await _request_blind_fold(ctx, client, cfg, g, blind_choice, tracker)
                        elif blind_action == "peek":
                            # 决策明细已在上方通用块打印（含蒙牌决策[看牌]），此处仅补数据不完整场景
                            if blind_choice is None:
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
