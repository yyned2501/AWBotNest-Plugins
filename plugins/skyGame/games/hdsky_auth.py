# -*- coding: utf-8 -*-
# 天空游戏 · HDSky 门户 Cookie 自动续期
#
# 门户会话（hdsky_portal_session）12 小时过期。续期全链路：
#   1. 从 MoviePilot 内置 CookieCloud 拉浏览器 cookie 快照（含 hdsky.me PT 站长效登录态）
#   2. 快照里若门户会话仍有余量（>1h）→ 直接复用，免发验证码
#   3. 否则 POST /api/portal/auth/start → 门户把 6 位验证码发到 HDSky 站内信
#   4. 用 PT 站 cookie 读 messages.php，找到新到的验证码邮件并抽码
#   5. POST /api/portal/auth/verify → Set-Cookie → 写 Netscape cookie 文件
#
# 游戏模块无感知：HdskyClient 在 401 时调用注入的 renewer，续期成功后
# 每次请求都会重读 cookie 文件，天然用上新会话。
#
# 注意：hdskyUid 必须按字符串发送（前端行为），数字会导致 start 与 verify
# 的 challenge 键不一致，verify 报「验证码不正确」。

from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
import ssl
import time
from typing import Any

import httpx

from .hdsky import DEFAULT_BASE_URL, DEFAULT_COOKIE_FILE, make_ssl_ctx, read_portal_session

# CookieCloud（MoviePilot 内置）缺省地址，LAN 内直连
DEFAULT_COOKIECLOUD_SERVER = "http://192.168.31.10:3000"
DEFAULT_HDSKY_UID = "105577"
DEFAULT_CHECK_INTERVAL = 1800

# hdsky.me PT 站（NexusPHP），收件箱 messages.php
PT_BASE = "https://hdsky.me"
PT_DOMAINS = ("hdsky.me", ".hdsky.me")

PORTAL_COOKIE_NAME = "hdsky_portal_session"
PORTAL_DOMAIN = "hdsky.supertimi.de"

# 伪装成浏览器访问 PT 站（Cloudflare 对默认 UA 敏感）
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# 续期失败也会重试，但要防刷站内信：两次续期最小间隔、失败通知节流
_MIN_RENEW_INTERVAL = 600.0
_FAIL_NOTIFY_INTERVAL = 1800.0
# 快照内门户会话剩余不足此值则走验证码流程
_MIN_CACHED_REMAIN = 3600.0

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


def build_pt_cookie_header(cookie_data: dict[str, Any]) -> str | None:
    """从解密后的 CookieCloud cookie_data 拼 hdsky.me 请求 Cookie 头。"""
    parts: list[str] = []
    for dom in PT_DOMAINS:
        for c in cookie_data.get(dom) or []:
            name, value = c.get("name"), c.get("value")
            if name and value:
                parts.append(f"{name}={value}")
    return "; ".join(parts) or None


def portal_session_from_cloud(cookie_data: dict[str, Any]) -> tuple[str, float] | None:
    """快照内若有剩余充足的门户会话则返回 (值, 剩余秒数)，否则 None。"""
    now = time.time()
    for c in cookie_data.get(PORTAL_DOMAIN) or []:
        if c.get("name") != PORTAL_COOKIE_NAME or not c.get("value"):
            continue
        remain = float(c.get("expirationDate") or 0) - now
        if remain > _MIN_CACHED_REMAIN:
            return str(c["value"]), remain
    return None


def write_portal_cookie(path: str, value: str, max_age: float) -> None:
    """写 Netscape 格式 cookie 文件（临时文件 + 原子替换，权限 0600）。"""
    expiry = int(time.time() + max_age)
    line = f"#HttpOnly_{PORTAL_DOMAIN}\tFALSE\t/\tTRUE\t{expiry}\t{PORTAL_COOKIE_NAME}\t{value}\n"
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(line)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


