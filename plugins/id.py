# =============================================================================
# AWBotNest 插件：查 ID（id）
#
# 由 AWLottery/plugins/user/Plugins_function_summary.py 的 get_id 迁移而来。
# 监听自己发出的 /id 或 .id 命令，查询被回复消息（或自身）的 群组ID / 用户ID。
# =============================================================================

import asyncio

__plugin__ = {
    "name": "查ID",
    "id": "id",
    "version": "1.0.0",
    "author": "AW",
    "description": "发送 /id 或 .id（可回复某条消息）查询群组ID、用户ID、用户名。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "command": {
            "type": "string", "default": ".id", "label": "触发命令",
            "section": "参数", "help": "自己发出、以此开头的消息会触发。/id 与 .id 等价均可识别。",
        },
        "auto_delete": {
            "type": "slider", "default": 20, "label": "结果自动删除(秒)",
            "min": 0, "max": 120, "step": 5, "section": "参数",
            "help": "查询结果多少秒后自动删除；0 表示不删除。",
        },
        "delete_command": {
            "type": "boolean", "default": True, "label": "删除命令消息",
            "section": "参数", "help": "查询后是否删除你发出的 /id 命令本身。",
        },
    },
}


def _format_id_info(chat_id, user_id=None, username=None, author_signature=None) -> str:
    """把 ID 信息格式化为带代码块（点击可复制）的文本。"""
    if user_id and username:
        return (
            "🔍 **用户信息查询**\n\n"
            f"👥 群组ID: `{chat_id}`\n"
            f"👤 用户ID: `{user_id}`\n"
            f"📝 用户名: {username}\n\n"
            "💡 点击ID数字即可复制"
        )
    elif author_signature:
        return (
            "🔍 **匿名消息信息**\n\n"
            f"👥 群组ID: `{chat_id}`\n"
            f"✍️ 作者签名: {author_signature}\n\n"
            "💡 点击ID数字即可复制"
        )
    else:
        return (
            "🔍 **群组信息**\n\n"
            f"👥 群组ID: `{chat_id}`\n\n"
            "💡 点击ID数字即可复制"
        )


def _norm(cmd: str) -> tuple[str, str]:
    """归一化触发命令，返回 (斜杠版, 点版)，两种都能触发。"""
    bare = cmd.lstrip("/.").strip() or "id"
    return f"/{bare}", f".{bare}"


async def setup(ctx):
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-17)
    async def get_id(client, message):
        cfg = ctx.config
        slash, dot = _norm(cfg.get("command", ".id"))
        text = (message.text or "").strip()
        # 仅当文本以命令开头（命令后是空白或结束）才触发
        head = text.split(maxsplit=1)[0].lower() if text else ""
        if head not in (slash, dot):
            return

        msg = message.reply_to_message or message
        chat_id = msg.chat.id

        if msg.from_user:
            re_mess = _format_id_info(
                chat_id=chat_id,
                user_id=msg.from_user.id,
                username=msg.from_user.first_name,
            )
        elif getattr(msg, "author_signature", None):
            re_mess = _format_id_info(chat_id=chat_id, author_signature=msg.author_signature)
        else:
            re_mess = _format_id_info(chat_id=chat_id)

        try:
            result = await message.reply(re_mess)
            # 结果自动删除
            delay = int(cfg.get("auto_delete", 20) or 0)
            if delay > 0:
                async def _auto_delete(m=result, d=delay):
                    await asyncio.sleep(d)
                    try:
                        await m.delete()
                    except Exception:
                        pass
                asyncio.create_task(_auto_delete())
            # 删除命令本身
            if cfg.get("delete_command", True):
                try:
                    await message.delete()
                except Exception:
                    pass
        except Exception as e:  # FloodWait 等：重试一次
            wait = getattr(e, "value", None)
            if isinstance(wait, (int, float)):
                await asyncio.sleep(wait)
                try:
                    await message.reply(re_mess)
                    if cfg.get("delete_command", True):
                        await message.delete()
                except Exception:
                    pass
            else:
                ctx.log.warning("查ID失败: %r", e)


async def teardown(ctx):
    pass
