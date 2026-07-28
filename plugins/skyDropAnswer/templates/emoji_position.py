# emoji_position.py — 图形位置查找，自动生成
TYPE = "图形位置查找"
REGEX = r"找出“🔺”出现的位置.*?[\U0001F300-\U0001F9FF\s]+"
STATUS = "learning"
VERIFY_COUNT = 0
SAMPLE = "小秘想给你 202 银元奖励。
找出“🔺”出现的位置，点击它的位置：
🍉 🐶 🔺 ⭐ 🐱"
COUNT = 1

def extract(text):
    import re
    lines = text.splitlines()
    for line in lines:
        if '🔺' in line:
            emojis = line.split()
            for i, emoji in enumerate(emojis):
                if '🔺' in emoji:
                    return str(i+1)
    return ""
