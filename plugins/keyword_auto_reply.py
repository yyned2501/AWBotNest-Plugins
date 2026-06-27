# =============================================================================
# AWBotNest 插件：关键词自动回复（keyword_auto_reply）
#
# 由 AWLottery/plugins/user/keyword_auto_reply_listener.py 迁移而来。
# 用户账号监听群组消息，命中关键词规则后自动回复，支持：
#   - 多规则（JSON 数组配置）
#   - 匹配方式 contains / exact / regex
#   - 按 账号+用户+规则 的冷却时间，可选零点重置
#   - 限定生效群组、回复后自动删除
#   - 回复模板：{uid}/{uname} 变量、a-b 随机数（+a-b 带符号）
#
# 原项目的"动态多规则"靠 TOML state_manager 存储；平台无此能力，
# 改为在 config_schema 的多行文本里放一个 JSON 数组，插件运行时解析。
# =============================================================================

import asyncio
import json
import random
import re
import time
from datetime import datetime, timedelta

__plugin__ = {
    "name": "关键词自动回复",
    "id": "keyword_auto_reply",
    "version": "1.0.0",
    "author": "AW",
    "description": "监听群消息，命中关键词自动回复。支持多规则、匹配方式、冷却、限群、自动删除、模板变量。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "enabled": {
            "type": "boolean", "default": True, "label": "启用关键词回复",
            "section": "功能开关",
        },
        "midnight_reset_cd": {
            "type": "boolean", "default": False, "label": "冷却零点重置",
            "section": "功能开关", "help": "开启后冷却在每天零点清零，而非按固定时长。",
        },
        "default_cooldown_hours": {
            "type": "number", "default": 24, "label": "默认冷却(小时)",
            "min": 0, "max": 720, "section": "参数",
            "help": "规则未单独指定 cooldown_hours 时使用。0 表示不冷却。",
        },
        "default_delete_after": {
            "type": "number", "default": 0, "label": "默认自动删除(秒)",
            "min": 0, "max": 3600, "section": "参数",
            "help": "回复消息多少秒后自动删除；0 表示不删。规则可用 delete_after 覆盖。",
        },
        "rules": {
            "type": "text", "default": "[]", "label": "规则列表(JSON)",
            "section": "规则",
            "help": (
                "JSON 数组，每条规则字段：\n"
                "id(规则名)、keyword(关键词/正则)、reply(回复文本)、\n"
                "match_type(contains|exact|regex，默认 contains)、\n"
                "chat_ids(限定群组ID，逗号分隔，留空=全部)、\n"
                "cooldown_hours(可选)、delete_after(可选)、cooldown_notify(true/false)。\n"
                "reply 支持 {uid} {uname} 变量与 a-b 随机数（+a-b 带符号）。\n"
                '例：[{"id":"hi","keyword":"你好","reply":"你好呀 {uname}~"}]'
            ),
        },
    },
}

# 用户冷却记录：{(account_id, user_id, rule_id): (最后触发时间戳, 触发日序号)}
_user_cooldowns: dict[tuple, tuple[float, int]] = {}
# 自动删除的后台任务，停用时统一取消
_pending_tasks: set = set()


def _parse_rules(raw) -> list[dict]:
    """解析 config 里的规则 JSON，容错：非法时返回空列表。"""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _match_keyword(text: str, keyword: str, match_type: str, log) -> bool:
    """根据匹配类型判断文本是否命中关键词。"""
    if match_type == "exact":
        return text.strip() == keyword
    if match_type == "regex":
        try:
            return bool(re.search(keyword, text))
        except re.error:
            log.warning("[关键词回复] 无效正则: %s", keyword)
            return False
    return keyword in text  # contains


def _check_chat_id(chat_id: int, chat_ids_str: str) -> bool:
    """判断当前会话是否在规则限定的群组范围内（留空=全部）。"""
    if not chat_ids_str:
        return True
    try:
        allowed = [int(c.strip()) for c in str(chat_ids_str).split(",") if c.strip()]
        return chat_id in allowed
    except ValueError:
        return True


