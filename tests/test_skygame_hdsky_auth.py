# -*- coding: utf-8 -*-
# skyGame · hdsky_auth 单元测试
#
# 覆盖：验证码抽取、收件箱 id 解析、PT cookie 头拼装、快照会话复用判断、
# Netscape cookie 写入/读回、续期器防抖与失败收敛（正向 + 异常路径）。

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from plugins.skyGame.games.hdsky import read_portal_session
from plugins.skyGame.games.hdsky_auth import (
    CookieRenewer,
    RenewError,
    build_pt_cookie_header,
    extract_code,
    latest_message_ids,
    portal_session_from_cloud,
    write_portal_cookie,
)


class FakeLog:
    """收集日志的桩，接口同 ctx.log。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, msg: str) -> None:
        self.records.append((level, msg))

    def debug(self, msg: str, *args: Any) -> None:
        self._add("debug", msg % args if args else msg)

    def info(self, msg: str, *args: Any) -> None:
        self._add("info", msg % args if args else msg)

    def warning(self, msg: str, *args: Any) -> None:
        self._add("warning", msg % args if args else msg)

    def error(self, msg: str, *args: Any) -> None:
        self._add("error", msg % args if args else msg)


class FakeCtx:
    """续期器测试桩：config / log / notify。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = {"auth_notify": False, **(config or {})}
        self.log = FakeLog()
        self.notified: list[tuple[str, str]] = []

    async def notify(self, msg: str, level: str = "info", **kwargs: Any) -> None:
        self.notified.append((msg, level))


# ── 纯函数：正向 ─────────────────────────────────────────────


def test_extract_code_from_message_page() -> None:
    html = '<td class="text">您好，本次登录验证码：<b>830964</b>，5 分钟内有效。</td>'
    assert extract_code(html) == "830964"


def test_extract_code_with_entities() -> None:
    html = "<div>验证码&#xFF1A;123456</div>"  # &#xFF1A; = 全角冒号
    assert extract_code(html) == "123456"


def test_latest_message_ids_ordered() -> None:
    html = (
        '<a href="messages.php?action=viewmessage&id=200">b</a><a href="messages.php?action=viewmessage&id=100">a</a>'
    )
    assert latest_message_ids(html) == ["200", "100"]


def test_build_pt_cookie_header() -> None:
    data = {
        "hdsky.me": [
            {"name": "c_secure_uid", "value": "aaa"},
            {"name": "c_secure_pass", "value": "bbb"},
        ],
        ".hdsky.me": [{"name": "cf_clearance", "value": "ccc"}],
        "other.com": [{"name": "x", "value": "y"}],
    }
    header = build_pt_cookie_header(data)
    assert header == "c_secure_uid=aaa; c_secure_pass=bbb; cf_clearance=ccc"


def test_portal_session_from_cloud_fresh() -> None:
    data = {
        "hdsky.supertimi.de": [
            {"name": "hdsky_portal_session", "value": "sess-value", "expirationDate": time.time() + 7200},
        ]
    }
    result = portal_session_from_cloud(data)
    assert result is not None
    value, remain = result
    assert value == "sess-value"
    assert remain > 3600


def test_write_portal_cookie_roundtrip(tmp_path: Any) -> None:
    path = tmp_path / "cookie.txt"
    write_portal_cookie(str(path), "new-session-xyz", 43200)
    assert read_portal_session(str(path)) == "new-session-xyz"
    assert (path.stat().st_mode & 0o777) == 0o600


# ── 纯函数：异常路径 ─────────────────────────────────────────


def test_extract_code_none_when_absent() -> None:
    assert extract_code("<td>没有码的普通站内信</td>") is None


def test_build_pt_cookie_header_empty() -> None:
    assert build_pt_cookie_header({"hdsky.me": []}) is None
    assert build_pt_cookie_header({}) is None


def test_portal_session_from_cloud_expired() -> None:
    data = {
        "hdsky.supertimi.de": [
            {"name": "hdsky_portal_session", "value": "old", "expirationDate": time.time() + 60},  # 剩余不足 1h
        ]
    }
    assert portal_session_from_cloud(data) is None
    assert portal_session_from_cloud({}) is None


# ── 续期器：防抖与失败收敛 ────────────────────────────────────


async def test_renew_failure_returns_false_and_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeCtx({"auth_notify": True, "cc_uuid": "u", "cc_password": "p"})
    renewer = CookieRenewer(ctx)
    calls = {"n": 0}

    async def boom(self: CookieRenewer) -> None:
        calls["n"] += 1
        raise RenewError("CookieCloud 请求失败（HTTP 500）")

    monkeypatch.setattr(CookieRenewer, "_do_renew", boom)

    assert await renewer.renew() is False
    assert calls["n"] == 1
    await asyncio.sleep(0)  # 让 _on_fail 里 create_task 的通知任务落地
    assert any("续期失败" in msg for msg, _ in ctx.notified)


