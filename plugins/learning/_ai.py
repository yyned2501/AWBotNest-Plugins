# =============================================================================
# learning 插件：ctx.ai 封装
# 由 setup(ctx) 传入 ctx.ai 实例，后续模块通过 generate() 调用。
# =============================================================================

_ai = None


def init_ai(ai: object) -> None:
    """初始化 AI 实例（由 setup(ctx) 调用）。"""
    global _ai
    _ai = ai


async def generate(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
) -> str:
    """调平台 AI 生成回复，兼容旧的 messages 格式。

    messages 为 [{"role","content"}, ...]。
    出错抛异常，由调用方处理。
    """
    system = None
    prompt_parts = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            prompt_parts.append(m["content"])
    prompt = "\n".join(prompt_parts)

    kwargs: dict = {"temperature": temperature}
    if model:
        kwargs["model"] = model

    return await _ai.chat(prompt, system=system, **kwargs)