def _render_reply_text(reply: str, message=None) -> str:
    """渲染回复模板：a-b 随机数、{uid}/{uname} 变量（uname 做 Markdown 转义）。"""
    pattern = re.compile(r"(?<!\d)(\+?)(\d+)-(\d+)(?!\d)")

    def _replace(match: re.Match) -> str:
        sign = match.group(1)
        start, end = int(match.group(2)), int(match.group(3))
        if start > end:
            start, end = end, start
        value = random.randint(start, end)
        return f"{sign}{value}" if sign else str(value)

    rendered = pattern.sub(_replace, reply)
    if message and message.from_user:
        uid = message.from_user.id
        uname = message.from_user.first_name or message.from_user.username or str(uid)
        for ch in ("\\", "_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
            uname = uname.replace(ch, f"\\{ch}")
        rendered = rendered.replace("{uid}", str(uid)).replace("{uname}", uname)
    return rendered


def _schedule_delete(message, delay: int):
    """delay 秒后删除一条消息（后台任务，登记以便停用时取消）。"""
    if delay <= 0:
        return

    async def _runner():
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception:
            pass

    task = asyncio.create_task(_runner())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def _fmt_remaining(seconds: float) -> str:
    """把剩余秒数格式化成 '约 X 小时 Y 分钟'。"""
    if seconds >= 3600:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h} 小时 {m} 分钟" if m else f"{h} 小时"
    if seconds >= 60:
        return f"{int(seconds // 60)} 分钟"
    return f"{int(seconds)} 秒"


async def setup(ctx):
    @ctx.on_message(
        ctx.filters.group & (ctx.filters.text | ctx.filters.caption),
        group=5,
    )
    async def keyword_auto_reply_listener(client, message):
        cfg = ctx.config
        if not cfg.get("enabled", True):
            return
        text = message.text or message.caption or ""
        if not text:
            return

        rules = _parse_rules(cfg.get("rules", "[]"))
        if not rules:
            return

        # 多账号：冷却按账号区分
        me = getattr(client, "me", None)
        account_id = me.id if me else id(client)
        chat_id = message.chat.id
        midnight_reset = bool(cfg.get("midnight_reset_cd", False))

        try:
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                keyword = rule.get("keyword", "")
                reply = rule.get("reply", "")
                if not keyword or not reply:
                    continue
                if rule.get("enabled", True) is False:
                    continue
                if not _check_chat_id(chat_id, rule.get("chat_ids", "")):
                    continue
                if not _match_keyword(text, keyword, rule.get("match_type", "contains"), ctx.log):
                    continue

                rule_id = str(rule.get("id") or keyword)
                user_id = message.from_user.id if message.from_user else None

                # 冷却判断
                if user_id is not None:
                    try:
                        cd_hours = rule.get("cooldown_hours", cfg.get("default_cooldown_hours", 24))
                        cooldown_secs = max(0.0, float(cd_hours)) * 3600
                    except (ValueError, TypeError):
                        cooldown_secs = 86400

                    if cooldown_secs > 0:
                        key = (account_id, user_id, rule_id)
                        record = _user_cooldowns.get(key)
                        today = datetime.now().date().toordinal()
                        if isinstance(record, tuple):
                            last_time, last_day = record
                        else:
                            last_time, last_day = float(record or 0.0), today

                        if midnight_reset and last_time > 0 and last_day != today:
                            last_time = 0.0

                        if time.time() - last_time < cooldown_secs:
                            # 冷却中，按需提示
                            if str(rule.get("cooldown_notify", "")).lower() in ("on", "true", "1") or rule.get("cooldown_notify") is True:
                                if midnight_reset:
                                    now_dt = datetime.now()
                                    next_midnight = datetime.combine(
                                        now_dt.date() + timedelta(days=1), datetime.min.time()
                                    )
                                    remaining = max(0.0, (next_midnight - now_dt).total_seconds())
                                    cd_text = f"⏳ 冷却中，距零点重置还剩 {_fmt_remaining(remaining)}"
                                else:
                                    remaining = cooldown_secs - (time.time() - last_time)
                                    cd_text = f"⏳ 冷却中，距下次还剩 {_fmt_remaining(remaining)}"
                                try:
                                    cd_msg = await client.send_message(
                                        chat_id, cd_text, reply_to_message_id=message.id
                                    )
                                    try:
                                        del_secs = int(rule.get("delete_after", cfg.get("default_delete_after", 0)))
                                    except (ValueError, TypeError):
                                        del_secs = 0
                                    _schedule_delete(cd_msg, del_secs)
                                except Exception:
                                    pass
                            continue
                        _user_cooldowns[key] = (time.time(), today)

                # 发送回复
                sent = await client.send_message(
                    chat_id,
                    _render_reply_text(reply, message),
                    reply_to_message_id=message.id,
                )
                try:
                    del_secs = int(rule.get("delete_after", cfg.get("default_delete_after", 0)))
                except (ValueError, TypeError):
                    del_secs = 0
                _schedule_delete(sent, del_secs)

                ctx.log.info("[关键词回复] 命中规则 '%s' | 群组 %s", rule_id, chat_id)
                break  # 每条消息只匹配第一个规则
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[关键词回复] 处理消息出错: %r", e)


async def teardown(ctx):
    # 取消所有待执行的自动删除任务
    for task in list(_pending_tasks):
        task.cancel()
    _pending_tasks.clear()
