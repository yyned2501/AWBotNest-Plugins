# =============================================================================
# 学习插件：提问画像 + 说话风格学习
# =============================================================================
import json
import re
import time
from collections import deque

from ._ai import generate
from ._text import extract_keywords

# 自己消息缓冲：chat_id -> deque[str]
_msg_buf: dict[int, deque] = {}
_BUF_MAX = 100

# 全消息缓冲（仅人类文本，由 Handler 2 写入）
_all_buf: dict[int, deque] = {}
_ALL_MAX = 200

# 未总结计数器
_buf_counter: dict[int, int] = {}

# （全消息缓冲供 summarize 取上下文）

# kv key 模板
_PROFILE_KEY = "profile:{}"
_COUNTER_KEY = "bufcnt:{}"
# 说话风格直接存在 profile['voice']['style_prompt'] 中，无需独立 KV key

_JSON_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = _JSON_PATTERN.search(text)
    if m:
        text = m.group(1).strip()
    for candidate in (text, text.removeprefix("`").removesuffix("`")):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


# ── 画像访问 ─────────────────────────────────────────────────────


def get_profile(chat_id: int, kv: object) -> dict:
    return kv.get(_PROFILE_KEY.format(chat_id), {})


# （说话风格直接读 profile['voice']['style_prompt']，无需独立访问函数）


# ── 缓冲操作 ────────────────────────────────────────────────────────


def push_own_message(chat_id: int, text: str, kv: object) -> None:
    buf = _msg_buf.setdefault(chat_id, deque(maxlen=_BUF_MAX))
    buf.append(text)
    cnt = _buf_counter.get(chat_id, 0) + 1
    _buf_counter[chat_id] = cnt
    kv.set(_COUNTER_KEY.format(chat_id), cnt)


def push_all_message(chat_id: int, text: str, user_id: int, name: str, is_bot: bool = False) -> None:
    """推入全量缓冲（仅由 Handler 2 调用，只存人类文本）。"""
    buf = _all_buf.setdefault(chat_id, deque(maxlen=_ALL_MAX))
    buf.append({"text": text, "user_id": user_id, "name": name, "is_bot": is_bot, "ts": time.time()})


def _build_context_str(chat_id: int, n: int) -> str:
    """构建群聊上下文文本（供 LLM summarize 使用），仅含人类消息。"""
    buf = _all_buf.get(chat_id)
    if not buf:
        return ""
    human_msgs = [m for m in buf if not m.get("is_bot")]
    recent = human_msgs[-n:]
    lines = []
    for m in recent:
        sender = m.get("name", f"user_{m['user_id']}")
        lines.append(f"| {sender}: {m['text']}")
    return "\n".join(lines)


def get_message_count(kv: object, chat_id: int) -> int:
    return _buf_counter.get(chat_id, 0)


def reset_counter(chat_id: int, kv: object) -> None:
    _buf_counter[chat_id] = 0
    kv.set(_COUNTER_KEY.format(chat_id), 0)


def get_recent_own_messages(chat_id: int, n: int) -> list[str]:
    buf = _msg_buf.get(chat_id)
    if not buf:
        return []
    return list(buf)[-n:]


def get_recent_context(chat_id: int, n: int) -> list[str]:
    """返回最近 n 条人类文本消息（纯文本，无前缀，不排除最后一条）。

    供 Handler 1 热词匹配使用。Handler 1 不向 _all_buf 写入自己的消息，
    所以直接取最后 n 条就是别人在聊的内容。
    """
    buf = _all_buf.get(chat_id)
    if not buf:
        return []
    human_msgs = [m for m in buf if not m.get("is_bot")]
    return [m["text"] for m in human_msgs[-n:] if m.get("text")]


def get_context_lines(chat_id: int, n: int) -> list[str]:
    """获取触发消息之前的 N 条群聊上下文文本（排除当前消息，仅人类）。

    Handler 2 (group=11) 已把当前消息 push 进 _all_buf，
    所以取倒数 n+1 条 ~ 倒数第 2 条 = 最近 N 条上文。
    不足 N 条时返回全部（不含当前消息）。
    供 Handler 3 参与回复使用。
    """
    buf = _all_buf.get(chat_id)
    if not buf:
        return []
    human_msgs = [m for m in buf if not m.get("is_bot")]
    if len(human_msgs) < 2:
        return []
    recent = human_msgs[-(n + 1) : -1]
    return [m.get("text", "") for m in recent if m.get("text")]


def _safe_str(v: object) -> str:
    """将任意类型的值安全转为去除首尾空白的字符串。"""
    return str(v or "").strip()


# ── LLM 总结（关键词 + 风格一起出）────────────────────────────────────


