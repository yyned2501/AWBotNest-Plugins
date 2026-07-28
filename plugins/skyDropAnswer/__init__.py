# -*- coding: utf-8 -*-
# AWBotNest 插件：天空答题 (skyDropAnswer)

import asyncio
import json
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))

__plugin__ = {
    "name": "天空答题",
    "id": "skyDropAnswer",
    "version": "1.6.1",
    "author": "Yy",
    "description": "天空答题奖励，每题型独立.py文件，模板管理+验证循环，Vue配置面板。",
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
            "section": "答题奖励", "help": "AI答完题后自动生成模板.py文件，下次同类题直接脚本答", "order": 6
        },
    },
}

_KV_PENDING = "auto_say_pending_rewards"
_PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要任何解释。"

# 注意：{{ 和 }} 是 str.format() 的转义，代表一个字面 { 或 }
# {text} 是真正的格式占位符，会被替换为题目文本
_PROMPT_LEARN = (
    '分析以下题目，生成 Python 模板文件。只输出JSON，不要其他文字。\n\n'
    '题目: {text}\n\n'
    '输出JSON: {{\n'
    '  "filename": "简短英文文件名(如prime_number)",\n'
    '  "type": "题型名（如「质数判断」）",\n'
    '  "regex": "能匹配此类题目的正则表达式（含 re.DOTALL）",\n'
    '  "sample": "题目示例(前50字)",\n'
    '  "has_options": true|false,\n'
    '  "script_code": "def extract(text):\\n    import re\\n    # 纯文本提取逻辑，无IO\\n    return str(<答案>)"\n'
    '}}'
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── 沙箱执行环境 ──
_SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "all": all, "any": any, "max": max, "min": min,
    "sum": sum, "abs": abs, "sorted": sorted,
    "enumerate": enumerate, "zip": zip, "reversed": reversed,
    "int": int, "float": float, "str": str, "bool": bool,
    "len": len, "range": range, "list": list, "dict": dict,
    "tuple": tuple, "set": set, "open": None, "__import__": None,
}


def _load_template_namespace(filepath: Path) -> dict:
    """加载单个 .py 模板文件到 namespace dict"""
    ns = {"__builtins__": __builtins__}
    try:
        exec(filepath.read_text(encoding="utf-8"), ns)
    except Exception as e:
        return {}
    return ns


def _load_all_templates() -> list[dict]:
    """从 templates/ 目录加载所有 .py 模板"""
    _TEMPLATES_DIR.mkdir(exist_ok=True)
    out = []
    for f in sorted(_TEMPLATES_DIR.glob("*.py")):
        if f.name.startswith("__"):
            continue
        ns = _load_template_namespace(f)
        if "extract" not in ns or "REGEX" not in ns:
            continue
        out.append({
            "id": f.stem,
            "type": ns.get("TYPE", "未知"),
            "regex": ns["REGEX"],
            "status": ns.get("STATUS", "verified"),
            "verify_count": ns.get("VERIFY_COUNT", 0),
            "count": ns.get("COUNT", 0),
            "sample": ns.get("SAMPLE", ""),
            "extract": ns["extract"],
        })
    return out


def _write_template_file(tpl: dict):
    """将模板写入 .py 文件"""
    _TEMPLATES_DIR.mkdir(exist_ok=True)
    filepath = _TEMPLATES_DIR / f"{tpl['id']}.py"
    content = (
        f"# {tpl['id']}.py — {tpl['type']}，自动生成\n"
        f'TYPE = "{tpl["type"]}"\n'
        f'REGEX = r"{tpl["regex"]}"\n'
        f'STATUS = "{tpl["status"]}"\n'
        f'VERIFY_COUNT = {tpl["verify_count"]}\n'
        f'SAMPLE = "{tpl["sample"]}"\n'
        f'COUNT = {tpl["count"]}\n'
        f'\n'
        f'{tpl["script_code"]}\n'
    )
    filepath.write_text(content, encoding="utf-8")


def _delete_template_file(tpl_id: str):
    """删除模板文件"""
    filepath = _TEMPLATES_DIR / f"{tpl_id}.py"
    if filepath.exists():
        filepath.unlink()


