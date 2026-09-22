# -*- coding: utf-8 -*-
# 天空答题 · 答题主逻辑（按钮匹配 + 模板/AI 解答 + 提交 + 通知）

from __future__ import annotations

import asyncio
import inspect
import random
import re
import time

from .models import (
    _DROP_REGEX,
    _PROMPT_ANSWER,
    _ensure_day,
    _ensure_hour,
    _extract_message,
    _is_group_message,
    _replies_to_own,
    _sender_id,
    _sender_username,
    refresh_stats,
)
from .templates import _learn_template, _match_templates, _save_template_count, _verify_template

# 防抖：记录已处理的消息 ID（带时间戳，TTL 清理防无界增长）
_DEDUP_TTL = 3600.0


def _button_text_rows(message: object) -> list[list[str]]:
    """取内联键盘的按钮文本矩阵（行 → 列），按运行时差异兼容两种结构。

    Pyrogram：reply_markup.inline_keyboard = [[Button, ...], ...]
    Telethon：reply_markup.rows = [Row(buttons=[Button, ...]), ...]
    """
    markup = getattr(message, "reply_markup", None)
    if markup is None:
        return []
    rows = getattr(markup, "inline_keyboard", None)
    if rows:
        return [[(getattr(b, "text", "") or "").strip() for b in row] for row in rows]
    rows = getattr(markup, "rows", None)
    if not rows:
        return []
    return [[(getattr(b, "text", "") or "").strip() for b in (getattr(row, "buttons", None) or [])] for row in rows]


def _match_button(message: object, ans: str) -> tuple[int, int] | None:
    """在内联键盘里找与答案匹配的按钮，返回 (row, col) 或 None。

    匹配优先级：文本精确相等 > 数值相等 > 文本包含答案。
    同时兼容两类答案：
      - 「答案是按钮上的值」（数学题，如答案 16 → 点文本为 16 的按钮）
      - 「答案是序号/选项号」（找不同、映射记忆，如答案 4 → 点文本为 4 的按钮）
    """
    keyboard = _button_text_rows(message)
    if not keyboard:
        return None
    ans_s = str(ans).strip()
    if not ans_s:
        return None
    buttons = [(r, c, text) for r, row in enumerate(keyboard) for c, text in enumerate(row)]
    # 1) 文本精确相等
    for r, c, text in buttons:
        if text == ans_s:
            return (r, c)
    # 2) 数值相等（兼容 "16" / "16.0"）
    try:
        ans_num = float(ans_s)
    except ValueError:
        ans_num = None
    if ans_num is not None:
        for r, c, text in buttons:
            try:
                if float(text) == ans_num:
                    return (r, c)
            except ValueError:
                continue
    # 3) 文本包含答案（按钮带装饰文字时的兜底）
    for r, c, text in buttons:
        if ans_s in text:
            return (r, c)
    return None


async def _click_cell(message: object, row: int, col: int) -> None:
    """点击内联按钮：V2/Telethon 是 click(i=行, j=列)，Pyrogram 适配期是 click(x=列, y=行)。

    按签名形参选择调用形式，避免位置参数被不同运行时解释成行列互换。
    """
    try:
        params = set(inspect.signature(message.click).parameters)  # type: ignore[union-attr]
    except (TypeError, ValueError):  # 内置/C 实现拿不到签名，退回位置参数
        params = set()
    if {"i", "j"} & params:
        await message.click(i=row, j=col)  # type: ignore[union-attr]
    elif {"x", "y"} & params:
        await message.click(x=col, y=row)  # type: ignore[union-attr]
    else:
        await message.click(row, col)  # type: ignore[union-attr]


