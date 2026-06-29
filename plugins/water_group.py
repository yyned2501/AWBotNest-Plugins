# =============================================================================
# AWBotNest 插件：水群（water_group）
#
# 定时从配置的发言列表中随机选取 N 条发送到指定群组，x 秒后删除。
# 用于维持群聊活跃度 / 掉落奖励。
# =============================================================================

import asyncio
import random
import time

__plugin__ = {
    "name": "水群",
    "id": "water_group",
    "version": "1.0.0",
    "author": "Yy",
    "description": "定时从发言列表中随机选 N 条发送到指定群组，x 秒后自动删除。",
    "scope": "user",
    "config_schema": {
        "enabled_groups": {
            "type": "string", "default": "",
            "label": "目标群组（一行一个ID）",
            "section": "群组",
            "help": "要发送的群组ID，每行一个。空 = 所有群。",
        },
        "interval": {
            "type": "slider", "default": 30, "label": "发送间隔(分钟)",
            "min": 1, "max": 480, "step": 1, "section": "定时",
            "help": "每间隔 N 分钟自动发送一次。",
        },
        "messages": {
            "type": "text", "default": "",
            "label": "发言列表",
            "section": "内容",
            "help": "每行一条发言，每次随机选取若干条发送。空则不发送。",
        },
        "count": {
            "type": "slider", "default": 1, "label": "每次发送条数",
            "min": 1, "max": 10, "step": 1, "section": "内容",
            "help": "每次从发言列表中随机选 N 条发送。",
        },
        "delete_after": {
            "type": "slider", "default": 10, "label": "发送后删除(秒)",
            "min": 0, "max": 120, "step": 1, "section": "内容",
            "help": "发送后多少秒删除。0=不删除。",
        },
    },
}


def _parse_groups(raw: str) -> list[int]:
    groups = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                groups.append(int(line))
            except ValueError:
                pass
    return groups


def _parse_messages(raw: str) -> list[str]:
    msgs = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            msgs.append(line)
    return msgs


# 内存级：最后一次发送的时间戳
_last_send: float = 0


async def setup(ctx):
    global _last_send
    cfg = ctx.config
    ctx.log.info("水群插件已启用")
    _last_send = time.time()  # 初始化为当前时间，让第一次也遵守间隔

    async def water_task():
        global _last_send

        c = ctx.config  # 每次读最新配置
        interval = int(c.get("interval", 30))
        if interval <= 0:
            return

        # 检查是否到间隔了
        now = time.time()
        if now - _last_send < interval * 60:
            return

        raw_groups = c.get("enabled_groups", "")
        groups = _parse_groups(raw_groups) if raw_groups else None
        if not groups:
            return

        raw_msgs = c.get("messages", "")
        msgs = _parse_messages(raw_msgs)
        if not msgs:
            return

        count = int(c.get("count", 1))
        count = max(1, min(count, len(msgs)))
        delete_after = int(c.get("delete_after", 10))
        chosen = random.sample(msgs, count)

        if not ctx.user.connected:
            ctx.log.warning("用户账号未连接，跳过水群")
            return

        ctx.log.info("水群：从 %s 条中选 %s 条，发往 %s 个群", len(msgs), count, len(groups))
        _last_send = now

        sent_messages = []
        for chat_id in groups:
            for text in chosen:
                try:
                    sent = await ctx.user.send(chat_id, text)
                    sent_messages.append(sent)
                    await asyncio.sleep(3)  # 每条消息间隔 3 秒，防频率限制
                except Exception as e:
                    ctx.log.warning("水群发送失败 chat=%s: %s", chat_id, e)

        if sent_messages and delete_after > 0:
            await asyncio.sleep(delete_after)
            deleted = 0
            for msg in sent_messages:
                try:
                    await msg.delete()
                    deleted += 1
                except Exception:
                    pass
            if deleted:
                ctx.log.info("已删除 %s 条水群消息", deleted)

    # 每分钟检查一次，内部根据 interval 判断是否已到时间
    ctx.schedule(water_task, "interval", minutes=1, id="water_check")


async def teardown(ctx):
    ctx.log.info("水群插件已停用")
