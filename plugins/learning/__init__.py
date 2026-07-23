# =============================================================================
# AWBotNest 插件：智能学习参与（learning）
#\n# 通过学习你的聊天偏好和说话风格，在匹配关键词的群聊中智能参与对话。
# 冷启动：未学到偏好前不参与任何群聊。
#
# 工作流程：
#   1. 监听自己发的消息 → 记录到缓冲，每 N 条（summarize_gap）做一次
#      LLM 关键词+风格总结，建立该群的偏好画像 + 全局说话风格。
#   2. 监听所有群消息 → 全量缓冲（供 summarize 取上下文参考）。
#   3. 当群聊中有人发消息匹配画像的关键词 → 按概率 roll，
#      通过则用学到的说话风格生成自然回复。
#   4. group ID 配置：一行一个，留空 = 不监听任何群。
#
# 默认不启用，手动打开后需要发一些消息让插件学习。
# =============================================================================
import asyncio
import time
import traceback

from ._config import parse_config
from ._engine import clear_clients
from ._judger import should_participate
from ._participator import participate
from ._profiler import (
    clear,
    format_keywords_display,
    get_context_lines,
    get_message_count,
    get_profile,
    get_recent_context,
    get_recent_own_messages,
    push_all_message,
    push_own_message,
    reset_counter,
    summarize,
    update_manual_keyword_heat,
)
from ._social import flush as flush_social
from ._social import record

