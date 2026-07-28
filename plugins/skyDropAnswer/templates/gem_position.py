# gem_position.py — 找符号位置，自动生成
TYPE = "找符号位置"
REGEX = r"找出.*💎.*位置"
STATUS = "learning"
VERIFY_COUNT = 0
SAMPLE = "小秘想给你 302 银元奖励。
找出“💎”出现的位置，点击它的位置：
🐶 🍋 ⭐ 💎 🔺
请在 30 秒内点击正确选项，答对后才会发放奖励。"
COUNT = 1

def extract(text):
    import re
    # 提取所有非空白符号，找到💎的索引（从1开始）
    symbols = re.findall(r'[^\s]+', text)
    for i, s in enumerate(symbols):
        if '💎' in s:
            return str(i+1)
    return ''
