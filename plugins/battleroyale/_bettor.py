from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._game import GameState


class AutoBettor:
    """自动下注逻辑：判断时机、选择目标、执行下注。"""

    def __init__(self, state: GameState, ctx) -> None:
        self.state = state
        self.ctx = ctx

    def should_bet(self, timing: int = 5) -> bool:
        """判断当前是否该下注（距结算不足 timing 秒 且 未下注）"""
        if not self.state.is_active or self.state.bet_placed:
            return False
        if not self.state.deadline:
            return False
        remaining = (self.state.deadline - datetime.now()).total_seconds()
        return remaining <= timing

    def determine_target(self, strategy: str = "少") -> str | None:
        """根据策略决定投哪个选项

        - 少：选投票人数最少的（以少胜多规则）
        - 多：选投票人数最多的（跟风）
        """
        votes = self.state.votes
        options = self.state.options
        if not options:
            return None

        if strategy == "少":
            if len(votes) >= 2:
                sv = sorted(votes.items(), key=lambda x: len(x[1]))
                return sv[0][0]
            elif len(votes) == 1:
                opt_has = list(votes.keys())[0]
                alt = [o for o in options if o != opt_has]
                return alt[0] if alt else None
            else:
                # 无人投票，选第一个选项
                return options[0]
        else:  # "多"
            if len(votes) >= 2:
                sv = sorted(votes.items(), key=lambda x: -len(x[1]))
                return sv[0][0]
            elif len(votes) == 1:
                return list(votes.keys())[0]
            else:
                return options[0]

    async def execute_bet(self, target: str, chat_id: int) -> bool:
        """通过用户账号向群发送选项文本执行下注"""
        if self.state.bet_placed:
            self.ctx.log.info("[下注] 本圈已下注，跳过")
            return False
        self.ctx.log.info("[下注] 投「%s」于群 %s", target, chat_id)
        await self.ctx.user.send(chat_id, target)
        self.state.bet_placed = True
        self.ctx.log.info("[下注] 成功: 「%s」", target)
        return True

    async def countdown_loop(self, chat_id: int, timing: int, strategy: str) -> None:
        """倒计时：等待至结算前 timing 秒，然后下注"""
        if not self.state.deadline:
            return
        remaining = (self.state.deadline - datetime.now()).total_seconds()
        self.ctx.log.info(
            "[倒计时] 第%u圈 距结算%.0f秒 策略=%s 时机=%u秒前",
            self.state.round, remaining, strategy, timing,
        )
        if remaining <= 0:
            return
        if remaining <= timing:
            target = self.determine_target(strategy)
            if target:
                await self.execute_bet(target, chat_id)
            return
        wait = max(remaining - timing, 1)
        self.ctx.log.info("[倒计时] 等待%.0f秒后下注", wait)
        await asyncio.sleep(wait)
        if self.state.is_active and not self.state.bet_placed:
            target = self.determine_target(strategy)
            if target:
                await self.execute_bet(target, chat_id)