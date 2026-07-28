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
    "version": "1.5.0",
    "author": "Yy",
    "description": "天空答题奖励，统一模板+ AI学习+验证循环，Vue配置面板。",
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
            "section": "答题奖励", "help": "AI答完题后自动提取模板+脚本，下次同类题直接脚本答", "order": 6
        },
    },
}

_KV_PENDING = "auto_say_pending_rewards"
_KV_TEMPLATE_IDS = "sky_answer_template_ids"
_PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要任何解释。"

_PROMPT_LEARN = (
    '分析以下题目，回答问题并生成提取函数。只输出JSON，不要其他文字。\n\n'
    '题目: {text}\n\n'
    '输出JSON: {\n'
    '  "answer": "答案",\n'
    '  "regex": "能匹配此类题目的正则表达式（含 re.DOTALL）",\n'
    '  "type": "简短题型名（如"质数判断"）",\n'
    '  "sample": "题目示例(前50字)",\n'
    '  "has_options": true|false,\n'
    '  "script_code": "def extract(text):\\n    import re\\n    # 纯文本提取逻辑，无IO\\n    return str(<答案>)"\n'
    '}'
)

# ── 沙箱执行环境 ──
# 只有 re + 基本类型 + Counter，无 IO/网络/文件

_SAFE_GLOBALS = {
    "re": re,
    "Counter": Counter,
    "int": int, "float": float, "str": str, "bool": bool,
    "len": len, "range": range, "list": list, "dict": dict, "tuple": tuple,
    "set": set, "enumerate": enumerate, "zip": zip,
    "all": all, "any": any, "max": max, "min": min,
    "sum": sum, "abs": abs, "sorted": sorted, "reversed": reversed,
    "__builtins__": {},
}


def _run_script(code: str, text: str) -> str | None:
    """安全执行 AI 生成的提取脚本，返回答案"""
    if not code.strip():
        return None
    try:
        ns = _SAFE_GLOBALS.copy()
        ns["text"] = text
        exec(code, ns)
        fn = ns.get("extract")
        if not callable(fn):
            return None
        result = fn(text)
        return str(result).strip() if result is not None else None
    except Exception:
        return None


# ── 3 个内置 handler（预编译快路径） ──
# 同时 script_code 字段存在模板中，格式与学习模板一致

