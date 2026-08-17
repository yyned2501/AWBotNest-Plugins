# -*- coding: utf-8 -*-
# skyDropAnswer 单元测试
#
# 覆盖：触发判定（开启时段/文案类型选择/模板与背诗分段/配额与调度 gate/
# /info 校准/跨小时翻转）、答案判定（按钮三级匹配/模板命中/答题提交流程，
# 含无 AI 跳过与按钮不匹配的边界）、模板验证升级（learning → verified）。
# 宿主依赖全部用 _FakeContext / 假 message 隔离，不触碰真实 Telegram/AI。

from __future__ import annotations

from typing import Any

import pytest

from plugins.skyDropAnswer import answer as answer_mod
from plugins.skyDropAnswer import models as models_mod
from plugins.skyDropAnswer import templates as templates_mod
from plugins.skyDropAnswer import trigger as trigger_mod
from plugins.skyDropAnswer.answer import _answer_and_submit, _match_button
from plugins.skyDropAnswer.models import _DROP_REGEX, _ensure_hour
from plugins.skyDropAnswer.templates import _match_templates, _verify_template
from plugins.skyDropAnswer.trigger import (
    _apply_info_reply,
    _in_active_window,
    _pick_trigger_kind,
    _pick_trigger_segments,
    _trigger_tick,
)

# ─────────────────────────────────────────────────────────────
# 假宿主上下文：kv / log / user.send / ai / notify 全部内存替身
# ─────────────────────────────────────────────────────────────


class _FakeKv:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.store[key] = value

    def keys(self) -> list[str]:
        return list(self.store.keys())

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _sink(self, msg: str, *args: Any) -> None:
        self.lines.append(msg % args if args else msg)

    info = warning = error = _sink


class _FakeUser:
    """记录 ctx.user.send 的私聊/群发消息。"""

    def __init__(self) -> None:
        self.sends: list[tuple[Any, str]] = []

    async def send(self, target: Any, text: str) -> None:
        self.sends.append((target, text))


class _FakeAi:
    def __init__(self, available: bool = False, reply: str = "") -> None:
        self.available = available
        self.reply = reply
        self.prompts: list[str] = []

    async def chat(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class _FakeContext:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}
        self.kv = _FakeKv()
        self.log = _FakeLog()
        self.user = _FakeUser()
        self.ai = _FakeAi()
        self.updated: dict[str, Any] = {}
        self.notifications: list[tuple[str, str, str]] = []

    def update_config(self, values: dict[str, Any]) -> None:
        self.updated.update(values)

    async def notify(self, message: str, level: str = "info", category: str = "", **kwargs: Any) -> None:
        self.notifications.append((level, category, message))


def _prime_clock_keys(ctx: _FakeContext) -> None:
    """把 kv 的时段/日期键预设为当前值，避免测试中途触发跨小时/跨天重置。"""
    ctx.kv.set("trig:hour_key", models_mod._get_hour_key())
    ctx.kv.set("trig:day_key", models_mod._get_day_key())


class _FakeClock:
    """替掉 trigger 模块的 datetime：now() 返回固定时分。"""

    def __init__(self, hour: int, minute: int = 30) -> None:
        self.hour = hour
        self.minute = minute

    def now(self, tz: Any = None) -> "_FakeClock":
        return self


# ─────────────────────────────────────────────────────────────
# 触发判定：开启时段 / 文案类型选择 / 消息段生成
# ─────────────────────────────────────────────────────────────


def test_in_active_window_inclusive_and_cross_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    # 正向：[start, end] 含端点
    monkeypatch.setattr(trigger_mod, "datetime", _FakeClock(8))
    assert _in_active_window({"trig_active_start": 8, "trig_active_end": 23}) is True
    monkeypatch.setattr(trigger_mod, "datetime", _FakeClock(23))
    assert _in_active_window({"trig_active_start": 8, "trig_active_end": 23}) is True
    # 边界：窗口外一小时
    monkeypatch.setattr(trigger_mod, "datetime", _FakeClock(7))
    assert _in_active_window({"trig_active_start": 8, "trig_active_end": 23}) is False
    # 跨午夜 22→6：两端内均允许，中间拒绝
    for hour, expected in ((23, True), (3, True), (12, False)):
        monkeypatch.setattr(trigger_mod, "datetime", _FakeClock(hour))
        assert _in_active_window({"trig_active_start": 22, "trig_active_end": 6}) is expected


