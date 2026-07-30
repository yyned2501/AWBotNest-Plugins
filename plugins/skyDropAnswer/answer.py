# -*- coding: utf-8 -*-
# 天空答题 · 答题主逻辑（按钮匹配 + 模板/AI 解答 + 提交 + 通知）

from __future__ import annotations

import asyncio
import random
import time

from .models import _DROP_REGEX, _PROMPT_ANSWER, _reply_to_own_filter
from .templates import _learn_template, _match_templates, _save_template_count, _verify_template

# 防抖：记录已处理的消息 ID（带时间戳，TTL 清理防无界增长）
_DEDUP_TTL = 3600.0


def _match_button(message: object, ans: str) -> tuple[int, int] | None:
    """在内联键盘里找与答案匹配的按钮，返回 (row, col) 或 None。

    匹配优先级：文本精确相等 > 数值相等 > 文本包含答案。
    同时兼容两类答案：
      - 「答案是按钮上的值」（数学题，如答案 16 → 点文本为 16 的按钮）
      - 「答案是序号/选项号」（找不同、映射记忆，如答案 4 → 点文本为 4 的按钮）
    """
    markup = getattr(message, "reply_markup", None)
    keyboard = getattr(markup, "inline_keyboard", None) if markup else None
    if not keyboard:
        return None
    ans_s = str(ans).strip()
    if not ans_s:
        return None
    buttons = [
        (r, c, (getattr(btn, "text", "") or "").strip()) for r, row in enumerate(keyboard) for c, btn in enumerate(row)
    ]
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
            await message.click(x=col, y=row)
            ctx.log.info("点击按钮 (%d,%d)，答案 %s", row, col, ans)
        except Exception as e:
            ctx.log.warning("点击按钮失败: %r", e)
    else:
        ctx.log.warning("未找到匹配答案 %s 的按钮，跳过", ans)

    # 向出题机器人推送通知
    try:
        bot_user = message.from_user
        if bot_user:
            chat_title = getattr(message.chat, "title", "") if message.chat else ""
            question_preview = text[:300] + ("..." if len(text) > 300 else "")
            await ctx.notify(
                f"🏠 所在群组\n   {chat_title}\n   群ID: {message.chat.id}\n\n"
                f"❓ 题目\n   {question_preview}\n\n"
                f"📩 答题结果\n   答案: {ans}\n\n"
                f"🔗 消息链接\n   {getattr(message, 'link', '')}",
                level="success",
                category="已答",
                account=client,
            )
            ctx.log.info("已向机器人推送答题结果")
    except Exception as e:
        ctx.log.warning("向机器人推送通知失败: %r", e)

    ctx.log.info("答题完成")


def register_answer_handler(ctx: object, templates: list[dict]) -> None:
    """注册答题奖励 handler（group=5，窄匹配：仅处理回复我自己消息的掉落）。"""
    processed_msg_ids: dict[int, float] = {}

    reward_filter = (
        ctx.filters.group & ctx.filters.text & ctx.filters.regex(_DROP_REGEX) & ctx.filters.create(_reply_to_own_filter)
    )

    @ctx.on_message(reward_filter, group=5)
    async def _reward_handler(client: object, message: object) -> None:
        if not ctx.config.get("enable_reward_answer", False):
            return
        # 防抖：同一消息只处理一次（顺带清理过期记录，防集合无界增长）
        now = time.time()
        if len(processed_msg_ids) > 500:
            stale = [k for k, ts in processed_msg_ids.items() if now - ts > _DEDUP_TTL]
            for k in stale:
                processed_msg_ids.pop(k, None)
        if message.id in processed_msg_ids:
            ctx.log.info("跳过重复消息: %s", message.id)
            return
        processed_msg_ids[message.id] = now
        bot_cfg = str(ctx.config.get("bot", "") or "").strip()
        if bot_cfg:
            bot_ids = [b.strip().lstrip("@") for b in bot_cfg.replace("，", ",").split(",") if b.strip()]
            sender_id = str(message.from_user.id) if message.from_user else ""
            sender_name = (message.from_user.username or "") if message.from_user else ""
            if bot_ids and sender_id not in bot_ids and sender_name not in bot_ids:
                return
        await _answer_and_submit((message.text or "").strip(), client, message, ctx, templates)
