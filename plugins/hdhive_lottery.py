# =============================================================================
# AWBotNest 插件：HDHive 抽奖（hdhive_lottery）
#
# 自动参与 HDHive 抽奖机器人发起的抽奖：监听「发起了一个抽奖 + 参与口令」消息，
# 随机等待后把口令原文发回群里参与；开奖时用自己的 TGID 检测是否中奖并通知主人。
#
# 用你的用户账号监听。参与/中奖结果用 ctx.notify 推给平台主人。
# =============================================================================

import asyncio
import re
import time as _time
from random import randint

__plugin__ = {
    "name": "HDHive抽奖",
    "id": "hdhive_lottery",
    "version": "1.0.0",
    "author": "AWdress",
    "description": "自动参与 HDHive 抽奖：监听抽奖消息，随机等待后发口令参与，开奖检测中奖并通知。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "group_id": {
            "type": "string", "default": "-1001379449445", "label": "影巢群ID",
            "section": "参数", "help": "HDHive 抽奖所在的群组ID。",
        },
        "bot_id": {
            "type": "string", "default": "5831593155", "label": "抽奖机器人ID",
            "section": "参数", "help": "发起抽奖的 HDHive 机器人用户ID。",
        },
        "wait_min": {
            "type": "slider", "default": 25, "label": "参与前最短等待(秒)",
            "min": 0, "max": 300, "step": 5, "section": "参数",
            "help": "收到抽奖后随机等待区间下限，避免秒回显得像机器人。",
        },
        "wait_max": {
            "type": "slider", "default": 65, "label": "参与前最长等待(秒)",
            "min": 5, "max": 600, "step": 5, "section": "参数",
        },
        "notify_owner": {
            "type": "boolean", "default": True, "label": "参与/中奖通知我",
            "section": "参数", "help": "参与成功、失败、中奖时用机器人通知平台主人。",
        },
    },
}

# 进行中的抽奖：key = "chat_id:message_id"（进程内跟踪，无跨插件共享）
_lottery_list: dict = {}
_added_at: dict = {}
_ENTRY_TTL = 3 * 24 * 3600  # 3 天


def _make_key(chat_id, message_id) -> str:
    return f"{chat_id}:{message_id}"


def _prune_stale(log) -> None:
    now = _time.time()
    stale = [k for k, ts in _added_at.items() if now - ts > _ENTRY_TTL]
    for k in stale:
        _lottery_list.pop(k, None)
        _added_at.pop(k, None)
    if stale:
        log.info("[HDHive抽奖] 清理 %d 个僵尸条目", len(stale))
    for k in [k for k in _added_at if k not in _lottery_list]:
        _added_at.pop(k, None)


def _parse_lottery(text: str) -> dict:
    """解析 HDHive 抽奖消息。"""
    info = {}
    m = re.search(r"🏆\s*奖励[:：]\s*(.+)", text)
    info["prize"] = m.group(1).strip() if m else ""
    m = re.search(r"中奖名额[:：]\s*(\d+)", text)
    info["winners_count"] = int(m.group(1)) if m else None
    m = re.search(r"🔑\s*参与口令[:：]\s*\n?\s*([\s\S]+?)(?:\n\s*[🏆👥🙋⏰👉🎁💡]|\Z)", text)
    info["keyword"] = m.group(1).strip() if m else ""
    return info


def _acct_name(client) -> str:
    me = getattr(client, "me", None)
    if not me:
        return "未知账号"
    return f"{me.first_name}(@{me.username})" if me.username else f"{me.first_name}(ID:{me.id})"


def _int_cfg(cfg, key, default):
    try:
        return int(cfg.get(key, default))
    except (ValueError, TypeError):
        return default


