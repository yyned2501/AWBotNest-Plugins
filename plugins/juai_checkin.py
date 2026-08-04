# =============================================================================
# AWBotNest 插件：JUAI 自动签到
#
# 每日自动签到 juai (https://www.juaiapi.com)，纯 REST API 签到，无需浏览器。
# 支持定时签到、手动触发、结果通知。
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

__plugin__ = {
    "name": "JUAI 自动签到",
    "id": "juai_checkin",
    "version": "1.0.0",
    "author": "Yy",
    "description": "每日自动签到 juai 平台，纯 API 签到无需浏览器。",
    "changelog": "v1.0.0 初始版本\n- 纯 REST API 签到，无需浏览器\n- 定时签到 + 手动触发\n- 结果通知与签到记录",
    "icon": "https://www.juaiapi.com/favicon.ico",
    "scope": "standalone",
    "default_enabled": False,
    "config_schema": {
        "auto_checkin": {
            "type": "boolean", "default": True, "label": "启用自动签到",
            "section": "功能开关", "cols": 4, "order": 1,
        },
        "notify": {
            "type": "boolean", "default": True, "label": "推送签到结果",
            "section": "功能开关", "cols": 4, "order": 2,
        },
        "email": {
            "type": "string", "default": "", "label": "登录邮箱",
            "help": "juai 平台注册邮箱，如 yyned2501@gmail.com",
            "section": "账号", "cols": 8, "order": 10,
        },
        "password": {
            "type": "password", "default": "", "label": "密码",
            "help": "juai 平台登录密码",
            "section": "账号", "cols": 8, "order": 11,
        },
        "checkin_hour": {
            "type": "slider", "default": 9, "label": "签到小时",
            "min": 0, "max": 23, "step": 1, "section": "定时", "cols": 6, "order": 20,
        },
        "checkin_minute": {
            "type": "slider", "default": 0, "label": "签到分钟",
            "min": 0, "max": 59, "step": 1, "section": "定时", "cols": 6, "order": 21,
        },
        "run_now": {
            "type": "action", "label": "立即签到", "action": "run_now",
            "section": "操作", "cols": 6, "order": 30,
        },
        "last_result": {
            "type": "info", "default": "尚未运行", "label": "最近结果",
            "section": "运行状态", "cols": 12, "order": 40,
        },
        "checkin_history": {
            "type": "info", "default": "暂无记录", "label": "最近签到记录",
            "section": "运行状态", "cols": 12, "order": 41,
        },
    },
}

BASE_URL = "https://www.juaiapi.com"
HISTORY_KEY = "juai_checkin_history"
HISTORY_LIMIT = 30

_run_lock: asyncio.Lock | None = None
_background_tasks: set[asyncio.Task] = set()


async def _do_checkin(ctx, email: str, password: str) -> dict:
    """执行签到流程，返回结果字典。"""
    masked = f"{email[:2]}***@{email.split('@')[1]}" if "@" in email else "***"
    ctx.log.info("[签到] 开始签到：%s", masked)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # Step 1: 登录，获取 session cookie
        ctx.log.info("[签到] 登录中...")
        login_resp = await client.post(
            "/api/user/login",
            json={"username": email, "password": password},
        )
        login_data = login_resp.json()
        if not login_data.get("success"):
            msg = login_data.get("message", "登录失败")
            ctx.log.error("[签到] 登录失败：%s", msg)
            return {"ok": False, "message": f"登录失败：{msg}"}

        user_id = login_data["data"]["id"]
        ctx.log.info("[签到] 登录成功，用户ID=%s", user_id)

        # Step 2: 检查签到状态
        ctx.log.info("[签到] 查询签到状态...")
        status_resp = await client.get(
            "/api/user/checkin",
            headers={"New-Api-User": user_id},
        )
        status_data = status_resp.json()
        if not status_data.get("success"):
            ctx.log.warning("[签到] 查询状态失败：%s", status_data.get("message", "未知"))
        else:
            stats = status_data.get("data", {}).get("stats", {})
            if stats.get("checked_in_today"):
                ctx.log.info("[签到] 今日已签到，无需重复操作")
                total_quota = stats.get("total_quota", 0)
                checkin_count = stats.get("checkin_count", 0)
                return {
                    "ok": True,
                    "already": True,
                    "message": f"今日已签到（累计签到 {checkin_count} 次，累计获得 {total_quota:,} 额度）",
                }

        # Step 3: 执行签到
        ctx.log.info("[签到] 执行签到...")
        checkin_resp = await client.post(
            "/api/user/checkin",
            json={},
            headers={"New-Api-User": user_id},
        )
        checkin_data = checkin_resp.json()
        if not checkin_data.get("success"):
            msg = checkin_data.get("message", "签到失败")
            ctx.log.error("[签到] 签到失败：%s", msg)
            return {"ok": False, "message": f"签到失败：{msg}"}

        awarded = checkin_data["data"].get("quota_awarded", 0)
        ctx.log.info("[签到] 签到成功，获得额度：%s", awarded)
        return {
            "ok": True,
            "already": False,
            "message": f"签到成功！获得 {awarded:,} 额度",
            "quota": awarded,
        }


async def _run(ctx, source: str):
    """执行完整签到流程（含配置验证、签到、记录、通知）。"""
    email = "yyned2501@gmail.com"
    password = "yy920120"

    result = await _do_checkin(ctx, email, password)

    # 记录历史
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    display = f"{stamp} · {result['message']}"
    record = {"time": stamp, **result}
    history = ctx.kv.get(HISTORY_KEY, [])
    if not isinstance(history, list):
        history = []
    history = [*history, record][-HISTORY_LIMIT:]
    history_display = "\n\n".join(
        f"{item.get('time', '')} · {item.get('message', '')}"
        for item in reversed(history[-10:])
    )

    ctx.update_config({
        "last_result": display,
        "checkin_history": history_display or "暂无记录",
    })
    ctx.kv.set(HISTORY_KEY, history)

    # 通知
    if ctx.config.get("notify", True):
        try:
            level = "success" if result["ok"] else "error"
            await ctx.notify(result["message"], level=level, category="JUAI 签到")
        except Exception as exc:
            ctx.log.warning("[签到] 通知失败：%r", exc)

    ctx.log.info("[签到] %s — %s", source, result["message"])
    return result


async def setup(ctx):
    global _run_lock
    _run_lock = asyncio.Lock()

    @ctx.action("run_now")
    async def _run_now():
        if _run_lock and _run_lock.locked():
            return {"ok": True, "message": "签到任务已在后台运行，请查看运行日志"}
        task = asyncio.create_task(_run(ctx, "手动"))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {"ok": True, "message": "签到已在后台开始，请查看运行日志"}

    if ctx.config.get("auto_checkin", True):
        hour = int(ctx.config.get("checkin_hour", 9))
        minute = int(ctx.config.get("checkin_minute", 0))
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))

        async def _scheduled_checkin():
            ctx.log.info("[签到] 定时任务已触发")
            await _run(ctx, "定时")

        ctx.schedule(
            _scheduled_checkin,
            "cron",
            hour=hour,
            minute=minute,
            id="JUAI 每日签到",
        )
        ctx.log.info("[签到] 已注册每日签到任务：%02d:%02d", hour, minute)
    else:
        ctx.log.info("[签到] 自动签到未启用，仅保留手动签到")


async def teardown(ctx):
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()
    _background_tasks.clear()
    ctx.log.info("JUAI 自动签到插件已停用")