async def session_alive(cookie_file: str, base_url: str) -> bool:
    """快速探测门户会话是否有效（GET /api/portal/session）。"""
    cookie = read_portal_session(cookie_file or DEFAULT_COOKIE_FILE)
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    headers = {"User-Agent": _BROWSER_UA}
    if cookie:
        headers["Cookie"] = f"{PORTAL_COOKIE_NAME}={cookie}"
    try:
        async with httpx.AsyncClient(verify=make_ssl_ctx(), timeout=10) as http:
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
            asyncio.create_task(self._notify(f"HDSky Cookie 续期失败：{reason}", level="warning"))

    async def _notify(self, msg: str, level: str = "info") -> None:
        if self._ctx.config.get("auth_notify", True):
            await self._ctx.notify(f"🔑 {msg}", level=level)

    async def _do_renew(self) -> None:
        """续期主流程，失败抛 RenewError。"""
        cfg = self._ctx.config
        server = str(cfg.get("cc_server", "") or DEFAULT_COOKIECLOUD_SERVER).rstrip("/")
        uuid = str(cfg.get("cc_uuid", "") or "").strip()
        password = str(cfg.get("cc_password", "") or "")
        uid = str(cfg.get("hdsky_uid", "") or DEFAULT_HDSKY_UID).strip()
        cookie_file = str(cfg.get("hdsky_cookie_file", "") or DEFAULT_COOKIE_FILE)
        base = (str(cfg.get("hdsky_base_url", "") or DEFAULT_BASE_URL)).rstrip("/")
        if not uuid or not password:
            raise RenewError("未配置 CookieCloud UUID / 加密密钥，无法自动续期")

        cookie_data = await _fetch_cookiecloud(server, uuid, password)

        # 快捷路径：浏览器快照里的门户会话仍有效 → 直接落盘复用
        cached = portal_session_from_cloud(cookie_data)
        if cached:
            value, remain = cached
            write_portal_cookie(cookie_file, value, remain)
            self._ctx.log.info("复用浏览器快照内的门户会话（剩余 %.1f 小时）", remain / 3600)
            await self._notify(f"续期成功：复用浏览器内仍有效的会话（剩余 {remain / 3600:.1f} 小时）")
            return

        pt_cookie = build_pt_cookie_header(cookie_data)
        if not pt_cookie:
            raise RenewError("CookieCloud 快照缺少 hdsky.me PT 站 cookie，请检查浏览器同步")

        pt_headers = {"Cookie": pt_cookie, "User-Agent": _BROWSER_UA, "Referer": f"{PT_BASE}/messages.php"}
        portal_headers = {"User-Agent": _BROWSER_UA, "Origin": base, "Referer": f"{base}/portal"}
        # PT 站走平台出站代理（与浏览器同出口 IP 以过 Cloudflare）；CookieCloud 是 LAN，禁代理直连
        ssl_ctx: ssl.SSLContext = make_ssl_ctx()
        async with (
            httpx.AsyncClient(verify=ssl_ctx, timeout=15) as portal_http,
            httpx.AsyncClient(timeout=15) as pt_http,
        ):
            before = set(latest_message_ids((await self._pt_get(pt_http, f"{PT_BASE}/messages.php", pt_headers)).text))

            resp = await portal_http.post(
                f"{base}/api/portal/auth/start", json={"hdskyUid": uid}, headers=portal_headers
            )
            data = self._json_or_raise(resp, "发送验证码")
            if not data.get("ok"):
                raise RenewError(f"发送验证码失败: {data.get('error', '未知')}")
            self._ctx.log.info("验证码已发送（用户 %s），等待站内信…", data.get("displayName", uid))

            code = await self._wait_for_code(pt_http, pt_headers, before)

            resp = await portal_http.post(
                f"{base}/api/portal/auth/verify", json={"hdskyUid": uid, "code": code}, headers=portal_headers
            )
            data = self._json_or_raise(resp, "验证码确认")
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

    @staticmethod
    def _json_or_raise(resp: httpx.Response, step: str) -> dict[str, Any]:
        """解析 JSON 响应，非 JSON 视为服务端异常。"""
        try:
            data: dict[str, Any] = resp.json()
            return data
        except Exception as e:
            raise RenewError(f"{step}：服务端返回非 JSON（HTTP {resp.status_code}）") from e

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


async def _fetch_cookiecloud(server: str, uuid: str, password: str) -> dict[str, Any]:
    """POST /cookiecloud/get/{uuid}（服务端解密）→ cookie_data。LAN 直连不走代理。"""
    async with httpx.AsyncClient(timeout=20, trust_env=False) as http:
        resp = await http.post(f"{server}/cookiecloud/get/{uuid}", json={"password": password})
    if resp.status_code != 200:
        raise RenewError(f"CookieCloud 请求失败（HTTP {resp.status_code}），检查地址/UUID/密钥")
    try:
        data: dict[str, Any] = resp.json()
    except Exception as e:
        raise RenewError("CookieCloud 返回非 JSON") from e
    if "detail" in data:
        raise RenewError(f"CookieCloud 错误: {data['detail']}")
    cd = data.get("cookie_data")
    if not isinstance(cd, dict):
        raise RenewError("CookieCloud 返回数据缺少 cookie_data")
    return cd


# ── 共享实例与看门狗 ─────────────────────────────────────────────

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
            if cfg.get("auth_auto_renew", True) and str(cfg.get("cc_uuid", "") or "").strip():
                cookie_file = str(cfg.get("hdsky_cookie_file", "") or DEFAULT_COOKIE_FILE)
                base = str(cfg.get("hdsky_base_url", "") or DEFAULT_BASE_URL)
                if not await session_alive(cookie_file, base):
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
    _task = asyncio.create_task(_watchdog(ctx))
    ctx.log.info("Cookie 自动续期看门狗已启动")


def stop(ctx: Any) -> None:
    """停止 Cookie 看门狗任务。"""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
    ctx.log.info("Cookie 自动续期看门狗已停止")
