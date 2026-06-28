# =============================================================================
# AWBotNest 插件：定时自动回复（custom_auto_reply）
#
# 用户账号按设定的时间，自动向指定会话发送一条消息。
# 配置全是普通表单项，照着填即可，无需懂 JSON / cron。
# =============================================================================

__plugin__ = {
    "name": "定时自动回复",
    "id": "custom_auto_reply",
    "version": "1.0.4",
    "author": "AWdress",
    "description": "到点自动用你的账号往指定群/会话发一条消息。可选每天定点、每隔几小时/几分钟，或直接填 cron 表达式。注册后会按规则反复发送。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        # —— 必填：发给谁、发什么 ——
        "target_chat_id": {
            "type": "string", "default": "", "label": "发送到哪个会话",
            "section": "发送内容",
            "help": "群组/频道ID（形如 -1001234567890）或 @用户名。不知道ID可先用「查ID」插件获取。",
        },
        "message": {
            "type": "text", "default": "", "label": "发送的消息",
            "section": "发送内容", "help": "要定时发出去的文字内容。",
        },

        # —— 发送频率 ——
        "frequency": {
            "type": "select", "default": "daily", "label": "发送频率",
            "section": "发送时间",
            "options": [
                {"value": "daily", "label": "每天定点（每天一次）"},
                {"value": "hours", "label": "每隔几小时循环发"},
                {"value": "minutes", "label": "每隔几分钟循环发"},
                {"value": "cron", "label": "自定义 cron 表达式（高级）"},
            ],
            "help": "无论选哪种，注册后都会按规则反复发送，不是只发一次。",
        },
        "daily_hour": {
            "type": "slider", "default": 9, "label": "每天几点", "min": 0, "max": 23, "step": 1,
            "section": "发送时间", "help": "24 小时制，0~23 点。", "show_if": {"frequency": "daily"},
        },
        "daily_minute": {
            "type": "slider", "default": 0, "label": "几分", "min": 0, "max": 59, "step": 1,
            "section": "发送时间", "show_if": {"frequency": "daily"},
        },
        "every_hours": {
            "type": "slider", "default": 3, "label": "每隔几小时", "min": 1, "max": 24, "step": 1,
            "section": "发送时间", "show_if": {"frequency": "hours"},
        },
        "every_minutes": {
            "type": "slider", "default": 30, "label": "每隔几分钟", "min": 1, "max": 180, "step": 1,
            "section": "发送时间", "show_if": {"frequency": "minutes"},
        },
        "cron_expr": {
            "type": "string", "default": "0 9 * * 1-5", "label": "cron 表达式",
            "section": "发送时间", "show_if": {"frequency": "cron"},
            "help": (
                "标准 5 段格式：分 时 日 月 周。星期 0/7=周日，1=周一。\n"
                "例：`0 9 * * 1-5` 工作日每天 9:00；`*/15 9-18 * * *` 9~18 点每 15 分钟一次；"
                "`30 8 1 * *` 每月 1 号 8:30。"
            ),
        },

        # —— 可选 ——
        "notify_owner": {
            "type": "boolean", "default": False, "label": "把结果通知给我",
            "section": "高级（可选）",
            "help": "每次发送成功/失败后，平台用机器人私聊你（或发到你账号的收藏夹）报一条。无需填ID。",
        },
    },
}


def _normalize_chat_id(raw):
    """目标会话：@用户名 原样返回，纯数字转 int，非法返回 None。"""
    s = str(raw or "").strip()
    if not s:
        return None
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return None


def _build_message_link(target_chat_id, msg_id) -> str:
    """尽力构建一条消息的可点击链接。"""
    if isinstance(target_chat_id, int) and target_chat_id < 0:
        gid = str(target_chat_id).replace("-100", "")
        return f"https://t.me/c/{gid}/{msg_id}"
    if isinstance(target_chat_id, str) and target_chat_id.startswith("@"):
        username = target_chat_id[1:]
        if username.lower().endswith("bot"):
            return f"目标: {target_chat_id}, 消息ID: {msg_id}"
        return f"https://t.me/{username}/{msg_id}"
    return f"消息ID: {msg_id}"