async def summarize(chat_id: int, kv: object, cfg: object, own_messages: list[str]) -> dict | None:
    """对该群做一次 LLM 总结 + 说话风格分析，**合并**保有画像。

    合并策略：
      - keywords → 新旧取并集（去重）
      - voice.habits → 新旧取并集（去重）
      - voice.tone / avg_words / punctuation / emoji_freq → 用最新值
      - voice.style_prompt → LLM 在 prompt 中合并新旧风格，直接取最新结果
      - keyword_heat → 从旧画像继承（不继承会导致热度每次总结清零）
      失败则保留旧数据不变。
    """
    if not own_messages:
        return None

    context_str = _build_context_str(chat_id, cfg.max_context_lines)
    own_str = "\n".join(f"| 我: {m}" for m in own_messages)

    # 加载旧画像（用于在 prompt 中给出旧风格信息，让 LLM 合并）
    old_profile = get_profile(chat_id, kv)
    old_voice = old_profile.get("voice", {}) if isinstance(old_profile.get("voice"), dict) else {}
    old_style = (old_voice.get("style_prompt") or "").strip()

    prompt = cfg.profile_prompt_template.format(
        context=context_str,
        my_messages=own_str,
    )

    if old_style:
        prompt += (
            f"\n\n【之前的风格描述】\n{old_style}\n\n"
            f"【合并要求】把之前的风格描述和上面最新消息结合起来，"
            f"在 style_prompt 字段输出一段 **合并后的完整描述**（≤150字），"
            f"不要分点、不要标注『之前』『补充』——必须合并成一段连贯的话。\n"
            f"如果新的消息没有额外信息，保持原来的描述不变。"
        )

    messages = [
        {"role": "system", "content": "你是一个用户行为分析助手。只输出 JSON，不要多余文字。"},
        {"role": "user", "content": prompt},
    ]

    try:
        raw = await generate(messages)
    except Exception:
        return None

    if not raw:
        return None

    parsed = _extract_json(raw)
    if not parsed:
        return old_profile if old_profile.get("ready") else {"keywords": [], "summary": "", "ready": False}
    else:
        # —— 关键词：并集 ——

        new_kws = {str(kw).strip().lower() for kw in parsed.get("keywords", []) if kw}
        old_kws = {str(kw).strip().lower() for kw in old_profile.get("keywords", []) if kw}
        merged_kws = list(old_kws | new_kws)

        profile = {
            "keywords": merged_kws,
            "summary": str(parsed.get("summary", "") or ""),
            "ready": True,
            "updated_ts": time.time(),
            # 继承旧画像的关键词热度；不继承会导致每次总结后热度清零
            "keyword_heat": old_profile.get("keyword_heat", {}),
        }

        # —— voice 数据：合并各子维度 ——
        voice_data = parsed.get("voice")
        if isinstance(voice_data, dict):
            # 口癖并集
            new_habits = {str(h).strip() for h in voice_data.get("habits", []) if h}
            old_habits = {str(h).strip() for h in old_voice.get("habits", []) if h}
            merged_habits = list(old_habits | new_habits)

            # 标量字段：新值优先，新值空时保留旧值
            merged_voice = {
                "tone": _safe_str(voice_data.get("tone")) or _safe_str(old_voice.get("tone")),
                "avg_words": _safe_str(voice_data.get("avg_words")) or _safe_str(old_voice.get("avg_words")),
                "habits": merged_habits,
                "punctuation": _safe_str(voice_data.get("punctuation")) or _safe_str(old_voice.get("punctuation")),
                "emoji_freq": _safe_str(voice_data.get("emoji_freq")) or _safe_str(old_voice.get("emoji_freq")),
            }

            # style_prompt：LLM 已在 prompt 中合并旧风格，直接用新结果
            new_style = (voice_data.get("style_prompt") or "").strip()
            if new_style:
                merged_voice["style_prompt"] = new_style
            elif old_style:
                merged_voice["style_prompt"] = old_style

            profile["voice"] = merged_voice

        # —— 关键词热度：新词初始化 + 淘汰 ——
        kw_heat = profile.get("keyword_heat", {})
        now = time.time()
        for kw in merged_kws:
            if kw not in kw_heat:
                kw_heat[kw] = {"count": 0, "last_use": 0, "created_ts": now}
        profile["keyword_heat"] = kw_heat

        max_kw = getattr(cfg, "max_keywords", 20)
        if len(merged_kws) > max_kw:
            _prune_inplace(profile, max_kw)

    kv.set(_PROFILE_KEY.format(chat_id), profile)
    return profile


def clear() -> None:
    _msg_buf.clear()
    _all_buf.clear()
    _buf_counter.clear()


