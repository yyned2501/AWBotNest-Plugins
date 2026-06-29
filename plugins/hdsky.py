# =============================================================================
# AWBotNest 插件：天空红包（hdsky）
#
# 由 tgbot-n/plugins/user/red_packet/hdsky.py 迁移适配。
# 天空小秘（bot ID 8907007783）在群组发拼手气红包，
# 消息含「拼手气红包」关键字，内联键盘有「抢红包」按钮，
# 点击按钮抢红包。
#
# 策略：
# 1. 检测到拼手气红包 → 立即算 gap（先于任何 auto_msg，避免 auto_msg 污染 last_id）
# 2. gap >= 阈值 → 不活跃，等待 x 秒后抢
# 3. gap < 阈值 → 活跃，立即抢
# 4. 可选：不活跃时自动发消息，拉近后续红包的活跃度
# =============================================================================

import asyncio
import time

__plugin__ = {
    "name": "天空红包",
    "id": "hdsky",
    "version": "1.4.0",
    "author": "Yy",
    "description": "天空小秘（bot 8907007783）拼手气红包自动抢：检测「抢红包」按钮自动点击，auto_msg 拉近活跃度 + gap 判定不活跃延迟。",
    "scope": "user",
    "config_schema": {
        "enabled_groups": {
            "type": "string", "default": "-1001326208894",
            "label": "监听群组（一行一个ID）",
            "section": "群组",
            "help": "要监听的群组ID，每行一个。空 = 所有群。",
        },
        "auto_msg": {
            "type": "string", "default": "",
            "label": "自动发送的文字",
            "section": "自动发言",
            "help": "群友发 /red 指令时自动发此消息后删除，拉近自身活跃度。为空则不发送。",
        },
        "auto_gap": {
            "type": "slider", "default": 15, "label": "自动发送阈值(msg_id差)",
            "min": 1, "max": 100, "step": 1, "section": "自动发言",
            "help": "群友发 /red 指令时，用此值与自身最后发言 msg_id 比，gap >= auto_gap 才发 auto_msg。值越小越敏感。",
        },
        "inactive_gap": {
            "type": "slider", "default": 20, "label": "不活跃阈值(msg_id差)",
            "min": 5, "max": 100, "step": 5, "section": "延迟策略",
            "help": "红包 msg_id 与最近自身发言差值超过此值视为不活跃，等待 inactive_delay 秒后再抢。",
        },
        "inactive_delay": {
            "type": "slider", "default": 5, "label": "不活跃时等待(秒)",
            "min": 0, "max": 30, "step": 1, "section": "延迟策略",
            "help": "处于不活跃状态时（gap >= 阈值），等待 x 秒后再抢红包。活跃时立即抢。",
        },
        "click_delay": {
            "type": "slider", "default": 0, "label": "额外固定延迟(秒)",
            "min": 0, "max": 10, "step": 1, "section": "延迟策略",
            "help": "无论活跃与否，额外固定等待的秒数。",
        },
    },
}

BOT_ID = 8907007783
_CLICKED_TTL = 3600

# 去重缓存（内存级，插件重载时重置）
_clicked: dict[str, float] = {}
# 自身发言追踪（内存级）
_last_self_msg_id: dict[str, int] = {}


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


async def _get_last_self_id(ctx, chat_id: int) -> int:
    """获取最近一次自身发言的 msg_id，优先读内存，回退读 kv。"""
    key = f"{chat_id}"
    last_id = _last_self_msg_id.get(key)
    if last_id is not None:
        return last_id
    # 读 kv 回填
    db_val = await ctx.kv.get(f"hdsky_last_msg:{chat_id}")
    if db_val:
        try:
            last_id = int(db_val)
            _last_self_msg_id[key] = last_id
            return last_id
        except ValueError:
            pass
    return 0


