# =============================================================================
# AWBotNest 插件：天空红包（hdsky）
#
# 由 tgbot-n/plugins/user/red_packet/hdsky.py 迁移适配。
# 天空小秘（bot ID 8907007783）在群组发拼手气红包，
# 消息含「拼手气红包」关键字，内联键盘有「抢红包」按钮，
# 点击按钮抢红包。
#
# 策略（v2.1）：
# 1. 追踪用户自己的发言，按群维护最近 30 秒滚动发言窗口
# 2. 检测到拼手气红包时：
#    - 最近 30 秒发言条数 >= recent_msg_count → 已发言 → 等 spoken_delay 秒
#    - 否则 → 未发言 → 等 no_speech_delay 秒
#    - 再叠加 random.uniform(0, random_delay_max) 随机延迟，避免规律被检测
# 3. 点击「抢红包」按钮并通知结果
# =============================================================================

from __future__ import annotations

import asyncio
import random
import time

__plugin__ = {
    "name": "🧧天空红包",
    "id": "hdsky",
    "version": "2.1.0",
    "author": "Yy",
    "description": "天空小秘（bot 8907007783）拼手气红包自动抢：追踪群内最近发言数，已发言快抢、未发言慢抢，自适应延迟 + 随机抖动防检测。",
    "scope": "user",
    "config_schema": {
        "enabled_groups": {
            "type": "string", "default": "-1001326208894",
            "label": "监听群组（一行一个ID）",
            "section": "群组",
            "help": "要监听的群组ID，每行一个。空 = 所有群。",
        },
        "recent_msg_count": {
            "type": "number", "default": 20,
            "label": "最近发言条数",
            "section": "策略",
            "help": "最近30秒内发言条数阈值，低于此视为未发言。",
        },
        "no_speech_delay": {
            "type": "number", "default": 8,
            "label": "未发言延迟(秒)",
            "section": "策略",
            "help": "未发言时抢红包前等待秒数。",
        },
        "spoken_delay": {
            "type": "number", "default": 1,
            "label": "已发言延迟(秒)",
            "section": "策略",
            "help": "已发言时抢红包前等待秒数。",
        },
        "random_delay_max": {
            "type": "number", "default": 3,
            "label": "随机延迟上限(秒)",
            "section": "策略",
            "help": "在基础延迟上额外叠加的随机延迟上限，避免规律被检测。",
        },
    },
}

BOT_ID = 8907007783
_CLICKED_TTL = 3600
_SPEECH_WINDOW = 30   # 发言统计滚动窗口（秒）
_SPEECH_TTL = 300     # 发言记录保留时长，整键过期清理（秒）

# 去重缓存（内存级，插件重载时重置）
_clicked: dict[str, float] = {}
# 发言日志："owner_id:chat_id" -> 发言时间戳列表
_speech_log: dict[str, list[float]] = {}


def _parse_groups(raw: str) -> list[int]:
    """解析多行群组 ID 字符串为列表。"""
    groups = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                groups.append(int(line))
            except ValueError:
                pass
    return groups


def _prune_clicked() -> None:
    """清理过期的去重记录。"""
    now = time.time()
    stale = [k for k, ts in _clicked.items() if now - ts > _CLICKED_TTL]
    for k in stale:
        _clicked.pop(k, None)


def _record_speech(owner_id: int, chat_id: int) -> None:
    """记录一条发言时间戳，并裁剪 30 秒窗口外的旧记录。"""
    now = time.time()
    key = f"{owner_id}:{chat_id}"
    stamps = _speech_log.get(key, [])
    stamps.append(now)
    cutoff = now - _SPEECH_WINDOW
    _speech_log[key] = [ts for ts in stamps if ts >= cutoff]


def _prune_speech_log() -> None:
    """清理过期发言记录（窗口内已无记录且超过保留时长的键整体删除）。"""
    now = time.time()
    stale = [
        k for k, stamps in _speech_log.items()
        if not stamps or now - stamps[-1] > _SPEECH_TTL
    ]
    for k in stale:
        _speech_log.pop(k, None)


def _count_recent_speech(owner_id: int, chat_id: int) -> int:
    """统计最近 _SPEECH_WINDOW 窗口内的发言条数。"""
    cutoff = time.time() - _SPEECH_WINDOW
    stamps = _speech_log.get(f"{owner_id}:{chat_id}", [])
    return sum(1 for ts in stamps if ts >= cutoff)


