# -*- coding: utf-8 -*-
# AWBotNest 插件：天空答题 (skyDropAnswer)

import asyncio
import json
import random
import re
import time
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

__plugin__ = {
    "name": "天空答题",
    "id": "skyDropAnswer",
    "version": "1.1.0",
    "author": "Yy",
    "description": "天空答题奖励，自动回复机器人的数学题/找不同/映射记忆，AI兜底未知题型。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "enable_reward_answer": {
            "type": "boolean", "default": False, "label": "开启答题奖励",
            "section": "答题奖励", "order": 1
        },
        "reward_bot_ids": {
            "type": "string", "default": "", "label": "答题机器人",
            "section": "答题奖励", "help": "@机器人用户名，逗号分隔", "order": 2
        },
        "reward_delay_min": {
            "type": "number", "default": 2, "label": "延迟最小",
            "section": "答题奖励", "min": 1, "max": 30, "help": "秒", "order": 3
        },
        "reward_delay_max": {
            "type": "number", "default": 5, "label": "延迟最大",
            "section": "答题奖励", "min": 1, "max": 60, "help": "秒", "order": 4
        },
        "use_ai_fallback": {
            "type": "boolean", "default": True, "label": "AI智能答题",
            "section": "答题奖励", "help": "未知题型时使用AI分析并回答", "order": 5
        },
        "test_say": {
            "type": "action", "label": "🎤 立即发言", "section": "操作",
            "action": "test_say"
        },
    },
}

_KV_PENDING = "auto_say_pending_rewards"


def _parse_ids(raw) -> list[int]:
    """解析逗号/换行分隔的ID列表"""
    out = []
    for c in str(raw or "").replace("\n", ",").split(","):
        c = c.strip()
        if not c:
            continue
        try:
            out.append(int(c))
        except ValueError:
            pass
    return out


async def setup(ctx):
    ctx.log.info("天空答题插件已加载")

    # ── 记录用户自己发的消息，用于答题奖励 ──
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=3)
    async def _user_msg_handler(client, message):
        if not ctx.config.get("enable_reward_answer", False):
            return
        pending = ctx.kv.get(_KV_PENDING, [])
        pending.append({"chat_id": message.chat.id, "msg_id": message.id, "time": time.time()})
        ctx.kv.set(_KV_PENDING, pending[-20:])

    # ── 答题奖励 ──
    @ctx.on_message(ctx.filters.group & ctx.filters.text & ctx.filters.reply & ctx.filters.regex(r"小秘想给你 \d+ 银元奖励。"), group=5)
    async def _reward_handler(client, message):
        if not ctx.config.get("enable_reward_answer", False):
            return
        # 检查是否来自指定机器人
        reward_bots = str(ctx.config.get("reward_bot_ids", "") or "").strip()
        if reward_bots:
            bot_ids = [b.strip().lstrip("@") for b in reward_bots.replace("，", ",").split(",") if b.strip()]
            sender_id = str(message.from_user.id) if message.from_user else ""
            sender_name = (message.from_user.username or "") if message.from_user else ""
            if bot_ids and sender_id not in bot_ids and sender_name not in bot_ids:
                return
        # 检查是否回复了我们的消息
        pending = ctx.kv.get(_KV_PENDING, [])
        matched = [p for p in pending if p["chat_id"] == message.chat.id and p["msg_id"] == message.reply_to_message_id]
        if not matched:
            return
        # 清理过期记录
        now = time.time()
        ctx.kv.set(_KV_PENDING, [p for p in pending if now - p.get("time", 0) < 300])

        text = (message.text or "").strip()
        _PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要加任何解释。"
        ans = None

        # 1. 数学题: 14 + 2 = 多少？
        m = re.search(r"请回答[：:]\s*(\d+)\s*([+\-×xX*/])\s*(\d+)\s*=\s*多少\s*[?？]", text)
        if m:
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            if op in ("+",): ans = str(a + b)
            elif op in ("-",): ans = str(a - b)
            elif op in ("×", "x", "X", "*"): ans = str(a * b)
            elif op in ("/",): ans = str(a // b) if b != 0 else "0"
            ctx.log.info("[天空答题] 数学题: %d %s %d = %s", a, op, b, ans)

        # 2. 找不同: 🐱 🐱 🐱 🐯 🐱 🐱 → 点击第4个
        if not ans:
            m = re.search(r"找出唯一不同的图案，点击它的位置[：:]\s*\n(.+)", text)
            if m:
                line = m.group(1).strip()
                items = re.split(r"\s+", line)
                # 找不同的那个
                from collections import Counter
                if len(items) >= 3:
                    counts = Counter(items)
                    for i, item in enumerate(items, 1):
                        if counts[item] == 1:
                            ans = str(i)
                            ctx.log.info("[天空答题] 找不同: %s → 第%d个", item, i)
                            break

        # 3. 映射记忆: 🔺=9、☀️=7、🌙=4 请问 ☀️ 对应哪个数字？
        if not ans:
            m = re.search(r"记住映射[：:]\s*(.+?)。?\s*请问\s*(.+?)\s*对应哪个数字", text)
            if m:
                mapping_str = m.group(1)
                target = m.group(2)
                pairs = re.findall(r"([^\d\s，,]+)\s*=\s*(\d+)", mapping_str)
                for symbol, num in pairs:
                    if symbol == target:
                        # 检查是否有选项
                        opt_m = re.search(r"选项[：:]\s*(.+)", text)
                        if opt_m:
                            options = re.findall(r"(\d+)\.\s*(\d+)", opt_m.group(1))
                            for opt_num, opt_val in options:
                                if opt_val == num:
                                    ans = opt_num
                                    break
                        if not ans:
                            ans = num
                        ctx.log.info("[天空答题] 映射: %s=%s", target, ans)
                        break

        # 4. AI 兜底
        if not ans and ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
            try:
                ctx.log.info("[天空答题] 使用AI分析题目: %s", text[:60])
                ai_ans = await ctx.ai.chat(f"{_PROMPT_ANSWER}\n\n题目: {text}")
                ai_ans = ai_ans.strip()[:20]
                if ai_ans:
                    ans = ai_ans
                    ctx.log.info("[天空答题] AI回答: %s", ans)
            except Exception as e:
                ctx.log.warning("[天空答题] AI分析失败: %r", e)

        if not ans:
            ctx.log.info("[天空答题] 无法解答，跳过")
            return

        ctx.log.info("[天空答题] 最终答案: %s", ans)
        d_min = int(ctx.config.get("reward_delay_min", 2) or 2)
        d_max = int(ctx.config.get("reward_delay_max", 5) or 5)
        if d_min >= d_max:
            d_max = d_min + 1
        await asyncio.sleep(random.uniform(d_min, d_max))
        await client.send_message(message.chat.id, str(ans))
        ctx.log.info("[天空答题] 答题完成")

    ctx.log.info("天空答题已就绪")

    # ── 测试按钮 ──
    @ctx.action("test_say")
    async def _test_say(req=None):
        if not ctx.config.get("enable_reward_answer", False):
            return {"ok": False, "message": "请先开启答题奖励"}
        return {"ok": True, "message": "天空答题插件运行正常（数学题/找不同/映射记忆/AI兜底）"}


async def teardown(ctx):
    ctx.log.info("天空答题已卸载")