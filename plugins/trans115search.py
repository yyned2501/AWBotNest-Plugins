# =============================================================================
# AWBotNest 插件：115 列表转发（trans115search）
#
# 监听指定来源会话里某机器人发出的「列表」消息，转发到你指定的目标会话。
# 用你的用户账号监听，用机器人把内容转发到目标会话。
# =============================================================================

__plugin__ = {
    "name": "115列表转发",
    "id": "trans115search",
    "version": "1.0.0",
    "author": "AWdress",
    "description": "监听来源会话里机器人发的「列表」消息，自动转发到你指定的目标会话。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "source_chat_id": {
            "type": "string", "default": "-1002466900287", "label": "来源会话ID",
            "section": "参数", "help": "监听哪个会话里机器人发的列表消息。",
        },
        "target_chat_id": {
            "type": "string", "default": "", "label": "转发到会话ID",
            "section": "参数", "help": "把列表消息转发到这个会话（群/频道ID或@用户名）。留空则不转发。",
        },
        "keyword": {
            "type": "string", "default": "列表", "label": "触发关键词",
            "section": "参数", "help": "消息含此关键词才转发。",
        },
    },
}


def _normalize_chat_id(raw):
    s = str(raw or "").strip()
    if not s:
        return None
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return None


async def setup(ctx):
    @ctx.on_message(ctx.filters.text | ctx.filters.caption, group=7)
    async def forward_list(client, message):
        cfg = ctx.config
        source = _normalize_chat_id(cfg.get("source_chat_id"))
        target = _normalize_chat_id(cfg.get("target_chat_id"))
        keyword = cfg.get("keyword", "列表")
        if source is None or target is None:
            return
        if message.chat.id != source:
            return
        fu = message.from_user
        if not (fu and fu.is_bot):
            return
        text = message.caption or message.text or ""
        if keyword and keyword not in text:
            return

        try:
            await ctx.bot.send(
                target, text,
                entities=message.entities,
                disable_web_page_preview=True,
            )
        except Exception as e:  # noqa: BLE001
            ctx.log.warning("[115列表转发] 转发失败: %r", e)


async def teardown(ctx):
    pass
