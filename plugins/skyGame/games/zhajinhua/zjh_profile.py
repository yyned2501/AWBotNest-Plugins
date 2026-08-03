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

import math
from typing import Any

from .zjh_hand import _extract_hand_value, _normalize_hand_type
from .zjh_prob import win_prob_1v1, win_prob_1v1_type
from .zjh_state import _player_key, _players

# kv 键前缀
_KV_PREFIX = "zjh:profile:"

# 画像字典键
_RAISE_PCTS = "raise_pcts"  # 加注后最终真实手牌分位（结算回填）
_CALL_PCTS = "call_pcts"  # 平跟后最终真实手牌分位
_TOTAL_HANDS = "total_hands"
_DISPLAY = "display_name"
_UPDATED = "updated_ms"
_RAISE_FREQ = "raise_freq"  # 加注频率分桶: {bucket_key: {"total": N, "raises": M}}

# 空动作计数（动作分桶用，桶键与加注频率分桶一致）
_EMPTY_ACTIONS = {"fold": 0, "call": 0, "raise": 0}

# 贝叶斯收缩伪样本数：样本不足时按此权重折回先验/基线（动作概率、实测胜率、诈唬率共用）
PRIOR_STRENGTH = 3.0

# 弱牌分位阈值：实测手牌分位低于此值计为一次「诈唬/弱牌继续」
_WEAK_PCTILE = 0.5


def _freq_bucket(op_seen: bool, seen_count: int, blind_count: int) -> str:
    """分桶键：对手状态 + 其他看牌人数 + 其他蒙牌人数。

    例如 s_s1b1 = 对手看牌，另有1人看牌、1人蒙牌，共4人存活。
    b_s0b2 = 对手蒙牌，无其他看牌人、另有2人蒙牌，共3人存活。
    动作分桶与加注频率分桶共用同一桶键方案。
    """
    op = "s" if op_seen else "b"
    return f"{op}_s{seen_count}b{blind_count}"


