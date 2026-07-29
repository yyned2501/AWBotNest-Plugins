# =============================================================================
# AWBotNest 插件：天空刮奖（scratch）
#
# 散财童子（@lucifer_hdsky_bot）刮刮乐自动挂机。
# 手动发 /scratch → 检测 Bot 回复你的刮刮乐卡片 → 随机逐格刮开 → 回本就停。
# 赢一把自动在群里发 /scratch 连锁下一张；连续亏损自动停止，关闭插件再开重置。
# =============================================================================

from __future__ import annotations

import asyncio
import random
import re
import time

__plugin__ = {
    "name": "🎰天空刮奖",
    "id": "scratch",
    "version": "1.6.1",
    "author": "Yy",
    "description": "散财童子刮刮乐自动挂机。按钮点击+发送命令双重试，filter 层过滤 Bot+回复，每轮自动连锁。",
    "scope": "user",
    "config_schema": {
        "target_group": {
            "type": "string",
            "default": "-1001326208894",
            "label": "目标群组ID",
            "section": "基础",
            "help": "Bot 所在群组，发 /scratch 和监听都在此群。",
        },
        "bot_id": {
            "type": "number",
            "default": 0,
            "label": "Bot 的 Telegram ID",
            "section": "基础",
            "help": "@lucifer_hdsky_bot 的数字 ID。填 0 = 不按 Bot 过滤（会处理群内所有刮刮乐）。",
            "min": 0,
            "max": 9999999999,
        },
        "click_delay": {
            "type": "slider",
            "default": 0.6,
            "label": "点击间隔(秒)",
            "section": "防封",
            "min": 0.3,
            "max": 2.0,
            "step": 0.1,
            "help": "每格点击之间的等待时间，加 ±20% 随机抖动。",
        },
        "card_cooldown": {
            "type": "slider",
            "default": 5,
            "label": "卡间冷却(秒)",
            "section": "防封",
            "min": 2,
            "max": 30,
            "step": 1,
            "help": "上一张结束后等 N 秒再发 /scratch，随机加 0~3 秒。",
        },
        "max_consecutive_loss": {
            "type": "number",
            "default": 5,
            "label": "连续亏损自动停止",
            "section": "策略",
            "help": "连续 N 张净亏损后自动停止刮奖。关闭插件再开即可重置。",
            "min": 1,
            "max": 20,
        },
    },
}

# ── 模块级状态 ──────────────────────────────────────
_playing: bool = False  # 防止同时玩多张卡
_consecutive_loss: int = 0  # 连续亏损计数
_auto_stopped: bool = False  # 连续亏损后自动停止

# 去重
_seen: dict[str, float] = {}
_SEEN_TTL: float = 300


# ── 工具函数 ────────────────────────────────────────


def _parse_group(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw.split("\n")[0].strip())
    except ValueError:
        return None


def _is_scratch_card(message: object) -> bool:
    text = message.text or message.caption or ""
    if "刮刮乐" not in text:
        return False
    markup = getattr(message, "reply_markup", None)
    if not markup or not getattr(markup, "inline_keyboard", None):
        return False
    for row in markup.inline_keyboard:
        for btn in row:
            cb = getattr(btn, "callback_data", "") or ""
            if cb.startswith("scratch:"):
                return True
    return False


def _parse_card(message: object) -> tuple:
    markup = message.reply_markup
    card_id: int | None = None
    cells: dict[int, tuple[int, int]] = {}
    abandon_pos: tuple[int, int] | None = None

    for r, row in enumerate(markup.inline_keyboard):
        for c, btn in enumerate(row):
            cb = getattr(btn, "callback_data", "") or ""
            if not cb.startswith("scratch:"):
                continue
            parts = cb.split(":")
            if len(parts) < 3:
                continue
            if card_id is None:
                try:
                    card_id = int(parts[1])
                except ValueError:
                    pass
            action = parts[2]
            if action == "abandon":
                abandon_pos = (r, c)
            elif action == "all":
                continue
            else:
                try:
                    cn = int(action)
                    if 1 <= cn <= 9:
                        cells[cn] = (r, c)
                except ValueError:
                    pass
    return card_id, cells, abandon_pos


