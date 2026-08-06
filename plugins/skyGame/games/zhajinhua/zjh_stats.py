# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：对局战绩统计
#
# 每局结算（game.lastResult.selfDelta，本局净输赢）入账一次，分别持久化到
# 累计（zjh:stats）与当日（zjh:stats:day:YYYY-MM-DD）两个键。调用方在牌局轮询
# roundId 切换时每局调用一次（zhajinhua.py）；展示文本由 zjh_notify 拼装。
# kv 值用 dict 存储（与画像 ProfileStore 同一套平台 kv，实测支持 dict）。

from __future__ import annotations

import datetime
from typing import Any

_STATS_TOTAL_KEY = "zjh:stats"
_STATS_DAY_PREFIX = "zjh:stats:day"


def _result_delta(last_result: Any) -> float | None:
    """读结算 selfDelta（本局净输赢，正=赢、负=输）；结构异常返回 None。"""
    if not isinstance(last_result, dict):
        return None
    delta = last_result.get("selfDelta")
    if not isinstance(delta, (int, float)):
        return None
    return float(delta)


def _empty_stats() -> dict[str, int | float]:
    return {"games": 0, "wins": 0, "draws": 0, "losses": 0, "profit": 0.0, "loss_amount": 0.0}


def _load_stats(kv: object, key: str) -> dict[str, int | float]:
    raw = kv.get(key)
    if not isinstance(raw, dict):
        return _empty_stats()
    stats = _empty_stats()
    for name in stats:
        value = raw.get(name)
        if isinstance(value, (int, float)):
            stats[name] = value
    return stats


def _save_stats(kv: object, key: str, stats: dict[str, int | float]) -> None:
    kv.set(key, stats)


def record_round_result(kv: object, last_result: Any, today: str | None = None) -> float | None:
    """入账一局结算：累计与当日统计同步更新，返回本局净输赢（无有效结算返回 None）。

    调用方保证每局只调一次（roundId 切换去重）；selfDelta 缺失时不入账、不报错。
    """
    delta = _result_delta(last_result)
    if delta is None:
        return None
    today = today or datetime.date.today().isoformat()
    for key in (_STATS_TOTAL_KEY, f"{_STATS_DAY_PREFIX}:{today}"):
        stats = _load_stats(kv, key)
        stats["games"] += 1
        if delta > 0:
            stats["wins"] += 1
            stats["profit"] += delta
        elif delta < 0:
            stats["losses"] += 1
            stats["loss_amount"] += -delta
        else:
            stats["draws"] += 1
        _save_stats(kv, key, stats)
    return delta


def load_total_stats(kv: object) -> dict[str, int | float]:
    """读累计战绩（无记录返回全零结构）。"""
    return _load_stats(kv, _STATS_TOTAL_KEY)


def load_day_stats(kv: object, day: str | None = None) -> dict[str, int | float]:
    """读指定日（缺省今天）战绩。"""
    day = day or datetime.date.today().isoformat()
    return _load_stats(kv, f"{_STATS_DAY_PREFIX}:{day}")


def format_stats(stats: dict[str, int | float]) -> str:
    """格式化战绩：局数 · 胜/平/负 · 净盈亏（总赢−总输）。"""
    net = float(stats["profit"]) - float(stats["loss_amount"])
    return f"{stats['games']} 局 · 胜 {stats['wins']} / 平 {stats['draws']} / 负 {stats['losses']} · 净 {net:+.0f}"
