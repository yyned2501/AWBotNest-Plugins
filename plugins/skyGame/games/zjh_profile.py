# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：按玩家 ID 的对手画像与动作概率统计
#
# 跨局记录每个对手在不同状态分桶下的动作频率（fold/call/raise），
# 供 Terminal EV 决策树（zjh_model._terminal_ev_decision）预测未来轮次对手行动。
# 持久化复用 learning/_social.py 的内存缓存 + 脏标记 + teardown flush 模式：
#   进程内 _cache 读写，标记脏桶，flush() 时批量写回 ctx.kv。
# 未知对手用全局先验（聚合所有对手的同桶频率）并向先验平滑。
#
# 只依赖标准库与 zjh_state / zjh_hand / zjh_prob，不产生副作用。

from __future__ import annotations

from typing import Any

from .zjh_hand import _extract_hand_value, _normalize_hand_type
from .zjh_prob import win_prob_1v1
from .zjh_state import _player_key, _players

# kv 键前缀
_KV_PREFIX = "zjh:profile:"

# 状态分桶维度：我方蒙/看 × 对手蒙/看 × 是否单挑
_MY_BLIND = "b"
_MY_SEEN = "s"
_OP_BLIND = "b"
_OP_SEEN = "s"
_HU = "hu"  # 单挑（对手仅剩1）
_MULTI = "multi"

# 画像字典键
_ACTIONS = "actions"  # {"fold": n, "call": n, "raise": n}
_N_HANDS = "n_hands"  # 本桶累计动作次数（供归一化）
_RAISE_PCTS = "raise_pcts"  # 加注后最终真实手牌分位（结算回填）
_CALL_PCTS = "call_pcts"  # 平跟后最终真实手牌分位
_TOTAL_HANDS = "total_hands"
_DISPLAY = "display_name"
_UPDATED = "updated_ms"

# 空动作计数
_EMPTY_ACTIONS = {"fold": 0, "call": 0, "raise": 0}


def _bucket(my_seen: bool, op_seen: bool, is_heads_up: bool) -> str:
    """构造状态分桶键：如 "b_b_hu"（我蒙、对手蒙、单挑）。"""
    my_side = _MY_SEEN if my_seen else _MY_BLIND
    op_side = _OP_SEEN if op_seen else _OP_BLIND
    heads = _HU if is_heads_up else _MULTI
    return f"{my_side}_{op_side}_{heads}"


class ProfileStore:
    """进程内对手画像缓存，延迟写回 ctx.kv。

    线程安全由调用方保证（轮询任务单协程顺序执行）。未绑定 kv 时仅在内存中
    累计（便于单元测试与纯逻辑复用），flush 为 no-op。
    """

    def __init__(self, kv: object | None = None) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._dirty: set[str] = set()
        self._kv = kv

    # ── 内部 ──

    def _ensure(self, uid: str) -> dict[str, Any]:
        if uid not in self._cache:
            self._cache[uid] = {}
        return self._cache[uid]

    @staticmethod
    def _normalize_uid(uid: str) -> str:
        """规范化玩家标识：缺失时可用座位索引，但跨局画像必须用稳定 id。"""
        return str(uid)

    # ── 训练：记录对手一次动作 ──

    def record_action(
        self,
        uid: str,
        action: str,
        my_seen: bool,
        op_seen: bool,
        is_heads_up: bool,
        display_name: str | None = None,
    ) -> None:
        """记录对手一次 fold/call/raise 动作到对应状态桶。"""
        uid = self._normalize_uid(uid)
        profile = self._ensure(uid)
        if display_name:
            profile[_DISPLAY] = display_name
        profile[_TOTAL_HANDS] = profile.get(_TOTAL_HANDS, 0) + 1
        bucket_key = _bucket(my_seen, op_seen, is_heads_up)
        bucket = profile.setdefault(bucket_key, {})
        actions = bucket.setdefault(_ACTIONS, dict(_EMPTY_ACTIONS))
        if action in actions:
            actions[action] += 1
            bucket[_N_HANDS] = bucket.get(_N_HANDS, 0) + 1
            self._dirty.add(uid)

    def record_hand_pctile(self, uid: str, action: str, pctile: float) -> None:
        """结算回填：记录对手本局最终手牌分位（按加注/平跟动作分桶）。"""
        uid = self._normalize_uid(uid)
        profile = self._ensure(uid)
        key = _RAISE_PCTS if action == "raise" else _CALL_PCTS
        profile.setdefault(key, []).append(pctile)
        self._dirty.add(uid)

    # ── 查询：某对手在某状态桶的动作概率 ──

    def action_probabilities(
        self, uid: str, my_seen: bool, op_seen: bool, is_heads_up: bool
    ) -> tuple[float, float, float]:
        """返回 (P_fold, P_call, P_raise)，未知/少样本向全局先验平滑。

        样本数低于 prior_strength 时，按 prior_strength 的伪样本权重折回全局先验。
        """
        uid = self._normalize_uid(uid)
        prior_strength = 3.0  # 伪样本数；未来可配置化
        global_prior = self._global_prior(my_seen, op_seen, is_heads_up)

        profile = self._cache.get(uid)
        if profile is None:
            return global_prior
        bucket = profile.get(_bucket(my_seen, op_seen, is_heads_up))
        actions = bucket.get(_ACTIONS) if bucket else None
        if not actions:
            return global_prior

        n = sum(actions.values())
        # 样本足够则直接用经验频率；不足则向全局先验收缩
        if n >= prior_strength:
            total = max(n, 1)
            return (
                actions.get("fold", 0) / total,
                actions.get("call", 0) / total,
                actions.get("raise", 0) / total,
            )

        # 经验频率与全局先验按样本数加权（贝叶斯收缩）
        g_f, g_c, g_r = global_prior
        total = n + prior_strength
        return (
            (actions.get("fold", 0) + prior_strength * g_f) / total,
            (actions.get("call", 0) + prior_strength * g_c) / total,
            (actions.get("raise", 0) + prior_strength * g_r) / total,
        )

    def _global_prior(self, my_seen: bool, op_seen: bool, is_heads_up: bool) -> tuple[float, float, float]:
        """聚合所有已见对手的同桶经验频率作为先验；无样本时用均等先验。"""
        bucket_key = _bucket(my_seen, op_seen, is_heads_up)
        agg = dict(_EMPTY_ACTIONS)
        total = 0
        for profile in self._cache.values():
            bucket = profile.get(bucket_key)
            actions = bucket.get(_ACTIONS) if bucket else None
            if not actions:
                continue
            for k in agg:
                agg[k] += actions.get(k, 0)
            total += sum(actions.values())
        if total <= 0:
            return (1 / 3, 1 / 3, 1 / 3)
        return (agg["fold"] / total, agg["call"] / total, agg["raise"] / total)

    # ── 持久化 ──

    def load_all(self) -> None:
        """从 kv 批量加载所有画像到内存（进程启动/热重载时调用）。"""
        if self._kv is None:
            return
        for key in self._kv.keys():
            if key.startswith(_KV_PREFIX):
                uid = key[len(_KV_PREFIX) :]
                raw = self._kv.get(key)
                if isinstance(raw, dict):
                    self._cache[uid] = raw

    def flush(self) -> None:
        """把脏画像写回 kv 并清空脏标记。"""
        if self._kv is None:
            return
        for uid in list(self._dirty):
            self._kv.set(f"{_KV_PREFIX}{uid}", self._cache.get(uid, {}))
        self._dirty.clear()

    def clear(self) -> None:
        """清空内存缓存与脏标记（teardown 用，避免悬挂引用）。"""
        self._cache.clear()
        self._dirty.clear()

    def debug_dump(self) -> dict[str, dict[str, Any]]:
        """导出全部画像（测试/诊断用）。"""
        return dict(self._cache)


