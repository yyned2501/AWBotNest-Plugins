from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any


class GameState:
    """大逃杀游戏状态机，跟踪游戏进程、选项、投票、结算历史。"""

    def __init__(self) -> None:
        self.is_active = False
        self.round = 0
        self.options: list[str] = []
        self.deadline: datetime | None = None
        self.votes: dict[str, set[int]] = {}  # 选项 -> 投票用户ID集合
        self.voted_users: set[int] = set()  # 已投票用户ID
        self.bet_placed = False  # 是否已下注
        self.target_msg_id: int | None = None  # 当前圈 Bot 消息ID
        self._counted_msg: set[int] = set()  # 已统计消息ID（去重）
        self._task: asyncio.Task | None = None  # 倒计时任务
        self.history: list[dict[str, Any]] = []  # 历史记录

    # ── 文本解析 ──

    @staticmethod
    def extract_deadline(text: str) -> datetime | None:
        """从消息提取结算时间，如「22:35左右」→ datetime"""
        text = str(text)
        m = re.search(r'(\d{1,2})[:.](\d{1,2})\s*[左右前後以]', text)
        if m:
            now = datetime.now()
            h, mi = int(m.group(1)), int(m.group(2))
            dl = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if dl < now:
                dl += timedelta(days=1)
            return dl
        return None

    @staticmethod
    def extract_options(text: str) -> list[str]:
        """从消息提取选项（只取「参与口令」后面的部分）"""
        text = str(text)
        idx = text.find("参与口令")
        if idx >= 0:
            text = text[idx:]
        m = re.findall(r'「(.+?)」', text)
        return m[:2] if len(m) >= 2 else []

    @staticmethod
    def extract_round(text: str) -> int:
        """从消息提取圈数，如「第3圈」→ 3"""
        rm = re.search(r'第(\d+)圈', text)
        return int(rm.group(1)) if rm else 0

    @staticmethod
    def extract_result(text: str) -> str | None:
        """从结算消息提取胜利口令"""
        rm = re.search(r'口令「(.+?)」胜利', text)
        return rm.group(1) if rm else None

    @staticmethod
    def has_gene_mutation(text: str) -> bool:
        return "基因突变" in text

    @staticmethod
    def is_game_over(text: str) -> bool:
        return "游戏结束" in text

    @staticmethod
    def is_game_start(text: str) -> bool:
        return "游戏启动" in text

    @staticmethod
    def is_settlement(text: str) -> bool:
        return "结算" in text or "平局" in text

    # ── 状态重置 ──

    def reset_round(self) -> None:
        """结算后准备下一圈"""
        self.votes.clear()
        self.voted_users.clear()
        self._counted_msg.clear()
        self.bet_placed = False
        self.target_msg_id = None
        self._task = None

    def reset_all(self) -> None:
        """完全重置游戏状态"""
        self.__init__()

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_active": self.is_active,
            "round": self.round,
            "options": self.options,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "deadline_ts": self.deadline.timestamp() if self.deadline else None,
            "votes": {k: len(v) for k, v in self.votes.items()},
            "bet_placed": self.bet_placed,
            "target_msg_id": self.target_msg_id,
        }