def _make_action(ctx):
    """生成定时回调：读取当前配置 → 用所有已连接用户账号发送。"""
    async def _action():
        cfg = ctx.config
        target = _normalize_chat_id(cfg.get("target_chat_id"))
        message_text = (cfg.get("message") or "").strip()
        if target is None:
            ctx.log.error("[定时回复] 目标会话未设置或格式错误")
            return
        if not message_text:
            ctx.log.error("[定时回复] 消息内容为空")
            return

        user_apps = ctx.user_apps
        if not user_apps:
            ctx.log.error("[定时回复] 没有已连接的用户账号，跳过")
            return

        notify_owner = bool(cfg.get("notify_owner", False))

        for app in user_apps:
            me = getattr(app, "me", None)
            if me:
                acct = f"{me.first_name}(@{me.username})" if me.username else f"{me.first_name}(ID:{me.id})"
            else:
                acct = getattr(app, "name", "未知账号")
            try:
                sent = await app.send_message(target, message_text)
                ctx.log.info("[定时回复] [%s] 发送成功 msg=%s", acct, sent.id)
            except Exception as send_err:  # noqa: BLE001
                ctx.log.error("[定时回复] [%s] 发送失败: %r", acct, send_err)
                if notify_owner:
                    # 级别/插件名/账号名由平台统一格式化，这里只给业务内容
                    try:
                        await ctx.notify(
                            f"定时回复失败\n🎯 目标：{target}\n⚠️ 错误：{send_err}",
                            level="error", category="定时回复", account=app,
                        )
                    except Exception:
                        pass
                continue

            if notify_owner:
                link = _build_message_link(target, sent.id)
                preview = message_text[:100] + ("..." if len(message_text) > 100 else "")
                try:
                    await ctx.notify(
                        f"定时回复已发送\n🎯 目标：{target}\n📝 内容：\n{preview}\n🔗 {link}",
                        level="success", category="定时回复", account=app,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass

    return _action


async def setup(ctx):
    cfg = ctx.config
    if not (cfg.get("message") or "").strip() or _normalize_chat_id(cfg.get("target_chat_id")) is None:
        ctx.log.info("[定时回复] 尚未填写目标会话或消息内容，未注册定时任务")
        return

    action = _make_action(ctx)
    freq = cfg.get("frequency", "daily")

    # 按频率注册定时任务（改配置后需在平台「重载」本插件以重新注册）
    if freq == "hours":
        hours = int(cfg.get("every_hours", 3) or 3)
        ctx.schedule(action, "interval", hours=hours, id="定时回复")
        ctx.log.info("[定时回复] 已注册：每 %d 小时一次", hours)
    elif freq == "minutes":
        minutes = int(cfg.get("every_minutes", 30) or 30)
        ctx.schedule(action, "interval", minutes=minutes, id="定时回复")
        ctx.log.info("[定时回复] 已注册：每 %d 分钟一次", minutes)
    elif freq == "cron":
        expr = (cfg.get("cron_expr") or "").strip()
        try:
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger.from_crontab(expr)
        except Exception as e:  # noqa: BLE001 - 表达式非法
            ctx.log.error("[定时回复] cron 表达式无效 %r：%r，未注册定时任务", expr, e)
            return
        ctx.schedule(action, trigger, id="定时回复")
        ctx.log.info("[定时回复] 已注册：cron(%s)", expr)
    else:  # daily
        hour = int(cfg.get("daily_hour", 9) or 0)
        minute = int(cfg.get("daily_minute", 0) or 0)
        ctx.schedule(action, "cron", hour=hour, minute=minute, id="定时回复")
        ctx.log.info("[定时回复] 已注册：每天 %02d:%02d", hour, minute)


async def teardown(ctx):
    # ctx.schedule 注册的任务由平台停用时自动移除
    pass
