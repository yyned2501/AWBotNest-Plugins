# =============================================================================
# 学习插件：参与回复生成器（模拟用户风格）
# =============================================================================
import logging

from ._config import AiConfig
from ._engine import generate
from ._profiler import get_profile

logger = logging.getLogger(__name__)

_DEFAULT_VOICE = (
    "你是一个真实用户，在群里自然接话。"
    "语气口语化、接地气，每次回复短小精炼。"
    "绝对不要用客套话、不要解释、不要加引号、不要复述对方原话。"
    "绝对不要暴露你是 AI 或在模仿任何人。"
)


async def participate(
    client,
    chat_id: int,
    message_text: str,
    cfg: AiConfig,
    kv,
    context_lines: list[str] | None = None,
) -> str | None:
    """针对匹配到的群消息，模拟用户风格生成自然回复并直接发送。
    返回回复文本，失败返回 None。"""
    if not cfg.api_key:
        return None

    profile = get_profile(chat_id, kv)
    summary = profile.get("summary", "")

    # === 核心：从画像直接读风格描述 ===
    voice_data = profile.get("voice", {})
    if isinstance(voice_data, dict):
        voice_prompt = (voice_data.get("style_prompt") or "").strip()
    else:
        voice_prompt = ""
    if not voice_prompt:
        voice_prompt = _DEFAULT_VOICE

    system = (
        f"{voice_prompt}\n\n"
        f"【你就是一个有自己的人设和说话风格的真实用户，按照上面的风格自然回复。】"
    )

    # 构建上文
    ctx_block = ""
    if context_lines:
        ctx_lines = "\n".join(f"- {l}" for l in context_lines if l.strip())
        if ctx_lines:
            ctx_block = (
                f"\n\n群聊最近的上下文（你还没说话之前）：\n{ctx_lines}\n\n"
            )

    pref_hint = ""
    if summary:
        pref_hint = f"\n你感兴趣的话题：{summary}"

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"{ctx_block}"
                f"群里正在聊：{message_text}"
                f"{pref_hint}\n\n"
                f"你自然地加入对话，接一句相关的话。不要复述、不要解释、不发散。"
            ),
        },
    ]

    try:
        reply_text = await generate(
            cfg.api_key, cfg.base_url, cfg.model, messages,
        )
    except Exception:
        logger.error("参与回复生成失败 chat=%s", chat_id, exc_info=True)
        return None

    if not reply_text:
        return None

    try:
        await client.send_message(chat_id, reply_text)
        return reply_text
    except Exception:
        logger.error("参与回复发送失败 chat=%s reply=%r", chat_id, reply_text[:50], exc_info=True)
        return None
