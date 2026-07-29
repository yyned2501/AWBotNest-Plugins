# =============================================================================
# 学习插件（智能参与版）：配置封装
# =============================================================================
import time
from dataclasses import dataclass, field


@dataclass
class AiConfig:
    """AI 智能参与插件全部配置，字段与 __plugin__['config_schema'] 对应。"""

    # —— 学习 ——
    summarize_gap: int = 10
    max_context_lines: int = 5
    # —— 参与 ——
    enable_participation: bool = True
    participation_rate: int = 20
    target_groups: list[int] = field(default_factory=list)
    # —— 关键词（手动补充） ——
    keywords: str = ""
    max_keywords: int = 20
    participation_context_lines: int = 5
    min_participation_gap: int = 60
    participation_msg_gap: int = 5
    # —— 画像总结模板 ——
    profile_prompt_template: str = (
        "请根据以下聊天记录，分析我的说话风格和兴趣偏好。\n\n"
        "上下文（群聊最近的几条消息）：\n{context}\n\n"
        "我的发言：\n{my_messages}\n\n"
        "输出格式（JSON）：\n"
        "{{\n"
        '  "voice": {{\n'
        '    "tone": "语气特征（随意/正经/幽默/暴躁等）",\n'
        '    "avg_words": 平均每句话字数（数字）,\n'
        '    "habits": ["口癖1", "口癖2"],\n'
        '    "punctuation": "标点使用习惯",\n'
        '    "emoji_freq": "emoji 使用频率（很少/偶尔/经常/几乎每条）",\n'
        '    "style_prompt": "一段可读的中文文本，完整描述这个人的说话风格，供 LLM 模仿"\n'
        "  }},\n"
        '  "keywords": ["关键词1", "关键词2"],\n'
        '  "summary": "一句话总结当前兴趣"\n'
        "}}"
    )


def parse_ids(raw: str) -> list[int]:
    """多行/逗号混用解析群 ID 列表。一行一个，也兼容逗号分隔。"""
    out: list[int] = []
    for c in str(raw or "").replace("，", ",").replace("\n", ",").split(","):
        c = c.strip()
        if not c:
            continue
        try:
            out.append(int(c))
        except ValueError:
            pass
    return out


def to_int(v: object, default: int) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ── parse_config TTL 缓存 ─────────────────────────────────────────
# 消息回调每条都会解析配置，缓存 30 秒避免重复构造 dataclass。
_CONFIG_CACHE_TTL = 30.0  # 秒
_cache_raw: dict | None = None
_cache_value: AiConfig | None = None
_cache_ts: float = 0.0  # time.monotonic() 时间戳


def parse_config(raw: dict) -> AiConfig:
    """解析原始配置 dict 为 AiConfig（模块级 TTL 缓存，30 秒过期）。

    缓存命中条件：raw 内容未变 且 距上次解析不足 TTL。
    配置内容变化或缓存过期时重新解析。
    """
    global _cache_raw, _cache_value, _cache_ts
    now = time.monotonic()
    if _cache_value is not None and _cache_raw == raw and now - _cache_ts < _CONFIG_CACHE_TTL:
        return _cache_value

    cfg = AiConfig(
        summarize_gap=max(1, to_int(raw.get("summarize_gap", 10), 10)),
        max_context_lines=max(1, min(20, to_int(raw.get("max_context_lines", 5), 5))),
        enable_participation=bool(raw.get("enable_participation", True)),
        participation_rate=max(1, min(100, to_int(raw.get("participation_rate", 20), 20))),
        target_groups=parse_ids(raw.get("target_groups", "")),
        keywords=str(raw.get("keywords", "") or ""),
        max_keywords=max(1, to_int(raw.get("max_keywords", 20), 20)),
        participation_context_lines=max(1, min(20, to_int(raw.get("participation_context_lines", 5), 5))),
        min_participation_gap=max(1, to_int(raw.get("min_participation_gap", 60), 60)),
        participation_msg_gap=max(1, to_int(raw.get("participation_msg_gap", 5), 5)),
        profile_prompt_template=str(raw.get("profile_prompt_template", "") or AiConfig.profile_prompt_template),
    )

    _cache_raw = dict(raw)  # 存副本，防止外部就地修改导致缓存失真
    _cache_value = cfg
    _cache_ts = now
    return cfg
