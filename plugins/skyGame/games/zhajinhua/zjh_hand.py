# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花：手牌解析
#
# 花色/点数映射、牌型归一、手牌字符串解析与查表键值提取。
# 仅依赖 hdsky 客户端（看牌后补拉状态）与标准库，不依赖其它炸金花子模块。

from __future__ import annotations

import asyncio
from typing import Any

from ..hdsky import HdskyClient

# 手牌解析：花色符号和点数映射
_SUIT_SYMBOLS = "♠♥♦♣"
_RANK_MAP = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}
_HAND_TYPE_ALIASES = {"同花": "金花"}


def _normalize_hand_type(hand_type: str) -> str:
    """将门户牌型名称或“手牌 → 牌型”组合文本归一为概率表名称。"""
    normalized = hand_type.rsplit("→", 1)[-1].strip()
    return _HAND_TYPE_ALIASES.get(normalized, normalized)


def _self_hand(game: dict[str, Any]) -> tuple[str, str]:
    """从牌局状态读取我方手牌与归一牌型；缺失时手牌为空串。"""
    self_state = game.get("self", {})
    hand = str(self_state.get("hand", "") or "")
    hand_type = _normalize_hand_type(str(self_state.get("handType", "") or ""))
    return hand, hand_type


async def _acquire_hand_after_peek(client: HdskyClient, game: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """看牌后确保读到我方手牌：响应里缺手牌时重拉状态补齐（最多 3 次短重试）。"""
    hand, hand_type = _self_hand(game)
    for _ in range(3):
        if hand:
            break
        await asyncio.sleep(0.5)
        refetch = await client.get("/api/portal/zhajinhua")
        if "_error" not in refetch:
            game = refetch.get("game", {})
            hand, hand_type = _self_hand(game)
    return game, hand, hand_type


def _parse_hand(hand: str) -> list[int]:
    """解析手牌字符串如 'A♠ K♠ Q♠' 为降序点数列表 [14, 13, 12]。"""
    cards: list[int] = []
    i = 0
    while i < len(hand):
        if hand[i] in _SUIT_SYMBOLS:
            i += 1
            continue
        if hand[i : i + 2] == "10":
            cards.append(10)
            i += 2
        else:
            r = _RANK_MAP.get(hand[i])
            if r is not None:
                cards.append(r)
            i += 1
    cards.sort(reverse=True)
    return cards


def _extract_hand_value(hand_type: str, hand: str) -> int | tuple[int, ...] | None:
    """根据牌型从手牌字符串提取概率表查表键值。"""
    if not hand:
        return None
    ranks = _parse_hand(hand)
    if len(ranks) < 3:
        return None
    if hand_type in ("豹子", "同花顺", "顺子"):
        if hand_type != "豹子" and ranks == [14, 3, 2]:
            return 3
        return ranks[0]
    if hand_type in ("金花", "散牌"):
        return (ranks[0], ranks[1], ranks[2])
    if hand_type == "对子":
        if ranks[0] == ranks[1]:
            return (ranks[0], ranks[2])
        return (ranks[1], ranks[0])
    return None