def _display_name_by_id(game: dict[str, Any], uid: str) -> str | None:
    """从牌局玩家列表按 id 查 displayName；找不到返回 None。"""
    for index, player in enumerate(_players(game)):
        if _player_key(player, index) == uid:
            return player.get("displayName")
    return None


def _hand_pctile_from_result(hand: str, hand_type: str) -> float | None:
    """把结算手牌文本转为一对一胜率分位；无法解析返回 None。"""
    normalized = _normalize_hand_type(hand_type)
    value = _extract_hand_value(normalized, hand)
    if value is None:
        return None
    return win_prob_1v1(normalized, value)


def feed_last_result(store: ProfileStore, game: dict[str, Any], uid_by_display: dict[str, str]) -> None:
    """从牌局结算 game.lastResult 回填对手真实手牌分位。

    lastResult.players 无 id，需用调用方提供的 displayName→id 映射关联。
    仅对非弃牌动作回填（已弃牌者没有加注/平跟的终局手牌意义）。
    """
    last = game.get("lastResult") or (game.get("game") or {}).get("lastResult")
    if not isinstance(last, dict):
        return
    players = last.get("players")
    if not isinstance(players, list):
        return
    for p in players:
        if not isinstance(p, dict):
            continue
        if p.get("isSelf"):
            continue
        if p.get("result") == "已弃牌":
            continue
        display = p.get("displayName")
        uid = uid_by_display.get(display)
        if not uid:
            continue
        hand = p.get("handType") or p.get("hand") or ""
        pctile = _hand_pctile_from_result(hand, _normalize_hand_type(hand))
        if pctile is None:
            continue
        # 无法从结算区分对手是加注还是平跟，保守回填到两者；供统计时自行取用
        store.record_hand_pctile(uid, "raise", pctile)
        store.record_hand_pctile(uid, "call", pctile)


# 模块级单例（进程内全局画像缓存），供 zhajinhua 轮询与决策使用
_store: ProfileStore | None = None


def get_store(kv: object | None = None) -> ProfileStore:
    """返回全局画像单例；首次调用绑定 kv 并加载已有画像。"""
    global _store
    if _store is None:
        _store = ProfileStore(kv)
        if kv is not None:
            _store.load_all()
    elif kv is not None and _store._kv is None:
        _store._kv = kv
        _store.load_all()
    return _store


def reset_store() -> None:
    """清空全局单例（测试用）。"""
    global _store
    if _store is not None:
        _store.clear()
    _store = None
