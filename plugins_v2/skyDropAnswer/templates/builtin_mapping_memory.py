# builtin_mapping_memory.py — 映射记忆，自动生成
TYPE = "映射记忆"
REGEX = r"记住映射[：:]\s*(.+?)\s*请问\s*(.+?)\s*对应哪个数字"
STATUS = "verified"
VERIFY_COUNT = 3
SAMPLE = "记住映射：\U0001f316=9、\U0001f31e=7、\U0001f319=4 请问 \U0001f31e 对应哪个数字？"
COUNT = 0

def extract(text):
    import re
    m = re.search(REGEX, text, re.DOTALL)
    if not m:
        return None
    pairs = re.findall(r"([^\d\s\u3002\uff0c,,\u3001]+)\s*=\s*(\d+)", m.group(1))
    target = m.group(2).strip()
    for symbol, num in pairs:
        if symbol.strip() == target:
            opt_m = re.search(r"选项[：:]\s*(.+)", text, re.DOTALL)
            if opt_m:
                options = re.findall(r"(\d+)\.\s*(\d+)", opt_m.group(1))
                for opt_num, opt_val in options:
                    if opt_val == num:
                        return opt_num
            return num
    return None
