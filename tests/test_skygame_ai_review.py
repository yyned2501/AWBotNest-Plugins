# -*- coding: utf-8 -*-
# skyGame · AI 评价通用模块（games/ai_review.py）单元测试
#
# 覆盖：简称/动作序列/提示词模板（默认+自定义、无 EV）、开关矩阵（总开关/多选/旧键兼容）、
# 群 ID 解析、直发群 vs 通知中心、无 AI/异常兜底不阻塞。

from __future__ import annotations

import pytest

from plugins.skyGame.games.ai_review import (
    _action_sequence_text,
    _build_prompt,
    _game_enabled,
    _group_ids,
    _short_name,
    review,
)


class _FakeLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _fmt(self, msg: str, args: tuple[object, ...]) -> str:
        return msg % args if args else msg

    def debug(self, msg: str, *args: object) -> None:
        self.records.append(("DEBUG", self._fmt(msg, args)))

    def info(self, msg: str, *args: object) -> None:
        self.records.append(("INFO", self._fmt(msg, args)))

    def warning(self, msg: str, *args: object) -> None:
        self.records.append(("WARNING", self._fmt(msg, args)))

    def error(self, msg: str, *args: object) -> None:
        self.records.append(("ERROR", self._fmt(msg, args)))


class _FakeAI:
    def __init__(self, reply: str = "还好我稳住了！", fail: Exception | None = None) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, str | None, float | None]] = []

    async def chat(self, prompt: str, system: str | None = None, temperature: float = 0.9) -> str:
        self.calls.append((prompt, system, temperature))
        if self.fail is not None:
            raise self.fail
        return self.reply


