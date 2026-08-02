# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：牌局公开状态读取
#
# 从门户返回的牌局字典里读取玩家列表、存活/看牌/自身标识等公开信息，
# 以及用于相邻轮询比较的玩家状态快照。仅依赖标准库，是其它子模块的底座。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _PlayerState:
    """用于相邻轮询比较的玩家公开状态。"""

    alive: bool
    seen: bool
    bet: float | None
    last_action: str


def _players(game: dict[str, Any]) -> list[dict[str, Any]]:
    """返回牌局公开玩家列表，缺失时为空。"""
    players = game.get("players") or game.get("seats")
    return [player for player in players if isinstance(player, dict)] if isinstance(players, list) else []


def _player_key(player: dict[str, Any], index: int) -> str:
    """优先以服务端玩家 ID 标识，缺失时仅在本局内使用座位索引。"""
    player_id = player.get("id")
    return str(player_id) if player_id else f"seat:{index}"


def _is_alive(player: dict[str, Any]) -> bool:
    """读取玩家是否仍在局。"""
    return bool(player.get("alive", player.get("active", False)))


def _is_self(player: dict[str, Any]) -> bool:
    """读取玩家是否是本账号。"""
    return bool(player.get("isSelf") or player.get("self"))


def _in_hand(game: dict[str, Any]) -> bool:
    """本账号是否仍在当前牌局（未弃牌/未出局）；只有此时才需跟踪对手快照。"""
    return bool(game.get("self", {}).get("alive", False))


def _player_state(player: dict[str, Any]) -> _PlayerState:
    """提取用于轮询比较的公开状态。"""
    bet = player.get("bet")
    return _PlayerState(
        alive=_is_alive(player),
        seen=bool(player.get("seen", False)),
        bet=float(bet) if isinstance(bet, (int, float)) else None,
        last_action=str(player.get("lastAction", "")),
    )


def _opponent_entries(game: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """返回仍在局且非自身的对手标识与公开信息。"""
    return [
        (_player_key(player, index), player)
        for index, player in enumerate(_players(game))
        if not _is_self(player) and _is_alive(player)
    ]


def _opponent_counts(game: dict[str, Any]) -> tuple[int, int]:
    """返回仍在局的蒙牌和已看牌对手数量。"""
    opponents = _opponent_entries(game)
    if not opponents and not _players(game):
        return 1, 0
    seen = sum(1 for _, player in opponents if player.get("seen", False))
    return len(opponents) - seen, seen


def _self_key(game: dict[str, Any]) -> str | None:
    """返回本账号在本局公开玩家列表中的标识。"""
    return next((_player_key(player, index) for index, player in enumerate(_players(game)) if _is_self(player)), None)
