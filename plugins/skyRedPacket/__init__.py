# =============================================================================
# AWBotNest 插件：天空红包（skyRedPacket）
#
# 由 tgbot-n/plugins/user/red_packet/hdsky.py 迁移适配。
# 天空小秘（bot ID 8907007783）在群组发拼手气红包，
# 消息含「拼手气红包」关键字，内联键盘有「抢红包」按钮，
# 点击按钮抢红包。
#
# 策略：
# 1. 检测到拼手气红包 → 等随机初始延迟 → 点击「抢红包」
# 2. 如果被拒（回调提示"红包前 30 秒仅限最近 20 位发言人领取"，说明最近没发言），
#    从回调文本解析等待秒数 n，按 message.date + n 等到可抢后，再追加一段随机
#    大延迟才重试，避免总在可抢瞬间精准点击被行为检测识别
# 3. 如果提示已抢过/已结束，直接跳过，不做去重
# =============================================================================

from __future__ import annotations

import asyncio
import random
import re
import time

__plugin__ = {
    "name": "天空红包",
    "id": "skyRedPacket",
    "version": "2.6.0",
    "author": "Yy",
    "description": "天空小秘（bot 8907007783）拼手气红包自动抢：先抢再重试，被拒（未发言）后加随机大延迟再重试。",
    "icon": "https://raw.githubusercontent.com/yyned2501/AWBotNest-Plugins/main/icons/skyRedPacket.svg",
    "scope": "user",
    "changelog": (
        "v2.6.0 更新内容：\n"
        "- 新增「未发言重试延迟」：被拒（说明最近没发言）后，在可抢时间基础上追加一段随机大延迟再重试，"
        "避免总在可抢瞬间精准点击被行为检测识别\n"
        "v2.5.3 更新内容：\n"
        "- 移除全部去重逻辑，见到新红包就抢，已抢过/已结束由回调提示处理\n"
        "v2.5.2 更新内容：\n"
        "- 移除 ctx.kv 持久化去重（热重载不频繁，内存去重已够用）\n"
        "v2.5.1 更新内容：\n"
        "- 已结束的红包不再推送为 success/已抢，改走 warning/已结束\n"
        "v2.5.0 更新内容：\n"
        "- 重构为 retry 策略：先抢，被拒后从回调解析等待时间自动重试\n"
        "- 移除发言追踪逻辑，不再需要预判发言状态\n"
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
        "initial_delay": {
            "type": "slider",
            "default": 2,
            "label": "初始延迟(秒)",
            "section": "策略",
            "min": 0,
            "max": 30,
            "step": 1,
            "help": "检测到红包后首次点击的等待时间，叠加随机抖动。",
        },
        "random_delay_max": {
            "type": "slider",
            "default": 3,
            "label": "随机抖动上限(秒)",
            "section": "策略",
            "min": 0,
            "max": 30,
            "step": 1,
            "help": "在初始延迟上额外叠加的随机延迟上限，避免规律被检测。",
        },
        "retry_offset": {
            "type": "slider",
            "default": 1,
            "label": "重试提前量(秒)",
            "section": "策略",
            "min": 0,
            "max": 10,
            "step": 1,
            "help": "计算出的重试时间前 N 秒提前点击，避免刚好错过。",
        },
        "quiet_retry_min": {
            "type": "slider",
            "default": 10,
            "label": "未发言延迟下限(秒)",
            "section": "策略",
            "min": 0,
            "max": 120,
            "step": 1,
            "help": "被拒（最近没发言）后，在可抢时间基础上再随机延后这么久才重试，模拟真人稍后才注意到。设 0 关闭。",
        },
        "quiet_retry_max": {
            "type": "slider",
            "default": 40,
            "label": "未发言延迟上限(秒)",
            "section": "策略",
            "min": 0,
            "max": 180,
            "step": 1,
            "help": "未发言重试随机延迟的上限，实际等待在下限~上限间随机取值；上下限相同则固定。上限设 0 关闭功能。",
        },
    },
}

BOT_ID = 8907007783
# 最大重试次数
_MAX_RETRIES = 5


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


def _parse_wait_seconds(callback_text: str) -> int | None:
    """从回调文本解析需要等待的秒数。

    取文本中第一个「N 秒」，即红包「前 N 秒」可抢窗口，配合 message.date 算重试点。
    例： "红包前 30 秒仅限最近 20 位发言人领取，请在 12 秒后重试" → 30
         "距红包可抢还有 5 秒" → 5
    """
    if not callback_text:
        return None
    m = re.search(r"(\d+)\s*秒", callback_text)
    if m:
        return int(m.group(1))
    return None


def _quiet_extra_delay(lo: float, hi: float) -> float:
    """未发言被拒时追加的随机额外延迟（秒）。

    上限 <= 0 表示关闭大延迟，返回 0，保持旧的"可抢即点"行为（向后兼容）。
    下限会被夹到 >=0；上下限写反自动纠正；相等则退化为固定值。
    """
    if hi <= 0:
        return 0.0
    lo = max(0.0, lo)
    if hi < lo:
        lo, hi = hi, lo
    return random.uniform(lo, hi)


def _compute_retry_wait(wait_seconds: int, msg_ts: float, retry_offset: float, quiet_extra: float) -> float:
    """计算被拒后到下次点击的等待秒数。

    可抢时间 = 红包发送时间 + wait_seconds，提前 retry_offset 秒点击避免刚好错过，
    未发言时再叠加 quiet_extra 大延迟。拿不到发送时间时退化为从现在等 wait_seconds。
    结果不低于 0.5 秒。
    """
    if msg_ts > 0:
        wait = msg_ts + wait_seconds - retry_offset - time.time()
    else:
        wait = float(wait_seconds)
    wait += quiet_extra
    return max(wait, 0.5)


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