async def setup(ctx):
    def _is_hdhive_msg(text: str) -> bool:
        return "发起了一个抽奖" in text and "参与口令" in text

    @ctx.on_message(ctx.filters.text | ctx.filters.caption, group=8)
    async def hdhive_new_lottery(client, message):
        cfg = ctx.config
        text = message.text or message.caption or ""
        # 群 + 机器人 + 抽奖文本 判定
        try:
            group_id = int(cfg.get("group_id", "-1001379449445"))
            bot_id = int(cfg.get("bot_id", "5831593155"))
        except (ValueError, TypeError):
            return
        if message.chat.id != group_id:
            return
        fu = message.from_user
        if not (fu and fu.is_bot and fu.id == bot_id):
            return
        if not _is_hdhive_msg(text):
            return

        _prune_stale(ctx.log)
        info = _parse_lottery(text)
        if not info["keyword"]:
            ctx.log.warning("[HDHive抽奖] 未解析出口令，跳过 msg=%s", message.id)
            return

        key = _make_key(message.chat.id, message.id)
        if key in _lottery_list:
            return
        _lottery_list[key] = {"keyword": info["keyword"], "prize": info["prize"],
                              "chat_id": message.chat.id, "won": False}
        _added_at[key] = _time.time()

        wmin = _int_cfg(cfg, "wait_min", 25)
        wmax = _int_cfg(cfg, "wait_max", 65)
        if wmin > wmax:
            wmin, wmax = wmax, wmin
        wait_time = randint(wmin, wmax)
        ctx.log.info("[HDHive抽奖] %ss 后参与 key=%s", wait_time, key)
        await asyncio.sleep(wait_time)

        if key not in _lottery_list:
            return

        acct = _acct_name(client)
        notify = cfg.get("notify_owner", True)
        try:
            await client.send_message(message.chat.id, info["keyword"], parse_mode=None)
            ctx.log.info("[HDHive抽奖] 已发口令参与: %s", key)
            if notify:
                try:
                    await ctx.notify(
                        f"HDHive抽奖参与成功\n🎁 {info['prize']}\n🔑 {info['keyword']}\n🔗 {message.link}",
                        level="success", category="HDHive抽奖", account=client,
                    )
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[HDHive抽奖] 发口令失败: %r", e)
            if notify:
                try:
                    await ctx.notify(
                        f"HDHive抽奖参与失败\n🎁 {info['prize']}\n⚠️ {e}\n🔗 {message.link}",
                        level="error", category="HDHive抽奖", account=client,
                    )
                except Exception:
                    pass

    @ctx.on_message(ctx.filters.text | ctx.filters.caption, group=9)
    async def hdhive_draw_result(client, message):
        cfg = ctx.config
        text = message.text or message.caption or ""
        try:
            group_id = int(cfg.get("group_id", "-1001379449445"))
            bot_id = int(cfg.get("bot_id", "5831593155"))
        except (ValueError, TypeError):
            return
        if message.chat.id != group_id:
            return
        fu = message.from_user
        if not (fu and fu.is_bot and fu.id == bot_id):
            return
        if "抽奖结果" not in text or "中奖名单" not in text:
            return

        m = re.search(r"🏆\s*奖励[:：]\s*(.+)", text)
        prize = m.group(1).strip() if m else ""
        winners = re.findall(r"\d+\.\s*(.+?)\s*[（(]\s*TGID[:：]\s*(\d+)\s*[)）]", text)
        winner_tgids = [int(tid) for _, tid in winners]
        winner_names = [name.strip() for name, _ in winners]

        me = getattr(client, "me", None)
        won = bool(me and me.id in winner_tgids)

        if won and cfg.get("notify_owner", True):
            ctx.log.info("[HDHive抽奖] 中奖！奖励=%s", prize)
            try:
                await ctx.notify(
                    f"HDHive抽奖中奖啦\n🎁 {prize}\n🏅 {', '.join(winner_names) or '(未解析)'}\n🔗 {message.link}",
                    level="success", category="HDHive抽奖", account=client,
                )
            except Exception:
                pass

        for k in [k for k, v in _lottery_list.items() if v["chat_id"] == message.chat.id]:
            _lottery_list.pop(k, None)
            _added_at.pop(k, None)


async def teardown(ctx):
    _lottery_list.clear()
    _added_at.clear()