def _prune_inplace(profile: dict, max_keywords: int) -> None:
    """对内存中的 profile dict 执行关键词裁剪（不读写 KV）。

    评分公式：count × 10 + 最近使用奖赏(0~5)
    - 从未触发参与且创建>7天的词直接淘汰
    - 按分数降序保留前 max_keywords 个
    """
    keywords = profile.get("keywords", [])
    if not keywords or len(keywords) <= max_keywords:
        return
    heat = profile.get("keyword_heat", {})
    now = time.time()
    seven_days = 7 * 86400

    kw_scores = {}
    for kw in keywords:
        entry = heat.get(kw, {})
        manual_count = entry.get("manual_count", 0)
        count = entry.get("count", 0)
        last_use = entry.get("last_use", 0)
        created_ts = entry.get("created_ts", 0)
        # 从未触发过且创建超过7天 → 直接淘汰
        if manual_count == 0 and count == 0 and created_ts > 0 and (now - created_ts) > seven_days:
            continue
        # 最近使用奖赏
        if last_use > 0:
            days_since = (now - last_use) / 86400
            recency = max(0, 30 - days_since) / 30 * 5
        else:
            recency = 0
        kw_scores[kw] = manual_count * 10 + count + recency

    sorted_kws = sorted(kw_scores.keys(), key=lambda k: kw_scores[k], reverse=True)
    kept = sorted_kws[:max_keywords]
    profile["keywords"] = kept
    profile["keyword_heat"] = {k: v for k, v in heat.items() if k in kept}


def update_keyword_heat(chat_id: int, kv: object, matched_keyword: str) -> None:
    """关键词参与热度+1，更新最后参与时间。"""
    profile = get_profile(chat_id, kv)
    if not profile:
        return
    heat = profile.get("keyword_heat", {})
    entry = heat.get(matched_keyword)
    now = time.time()
    if entry:
        entry["count"] = entry.get("count", 0) + 1
        entry["last_use"] = now
    else:
        heat[matched_keyword] = {"count": 1, "last_use": now, "created_ts": now}
    profile["keyword_heat"] = heat
    profile["updated_ts"] = now
    kv.set(_PROFILE_KEY.format(chat_id), profile)


def update_manual_keyword_heat(chat_id: int, kv: object, text: str, extra_keywords: list[str] | None = None) -> dict:
    """手动消息热词追踪：从群聊文本中匹配关键词并累积 manual_count。

    对传入文本（群聊上下文/话题来源）做关键词提取，与画像 keywords 做
    子串匹配 + token 匹配，命中的关键词 manual_count +1。
    extra_keywords 为用户手动补充的关键词，也参与匹配。

    返回 dict 供调用方记录日志：
      - {"reason": "no_ready_profile"}  —— 画像尚未 ready
      - {"reason": "no_keywords"}        —— 画像无关键词（且无手动补充）
      - {"matched": [...], "new": [...]} —— 正常处理结果
    """
    profile = get_profile(chat_id, kv)
    if not profile or not profile.get("ready"):
        return {"reason": "no_ready_profile"}
    kw_list = list(profile.get("keywords", []))
    # 合并手动补充的关键词
    if extra_keywords:
        for ek in extra_keywords:
            if ek not in kw_list:
                kw_list.append(ek)
    if not kw_list:
        return {"reason": "no_keywords"}

    msg_tokens = extract_keywords(text)
    text_lower = text.lower()
    heat = profile.get("keyword_heat", {})
    now = time.time()
    matched_kws: list[str] = []
    new_kws: list[str] = []
    has_update = False

    for kw in kw_list:
        kw_lower = kw.lower()
        matched = kw_lower in text_lower or any(kw_lower in mk or mk in kw_lower for mk in msg_tokens)
        if matched:
            entry = heat.get(kw)
            if entry:
                entry["manual_count"] = entry.get("manual_count", 0) + 1
                entry["last_manual_use"] = now
                entry["last_use"] = now
                matched_kws.append(kw)
            else:
                heat[kw] = {
                    "count": 0,
                    "manual_count": 1,
                    "last_use": now,
                    "last_manual_use": now,
                    "created_ts": now,
                }
                new_kws.append(kw)
            has_update = True

    if has_update:
        profile["keyword_heat"] = heat
        profile["updated_ts"] = now
        kv.set(_PROFILE_KEY.format(chat_id), profile)

    return {"matched": matched_kws, "new": new_kws}


def format_keywords_display(profile: dict, extra_keywords: list[str] | None = None, max_keywords: int = 20) -> str:
    """从 profile 的 keyword_heat + 手动补充关键词构建展示，按总热度排序。"""
    heat = dict(profile.get("keyword_heat", {}))

    # 合并手动关键词（没有热度数据的新词，count/manual_count 均为 0）
    if extra_keywords:
        for kw in extra_keywords:
            if kw not in heat:
                heat[kw] = {"count": 0, "manual_count": 0, "last_use": 0, "created_ts": 0}

    if not heat:
        return ""

    sorted_kws = sorted(
        heat.items(),
        key=lambda item: item[1].get("count", 0) + item[1].get("manual_count", 0),
        reverse=True,
    )

    if max_keywords > 0:
        sorted_kws = sorted_kws[:max_keywords]

    lines = []
    for kw, data in sorted_kws:
        total = data.get("count", 0) + data.get("manual_count", 0)
        auto = data.get("count", 0)
        manual = data.get("manual_count", 0)
        line = f"{kw}（热度: {total}"
        if auto:
            line += f" | 自动: {auto}"
        if manual:
            line += f" | 手动: {manual}"
        line += "）"
        lines.append(line)

    return "\n".join(lines)
