# builtin_find_diff.py — 找不同，自动生成
TYPE = "找不同"
REGEX = r"找出唯一不同的图案，点击它的位置[：:]\s*\n(.+)"
STATUS = "verified"
VERIFY_COUNT = 3
SAMPLE = "找出唯一不同的图案，点击它的位置：\n\U0001f431 \U0001f431 \U0001f431 \U0001f42f \U0001f431 \U0001f431"
COUNT = 0

def extract(text):
    import re
    from collections import Counter
    m = re.search(REGEX, text)
    if not m:
        return None
    items = re.split(r"\s+", m.group(1).strip())
    if len(items) < 3:
        return None
    counts = Counter(items)
    for i, item in enumerate(items, 1):
        if counts[item] == 1:
            return str(i)
    return None
