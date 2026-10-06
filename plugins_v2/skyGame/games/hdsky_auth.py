# -*- coding: utf-8 -*-
# 天空游戏 · HDSky 门户 Cookie 自动续期
#
# 续期分两级：
#   1) 平台 CookieCloud 同步的门户会话（ctx.cookies）仍有效 → 直接复用；
#   2) 平台给不出可用会话（浏览器久未打开门户，快照里的会话已按 expirationDate
#      过期，平台会过滤掉过期 Cookie）→ 用平台同步的 hdsky.me PT 站 Cookie
#      走「门户发验证码 → 站内信取码 → verify」自动登录，新会话写入本地
#      cookie 文件，由 HdskyClient 兜底读取。
# 插件不保存 CookieCloud 凭据，也不直连 CookieCloud 服务端。
#
# 注意：hdskyUid 必须按字符串发送（前端行为），数字会导致 start 与 verify
# 的 challenge 键不一致，verify 报「验证码不正确」。

from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
import time
from typing import Any

import httpx

from .hdsky import DEFAULT_BASE_URL, DEFAULT_COOKIE_FILE, make_client, read_portal_session, resolve_proxy

DEFAULT_HDSKY_UID = "105577"
DEFAULT_CHECK_INTERVAL = 1800

# hdsky.me PT 站（NexusPHP），收件箱 messages.php
PT_BASE = "https://hdsky.me"
PT_SITE_DOMAIN = "hdsky.me"

PORTAL_COOKIE_NAME = "hdsky_portal_session"
PORTAL_DOMAIN = "hdsky.supertimi.de"

# 伪装成浏览器访问 PT 站（Cloudflare 对默认 UA 敏感）
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# 续期失败也会重试，但要防刷站内信：两次续期最小间隔、失败通知节流
_MIN_RENEW_INTERVAL = 600.0
_FAIL_NOTIFY_INTERVAL = 1800.0
# 门户网关瞬时故障（502/503/504 HTML 错误页、连接抖动）：短退避重试，
# 避免几秒的网关抖动让整轮续期失败、游戏 401 干等下一轮防抖/看门狗
_TRANSIENT_STATUS = {502, 503, 504}
_PORTAL_RETRY_ATTEMPTS = 3
_PORTAL_RETRY_BACKOFF = (3.0, 6.0)  # 第 1/2 次失败后的等待秒数

_CODE_RE = re.compile(r"验证码\D{0,10}?(\d{4,8})")
_MSG_LINK_RE = re.compile(r"messages\.php\?action=viewmessage&id=(\d+)")
_SESSION_RE = re.compile(r"hdsky_portal_session=([^;\r\n]+)")
_MAX_AGE_RE = re.compile(r"Max-Age=(\d+)", re.IGNORECASE)


class RenewError(RuntimeError):
    """Cookie 续期业务异常：消息可直接告知管理员。"""


def extract_code(page_html: str) -> str | None:
    """从站内信详情页 HTML 抽取数字验证码；抽不到返回 None。"""
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", page_html))
    m = _CODE_RE.search(text)
    return m.group(1) if m else None


def latest_message_ids(page_html: str) -> list[str]:
    """收件箱列表页 → 消息 id 列表（按页面顺序，通常降序）。"""
    return _MSG_LINK_RE.findall(page_html)


def write_portal_cookie(path: str, value: str, max_age: float) -> None:
    """写 Netscape 格式 cookie 文件（临时文件 + 原子替换，权限 0600）。"""
    expiry = int(time.time() + max_age)
    line = f"#HttpOnly_{PORTAL_DOMAIN}\tFALSE\t/\tTRUE\t{expiry}\t{PORTAL_COOKIE_NAME}\t{value}\n"
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(line)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


