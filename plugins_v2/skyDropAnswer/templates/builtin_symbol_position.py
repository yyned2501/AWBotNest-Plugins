# builtin_symbol_position.py — 找出指定符号位置，手写内置
# 题型：找出“X”出现的位置，点击它的位置：🍉 🐶 🔺 ⭐ 🐱
# 目标符号 X 每题都变，extract 动态提取后在符号序列里定位（1-based）。
TYPE = "找出指定符号位置"
REGEX = r"找出.+?出现的位置"
STATUS = "verified"
VERIFY_COUNT = 3
SAMPLE = "找出“🔺”出现的位置，点击它的位置：\n🍉 🐶 🔺 ⭐ 🐱"
COUNT = 0

def extract(text):
    import re
    # 1) 提取要找的目标符号：找出“X”出现的位置（去掉两侧引号）
    m = re.search(r"找出\s*(.+?)\s*出现的位置", text)
    if not m:
        return ""
    target = m.group(1).strip().strip('“”"\'「」')
    if not target:
        return ""
    # 2) 取符号序列所在行：优先“点击它的位置”冒号后同行，否则取下一非空行
    lines = [ln.strip() for ln in text.splitlines()]
    row = ""
    for i, ln in enumerate(lines):
        if "点击它的位置" in ln or "出现的位置" in ln:
            tail = ln.split("：")[-1].split(":")[-1].strip()
            if tail:
                row = tail
            else:
                for j in range(i + 1, len(lines)):
                    if lines[j]:
                        row = lines[j]
                        break
            break
    if not row:
        return ""
    # 3) 目标符号在序列中的 1-based 位置
    for idx, tok in enumerate(row.split(), 1):
        if target in tok:
            return str(idx)
    return ""
