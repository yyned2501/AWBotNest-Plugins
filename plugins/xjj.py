# =============================================================================
# AWBotNest 插件：小姐姐视频（xjj）
#
# 由 AWLottery/plugins/user/xjj.py 迁移而来。
# 监听自己发出的 /xjj 或 .xjj 命令，从视频 API 拉一条短视频发到当前会话。
# =============================================================================

import httpx

__plugin__ = {
    "name": "小姐姐视频",
    "id": "xjj",
    "version": "1.0.0",
    "author": "AW",
    "description": "发送 /xjj 或 .xjj 获取一条随机短视频。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "command": {
            "type": "string", "default": ".xjj", "label": "触发命令",
            "section": "参数", "help": "自己发出、以此开头的消息会触发。/xjj 与 .xjj 等价。",
        },
        "api_url": {
            "type": "string",
            "default": "http://47.115.231.249/API/sjsp/api.php?msg=热舞",
            "label": "视频接口地址", "section": "参数",
            "help": "返回 JSON 且含视频直链的接口。",
        },
        "video_key": {
            "type": "string", "default": "url", "label": "直链字段名",
            "section": "参数", "help": "接口返回 JSON 中视频直链所在的字段（支持顶层或 data 下）。",
        },
        "timeout": {
            "type": "slider", "default": 15, "label": "请求超时(秒)",
            "min": 5, "max": 60, "step": 5, "section": "参数",
        },
    },
}


async def _fetch_video_url(api_url: str, video_key: str, timeout: float):
    """请求接口取视频直链。返回 (url, error)。"""
    try:
        async with httpx.AsyncClient() as session:
            resp = await session.get(api_url, timeout=timeout)
            if resp.status_code != 200:
                return None, f"接口返回状态码 {resp.status_code}"
            data = resp.json()
            video_url = None
            if isinstance(data, dict):
                if video_key in data:
                    video_url = data[video_key]
                elif "data" in data and isinstance(data["data"], dict) and video_key in data["data"]:
                    video_url = data["data"][video_key]
            if not video_url:
                return None, "接口未返回视频直链"
            # 补全协议
            if video_url.startswith("//"):
                video_url = "https:" + video_url
            elif not video_url.startswith("http"):
                video_url = "https://" + video_url
            return video_url, None
    except Exception as e:  # noqa: BLE001
        return None, f"接口访问失败: {e.__class__.__name__}"


def _matches(text: str, command: str) -> bool:
    bare = command.lstrip("/.").strip() or "xjj"
    head = text.split(maxsplit=1)[0].lower() if text else ""
    return head in (f"/{bare}", f".{bare}")


async def setup(ctx):
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-18)
    async def xjj(client, message):
        cfg = ctx.config
        if not _matches((message.text or "").strip(), cfg.get("command", ".xjj")):
            return

        try:
            code_message = await message.edit("小姐姐视频生成中 .")
        except Exception:
            code_message = message

        url, error = await _fetch_video_url(
            cfg.get("api_url", ""),
            cfg.get("video_key", "url"),
            float(cfg.get("timeout", 15) or 15),
        )
        if not url:
            try:
                await message.edit(f"❌ {error}")
            except Exception:
                pass
            return

        try:
            await message.reply_video(
                url,
                quote=False,
                reply_to_message_id=message.reply_to_message_id,
                supports_streaming=True,
            )
            try:
                await code_message.delete()
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            ctx.log.warning("发送视频失败: %r", e)
            try:
                await message.edit(f"出错了呜 ~ {e.__class__.__name__}")
            except Exception:
                pass


async def teardown(ctx):
    pass