__plugin__ = {
    "name": "智能学习",
    "id": "learning",
    "version": "2.9.0",
    "author": "Yy",
    "description": (
        "学习你的聊天偏好和说话风格，在匹配关键词的群聊中智能参与对话。"
        "冷启动：未学到偏好前不参与。"
    ),
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        # —— 接口 ——
        "api_key": {
            "type": "password", "default": "", "label": "API Key",
            "section": "接口", "help": "OpenAI 兼容接口的密钥。",
        },
        "base_url": {
            "type": "string", "default": "", "label": "接口地址(Base URL)",
            "section": "接口", "help": "OpenAI 兼容接口地址，留空用官方默认。",
        },
        "model": {
            "type": "string", "default": "gpt-3.5-turbo", "label": "模型",
            "section": "接口", "help": "用于关键词风格分析和参与回复。",
        },
        # —— 学习 ——
        "summarize_gap": {
            "type": "slider", "default": 10, "label": "总结间隔(条)",
            "min": 3, "max": 100, "step": 1, "section": "学习",
            "help": "每发这么多条消息，就总结一次关键词偏好。越小越灵敏、越费 token。",
        },
        "max_context_lines": {
            "type": "slider", "default": 5, "label": "总结上下文行数",
            "min": 1, "max": 20, "step": 1, "section": "学习",
            "help": "总结时读取每条自己消息前 N 条群聊上下文作为参考。",
        },
        # —— 群组 ——
        "target_groups": {
            "type": "text", "default": "",
            "label": "监听群组",
            "section": "群组",
            "help": (
                "监听这些群组的消息来学习和参与。\n"
                "每个群 ID 一行，也兼容逗号分隔。\n"
                "留空 = 不监听任何群。"
            ),
        },
        # —— 参与 ——
        "enable_participation": {
            "type": "boolean", "default": True, "label": "启用智能参与",
            "section": "参与",
        },
        "participation_rate": {
            "type": "slider", "default": 20, "label": "参与概率(%)",
            "min": 1, "max": 100, "step": 1, "section": "参与",
            "show_if": {"enable_participation": True},
            "help": "匹配到关键词偏好时，按此概率实际参与回复。20 = 20%概率。",
        },
        "participation_context_lines": {
            "type": "slider", "default": 5, "label": "参与时读取上文(条)",
            "min": 1, "max": 20, "step": 1, "section": "参与",
            "show_if": {"enable_participation": True},
            "help": "触发关键词参与时，读取最近 N 条群聊上文给 LLM 参考，减少乱说话。",
        },
        "min_participation_gap": {
            "type": "slider", "default": 60, "label": "发言冷却(秒)",
            "min": 10, "max": 600, "step": 10, "section": "参与",
            "help": "每个群两次参与发言（含你自己发的消息）的最小时间间隔，防止刷屏。",
        },
        "participation_msg_gap": {
            "type": "slider", "default": 5, "label": "消息条数间隔",
            "min": 1, "max": 50, "step": 1, "section": "参与",
            "help": "上一条发言（含你自己发的）之后，需攒够 N 条别人消息才能再次自动参与。防止群活跃时刷屏。",
        },
        # —— 关键词（手动补充） ——
        "keywords": {
            "type": "text", "default": "", "label": "关键词（手动补充）",
            "section": "关键词",
            "help": (
                "补充你关心的关键词，每行或逗号分隔。\n"
                "与自动学习的关键词合并，共同决定是否参与群聊。\n"
                "留空则只使用自动学习的关键词。"
            ),
        },
        # —— 关键词 ——
        "max_keywords": {
            "type": "slider", "default": 20, "label": "关键词上限",
            "min": 5, "max": 100, "step": 5, "section": "关键词",
            "help": "自动学习的关键词数量上限。超出时按参与热度淘汰低频关键词。",
        },
        "keyword_display": {
            "type": "text",
            "default": "",
            "label": "已学关键词",
            "section": "关键词",
            "help": (
                "自动学习的关键词，按你手动发送消息命中次数降序排列。\\n"
                "手动次数越高表示你越常聊这个关键词。\\n"
                "留空 = 尚未学习到关键词。",
            ),
        },
        # —— 当前画像（自动生成，只读展示）——
        "profile_display": {
            "type": "text",
            "default": "",
            "label": "当前画像（自动累积）",
            "section": "身份模拟",
            "help": (
                "每次学习后自动更新，涵盖关键词、语气、口癖、平均字数、\n"
                "标点习惯、emoji 频率、风格描述等全部维度。\n"
                "仅供参考，不可编辑。如字段为空，发送消息触发学习后自动填充。"
            ),
        },
        "profile_prompt_template": {
            "type": "text",
            "default": (
                "请根据以下聊天记录，分析我的说话风格和兴趣偏好。\n\n"
                "【上下文】群聊最近讨论的内容（请从中提取 keywords）：\\n{context}\\n\\n"
                "【我的发言】以下消息中分析我的语气/风格/口癖/字数/标点/emoji：\\n{my_messages}\\n\\n"
                "⚠ 注意：keywords 只从「上下文」中提取，不要从我的发言中提取；\\n"
                "voice 字段（tone/habits/avg_words/punctuation/emoji_freq/style_prompt）只从我的发言中分析。\\n\\n"
                "输出格式（JSON）：\n"
                '{{\n'
                '  "voice": {{\n'
                '    "tone": "语气特征（随意/正经/幽默/暴躁等）",\n'
                '    "avg_words": 平均每句话字数（数字）,\n'
                '    "habits": ["口癖1", "口癖2"],\n'
                '    "punctuation": "标点使用习惯",\n'
                '    "emoji_freq": "emoji 使用频率（很少/偶尔/经常/几乎每条）",\n'
                '    "style_prompt": "一段可读的中文文本，完整描述这个人的说话风格，供 LLM 模仿"\n'
                '  }},\n'
                '  "keywords": ["关键词1", "关键词2"],\\n'
                '  "summary": "一句话总结当前兴趣"\n'
                "}}"
            ),
            "label": "画像总结模板",
            "section": "身份模拟",
            "help": "占位符：{context} = 上下文，{my_messages} = 我自己的发言。⚠ keywords 从上下文提取，voice 从我的发言提取。",
        },
    },
}

# 活跃群组跟踪（用于定时兜底检查）
_active_groups: set[int] = set()
# 发言冷却：chat_id -> 上次成功参与时间戳
_last_participate_time: dict[int, float] = {}
# 消息条数计数：chat_id -> 上次发言后收到的别人消息条数（用于 participation_msg_gap）
_incoming_msg_count: dict[int, int] = {}
# 自动回复中标记集：chat_id 在集合中时，on_own_messages 跳过热词追踪
_auto_sending_chats: set[int] = set()

