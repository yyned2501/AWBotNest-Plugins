# =============================================================================
# AWBotNest 插件：大逃杀助手（battleroyale）
#
# 监听 @NextFunBot 的大逃杀游戏，自动跟踪投票、结算通知、自动下注。
# 以少胜多规则：投票人数少的选项获胜（除非基因突变逆转）。
#
# 工作流程：
#   1. 监听群消息 → 检测游戏启动/结算/结束
#   2. 跟踪玩家投票统计
#   3. 结算前自动下注（人少的一边）
#   4. 每圈结算通知 + 游戏结束总结
# =============================================================================
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime

from ._bettor import AutoBettor
from ._game import GameState

# 事件循环引用（用于延迟调度）
_loop = None

__plugin__ = {
    "name": "大逃杀助手",
    "id": "battleroyale",
    "version": "1.0.0",
    "author": "Yy",
    "description": (
        "监听 @NextFunBot 大逃杀游戏，自动跟踪投票统计、"
        "每圈结算通知、自动下注（以少胜多规则）。"
    ),
    "scope": "user",
    "default_enabled": False,
    "render_mode": "vue",
    "config_schema": {
        # —— 监听 ——
        "chat_id": {
            "type": "string", "default": "", "label": "监听群组",
            "section": "监听",
            "help": "监听的群组 chat_id（如 -1003808371287）",
        },
        "bot_id": {
            "type": "number", "default": 8835151149, "label": "游戏 Bot ID",
            "section": "监听",
            "help": "@NextFunBot 的 user_id",
        },
        # —— 自动下注 ——
        "auto_bet": {
            "type": "boolean", "default": True, "label": "启用自动下注",
            "section": "自动下注",
        },
        "bet_timing": {
            "type": "slider", "default": 5, "min": 0, "max": 30, "step": 1,
            "label": "结算前下注(秒)", "section": "自动下注",
            "show_if": {"auto_bet": True},
            "help": "距结算多少秒时下注。0=结算时刻。",
        },
        "bet_strategy": {
            "type": "select", "default": "少",
            "options": [
                {"value": "少", "label": "人少（以少胜多规则）"},
                {"value": "多", "label": "人多（跟风策略）"},
            ],
            "label": "下注策略", "section": "自动下注",
            "show_if": {"auto_bet": True},
        },
        # —— 通知 ——
        "notify_round": {
            "type": "boolean", "default": True, "label": "每圈结算通知",
            "section": "通知",
        },
        "notify_summary": {
            "type": "boolean", "default": True, "label": "游戏结束总结",
            "section": "通知",
        },
    },
}

# 全局游戏状态
_state = GameState()
# 当前圈监听的关键词
_monitored_keywords: list[str] = []


def _get_chat_id(cfg: dict) -> int | None:
    """从配置获取 chat_id，支持数字和字符串格式"""
    raw = cfg.get("chat_id", "")
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


# ── 启动恢复扫描 ──