def _parse_cell_payout(cb_text: str) -> int | None:
    """从 callback_answer.message 解析单格点数。例: "获得 5 银元，净收益 -95 银元。" → 5"""
    if not cb_text:
        return None
    m = re.search(r"获得\s*(\d+)\s*银元", cb_text)
    return int(m.group(1)) if m else None


def _prune_seen() -> None:
    now = time.time()
    stale = [k for k, ts in _seen.items() if now - ts > _SEEN_TTL]
    for k in stale:
        _seen.pop(k, None)


# ── 重试工具 ────────────────────────────────────────


async def _click_btn(
    ctx: object, client: object, chat_id: int, msg_id: int, row: int, col: int, label: str = "格子"
) -> str | None:
    """点击按钮，带重试。返回 callback_answer.message 文本（含"获得 X 银元"），失败返回 None。"""
    for attempt in range(3):
        try:
            msg = await client.get_messages(chat_id, msg_id)
            if not msg:
                ctx.log.warning("get_messages 返回空 msg=%s", msg_id)
                return None

            # 检查按钮还在不在
            markup = getattr(msg, "reply_markup", None)
            if not markup or not getattr(markup, "inline_keyboard", None):
                ctx.log.warning("消息已无键盘 msg=%s", msg_id)
                return None
            if row >= len(markup.inline_keyboard) or col >= len(markup.inline_keyboard[row]):
                ctx.log.warning("按钮 (%d,%d) 已消失 msg=%s", row, col, msg_id)
                return None

            result = await msg.click(x=col, y=row)
            cb_msg = getattr(result, "message", None)
            return str(cb_msg) if cb_msg else ""

        except Exception as e:
            err_s = str(e).upper()
            if "FLOOD_WAIT" in err_s:
                fm = re.search(r"(\d+)", str(e))
                s = int(fm.group(1)) if fm else 3
                ctx.log.warning("⏳ FloodWait %ss (%s)", s, label)
                await asyncio.sleep(s)
                continue
            elif "BUTTON_DATA_INVALID" in err_s or "MESSAGE_ID_INVALID" in err_s:
                ctx.log.warning("消息已失效 msg=%s (%s)", msg_id, label)
                return None
            else:
                if attempt < 2:
                    ctx.log.warning(
                        "点击%s失败 (attempt %d/3): %s，1s后重试",
                        label,
                        attempt + 1,
                        e,
                    )
                    await asyncio.sleep(1)
                else:
                    ctx.log.warning("点击%s失败 (attempt %d/3): %s", label, attempt + 1, e)
    return None


async def _send_scratch(ctx: object, chat_id: int, label: str = "") -> bool:
    """发送 /scratch，带重试。返回 True=成功。"""
    for attempt in range(3):
        try:
            await ctx.user.send(chat_id, "/scratch")
            return True
        except Exception as e:
            err_s = str(e).upper()
            if "FLOOD_WAIT" in err_s:
                fm = re.search(r"(\d+)", str(e))
                s = int(fm.group(1)) if fm else 3
                ctx.log.warning("⏳ 发送 /scratch FloodWait %ss", s)
                await asyncio.sleep(s)
                continue
            else:
                ctx.log.warning(
                    "发送 /scratch 失败 (attempt %d/3)%s: %s",
                    attempt + 1,
                    label,
                    e,
                )
                if attempt < 2:
                    await asyncio.sleep(2)
    return False


# ── 刮奖策略 ────────────────────────────────────────