async def session_alive(cookie_file: str, base_url: str, cookie_header: str = "", proxy: str = "") -> bool:
    """快速探测门户会话是否有效（GET /api/portal/session）。"""
    cookie = read_portal_session(cookie_file or DEFAULT_COOKIE_FILE)
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    headers = {"User-Agent": _BROWSER_UA}
    if cookie_header:
        headers["Cookie"] = cookie_header
    elif cookie:
        headers["Cookie"] = f"{PORTAL_COOKIE_NAME}={cookie}"
    try:
        async with make_client(proxy) as http:
            resp = await http.get(f"{base}/api/portal/session", headers=headers)
        return resp.status_code == 200 and bool(resp.json().get("csrfToken"))
    except Exception:
        return False


class CookieRenewer:
    """门户 Cookie 续期器。

    插件内共享一个实例（防抖锁全局生效）；所有参数实时读 ctx.config，
    改配置即时生效。可作为无参异步回调直接注入 HdskyClient。
    """

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._lock = asyncio.Lock()
        self._last_attempt = 0.0
        self._last_fail_notify = 0.0

    async def __call__(self) -> bool:
        """HdskyClient 回调入口：普通（带防抖）续期。"""
        return await self.renew()

    async def renew(self, force: bool = False) -> bool:
        """执行一次续期，返回是否写入了新 cookie。force 跳过防抖（手动触发用）。"""
        if not force and time.monotonic() - self._last_attempt < _MIN_RENEW_INTERVAL:
            self._ctx.log.debug("距上次续期不足 %.0f 秒，跳过", _MIN_RENEW_INTERVAL)
            return False
        async with self._lock:
            if not force and time.monotonic() - self._last_attempt < _MIN_RENEW_INTERVAL:
                return False
            self._last_attempt = time.monotonic()
            try:
                await self._do_renew()
            except RenewError as e:
                self._on_fail(str(e))
                return False
            except httpx.ConnectError as e:
                self._on_fail(
                    f"门户/PT 站连不上（{e}）；直连被站方拒时请在「全局设置 → 出站代理」填代理地址"
                )
                return False
            except Exception as e:  # 最外层边界：收敛一切异常为失败通知
                self._on_fail(f"意外异常: {e!r}")
                return False
            return True

    def _on_fail(self, reason: str) -> None:
        """续期失败：记日志 + 节流通知（避免故障时刷屏）。"""
        self._ctx.log.warning("Cookie 续期失败: %s", reason)
        now = time.monotonic()
        if now - self._last_fail_notify >= _FAIL_NOTIFY_INTERVAL:
            self._last_fail_notify = now
            self._ctx.create_task(
                self._notify(f"HDSky Cookie 续期失败：{reason}", level="warning"),
                name="天空游戏 Cookie 续期通知",
            )

    async def _notify(self, msg: str, level: str = "info") -> None:
        if self._ctx.config.get("auth_notify", True):
            await self._ctx.notify(f"🔑 {msg}", level=level)

    async def _do_renew(self) -> None:
        """续期主流程：先复用平台同步的门户会话，拿不到则用 PT 站 Cookie 自动登录。"""
        cfg = self._ctx.config
        base = str(cfg.get("hdsky_base_url", "") or DEFAULT_BASE_URL).rstrip("/")
        proxy = resolve_proxy(self._ctx, cfg)
        if await self._use_platform_session(base, proxy):
            return
        await self._login_portal(base, proxy)

    async def _use_platform_session(self, base: str, proxy: str) -> bool:
        """平台 CookieCloud 里的门户会话仍有效则复用；不可用返回 False（不抛错）。"""
        cookie_header = await cookie_provider(self._ctx)
        if not cookie_header:
            return False
        if not await session_alive("", base, cookie_header, proxy):
            self._ctx.log.info("平台同步的门户会话已失效，改用 PT 站验证码自动登录")
            return False
        self._ctx.log.info("已使用平台 CookieCloud 同步的 HDSky 会话")
        await self._notify("续期成功：已使用平台 CookieCloud 同步的门户会话")
        return True

    async def _login_portal(self, base: str, proxy: str = "") -> None:
        """PT 站验证码自动登录门户，新会话写入本地 cookie 文件供客户端兜底读取。"""
        cookies = getattr(self._ctx, "cookies", None)
        if cookies is None or not getattr(cookies, "available", False):
            raise RenewError("平台 Cookie 同步不可用，请在系统设置中配置 CookieCloud")
        pt_cookie = str(await cookies.header(PT_SITE_DOMAIN, path="/") or "")
        if not pt_cookie:
            raise RenewError(f"平台未同步 {PT_SITE_DOMAIN} 的 PT 站 Cookie，无法自动登录门户")
        uid = str(self._ctx.config.get("hdsky_uid", "") or DEFAULT_HDSKY_UID).strip()
        cookie_file = str(self._ctx.config.get("hdsky_cookie_file", "") or DEFAULT_COOKIE_FILE)

        pt_headers = {"Cookie": pt_cookie, "User-Agent": _BROWSER_UA, "Referer": f"{PT_BASE}/messages.php"}
        portal_headers = {"User-Agent": _BROWSER_UA, "Origin": base, "Referer": f"{base}/portal"}
        async with (
            make_client(proxy) as portal_http,
            make_client(proxy, secure=True, timeout=15) as pt_http,
        ):
            before = set(latest_message_ids((await self._pt_get(pt_http, f"{PT_BASE}/messages.php", pt_headers)).text))

            resp = await self._portal_post(
                portal_http, f"{base}/api/portal/auth/start", {"hdskyUid": uid}, portal_headers, "发送验证码"
            )
            data: dict[str, Any] = resp.json()
            if not data.get("ok"):
                raise RenewError(f"发送验证码失败: {data.get('error', '未知')}")
            self._ctx.log.info("验证码已发送（用户 %s），等待站内信…", data.get("displayName", uid))

            code = await self._wait_for_code(pt_http, pt_headers, before)

            resp = await self._portal_post(
                portal_http,
                f"{base}/api/portal/auth/verify",
                {"hdskyUid": uid, "code": code},
                portal_headers,
                "验证码确认",
            )
            data = resp.json()
            if not data.get("ok"):
                raise RenewError(f"验证码确认失败: {data.get('error', '未知')}")
            set_cookie = resp.headers.get("set-cookie", "")
            m = _SESSION_RE.search(set_cookie)
            if not m:
                raise RenewError("验证通过但响应未携带 Set-Cookie")
            max_age = 43200.0
            mm = _MAX_AGE_RE.search(set_cookie)
            if mm:
                max_age = float(mm.group(1))
            write_portal_cookie(cookie_file, m.group(1), max_age)
            self._ctx.log.info("门户 Cookie 续期成功（有效期 %.0f 小时）", max_age / 3600)
            await self._notify(f"续期成功：已自动登录门户，新会话有效期 {max_age / 3600:.0f} 小时")

    async def _portal_post(
        self,
        http: httpx.AsyncClient,
        url: str,
        payload: dict[str, str],
        headers: dict[str, str],
        step: str,
    ) -> httpx.Response:
        """POST 门户 API，网关瞬时故障（5xx 非 JSON / 连接抖动）自动退避重试。

        返回 body 已校验为 JSON 的响应，业务判断（ok=false、Set-Cookie）留给调用方；
        非瞬时的非 JSON（如 403 HTML 错误页）视为明确失败，立即抛错不重试。
        """
        last_error = ""
        for attempt in range(1, _PORTAL_RETRY_ATTEMPTS + 1):
            try:
                resp = await http.post(url, json=payload, headers=headers)
            except httpx.TransportError as e:
                last_error = f"{step}：门户连接失败（{e.__class__.__name__}）"
            else:
                try:
                    resp.json()
                except Exception:
                    if resp.status_code in _TRANSIENT_STATUS:
                        last_error = f"{step}：门户网关故障（HTTP {resp.status_code} 非 JSON）"
                    else:
                        raise RenewError(f"{step}：服务端返回非 JSON（HTTP {resp.status_code}）") from None
                else:
                    return resp
            if attempt < _PORTAL_RETRY_ATTEMPTS:
                backoff = _PORTAL_RETRY_BACKOFF[attempt - 1]
                self._ctx.log.warning(
                    "%s，%.0f 秒后重试（%d/%d）", last_error, backoff, attempt, _PORTAL_RETRY_ATTEMPTS
                )
                await asyncio.sleep(backoff)
        raise RenewError(f"{last_error}，已重试 {_PORTAL_RETRY_ATTEMPTS} 次")

    async def _pt_get(self, http: httpx.AsyncClient, url: str, headers: dict[str, str]) -> httpx.Response:
        """请求 PT 站页面；非 200 或不像收件箱页面视为登录态失效。"""
        resp = await http.get(url, headers=headers)
        if resp.status_code != 200:
            raise RenewError(f"PT 站请求失败（HTTP {resp.status_code}），PT 站 cookie 可能已失效或被 Cloudflare 拦截")
        return resp

    async def _wait_for_code(self, http: httpx.AsyncClient, pt_headers: dict[str, str], before: set[str]) -> str:
        """轮询收件箱直到出现新验证码邮件并抽出码（最长约 18 秒）。"""
        for _ in range(6):
            await asyncio.sleep(3)
            resp = await self._pt_get(http, f"{PT_BASE}/messages.php", pt_headers)
            new_ids = [i for i in latest_message_ids(resp.text) if i not in before]
            if not new_ids:
                continue
            page = await self._pt_get(http, f"{PT_BASE}/messages.php?action=viewmessage&id={new_ids[0]}", pt_headers)
            code = extract_code(page.text)
            if code:
                self._ctx.log.info("已从站内信读取验证码")
                return code
        raise RenewError("超时未读到验证码站内信")


