# Minimal AWBotNest plugin template
# Copy to plugins/<id>.py and replace metadata values.

__plugin__ = {
    "name": "示例功能",
    "id": "my_feature",
    "version": "1.0.0",
    "scope": "user",
    "author": "",
    "description": "最小可用插件模板",
    "changelog": "v1.0.0 初始版本\n- 提供基础命令回复",
    "default_enabled": False,
    "config_schema": {
        "keyword": {
            "type": "string",
            "default": ".ping",
            "label": "触发词",
            "section": "命令",
            "cols": 6,
            "order": 1,
        },
        "reply_text": {
            "type": "string",
            "default": "pong",
            "label": "回复内容",
            "section": "命令",
            "cols": 6,
            "order": 2,
        },
    },
}

async def setup(ctx):
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text)
    async def on_text(client, message):
        text = message.text or ""
        keyword = ctx.config.get("keyword", ".ping")
        if not text.startswith(keyword):
            return
        await message.reply(ctx.config.get("reply_text", "pong"))

async def teardown(ctx):
    pass