async def _play_card(ctx: object, client: object, message: object, cfg: dict) -> dict | None:
    chat_id = message.chat.id
    msg_id = message.id
    chat_title = getattr(message.chat, "title", "") if message.chat else ""
    msg_link = getattr(message, "link", "")

    card_id, cells, abandon_pos = _parse_card(message)
    if not card_id or not cells:
        ctx.log.warning("无法解析刮刮乐 msg=%s", msg_id)
        return None

    ctx.log.info("刮奖开始 卡#%s msg=%s", card_id, msg_id)

    remaining = list(range(1, 10))
    random.shuffle(remaining)

    cells_revealed = 0
    cum_payout = 0
    click_delay = float(cfg.get("click_delay", 0.6))

    for cell_num in remaining:
        # 重新拉消息看当前键盘状态
        refetched = await client.get_messages(chat_id, msg_id)
        if not refetched:
            ctx.log.warning("get_messages 返回空 msg=%s", msg_id)
            continue

        _, current_cells, current_abandon = _parse_card(refetched)
        if cell_num not in current_cells:
            continue

        row, col = current_cells[cell_num]

        delay = click_delay * random.uniform(0.8, 1.2)
        await asyncio.sleep(delay)

        cb_text = await _click_btn(ctx, client, chat_id, msg_id, row, col, f"格{cell_num}")
        if cb_text is None:
            # 按钮失效 → 当前卡报废，用累计值结算
            cost = cells_revealed * 100
            net = cum_payout - cost
            ctx.log.warning("卡#%s 中断 格%s失效 累计%d 净%d", card_id, cell_num, cum_payout, net)
            if cells_revealed > 0:
                return {
                    "card_id": card_id,
                    "cells": cells_revealed,
                    "payout": cum_payout,
                    "cost": cost,
                    "net": net,
                }
            return None

        # 从回调文本解析单格点数
        cell_val = _parse_cell_payout(cb_text)
        if cell_val is not None:
            cum_payout += cell_val
        else:
            # 解析失败 → 尝试从消息文本回退
            ctx.log.debug("回调文本解析失败，回退到消息文本: %s", cb_text[:80])
            refetched = await client.get_messages(chat_id, msg_id)
            if refetched:
                new_total = 0
                m = re.search(r"已派奖：(\d+) 银元", refetched.text or "")
                if m:
                    new_total = int(m.group(1))
                    # 本次获得 = 新累计 - 旧累计
                    cell_val = new_total - cum_payout
                    if cell_val > 0:
                        cum_payout = new_total
        if cell_val is None:
            cell_val = 0

        cells_revealed += 1

        ctx.log.info(
            "卡#%s 格%s %d/9 获得%d 累计%d 成本%d",
            card_id,
            cell_num,
            cells_revealed,
            cell_val,
            cum_payout,
            cells_revealed * 100,
        )

        if cum_payout >= cells_revealed * 100:
            ctx.log.info("✅ 回本 卡#%s %d格 累计%d", card_id, cells_revealed, cum_payout)

            # 点「放弃」按钮（重新拉消息拿最新位置）
            refetched = await client.get_messages(chat_id, msg_id)
            if refetched:
                _, _, ab_pos = _parse_card(refetched)
                if ab_pos:
                    await _click_btn(ctx, client, chat_id, msg_id, ab_pos[0], ab_pos[1], "放弃")

            net = cum_payout - cells_revealed * 100
            await ctx.notify(
                f"🏠 群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
                f"🎰 刮奖结果\n   卡#{card_id} | 刮{cells_revealed}格\n"
                f"   累计{cum_payout} | 成本{cells_revealed * 100} | 净{net:+d}\n"
                f"   ✅ 回本就停\n\n"
                f"🔗 消息链接\n   {msg_link}",
                level="success",
                category="回本",
                account=client,
            )
            return {
                "card_id": card_id,
                "cells": cells_revealed,
                "payout": cum_payout,
                "cost": cells_revealed * 100,
                "net": net,
            }

    # 全刮完或中断
    cost = cells_revealed * 100
    net = cum_payout - cost
    emoji = "❌" if net < 0 else "⚠️"
    tag = "亏损" if net < 0 else "中断"

    ctx.log.info(
        "卡#%s %s %d格 累计%d 成本%d 净%d",
        card_id,
        tag,
        cells_revealed,
        cum_payout,
        cost,
        net,
    )

    await ctx.notify(
        f"🏠 群组\n   {chat_title}\n   群ID: {chat_id}\n\n"
        f"🎰 刮奖结果\n   卡#{card_id} | 刮{cells_revealed}格\n"
        f"   累计{cum_payout} | 成本{cost} | 净{net:+d}\n"
        f"   {emoji} {tag}\n\n"
        f"🔗 消息链接\n   {msg_link}",
        level="success" if net >= 0 else "warning",
        category=tag,
        account=client,
    )
    return {
        "card_id": card_id,
        "cells": cells_revealed,
        "payout": cum_payout,
        "cost": cost,
        "net": net,
    }