# ── 共享实例与看门狗 ─────────────────────────────────────────────

async def cookie_provider(ctx: Any) -> str:
    """读取平台同步的 HDSky Cookie；平台不可用时返回空字符串。"""
    cookies = getattr(ctx, "cookies", None)
    if cookies is None or not getattr(cookies, "available", False):
        return ""
    return str(await cookies.header(PORTAL_DOMAIN, path="/") or "")


_renewers: dict[int, CookieRenewer] = {}
_task: asyncio.Task[None] | None = None


def renewer_for(ctx: Any) -> CookieRenewer:
    """取插件内共享的续期器（各模块共用防抖锁，多路 401 只触发一次续期）。"""
    key = id(ctx)
    renewer = _renewers.get(key)
    if renewer is None:
        renewer = CookieRenewer(ctx)
        _renewers[key] = renewer
    return renewer


async def _watchdog(ctx: Any) -> None:
    """定期体检：会话失效则主动续期（覆盖两个游戏都停用的空窗）。"""
    renewer = renewer_for(ctx)
    while True:
        try:
            cfg = ctx.config
            interval = float(cfg.get("auth_check_interval", DEFAULT_CHECK_INTERVAL) or DEFAULT_CHECK_INTERVAL)
            if cfg.get("auth_auto_renew", True):
                cookie_file = str(cfg.get("hdsky_cookie_file", "") or DEFAULT_COOKIE_FILE)
                base = str(cfg.get("hdsky_base_url", "") or DEFAULT_BASE_URL)
                proxy = resolve_proxy(ctx, cfg)
                cookie_header = await cookie_provider(ctx)
                alive = bool(cookie_header) and await session_alive("", base, cookie_header, proxy)
                if not alive:  # 平台没给会话（或已失效）时再看本地续期落盘的会话
                    alive = await session_alive(cookie_file, base, proxy=proxy)
                if not alive:
                    ctx.log.info("体检发现门户会话失效，触发续期")
                    await renewer.renew()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            ctx.log.error("Cookie 看门狗异常: %r", e)
            await asyncio.sleep(60)


def start(ctx: Any) -> None:
    """启动 Cookie 看门狗任务。"""
    global _task
    _task = ctx.create_task(_watchdog(ctx), name="天空游戏 Cookie 看门狗")
    ctx.log.info("Cookie 自动续期看门狗已启动")


def stop(ctx: Any) -> None:
    """停止 Cookie 看门狗任务。"""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
    ctx.log.info("Cookie 自动续期看门狗已停止")