def _handle_math(text: str) -> str | None:
    m = re.search(r"请回答[：:]\s*(\d+)\s*([+\-×xX*/])\s*(\d+)\s*=\s*多少\s*[?？]", text)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op in ("+",): return str(a + b)
    elif op in ("-",): return str(a - b)
    elif op in ("×", "x", "X", "*"): return str(a * b)
    elif op in ("/",): return str(a // b) if b != 0 else "0"
    return None


def _handle_find_diff(text: str) -> str | None:
    m = re.search(r"找出唯一不同的图案，点击它的位置[：:]\s*\n(.+)", text)
    if not m:
        return None
    items = re.split(r"\s+", m.group(1).strip())
    if len(items) < 3:
        return None
    counts = Counter(items)
    for i, item in enumerate(items, 1):
        if counts[item] == 1:
            return str(i)
    return None


def _handle_mapping_memory(text: str) -> str | None:
    m = re.search(r"记住映射[：:]\s*(.+?)\s*请问\s*(.+?)\s*对应哪个数字", text, re.DOTALL)
    if not m:
        return None
    pairs = re.findall(r"([^\d\s，,、]+)\s*=\s*(\d+)", m.group(1))
    target = m.group(2).strip()
    for symbol, num in pairs:
        if symbol.strip() == target:
            opt_m = re.search(r"选项[：:]\s*(.+)", text, re.DOTALL)
            if opt_m:
                options = re.findall(r"(\d+)\.\s*(\d+)", opt_m.group(1))
                for opt_num, opt_val in options:
                    if opt_val == num:
                        return opt_num
            return num
    return None


_HANDLER_MAP = {
    "数学题": _handle_math,
    "找不同": _handle_find_diff,
    "映射记忆": _handle_mapping_memory,
}

# ── 内置模板 script_code（格式与学习模板完全一致） ──

_BUILTIN_SCRIPTS = {
    "数学题": '''def extract(text):
    import re
    m = re.search(r"请回答[：:]\\\\s*(\\\\d+)\\\\s*([+\\\\-×xX*/])\\\\s*(\\\\d+)\\\\s*=\\\\s*多少\\\\s*[?？]", text)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op in ("+",): return str(a + b)
    elif op in ("-",): return str(a - b)
    elif op in ("×", "x", "X", "*"): return str(a * b)
    elif op in ("/",): return str(a // b) if b != 0 else "0"
    return None''',
    "找不同": '''def extract(text):
    import re
    from collections import Counter
    m = re.search(r"找出唯一不同的图案，点击它的位置[：:]\\\\s*\\\\n(.+)", text)
    if not m:
        return None
    items = re.split(r"\\\\s+", m.group(1).strip())
    if len(items) < 3:
        return None
    counts = Counter(items)
    for i, item in enumerate(items, 1):
        if counts[item] == 1:
            return str(i)
    return None''',
    "映射记忆": '''def extract(text):
    import re
    m = re.search(r"记住映射[：:]\\\\s*(.+?)\\\\s*请问\\\\s*(.+?)\\\\s*对应哪个数字", text, re.DOTALL)
    if not m:
        return None
    pairs = re.findall(r"([^\\\\d\\\\s，,、]+)\\\\s*=\\\\s*(\\\\d+)", m.group(1))
    target = m.group(2).strip()
    for symbol, num in pairs:
        if symbol.strip() == target:
            opt_m = re.search(r"选项[：:]\\\\s*(.+)", text, re.DOTALL)
            if opt_m:
                options = re.findall(r"(\\\\d+)\\\\.\\\\s*(\\\\d+)", opt_m.group(1))
                for opt_num, opt_val in options:
                    if opt_val == num:
                        return opt_num
            return num
    return None''',
}


# ── 模板工具函数（独立 KV 存储） ──

def _load_templates(kv) -> list[dict]:
    ids = kv.get(_KV_TEMPLATE_IDS, [])
    out = []
    for tid in ids:
        tpl = kv.get(f"sky_answer_template:{tid}")
        if tpl:
            out.append(tpl)
    return out


def _save_templates(kv, templates: list[dict]):
    ids = []
    for t in templates:
        tid = t.get("id")
        if not tid:
            continue
        kv.set(f"sky_answer_template:{tid}", t)
        ids.append(tid)
    kv.set(_KV_TEMPLATE_IDS, ids)


def _get_template(kv, tpl_id: str) -> dict | None:
    return kv.get(f"sky_answer_template:{tpl_id}")


def _save_single_template(kv, tpl: dict):
    tid = tpl.get("id")
    if not tid:
        return
    kv.set(f"sky_answer_template:{tid}", tpl)


def _delete_template_kv(kv, tpl_id: str):
    kv.delete(f"sky_answer_template:{tpl_id}")
    ids = kv.get(_KV_TEMPLATE_IDS, [])
    if tpl_id in ids:
        ids.remove(tpl_id)
        kv.set(_KV_TEMPLATE_IDS, ids)


def _seed_builtin_templates(kv):
    """首次启动时 seed 3 条内置模板（status=verified，格式与学习模板一致）"""
    ids = kv.get(_KV_TEMPLATE_IDS, [])
    if ids:
        return
    now = time.time()
    builtins = [
        {
            "id": "builtin_math",
            "type": "数学题",
            "regex": r"请回答[：:]\s*(\d+)\s*([+\-×xX*/])\s*(\d+)\s*=\s*多少\s*[?？]",
            "script_code": _BUILTIN_SCRIPTS["数学题"],
            "status": "verified",
            "sample": "请回答：14 + 2 = 多少？",
            "verify_count": 3,
            "count": 0,
            "created_at": now,
        },
        {
            "id": "builtin_find_diff",
            "type": "找不同",
            "regex": r"找出唯一不同的图案，点击它的位置[：:]\s*\n(.+)",
            "script_code": _BUILTIN_SCRIPTS["找不同"],
            "status": "verified",
            "sample": "找出唯一不同的图案，点击它的位置：\n🐱 🐱 🐱 🐯 🐱 🐱",
            "verify_count": 3,
            "count": 0,
            "created_at": now,
        },
        {
            "id": "builtin_mapping_memory",
            "type": "映射记忆",
            "regex": r"记住映射[：:]\s*(.+?)\s*请问\s*(.+?)\s*对应哪个数字",
            "script_code": _BUILTIN_SCRIPTS["映射记忆"],
            "status": "verified",
            "sample": "记住映射：☀️=8、🍉=5、🍎=2 请问 🍉 对应哪个数字？",
            "verify_count": 3,
            "count": 0,
            "created_at": now,
        },
    ]
    _save_templates(kv, builtins)


def _match_templates(text: str, kv) -> tuple[str | None, str | None, str | None, str | None]:
    """遍历模板，返回 (answer, type, tpl_id, status)"""
    templates = _load_templates(kv)
    for t in templates:
        regex = t.get("regex", "")
        if not regex:
            continue
        try:
            if re.search(regex, text, re.DOTALL):
                return (
                    t.get("answer"),
                    t.get("type"),
                    t.get("id"),
                    t.get("status", "verified"),
                )
        except re.error:
            continue
    return (None, None, None, None)


def _increment_template_count(kv, tpl_id: str | None):
    if not tpl_id:
        return
    tpl = _get_template(kv, tpl_id)
    if tpl:
        tpl["count"] = tpl.get("count", 0) + 1
        _save_single_template(kv, tpl)


async def _learn_template(text: str, ans: str, ctx, kv):
    """AI 分析题目 → 生成答案+regex+script_code → 存入 KV（status=learning）"""
    cfg = ctx.config
    if not cfg.get("enable_template_learning", True):
        return
    try:
        prompt = _PROMPT_LEARN.format(text=text[:200])
        result = await ctx.ai.chat(prompt)
        result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(result)

        regex = data.get("regex", "").strip()
        if not regex:
            return

        templates = _load_templates(kv)
        # 去重
        for t in templates:
            if t.get("regex") == regex:
                t["count"] = t.get("count", 0) + 1
                t["answer"] = ans
                t["sample"] = data.get("sample", text[:50])
                _save_single_template(kv, t)
                ctx.log.info("[天空答题] 更新已有模板: %s", regex[:40])
                return

        tpl = {
            "id": str(int(time.time() * 1000)),
            "type": data.get("type", "未知题型"),
            "regex": regex,
            "script_code": data.get("script_code", ""),
            "answer": ans,
            "status": "learning",
            "sample": data.get("sample", text[:50]),
            "verify_count": 0,
            "count": 1,
            "created_at": time.time(),
        }
        templates.append(tpl)
        _save_templates(kv, templates)
        ctx.log.info("[天空答题] 学习新模板: %s | %s | status=learning | 共%d个",
                     tpl["type"], regex[:40], len(templates))
    except Exception as e:
        ctx.log.warning("[天空答题] 模板学习失败: %r", e)


async def _verify_template(ai_ans: str, script_ans: str | None, tpl: dict, kv) -> str | None:
    """验证循环：script vs AI → 一致则 verify_count++，3 次达标升 verified"""
    if script_ans and ai_ans and script_ans == ai_ans:
        tpl["verify_count"] = tpl.get("verify_count", 0) + 1
        if tpl["verify_count"] >= 3:
            tpl["status"] = "verified"
        _save_single_template(kv, tpl)
        return script_ans
    else:
        # 不一致重置
        if tpl.get("verify_count", 0) > 0:
            tpl["verify_count"] = 0
            _save_single_template(kv, tpl)
        return None


def _update_config(ctx, **updates):
    reg = ctx._registry
    current = reg.get_config(ctx.plugin_id)
    current.update(updates)
    reg.set_config(ctx.plugin_id, current)


async def _answer_and_submit(text, client, message, ctx, kv):
    """答题主逻辑：模板匹配 → 验证循环/AI兜底 → 提交答案"""
    ans = None
    tpl_ans, tpl_type, tpl_id, tpl_status = _match_templates(text, kv)

    if tpl_id:
        tpl = _get_template(kv, tpl_id)
        if tpl:
            status = tpl.get("status", "verified")

            # ── verified: 走快路径（_HANDLER_MAP）或脚本 ──
            if status == "verified":
                if tpl_type in _HANDLER_MAP:
                    ans = _HANDLER_MAP[tpl_type](text)
                else:
                    ans = _run_script(tpl.get("script_code", ""), text)
                if ans:
                    ctx.log.info("[天空答题] 模板命中(verified): %s → %s", tpl_type or tpl_id[:8], ans)
                    _increment_template_count(kv, tpl_id)

            # ── learning: 验证循环 ──
            elif status == "learning":
                script_ans = _run_script(tpl.get("script_code", ""), text)
                # 调 AI 获取标准答案
                if ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
                    try:
                        ai_text = f"{_PROMPT_ANSWER}\n\n题目: {text}"
                        ai_ans = (await ctx.ai.chat(ai_text)).strip()[:20]
                        if ai_ans:
                            result = await _verify_template(ai_ans, script_ans, tpl, kv)
                            if result:
                                ans = result
                                ctx.log.info("[天空答题] 验证通过(%d/3): %s", tpl["verify_count"], ans)
                            else:
                                ans = ai_ans
                                ctx.log.info("[天空答题] 验证不一致，使用AI答案: %s", ans)
                                ctx.log.info("  script=%s  ai=%s", script_ans, ai_ans)
                    except Exception as e:
                        ctx.log.warning("[天空答题] 验证AI调用失败: %r", e)
                        ans = script_ans
                else:
                    ans = script_ans

                if ans:
                    _increment_template_count(kv, tpl_id)

    # ── AI 兜底（无模板命中时） ──
    if not ans and ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
        try:
            ctx.log.info("[天空答题] 无模板命中，使用AI分析: %s", text[:60])
            ai_ans = await ctx.ai.chat(f"{_PROMPT_ANSWER}\n\n题目: {text}")
            ai_ans = (ai_ans.strip() or "")[:20]
            if ai_ans:
                ans = ai_ans
                ctx.log.info("[天空答题] AI回答: %s", ans)
                await _learn_template(text, ans, ctx, kv)
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
    ctx.log.info("天空答题插件已加载 (v1.5.0)")

    # 首次启动写入内置模板（status=verified，与学习模板格式一致）
    _seed_builtin_templates(ctx.kv)

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
        _delete_template_kv(kv, tid)
        ctx.log.info("[天空答题] 删除模板: %s", tid)
        return {"ok": True, "message": "已删除"}

    # ── API: 清空模板 ──
    @ctx.on_api("/api/templates/clear", methods=["POST"])
    async def _clear_templates(req):
        kv = ctx.kv
        ids = kv.get(_KV_TEMPLATE_IDS, [])
        for tid in ids:
            kv.delete(f"sky_answer_template:{tid}")
        kv.set(_KV_TEMPLATE_IDS, [])
        ctx.log.info("[天空答题] 清空所有模板")
        return {"ok": True, "message": "已清空"}

    ctx.log.info("天空答题已就绪")


async def teardown(ctx):
    ctx.log.info("天空答题已卸载")