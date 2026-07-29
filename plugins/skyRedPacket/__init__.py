# =============================================================================
# AWBotNest 插件：天空红包（skyRedPacket）
#
# 由 tgbot-n/plugins/user/red_packet/hdsky.py 迁移适配。
# 天空小秘（bot ID 8907007783）在群组发拼手气红包，
# 消息含「拼手气红包」关键字，内联键盘有「抢红包」按钮，
# 点击按钮抢红包。
#
# 策略（v2.4）：
# 1. 追踪群内所有发言，按 msgid 维护最近 20 位不重复发言者
# 2. 检测到拼手气红包时：
#    - 是最近 20 位发言人之一 → 已发言 → 等 spoken_delay 秒
#    - 否则 → 未发言 → 等 no_speech_delay 秒（等 30 秒限制解除）
#    - 再叠加 random.uniform(0, random_delay_max) 随机延迟
# 3. 点击「抢红包」按钮并通知结果
# 4. 去重缓存持久化到 ctx.kv，热重载后不重复抢包
# =============================================================================

from __future__ import annotations

import asyncio
import random
import time

__plugin__ = {
    "name": "天空红包",
    "id": "skyRedPacket",
    "version": "2.4.0",
    "author": "Yy",
    "description": "天空小秘（bot 8907007783）拼手气红包自动抢：按 msgid 追踪最近 20 位发言人，"
    "已发言快抢、未发言慢抢，自适应延迟 + 随机抖动防检测。",
    "scope": "user",
    "changelog": (
        "v2.4.0 更新内容：\n"
        "- 发言判断改为按 msgid 追踪最近 20 位发言人，不再用时间窗口\n"
        "v2.3.0 更新内容：\n"
        "- 项目重命名为 skyRedPacket，从单文件改为目录插件\n"
        "v2.2.0 更新内容：\n"
        "- 去重缓存改用 ctx.kv 持久化，热重载后不重复抢包\n"
        "- 延迟参数改用 slider 类型，更直观\n"
        "- 移除 emoji 命名，符合规范"
    ),
    "config_schema": {
        "enabled_groups": {
            "type": "string",
            "default": "-1001326208894",
            "label": "监听群组（一行一个ID）",
            "section": "群组",
            "help": "要监听的群组ID，每行一个。空 = 所有群。",
        },
        "recent_msg_count": {
            "type": "number",
            "default": 20,
            "label": "最近发言人数",
            "section": "策略",
            "help": "按 msgid 追踪最近 N 位不重复发言人。红包前 30 秒仅限最近 20 位领取。",
        },
        "no_speech_delay": {
            "type": "slider",
            "default": 8,
            "label": "未发言延迟(秒)",
            "section": "策略",
            "min": 1,
            "max": 60,
            "step": 1,
            "help": "未发言时抢红包前等待秒数。",
        },
        "spoken_delay": {
            "type": "slider",
            "default": 1,
            "label": "已发言延迟(秒)",
            "section": "策略",
            "min": 0,
            "max": 30,
            "step": 1,
            "help": "已发言时抢红包前等待秒数。",
        },
        "random_delay_max": {
            "type": "slider",
            "default": 3,
            "label": "随机延迟上限(秒)",
            "section": "策略",
            "min": 0,
            "max": 30,
            "step": 1,
            "help": "在基础延迟上额外叠加的随机延迟上限，避免规律被检测。",
        },
    },
}

BOT_ID = 8907007783
_CLICKED_TTL = 3600
_KV_CLICKED_PREFIX = "clicked:"

# 去重缓存（内存级，启动时从 ctx.kv 恢复）
_clicked: dict[str, float] = {}
# 发言追踪："chat_id" -> 有序列表 [user_id, ...]，按接收顺序保留最近 N 位不重复发言人
_speakers: dict[int, list[int]] = {}


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
    """清理过期的内存去重记录。"""
    now = time.time()
    stale = [k for k, ts in _clicked.items() if now - ts > _CLICKED_TTL]
    for k in stale:
        _clicked.pop(k, None)


