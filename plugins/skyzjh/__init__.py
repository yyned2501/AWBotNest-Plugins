# -*- coding: utf-8 -*-
# 天空炸金花（skyzjh）：监听 hdsky 炸金花牌局，自动加入、看牌、决策
#
# 适配自 zhajinhua_bot.py：
#   - 每 2 秒轮询牌局状态
#   - 未加入且可加入 → 加入
#   - 轮到我了 → 看牌 → 好牌跟注 / 烂牌弃牌
#   - 支持双击弃牌确认
#   - 新牌局自动刷新 CSRF

from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any

import httpx

__plugin__ = {
    "name": "天空炸金花",
    "id": "skyzjh",
    "version": "1.0.0",
    "author": "Yy",
    "description": "监听 hdsky 炸金花牌局，自动加入、看牌、好牌跟注烂牌弃牌，支持双击弃牌确认。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "enabled": {
            "type": "boolean",
            "default": True,
            "label": "启用自动参与",
            "section": "基本设置",
            "order": 1,
        },
        "cookie_file": {
            "type": "string",
            "default": "/home/hermes/.hermes/cookies/hdsky_cookie.txt",
            "label": "Cookie 文件路径",
            "section": "基本设置",
            "help": "hdsky_portal_session cookie 文件路径",
            "order": 2,
        },
        "base_url": {
            "type": "string",
            "default": "https://hdsky.supertimi.de:8443",
            "label": "服务器地址",
            "section": "基本设置",
            "help": "hdsky 门户地址",
            "order": 3,
        },
        "poll_interval": {
            "type": "slider",
            "default": 2,
            "label": "轮询间隔(秒)",
            "section": "策略",
            "min": 1,
            "max": 10,
            "step": 0.5,
            "help": "牌局状态轮询间隔",
            "order": 10,
        },
        "notify_join": {
            "type": "boolean",
            "default": True,
            "label": "通知：加入牌局",
            "section": "通知",
            "order": 20,
        },
        "notify_hand": {
            "type": "boolean",
            "default": True,
            "label": "通知：手牌决策",
            "section": "通知",
            "help": "好牌跟注 / 烂牌弃牌时通知",
            "order": 21,
        },
        "notify_fold_confirm": {
            "type": "boolean",
            "default": False,
            "label": "通知：双击确认弃牌",
            "section": "通知",
            "order": 22,
        },
        "notify_error": {
            "type": "boolean",
            "default": True,
            "label": "通知：异常",
            "section": "通知",
            "order": 23,
        },
    },
    "changelog": (
        "v1.0.0 初始版本\n"
        "- 自动加入炸金花牌局\n"
        "- 自动看牌、好牌跟注烂牌弃牌\n"
        "- 支持双击弃牌确认\n"
        "- 可配置轮询间隔和通知开关"
    ),
    "requirements": ["httpx>=0.27"],
}

_GOOD_HANDS = ["豹子", "同花顺", "金花", "顺子", "对子"]
_poll_task: asyncio.Task[None] | None = None


def _read_cookie(path: str) -> str | None:
    """从 Netscape cookie 文件读取 hdsky_portal_session。"""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#") and not line.startswith("#HttpOnly_"):
                    continue
                fields = line.split("\t")
                if len(fields) >= 7 and fields[5] == "hdsky_portal_session":
                    return fields[6]
    except (FileNotFoundError, PermissionError, OSError):
        return None
    return None


def _good_hand(hand_type: str) -> bool:
    """判断手牌是否值得继续。"""
    return any(h in hand_type for h in _GOOD_HANDS)


async def _api(
    client: httpx.AsyncClient,
    base: str,
    path: str,
    method: str = "GET",
    body: bytes | None = None,
    csrf: str | None = None,
    cookie: str | None = None,
) -> dict[str, Any]:
    """调用 hdsky API，返回解析后的 JSON。"""
    headers = {
        "Origin": base,
        "Referer": f"{base}/portal",
    }
    if cookie:
        headers["Cookie"] = f"hdsky_portal_session={cookie}"
    if method == "POST":
        headers["Content-Type"] = "application/json"
        if csrf:
            headers["X-CSRF-Token"] = csrf
    try:
        resp = await client.request(method, f"{base}{path}", headers=headers, content=body, timeout=10)
        return resp.json()
    except Exception as e:
        return {"_error": str(e)}


