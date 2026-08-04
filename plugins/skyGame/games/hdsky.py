# -*- coding: utf-8 -*-
# 天空游戏 · hdsky 门户 HTTP 客户端
#
# 把认证与传输细节全部收敛到 HdskyClient，游戏模块调用只需「接口 + 参数」：
#     async with HdskyClient(log=ctx.log) as client:
#         data = await client.get("/api/portal/horse")
#         r = await client.post("/api/portal/horse/action", {"action": "walk"})
#
# 内部负责：cookie 读取、CSRF 获取与定期刷新、自签证书、通用请求头、
# JSON 编解码、异常收敛（失败返回 {"_error": ...}，不抛给调用方）。
# 会话过期（HTTP 401）时若注入了 renewer，自动续期一次并重试原请求。

from __future__ import annotations

import datetime
import json
import os
import secrets
import ssl
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

# 全局配置缺省值（老配置升级后可能没有 hdsky_* 键，代码兜底）
# 平台跑在容器内，cookie 放数据卷挂载目录（宿主 appdata/awbotnest/data → 容器 /app/data）
DEFAULT_COOKIE_FILE = "/app/data/hdsky_cookie.txt"
DEFAULT_BASE_URL = "https://hdsky.supertimi.de:8443"
# 门户调试记录文件（JSONL）：仅当配置开启 hdsky_debug 时写入
DEFAULT_DEBUG_FILE = "/app/data/hdsky_debug.jsonl"

# CSRF 最长缓存时间（秒）：门户 token 会过期，超时自动重取
_CSRF_MAX_AGE = 1800


def request_key() -> str:
    """门户幂等键：web_ + 32 位 hex（与前端 createRequestKey 一致）。"""
    return "web_" + secrets.token_hex(16)


def is_csrf_error(data: dict[str, Any]) -> bool:
    """403 响应是否为 CSRF / 请求来源校验失败（重取 CSRF 后可恢复）。"""
    err = str(data.get("error", "") or "")
    return "请求来源" in err or "csrf" in err.lower() or "安全校验" in err


def read_portal_session(path: str) -> str | None:
    """从 Netscape cookie 文件读取 hdsky_portal_session（每次请求重读，支持原地续期）。"""
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