async def _resume_game(ctx):
    """启动时扫描历史消息，恢复进行中的游戏状态"""
    global _state, _monitored_keywords
    cfg = ctx.config
    chat_id = _get_chat_id(cfg)
    bot_id = int(cfg.get("bot_id", 8835151149))
    if not chat_id:
        return

    ctx.log.info("[启动] 扫描历史恢复游戏状态...")
    try:
        bot_msgs = []
        last_id = None
        for _ in range(30):
            try:
                kwargs = {"limit": 1}
                if last_id:
                    kwargs["offset_id"] = last_id
                async for msg in ctx.user.get_chat_history(chat_id, **kwargs):
                    last_id = msg.id
                    if not msg.from_user or msg.from_user.id != bot_id:
                        break
                    txt = str(msg.text or "")
                    if txt:
                        bot_msgs.append(msg)
                        break
                    break
            except Exception:
                continue
            if len(bot_msgs) >= 5:
                break

        if not bot_msgs:
            return

        for msg in bot_msgs:
            text = str(msg.text or "")

            if GameState.is_game_over(text):
                ctx.log.info("[启动] 最后消息是游戏结束，不恢复")
                return

            if GameState.is_settlement(text):
                deadline = GameState.extract_deadline(text)
                options = GameState.extract_options(text)
                now = datetime.now()
                if deadline and deadline > now and options:
                    _state.reset_all()
                    _state.is_active = True
                    r = GameState.extract_round(text)
                    _state.round = r + 1 if r else 1
                    _state.target_msg_id = msg.id
                    _state.deadline = deadline
                    _state.options = options
                    _monitored_keywords = list(options)
                    ctx.log.info(
                        "[启动] 恢复游戏第%u圈，距结算%.0f秒",
                        _state.round, (deadline - now).total_seconds(),
                    )
                    if cfg.get("auto_bet", True):
                        bettor = AutoBettor(_state, ctx)
                        _state._task = asyncio.create_task(
                            bettor.countdown_loop(
                                chat_id,
                                int(cfg.get("bet_timing", 5)),
                                cfg.get("bet_strategy", "少"),
                            )
                        )
                    return
                continue

            if GameState.is_game_start(text):
                deadline = GameState.extract_deadline(text)
                options = GameState.extract_options(text)
                now = datetime.now()
                if deadline and deadline > now and options:
                    _state.reset_all()
                    _state.is_active = True
                    _state.round = 1
                    _state.target_msg_id = msg.id
                    _state.deadline = deadline
                    _state.options = options
                    _monitored_keywords = list(options)
                    ctx.log.info(
                        "[启动] 恢复游戏第一圈，距结算%.0f秒",
                        (deadline - now).total_seconds(),
                    )
                    if cfg.get("auto_bet", True):
                        bettor = AutoBettor(_state, ctx)
                        _state._task = asyncio.create_task(
                            bettor.countdown_loop(
                                chat_id,
                                int(cfg.get("bet_timing", 5)),
                                cfg.get("bet_strategy", "少"),
                            )
                        )
                    return
                continue
    except Exception as e:
        ctx.log.error("[启动] 恢复失败: %s", e, exc_info=True)


async def _startup_scan(ctx):
    """等待 userbot 就绪后启动恢复扫描"""
    for _ in range(60):
        if ctx.user and ctx.user.is_connected:
            ctx.log.info("[启动] userbot 就绪，开始扫描")
            await _resume_game(ctx)
            return
        await asyncio.sleep(1)
    ctx.log.warning("[启动] 超时未等到 userbot 就绪")


# ── 消息处理器 ──

