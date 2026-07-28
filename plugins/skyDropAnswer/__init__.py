# -*- coding: utf-8 -*-
# AWBotNest 插件：天空答题 (skyDropAnswer)

import asyncio
import json
import random
import re
import time
from datetime import datetime, timezone, timedelta
from collections import Counter

TZ = timezone(timedelta(hours=8))

__plugin__ = {
    "name": "天空答题",
    "id": "skyDropAnswer",
    "version": "1.2.0",
    "author": "Yy",
    "description": "天空答题奖励，自动答题+AI学习模板，Vue配置面板。",
    "scope": "user",
    "render_mode": "vue",
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
        "enable_template_learning": {
            "type": "boolean", "default": True, "label": "AI学习模板",
            "section": "答题奖励", "help": "AI答完题后自动提取模板，下次同类题直接脚本答", "order": 6
        },
    },
}

_KV_PENDING = "auto_say_pending_rewards"
_KV_TEMPLATES = "sky_answer_templates"
_PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要加任何解释。"
_PROMPT_LEARN = (
    "分析以下题目，提取答题模板。只输出JSON，不要任何其他文字。\n\n"
    "题目: {text}\n"
    "正确答案: {ans}\n\n"
    '输出JSON: {{\n'
    '  "regex": "能匹配此类题目的Python正则表达式（含re.DOTALL标志）",\n'
    '  "type": "数学题|映射记忆|找不同|未知题型",\n'
    '  "sample": "题目示例(前50字)",\n'
    '  "answer": "答案",\n'
    '  "has_options": true|false\n'
    '}}'
)


def _parse_ids(raw) -> list[int]:
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


def _load_templates(kv) -> list[dict]:
    return kv.get(_KV_TEMPLATES, [])


def _save_templates(kv, templates: list[dict]):
    kv.set(_KV_TEMPLATES, templates)


def _match_templates(text: str, kv) -> str | None:
    """遍历模板，匹配则返回答案"""
    templates = _load_templates(kv)
    for t in templates:
        regex = t.get("regex", "")
        if not regex:
            continue
        try:
            if re.search(regex, text, re.DOTALL):
                return t.get("answer")
        except re.error:
            continue
    return None


async def _learn_template(text: str, ans: str, ctx, kv):
    """AI分析题目结构，提取模板存入KV"""
    cfg = ctx.config
    if not cfg.get("enable_template_learning", True):
        return
    try:
        prompt = _PROMPT_LEARN.format(text=text[:200], ans=ans)
        result = await ctx.ai.chat(prompt)
        result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        template = json.loads(result)
        template["regex"] = template.get("regex", "").strip()
        if not template.get("regex"):
            return

        templates = _load_templates(kv)
        # 去重：已存在相同regex则更新
        found = False
        for t in templates:
            if t.get("regex") == template["regex"]:
                t["count"] = t.get("count", 0) + 1
                t["answer"] = ans
                t["sample"] = template.get("sample", text[:50])
                found = True
                break
        if not found:
            template["id"] = str(int(time.time() * 1000))
            template["count"] = 1
            template["created_at"] = time.time()
            templates.append(template)

        _save_templates(kv, templates)
        ctx.log.info("[天空答题] 学习新模板: %s | %s | 共%d个模板",
                     template.get("type", "?"), template["regex"][:40], len(templates))
    except Exception as e:
        ctx.log.warning("[天空答题] 模板学习失败: %r", e)


def _update_config(ctx, **updates):
    """写入插件配置到持久存储"""
    reg = ctx._registry
    current = reg.get_config(ctx.plugin_id)
    current.update(updates)
    reg.set_config(ctx.plugin_id, current)


