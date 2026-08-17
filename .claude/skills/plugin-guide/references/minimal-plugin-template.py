"""AWBotNest 最小插件模板。

复制到 plugins/<id>.py 后，替换元数据和业务逻辑。
"""

__plugin__ = {
    "name": "示例功能",
    "id": "my_feature",
    "version": "1.0.0",
    "scope": "user",  # user | bot | both | standalone
    "author": "",
    "description": "最小可用插件模板。",
    "changelog": "v1.0.0 初始版本\n- 提供基础命令回复",
    "default_enabled": False,
    # 下列运行治理字段按需启用；简单插件可不声明，平台会使用安全默认值。
    # "min_platform_version": "1.1.4.0",
    # "plugin_api_version": 1,
    # "instance_mode": "shared",  # shared | account
    # "resources": {
    #     "timeout_seconds": 120,
    #     "max_concurrency": 4,
    #     "max_background_tasks": 8,
    #     "failure_threshold": 5,
    #     "recovery_seconds": 60,
    # },
    "config_schema": {
        "keyword": {
            "type": "string",
            "default": ".ping",
            "label": "触发词",
            "section": "命令",
            "required": True,
            "cols": 6,
            "order": 1,
        },
        "reply_text": {
            "type": "string",
            "default": "pong",
            "label": "回复内容",
            "section": "命令",
            "required": True,
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
