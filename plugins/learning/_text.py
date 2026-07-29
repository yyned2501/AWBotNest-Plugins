# =============================================================================
# learning 插件：共享文本处理工具（关键词提取 + 分隔符）
# 供 _judger.py 和 _profiler.py 共用，避免重复代码。
# =============================================================================

# 中文标点/分隔符集合
DELIMITERS = set(" \t\n\r,，。！？、；：\"\"''（）()[]【】/\\|@#$%^&*+=~`<>《》")

# 停用词表
_STOPWORDS = {
    "的",
    "了",
    "在",
    "是",
    "我",
    "有",
    "和",
    "就",
    "不",
    "人",
    "都",
    "一",
    "个",
    "上",
    "也",
    "很",
    "到",
    "说",
    "要",
    "去",
    "你",
    "会",
    "着",
    "没有",
    "看",
    "好",
    "自己",
    "这",
    "他",
    "她",
    "它",
    "们",
    "那",
    "什么",
    "怎么",
    "为啥",
    "吗",
    "呢",
    "啊",
    "吧",
    "嗯",
    "哦",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "it",
    "this",
    "that",
    "to",
    "in",
    "of",
    "for",
    "on",
    "and",
    "or",
    "with",
}


def extract_keywords(text: str) -> set[str]:
    """简单关键词提取：按分隔符切分，过滤停用词和短词。

    不做分词（不引入额外依赖），轻量但够用，
    更精确的匹配留到 LLM 判断环节。
    """
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch in DELIMITERS:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))

    result: set[str] = set()
    for t in tokens:
        t = t.strip().lower()
        if len(t) < 2 or t in _STOPWORDS or t.isdigit():
            continue
        result.add(t)
    return result