async def _try_snatch(client: object, message: object, row: int, col: int, timeout: int = 10) -> str | None:
    """点击抢红包按钮，返回回调文本。失败返回 None。"""
    try:
        result = await message.click(x=col, y=row, timeout=timeout)
        return getattr(result, "message", None) or str(result)
    except Exception:
        return None


async def setup(ctx: object) -> None:
    cfg = ctx.config
    ctx.log.info("天空红包插件已启用")

    # ─── 抢红包 Handler ────────────────────────────────
    @ctx.on_message(
        ctx.filters.group & ctx.filters.user(BOT_ID),
        group=-9,
    )
    async def snatch_red_packet(client: object, message: object) -> None:
        """检测拼手气红包，先抢再重试，被拒后解析等待时间自动重试。"""
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

        row, col = btn_pos
        msg_link = getattr(message, "link", "")
        msg_date = getattr(message, "date", None)
        msg_ts = msg_date.timestamp() if msg_date else 0

        initial_delay = float(cfg.get("initial_delay", 2))
        random_delay_max = float(cfg.get("random_delay_max", 3))
        retry_offset = float(cfg.get("retry_offset", 1))
        quiet_retry_min = float(cfg.get("quiet_retry_min", 10))
        quiet_retry_max = float(cfg.get("quiet_retry_max", 40))

        # 首次尝试
        delay = initial_delay + (random_delay_max * random.random())
        if delay > 0:
            ctx.log.info("初始延迟 %.1fs 后抢 chat=%s msg=%s", delay, chat_id, message.id)
            await asyncio.sleep(delay)

        result_text = await _try_snatch(client, message, row, col)
        if result_text is None:
            ctx.log.warning("首次点击抢红包失败 chat=%s msg=%s", chat_id, message.id)
            await ctx.notify(
                f"🏠 群ID: {chat_id}\n\n⚠️ 抢红包失败（首次点击无效）\n\n🔗 消息链接\n   {msg_link}",
                level="error",
                category="失败",
                account=client,
            )
            return

        ctx.log.info("首次抢包结果 chat=%s msg=%s %s", chat_id, message.id, result_text)

        # 判断是否被拒（30 秒限制）
        for attempt in range(_MAX_RETRIES):
            # 红包已结束，不再重试
            if "已结束" in result_text or "已过期" in result_text or "已失效" in result_text:
                ctx.log.info("红包已结束，放弃 chat=%s msg=%s", chat_id, message.id)
                await ctx.notify(
                    f"🏠 群ID: {chat_id}\n\n📩 抢包结果\n   {result_text}\n\n🔗 消息链接\n   {msg_link}",
                    level="warning",
                    category="已结束",
                    account=client,
                )
                return

            if "仅限最近" not in result_text and "30秒" not in result_text:
                # 没有限制提示，说明抢到了
                await ctx.notify(
                    f"🏠 群ID: {chat_id}\n\n📩 抢包结果\n   {result_text}\n\n🔗 消息链接\n   {msg_link}",
                    level="success",
                    category="已抢",
                    account=client,
                )
                return

            wait_seconds = _parse_wait_seconds(result_text)
            if wait_seconds is None:
                ctx.log.info("无法解析等待时间，放弃重试 chat=%s msg=%s", chat_id, message.id)
                await ctx.notify(
                    f"🏠 群ID: {chat_id}\n\n📩 抢包结果\n   {result_text}\n\n🔗 消息链接\n   {msg_link}",
                    level="success",
                    category="已抢",
                    account=client,
                )
                return

            # 被拒即说明最近没发言（未进前 20 位发言人）：在可抢时间基础上再
            # 追加一段随机大延迟，模拟真人稍后才注意到，避免总在可抢瞬间精准点击
            quiet_extra = _quiet_extra_delay(quiet_retry_min, quiet_retry_max)
            wait = _compute_retry_wait(wait_seconds, msg_ts, retry_offset, quiet_extra)

            ctx.log.info(
                "被拒(未发言)，可抢后再延后 %.1fs，共等待 %.1fs 后重试（attempt %d/%d）chat=%s msg=%s",
                quiet_extra,
                wait,
                attempt + 1,
                _MAX_RETRIES,
                chat_id,
                message.id,
            )
            await asyncio.sleep(wait)

            result_text = await _try_snatch(client, message, row, col)
            if result_text is None:
                ctx.log.warning("重试点击失败 chat=%s msg=%s", chat_id, message.id)
                await ctx.notify(
                    f"🏠 群ID: {chat_id}\n\n⚠️ 抢红包失败（重试点击无效）\n\n🔗 消息链接\n   {msg_link}",
                    level="error",
                    category="失败",
                    account=client,
                )
                return

            ctx.log.info(
                "重试结果 chat=%s msg=%s attempt=%d %s",
                chat_id,
                message.id,
                attempt + 1,
                result_text,
            )

        # 重试耗尽，推送最终结果
        if "已结束" in result_text or "已过期" in result_text or "已失效" in result_text:
            level = "warning"
            category = "已结束"
        else:
            level = "success" if "抢到" in result_text else "warning"
            category = "已抢"
        await ctx.notify(
            f"🏠 群ID: {chat_id}\n\n📩 抢包结果\n   {result_text}\n\n🔗 消息链接\n   {msg_link}",
            level=level,
            category=category,
            account=client,
        )


async def teardown(ctx: object) -> None:
    ctx.log.info("天空红包插件已停用")