async def test_renew_debounce_skips_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeCtx()
    renewer = CookieRenewer(ctx)
    calls = {"n": 0}

    async def count(self: CookieRenewer) -> None:
        calls["n"] += 1

    monkeypatch.setattr(CookieRenewer, "_do_renew", count)

    assert await renewer.renew() is True
    assert await renewer.renew() is False  # 10 分钟防抖窗口内，直接跳过
    assert calls["n"] == 1

    assert await renewer.renew(force=True) is True  # 手动触发跳防抖
    assert calls["n"] == 2


async def test_renew_missing_config_returns_false() -> None:
    ctx = FakeCtx({"cc_uuid": "", "cc_password": ""})  # 未配置 → RenewError → False
    renewer = CookieRenewer(ctx)
    assert await renewer.renew() is False
    assert any("未配置" in msg for level_msg in ctx.log.records for msg in [level_msg[1]])


# ── 门户网关瞬时故障重试（_portal_post）────────────────────────


class _FakePortalResp:
    """模拟 httpx 响应：payload 为 None 时 json() 抛错（模拟非 JSON 错误页）。"""

    def __init__(self, status_code: int, payload: dict[str, Any] | None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("非 JSON 响应")
        return self._payload


class _FakePortalHttp:
    """按调用顺序返回预设响应；可植入异常模拟连接失败。"""

    def __init__(self, results: list[_FakePortalResp | Exception]) -> None:
        self._results = list(results)
        self.calls = 0

    async def post(
        self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> _FakePortalResp:
        self.calls += 1
        if not self._results:
            raise AssertionError("请求次数超出预设响应数量")
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """替换 asyncio.sleep 记录退避秒数，测试不真实等待。"""
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


async def test_portal_post_retries_502_then_succeeds(no_sleep: list[float]) -> None:
    """发送验码首撞 502 网关错误页 → 退避重试 → 第二次成功（正向）。"""
    ctx = FakeCtx()
    renewer = CookieRenewer(ctx)
    http = _FakePortalHttp(
        [
            _FakePortalResp(502, None),  # 网关 HTML 错误页
            _FakePortalResp(200, {"ok": True, "displayName": "测试用户"}),
        ]
    )
    resp = await renewer._portal_post(http, "https://p/api/portal/auth/start", {"hdskyUid": "1"}, {}, "发送验证码")
    assert resp.json() == {"ok": True, "displayName": "测试用户"}
    assert http.calls == 2
    assert no_sleep == [3.0]
    assert any("重试" in msg for _, msg in ctx.log.records)


async def test_portal_post_retries_connect_error_then_succeeds(no_sleep: list[float]) -> None:
    """连接抖动（TransportError）同样退避重试后成功（正向）。"""
    ctx = FakeCtx()
    renewer = CookieRenewer(ctx)
    http = _FakePortalHttp(
        [
            httpx.ConnectError("connection refused"),
            _FakePortalResp(200, {"ok": True}),
        ]
    )
    resp = await renewer._portal_post(http, "https://p/api/portal/auth/verify", {"hdskyUid": "1"}, {}, "验证码确认")
    assert resp.json()["ok"] is True
    assert http.calls == 2
    assert any("连接失败" in msg for _, msg in ctx.log.records)


async def test_portal_post_persistent_502_raises_after_retries(no_sleep: list[float]) -> None:
    """持续 502 → 重试耗尽后抛 RenewError，错误信息带状态码与重试次数（异常）。"""
    ctx = FakeCtx()
    renewer = CookieRenewer(ctx)
    http = _FakePortalHttp([_FakePortalResp(502, None)] * 3)
    with pytest.raises(RenewError, match="HTTP 502.*已重试 3 次"):
        await renewer._portal_post(http, "https://p/api/portal/auth/start", {"hdskyUid": "1"}, {}, "发送验证码")
    assert http.calls == 3
    assert no_sleep == [3.0, 6.0]


async def test_portal_post_non_transient_non_json_no_retry(no_sleep: list[float]) -> None:
    """非 5xx 的非 JSON（如 403 HTML 错误页）视为明确失败：立即抛错不重试（异常）。"""
    ctx = FakeCtx()
    renewer = CookieRenewer(ctx)
    http = _FakePortalHttp([_FakePortalResp(403, None)])
    with pytest.raises(RenewError, match="服务端返回非 JSON（HTTP 403）"):
        await renewer._portal_post(http, "https://p/api/portal/auth/start", {"hdskyUid": "1"}, {}, "发送验证码")
    assert http.calls == 1
    assert no_sleep == []