def _match_templates(text: str, templates: list[dict]) -> tuple[str | None, dict | None]:
    """遍历模板列表，返回 (extract_fn, tpl_dict) 或 (None, None)"""
    import re
    for t in templates:
        regex = t.get("regex", "")
        if not regex:
            continue
        try:
            if re.search(regex, text, re.DOTALL):
                return (t["extract"], t)
        except re.error:
            continue
    return (None, None)


def _update_template_file(tpl: dict, **kwargs):
    """更新模板的元数据字段并重写文件"""
    for k, v in kwargs.items():
        if k in tpl:
            tpl[k] = v
    filepath = _TEMPLATES_DIR / f"{tpl['id']}.py"
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        changed = False
        for k, v in kwargs.items():
            if line.startswith(f"{k} =") or line.startswith(f"{k}="):
                new_lines.append(f'{k} = {v!r}' if isinstance(v, str) else f'{k} = {v}')
                changed = True
                break
        if not changed:
            new_lines.append(line)
    filepath.write_text("\n".join(new_lines), encoding="utf-8")


async def _learn_template(text: str, ans: str, ctx, templates: list[dict]):
    """AI 分析题目 → 生成 .py 模板文件 → 加载到内存"""
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

        # 去重
        for t in templates:
            if t.get("regex") == regex:
                t["count"] = t.get("count", 0) + 1
                t["sample"] = data.get("sample", text[:50])
                _update_template_file(t, count=t["count"], sample=t["sample"])
                ctx.log.info("[天空答题] 更新已有模板: %s", regex[:40])
                return

        # 新模板
        filename = data.get("filename", str(int(time.time() * 1000)))
        tpl = {
            "id": filename,
            "type": data.get("type", "未知题型"),
            "regex": regex,
            "script_code": data.get("script_code") or "def extract(text):\n    return " + repr(ans) + "\n",
            "status": "learning",
            "verify_count": 0,
            "count": 1,
            "sample": data.get("sample", text[:50]),
            "extract": None,  # 写入文件后重新加载
        }
        _write_template_file(tpl)
        # 重新加载 extract 函数
        ns = _load_template_namespace(_TEMPLATES_DIR / f"{filename}.py")
        tpl["extract"] = ns.get("extract", lambda t: None)
        templates.append(tpl)
        ctx.log.info("[天空答题] 学习新模板: %s | %s | status=learning | 共%d个",
                     tpl["type"], regex[:40], len(templates))
    except Exception as e:
        ctx.log.warning("[天空答题] 模板学习失败: %r", e)
        try:
            ctx.log.warning("[天空答题] AI原始响应(前200字): %s", result[:200])
        except Exception:
            pass


async def _verify_template(ai_ans: str, script_ans: str | None, tpl: dict, ctx) -> str | None:
    """验证循环：script vs AI → 一致则 verify_count++，3 次达标升 verified"""
    if script_ans and ai_ans and script_ans == ai_ans:
        tpl["verify_count"] = tpl.get("verify_count", 0) + 1
        if tpl["verify_count"] >= 3:
            tpl["status"] = "verified"
            ctx.log.info("[天空答题] 模板升级 verified: %s", tpl["id"])
        _update_template_file(tpl, verify_count=tpl["verify_count"], status=tpl["status"])
        return script_ans
    else:
        if tpl.get("verify_count", 0) > 0:
            tpl["verify_count"] = 0
            _update_template_file(tpl, verify_count=0)
        return None


def _update_config(ctx, **updates):
    reg = ctx._registry
    current = reg.get_config(ctx.plugin_id)
    current.update(updates)
    reg.set_config(ctx.plugin_id, current)