def test_pick_trigger_kind_filters_empty_pools_and_falls_back() -> None:
    # 勾选背诗但池为空 → 回退模板，保证 random.choice 不拿空列表
    assert _pick_trigger_kind({"trig_kinds": ["poem"], "trig_msg_poems": ""}) == "template"
    # 全不选 → 同样回退模板
    assert _pick_trigger_kind({"trig_kinds": []}) == "template"
    # 勾选唱歌且池非空 → 唯一候选即唱歌
    assert _pick_trigger_kind({"trig_kinds": ["song"], "trig_msg_songs": "一句歌词"}) == "song"


def test_pick_trigger_segments_template_format_and_fallback() -> None:
    ctx = _FakeContext()
    # 正向：{n}/{x} 占位符替换
    cfg = {"trig_message_template": "第{n}题{x} 求掉落"}
    assert _pick_trigger_segments(ctx, cfg, "template", 3, 2) == ["第3题2 求掉落"]
    # 边界：模板占位符写坏 → 回退默认格式而不是抛异常
    assert _pick_trigger_segments(ctx, {"trig_message_template": "{n} {bad"}, "template", 3, 2) == ["第3题2"]


def test_pick_trigger_segments_poem_cycles_lines_and_splits_punct() -> None:
    ctx = _FakeContext()
    cfg = {"trig_msg_poems": "静夜思，李白。\n春眠不觉晓"}
    # 第一行按标点拆成多段
    assert _pick_trigger_segments(ctx, cfg, "poem", 1, 1) == ["静夜思", "李白"]
    assert ctx.kv.get("trig:poem_idx") == 1
    # 第二行无标点，原样单段
    assert _pick_trigger_segments(ctx, cfg, "poem", 1, 2) == ["春眠不觉晓"]
    # 行号循环回第一行
    assert _pick_trigger_segments(ctx, cfg, "poem", 1, 3) == ["静夜思", "李白"]


# ─────────────────────────────────────────────────────────────
# 触发判定：_trigger_tick 调度 gate 与 /info 校准
# ─────────────────────────────────────────────────────────────


def _base_trig_config(**over: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "trig_enabled": True,
        "target_groups": "-1001234567890",
        "trig_use_info": False,
        "trig_start_min": 0,
        "trig_active_start": 0,
        "trig_active_end": 23,
        "bot": "@skybot",
    }
    cfg.update(over)
    return cfg


async def test_trigger_tick_disabled_goes_idle() -> None:
    ctx = _FakeContext({"trig_enabled": False})
    ctx.kv.set("trig:phase", "round")
    await _trigger_tick(ctx)
    assert ctx.kv.get("trig:phase") == "idle"
    assert ctx.user.sends == []


async def test_trigger_tick_no_groups_does_nothing() -> None:
    ctx = _FakeContext(_base_trig_config(target_groups=""))
    _prime_clock_keys(ctx)
    await _trigger_tick(ctx)
    assert ctx.user.sends == []
    assert ctx.kv.get("trig:phase") in (None, "idle")


async def test_trigger_tick_quota_exhausted_idles() -> None:
    ctx = _FakeContext(_base_trig_config())
    _prime_clock_keys(ctx)
    ctx.kv.set("trig:drops_this_hour", 4)
    ctx.kv.set("trig:drops_per_hour", 4)
    await _trigger_tick(ctx)
    # 边界：本时段配额用完 → 停在 idle，不再触发
    assert ctx.kv.get("trig:phase") == "idle"
    assert ctx.user.sends == []


async def test_trigger_tick_scheduled_not_due_waits() -> None:
    import time

    ctx = _FakeContext(_base_trig_config())
    _prime_clock_keys(ctx)
    ctx.kv.set("trig:phase", "scheduled")
    ctx.kv.set("trig:next_round_at", time.time() + 999)
    await _trigger_tick(ctx)
    # 未到定时点：维持 scheduled，不发任何消息
    assert ctx.kv.get("trig:phase") == "scheduled"
    assert ctx.user.sends == []


