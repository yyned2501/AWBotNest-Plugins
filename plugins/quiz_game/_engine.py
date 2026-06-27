# =============================================================================
# quiz_game 私有辅助：出题源（AI / 天行数据）+ 题目解析
# =============================================================================

import random
from typing import Any, Optional

import httpx
import openai


def _normalize_line(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    while s and s[0] in "\"'`“”‘’《》（）()[]{}":
        s = s[1:].lstrip()
    while s and s[-1] in "\"'`“”‘’《》（）()[]{}":
        s = s[:-1].rstrip()
    return s.strip()


def parse_multi_qa(resp_text: str, expected: int) -> list[dict]:
    """解析「题目:/答案:」多题文本为 [{q,a,aliases}]。"""
    if not resp_text:
        return []
    lines = [_normalize_line(x) for x in str(resp_text).replace("\r\n", "\n").split("\n")]
    lines = [x for x in lines if x]
    result, q, a = [], "", ""
    for line in lines:
        l2 = line.replace("题目：", "题目:").replace("答案：", "答案:")
        if "题目:" in l2:
            if q and a:
                result.append({"q": q, "a": a, "aliases": []})
                if len(result) >= expected:
                    return result
            q, a = _normalize_line(l2.split("题目:", 1)[1]), ""
            continue
        if "答案:" in l2:
            a = _normalize_line(l2.split("答案:", 1)[1])
            if q and a:
                result.append({"q": q, "a": a, "aliases": []})
                if len(result) >= expected:
                    return result
                q, a = "", ""
    if q and a and len(result) < expected:
        result.append({"q": q, "a": a, "aliases": []})
    return result


async def fetch_from_ai(rounds: int, difficulty: str, api_key: str,
                        base_url: str, model: str, log) -> list[dict]:
    """用 OpenAI 兼容接口批量出题。"""
    if not api_key:
        log.warning("[答题] 未配置 AI API Key")
        return []
    prompt = (
        f"请出 {rounds} 道中文趣味答题，难度：{difficulty}。\n"
        "题型可选：Emoji猜成语、脑筋急转弯、谜语、字谜、歇后语、常识问答。\n"
        "每道题输出两行：第一行 题目: ...，第二行 答案: ...\n"
        "不同题目之间用空行分隔，不要编号，不要额外解释。"
    )
    try:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        resp = await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=0.9
        )
        text = resp.choices[0].message.content if resp.choices else ""
        return parse_multi_qa(text, rounds)
    except Exception as e:  # noqa: BLE001
        log.error("[答题] AI 出题失败: %r", e)
        return []


async def fetch_from_tianapi(tianapi_key: str, log) -> Optional[dict]:
    """从天行数据取一题。"""
    if not tianapi_key:
        log.warning("[答题] 未配置天行 API Key")
        return None
    endpoints = [
        ("成语", "https://apis.tianapi.com/ca542/index"),
        ("脑筋急转弯", "https://apis.tianapi.com/naowan/index"),
        ("谜语", "https://apis.tianapi.com/riddle/index"),
    ]
    name, ep = random.choice(endpoints)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(ep, params={"key": tianapi_key})
            resp.raise_for_status()
            data = resp.json()
            item = (data.get("result") or {})
            if isinstance(item, dict) and item.get("list"):
                item = item["list"][0]
            pic = item.get("picUrl") or item.get("img") or item.get("imgurl")
            title = (item.get("quest") or item.get("front") or item.get("title")
                     or item.get("content") or f"请猜一猜（{name}）")
            answer = item.get("result") or item.get("back") or item.get("answer")
            if not answer:
                return None
            q_text = f"【{name}】 {title}"
            if pic:
                q_text += f"\n\n[🖼️点击查看图片]({pic})"
            return {"q": q_text, "a": answer, "aliases": []}
    except Exception as e:  # noqa: BLE001
        log.warning("[答题] 天行接口失败: %r", e)
        return None
