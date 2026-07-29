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
    "version": "1.10.3",
    "author": "Yy",
    "description": "天空答题奖励，每题型独立.py文件，模板管理+验证循环，Vue配置面板。",
    "changelog": "v1.10.3 更新内容：\n- 简化 _reply_to_own 使用 ctx.filters.outgoing 判断，去掉冗余 kv 缓存\nv1.10.2 更新内容：\n- 答题后通过 ctx.notify 推送通知到管理员",
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

_PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要任何解释。"

# 注意：{{ 和 }} 是 str.format() 的转义，代表一个字面 { 或 }
# {text} / {existing} 是真正的格式占位符
_PROMPT_LEARN = (
    '分析以下题目，生成一个可复用的 Python 答题模板。只输出JSON，不要其他文字。\n\n'
    '题目: {text}\n\n'
    '已有模板列表（若本题属于其中某一类，必须复用其 filename 和 type，切勿新建）:\n'
    '{existing}\n\n'
    '生成要求:\n'
    '1. regex 要宽松、只抓题型结构，不要硬编码题目里的具体数字或符号：'
    '数字用 \\d+，空白用 \\s*，可变内容用 .*?。须兼容 re.DOTALL。\n'
    '2. filename 是稳定的英文标识，同一题型务必始终相同（如 math_arithmetic、find_odd_one）。\n'
    '3. extract(text) 只做纯文本提取并返回字符串答案；答案若是选项序号就返回序号字符串。\n'
    '4. 【最重要】题目中会变化的内容（要找的符号、具体数字、关键词等）必须当作变量动态解析，'
    '绝不把某一个具体值写死进 regex 或 extract——否则同一题型换个符号就会被误判成全新题型而重复生成模板。'
    '做法：regex 里用捕获组 (.+?) 或 \\d+ 占位，extract 里先解析出这个变量再用它求解。'
    '例：「找出“🔺”出现的位置，点击它的位置：🍉 🐶 🔺 ⭐ 🐱」这类题，'
    '应先用 找出\\s*(.+?)\\s*出现的位置 提取引号里的目标符号（此处是 🔺，但下一题会变成别的），'
    '再在符号序列里找该符号的 1-based 位置返回；切勿把 🔺 写死。\n\n'
    '输出JSON: {{\n'
    '  "filename": "稳定英文标识",\n'
    '  "type": "题型中文名",\n'
    '  "regex": "宽松正则表达式",\n'
    '  "sample": "题目示例(前50字)",\n'
    '  "has_options": true,\n'
    '  "script_code": "def extract(text):\\n    import re\\n    # 纯文本提取逻辑，无IO\\n    return str(<答案>)"\n'
    '}}'
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

def _load_template_namespace(filepath: Path) -> dict:
    """加载单个 .py 模板文件到 namespace dict。

    模板以完整 builtins 执行（非沙箱）：学习出来的脚本需要 import re、
    collections 等标准库能力，这是本插件的设计前提。
    """
    ns = {"__builtins__": __builtins__}
    try:
        exec(filepath.read_text(encoding="utf-8"), ns)
    except Exception as e:
        return {}
    return ns


def _extract_script_code(filepath: Path) -> str:
    """从模板文件里取出 extract 函数源码（从 def extract 行到文件尾），供前端编辑。"""
    try:
        lines = filepath.read_text(encoding="utf-8").split("\n")
    except Exception:
        return ""
    for i, ln in enumerate(lines):
        if ln.startswith("def extract"):
            return "\n".join(lines[i:]).rstrip() + "\n"
    return ""


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
            "script_code": _extract_script_code(f),
            "extract": ns["extract"],
        })
    return out


def _build_template_content(tpl: dict) -> str:
    """按模板字典拼出 .py 文件全文（元数据 + extract 脚本）。

    字符串字段一律用 repr 写入，保证含换行/引号/emoji 的内容也能安全往返。
    """
    return (
        f"# {tpl['id']}.py — {tpl['type']}\n"
        f"TYPE = {tpl['type']!r}\n"
        f"REGEX = {tpl['regex']!r}\n"
        f"STATUS = {tpl['status']!r}\n"
        f"VERIFY_COUNT = {tpl['verify_count']}\n"
        f"SAMPLE = {tpl['sample']!r}\n"
        f"COUNT = {tpl['count']}\n"
        f"\n"
        f"{tpl['script_code']}\n"
    )