async def _answer_and_submit(text, client, message, ctx, kv):
    """答题主逻辑：模板→硬编码→AI兜底→学习→提交"""
    ans = None
    learned = False

    # 0. 模板匹配（优先于硬编码，但优先级低于AI准确率考量）
    #    放在硬编码之后、AI之前，因为模板可能不够精确

    # 1. 数学题: 14 + 2 = 多少？
    m = re.search(r"请回答[：:]\s*(\d+)\s*([+\-×xX*/])\s*(\d+)\s*=\s*多少\s*[?？]", text)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        if op in ("+",): ans = str(a + b)
        elif op in ("-",): ans = str(a - b)
        elif op in ("×", "x", "X", "*"): ans = str(a * b)
        elif op in ("/",): ans = str(a // b) if b != 0 else "0"
        ctx.log.info("[天空答题] 数学题: %d %s %d = %s", a, op, b, ans)

    # 2. 找不同
    if not ans:
        m = re.search(r"找出唯一不同的图案，点击它的位置[：:]\s*\n(.+)", text)
        if m:
            line = m.group(1).strip()
            items = re.split(r"\s+", line)
            if len(items) >= 3:
                counts = Counter(items)
                for i, item in enumerate(items, 1):
                    if counts[item] == 1:
                        ans = str(i)
                        ctx.log.info("[天空答题] 找不同: %s → 第%d个", item, i)
                        break

    # 3. 映射记忆
    if not ans:
        m = re.search(r"记住映射[：:]\s*(.+?)\s*请问\s*(.+?)\s*对应哪个数字", text, re.DOTALL)
        if m:
            mapping_str = m.group(1)
            target = m.group(2).strip()
            pairs = re.findall(r"([^\d\s，,、]+)\s*=\s*(\d+)", mapping_str)
            for symbol, num in pairs:
                if symbol.strip() == target:
                    opt_m = re.search(r"选项[：:]\s*(.+)", text, re.DOTALL)
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

    # 4. 模板匹配（硬编码没命中时才查模板）
    if not ans:
        ans = _match_templates(text, kv)
        if ans:
            ctx.log.info("[天空答题] 模板命中: %s", ans)

    # 5. AI 兜底 + 学习
    if not ans and ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
        try:
            ctx.log.info("[天空答题] 使用AI分析题目: %s", text[:60])
            ai_ans = await ctx.ai.chat(f"{_PROMPT_ANSWER}\n\n题目: {text}")
            ai_ans = (ai_ans.strip() or "")[:20]
            if ai_ans:
                ans = ai_ans
                ctx.log.info("[天空答题] AI回答: %s", ans)
                # 学习模板
                await _learn_template(text, ans, ctx, kv)
                learned = True
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

    # 提交答案
    clicked = False
    reply_markup = getattr(message, "reply_markup", None)
    keyboard = getattr(reply_markup, "inline_keyboard", None)
    if keyboard:
        total_buttons = sum(len(row) for row in keyboard)
        try:
            button_index = int(str(ans).strip()) - 1
        except ValueError:
            button_index = -1
        if 0 <= button_index < total_buttons:
            await message.click(button_index)
            clicked = True
            ctx.log.info("[天空答题] 点击按钮: 索引=%d（答案 %s）", button_index, ans)
        else:
            ctx.log.warning("[天空答题] 答案 %s 无法对应按钮（共%d个），改为发文字", ans, total_buttons)
    if not clicked:
        await client.send_message(message.chat.id, str(ans))
        ctx.log.info("[天空答题] 发送文字: %s", ans)
    ctx.log.info("[天空答题] 答题完成")


async def setup(ctx):
    ctx.log.info("天空答题插件已加载 (v1.2.0)")

    # ── 记录用户自己发的消息 ──
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=3)
    async def _user_msg_handler(client, message):
        if not ctx.config.get("enable_reward_answer", False):
            return
        pending = ctx.kv.get(_KV_PENDING, [])
        pending.append({"chat_id": message.chat.id, "msg_id": message.id, "time": time.time()})
        ctx.kv.set(_KV_PENDING, pending[-20:])

    # ── 答题奖励 ──
    def _reply_to_own(_, __, message):
        if not message.reply_to_message_id:
            return False
        pending = ctx.kv.get(_KV_PENDING, [])
        return any(
            p["chat_id"] == message.chat.id and p["msg_id"] == message.reply_to_message_id
            for p in pending
        )

    @ctx.on_message(ctx.filters.group & ctx.filters.text & ctx.filters.create(_reply_to_own) & ctx.filters.regex(r"小秘想给你 \d+ 银元奖励。"), group=5)
    async def _reward_handler(client, message):
        if not ctx.config.get("enable_reward_answer", False):
            return
        reward_bots = str(ctx.config.get("reward_bot_ids", "") or "").strip()
        if reward_bots:
            bot_ids = [b.strip().lstrip("@") for b in reward_bots.replace("，", ",").split(",") if b.strip()]
            sender_id = str(message.from_user.id) if message.from_user else ""
            sender_name = (message.from_user.username or "") if message.from_user else ""
            if bot_ids and sender_id not in bot_ids and sender_name not in bot_ids:
                return
        await _answer_and_submit((message.text or "").strip(), client, message, ctx, ctx.kv)

    # ── API: 获取模板列表 ──
    @ctx.on_api("/api/templates", methods=["GET"])
    async def _get_templates(req):
        kv = ctx.kv
        templates = _load_templates(kv)
        return {"ok": True, "data": templates}

    # ── API: 删除模板 ──
    @ctx.on_api("/api/templates", methods=["DELETE"])
    async def _delete_template(req):
        data = req.json or {}
        tid = data.get("id", "")
        if not tid:
            return {"ok": False, "message": "缺少 id"}
        kv = ctx.kv
        templates = _load_templates(kv)
        new_templates = [t for t in templates if t.get("id") != tid]
        if len(new_templates) == len(templates):
            return {"ok": False, "message": "未找到指定模板"}
        _save_templates(kv, new_templates)
        ctx.log.info("[天空答题] 删除模板: %s", tid)
        return {"ok": True, "message": "已删除"}

    # ── API: 清空模板 ──
    @ctx.on_api("/api/templates/clear", methods=["POST"])
    async def _clear_templates(req):
        kv = ctx.kv
        _save_templates(kv, [])
        ctx.log.info("[天空答题] 清空所有模板")
        return {"ok": True, "message": "已清空"}

    ctx.log.info("天空答题已就绪")


async def teardown(ctx):
    ctx.log.info("天空答题已卸载")