def _prune_clicked_kv(ctx: object) -> None:
    """清理过期的 kv 去重记录。"""
    now = time.time()
    for key in ctx.kv.keys():
        if key.startswith(_KV_CLICKED_PREFIX):
            val = ctx.kv.get(key, 0)
            if isinstance(val, (int, float)) and now - float(val) > _CLICKED_TTL:
                ctx.kv.delete(key)


def _load_clicked_from_kv(ctx: object) -> dict[str, float]:
    """从 ctx.kv 恢复去重记录到内存。"""
    clicked: dict[str, float] = {}
    for key in ctx.kv.keys():
        if key.startswith(_KV_CLICKED_PREFIX):
            msg_key = key[len(_KV_CLICKED_PREFIX) :]
            val = ctx.kv.get(key, 0)
            if isinstance(val, (int, float)):
                clicked[msg_key] = float(val)
    return clicked


def _record_speaker(chat_id: int, user_id: int, max_speakers: int = 20) -> None:
    """记录一条消息发送者，按 msgid 顺序维护最近 max_speakers 位不重复发言人。"""
    speakers = _speakers.setdefault(chat_id, [])
    # 如果已存在，先移除旧位置
    if user_id in speakers:
        speakers.remove(user_id)
    # 追加到末尾（最新发言）
    speakers.append(user_id)
    # 裁剪超出部分
    if len(speakers) > max_speakers:
        speakers[:] = speakers[-max_speakers:]


def _is_recent_speaker(chat_id: int, user_id: int, threshold: int = 20) -> bool:
    """判断 user_id 是否在最近 threshold 位发言人中。"""
    speakers = _speakers.get(chat_id, [])
    return user_id in speakers[-threshold:]


def _find_snatch_button(message: object) -> tuple[int, int] | None:
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


def _is_lucky_packet(message: object) -> bool:
    """判断是否为拼手气红包消息。"""
    text = message.text or message.caption or ""
    if "拼手气红包" in text:
        return True
    if "红包" in text and ("份数" in text or "总银元" in text or "总金额" in text):
        return True
    return False


async def setup(ctx: object) -> None:
    cfg = ctx.config
    ctx.log.info("天空红包插件已启用")

    # 从 ctx.kv 恢复去重记录，热重载后不重复抢包
    global _clicked
    _clicked = _load_clicked_from_kv(ctx)
    _prune_clicked_kv(ctx)
    ctx.log.info("从 kv 恢复 %d 条去重记录", len(_clicked))

    # ─── 发言追踪 Handler（群内所有消息，不限于自己）────────────────
    @ctx.on_message(
        ctx.filters.text,
        group=-10,
    )
    async def track_speakers(client: object, message: object) -> None:
        """追踪群内所有消息发送者，按 msgid 维护最近发言人列表。"""
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", 0)
        if chat_id >= 0:
            return  # 只追踪群聊
        # 只追踪配置的群组
        groups = _parse_groups(cfg.get("enabled_groups", ""))
        if groups and chat_id not in groups:
            return
        fu = message.from_user
        if not fu or fu.is_bot:
            return
        threshold = int(cfg.get("recent_msg_count", 20))
        _record_speaker(chat_id, fu.id, threshold)

    # ─── 抢红包 Handler ────────────────────────────────
    @ctx.on_message(
        ctx.filters.group & ctx.filters.user(BOT_ID),
        group=-9,
    )
    async def snatch_red_packet(client: object, message: object) -> None:
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
        ctx.kv.set(f"{_KV_CLICKED_PREFIX}{key}", time.time())

        # ── 自适应延迟：按是否为最近发言人来决定快抢/慢抢 ──
        owner_id = getattr(client, "_owner_id", 0)
        threshold = int(cfg.get("recent_msg_count", 20))
        is_recent = _is_recent_speaker(chat_id, owner_id, threshold)
        if is_recent:
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
                    "最近发言人中%s，等待 %.1fs 后抢 chat=%s msg=%s",
                    speech_state,
                    delay,
                    chat_id,
                    message.id,
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
                f"🏠 所在群组\n   {chat_title}\n   群ID: {chat_id}\n\n⚠️ 错误信息\n   {e}\n\n🔗 消息链接\n   {msg_link}",
                level="error",
                category="失败",
                account=client,
            )


async def teardown(ctx: object) -> None:
    ctx.log.info("天空红包插件已停用")