def _find_snatch_button(message) -> tuple[int, int] | None:
    """在消息内联键盘里找「抢红包」按钮，返回 (row, col) 或 None。"""
    markup = getattr(message, "reply_markup", None)
    if not markup or not getattr(markup, "inline_keyboard", None):
        return None
    for r, row in enumerate(markup.inline_keyboard):
        for c, btn in enumerate(row):
            text = getattr(btn, "text", "") or ""
            if "抢红包" in text or "抢 红 包" in text or text.strip() in ("抢", "领取红包"):
                return (r, c)
    return None


def _is_lucky_packet(message) -> bool:
    """判断是否为拼手气红包消息。"""
    text = message.text or message.caption or ""
    if "拼手气红包" in text:
        return True
    if "红包" in text and ("份数" in text or "总银元" in text or "总金额" in text):
        return True
    return False


async def setup(ctx):
    cfg = ctx.config
    ctx.log.info("天空红包插件已启用")

    # ─── 发言追踪 Handler（用户自己的 outgoing 消息）────────────────
    @ctx.on_message(
        ctx.filters.outgoing & ctx.filters.text,
        group=-10,
    )
    async def track_outgoing_speech(client, message):
        """追踪用户自己的发言，按群维护滚动发言窗口。"""
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", 0)
        if chat_id >= 0:
            return  # 只追踪群聊，私聊不计入
        owner_id = getattr(client, "_owner_id", 0)
        _record_speech(owner_id, chat_id)
        _prune_speech_log()

    # ─── 抢红包 Handler ────────────────────────────────
    @ctx.on_message(
        ctx.filters.group
        & ctx.filters.user(BOT_ID),
        group=-9,
    )
    async def snatch_red_packet(client, message):
        """检测拼手气红包消息，按发言状态自适应延迟后点击「抢红包」按钮。"""
        chat_id = message.chat.id
        groups = _parse_groups(cfg.get("enabled_groups", ""))
        if groups and chat_id not in groups:
            return

        if not _is_lucky_packet(message):
            return

        btn_pos = _find_snatch_button(message)
        if not btn_pos:
            ctx.log.debug("拼手气红包消息无「抢红包」按钮，跳过 msg=%s", message.id)
            return

        # 去重（按 owner 隔离，多账号安全）
        owner_id = getattr(client, "_owner_id", 0)
        key = f"{owner_id}:{chat_id}:{message.id}"
        _prune_clicked()
        if key in _clicked:
            return
        _clicked[key] = time.time()

        # ── 自适应延迟：按最近发言数决定快抢/慢抢 ──
        threshold = float(cfg.get("recent_msg_count", 20))
        recent = _count_recent_speech(owner_id, chat_id)
        if recent >= threshold:
            base_delay = float(cfg.get("spoken_delay", 1))
            speech_state = "已发言"
        else:
            base_delay = float(cfg.get("no_speech_delay", 8))
            speech_state = "未发言"
        delay = base_delay + random.uniform(0, float(cfg.get("random_delay_max", 3)))

        row, col = btn_pos
        chat_title = getattr(message.chat, "title", "") if message.chat else ""
        msg_link = getattr(message, "link", "")

        try:
            if delay > 0:
                ctx.log.info(
                    "天空红包 最近30秒发言%d条（%s），等待 %.1fs 后抢 chat=%s msg=%s",
                    recent, speech_state, delay, chat_id, message.id,
                )
                await asyncio.sleep(delay)

            result = await message.click(x=col, y=row, timeout=10)
            result_text = getattr(result, "message", None) or str(result)

            ctx.log.info("已点击抢红包 chat=%s msg=%s 结果=%s", chat_id, message.id, result_text)
            await ctx.notify(
                f"🏠 所在群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"📩 抢包结果\n   {result_text}\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="success",
                category="已抢",
                account=client,
            )
        except Exception as e:
            ctx.log.warning("点击抢红包失败 chat=%s msg=%s: %s", chat_id, message.id, e)
            await ctx.notify(
                f"🏠 所在群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"⚠️ 错误信息\n   {e}\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="error",
                category="失败",
                account=client,
            )


async def teardown(ctx):
    ctx.log.info("天空红包插件已停用")
