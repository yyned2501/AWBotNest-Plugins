# =============================================================================
# AWBotNest 插件：天空掉落触发（skyDropTrigger）
#
# 天空小秘（bot ID 8907007783）会概率性地「回复」群里的发言并掉落答题，
# 消息形如「小秘想给你 N 银元奖励。」+ 带按钮的题目。答对即得银元——
# 答题由姊妹插件 skyDropAnswer 负责。
#
# 本插件只负责「喂消息」把掉落刷出来：
# 1. 按配置的 cron 时间点（如 09:00,13:00,20:00）向目标群发一条普通聊天消息；
# 2. 发送前可叠加随机延迟，降低规律性、更像真人发言；
# 3. 若最近 N 分钟内小秘已掉落过，跳过本次触发，避免刷屏干扰答题；
# 4. 监听小秘的银元奖励掉落消息，统计触发/掉落次数供面板查看。
#
# 与 skyDropAnswer 配套使用：本插件触发掉落 → 小秘回复出题 →
# skyDropAnswer 自动作答领取银元。
# =============================================================================

from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

TZ = timezone(timedelta(hours=8))

__plugin__ = {
    "name": "天空掉落触发",
    "id": "skyDropTrigger",
    "version": "1.0.0",
    "author": "Yy",
    "description": "按 cron 定时向目标群发聊天消息，触发天空小秘掉落答题，配合 skyDropAnswer 自动答题赚银元。",
    "icon": "https://raw.githubusercontent.com/yyned2501/AWBotNest-Plugins/main/icons/skyDropTrigger.svg",
    "scope": "user",
    "default_enabled": False,
    "changelog": (
        "v1.0.0 初始版本：\n"
        "- cron 多时间点定时向目标群发触发消息（消息池随机选取）\n"
        "- 随机延迟抖动，降低规律性\n"
        "- 掉落冷却：最近 N 分钟内已掉落则跳过，避免刷屏\n"
        "- 监听小秘银元掉落消息，统计触发/掉落次数"
    ),
    "config_schema": {
        "enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用自动触发",
            "section": "触发设置",
            "cols": 4,
            "order": 1,
        },
        "target_groups": {
            "type": "text",
            "default": "-1001326208894",
            "label": "目标群组（一行一个ID）",
            "section": "触发设置",
            "help": "要发送触发消息的群组 ID，每行一个。",
            "order": 10,
        },
        "cron_times": {
            "type": "string",
            "default": "09:00,13:00,20:00",
            "label": "触发时间点",
            "section": "触发设置",
            "help": "每天的触发时刻，HH:MM 逗号分隔。改后需重载插件生效。",
            "order": 11,
        },
        "jitter_max": {
            "type": "slider",
            "default": 60,
            "label": "随机延迟上限(秒)",
            "section": "触发设置",
            "min": 0,
            "max": 300,
            "step": 5,
            "help": "到点后在 0~此值内随机等待再发送，更像真人。",
            "cols": 6,
            "order": 12,
        },
        "cooldown_minutes": {
            "type": "slider",
            "default": 30,
            "label": "掉落冷却(分钟)",
            "section": "触发设置",
            "min": 0,
            "max": 240,
            "step": 5,
            "help": "最近 N 分钟内小秘已掉落过则跳过本次触发，0=不限制。",
            "cols": 6,
            "order": 13,
        },
        "messages": {
            "type": "text",
            "default": "",
            "label": "触发消息池",
            "section": "消息内容",
            "help": "每次随机选一条发送，一行一条。留空使用内置日常短句。",
            "order": 20,
        },
        "stats": {
            "type": "info",
            "label": "累计统计",
            "section": "状态",
            "order": 30,
        },
    },
}

# 天空小秘 Bot ID（与 skyRedPacket / skyDropAnswer 一致）
BOT_ID = 8907007783

# 内置默认触发消息池：普通日常短句，模拟真人水群
_DEFAULT_MESSAGES = [
    "顶一下",
    "666",
    "有人吗",
    "大家在干嘛",
    "无聊啊",
    "今天怎么样",
    "有好东西吗",
    "蹲一个",
    "前排",
    "路过",
]