async def setup(ctx):
    global _state, _monitored_keywords

    # ── 启动恢复扫描 ──
    asyncio.create_task(_startup_scan(ctx))

    # ── 处理器 1：游戏 Bot 消息（游戏启动/结算/结束）──
    @ctx.on_message(ctx.filters.text, group=0)
    async def game_handler(client, message):
        global _state, _monitored_keywords
        cfg = ctx.config
        chat_id = _get_chat_id(cfg)
        bot_id = int(cfg.get("bot_id", 8835151149))
        if not chat_id or message.chat.id != chat_id:
            return
        fu = message.from_user
        if not fu or fu.id != bot_id:
            return

        text = str(message.text or "")
        state = _state
        ctx.log.info("[游戏] msg_id=%s: %s", message.id, text[:80])

        # ── 游戏启动 ──
        if GameState.is_game_start(text):
            ctx.log.info("[游戏] 检测到游戏启动!")
            state.reset_all()
            state.is_active = True
            state.target_msg_id = message.id
            state.deadline = GameState.extract_deadline(text)
            state.options = GameState.extract_options(text)
            state.round = 1
            _monitored_keywords = list(state.options)
            ctx.log.info(
                "[游戏] 第1圈 options=%s deadline=%s",
                state.options, state.deadline,
            )

            opt_str = " / ".join(state.options)
            dl_str = state.deadline.strftime("%H:%M") if state.deadline else "?"
            await ctx.notify(
                f"大逃杀游戏开始!\n选项: {opt_str}\n首圈结算: {dl_str}",
                level="info", category="大逃杀",
            )

            if state.deadline and cfg.get("auto_bet", True):
                bettor = AutoBettor(state, ctx)
                state._task = asyncio.create_task(
                    bettor.countdown_loop(
                        chat_id,
                        int(cfg.get("bet_timing", 5)),
                        cfg.get("bet_strategy", "少"),
                    )
                )
            return

        # ── 结算 / 平局 ──
        if GameState.is_settlement(text):
            result = GameState.extract_result(text) or "?"
            mutation = "基因突变" if GameState.has_gene_mutation(text) else ""
            ctx.log.info(
                "[游戏] 结算 第%u圈 结果=%s%s",
                state.round, result, f" {mutation}" if mutation else "",
            )

            vote_detail = ", ".join(
                f"{k}={len(v)}" for k, v in sorted(
                    state.votes.items(), key=lambda x: -len(x[1]),
                )
            )

            # 记录历史
            entry = {
                "round": state.round,
                "result": result,
                "mutation": bool(mutation),
                "votes": {k: len(v) for k, v in state.votes.items()},
                "time": datetime.now().isoformat(),
            }
            state.history.append(entry)

            if cfg.get("notify_round", True):
                await ctx.notify(
                    f"第{state.round}圈结算 {mutation}\n"
                    f"结果: {result}\n"
                    f"投票: {vote_detail}",
                    level="info" if not mutation else "warning",
                    category="大逃杀",
                )

            # 准备下一圈
            next_deadline = GameState.extract_deadline(text)
            next_options = GameState.extract_options(text)

            state.reset_round()
            state.round = GameState.extract_round(text) + 1 if GameState.extract_round(text) else (state.round + 1 if state.round else 1)
            state.target_msg_id = message.id
            state.deadline = next_deadline
            state.options = next_options
            _monitored_keywords = list(next_options) if next_options else []

            if next_options and next_deadline and cfg.get("auto_bet", True):
                bettor = AutoBettor(state, ctx)
                state._task = asyncio.create_task(
                    bettor.countdown_loop(
                        chat_id,
                        int(cfg.get("bet_timing", 5)),
                        cfg.get("bet_strategy", "少"),
                    )
                )
            return

        # ── 游戏结束 ──
        if GameState.is_game_over(text):
            total_rounds = state.round
            ctx.log.info("[游戏] 游戏结束! 共%u圈", total_rounds)
            state.is_active = False
            _monitored_keywords.clear()

            if cfg.get("notify_summary", True):
                summary_lines = "\n".join(
                    f"  · 第{h['round']}圈: {h['result']} "
                    f"投票: {', '.join(f'{k}={v}' for k, v in h['votes'].items())}"
                    for h in state.history
                )
                await ctx.notify(
                    f"游戏结束!\n共 {total_rounds} 圈\n{summary_lines}",
                    level="info", category="大逃杀",
                )

            state.reset_all()
            return

    # ── 处理器 2：投票跟踪 ──
    @ctx.on_message(ctx.filters.text, group=1)
    async def vote_tracker(client, message):
        global _state, _monitored_keywords
        cfg = ctx.config
        chat_id = _get_chat_id(cfg)
        if not chat_id or message.chat.id != chat_id:
            return

        text = str(message.text or "").strip()
        if text not in _monitored_keywords:
            return

        state = _state
        fu = message.from_user
        if not fu or fu.is_bot:
            return
        uid = fu.id

        # 去重
        mid = message.id
        if mid in state._counted_msg:
            return
        state._counted_msg.add(mid)

        if uid in state.voted_users:
            return
        state.voted_users.add(uid)
        state.votes.setdefault(text, set()).add(uid)
        ctx.log.info(
            "[投票] %s(%s) → %s  当前: %s",
            fu.first_name or "?", uid, text,
            {k: len(v) for k, v in state.votes.items()},
        )
        # ── on_api 端点（在 setup 内部注册）──
        @ctx.on_api
        async def api_handler(req):
            cfg = ctx.config
            path = req.method + ' ' + req.path.rstrip('/')
            if path == 'GET /status':
                return _state.to_dict()
            if path == 'GET /history':
                return _state.history
            if path == 'POST /force_bet':
                if not _state.is_active or not _state.options:
                    return {'ok': False, 'message': '没有进行中的游戏'}
                if _state.bet_placed:
                    return {'ok': False, 'message': '本圈已下注'}
                chat_id = _get_chat_id(cfg)
                if not chat_id:
                    return {'ok': False, 'message': '未配置群组'}
                strategy = cfg.get('bet_strategy', '少')
                bettor = AutoBettor(_state, ctx)
                target = bettor.determine_target(strategy)
                if not target:
                    return {'ok': False, 'message': '无法确定下注目标'}
                await bettor.execute_bet(target, chat_id)
                return {'ok': True, 'message': f'已下注「{target}」'}
            if path == 'POST /reset':
                _state.reset_all()
                _monitored_keywords.clear()
                return {'ok': True, 'message': '游戏状态已重置'}
            return {'ok': False, 'message': '未知路径'}


async def teardown(ctx):
    global _state, _monitored_keywords
    if _state._task and not _state._task.done():
        _state._task.cancel()
    _state.reset_all()
    _monitored_keywords.clear()