def _write_template_file(tpl: dict):
    """将模板写入 .py 文件"""
    _TEMPLATES_DIR.mkdir(exist_ok=True)
    filepath = _TEMPLATES_DIR / f"{tpl['id']}.py"
    filepath.write_text(_build_template_content(tpl), encoding="utf-8")


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


def _norm_regex(rx: str) -> str:
    """归一化正则用于比较：去空白、统一全/半角常见等价写法。"""
    import re
    rx = re.sub(r"\s+", "", rx or "")
    return rx.replace("（", "(").replace("）", ")").replace("：", ":").replace("，", ",")


def _identity(d: dict) -> tuple:
    """取模板/题目的归类标识：(filename小写, type, 归一化正则)。"""
    fn = (d.get("filename") or d.get("id") or "").strip().lower()
    ty = (d.get("type") or "").strip()
    return fn, ty, _norm_regex(d.get("regex", ""))


def _same_type(a: dict, b: dict) -> bool:
    """判断两个模板（或一个题目 data 与一个模板）是否同类。

    高置信信号：filename / type / 归一化正则相同；
    兜底信号：双方正则能互相匹配对方样例（双向，降低误判）。
    """
    import re
    fa, ta, ra = _identity(a)
    fb, tb, rb = _identity(b)
    if fa and fa == fb:
        return True
    if ta and ta == tb:
        return True
    if ra and ra == rb:
        return True
    sa, sb = (a.get("sample") or ""), (b.get("sample") or "")
    ra_raw, rb_raw = (a.get("regex") or ""), (b.get("regex") or "")
    try:
        ab = bool(ra_raw and sb and re.search(ra_raw, sb, re.DOTALL))
        ba = bool(rb_raw and sa and re.search(rb_raw, sa, re.DOTALL))
        if ab and ba:
            return True
    except re.error:
        pass
    return False


def _rank(t: dict) -> tuple:
    """模板优先级：verified > learning，再比验证次数、命中数。"""
    return (1 if t.get("status") == "verified" else 0, t.get("verify_count", 0), t.get("count", 0))


def _dedup_templates(templates: list[dict], ctx) -> list[dict]:
    """启动时合并同类模板：聚类后每组保留最优者（_rank 最高），命中数累加，
    其余模板删除文件。返回去重后的列表。"""
    groups: list[list[dict]] = []
    for t in templates:
        grp = next((g for g in groups if _same_type(g[0], t)), None)
        if grp is None:
            groups.append([t])
        else:
            grp.append(t)
    kept: list[dict] = []
    for grp in groups:
        if len(grp) == 1:
            kept.append(grp[0])
            continue
        survivor = max(grp, key=_rank)
        survivor["count"] = sum(x.get("count", 0) for x in grp)
        _update_template_file(survivor, count=survivor["count"])
        for x in grp:
            if x is not survivor:
                _delete_template_file(x["id"])
                ctx.log.info("[天空答题] 启动去重：模板 %s 归并到 %s", x["id"], survivor["id"])
        kept.append(survivor)
    return kept


async def _learn_template(text: str, ans: str, ctx, templates: list[dict]):
    """AI 分析题目 → 生成 .py 模板文件 → 加载到内存"""
    cfg = ctx.config
    if not cfg.get("enable_template_learning", True):
        return
    try:
        existing_lines = [f"- {t.get('id')}: {t.get('type', '')}" for t in templates]
        existing = "\n".join(existing_lines) if existing_lines else "（暂无）"
        prompt = _PROMPT_LEARN.format(text=text[:200], existing=existing)
        result = await ctx.ai.chat(prompt)
        result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(result)

        regex = data.get("regex", "").strip()
        if not regex:
            return

        # 去重：同类题归并到已有模板（filename/type/正则/样例判断），不新建
        hit = next((t for t in templates if _same_type(data, t)), None)
        if hit:
            hit["count"] = hit.get("count", 0) + 1
            hit["sample"] = data.get("sample", text[:50])
            _update_template_file(hit, count=hit["count"], sample=hit["sample"])
            ctx.log.info("[天空答题] 同类题归并到已有模板 %s（不新建）", hit["id"])
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


