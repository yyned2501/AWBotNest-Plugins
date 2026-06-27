# =============================================================================
# AWBotNest 插件：定时自动回复（custom_auto_reply）
#
# 由 AWLottery/schedulers/universal/custom_auto_reply.py 迁移而来。
# 按 cron 定时用用户账号向指定会话发送消息，支持：
#   - 多任务（JSON 数组配置），每任务独立 cron
#   - 可选活动日期范围（不在范围内则跳过）
#   - 多账号逐个发送
#   - 可选把发送结果通知到某个会话（Bot）
#
# 原项目用 TOML state_manager + SCHEDULER 开关管理多任务；平台改为
# 在 config_schema 多行文本里放 JSON 数组，setup 时为每个任务注册 ctx.schedule。
#
# 注意：定时任务在 setup 时按当前配置注册。改了任务配置后，需在平台
#       「重载」本插件（或关一次再开）让新配置重新注册生效。
# =============================================================================

import json
from datetime import datetime, timezone, timedelta

__plugin__ = {
    "name": "定时自动回复",
    "id": "custom_auto_reply",
    "version": "1.0.0",
    "author": "AW",
    "description": "按 cron 定时用用户账号向指定会话发消息。支持多任务、活动日期范围、多账号、结果通知。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "notify_chat_id": {
            "type": "string", "default": "", "label": "结果通知会话ID",
            "section": "参数",
            "help": "发送成功/失败后用 Bot 通知到此会话；留空则不通知。",
        },
        "tasks": {
            "type": "text", "default": "[]", "label": "定时任务(JSON)",
            "section": "任务",
            "help": (
                "JSON 数组，每个任务字段：\n"
                "id(任务标识)、name(任务名，可选)、\n"
                "target_chat_id(目标会话ID或@username)、message(消息内容)、\n"
                "hour(cron 小时，如 \"0,3,6,9,12,15,18,21\"，默认每小时)、\n"
                "minute(cron 分钟，默认 0)、\n"
                "start_date / end_date(可选，'YYYY-MM-DD HH:MM:SS'，东八区，限定活动期)。\n"
                '例：[{"id":"morning","target_chat_id":-1001234567890,'
                '"message":"早安","hour":"8","minute":"0"}]'
            ),
        },
    },
}

# 东八区
_TZ8 = timezone(timedelta(hours=8))


def _parse_tasks(raw) -> list[dict]:
    """解析任务 JSON，容错返回列表。"""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _normalize_chat_id(raw):
    """目标会话：@username 原样，数字转 int。"""
    s = str(raw).strip()
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return None


def _build_message_link(target_chat_id, msg_id) -> str:
    """根据目标类型构建消息链接（尽力而为）。"""
    if isinstance(target_chat_id, int) and target_chat_id < 0:
        gid = str(target_chat_id).replace("-100", "")
        return f"https://t.me/c/{gid}/{msg_id}"
    if isinstance(target_chat_id, str) and target_chat_id.startswith("@"):
        username = target_chat_id[1:]
        if username.lower().endswith("bot"):
            return f"目标: {target_chat_id}, 消息ID: {msg_id}"
        return f"https://t.me/{username}/{msg_id}"
    return f"消息ID: {msg_id}"


def _make_action(ctx, task: dict):
    """为单个任务生成 cron 回调函数。"""
    task_id = str(task.get("id") or "task")
    task_name = task.get("name") or task_id
    target_raw = task.get("target_chat_id")
    message_text = task.get("message", "")
    start_date_str = task.get("start_date")
    end_date_str = task.get("end_date")

    async def _action():
        # 日期范围检查
        now = datetime.now(_TZ8)
        if start_date_str and end_date_str:
            try:
                start = datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZ8)
                end = datetime.strptime(end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZ8)
                if not (start <= now <= end):
                    ctx.log.debug("[定时回复] 任务 %s 不在活动时间范围，跳过", task_id)
                    return
            except ValueError as e:
                ctx.log.error("[定时回复] 任务 %s 日期格式错误: %s", task_id, e)
                return

        target = _normalize_chat_id(target_raw)
        if target is None:
            ctx.log.error("[定时回复] 任务 %s 目标会话ID无效: %r", task_id, target_raw)
            return
        if not message_text:
            ctx.log.error("[定时回复] 任务 %s 未设置消息内容", task_id)
            return

        user_apps = ctx.user_apps
        if not user_apps:
            ctx.log.error("[定时回复] 任务 %s 无已连接用户账号，跳过", task_id)
            return

        notify_id = _normalize_chat_id(ctx.config.get("notify_chat_id", "")) if ctx.config.get("notify_chat_id") else None
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        for app in user_apps:
            me = getattr(app, "me", None)
            if me:
                acct = f"{me.first_name}(@{me.username})" if me.username else f"{me.first_name}(ID:{me.id})"
            else:
                acct = getattr(app, "name", "未知账号")
            try:
                sent = await app.send_message(target, message_text)
                ctx.log.info("[定时回复] 任务 %s [%s] 发送成功 msg=%s", task_id, acct, sent.id)
            except Exception as send_err:  # noqa: BLE001
                ctx.log.error("[定时回复] 任务 %s [%s] 发送失败: %r", task_id, acct, send_err)
                if notify_id:
                    try:
                        await ctx.bot.send(
                            notify_id,
                            f"❌ **定时回复失败**\n\n👤 账号：{acct}\n📋 任务：{task_name}\n"
                            f"🎯 目标：{target}\n⚠️ 错误：{send_err}",
                        )
                    except Exception:
                        pass
                continue

            if notify_id:
                link = _build_message_link(target, sent.id)
                preview = message_text[:100] + ("..." if len(message_text) > 100 else "")
                try:
                    await ctx.bot.send(
                        notify_id,
                        f"🎉 **定时回复已发送**\n\n👤 账号：{acct}\n📋 任务名称：{task_name}\n"
                        f"📅 发送时间：{now_str}\n🎯 目标聊天：{target}\n📝 消息内容：\n{preview}\n\n🔗 {link}",
                        disable_web_page_preview=True,
                    )
                except Exception as notify_err:  # noqa: BLE001
                    ctx.log.error("[定时回复] 任务 %s [%s] 通知失败: %r", task_id, acct, notify_err)

    return _action


async def setup(ctx):
    tasks = _parse_tasks(ctx.config.get("tasks", "[]"))
    if not tasks:
        ctx.log.info("[定时回复] 未配置任何任务")
        return

    registered = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("enabled", True) is False:
            continue
        task_id = str(task.get("id") or f"task{registered}")
        hour = str(task.get("hour", "*"))
        minute = str(task.get("minute", "0"))
        try:
            ctx.schedule(
                _make_action(ctx, task),
                "cron",
                hour=hour,
                minute=minute,
                id=task_id,
            )
            registered += 1
            ctx.log.info("[定时回复] 已注册任务 %s (hour=%s minute=%s)", task_id, hour, minute)
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[定时回复] 注册任务 %s 失败: %r", task_id, e)

    ctx.log.info("[定时回复] 共注册 %d 个定时任务", registered)


async def teardown(ctx):
    # ctx.schedule 注册的任务由平台在停用时自动移除，无需手动处理
    pass
