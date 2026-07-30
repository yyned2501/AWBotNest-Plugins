# -*- coding: utf-8 -*-
# 天空答题 · 常量与纯工具函数（无 ctx 依赖，供各模块复用）

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 东八区时区（天空小秘的掉落/统计时间均按北京时间）
TZ = timezone(timedelta(hours=8))

# 天空小秘 Bot ID（与 skyRedPacket 一致）
BOT_ID = 8907007783

# 天空小秘掉落答题的消息特征正则（答题/统计/info 排除三处共用）
_DROP_REGEX = r"小秘想给你 \d+ 银元奖励。"

# 模板 .py 文件目录（本模块与 templates/ 同在 skyDropAnswer/ 下）
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# 模板命中次数在 ctx.kv 里的键前缀
_KV_COUNT_PREFIX = "tpl_count:"

# AI 答题提示词
_PROMPT_ANSWER = "你是Telegram答题助手，分析题目并给出答案。只输出答案内容，不要任何解释。"

# 注意：{{ 和 }} 是 str.format() 的转义，代表一个字面 { 或 }
# {text} / {existing} 是真正的格式占位符
_PROMPT_LEARN = (
    "分析以下题目，生成一个可复用的 Python 答题模板。只输出JSON，不要其他文字。\n\n"
    "题目: {text}\n\n"
    "已有模板列表（若本题属于其中某一类，必须复用其 filename 和 type，切勿新建）:\n"
    "{existing}\n\n"
    "生成要求:\n"
    "1. regex 要宽松、只抓题型结构，不要硬编码题目里的具体数字或符号："
    "数字用 \\d+，空白用 \\s*，可变内容用 .*?。须兼容 re.DOTALL。\n"
    "2. filename 是稳定的英文标识，同一题型务必始终相同（如 math_arithmetic、find_odd_one）。\n"
    "3. extract(text) 只做纯文本提取并返回字符串答案；答案若是选项序号就返回序号字符串。\n"
    "4. 【最重要】题目中会变化的内容（要找的符号、具体数字、关键词等）必须当作变量动态解析，"
    "绝不把某一个具体值写死进 regex 或 extract——否则同一题型换个符号就会被误判成全新题型而重复生成模板。"
    "做法：regex 里用捕获组 (.+?) 或 \\d+ 占位，extract 里先解析出这个变量再用它求解。"
    "例：「找出“🔺”出现的位置，点击它的位置：🍉 🐶 🔺 ⭐ 🐱」这类题，"
    "应先用 找出\\s*(.+?)\\s*出现的位置 提取引号里的目标符号（此处是 🔺，但下一题会变成别的），"
    "再在符号序列里找该符号的 1-based 位置返回；切勿把 🔺 写死。\n\n"
    "输出JSON: {{\n"
    '  "filename": "稳定英文标识",\n'
    '  "type": "题型中文名",\n'
    '  "regex": "宽松正则表达式",\n'
    '  "sample": "题目示例(前50字)",\n'
    '  "has_options": true,\n'
    '  "script_code": "def extract(text):\\n    import re\\n    # 纯文本提取逻辑，无IO\\n    return str(<答案>)"\n'
    "}}"
)

# 内置默认触发消息池：普通日常短句，模拟真人水群（仅在未配置模板且需要兜底时用）
_DEFAULT_MESSAGES = [
    "顶一下",
    "666",
    "有人吗",
    "大家在干嘛",
    "无聊啊",
    "今天怎么样",
    "有好东西吗",
    "蹲一个",
    "前排",
    "路过",
]


# ────────────────────────── 触发侧工具函数 ──────────────────────────


def _reply_to_own_filter(_: object, __: object, m: object) -> bool:
    """判断消息是否是「回复我自己发的消息」。

    天空小秘掉题与 /info 回复都会 reply 到触发它的那条消息，
    reply_to_message.from_user.is_self 即「回复的是我」。答题与触发两侧共用。
    """
    return bool(
        getattr(m, "reply_to_message", None)
        and getattr(m.reply_to_message, "from_user", None)
        and getattr(m.reply_to_message.from_user, "is_self", False)
    )


def _parse_groups(raw: str) -> list[int]:
    """解析多行群组 ID 字符串为列表（忽略空行与非法行）。"""
    groups: list[int] = []
    for line in (raw or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            groups.append(int(line))
        except ValueError:
            continue
    return groups


def _pick_message(cfg: dict[str, Any]) -> str:
    """从配置的消息池随机取一条；池为空时用内置默认短句。"""
    raw = str(cfg.get("messages", "") or "").strip()
    pool = [ln.strip() for ln in raw.split("\n") if ln.strip()] if raw else []
    if not pool:
        pool = _DEFAULT_MESSAGES
    return random.choice(pool)


def _parse_bot_ids(raw: str) -> list[int | str]:
    """解析 bot 配置（@用户名 或 数字ID，逗号分隔）为 filters.user 可用的列表。

    纯数字转 int（pyrogram 按 ID 过滤更快），其余按用户名。留空回退默认天空小秘。
    """
    out: list[int | str] = []
    for part in (raw or "").replace("，", ",").split(","):
        part = part.strip().lstrip("@")
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            out.append(part)
    return out or [BOT_ID]


def _fmt_ts(ts: object) -> str:
    """时间戳 → MM-DD HH:MM（东八区）；无效值返回 —。"""
    try:
        val = float(ts or 0)
    except (TypeError, ValueError):
        return "—"
    if val <= 0:
        return "—"
    return datetime.fromtimestamp(val, TZ).strftime("%m-%d %H:%M")


# ────────────────────────── 模板归类工具函数 ──────────────────────────


def _norm_regex(rx: str) -> str:
    """归一化正则用于比较：去空白、统一全/半角常见等价写法。"""
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