def _match_button(message, ans):
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
        (r, c, (getattr(btn, "text", "") or "").strip())
        for r, row in enumerate(keyboard)
        for c, btn in enumerate(row)
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

    # 提交答案：按按钮文本匹配答案（兼容「值为答案」与「序号为答案」两类题型）
    pos = _match_button(message, ans)
    if pos:
        row, col = pos
        try:
            await message.click(x=col, y=row)
            ctx.log.info("[天空答题] 点击按钮 (%d,%d)，答案 %s", row, col, ans)
        except Exception as e:
            ctx.log.warning("[天空答题] 点击按钮失败: %r", e)
    else:
        ctx.log.warning("[天空答题] 未找到匹配答案 %s 的按钮，跳过", ans)

    # 向出题机器人推送通知
    try:
        bot_user = message.from_user
        if bot_user:
            chat_title = getattr(message.chat, "title", "") if message.chat else ""
            await ctx.notify(
                f"🏠 所在群组\n   {chat_title}\n   群ID: {message.chat.id}\n\n"
                f"📩 答题结果\n   答案: {ans}\n\n"
                f"🔗 消息链接\n   {getattr(message, 'link', '')}",
                level="success",
                category="已答",
                account=client,
            )
            ctx.log.info("[天空答题] 已向机器人推送答题结果")
    except Exception as e:
        ctx.log.warning("[天空答题] 向机器人推送通知失败: %r", e)

    ctx.log.info("[天空答题] 答题完成")


async def setup(ctx):
    ctx.log.info("天空答题插件已加载 (v1.10.2)")

    # 从 templates/ 目录加载所有 .py 模板文件，并合并历史遗留的同类重复模板
    templates = _dedup_templates(_load_all_templates(), ctx)
    ctx.log.info("[天空答题] 加载 %d 个模板文件", len(templates))

    # 防抖：记录已处理的消息 ID（带时间戳，TTL 清理防无界增长）
    _processed_msg_ids: dict[int, float] = {}
    _DEDUP_TTL = 3600.0

    # ── 答题奖励 ──
    def _reply_to_own(_, __, message):
        if not message.reply_to_message_id:
            return False
        return ctx.filters.outgoing(_, message.reply_to_message)

    @ctx.on_message(ctx.filters.group & ctx.filters.text & ctx.filters.create(_reply_to_own) & ctx.filters.regex(r"小秘想给你 \d+ 银元奖励。"), group=5)
    async def _reward_handler(client, message):
        if not ctx.config.get("enable_reward_answer", False):
            return
        # 防抖：同一消息只处理一次（顺带清理过期记录，防集合无界增长）
        now = time.time()
        if len(_processed_msg_ids) > 500:
            stale = [k for k, ts in _processed_msg_ids.items() if now - ts > _DEDUP_TTL]
            for k in stale:
                _processed_msg_ids.pop(k, None)
        if message.id in _processed_msg_ids:
            ctx.log.info("[天空答题] 跳过重复消息: %s", message.id)
            return
        _processed_msg_ids[message.id] = now
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

    # ── API: 编辑模板（微调正则 / extract 脚本） ──
    @ctx.on_api("/api/templates/save", methods=["POST"])
    async def _save_template(req):
        import re as _re
        data = req.json or {}
        tid = data.get("id", "")
        tpl = next((t for t in templates if t["id"] == tid), None)
        if tpl is None:
            return {"ok": False, "message": "模板不存在"}
        new_regex = (data.get("regex") or "").strip()
        new_code = data.get("script_code") or ""
        if not new_regex:
            return {"ok": False, "message": "正则不能为空"}
        if "def extract" not in new_code:
            return {"ok": False, "message": "脚本必须定义 extract(text) 函数"}
        # 先校验后落盘：在内存执行确认脚本可用、正则合法，通过才写文件
        candidate = dict(tpl)
        candidate["regex"] = new_regex
        candidate["script_code"] = new_code.rstrip() + "\n"
        ns = {"__builtins__": __builtins__}
        try:
            exec(_build_template_content(candidate), ns)
        except Exception as e:
            return {"ok": False, "message": f"脚本/正则错误：{e}"}
        if "extract" not in ns:
            return {"ok": False, "message": "脚本执行后未生成 extract(text) 函数"}
        try:
            _re.compile(new_regex)
        except _re.error as e:
            return {"ok": False, "message": f"正则不合法：{e}"}
        # 校验通过：落盘 + 更新内存（立即对后续题目生效）
        tpl["regex"] = new_regex
        tpl["script_code"] = candidate["script_code"]
        tpl["extract"] = ns["extract"]
        _write_template_file(tpl)
        ctx.log.info("[天空答题] 模板已手动微调: %s", tid)
        return {"ok": True, "message": "已保存，后续题目立即生效"}

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