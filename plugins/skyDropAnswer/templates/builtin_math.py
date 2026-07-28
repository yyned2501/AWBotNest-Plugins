# builtin_math.py — 数学题，自动生成
TYPE = "数学题"
REGEX = r"请回答[：:]\s*(\d+)\s*([+\-×xX*/])\s*(\d+)\s*=\s*多少\s*[?？]"
STATUS = "verified"
VERIFY_COUNT = 3
SAMPLE = "请回答：14 + 2 = 多少？"
COUNT = 0

def extract(text):
    import re
    m = re.search(REGEX, text)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op in ("+",): return str(a + b)
    elif op in ("-",): return str(a - b)
    elif op in ("\u00d7", "x", "X", "*"): return str(a * b)
    elif op in ("/",): return str(a // b) if b != 0 else "0"
    return None
