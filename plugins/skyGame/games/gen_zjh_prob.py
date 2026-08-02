# -*- coding: utf-8 -*-
"""生成炸金花穷举胜率查表。

在项目根目录执行：
    python plugins/skyGame/games/gen_zjh_prob.py
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import TypeAlias

RankTuple: TypeAlias = tuple[int, int, int]

_TOTAL = 22100
_RANKS = range(2, 15)


def _is_straight(ranks: RankTuple) -> bool:
    """判断降序三点数是否为顺子（A23 是最小顺子）。"""
    return ranks == (14, 3, 2) or (ranks[0] - ranks[1] == 1 and ranks[1] - ranks[2] == 1)


def _rank_tuples() -> list[RankTuple]:
    """按炸金花点数比较顺序（high, mid, low 升序）返回所有非顺子的不重复点数组合。

    必须严格按牌力升序排列：weaker_count 直接取枚举序号 × 同牌型花色组合数，
    若枚举序与牌力序不一致（如 combinations 原生按 low 优先），强散牌会被算出
    比弱散牌更低的胜率。散牌/金花比大小为 high→mid→low，元组即 (high, mid, low)，
    直接 sorted() 即得牌力升序。
    """
    tuples = [
        tuple(reversed(values)) for values in combinations(_RANKS, 3) if not _is_straight(tuple(reversed(values)))
    ]
    return sorted(tuples)


def _format_table(name: str, table: dict[object, int]) -> str:
    lines = [f"{name} = {{"]
    lines.extend(f"    {key!r}: {value}," for key, value in table.items())
    lines.append("}")
    return "\n".join(lines)


def _build_tables() -> dict[str, dict[object, int]]:
    non_straights = _rank_tuples()
    straights = list(range(3, 15))

    tables: dict[str, dict[object, int]] = {}
    offset = 0

    tables["_散牌"] = {ranks: offset + index * 60 for index, ranks in enumerate(non_straights)}
    offset += len(non_straights) * 60

    pairs = [(pair, kicker) for pair in _RANKS for kicker in _RANKS if pair != kicker]
    tables["_对子"] = {ranks: offset + index * 24 for index, ranks in enumerate(pairs)}
    offset += len(pairs) * 24

    tables["_顺子"] = {high: offset + index * 60 for index, high in enumerate(straights)}
    offset += len(straights) * 60

    tables["_金花"] = {ranks: offset + index * 4 for index, ranks in enumerate(non_straights)}
    offset += len(non_straights) * 4

    tables["_同花顺"] = {high: offset + index * 4 for index, high in enumerate(straights)}
    offset += len(straights) * 4

    tables["_豹子"] = {rank: offset + index * 4 for index, rank in enumerate(_RANKS)}
    offset += len(_RANKS) * 4

    if offset != _TOTAL:
        raise RuntimeError(f"牌型总数错误: {offset} != {_TOTAL}")
    return tables


def _render(tables: dict[str, dict[object, int]]) -> str:
    ordered_names = ("_豹子", "_同花顺", "_金花", "_顺子", "_对子", "_散牌")
    source = [
        "# 炸金花穷举概率表 — 由 gen_zjh_prob.py 自动生成，勿手动编辑",
        "# 总牌型: 22100",
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "_TOTAL = 22100",
        "",
    ]
    for name in ordered_names:
        source.extend([_format_table(name, tables[name]), ""])
    source.extend(
        [
            "",
            "def _weaker_count(hand_type: str, hand_value: Any) -> int:",
            '    """返回严格弱于当前手牌的组合数。"""',
            "    tbl = {",
            '        "豹子": _豹子,',
            '        "同花顺": _同花顺,',
            '        "金花": _金花,',
            '        "顺子": _顺子,',
            '        "对子": _对子,',
            '        "散牌": _散牌,',
            "    }",
            "    table = tbl.get(hand_type)",
            "    if table is None:",
            "        return 0",
            "    return table.get(hand_value, 0)",
            "",
            "",
            "def win_prob_1v1(hand_type: str, hand_value: Any) -> float:",
            '    """按全量牌型分布计算一对一胜率。"""',
            "    return _weaker_count(hand_type, hand_value) / _TOTAL",
            "",
            "",
            "def win_prob_n(hand_type: str, hand_value: Any, opponents: int) -> float:",
            '    """按独立对手近似计算对多个未看牌对手的胜率。"""',
            "    weaker = _weaker_count(hand_type, hand_value)",
            "    if weaker >= _TOTAL - 1:",
            "        return 1.0",
            "    return (weaker / _TOTAL) ** opponents",
            "",
        ]
    )
    return "\n".join(source)


def main() -> None:
    """生成运行时概率表文件。"""
    target = Path(__file__).with_name("zjh_prob.py")
    target.write_text(_render(_build_tables()), encoding="utf-8")


if __name__ == "__main__":
    main()
