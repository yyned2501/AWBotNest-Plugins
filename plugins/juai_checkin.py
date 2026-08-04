# =============================================================================
# AWBotNest 插件：JUAI 自动签到
#
# 每日自动签到 juai（https://www.juaiapi.com），纯 REST API 签到无需浏览器。
# 契约见 docs/juai-api.md（已实测确认）：
#   1. POST /api/user/login 登录，Set-Cookie: session（30 天）
#   2. GET  /api/user/checkin 查签到状态（需 session cookie + New-Api-User 头）
#   3. POST /api/user/checkin 执行签到；「今日已签到」错误视为已完成
# 支持多账号列表、定时签到、手动触发、结果汇总通知。
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

__plugin__ = {
    "name": "JUAI 自动签到",
    "id": "juai_checkin",
    "version": "1.1.0",
    "author": "Yy",
    "description": "每日自动签到 juai 平台（多账号），纯 REST API 签到无需浏览器。",
    "changelog": (
        "v1.1.0 更新：\n"
        "- 支持多账号签到：账号改为列表配置，逐个登录签到并汇总结果\n"
        "- 移除代码内硬编码账号密码，一律从配置读取（安全红线）；"
        "旧版单账号配置自动兼容\n"
        "- 签到契约实测加固：先查 checked_in_today 再 POST，"
        "「今日已签到」错误视为已完成而非失败\n"
        "v1.0.0 初始版本：\n"
        "- 纯 REST API 签到，无需浏览器；定时签到 + 手动触发 + 结果通知"
    ),
    "icon": "https://www.juaiapi.com/favicon.png",
    "scope": "standalone",
    "default_enabled": False,
    "requirements": ["httpx>=0.27"],
    "config_schema": {
        "auto_checkin": {
            "type": "boolean",
            "default": True,
            "label": "启用自动签到",
            "section": "功能开关",
            "cols": 4,
            "order": 1,
        },
        "notify": {
            "type": "boolean",
            "default": True,
            "label": "推送签到结果",
            "section": "功能开关",
            "cols": 4,
            "order": 2,
        },
        "accounts": {
            "type": "list",
            "default": [],
            "label": "签到账号",
            "item_label": "账号",
            "help": "逐个添加 juai 账号，依次签到。",
            "section": "账号",
            "cols": 12,
            "order": 10,
            "fields": {
                "email": {
                    "type": "string",
                    "label": "登录邮箱",
                    "help": "juai 注册邮箱。",
                },
                "password": {
                    "type": "password",
                    "label": "账户密码",
                    "help": "juai 登录密码。",
                },
            },
        },
        "checkin_hour": {
            "type": "slider",
            "default": 9,
            "label": "签到小时",
            "min": 0,
            "max": 23,
            "step": 1,
            "section": "定时",
            "cols": 6,
            "order": 20,
        },
        "checkin_minute": {
            "type": "slider",
            "default": 7,
            "label": "签到分钟",
            "min": 0,
            "max": 59,
            "step": 1,
            "section": "定时",
            "cols": 6,
            "order": 21,
        },
        "run_now": {
            "type": "action",
            "label": "立即签到",
            "action": "run_now",
            "section": "操作",
            "cols": 6,
            "order": 30,
        },
        "last_result": {
            "type": "info",
            "default": "尚未运行",
            "label": "最近结果",
            "section": "运行状态",
            "cols": 12,
            "order": 40,
        },
        "checkin_history": {
            "type": "info",
            "default": "暂无记录",
            "label": "最近签到记录",
            "section": "运行状态",
            "cols": 12,
            "order": 41,
        },
    },
}

BASE_URL = "https://www.juaiapi.com"
HISTORY_KEY = "checkin_history"
HISTORY_LIMIT = 30
REQUEST_TIMEOUT = 30.0

_run_lock: asyncio.Lock | None = None
_background_tasks: set[asyncio.Task[dict[str, Any]]] = set()


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _masked_email(email: str) -> str:
    local, separator, domain = str(email or "").partition("@")
    if not separator:
        return (local[:2] + "***") if local else "未知账号"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def _configured_accounts(config: dict[str, Any]) -> list[dict[str, str]]:
    """从配置读取账号列表；兼容旧版单账号 email/password 字段。"""
    accounts: list[dict[str, str]] = []
    seen: set[str] = set()
    raw_accounts = config.get("accounts") or []
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip()
            password = str(item.get("password") or "")
            key = email.casefold()
            if email and password and key not in seen:
                seen.add(key)
                accounts.append({"email": email, "password": password})
    legacy_email = str(config.get("email") or "").strip()
    legacy_password = str(config.get("password") or "")
    if legacy_email and legacy_password and legacy_email.casefold() not in seen:
        accounts.append({"email": legacy_email, "password": legacy_password})
    return accounts


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    """响应体解析为 dict；非 JSON 返回空 dict，由调用方按失败处理。"""
    try:
        data = resp.json()
    except (ValueError, httpx.DecodingError):
        return {}
    return data if isinstance(data, dict) else {}


