# =============================================================================
# learning 插件：OpenAI 兼容接口封装
# 按 (api_key, base_url) 缓存客户端实例，复用连接池。
# =============================================================================

from typing import Optional

import openai

# 客户端缓存：(api_key, base_url) -> AsyncOpenAI
_client_cache: dict[tuple[str, str], openai.AsyncOpenAI] = {}


def classify_error(err: Exception) -> str:
    """把上游/SDK 异常转成可展示的中文提示（脱敏 + 截断）。"""
    msg = str(err) or err.__class__.__name__
    lower = msg.lower()
    # 脱敏：避免把 key/token 打到群里
    if "api_key" in lower or "authorization" in lower or "bearer" in lower:
        msg = "(错误信息已脱敏)"
    if len(msg) > 300:
        msg = msg[:300] + "..."
    if any(k in lower for k in ("model_not_found", "no available channel", "model not found")):
        return f"AI 模型不可用：{msg}"
    if any(k in lower for k in ("401", "403", "unauthorized", "forbidden")):
        return f"AI 鉴权失败（401/403）：{msg}"
    if any(k in lower for k in ("429", "rate limit", "too many requests")):
        return f"AI 请求过于频繁（429）：{msg}"
    if "503" in lower or "service unavailable" in lower:
        return f"AI 服务暂时不可用（503）：{msg}"
    return f"AI 调用失败：{msg}"


def _get_client(api_key: str, base_url: Optional[str]) -> openai.AsyncOpenAI:
    """获取或创建缓存的 AsyncOpenAI 客户端。"""
    key = (api_key, base_url or "")
    client = _client_cache.get(key)
    if client is None:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        _client_cache[key] = client
    return client


async def generate(
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
) -> str:
    """调 OpenAI 兼容接口生成回复。

    messages 为 [{"role","content"}, ...]。
    出错抛异常，由调用方分类处理。
    """
    client = _get_client(api_key, base_url)
    formatted = [{"role": m["role"], "content": m["content"]} for m in messages]

    resp = await client.chat.completions.create(
        model=model, messages=formatted, temperature=temperature
    )
    if resp.choices:
        return resp.choices[0].message.content or ""
    return ""


def clear_clients():
    """清理缓存的客户端（teardown 时调用）。"""
    _client_cache.clear()