def make_ssl_ctx() -> ssl.SSLContext:
    """门户为自签证书，禁用校验。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# 调试文件超过该大小后轮转一次（覆盖旧 .1），避免无限增长
_DEBUG_MAX_BYTES = 10 * 1024 * 1024

# 调试记录需脱敏的字段名（小写匹配）：令牌/会话类值一律替换为 ***
_SENSITIVE_KEYS = {"csrftoken", "token", "cookie", "session", "authorization", "password"}


def _redact(value: Any) -> Any:
    """递归脱敏：敏感字段值替换为 ***，避免调试文件泄露凭证。"""
    if isinstance(value, dict):
        return {key: ("***" if str(key).lower() in _SENSITIVE_KEYS else _redact(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class _DebugRecorder:
    """把门户 API 的请求/响应追加写入 JSONL 调试文件，供事后核对实际请求。"""

    def __init__(self, path: str) -> None:
        self._path = path
        # 按 (method, path) 缓存上一次 response 原文，连续相同跳过
        self._last_response: dict[tuple[str, str], str | None] = {}

    def record(self, method: str, path: str, body: dict | None, response: dict[str, Any]) -> None:
        """追加一条记录；任何失败都静默，绝不影响插件主流程。"""
        try:
            key = (method, path)
            raw = json.dumps(
                {"request": _redact(body), "response": _redact(response)},
                ensure_ascii=False,
                sort_keys=True,
            )
            if self._last_response.get(key) == raw:
                return  # 内容与上一条相同，跳过
            self._last_response[key] = raw
            self._rotate_if_needed()
            entry = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "method": method,
                "path": path,
                "request": _redact(body),
                "response": _redact(response),
            }
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _rotate_if_needed(self) -> None:
        try:
            if os.path.getsize(self._path) > _DEBUG_MAX_BYTES:
                os.replace(self._path, self._path + ".1")
        except FileNotFoundError:
            pass


class HdskyClient:
    """hdsky 门户 API 客户端。长连接复用，支持热更新 cookie 路径与地址。"""

    def __init__(self, cookie_file: str = "", base_url: str = "", log: Any = None) -> None:
        self._cookie_file = cookie_file or DEFAULT_COOKIE_FILE
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._log = log
        self._csrf: str | None = None
        self._csrf_at: float = 0.0
        self._renewer: Callable[[], Awaitable[bool]] | None = None
        self._debug: _DebugRecorder | None = None
        self._http = httpx.AsyncClient(verify=make_ssl_ctx())

    async def __aenter__(self) -> HdskyClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层连接。"""
        await self._http.aclose()

    def configure(
        self,
        cookie_file: str,
        base_url: str,
        *,
        debug_enabled: bool = False,
        debug_file: str = "",
    ) -> None:
        """热更新连接参数（每轮轮询开头调用一次即可，值不变时无副作用）。"""
        self._cookie_file = cookie_file or DEFAULT_COOKIE_FILE
        base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        if base != self._base:
            self._base = base
            self.reset_csrf()
        self._debug = _DebugRecorder(debug_file or DEFAULT_DEBUG_FILE) if debug_enabled else None

    def reset_csrf(self) -> None:
        """作废缓存的 CSRF（接口报错或换站时调用，下次 POST 自动重取）。"""
        self._csrf = None
        self._csrf_at = 0.0

    def set_renewer(self, renewer: Callable[[], Awaitable[bool]] | None) -> None:
        """注入会话续期回调（无参，异步返回是否成功）。收到 401 时自动调用一次。"""
        self._renewer = renewer

    def _trace(self, method: str, path: str, body: dict | None, response: dict[str, Any]) -> None:
        """开启调试时记录一次请求/响应（脱敏后写入调试文件）。"""
        if self._debug is not None:
            self._debug.record(method, path, body, response)

    async def _ensure_csrf(self) -> None:
        """惰性获取 CSRF；过期自动刷新。"""
        if self._csrf and time.monotonic() - self._csrf_at < _CSRF_MAX_AGE:
            return
        sess = await self.get("/api/portal/session")
        self._csrf = sess.get("csrfToken") or None
        self._csrf_at = time.monotonic()

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        _retry: bool = False,
        _csrf_retry: bool = False,
    ) -> dict[str, Any]:
        """通用请求：拼认证头、编解码 JSON；任何异常收敛为 {"_error": ...}。"""
        headers: dict[str, str] = {
            "Origin": self._base,
            "Referer": f"{self._base}/portal",
        }
        cookie = read_portal_session(self._cookie_file)
        if cookie:
            headers["Cookie"] = f"hdsky_portal_session={cookie}"
        content: bytes | None = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            content = json.dumps(body or {}).encode()
            await self._ensure_csrf()
            if self._csrf:
                headers["X-CSRF-Token"] = self._csrf
        try:
            resp = await self._http.request(method, f"{self._base}{path}", headers=headers, content=content, timeout=10)
            if resp.status_code == 401 and not _retry:
                return await self._handle_expired(method, path, body)
            data = resp.json()
            # CSRF 失效：作废缓存重取一次后重试，避免持续失败。
            # 门户可能用 403 或 200+ok:false 两种方式返回 CSRF 错误，
            # 前者 ("请求来源无效") 已被 403 覆盖，后者 ("页面安全校验已失效") 需要额外判断。
            if not _csrf_retry and (resp.status_code == 403 or is_csrf_error(data)):
                if self._log:
                    self._log.debug("CSRF 校验失败(HTTP %s)，刷新后重试: %s", resp.status_code, path)
                self.reset_csrf()
                return await self._request(method, path, body, _retry=_retry, _csrf_retry=True)
            self._trace(method, path, body, data)
            return data
        except Exception as e:
            error = {"_error": str(e)}
            self._trace(method, path, body, error)
            return error

    async def _handle_expired(self, method: str, path: str, body: dict | None) -> dict[str, Any]:
        """会话过期（401）：有 renewer 则续期一次并重试，否则收敛为错误。"""
        if self._renewer is None:
            return {"_error": "门户 Cookie 已过期（未配置自动续期）"}
        if self._log:
            self._log.info("门户会话过期，尝试自动续期…")
        try:
            renewed = await self._renewer()
        except Exception as e:
            return {"_error": f"门户 Cookie 续期异常: {e}"}
        if not renewed:
            return {"_error": "门户 Cookie 已过期且自动续期失败"}
        self.reset_csrf()  # cookie 已换新，CSRF 一并重取
        return await self._request(method, path, body, _retry=True)

    async def get(self, path: str) -> dict[str, Any]:
        """GET 接口，返回 JSON dict。"""
        return await self._request("GET", path)

    async def post(self, path: str, body: dict | None = None) -> dict[str, Any]:
        """POST 接口：body 为参数字典，自动 JSON 编码并带 CSRF。"""
        return await self._request("POST", path, body)