async def _answer_and_submit(
    text: str,
    client: object,
    message: object,
    ctx: object,
    templates: list[dict],
) -> None:
    """答题主逻辑：模板匹配 → 验证循环/AI兜底 → 提交"""
    ans = None
    extract_fn, tpl = _match_templates(text, templates)

    if tpl:
        status = tpl.get("status", "verified")

        if status == "verified":
            ans = extract_fn(text) if extract_fn else None
            if ans:
                ctx.log.info("模板命中(verified): %s → %s", tpl["type"], ans)
                tpl["count"] = tpl.get("count", 0) + 1
                _save_template_count(tpl["id"], tpl["count"], ctx)

        elif status == "learning":
            script_ans = extract_fn(text) if extract_fn else None
            if ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
                try:
                    ai_text = f"{_PROMPT_ANSWER}\n\n题目: {text}"
                    ai_ans = (await ctx.ai.chat(ai_text)).strip()[:20]
                    if ai_ans:
                        result = await _verify_template(ai_ans, script_ans, tpl, ctx)
                        if result:
                            ans = result
                            ctx.log.info("验证通过(%d/3): %s", tpl["verify_count"], ans)
                        else:
                            ans = ai_ans
                            ctx.log.info("验证不一致，使用AI答案: %s (script=%s)", ans, script_ans)
                except Exception as e:
                    ctx.log.warning("验证AI调用失败: %r", e)
                    ans = script_ans
            else:
                ans = script_ans

            if ans:
                tpl["count"] = tpl.get("count", 0) + 1
                _save_template_count(tpl["id"], tpl["count"], ctx)

    # AI 兜底（无模板命中时）
    if not ans and ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
        try:
            ctx.log.info("无模板命中，使用AI分析: %s", text[:60])
            ai_ans = await ctx.ai.chat(f"{_PROMPT_ANSWER}\n\n题目: {text}")
            ai_ans = (ai_ans.strip() or "")[:20]
            if ai_ans:
                ans = ai_ans
                ctx.log.info("AI回答: %s", ans)
                await _learn_template(text, ans, ctx, templates)
        except Exception as e:
            ctx.log.warning("AI分析失败: %r", e)

    if not ans:
        ctx.log.info("无法解答，跳过")
        return

    ctx.log.info("最终答案: %s", ans)
    d_min = int(ctx.config.get("reward_delay_min", 2) or 2)
    d_max = int(ctx.config.get("reward_delay_max", 5) or 5)
    if d_min >= d_max:
        d_max = d_min + 1
    await asyncio.sleep(random.uniform(d_min, d_max))

    # 提交答案：按按钮文本匹配答案（兼容「值为答案」与「序号为答案」两类题型）
    pos = _match_button(message, ans)
    if pos:
        row, col = pos
        try:
            await _click_cell(message, row, col)
            ctx.log.info("点击按钮 (%d,%d)，答案 %s", row, col, ans)
        except Exception as e:
            ctx.log.warning("点击按钮失败: %r", e)
    else:
        ctx.log.warning("未找到匹配答案 %s 的按钮，跳过", ans)

    # 向出题机器人推送通知
    try:
        chat = getattr(message, "chat", None)
        if chat is not None:
            chat_title = getattr(chat, "title", "") or getattr(chat, "name", "") or ""
            question_preview = text[:300] + ("..." if len(text) > 300 else "")
            account_kwargs = {"account": client} if client is not None else {}
            await ctx.notify(
                f"🏠 所在群组\n   {chat_title}\n   群ID: {getattr(chat, 'id', '?')}\n\n"
                f"❓ 题目\n   {question_preview}\n\n"
                f"📩 答题结果\n   答案: {ans}\n\n"
                f"🔗 消息链接\n   {getattr(message, 'link', '')}",
                level="success",
                category="已答",
                **account_kwargs,
            )
            ctx.log.info("已向机器人推送答题结果")
    except Exception as e:
        ctx.log.warning("向机器人推送通知失败: %r", e)

    ctx.log.info("答题完成")


def register_answer_handler(ctx: object, templates: list[dict]) -> None:
    """注册答题奖励 handler（窄匹配：群消息 + 掉落文案 + 仅处理回复我自己消息的掉落）。

    V2 平台（Telethon 底层）不提供 ctx.filters 与 group 关键字，回调也只收到单个
    event，因此过滤在 handler 内手动完成。
    """
    processed_msg_ids: dict[int, float] = {}
    probe_warned = False

    @ctx.on_message()
    async def _reward_handler(*args: object, **kwargs: object) -> None:
        nonlocal probe_warned
        if not ctx.config.get("enable_reward_answer", False):
            return
        message, event = _extract_message(args, kwargs)
        if message is None:
            return
        # 原 reward_filter：group & text & regex(_DROP_REGEX) & 回复我自己
        if not _is_group_message(message, event):
            return
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
        if not text or not re.search(_DROP_REGEX, text):
            return
        if not await _replies_to_own(message, event):
            # 只在运行时压根不提供 get_reply_message 时留一次线索，避免归属判断静默失效
            if not probe_warned and not callable(getattr(event, "get_reply_message", None)):
                probe_warned = True
                ctx.log.warning("掉落归属无法判断：运行时 event 缺 get_reply_message，请反馈这条日志")
            return
        # (client, message) 双参数形态下 args[0] 即 client；Telethon 单参数时取 event.client
        client = args[0] if len(args) >= 2 else getattr(event, "client", None)

        # 防抖：同一消息只处理一次（顺带清理过期记录，防集合无界增长）
        now = time.time()
        if len(processed_msg_ids) > 500:
            stale = [k for k, ts in processed_msg_ids.items() if now - ts > _DEDUP_TTL]
            for k in stale:
                processed_msg_ids.pop(k, None)
        msg_id = getattr(message, "id", None) or getattr(event, "id", None)
        if msg_id in processed_msg_ids:
            ctx.log.info("跳过重复消息: %s", msg_id)
            return
        processed_msg_ids[msg_id] = now
        bot_cfg = str(ctx.config.get("bot", "") or "").strip()
        if bot_cfg:
            bot_ids = [b.strip().lstrip("@") for b in bot_cfg.replace("，", ",").split(",") if b.strip()]
            sender_id = str(_sender_id(message, event) or "")
            sender_name = _sender_username(message, event)
            if bot_ids and sender_id not in bot_ids and sender_name not in bot_ids:
                return

        # 掉落计数：写入共享 kv 供触发状态机读取
        _ensure_day(ctx)
        _ensure_hour(ctx)
        drops = int(ctx.kv.get("trig:drops_this_hour", 0) or 0) + 1
        ctx.kv.set("trig:drops_this_hour", drops)
        ctx.kv.set("trig:last_drop_ts", time.time())
        total = int(ctx.kv.get("trig:drop_count", 0) or 0) + 1
        ctx.kv.set("trig:drop_count", total)
        drop_today = int(ctx.kv.get("trig:drop_today", 0) or 0) + 1
        ctx.kv.set("trig:drop_today", drop_today)
        ctx.log.info(
            "检测到天空掉落（本时段第 %d 次 · 今日第 %d 次 · 累计 %d 次）msg=%s",
            drops,
            drop_today,
            total,
            msg_id,
        )
        refresh_stats(ctx)

        await _answer_and_submit(text, client, message, ctx, templates)