# ── 配置写入防抖：展示字段更新频繁，合并到防抖窗口后一次性落盘 ──
_CONFIG_DEBOUNCE = 5.0  # 秒，最后一次调用后等待时长
_config_pending: dict = {}
_config_debounce_task: asyncio.Task | None = None


def _format_profile_display(profile: dict) -> str:
    """将画像 dict 格式化成可读的多行文本，供配置页显示（不含关键词，关键词在独立字段中）。"""
    parts = []

    voice = profile.get("voice", {})
    if isinstance(voice, dict):
        tone = (voice.get("tone") or "").strip()
        if tone:
            parts.append(f"【语气】{tone}")
        habits = voice.get("habits", [])
        if habits:
            parts.append(f"【口癖】{'、'.join(habits[:15])}")
        avg_words = (voice.get("avg_words") or "").strip()
        if avg_words:
            parts.append(f"【平均字数】{avg_words}")
        punct = (voice.get("punctuation") or "").strip()
        if punct:
            parts.append(f"【标点习惯】{punct}")
        emoji = (voice.get("emoji_freq") or "").strip()
        if emoji:
            parts.append(f"【emoji】{emoji}")
        style = (voice.get("style_prompt") or "").strip()
        if style:
            parts.append(f"【风格描述】{style}")

    summary = (profile.get("summary") or "").strip()
    if summary:
        parts.append(f"【兴趣总结】{summary}")

    if not parts:
        return ""
    return "\n\n".join(parts)


def _build_profile_display(kv) -> str:
    """跨所有活跃群构建画像展示，每个群独立标注。"""
    parts = []
    for gid in sorted(_active_groups):
        profile = get_profile(gid, kv)
        if not profile:
            continue
        text = _format_profile_display(profile)
        if text:
            parts.append(f"【群 {gid}】\n{text}")
    return "\n\n".join(parts) if parts else "（尚未学习到任何画像，发送消息后自动生成）"


def _build_keyword_display(kv, cfg=None) -> str:
    """跨所有活跃群构建带热度的关键词展示。

    合并 profile.keyword_heat 和 cfg.keywords（手动补充）。
    """
    extra_keywords: list[str] = []
    max_kw = 20
    if cfg:
        if cfg.keywords:
            extra_keywords = [kw.strip().lower() for kw in cfg.keywords.replace("\n", ",").split(",") if kw.strip()]
        max_kw = getattr(cfg, "max_keywords", 20)

    entries = []
    for gid in sorted(_active_groups):
        profile = get_profile(gid, kv)
        # 有自动关键词或手动关键词才展示
        if profile and (profile.get("keywords") or extra_keywords):
            entry = format_keywords_display(profile, extra_keywords=extra_keywords, max_keywords=max_kw)
            if entry:
                entries.append(f"【群 {gid}】\n{entry}")
    return "\n\n".join(entries) if entries else "（暂无关键词）"


def _group_allowed(chat_id: int, cfg) -> bool:
    """检查 chat_id 是否在目标群组中（白名单模式）。"""
    if cfg.target_groups and chat_id not in cfg.target_groups:
        return False
    return True


def _update_config(ctx, **updates):
    """写入插件配置到持久存储（asyncio 防抖：最后一次调用后 5 秒合并写入）。

    ctx.config['x'] = y 不会持久化（ctx.config 是只读 property），
    必须通过 registry.set_config 合并写入。
    展示字段（keyword_display / profile_display）更新频繁，
    防抖窗口内的多次调用合并为一次落盘，减少 IO。
    """
    global _config_debounce_task
    _config_pending.update(updates)
    # 取消上一轮定时器，重新计时
    if _config_debounce_task is not None and not _config_debounce_task.done():
        _config_debounce_task.cancel()
    _config_debounce_task = asyncio.create_task(_flush_config_updates(ctx))


async def _flush_config_updates(ctx):
    """等待防抖窗口后，把累积的配置更新一次性写入 registry。"""
    await asyncio.sleep(_CONFIG_DEBOUNCE)
    updates = dict(_config_pending)
    _config_pending.clear()
    if not updates:
        return
    reg = ctx._registry
    current = reg.get_config(ctx.plugin_id)
    current.update(updates)
    reg.set_config(ctx.plugin_id, current)