async def test_trigger_tick_idle_sends_info_first() -> None:
    ctx = _FakeContext(_base_trig_config(trig_use_info=True))
    _prime_clock_keys(ctx)
    await _trigger_tick(ctx)
    # 正向：开启 /info 校准时，先私聊 bot 发 /info 并进入 await_info
    assert ctx.user.sends == [("@skybot", "/info")]
    assert ctx.kv.get("trig:phase") == "await_info"


def test_apply_info_reply_calibrates_quota() -> None:
    ctx = _FakeContext()
    ctx.kv.set("trig:drops_this_hour", 1)
    _apply_info_reply(ctx, "天空小秘状态\n当前时段剩余掉落: 3\n其他信息")
    assert ctx.kv.get("trig:drops_per_hour") == 4  # 剩余 3 + 已掉 1
    # 异常：回复解析不出剩余掉落 → 只告警不写配额
    ctx2 = _FakeContext()
    _apply_info_reply(ctx2, "一段无关文本")
    assert ctx2.kv.get("trig:drops_per_hour") is None
    assert any("剩余掉落" in ln for ln in ctx2.log.lines)


def test_ensure_hour_resets_on_rollover_and_is_idempotent() -> None:
    ctx = _FakeContext()
    ctx.kv.set("trig:hour_key", "2000-01-01-00")  # 陈旧小时键 → 触发翻转重置
    ctx.kv.set("trig:drops_this_hour", 3)
    ctx.kv.set("trig:question", 5)
    _ensure_hour(ctx)
    assert ctx.kv.get("trig:hour_key") == models_mod._get_hour_key()
    assert ctx.kv.get("trig:drops_this_hour") == 0
    assert ctx.kv.get("trig:question") == 1
    # 幂等：同一小时内再次调用不清空新累计值
    ctx.kv.set("trig:drops_this_hour", 2)
    _ensure_hour(ctx)
    assert ctx.kv.get("trig:drops_this_hour") == 2


def test_drop_regex_matches_reward_message() -> None:
    import re

    assert re.search(_DROP_REGEX, "小秘想给你 200 银元奖励。快来答题！")
    assert not re.search(_DROP_REGEX, "普通群聊消息")


# ─────────────────────────────────────────────────────────────
# 答案判定：按钮三级匹配 / 模板命中 / 答题提交
# ─────────────────────────────────────────────────────────────


class _FakeButton:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMarkup:
    def __init__(self, rows: list[list[_FakeButton]]) -> None:
        self.inline_keyboard = rows


class _FakeUser2:
    """消息发送者替身（出题 bot）。"""

    def __init__(self) -> None:
        self.id = 8907007783
        self.username = "skyxiaomi"


class _FakeChat:
    def __init__(self) -> None:
        self.title = "测试群"
        self.id = -1001234567890


class _FakeMessage:
    """带内联键盘的消息替身，记录 click 坐标。"""

    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.reply_markup = _FakeMarkup([[_FakeButton(t) for t in row] for row in rows]) if rows else None
        self.clicks: list[tuple[int, int]] = []
        self.from_user = _FakeUser2()
        self.chat = _FakeChat()
        self.link = "https://t.me/c/1/1"

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((y, x))  # 记录为 (row, col) 便于断言


def test_match_button_priority_exact_over_numeric_over_contains() -> None:
    msg = _FakeMessage([["1", "16"], ["16.0", "选项16"]])
    # 精确相等优先于数值相等：选 (0,1) 而非数值等价的 (1,0)
    assert _match_button(msg, "16") == (0, 1)
    # 数值相等：答案 "16.0" 匹配文本 "16"
    assert _match_button(_FakeMessage([["16"]]), "16.0") == (0, 0)
    # 文本包含兜底：按钮带装饰文字
    assert _match_button(_FakeMessage([["点击领取4号"]]), "4") == (0, 0)


