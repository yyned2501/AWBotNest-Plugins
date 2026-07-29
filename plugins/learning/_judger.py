# =============================================================================
# 学习插件：参与判断器
# =============================================================================
import random

from ._config import AiConfig
from ._profiler import get_profile
from ._text import extract_keywords


def should_participate(
    chat_id: int,
    message_text: str,
    cfg: AiConfig,
    kv: object,
) -> tuple[bool, str | None]:
    """决定是否参与该消息的讨论。

    返回 True = 应该参与（由调用方生成回复内容）。
    判断顺序：
    1. 排除群组/白名单过滤
    2. 冷启动：没画像 → 不参与
    3. 关键词匹配：消息中的词 → 画像中的 keywords
    4. 抽签 roll
    """
    if not cfg.enable_participation:
        return False, None

    # 目标群组白名单（填了则只在这些群参与）
    if cfg.target_groups and chat_id not in cfg.target_groups:
        return False, None

    # 获取画像
    profile = get_profile(chat_id, kv)
    if not profile or not profile.get("ready"):
        # 冷启动：没有偏好 → 不参与
        return False, None

    keywords = profile.get("keywords", [])

    # 合并用户手动配置的关键词（config → keywords）
    if cfg.keywords:
        manual_kws = [kw.strip().lower() for kw in cfg.keywords.replace("\n", ",").split(",") if kw.strip()]
        keywords = list(set(keywords) | set(manual_kws))

    # 消息关键词
    msg_keywords = extract_keywords(message_text)

    # 匹配：消息中的关键词是否与画像 keywords 重叠
    matched_kw: str | None = None
    for kw in keywords:
        kw_lower = kw.lower()
        # 画像关键词可能是一个短语，检查消息是否包含该短语
        if kw_lower in message_text.lower():
            matched_kw = kw
            break
        # 也检查切分后的 tokens
        if any(kw_lower in mk or mk in kw_lower for mk in msg_keywords):
            matched_kw = kw
            break

    if not matched_kw:
        return False, None

    # roll 概率
    if random.randint(1, 100) > cfg.participation_rate:
        return False, None

    return True, matched_kw