async def _poll_loop(ctx: object) -> None:
    """轮询牌局状态并执行操作。"""
    cfg = ctx.config
    cookie_file = str(cfg.get("cookie_file", "") or "")
    base = str(cfg.get("base_url", "") or "")
    interval = float(cfg.get("poll_interval", 2) or 2)

    csrf: str | None = None
    fold_pending = False

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(verify=ssl_ctx) as client:
        while True:
            try:
                if not cfg.get("enabled", True):
                    await asyncio.sleep(interval)
                    continue

                cookie = _read_cookie(cookie_file)
                if not cookie:
                    await asyncio.sleep(interval)
                    continue

                # 获取 CSRF token
                if not csrf:
                    sess = await _api(client, base, "/api/portal/session", cookie=cookie)
                    csrf = sess.get("csrfToken", "")

                # 获取牌局状态
                game_data = await _api(client, base, "/api/portal/zhajinhua", cookie=cookie, csrf=csrf)
                if "_error" in game_data:
                    ctx.log.warning("API 请求失败: %s", game_data["_error"])
                    csrf = None
                    await asyncio.sleep(interval)
                    continue

                g = game_data.get("game", {})
                rid = g.get("roundId")
                phase = g.get("phase", "")
                actions = g.get("actions", [])
                s = g.get("self", {})
                joined = s.get("joined", False)
                is_turn = s.get("isTurn", False)
                alive = s.get("alive", False)
                hand = s.get("hand", "")
                hand_type = s.get("handType", "")
                fc = s.get("foldConfirm", False)

                # 没加入且可加入 → 加入
                if not joined and "join" in actions:
                    ctx.log.info("加入牌桌 #%s...", rid)
                    r = await _api(client, base, "/api/portal/zhajinhua/join", "POST", b"{}", csrf, cookie)
                    if r.get("ok"):
                        ctx.log.info("加入成功！")
                        if cfg.get("notify_join", True):
                            await ctx.notify(f"🃏 加入牌桌 #{rid}")
                    else:
                        ctx.log.warning("加入失败: %s", r.get("error"))

                # 轮到我了 → 看牌或操作
                if joined and is_turn and phase == "playing":
                    if not hand:
                        # 还没看牌
                        ctx.log.info("轮到我了！看牌...")
                        body = json.dumps({"action": "peek"}).encode()
                        r = await _api(client, base, "/api/portal/zhajinhua/action", "POST", body, csrf, cookie)
                        if r.get("ok"):
                            hand = r.get("game", {}).get("self", {}).get("hand", "?")
                            hand_type = r.get("game", {}).get("self", {}).get("handType", "?")
                            fc = r.get("game", {}).get("self", {}).get("foldConfirm", False)
                            ctx.log.info("手牌: %s (%s)", hand, hand_type)

                            if _good_hand(hand_type):
                                ctx.log.info("好牌！跟注")
                                body = json.dumps({"action": "call"}).encode()
                                await _api(client, base, "/api/portal/zhajinhua/action", "POST", body, csrf, cookie)
                                ctx.log.info("已跟注，等待下一轮")
                                if cfg.get("notify_hand", True):
                                    await ctx.notify(f"🃏 好牌跟注: {hand} ({hand_type})")
                            else:
                                ctx.log.info("烂牌！弃牌")
                                body = json.dumps({"action": "fold"}).encode()
                                await _api(client, base, "/api/portal/zhajinhua/action", "POST", body, csrf, cookie)
                                if fc:
                                    fold_pending = True
                                else:
                                    ctx.log.info("已弃牌")
                                    if cfg.get("notify_hand", True):
                                        await ctx.notify(f"🃏 烂牌弃牌: {hand} ({hand_type})")
                    else:
                        # 已经看过牌了，直接决策
                        if hand and not _good_hand(hand_type):
                            ctx.log.info("牌不好，弃牌...")
                            body = json.dumps({"action": "fold"}).encode()
                            await _api(client, base, "/api/portal/zhajinhua/action", "POST", body, csrf, cookie)
                            if fc:
                                fold_pending = True
                            else:
                                ctx.log.info("已弃牌")
                                if cfg.get("notify_hand", True):
                                    await ctx.notify(f"🃏 烂牌弃牌: {hand} ({hand_type})")

                elif fold_pending and alive and is_turn:
                    # 双击确认弃牌
                    ctx.log.info("确认弃牌...")
                    body = json.dumps({"action": "fold"}).encode()
                    r = await _api(client, base, "/api/portal/zhajinhua/action", "POST", body, csrf, cookie)
                    if r.get("ok"):
                        ctx.log.info("确认弃牌成功")
                        if cfg.get("notify_fold_confirm", False):
                            await ctx.notify("🃏 双击确认弃牌")
                        fold_pending = False

                # 新牌局开始 → 刷新 CSRF
                if phase == "waiting" and rid and not joined:
                    sess = await _api(client, base, "/api/portal/session", cookie=cookie)
                    csrf = sess.get("csrfToken", "")

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                ctx.log.error("轮询异常: %r", e)
                if cfg.get("notify_error", True):
                    await ctx.notify(f"⚠️ 炸金花轮询异常: {e}", level="warning")
                await asyncio.sleep(interval * 2)


async def setup(ctx: object) -> None:
    global _poll_task
    ctx.log.info("天空炸金花已加载 (v1.0.0)")
    _poll_task = asyncio.create_task(_poll_loop(ctx))
    ctx.log.info("天空炸金花已就绪")


async def teardown(ctx: object) -> None:
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        _poll_task = None
    ctx.log.info("天空炸金花已卸载")
