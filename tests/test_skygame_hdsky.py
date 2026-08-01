# -*- coding: utf-8 -*-
# skyGame · HdskyClient 单元测试
#
# 覆盖：CSRF 失效判定、403「请求来源无效」自动刷新 CSRF 并重试一次、
# 非 CSRF 的 403 不重试、重试只发生一次不死循环（正向 + 异常路径）。

from __future__ import annotations

from typing import Any

import pytest

from plugins.skyGame.games.hdsky import HdskyClient, is_csrf_error


class _FakeResp:
    """模拟 httpx 响应：status_code + json()。"""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttp:
    """按调用顺序返回预设响应，记录每次请求的 method / url / CSRF 头。"""

    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        timeout: float | None = None,
    ) -> _FakeResp:
        headers = headers or {}
        self.calls.append({"method": method, "url": url, "csrf": headers.get("X-CSRF-Token")})
        if not self._responses:
            raise AssertionError("请求次数超出预设响应数量")
        return self._responses.pop(0)

    async def aclose(self) -> None:
        pass


def _make_client(responses: list[_FakeResp]) -> HdskyClient:
    """构造 HdskyClient 并把底层 httpx 换成假客户端（cookie 文件不存在即无 cookie）。"""
    client = HdskyClient(cookie_file="/nonexistent_cookie.txt", base_url="https://example.test")
    client._http = _FakeHttp(responses)
    return client


# ── is_csrf_error 判定 ──


def test_is_csrf_error_matches_portal_message() -> None:
    assert is_csrf_error({"ok": False, "error": "请求来源无效"}) is True


def test_is_csrf_error_matches_csrf_keyword() -> None:
    assert is_csrf_error({"error": "CSRF token invalid"}) is True


def test_is_csrf_error_rejects_other_errors() -> None:
    assert is_csrf_error({"error": "权限不足"}) is False
    assert is_csrf_error({}) is False
    assert is_csrf_error({"ok": True}) is False


# ── 403 CSRF 失效自动刷新重试 ──


@pytest.mark.asyncio
async def test_csrf_error_triggers_refresh_and_retry() -> None:
    """首次 POST 因 CSRF 失效被拒 → 重取 CSRF → 用新 token 重试成功。"""
    client = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),  # 初次取 CSRF
            _FakeResp(403, {"ok": False, "error": "请求来源无效"}),  # 首次 POST 被拒
            _FakeResp(200, {"ok": True, "csrfToken": "tok2"}),  # 刷新后重取 CSRF
            _FakeResp(200, {"ok": True, "result": {"ok": True}}),  # 重试成功
        ]
    )
    result = await client.post("/api/portal/horse/action", {"action": "walk"})
    assert result == {"ok": True, "result": {"ok": True}}
    posts = [c for c in client._http.calls if c["method"] == "POST"]
    # 两次 POST 使用了不同的 CSRF token，证明刷新生效
    assert [c["csrf"] for c in posts] == ["tok1", "tok2"]


@pytest.mark.asyncio
async def test_csrf_retry_only_once() -> None:
    """重试后仍是 CSRF 错误：只重试一次即返回，不死循环。"""
    client = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),
            _FakeResp(403, {"ok": False, "error": "请求来源无效"}),
            _FakeResp(200, {"ok": True, "csrfToken": "tok2"}),
            _FakeResp(403, {"ok": False, "error": "请求来源无效"}),  # 重试仍失败
        ]
    )
    result = await client.post("/api/portal/horse/action", {"action": "walk"})
    assert result == {"ok": False, "error": "请求来源无效"}
    posts = [c for c in client._http.calls if c["method"] == "POST"]
    assert len(posts) == 2  # 原始 + 一次重试，不再继续


@pytest.mark.asyncio
async def test_non_csrf_403_not_retried() -> None:
    """非 CSRF 的 403（如权限不足）不应触发 CSRF 刷新重试。"""
    client = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),
            _FakeResp(403, {"ok": False, "error": "权限不足"}),
        ]
    )
    result = await client.post("/api/portal/horse/action", {"action": "walk"})
    assert result == {"ok": False, "error": "权限不足"}
    posts = [c for c in client._http.calls if c["method"] == "POST"]
    assert len(posts) == 1  # 未重试