async def _answer_and_submit(text, client, message, ctx, templates):
    """答题主逻辑：模板匹配 → 验证循环/AI兜底 → 提交"""
    ans = None
    extract_fn, tpl = _match_templates(text, templates)

    if tpl:
        status = tpl.get("status", "verified")

        if status == "verified":
            ans = extract_fn(text) if extract_fn else None
            if ans:
                ctx.log.info("[天空答题] 模板命中(verified): %s → %s", tpl["type"], ans)
                tpl["count"] = tpl.get("count", 0) + 1
                _update_template_file(tpl, count=tpl["count"])

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
                            ctx.log.info("[天空答题] 验证通过(%d/3): %s", tpl["verify_count"], ans)
                        else:
                            ans = ai_ans
                            ctx.log.info("[天空答题] 验证不一致，使用AI答案: %s (script=%s)", ans, script_ans)
                except Exception as e:
                    ctx.log.warning("[天空答题] 验证AI调用失败: %r", e)
                    ans = script_ans
            else:
                ans = script_ans

            if ans:
                tpl["count"] = tpl.get("count", 0) + 1
                _update_template_file(tpl, count=tpl["count"])

    # AI 兜底（无模板命中时）
    if not ans and ctx.config.get("use_ai_fallback", True) and ctx.ai.available:
        try:
            ctx.log.info("[天空答题] 无模板命中，使用AI分析: %s", text[:60])
            ai_ans = await ctx.ai.chat(f"{_PROMPT_ANSWER}\n\n题目: {text}")
            ai_ans = (ai_ans.strip() or "")[:20]
            if ai_ans:
                ans = ai_ans
                ctx.log.info("[天空答题] AI回答: %s", ans)
                await _learn_template(text, ans, ctx, templates)
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
            ctx.log.warning("[天空答题] 答案 %s 无法对应按钮（共%d个），跳过", ans, total_buttons)
    if not clicked:
        ctx.log.info("[天空答题] 无按钮或无法点击，跳过")
    ctx.log.info("[天空答题] 答题完成")


async def setup(ctx):
    ctx.log.info("天空答题插件已加载 (v1.6.1)")

    # 从 templates/ 目录加载所有 .py 模板文件
    templates = _load_all_templates()
    ctx.log.info("[天空答题] 加载 %d 个模板文件", len(templates))

    # 防抖：记录已处理的消息 ID
    _processed_msg_ids = set()

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
        # 防抖：同一消息只处理一次
        if message.id in _processed_msg_ids:
            ctx.log.info("[天空答题] 跳过重复消息: %s", message.id)
            return
        _processed_msg_ids.add(message.id)
        reward_bots = str(ctx.config.get("reward_bot_ids", "") or "").strip()
        if reward_bots:
            bot_ids = [b.strip().lstrip("@") for b in reward_bots.replace("，", ",").split(",") if b.strip()]
            sender_id = str(message.from_user.id) if message.from_user else ""
            sender_name = (message.from_user.username or "") if message.from_user else ""
            if bot_ids and sender_id not in bot_ids and sender_name not in bot_ids:
                return
        await _answer_and_submit((message.text or "").strip(), client, message, ctx, templates)

    # ── API: 获取模板列表 ──
    @ctx.on_api("/api/templates", methods=["GET"])
    async def _get_templates(req):
        return {"ok": True, "data": [
            {k: v for k, v in t.items() if k != "extract"} for t in templates
        ]}

    # ── API: 删除模板 ──
    @ctx.on_api("/api/templates", methods=["DELETE"])
    async def _delete_template(req):
        data = req.json or {}
        tid = data.get("id", "")
        if not tid:
            return {"ok": False, "message": "缺少 id"}
        _delete_template_file(tid)
        # 从内存列表移除
        for i, t in enumerate(templates):
            if t["id"] == tid:
                templates.pop(i)
                break
        ctx.log.info("[天空答题] 删除模板: %s", tid)
        return {"ok": True, "message": "已删除"}

    # ── API: 清空模板（保留内置） ──
    @ctx.on_api("/api/templates/clear", methods=["POST"])
    async def _clear_templates(req):
        kept = [t for t in templates if t["id"].startswith("builtin_")]
        removed = [t for t in templates if not t["id"].startswith("builtin_")]
        for t in removed:
            _delete_template_file(t["id"])
        templates.clear()
        templates.extend(kept)
        ctx.log.info("[天空答题] 清空 %d 个学习模板", len(removed))
        return {"ok": True, "message": f"已清空，保留 {len(kept)} 个内置模板"}

    ctx.log.info("天空答题已就绪")


async def teardown(ctx):
    ctx.log.info("天空答题已卸载")