async def setup(ctx):
    cfg = ctx.config
    ctx.log.info("天空红包插件已启用")

    # ─── 自身发言追踪 Handler ────────────────────────────
    @ctx.on_message(
        ctx.filters.group
        & ctx.filters.me,
        group=-9,
    )
    async def track_self_message(client, message):
        """追踪自己在群中的最后一次发言 msg_id。"""
        chat_id = message.chat.id
        groups = _parse_groups(cfg.get("enabled_groups", ""))
        if groups and chat_id not in groups:
            return

        _last_self_msg_id[f"{chat_id}"] = message.id
        await ctx.kv.set(f"hdsky_last_msg:{chat_id}", str(message.id))

    # ─── 监听群友的 /red 指令（发 auto_msg 拉近活跃度）───
    # 同 group=-9，但 track_self_message 只用 filters.me，群友消息不会被它拦截
    @ctx.on_message(
        ctx.filters.group
        & ctx.filters.regex(r"/red\S*\s+\d+\s+\d+"),
        group=-9,
    )
    async def red_command_alert(client, message):
        """监听群友发送的 /red 指令，gap >= auto_gap 时才发 auto_msg 拉近活跃度。"""
        chat_id = message.chat.id
        groups = _parse_groups(cfg.get("enabled_groups", ""))
        if groups and chat_id not in groups:
            return

        auto_msg = (cfg.get("auto_msg") or "").strip()
        if not auto_msg:
            return

        # 自身最近是否活跃：用 /red 指令的 msg_id 与最后自身发言算 gap
        auto_gap = int(cfg.get("auto_gap", 15))
        last_id = await _get_last_self_id(ctx, chat_id)
        gap = message.id - last_id
        if gap < auto_gap:
            ctx.log.debug("已活跃 gap=%s < auto_gap=%s，跳过 auto_msg", gap, auto_gap)
            return

        try:
            sent = await client.send_message(chat_id, auto_msg)
            # 手动更新 last_id，避免依赖 Pyrogram update loop 触发 track_self_message
            _last_self_msg_id[f"{chat_id}"] = sent.id
            await ctx.kv.set(f"hdsky_last_msg:{chat_id}", str(sent.id))
            await sent.delete()
            ctx.log.info("已响应 /red 发送 auto_msg (gap=%s >= auto_gap=%s) chat=%s last_id=%s",
                         gap, auto_gap, chat_id, sent.id)
        except Exception:
            pass

    # ─── 抢红包 Handler ────────────────────────────────
    @ctx.on_message(
        ctx.filters.group
        & ctx.filters.user(BOT_ID),
        group=-9,
    )
    async def snatch_red_packet(client, message):
        """检测拼手气红包消息并点击「抢红包」按钮。"""
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

        # 去重
        key = f"{chat_id}:{message.id}"
        _prune_clicked()
        if key in _clicked:
            return
        _clicked[key] = time.time()

        # ── 活跃度判定 ──
        inactive_gap = int(cfg.get("inactive_gap", 20))
        last_id = await _get_last_self_id(ctx, chat_id)
        gap = message.id - last_id
        is_inactive = gap >= inactive_gap

        if is_inactive:
            inactive_delay = int(cfg.get("inactive_delay", 5) or 0)
            if inactive_delay > 0:
                ctx.log.info(
                    "不活跃 gap=%s >= %s，等 %ss 后抢 chat=%s msg=%s",
                    gap, inactive_gap, inactive_delay, chat_id, message.id,
                )
                await asyncio.sleep(inactive_delay)
            else:
                ctx.log.info("不活跃 gap=%s >= %s，立即抢 chat=%s msg=%s", gap, inactive_gap, chat_id, message.id)
        else:
            ctx.log.info("活跃 gap=%s < %s，立即抢 chat=%s msg=%s", gap, inactive_gap, chat_id, message.id)

        # 额外固定延迟
        click_delay = int(cfg.get("click_delay", 0) or 0)
        if click_delay > 0:
            await asyncio.sleep(click_delay)

        row, col = btn_pos
        chat_title = getattr(message.chat, "title", "") if message.chat else ""
        msg_link = getattr(message, "link", "")

        try:
            result = await message.click(x=col, y=row, timeout=10)
            result_text = getattr(result, "message", None) or str(result)
            ctx.log.info("已点击抢红包 chat=%s msg=%s 结果=%s", chat_id, message.id, result_text)
            await ctx.notify(
                f"🧧 天空红包-已抢\n\n"
                f"🏠 所在群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"📩 抢包结果\n   {result_text}\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="success",
                category="红包",
                account=client,
            )
        except Exception as e:
            ctx.log.warning("点击抢红包失败 chat=%s msg=%s: %s", chat_id, message.id, e)
            await ctx.notify(
                f"❌ 天空红包-点击失败\n\n"
                f"🏠 所在群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"⚠️ 错误信息\n   {e}\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="error",
                category="红包",
                account=client,
            )


async def teardown(ctx):
    ctx.log.info("天空红包插件已停用")