async def _checkin_one(client: httpx.AsyncClient, email: str, password: str) -> dict[str, Any]:
    """单账号签到：登录 → 查状态 → 未签到才 POST。返回 {ok, already, message}。"""
    login_resp = await client.post("/api/user/login", json={"username": email, "password": password})
    login_data = _safe_json(login_resp)
    if not login_data.get("success"):
        message = str(login_data.get("message") or "未知错误")
        return {"ok": False, "already": False, "message": f"登录失败：{message}"}
    user_id = str((login_data.get("data") or {}).get("id") or "")
    if not user_id:
        return {"ok": False, "already": False, "message": "登录成功但未返回用户 ID，接口可能已变更"}
    headers = {"New-Api-User": user_id}

    status_resp = await client.get("/api/user/checkin", headers=headers)
    status_data = _safe_json(status_resp)
    if status_data.get("success"):
        checkin_data = status_data.get("data") or {}
        if not checkin_data.get("enabled", True):
            return {"ok": False, "already": False, "message": "站点当前未启用签到功能"}
        stats = checkin_data.get("stats") or {}
        if stats.get("checked_in_today"):
            total = stats.get("total_checkins")
            suffix = f"，累计签到 {total} 次" if isinstance(total, int) else ""
            return {"ok": True, "already": True, "message": f"今日已签到{suffix}"}

    checkin_resp = await client.post("/api/user/checkin", headers=headers, json={})
    checkin_data = _safe_json(checkin_resp)
    if checkin_data.get("success"):
        awarded = (checkin_data.get("data") or {}).get("quota_awarded")
        if isinstance(awarded, int):
            return {"ok": True, "already": False, "message": f"签到成功，获得 {awarded:,} 额度", "quota": awarded}
        return {"ok": True, "already": False, "message": "签到成功"}
    message = str(checkin_data.get("message") or "签到失败")
    if "已签到" in message:
        return {"ok": True, "already": True, "message": f"今日已签到（{message}）"}
    return {"ok": False, "already": False, "message": f"签到失败：{message}"}


async def _run(ctx: Any, source: str) -> dict[str, Any]:
    """完整签到流程：逐账号签到、记录历史、汇总通知。"""
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    if _run_lock.locked():
        return {"ok": False, "message": "已有签到任务正在运行，请稍后再试"}

    async with _run_lock:
        accounts = _configured_accounts(dict(ctx.config or {}))
        if not accounts:
            result: dict[str, Any] = {"ok": False, "message": "请先添加至少一个 juai 签到账号"}
        else:
            ctx.log.info("开始%s签到，共 %s 个账号", source, len(accounts))
            account_results: list[dict[str, Any]] = []
            for index, account in enumerate(accounts, 1):
                email = account["email"]
                masked = _masked_email(email)
                ctx.log.info("[签到][%s/%s][%s] 开始", index, len(accounts), masked)
                try:
                    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT) as client:
                        item = await _checkin_one(client, email, account["password"])
                except httpx.HTTPError as exc:
                    item = {"ok": False, "already": False, "message": f"网络请求失败：{exc}"}
                    ctx.log.error("[签到][%s] 请求异常：%r", masked, exc)
                account_results.append(item)
                ctx.log.info("[签到][%s] 结果：%s", masked, item["message"])

            success_count = sum(1 for item in account_results if item["ok"])
            failed_count = len(account_results) - success_count
            summary = f"签到完成（{len(account_results)} 个账号）：成功 {success_count}，失败 {failed_count}"
            details = "\n".join(
                f"[{_masked_email(account['email'])}] {item['message']}"
                for account, item in zip(accounts, account_results, strict=True)
            )
            result = {
                "ok": failed_count == 0,
                "partial": success_count > 0 and failed_count > 0,
                "message": f"{summary}\n{details}",
                "accounts": account_results,
            }

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        display = f"{stamp} · {result['message']}"
        record = {"time": stamp, **result}
        history = ctx.kv.get(HISTORY_KEY, [])
        if not isinstance(history, list):
            history = []
        history = [*history, record][-HISTORY_LIMIT:]
        history_display = "\n\n".join(
            f"{item.get('time', '')} · {item.get('message', '')}" for item in reversed(history[-10:])
        )
        ctx.update_config(
            {
                "last_result": display,
                "checkin_history": history_display or "暂无记录",
            }
        )
        ctx.kv.set(HISTORY_KEY, history)
        if ctx.config.get("notify", True):
            try:
                level = "success" if result["ok"] else ("warning" if result.get("partial") else "error")
                await ctx.notify(result["message"], level=level, category="JUAI 签到")
            except Exception as exc:  # noqa: BLE001 - 通知失败不改变签到结果
                ctx.log.warning("签到结果通知失败：%r", exc)
        ctx.log.info("%s", result["message"])
        return result


async def setup(ctx: Any) -> None:
    global _run_lock
    _run_lock = asyncio.Lock()

    @ctx.action("run_now")
    async def _run_now() -> dict[str, Any]:
        if not _configured_accounts(dict(ctx.config or {})):
            return {"ok": False, "message": "请先添加至少一个 juai 签到账号"}
        if _run_lock and _run_lock.locked():
            return {"ok": True, "message": "签到任务已在后台运行，请查看运行日志"}
        task = asyncio.create_task(_run(ctx, "手动"))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {"ok": True, "message": "签到已在后台开始，请查看运行日志"}

    if ctx.config.get("auto_checkin", True):
        hour = _bounded_int(ctx.config.get("checkin_hour"), 9, 0, 23)
        minute = _bounded_int(ctx.config.get("checkin_minute"), 7, 0, 59)

        async def _scheduled_checkin() -> None:
            ctx.log.info("定时任务已触发")
            await _run(ctx, "定时")

        ctx.schedule(_scheduled_checkin, "cron", hour=hour, minute=minute, id="JUAI 每日签到")
        ctx.log.info("已注册每日签到任务：%02d:%02d", hour, minute)
    else:
        ctx.log.info("自动签到未启用，仅保留手动签到")


async def teardown(ctx: Any) -> None:
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()
    _background_tasks.clear()
    ctx.log.info("JUAI 自动签到插件已停用")