def _percentile(values: list[float], q: float) -> float:
    """线性插值分位数（q∈[0,1]）；values 非空。q=0.25 即下四分位。"""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = q * (len(ordered) - 1)
    low = int(math.floor(rank))
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


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
        op_seen: bool,
        seen_count: int,
        blind_count: int,
        display_name: str | None = None,
    ) -> None:
        """记录对手一次 fold/call/raise 动作到对应状态桶。

        桶键与加注频率分桶一致（_freq_bucket），动作计数直接存于桶字典
        {r: N, c: N, f: N}，无需额外嵌套。
        """
        uid = self._normalize_uid(uid)
        profile = self._ensure(uid)
        if display_name:
            profile[_DISPLAY] = display_name
        profile[_TOTAL_HANDS] = profile.get(_TOTAL_HANDS, 0) + 1
        bucket_key = _freq_bucket(op_seen, seen_count, blind_count)
        bucket = profile.setdefault(bucket_key, dict(_EMPTY_ACTIONS))
        if action in bucket:
            bucket[action] += 1
            self._dirty.add(uid)

    def record_hand_pctile(self, uid: str, action: str, pctile: float) -> None:
        """结算回填：记录对手本局最终手牌分位（按加注/平跟动作分桶）。"""
        uid = self._normalize_uid(uid)
        profile = self._ensure(uid)
        key = _RAISE_PCTS if action == "raise" else _CALL_PCTS
        profile.setdefault(key, []).append(pctile)
        self._dirty.add(uid)

    # ── 训练：记录对手加注频率（按对手状态+剩余人数分桶）──

    def record_raise_freq(
        self,
        uid: str,
        op_seen: bool,
        seen_count: int,
        blind_count: int,
        is_raise: bool,
    ) -> None:
        """记录对手在本局的加注频率统计。

        按对手看牌状态 + 其他看牌人数 + 其他蒙牌人数分桶，如 s_s1b1。
        每局调用一次（hand-level），is_raise=True 表示该局对手至少加注一次。
        """
        uid = self._normalize_uid(uid)
        profile = self._ensure(uid)
        bucket_key = _freq_bucket(op_seen, seen_count, blind_count)
        freq_buckets = profile.setdefault(_RAISE_FREQ, {})
        bucket = freq_buckets.setdefault(bucket_key, {"total": 0, "raises": 0})
        bucket["total"] += 1
        if is_raise:
            bucket["raises"] += 1
        self._dirty.add(uid)

    # ── 查询：某对手在某状态桶的动作概率 ──

    def raise_floor_from_freq(self, uid: str, bucket_key: str, base_threshold: float) -> float | None:
        """从加注频率推断对手最小加注牌力。

        raise_rate = raises / total，min_strength = 1.0 - raise_rate。
        向 base_threshold 贝叶斯收缩；无样本返回 None。
        """
        uid = self._normalize_uid(uid)
        profile = self._cache.get(uid)
        if profile is None:
            return None
        freq_buckets = profile.get(_RAISE_FREQ)
        if not isinstance(freq_buckets, dict):
            return None
        bucket = freq_buckets.get(bucket_key)
        if not isinstance(bucket, dict):
            return None
        total = bucket.get("total", 0)
        raises = bucket.get("raises", 0)
        if total <= 0:
            return None
        raise_rate = raises / total
        min_strength = 1.0 - raise_rate  # 80% raise → min_strength ≈ 0.2
        weight = total / (total + PRIOR_STRENGTH)
        return weight * min_strength + (1 - weight) * base_threshold

    def raise_floor_from_freq_bucket(
        self,
        uid: str,
        op_seen: bool,
        seen_count: int,
        blind_count: int,
        base_threshold: float,
    ) -> float | None:
        """从加注频率推断对手最小加注牌力（按原始参数分桶）。

        与 record_raise_freq 参数对称，方便调用方无需构造 bucket_key。
        """
        bucket_key = _freq_bucket(op_seen, seen_count, blind_count)
        return self.raise_floor_from_freq(uid, bucket_key, base_threshold)

    # ── 查询：某对手在某状态桶的动作概率 ──

    def action_probabilities(
        self, uid: str, op_seen: bool, seen_count: int, blind_count: int
    ) -> tuple[float, float, float]:
        """返回 (P_fold, P_call, P_raise)，未知/少样本向全局先验平滑。

        样本数低于 prior_strength 时，按 prior_strength 的伪样本权重折回全局先验。
        """
        uid = self._normalize_uid(uid)
        global_prior = self._global_prior(op_seen, seen_count, blind_count)

        profile = self._cache.get(uid)
        if profile is None:
            return global_prior
        bucket_key = _freq_bucket(op_seen, seen_count, blind_count)
        bucket = profile.get(bucket_key)
        if not bucket:
            return global_prior

        n = sum(bucket.get(k, 0) for k in ("fold", "call", "raise"))
        if n <= 0:
            return global_prior

        # 样本足够则直接用经验频率；不足则向全局先验收缩
        if n >= PRIOR_STRENGTH:
            return (
                bucket.get("fold", 0) / n,
                bucket.get("call", 0) / n,
                bucket.get("raise", 0) / n,
            )

        # 经验频率与全局先验按样本数加权（贝叶斯收缩）
        g_f, g_c, g_r = global_prior
        total = n + PRIOR_STRENGTH
        return (
            (bucket.get("fold", 0) + PRIOR_STRENGTH * g_f) / total,
            (bucket.get("call", 0) + PRIOR_STRENGTH * g_c) / total,
            (bucket.get("raise", 0) + PRIOR_STRENGTH * g_r) / total,
        )

    def _global_prior(self, op_seen: bool, seen_count: int, blind_count: int) -> tuple[float, float, float]:
        """聚合所有已见对手的同桶经验频率作为先验；无样本时用均等先验。"""
        bucket_key = _freq_bucket(op_seen, seen_count, blind_count)
        agg = dict(_EMPTY_ACTIONS)
        total = 0
        for profile in self._cache.values():
            bucket = profile.get(bucket_key)
            if not bucket:
                continue
            for k in agg:
                agg[k] += bucket.get(k, 0)
            total += sum(bucket.get(k, 0) for k in ("fold", "call", "raise"))
        if total <= 0:
            return (1 / 3, 1 / 3, 1 / 3)
        return (agg["fold"] / total, agg["call"] / total, agg["raise"] / total)

    # ── 查询：对手实测手牌分位 / 诈唬率 ──

    def hand_percentiles(self, uid: str, action: str) -> list[float]:
        """返回该对手加注/平跟后结算回填的真实手牌分位列表（可能为空）。"""
        uid = self._normalize_uid(uid)
        profile = self._cache.get(uid)
        if profile is None:
            return []
        key = _RAISE_PCTS if action == "raise" else _CALL_PCTS
        values = profile.get(key)
        return list(values) if isinstance(values, list) else []

    def empirical_win_factor(self, uid: str, action: str, my_threshold: float, model_baseline: float) -> float:
        """实测胜率收缩混合：我方牌力击败对手该动作实测手牌的比例。

        wins = mean(p < my_threshold for p in pcts)，按 n/(n+PRIOR_STRENGTH) 与
        model_baseline（现有范围模型胜率）收缩；无样本返回 model_baseline。
        """
        pcts = self.hand_percentiles(uid, action)
        if not pcts:
            return model_baseline
        wins = sum(1.0 for p in pcts if p < my_threshold) / len(pcts)
        weight = len(pcts) / (len(pcts) + PRIOR_STRENGTH)
        return weight * wins + (1 - weight) * model_baseline

    def bluff_rate(self, uid: str, baseline: float) -> float:
        """逐对手诈唬率：其实测继续手牌中弱牌（分位 < _WEAK_PCTILE）占比。

        样本数低于 PRIOR_STRENGTH 回退全局基线 baseline；否则向 baseline 收缩。
        """
        pcts = self.hand_percentiles(uid, "raise") + self.hand_percentiles(uid, "call")
        if len(pcts) < PRIOR_STRENGTH:
            return baseline
        weak = sum(1.0 for p in pcts if p < _WEAK_PCTILE) / len(pcts)
        weight = len(pcts) / (len(pcts) + PRIOR_STRENGTH)
        return weight * weak + (1 - weight) * baseline

    def raise_threshold_floor(self, uid: str, base_threshold: float) -> float | None:
        """对手加注手牌范围下界：实测加注分位的下四分位（最弱实测加注牌）。

        爱拿弱牌加注（诈唬型）的对手下四分位低 → 门槛低 → 我方蒙牌胜率高；
        紧手加注者下四分位高 → 门槛高。按样本数向通用推断 base_threshold 收缩；
        无样本返回 None（调用方回退通用推断）。
        """
        pcts = self.hand_percentiles(uid, "raise")
        if not pcts:
            return None
        floor = _percentile(pcts, 0.25)
        weight = len(pcts) / (len(pcts) + PRIOR_STRENGTH)
        return weight * floor + (1 - weight) * base_threshold

    def call_threshold_ceiling(self, uid: str, base_ceiling: float) -> float | None:
        """对手平跟手牌范围上界：实测平跟分位的上四分位（最强实测平跟牌）。

        爱拿大牌平跟慢打的对手上四分位高 → 上限高 → 我方胜率低；
        反之弱牌平跟者上四分位低 → 上限低。按样本数向通用推断 base_ceiling 收缩；
        无样本返回 None（调用方回退通用推断）。
        """
        pcts = self.hand_percentiles(uid, "call")
        if not pcts:
            return None
        ceiling = _percentile(pcts, 0.75)
        weight = len(pcts) / (len(pcts) + PRIOR_STRENGTH)
        return weight * ceiling + (1 - weight) * base_ceiling

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
    """把结算手牌转为一对一胜率分位。

    有具体牌面（hand）时按精确点数查表；结算 lastResult 只给 handType 不给牌面时
    回退牌型分位带中点（win_prob_1v1_type）。两者都解析不出返回 None。
    """
    normalized = _normalize_hand_type(hand_type)
    value = _extract_hand_value(normalized, hand)
    if value is not None:
        return win_prob_1v1(normalized, value)
    return win_prob_1v1_type(normalized)


def feed_last_result(
    store: ProfileStore,
    game: dict[str, Any],
    uid_by_display: dict[str, str],
    round_action: dict[str, str] | None = None,
) -> None:
    """从牌局结算 game.lastResult 回填对手真实手牌分位。

    lastResult.players 无 id，需用调用方提供的 displayName→id 映射关联。
    仅对非弃牌动作回填（已弃牌者没有加注/平跟的终局手牌意义）。

    round_action：本轮各对手最激进动作 {uid: "raise"|"call"}，由轮询跟踪得到。
    提供时按对手实际动作只回填对应桶（区分「加注的牌」与「平跟的牌」）；
    为 None 时保持旧行为保守回填到两者。
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
        hand_text = p.get("hand") or ""
        hand_type = p.get("handType") or ""
        pctile = _hand_pctile_from_result(hand_text, hand_type)
        if pctile is None:
            continue
        if round_action is not None:
            # 按对手本轮实际动作分桶；未知动作保守归入平跟
            store.record_hand_pctile(uid, round_action.get(uid, "call"), pctile)
            continue
        # 无动作跟踪时保守回填到两者；供统计时自行取用
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