def _parse_groups(raw: str) -> list[int]:
    """解析多行群组 ID 字符串为列表（忽略空行与非法行）。"""
    groups: list[int] = []
    for line in (raw or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            groups.append(int(line))
        except ValueError:
            continue
    return groups


def _parse_times(raw: str) -> list[tuple[int, int]]:
    """解析 "09:00,13:00,20:00" 为 [(9,0),(13,0),(20,0)]。

    兼容中文逗号/全角冒号/空白；非法或越界的时间点直接忽略，结果去重。
    """
    out: list[tuple[int, int]] = []
    for part in (raw or "").replace("，", ",").split(","):
        part = part.strip().replace("：", ":")
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", part)
        if not m:
            continue
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59 and (h, mi) not in out:
            out.append((h, mi))
    return out


def _pick_message(cfg: dict[str, Any]) -> str:
    """从配置的消息池随机取一条；池为空时用内置默认短句。"""
    raw = str(cfg.get("messages", "") or "").strip()
    pool = [ln.strip() for ln in raw.split("\n") if ln.strip()] if raw else []
    if not pool:
        pool = _DEFAULT_MESSAGES
    return random.choice(pool)


def _fmt_ts(ts: object) -> str:
    """时间戳 → MM-DD HH:MM（东八区）；无效值返回 —。"""
    try:
        val = float(ts or 0)
    except (TypeError, ValueError):
        return "—"
    if val <= 0:
        return "—"
    return datetime.fromtimestamp(val, TZ).strftime("%m-%d %H:%M")


def _refresh_stats(ctx: object) -> None:
    """把累计统计写回 stats 配置项，供面板 info 字段展示。"""
    trig = int(ctx.kv.get("trigger_count", 0) or 0)
    drop = int(ctx.kv.get("drop_count", 0) or 0)
    last_trig = _fmt_ts(ctx.kv.get("last_trigger_ts", 0))
    last_drop = _fmt_ts(ctx.kv.get("last_drop_ts", 0))
    ctx.update_config({"stats": (f"触发 {trig} 次 · 掉落 {drop} 次\n最近触发 {last_trig} · 最近掉落 {last_drop}")})


async def _do_trigger(ctx: object) -> None:
    """执行一次触发：冷却检查 → 随机延迟 → 向各目标群发一条消息 → 记账。"""
    cfg = ctx.config
    if not cfg.get("enabled", False):
        return

    now = time.time()
    cooldown = float(cfg.get("cooldown_minutes", 30) or 0) * 60
    last_drop = float(ctx.kv.get("last_drop_ts", 0) or 0)
    if cooldown > 0 and last_drop > 0 and now - last_drop < cooldown:
        ctx.log.info("距上次掉落仅 %.0f 秒（冷却 %.0f 秒），跳过本次触发", now - last_drop, cooldown)
        return

    jitter = float(cfg.get("jitter_max", 60) or 0)
    if jitter > 0:
        delay = random.uniform(0, jitter)
        ctx.log.info("随机延迟 %.1f 秒后发送", delay)
        await asyncio.sleep(delay)
        # 延迟期间配置可能变化，重查开关
        if not ctx.config.get("enabled", False):
            ctx.log.info("延迟期间插件已被关闭，取消发送")
            return

    groups = _parse_groups(str(ctx.config.get("target_groups", "") or ""))
    if not groups:
        ctx.log.warning("未配置目标群组，跳过")
        return

    msg = _pick_message(ctx.config)
    sent = 0
    for gid in groups:
        try:
            await ctx.user.send(gid, msg)
            sent += 1
            ctx.log.info("已向群 %s 发送触发消息: %s", gid, msg)
        except Exception as e:
            ctx.log.warning("向群 %s 发送失败: %r", gid, e)

    if sent:
        ctx.kv.set("trigger_count", int(ctx.kv.get("trigger_count", 0) or 0) + sent)
        ctx.kv.set("last_trigger_ts", time.time())
        _refresh_stats(ctx)


async def setup(ctx: object) -> None:
    ctx.log.info("天空掉落触发插件已加载 (v%s)", __plugin__["version"])

    # ── 监听小秘的银元掉落（与 skyDropAnswer 识别同一批消息）──
    _drop_filter = (
        ctx.filters.group
        & ctx.filters.user(BOT_ID)
        & ctx.filters.text
        & ctx.filters.regex(r"小秘想给你 \d+ 银元奖励。")
    )

    @ctx.on_message(_drop_filter)
    async def _on_drop(client: object, message: object) -> None:
        ctx.kv.set("last_drop_ts", time.time())
        count = int(ctx.kv.get("drop_count", 0) or 0) + 1
        ctx.kv.set("drop_count", count)
        ctx.log.info("检测到天空掉落答题（累计 %d 次）msg=%s", count, getattr(message, "id", "?"))
        _refresh_stats(ctx)

    # ── 注册 cron 触发任务（每个时间点一个独立任务）──
    times = _parse_times(str(ctx.config.get("cron_times", "")))
    if not times:
        times = [(9, 0), (13, 0), (20, 0)]
        ctx.log.warning("未配置有效触发时间点，使用默认 %s", times)

    for h, m in times:

        async def _tick(_h: int = h, _m: int = m) -> None:
            ctx.log.info("到达触发时间点 %02d:%02d", _h, _m)
            await _do_trigger(ctx)

        ctx.schedule(_tick, "cron", hour=h, minute=m, id=f"drop_{h:02d}{m:02d}")

    ctx.log.info("已注册 %d 个定时触发任务: %s", len(times), [f"{h:02d}:{m:02d}" for h, m in times])
    _refresh_stats(ctx)
    ctx.log.info("天空掉落触发已就绪")


async def teardown(ctx: object) -> None:
    ctx.log.info("天空掉落触发已卸载")