class _FakeBot:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.sent: list[tuple[object, str]] = []

    async def send(self, chat_id: object, text: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((chat_id, text))


class _FakeCtx:
    def __init__(self, ai: object | None = None, bot: object | None = None) -> None:
        self.log = _FakeLog()
        self.ai = ai
        self.bot = bot
        self.notifications: list[tuple[object, str]] = []

    async def notify(self, message: object, *args: object, **kwargs: object) -> None:
        self.notifications.append((message, str(kwargs.get("level", "info"))))


def _ctx(
    ai_reply: str | None = "还好我稳住了！", with_bot: bool = False
) -> tuple[_FakeCtx, _FakeAI | None, _FakeBot | None]:
    ai = _FakeAI(reply=ai_reply) if ai_reply is not None else None
    bot = _FakeBot() if with_bot else None
    return _FakeCtx(ai=ai, bot=bot), ai, bot


# ── 简称 ──


def test_short_name_abbrev_and_fallback() -> None:
    assert _short_name("麦克格雷涛") == "麦克"
    assert _short_name("南凝 徐") == "南凝"
    assert _short_name("飞亦") == "飞亦"
    assert _short_name(" ") == "对手"
    assert _short_name("", "庄家") == "庄家"


# ── 动作序列 ──


def test_action_sequence_text_with_and_without_labels() -> None:
    steps = [[0.0, "", "hit", -0.60, None, None], [3.0, "A♥ 2♣", "stand", None, None, None]]
    assert _action_sequence_text(steps, {"hit": "要牌", "stand": "停牌"}) == "要牌 0点 → 停牌 3点"
    assert _action_sequence_text(steps) == "hit 0点 → stand 3点"  # 无标签时原样
    assert _action_sequence_text([]) == "观望"


# ── 提示词模板 ──


def test_prompt_default_template_no_ev_and_tones() -> None:
    steps = [[0.0, "", "hit", -0.60, None, None], [3.0, "A♥ 2♣", "stand", None, None, None]]
    seq = _action_sequence_text(steps, {"hit": "要牌", "stand": "停牌"})
    for delta in (198, -100, 0):
        system, prompt = _build_prompt({}, "tenhalf", "麦克", delta, "胜", seq)
        assert "ev" not in system.lower() and "ev" not in prompt.lower()  # 绝不漏 EV
        assert "概率" not in system and "期望" not in system
        assert "麦" in prompt  # 对手简称已带入
        assert "十点半" in system and "麦克" in prompt
    assert "炫耀" in _build_prompt({}, "tenhalf", "麦克", 198, "胜", seq)[1]
    assert "运气太好" in _build_prompt({}, "tenhalf", "麦克", -100, "负", seq)[1]
    assert "调侃" in _build_prompt({}, "tenhalf", "麦克", 0, "和", seq)[1]


def test_prompt_custom_template_placeholders() -> None:
    cfg = {"ai_review_prompt": "玩的是{game}。我做：{actions}。对手{opponent}。{result}。{tone}！"}
    system, prompt = _build_prompt(cfg, "zjh", "阿强", -50, "负", "牌很大")
    assert "玩的是炸金花" in prompt
    assert "我做：牌很大" in prompt
    assert "对手阿强" in prompt
    assert "负" in prompt
    assert "吐槽" in prompt and "阿强" in prompt
    assert "炸金花" in system


# ── 开关矩阵 ──


def test_game_enabled_matrix() -> None:
    assert _game_enabled({}, "tenhalf")  # 无配置默认十点半开
    assert not _game_enabled({}, "zjh")
    assert not _game_enabled({"ai_review_enabled": False}, "tenhalf")
    assert _game_enabled({"ai_review_games": ["zjh", "horse"]}, "zjh")
    assert not _game_enabled({"ai_review_games": ["zjh", "horse"]}, "tenhalf")
    assert not _game_enabled({"tenhalf_ai_comment": False}, "tenhalf")  # 旧键显式关闭兼容
    assert _game_enabled({"tenhalf_ai_comment": True}, "tenhalf")


def test_group_ids_parsing() -> None:
    assert _group_ids({}) == []
    assert _group_ids({"ai_review_groups": "-100123, -100456"}) == ["-100123", "-100456"]
    assert _group_ids({"ai_review_groups": "-100123\n@chat_x"}) == ["-100123", "@chat_x"]
    assert _group_ids({"ai_review_groups": "   "}) == []


# ── review 集成 ──


@pytest.mark.asyncio
async def test_review_notify_channel_by_default() -> None:
    """无群配置 → 走 ctx.notify 通知中心，消息带游戏名前缀。"""
    ctx, ai, _ = _ctx()
    steps = [[0.0, "", "hit", None, None, None]]
    await review(ctx, {}, "tenhalf", 198, "胜", opponent="麦克格雷涛", actions=steps, labels={"hit": "要牌"})
    assert ai and ai.calls and "炫耀" in ai.calls[0][0] and "麦克" in ai.calls[0][0]
    assert any("十点半心路历程" in str(msg) and "还好我稳住了！" in str(msg) for msg, _ in ctx.notifications)


@pytest.mark.asyncio
async def test_review_sends_to_configured_groups() -> None:
    """配置了 ai_review_groups → 直发群（数字转 int，@用户名原样）。"""
    ctx, _, bot = _ctx(with_bot=True)
    cfg = {"ai_review_groups": "-100123\n@chat_x"}
    await review(ctx, cfg, "tenhalf", -100, "负", opponent="南凝 徐", actions=None)
    assert bot and len(bot.sent) == 2
    assert bot.sent[0][0] == -100123 and isinstance(bot.sent[0][0], int)
    assert bot.sent[1][0] == "@chat_x"
    assert all("心路历程" in text for _, text in bot.sent)
    assert not ctx.notifications  # 直发群时不再走通知中心


@pytest.mark.asyncio
async def test_review_skips_when_disabled_or_not_selected() -> None:
    ctx, ai, _ = _ctx()
    await review(ctx, {"ai_review_games": ["zjh"]}, "tenhalf", 198, "胜")
    await review(ctx, {"ai_review_enabled": False, "ai_review_games": ["tenhalf"]}, "tenhalf", 198, "胜")
    assert ai and not ai.calls and not ctx.notifications


@pytest.mark.asyncio
async def test_review_skips_without_ai() -> None:
    ctx, _, _ = _ctx(ai_reply=None)
    await review(ctx, {}, "tenhalf", 198, "胜")
    assert not ctx.notifications
    assert any("跳过" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_review_failure_does_not_raise() -> None:
    """AI 抛异常 / 群发送失败 → 静默记日志，不冒泡。"""
    ctx = _FakeCtx(ai=_FakeAI(fail=RuntimeError("ai down")), bot=_FakeBot())
    await review(ctx, {"ai_review_groups": "-100123"}, "tenhalf", 198, "胜")
    assert any("AI 评价失败" in msg for _, msg in ctx.log.records)
    ctx, _, _ = _ctx(with_bot=False)
    ctx.bot = _FakeBot(fail=RuntimeError("bot down"))
    await review(ctx, {"ai_review_groups": "-1"}, "tenhalf", 198, "胜")
    assert any("直发群" in msg for _, msg in ctx.log.records)


@pytest.mark.asyncio
async def test_review_all_games_labels() -> None:
    """四个游戏都能评价：游戏名进入 system 与消息前缀。"""
    for game, label in [("tenhalf", "十点半"), ("zjh", "炸金花"), ("horse", "养马"), ("lucky", "幸运轮盘")]:
        ctx, ai, _ = _ctx()
        await review(ctx, {"ai_review_games": [game]}, game, 50, "结果文本", actions="走了几步")
        assert ai and ai.calls and label in ai.calls[0][1] or ""
        assert any(label in str(msg) for msg, _ in ctx.notifications)
