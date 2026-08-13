# -*- coding: utf-8 -*-
# juai_checkin 单元测试
#
# 覆盖：多账号配置解析（含旧版兼容）、邮箱打码、额度单位换算展示、
# 单账号签到全流程（缓存 session → 未签到/已签到/失败 / 站点未启用 / 非 JSON /
# 余额读取失败降级）、会话探活与复用、浏览器登录正反路径、
# _run 多账号汇总与网络/登录异常收敛（正向 + 异常路径）。
# 签到契约见 docs/juai-api.md。

from __future__ import annotations

from typing import Any

import httpx
import pytest

from plugins.juai_checkin import (
    HISTORY_KEY,
    LOGIN_URL,
    SESSION_KEY,
    _bounded_int,
    _browser_login,
    _checkin_one,
    _configured_accounts,
    _ensure_session,
    _fetch_quota_unit,
    _format_quota,
    _masked_email,
    _run,
    _session_alive,
)

# ─────────────────────────────────────────────────────────────
# 假 httpx 客户端：按预设顺序消费响应并记录请求
# ─────────────────────────────────────────────────────────────


class _FakeResp:
    """模拟 httpx 响应：payload 为 Exception 时 json() 抛出。"""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """每项预设：(method, path, payload)；顺序不符即断言失败。"""

    def __init__(self, responses: list[tuple[str, str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def _next(self, method: str, url: str, **extra: Any) -> _FakeResp:
        if not self._responses:
            raise AssertionError(f"请求次数超出预设：{method} {url}")
        exp_method, exp_path, payload = self._responses.pop(0)
        assert (method, url) == (exp_method, exp_path), f"请求顺序不符：{method} {url} ≠ {exp_method} {exp_path}"
        self.calls.append({"method": method, "url": url, **extra})
        return _FakeResp(payload)

    async def post(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> _FakeResp:
        return self._next("POST", url, json=json, headers=headers or {})

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResp:
        return self._next("GET", url, headers=headers or {})


class _AsyncCM:
    """把假客户端包成 async context manager，替掉 httpx.AsyncClient。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __aenter__(self) -> Any:
        return self._inner

    async def __aexit__(self, *args: Any) -> None:
        return None


_UNAUTHORIZED = {
    "success": False,
    "message": "Unauthorized, not logged in and no access token provided",
}
_RECAPTCHA_EMPTY = {"success": False, "message": "reCAPTCHA token 为空"}
_STATUS_NOT_YET = {
    "success": True,
    "message": None,
    "data": {"enabled": True, "stats": {"checked_in_today": False, "total_checkins": 4}},
}
_STATUS_ALREADY = {
    "success": True,
    "message": None,
    "data": {"enabled": True, "stats": {"checked_in_today": True, "total_checkins": 5}},
}
_STATUS_DISABLED = {"success": True, "message": None, "data": {"enabled": False, "stats": {}}}
_CHECKIN_OK = {"success": True, "message": None, "data": {"quota_awarded": 1183945}}
_CHECKIN_ALREADY = {"success": False, "message": "今日已签到"}
_CHECKIN_FAIL = {"success": False, "message": "签到间隔过短"}
_SELF_OK = {"success": True, "data": {"quota": 9514057}}
# 实测单位：quota_per_unit=500000，quota_display_type=USD（50 万额度 = $1）
PER_UNIT = 500000.0
DISPLAY_TYPE = "USD"


# ─────────────────────────────────────────────────────────────
# 配置解析与工具函数
# ─────────────────────────────────────────────────────────────


def test_configured_accounts_list_dedup() -> None:
    config: dict[str, Any] = {
        "accounts": [
            {"email": "a@x.com", "password": "p1"},
            {"email": "A@X.com", "password": "p2"},  # 与第一个同邮箱（大小写不同），去重
            {"email": "b@x.com", "password": "p3"},
            {"email": "", "password": "p4"},  # 空邮箱，丢弃
            {"email": "c@x.com", "password": ""},  # 空密码，丢弃
            "not-a-dict",  # 非法条目，丢弃
        ]
    }
    accounts = _configured_accounts(config)
    assert [a["email"] for a in accounts] == ["a@x.com", "b@x.com"]
    assert accounts[0]["password"] == "p1"  # 去重保留先出现的


def test_configured_accounts_legacy_single() -> None:
    # 旧版单账号字段兼容；列表已有同邮箱时不重复添加
    config: dict[str, Any] = {
        "accounts": [{"email": "a@x.com", "password": "p1"}],
        "email": "a@x.com",
        "password": "legacy",
    }
    assert len(_configured_accounts(config)) == 1
    legacy_only = _configured_accounts({"email": "old@x.com", "password": "legacy"})
    assert legacy_only == [{"email": "old@x.com", "password": "legacy"}]
    assert _configured_accounts({}) == []


def test_masked_email() -> None:
    assert _masked_email("yyned2501@gmail.com") == "yy***@gmail.com"
    assert _masked_email("ab@x.com") == "a***@x.com"
    assert _masked_email("no-at-sign") == "no***"
    assert _masked_email("") == "未知账号"


def test_bounded_int() -> None:
    assert _bounded_int(9, 0, 0, 23) == 9
    assert _bounded_int(99, 7, 0, 59) == 59
    assert _bounded_int(-3, 7, 0, 59) == 0
    assert _bounded_int("bad", 7, 0, 59) == 7
    assert _bounded_int(None, 7, 0, 59) == 7


def test_format_quota_by_unit() -> None:
    # 平台实际单位：500000 额度 = $1
    assert _format_quota(1183945, PER_UNIT, DISPLAY_TYPE) == "$2.37"
    assert _format_quota(500000, PER_UNIT, DISPLAY_TYPE) == "$1.00"
    assert _format_quota(1116266403, PER_UNIT, DISPLAY_TYPE) == "$2,232.53"
    assert _format_quota(100000, PER_UNIT, "CNY") == "¥0.20"
    # 换算系数未知 → 退回原始值
    assert _format_quota(1183945, 0.0, "") == "1,183,945 额度"


async def test_fetch_quota_unit_success_and_fallback() -> None:
    status_ok = {"success": True, "data": {"quota_per_unit": 500000, "quota_display_type": "USD"}}
    ok = _FakeClient([("GET", "/api/status", status_ok)])
    assert await _fetch_quota_unit(ok) == (PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    # 缺字段 / 网络错误 → (0, "") 由调用方退回原始额度展示
    empty = _FakeClient([("GET", "/api/status", {"success": True, "data": {}})])
    assert await _fetch_quota_unit(empty) == (0.0, "")  # type: ignore[arg-type]
    broken = _FakeClient([("GET", "/api/status", httpx.ConnectError("boom"))])
    assert await _fetch_quota_unit(broken) == (0.0, "")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────
# 单账号签到流程（正向 + 异常）——登录已拆到 _ensure_session
# ─────────────────────────────────────────────────────────────


async def test_checkin_one_success() -> None:
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_OK),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is False
    assert "签到成功，获得 $2.37" in result["message"]  # 按平台单位展示，不是原始额度值
    assert "剩余 $19.03" in result["message"]
    assert result["quota"] == 1183945
    assert result["balance"] == 9514057
    # 不再走 REST 登录；checkin/self 仍带 New-Api-User 头
    assert [c["method"] for c in client.calls] == ["GET", "POST", "GET"]
    assert client.calls[0]["url"] != "/api/user/login"
    assert client.calls[0]["headers"]["New-Api-User"] == "u-123"
    assert client.calls[2]["headers"]["New-Api-User"] == "u-123"


async def test_checkin_one_already_in_status_skips_post() -> None:
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_ALREADY),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is True
    assert "累计签到 5 次" in result["message"]
    assert "剩余 $19.03" in result["message"]
    # 状态已签到则不再 POST，但仍读余额
    assert [c["method"] for c in client.calls] == ["GET", "GET"]


async def test_checkin_one_post_returns_already() -> None:
    # 状态接口漏报、POST 才告知已签到 → 仍视为成功（幂等）
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_ALREADY),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is True


async def test_checkin_one_missing_user_id() -> None:
    result = await _checkin_one(_FakeClient([]), "")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "用户 ID" in result["message"]


async def test_checkin_one_checkin_failed() -> None:
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_FAIL),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "签到失败" in result["message"]
    assert "签到间隔过短" in result["message"]
    assert "剩余 $19.03" in result["message"]  # 签到失败也统计余额


async def test_checkin_one_site_disabled() -> None:
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_DISABLED),
        ]
    )
    result = await _checkin_one(client, "u-123")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "未启用签到" in result["message"]


async def test_checkin_one_balance_fetch_failed_degrades() -> None:
    # 余额接口失败不影响签到结果，只是文案里没有「剩余」
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", _STATUS_ALREADY),
            ("GET", "/api/user/self", {"success": False, "message": "Unauthorized"}),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert "剩余" not in result["message"]
    assert "balance" not in result


async def test_checkin_one_non_json_status_still_posts() -> None:
    # 状态接口非 JSON 时按未签到继续 POST，避免卡死
    client = _FakeClient(
        [
            ("GET", "/api/user/checkin", ValueError("not json")),
            ("POST", "/api/user/checkin", _CHECKIN_OK),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "u-123", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is False


# ─────────────────────────────────────────────────────────────
# 会话探活 / 缓存复用 / 失效重登
# ─────────────────────────────────────────────────────────────


async def test_session_alive_success() -> None:
    client = _FakeClient([("GET", "/api/user/checkin", _STATUS_NOT_YET)])
    assert await _session_alive(client, "u-123") is True  # type: ignore[arg-type]
    assert client.calls[0]["headers"]["New-Api-User"] == "u-123"


async def test_session_alive_unauthorized() -> None:
    client = _FakeClient([("GET", "/api/user/checkin", _UNAUTHORIZED)])
    assert await _session_alive(client, "u-123") is False  # type: ignore[arg-type]


async def test_session_alive_recaptcha_empty_is_dead() -> None:
    # 回归：登录口无 token 时站点返回该文案；探活也应视为未登录
    client = _FakeClient([("GET", "/api/user/checkin", _RECAPTCHA_EMPTY)])
    assert await _session_alive(client, "u-123") is False  # type: ignore[arg-type]


async def test_session_alive_network_error() -> None:
    client = _FakeClient([("GET", "/api/user/checkin", httpx.ConnectError("boom"))])
    assert await _session_alive(client, "u-123") is False  # type: ignore[arg-type]


class _FakeKv:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.store[key] = value


class _FakeBrowser:
    def __init__(self, result: dict[str, str] | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def run(self, url: str, action: Any, **kwargs: Any) -> Any:
        self.calls.append({"url": url, "action": action, **kwargs})
        if self.error:
            raise self.error
        return self.result


class _FakeCtx:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.kv = _FakeKv()
        self.updated: dict[str, Any] = {}
        self.notifications: list[tuple[str, str]] = []
        self.logs: list[str] = []
        self.browser: _FakeBrowser | None = None

        class _Log:
            def __init__(self, sink: list[str]) -> None:
                self._sink = sink

            def info(self, msg: str, *args: Any) -> None:
                self._sink.append(msg % args if args else msg)

            warning = error = info

        self.log = _Log(self.logs)

    def update_config(self, values: dict[str, Any]) -> None:
        self.updated.update(values)

    async def notify(self, message: str, level: str = "info", category: str = "") -> None:
        self.notifications.append((level, message))


def _patch_probe_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr("plugins.juai_checkin.httpx.AsyncClient", lambda *a, **k: _AsyncCM(client))


async def test_ensure_session_reuses_valid_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _FakeClient([("GET", "/api/user/checkin", _STATUS_ALREADY)])
    _patch_probe_client(monkeypatch, probe)
    ctx = _FakeCtx({})
    ctx.kv.set(SESSION_KEY, {"a@x.com": {"cookie": "session=old", "user_id": "u-123"}})
    ctx.browser = _FakeBrowser(result={"cookie": "session=new", "user_id": "u-999"})

    result = await _ensure_session(ctx, "a@x.com", "pw")
    assert result == {"cookie": "session=old", "user_id": "u-123"}
    assert ctx.browser.calls == []  # 缓存有效则不打开浏览器
    assert probe.calls[0]["url"] == "/api/user/checkin"


async def test_ensure_session_relogs_when_cache_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _FakeClient([("GET", "/api/user/checkin", _UNAUTHORIZED)])
    _patch_probe_client(monkeypatch, probe)
    ctx = _FakeCtx({})
    ctx.kv.set(SESSION_KEY, {"a@x.com": {"cookie": "session=old", "user_id": "u-123"}})
    ctx.browser = _FakeBrowser(result={"cookie": "session=new", "user_id": "u-999"})

    result = await _ensure_session(ctx, "a@x.com", "pw")
    assert result == {"cookie": "session=new", "user_id": "u-999"}
    assert len(ctx.browser.calls) == 1
    assert ctx.browser.calls[0]["url"] == LOGIN_URL
    saved = ctx.kv.get(SESSION_KEY)
    assert isinstance(saved, dict)
    assert saved["a@x.com"]["user_id"] == "u-999"
    assert saved["a@x.com"]["cookie"] == "session=new"


async def test_ensure_session_browser_when_no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_client(monkeypatch, _FakeClient([]))
    ctx = _FakeCtx({})
    ctx.browser = _FakeBrowser(result={"cookie": "session=fresh", "user_id": "u-1"})

    result = await _ensure_session(ctx, "b@x.com", "pw")
    assert result["cookie"] == "session=fresh"
    assert ctx.browser.calls[0]["url"] == LOGIN_URL
    # 无头、不注入旧 cookie，让前端自己打 recaptcha
    assert ctx.browser.calls[0].get("cookies") in (None, "")
    assert ctx.browser.calls[0]["headless"] is True


async def test_ensure_session_browser_missing() -> None:
    ctx = _FakeCtx({})
    ctx.browser = None
    with pytest.raises(RuntimeError, match="浏览器不可用"):
        await _ensure_session(ctx, "a@x.com", "pw")


async def test_ensure_session_browser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_client(monkeypatch, _FakeClient([]))
    ctx = _FakeCtx({})
    ctx.browser = _FakeBrowser(error=RuntimeError("用户名或密码错误"))
    with pytest.raises(RuntimeError, match="用户名或密码错误"):
        await _ensure_session(ctx, "a@x.com", "pw")


async def test_ensure_session_rejects_empty_browser_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_client(monkeypatch, _FakeClient([]))
    ctx = _FakeCtx({})
    ctx.browser = _FakeBrowser(result={"cookie": "", "user_id": ""})
    with pytest.raises(RuntimeError, match="有效会话"):
        await _ensure_session(ctx, "a@x.com", "pw")


# ─────────────────────────────────────────────────────────────
# 浏览器登录动作（同步 page 替身）
# ─────────────────────────────────────────────────────────────


class _Node:
    def __init__(
        self,
        *,
        kind: str = "input",
        text: str = "",
        visible: bool = True,
        enabled: bool = True,
        checked: bool = False,
        selectors: set[str] | None = None,
        on_click: Any = None,
    ) -> None:
        self.kind = kind
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.checked = checked
        self.selectors = selectors or set()
        self.on_click = on_click
        self.typed = ""
        self.clicks = 0
        self.pressed: list[str] = []

    def is_visible(self, timeout: int = 0) -> bool:
        return self.visible

    def is_enabled(self) -> bool:
        return self.enabled

    def is_checked(self) -> bool:
        return self.checked

    def inner_text(self, timeout: int = 0) -> str:
        return self.text

    def click(self, timeout: int = 0, force: bool = False) -> None:
        self.clicks += 1
        if self.on_click:
            self.on_click()

    def check(self, timeout: int = 0, force: bool = False) -> None:
        self.checked = True
        self.clicks += 1

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def type(self, value: str, delay: int = 0, timeout: int = 0) -> None:
        self.typed = value


class _LocatorList:
    def __init__(self, nodes: list[_Node]) -> None:
        self._nodes = nodes

    def count(self) -> int:
        return len(self._nodes)

    def nth(self, index: int) -> _Node:
        return self._nodes[index]

    @property
    def first(self) -> "_LocatorList":
        return _LocatorList(self._nodes[:1])

    def click(self, timeout: int = 0, force: bool = False) -> None:
        if self._nodes:
            self._nodes[0].click(timeout=timeout, force=force)

    def is_visible(self, timeout: int = 0) -> bool:
        return bool(self._nodes) and self._nodes[0].visible

    def inner_text(self, timeout: int = 0) -> str:
        if not self._nodes:
            return ""
        return self._nodes[0].inner_text(timeout=timeout)


class _ScriptedPage:
    """足够支撑 _browser_login 的同步 page 替身。

    模拟实测页面：登录卡片直接在 /login 渲染，含 username/password 输入框、
    Semi Design 协议 checkbox、login-btn-primary 提交按钮。
    """

    def __init__(self, *, after_submit: str = "ok", has_checkbox: bool = True) -> None:
        self.url = "https://www.juaiapi.com/login"
        self._body = "登 录"
        self._user_json = ""
        self._cookies: list[dict[str, str]] = []
        self._after_submit = after_submit
        self.username = _Node(
            selectors={'input[name="username"]', "#username", 'input[placeholder*="username" i]'},
            visible=True,
        )
        self.password = _Node(
            selectors={'input[name="password"]', "#password", 'input[type="password"]'},
            visible=True,
        )
        self.agree = _Node(
            kind="checkbox",
            checked=False,
            selectors={'input[type="checkbox"]'},
            on_click=lambda: setattr(self.agree, "checked", True),
        )
        self._has_checkbox = has_checkbox
        # 提交按钮：新流程按选择器 button.login-btn-primary 匹配
        self.continue_btn = _Node(
            kind="button",
            text="Continue",
            selectors={"button.login-btn-primary", 'button[type="submit"]'},
            on_click=self._submit,
        )
        self.context = self

    def cookies(self) -> list[dict[str, str]]:
        return list(self._cookies)

    def _submit(self) -> None:
        if self._after_submit == "ok":
            self.url = "https://www.juaiapi.com/console"
            self._user_json = '{"id":"u-123","username":"tester"}'
            self._cookies = [{"name": "session", "value": "tok"}]
            self._body = "控制台"
        elif self._after_submit == "2fa":
            self._body = "两步验证 请输入认证器应用显示的验证码"
        elif self._after_submit == "bad_password":
            self._body = "用户名或密码错误"
        elif self._after_submit == "recaptcha":
            self._body = "reCAPTCHA token 为空"
        # timeout：什么都不改，等 LOGIN_WAIT_SECONDS

    def locator(self, selector: str) -> _LocatorList:
        if selector == 'input[type="checkbox"]':
            return _LocatorList([self.agree] if self._has_checkbox else [])
        if selector in ("button.login-btn-primary", 'button[type="submit"]'):
            return _LocatorList([self.continue_btn])
        if selector == "body":
            return _LocatorList([_Node(text=self._body, visible=True)])
        if selector == "button, a, [role='button']":
            return _LocatorList([self.continue_btn])
        nodes = [self.username, self.password]
        return _LocatorList([n for n in nodes if selector in n.selectors and n.visible])

    def evaluate(self, script: str, *args: Any) -> Any:
        if "localStorage.getItem" in script and "user" in script:
            return self._user_json
        if "querySelector('input[type=\"checkbox\"]')" in script:
            self.agree.checked = True
            return True
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None


def test_browser_login_success() -> None:
    page = _ScriptedPage(after_submit="ok")
    result = _browser_login(page, "a@x.com", "pw")
    assert result["user_id"] == "u-123"
    assert result["cookie"] == "session=tok"
    assert page.username.typed == "a@x.com"
    assert page.password.typed == "pw"
    # 协议 checkbox 被勾上（force click 穿过 Semi 的拦截层）
    assert page.agree.checked is True
    assert page.continue_btn.clicks == 1


def test_browser_login_no_checkbox_still_works() -> None:
    # 站点未启用协议时没有 checkbox，登录照常
    page = _ScriptedPage(after_submit="ok", has_checkbox=False)
    result = _browser_login(page, "a@x.com", "pw")
    assert result["user_id"] == "u-123"
    assert page.continue_btn.clicks == 1


def test_browser_login_2fa() -> None:
    page = _ScriptedPage(after_submit="2fa")
    with pytest.raises(RuntimeError, match="两步验证"):
        _browser_login(page, "a@x.com", "pw")


def test_browser_login_bad_password() -> None:
    page = _ScriptedPage(after_submit="bad_password")
    with pytest.raises(RuntimeError, match="用户名或密码错误"):
        _browser_login(page, "a@x.com", "pw")


def test_browser_login_recaptcha_failed() -> None:
    page = _ScriptedPage(after_submit="recaptcha")
    with pytest.raises(RuntimeError, match="reCAPTCHA"):
        _browser_login(page, "a@x.com", "pw")


def test_browser_login_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("plugins.juai_checkin.LOGIN_WAIT_SECONDS", 0.2)
    page = _ScriptedPage(after_submit="timeout")
    with pytest.raises(RuntimeError, match="登录超时"):
        _browser_login(page, "a@x.com", "pw")


# ─────────────────────────────────────────────────────────────
# _run 多账号汇总（正向 + 异常收敛）
# ─────────────────────────────────────────────────────────────


def _patch_run_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """替换 _run_lock、单位查询与会话获取，避免真实网络/浏览器。"""
    monkeypatch.setattr("plugins.juai_checkin._run_lock", None)

    async def fake_fetch_unit(client: Any) -> tuple[float, str]:
        return PER_UNIT, DISPLAY_TYPE

    monkeypatch.setattr("plugins.juai_checkin._fetch_quota_unit", fake_fetch_unit)

    async def fake_ensure_session(ctx: Any, email: str, password: str) -> dict[str, str]:
        return {"cookie": f"session={email}", "user_id": email}

    monkeypatch.setattr("plugins.juai_checkin._ensure_session", fake_ensure_session)


async def test_run_multi_account_summary_with_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx(
        {
            "accounts": [{"email": "a@x.com", "password": "p1"}, {"email": "b@x.com", "password": "p2"}],
            "notify": True,
        }
    )

    async def fake_checkin_one(
        client: Any, user_id: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        assert per_unit == PER_UNIT  # 单位信息已透传
        if user_id == "a@x.com":
            return {"ok": True, "already": False, "message": "签到成功 · 剩余 $2.00", "balance": 1000000}
        # 签到失败但登录成功 → 仍有余额统计
        return {"ok": False, "already": False, "message": "签到失败：网络异常 · 剩余 $1.00", "balance": 500000}

    monkeypatch.setattr("plugins.juai_checkin._checkin_one", fake_checkin_one)
    _patch_run_env(monkeypatch)

    result = await _run(ctx, "测试")
    assert result["ok"] is False
    assert result["partial"] is True
    assert "成功 1，失败 1" in result["message"]
    assert "[a***@x.com]" in result["message"]
    assert "[b***@x.com]" in result["message"]
    # 多账号剩余额度合计（$2.00 + $1.00）
    assert "账号剩余额度合计：$3.00" in result["message"]
    # 部分成功 → warning 级通知
    assert ctx.notifications and ctx.notifications[0][0] == "warning"
    # 历史与状态落盘
    history = ctx.kv.get(HISTORY_KEY)
    assert isinstance(history, list) and len(history) == 1
    assert "·" in ctx.updated["last_result"]
    assert ctx.updated["checkin_history"]


async def test_run_single_account_no_total_line(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx({"accounts": [{"email": "a@x.com", "password": "p1"}]})

    async def fake_checkin_one(
        client: Any, user_id: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        return {"ok": True, "already": True, "message": "今日已签到 · 剩余 $3.00", "balance": 1500000}

    monkeypatch.setattr("plugins.juai_checkin._checkin_one", fake_checkin_one)
    _patch_run_env(monkeypatch)

    result = await _run(ctx, "测试")
    assert result["ok"] is True
    assert "账号剩余额度合计" not in result["message"]  # 单账号不重复合计


async def test_run_no_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx({"accounts": []})
    _patch_run_env(monkeypatch)
    result = await _run(ctx, "测试")
    assert result["ok"] is False
    assert "添加至少一个" in result["message"]
    # 无账号也会走通知分支（error 级），提醒用户补配置
    assert ctx.notifications and ctx.notifications[0][0] == "error"


async def test_run_network_error_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx({"accounts": [{"email": "a@x.com", "password": "p1"}], "notify": False})

    async def fake_checkin_one(
        client: Any, user_id: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("plugins.juai_checkin._checkin_one", fake_checkin_one)
    _patch_run_env(monkeypatch)
    result = await _run(ctx, "测试")
    assert result["ok"] is False
    assert "网络请求失败" in result["accounts"][0]["message"]
    assert ctx.notifications == []  # notify=False 不通知


async def test_run_login_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx({"accounts": [{"email": "a@x.com", "password": "p1"}]})

    async def fake_ensure_session(ctx: Any, email: str, password: str) -> dict[str, str]:
        raise RuntimeError("reCAPTCHA token 为空")

    async def fake_checkin_one(
        client: Any, user_id: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        raise AssertionError("登录失败不应再签到")

    monkeypatch.setattr("plugins.juai_checkin._run_lock", None)

    async def fake_fetch_unit(client: Any) -> tuple[float, str]:
        return PER_UNIT, DISPLAY_TYPE

    monkeypatch.setattr("plugins.juai_checkin._fetch_quota_unit", fake_fetch_unit)
    monkeypatch.setattr("plugins.juai_checkin._ensure_session", fake_ensure_session)
    monkeypatch.setattr("plugins.juai_checkin._checkin_one", fake_checkin_one)

    result = await _run(ctx, "测试")
    assert result["ok"] is False
    assert "登录失败" in result["accounts"][0]["message"]
    assert "reCAPTCHA token 为空" in result["accounts"][0]["message"]