# ── setup / teardown ────────────────────────────────


async def setup(ctx: object) -> None:
    global _playing, _consecutive_loss, _auto_stopped
    _playing = False
    _auto_stopped = False
    _consecutive_loss = 0

    ctx.log.info("天空刮奖插件已启用 owner_id=%s", ctx.owner_id)

    # ── 消息处理器 ──────────────────────────────────
    # filter 层：target_group ∩ bot_id ∩ reply_to_me
    # handler 只管刮刮乐识别 + 策略执行，不重复判断身份/回复
    cfg = ctx.config
    bot_id = int(cfg.get("bot_id", 0))
    owner_id = ctx.owner_id

    msg_filter = ctx.filters.group
    if bot_id:
        msg_filter = msg_filter & ctx.filters.user(bot_id)
        ctx.log.info("Bot 过滤已启用 bot_id=%s", bot_id)
    else:
        ctx.log.warning("bot_id=0，将处理目标群内所有刮刮乐（不按 Bot 过滤）")

    if owner_id:

        def _reply_to_me(_: object, __: object, message: object) -> bool:
            rt = getattr(message, "reply_to_message", None)
            return bool(rt and getattr(rt, "from_user", None) and rt.from_user.id == owner_id)

        msg_filter = msg_filter & ctx.filters.create(_reply_to_me)
        ctx.log.info("回复过滤已启用 owner_id=%s", owner_id)
    else:
        ctx.log.warning("ctx.owner_id=0，不检查回复")

    @ctx.on_message(msg_filter, group=-9)
    async def on_scratch_card(client: object, message: object) -> None:
        global _playing, _consecutive_loss, _auto_stopped

        tg = _parse_group(cfg.get("target_group", ""))
        if not tg or message.chat.id != tg:
            return

        if _auto_stopped:
            return

        if not _is_scratch_card(message):
            return

        ctx.log.info("🎰 识别到刮刮乐 msg=%s", message.id)

        # 去重
        _prune_seen()
        key = f"{message.chat.id}:{message.id}"
        if key in _seen:
            return
        _seen[key] = time.time()

        if _playing:
            ctx.log.info("⏳ 正在玩卡中，跳过 msg=%s", message.id)
            return

        _playing = True
        try:
            result = await _play_card(ctx, client, message, cfg)
            if not result:
                return

            if result["net"] >= 0:
                _consecutive_loss = 0
            else:
                _consecutive_loss += 1
                ctx.log.info("📉 连续亏损 %d 张", _consecutive_loss)

            max_loss = int(cfg.get("max_consecutive_loss", 5))
            if _consecutive_loss >= max_loss:
                _auto_stopped = True
                ctx.log.warning("🛑 连续亏损达上限，自动停止")
                chat_title = getattr(message.chat, "title", "") if message.chat else ""
                await ctx.notify(
                    f"🛑 天空刮奖已自动停止\n\n"
                    f"🏠 群组\n   {chat_title}\n   群ID: {tg}\n\n"
                    f"⚠️ 原因\n   连续 {_consecutive_loss} 张亏损\n\n"
                    f"💡 重新开始\n   在插件管理关闭再开启「🎰天空刮奖」",
                    level="warning",
                    category="自动停止",
                    account=client,
                )
                return  # 不连锁

            # 无论盈亏，只要没停就连锁下一张
            cooldown = int(cfg.get("card_cooldown", 5))
            wait = cooldown + random.uniform(0, 3)
            ctx.log.info("🔄 %.1fs 后群内发送 /scratch（连续亏损=%d）", wait, _consecutive_loss)
            await asyncio.sleep(wait)
            ok = await _send_scratch(ctx, tg, f" 连续亏损={_consecutive_loss}")
            if ok:
                ctx.log.info("📤 已在群内发送 /scratch")
        except Exception:
            ctx.log.exception("刮奖流程异常")
        finally:
            _playing = False


async def teardown(ctx: object) -> None:
    ctx.log.info("天空刮奖插件已停用")