async def setup(ctx):
    kv = ctx.kv

    # ── 处理器 1：自己发的消息 → 学习（仅限 target_groups 中的群）──
    @ctx.on_message(ctx.filters.outgoing, group=-11)
    async def on_own_messages(client, message):
        try:
            cfg = parse_config(ctx.config)
            if not cfg.api_key or not cfg.target_groups:
                return
            if not message.text:
                return
            text = message.text.strip()
            if not text or text.startswith("/") or text.startswith("."):
                return

            chat_id = message.chat.id
            if chat_id > 0:
                return  # 私聊不学习
            if not _group_allowed(chat_id, cfg):
                return

            _active_groups.add(chat_id)
            ctx.log.info(
                "[学习] 收到手动消息: 群 %s | %s…",
                chat_id, text[:60],
            )

            fu = message.from_user
            me_name = getattr(fu, "first_name", "") if fu else ""

            # 社交：回复了某人则记录
            if message.reply_to_message:
                rfu = message.reply_to_message.from_user
                if rfu and not rfu.is_self and not rfu.is_bot:
                    record(chat_id, rfu.id, rfu.first_name or "", kv)

            # 学习：计数达标则 LLM 总结
            push_own_message(chat_id, text, kv)

            # 手动消息热词追踪：用群聊上下文匹配热词
            if chat_id not in _auto_sending_chats:
                # 手动发言也计入冷却 + 重置消息条数计数
                _last_participate_time[chat_id] = time.time()
                _incoming_msg_count[chat_id] = 0
                ctx_lines = get_recent_context(chat_id, cfg.max_context_lines or 5)
                if ctx_lines:
                    trigger_text = "\n".join(ctx_lines)
                    manual_kws = [kw.strip().lower() for kw in cfg.keywords.replace("\n", ",").split(",") if kw.strip()] if cfg.keywords else []
                    hresult = update_manual_keyword_heat(chat_id, kv, trigger_text, extra_keywords=manual_kws)
                    _update_config(ctx, keyword_display=_build_keyword_display(kv, cfg))
                    reason = hresult.get("reason")
                    if reason:
                        ctx.log.info(
                            "[学习] 群 %s 手动热词跳过: %s",
                            chat_id, reason,
                        )
                    else:
                        matched = hresult.get("matched", [])
                        new = hresult.get("new", [])
                        msg = f"[学习] 群 {chat_id} 手动热词:"
                        if matched:
                            msg += f" 命中={matched}"
                        if new:
                            msg += f" 新增={new}"
                        ctx.log.info("%s | 上下文=%d条…", msg, len(ctx_lines))
                else:
                    ctx.log.debug("[学习] 群 %s 无上下文记录，跳过热词更新", chat_id)
            else:
                ctx.log.debug("[学习] 群 %s 自动回复消息，跳过热词", chat_id)

            cnt = get_message_count(kv, chat_id)
            ctx.log.info(
                "[学习] 群 %s 手动消息计数: %d/%d (当前/阈值)",
                chat_id, cnt, cfg.summarize_gap,
            )
            if cnt >= cfg.summarize_gap:
                own_msgs = get_recent_own_messages(chat_id, cfg.summarize_gap)
                if own_msgs:
                    profile = await summarize(chat_id, kv, cfg, own_msgs)
                    if profile:
                        ctx.log.info(
                            "[学习] 群 %s 画像已更新: keywords=%s",
                            chat_id, profile.get("keywords", []),
                        )
                        _update_config(ctx, profile_display=_build_profile_display(kv), keyword_display=_build_keyword_display(kv, cfg))
                        reset_counter(chat_id, kv)
                        ctx.log.info(
                            "[学习] 群 %s 画像已更新，风格描述已写入 profile.voice.style_prompt",
                            chat_id,
                        )
        except Exception:
            ctx.log.error("[学习] on_own_messages 异常:\n%s", traceback.format_exc())

    # ── 处理器 2：所有人消息 → 全量缓冲 ──
    @ctx.on_message(~ctx.filters.outgoing, group=11)
    async def on_all_messages(client, message):
        cfg = parse_config(ctx.config)
        if not cfg.api_key:
            return
        if not message.text or not cfg.target_groups:
            return
        fu = message.from_user
        if not fu or fu.is_bot:
            return

        chat_id = message.chat.id
        if not _group_allowed(chat_id, cfg):
            return

        text = message.text.strip()
        if not text or text.startswith("/") or text.startswith("."):
            return

        push_all_message(chat_id, text, fu.id, fu.first_name or "", is_bot=fu.is_bot)
        _incoming_msg_count[chat_id] = _incoming_msg_count.get(chat_id, 0) + 1
        _active_groups.add(chat_id)

    # ── 处理器 3：判定是否参与 ──
    @ctx.on_message(ctx.filters.group & ctx.filters.text & ~ctx.filters.outgoing, group=12)
    async def on_participate(client, message):
        cfg = parse_config(ctx.config)
        if not cfg.api_key or not cfg.enable_participation:
            return
        if not cfg.target_groups:
            return
        fu = message.from_user
        if not fu or fu.is_self or fu.is_bot:
            return
        if not message.text:
            return
        text = message.text.strip()
        if not text or text.startswith("/") or text.startswith("."):
            return

        chat_id = message.chat.id
        if not _group_allowed(chat_id, cfg):
            return

        # 发言冷却检查（时间 + 条数双重间隔）
        now = time.time()
        last_ts = _last_participate_time.get(chat_id, 0)
        if now - last_ts < cfg.min_participation_gap:
            return
        if _incoming_msg_count.get(chat_id, 0) < cfg.participation_msg_gap:
            return

        ok, matched_kw = should_participate(chat_id, text, cfg, kv)
        if not ok:
            return

        ctx.log.info(
            "[学习] 群 %s 触发参与 (关键词: %s): %s…",
            chat_id, matched_kw, text[:30],
        )
        context_lines = get_context_lines(chat_id, cfg.participation_context_lines)
        _auto_sending_chats.add(chat_id)
        try:
            reply = await participate(client, chat_id, text, cfg, kv, context_lines=context_lines)
        finally:
            _auto_sending_chats.discard(chat_id)
        if reply:
            ctx.log.info("[学习] 群 %s 已回复: %s", chat_id, reply[:50])
            _last_participate_time[chat_id] = time.time()
            _incoming_msg_count[chat_id] = 0
            _update_config(ctx, keyword_display=_build_keyword_display(kv, cfg))

    # ── 定时兜底：检查未总结的群 ──
    async def summary_tick():
        cfg = parse_config(ctx.config)
        if not cfg.api_key:
            return
        for chat_id in list(_active_groups):
            cnt = get_message_count(kv, chat_id)
            if cnt >= cfg.summarize_gap:
                own_msgs = get_recent_own_messages(chat_id, cfg.summarize_gap)
                if own_msgs:
                    profile = await summarize(chat_id, kv, cfg, own_msgs)
                    if profile:
                        _update_config(ctx, profile_display=_build_profile_display(kv), keyword_display=_build_keyword_display(kv, cfg))
                        reset_counter(chat_id, kv)

    ctx.schedule(summary_tick, "interval", minutes=5, id="AI学习总结")


async def teardown(ctx):
    global _config_debounce_task
    # 取消防抖定时器，但把累积的配置更新立即落盘，防止丢失最后一次展示更新
    if _config_debounce_task is not None and not _config_debounce_task.done():
        _config_debounce_task.cancel()
    if _config_pending:
        updates = dict(_config_pending)
        _config_pending.clear()
        reg = ctx._registry
        current = reg.get_config(ctx.plugin_id)
        current.update(updates)
        reg.set_config(ctx.plugin_id, current)

    # 社交图谱刷盘 + 清理缓存的 AI 客户端
    await flush_social(ctx.kv)
    clear_clients()

    clear()
    _active_groups.clear()
    _last_participate_time.clear()
    _incoming_msg_count.clear()
    _auto_sending_chats.clear()