def test_match_button_returns_none_without_keyboard_or_empty_answer() -> None:
    assert _match_button(_FakeMessage(None), "16") is None
    assert _match_button(_FakeMessage([["16"]]), "  ") is None
    assert _match_button(_FakeMessage([["1", "2"]]), "99") is None


def test_match_templates_hit_miss_and_bad_regex() -> None:
    tpls = [
        {"regex": "[坏正则", "extract": lambda t: "bad"},
        {"regex": r"等于\s*\?", "extract": lambda t: "16"},
    ]
    fn, tpl = _match_templates("3 加 13 等于 ?", tpls)
    assert tpl is tpls[1] and fn is not None and fn("") == "16"  # 非法正则被跳过
    assert _match_templates("完全无关的题目", tpls) == (None, None)


def _make_verified_tpl(extract: Any) -> dict[str, Any]:
    return {
        "id": "builtin_math",
        "type": "算术题",
        "regex": r"等于\s*\?",
        "status": "verified",
        "verify_count": 3,
        "count": 0,
        "extract": extract,
    }


async def test_answer_and_submit_verified_template_clicks_button(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向：verified 模板命中 → 提取答案 → 点对应按钮 → 推送通知 → 计数落 kv。"""

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(answer_mod.asyncio, "sleep", _no_sleep)
    ctx = _FakeContext({"reward_delay_min": 1, "reward_delay_max": 2})
    msg = _FakeMessage([["7", "16"]])
    tpl = _make_verified_tpl(lambda t: "16")

    await _answer_and_submit("3 加 13 等于 ?", object(), msg, ctx, [tpl])

    assert msg.clicks == [(0, 1)]  # 点了文本为 16 的按钮
    assert tpl["count"] == 1
    assert ctx.kv.get("tpl_count:builtin_math") == 1
    assert len(ctx.notifications) == 1
    level, category, text = ctx.notifications[0]
    assert (level, category) == ("success", "已答")
    assert "答案: 16" in text and "测试群" in text


async def test_answer_and_submit_no_template_no_ai_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """边界：无模板命中且 AI 兜底关闭 → 跳过，不点击不通知。"""

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(answer_mod.asyncio, "sleep", _no_sleep)
    ctx = _FakeContext({"use_ai_fallback": False})
    msg = _FakeMessage([["7", "16"]])

    await _answer_and_submit("没见过的题型", object(), msg, ctx, [])

    assert msg.clicks == []
    assert ctx.notifications == []
    assert any("无法解答" in ln for ln in ctx.log.lines)


async def test_answer_and_submit_no_matching_button_skips_click(monkeypatch: pytest.MonkeyPatch) -> None:
    """边界：模板给出答案但键盘上没有对应按钮 → 不点击，通知仍推送。"""

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(answer_mod.asyncio, "sleep", _no_sleep)
    ctx = _FakeContext()
    msg = _FakeMessage([["1", "2"]])
    tpl = _make_verified_tpl(lambda t: "99")

    await _answer_and_submit("3 加 13 等于 ?", object(), msg, ctx, [tpl])

    assert msg.clicks == []
    assert any("未找到匹配答案" in ln for ln in ctx.log.lines)
    assert len(ctx.notifications) == 1


# ─────────────────────────────────────────────────────────────
# 模板生成：learning 模板连续三次验证一致后升级 verified
# ─────────────────────────────────────────────────────────────


async def test_verify_template_promotes_after_three_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[dict[str, Any]] = []
    monkeypatch.setattr(templates_mod, "_update_template_file", lambda tpl, **kw: writes.append(kw))
    ctx = _FakeContext()
    tpl: dict[str, Any] = {"id": "learned_math", "status": "learning", "verify_count": 2}

    # 第 3 次一致 → 升级 verified
    assert await _verify_template("16", "16", tpl, ctx) == "16"
    assert tpl["verify_count"] == 3 and tpl["status"] == "verified"

    # 之后 script 与 AI 不一致 → 验证计数清零
    assert await _verify_template("16", "99", tpl, ctx) is None
    assert tpl["verify_count"] == 0
    assert writes  # 每次验证结果都落文件
