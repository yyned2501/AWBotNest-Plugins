# -*- coding: utf-8 -*-
# skyGame · HdskyClient 单元测试
#
# 覆盖：CSRF 失效判定、403「请求来源无效」自动刷新 CSRF 并重试一次、
# 非 CSRF 的 403 不重试、重试只发生一次不死循环（正向 + 异常路径）。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plugins.skyGame.games.hdsky import HdskyClient, _DebugRecorder, _redact, is_csrf_error


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


@pytest.fixture(autouse=True)
def _reset_shared_csrf() -> None:
    """CSRF 为进程级共享（类变量），每个测试前清空，避免跨测试残留。"""
    HdskyClient._csrf = None
    HdskyClient._csrf_at = 0.0


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
async def test_non_csrf_403_retried_once() -> None:
    """v1.16.2 起任何 403 都按疑似 CSRF 失效处理：刷新 CSRF 重试一次（无法单靠
    状态码区分 CSRF 403 与权限 403，防御性重试一次），重试仍 403 才返回错误。"""
    client = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),
            _FakeResp(403, {"ok": False, "error": "权限不足"}),
            _FakeResp(200, {"ok": True, "csrfToken": "tok2"}),  # 刷新后重取 CSRF
            _FakeResp(403, {"ok": False, "error": "权限不足"}),  # 重试仍是权限 403
        ]
    )
    result = await client.post("/api/portal/horse/action", {"action": "walk"})
    assert result == {"ok": False, "error": "权限不足"}
    posts = [c for c in client._http.calls if c["method"] == "POST"]
    assert len(posts) == 2  # 原始 + 一次重试，不再继续


@pytest.mark.asyncio
async def test_shared_csrf_across_instances_no_invalidation() -> None:
    """回归（用户报障）：CSRF 进程级共享——养马/炸金花两实例不再互相作废 token。

    门户只认「最近一次 GET /api/portal/session 的 token」（实测：新 GET 后旧 token
    立即 403「安全校验已失效」）。各实例独立缓存时，B 实例取 token 会作废 A 实例的，
    A 的 POST 全被 CSRF 屏蔽、重取又被作废，连续失败直至门户行动超时。共享缓存后
    B 复用 A 刚取的 token 不再 GET session，两实例 POST 用同一 token 稳定成功。
    """
    client_a = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),  # A 首次取 CSRF
            _FakeResp(200, {"ok": True, "result": {"ok": True}}),  # A POST 成功
        ]
    )
    client_b = _make_client(
        [
            _FakeResp(200, {"ok": True, "result": {"ok": True}}),  # B POST 成功（复用共享 token）
        ]
    )
    assert await client_a.post("/api/portal/horse/action", {"action": "walk"}) == {
        "ok": True,
        "result": {"ok": True},
    }
    assert await client_b.post("/api/portal/zhajinhua/action", {"action": "call"}) == {
        "ok": True,
        "result": {"ok": True},
    }
    # B 全程不再 GET session（预设仅 1 个响应，多 GET 会触发 _FakeHttp 断言）
    posts_a = [c for c in client_a._http.calls if c["method"] == "POST"]
    posts_b = [c for c in client_b._http.calls if c["method"] == "POST"]
    assert [c["csrf"] for c in posts_a] == ["tok1"]
    assert [c["csrf"] for c in posts_b] == ["tok1"]


@pytest.mark.asyncio
async def test_shared_csrf_reset_propagates_to_other_instance() -> None:
    """A 实例 CSRF 失效刷新后，B 实例复用新 token（共享 reset 跨实例传播）。"""
    client_a = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),  # A 取 CSRF
            _FakeResp(403, {"ok": False, "error": "请求来源无效"}),  # A POST 被拒
            _FakeResp(200, {"ok": True, "csrfToken": "tok2"}),  # A 刷新重取
            _FakeResp(200, {"ok": True, "result": {"ok": True}}),  # A 重试成功
        ]
    )
    assert await client_a.post("/api/portal/horse/action", {"action": "walk"}) == {
        "ok": True,
        "result": {"ok": True},
    }
    client_b = _make_client([_FakeResp(200, {"ok": True, "result": {"ok": True}})])
    assert await client_b.post("/api/portal/zhajinhua/action", {"action": "call"}) == {
        "ok": True,
        "result": {"ok": True},
    }
    posts_b = [c for c in client_b._http.calls if c["method"] == "POST"]
    assert [c["csrf"] for c in posts_b] == ["tok2"]


@pytest.mark.asyncio
async def test_403_non_json_response_still_triggers_csrf_retry() -> None:
    """回归：403 返回非 JSON（门户 HTML 错误页）时仍触发 CSRF 刷新重试。

    旧实现 `resp.json()` 在 403 检查前调用，非 JSON 响应直接抛异常落 `_error`，
    CSRF 恢复要等调用方下一轮 reset——重试被屏蔽一轮。改为解析失败视为空数据，
    403 状态码本身即疑似 CSRF 失效，照常刷新重试一次。
    """
    client = _make_client(
        [
            _FakeResp(200, {"ok": True, "csrfToken": "tok1"}),
            _FakeResp(403, {"ok": False, "error": "请求来源无效"}),  # 首次 POST 被拒
            _FakeResp(200, {"ok": True, "csrfToken": "tok2"}),  # 刷新后重取
            _FakeResp(200, {"ok": True, "result": {"ok": True}}),  # 重试成功
        ]
    )
    client._http._responses[1] = _FakeResp(403, "<html>Forbidden</html>")  # 非 JSON 403
    result = await client.post("/api/portal/horse/action", {"action": "walk"})
    assert result == {"ok": True, "result": {"ok": True}}
    posts = [c for c in client._http.calls if c["method"] == "POST"]
    assert [c["csrf"] for c in posts] == ["tok1", "tok2"]


# ── 调试记录：脱敏 / 追加 / 轮转 / 静默失败 ──


def test_redact_masks_sensitive_keys_and_recurses() -> None:
    data = {
        "csrfToken": "secret",
        "nested": {"token": "s2", "name": "Yy"},
        "list": [{"cookie": "c"}, {"ok": 1}],
    }
    out = _redact(data)
    assert out["csrfToken"] == "***"
    assert out["nested"]["token"] == "***"
    assert out["nested"]["name"] == "Yy"
    assert out["list"][0]["cookie"] == "***"
    assert out["list"][1]["ok"] == 1


def test_debug_recorder_appends_redacted_jsonl(tmp_path: Path) -> None:
    # 正向：逐条追加 JSONL，敏感字段脱敏
    f = tmp_path / "d.jsonl"
    rec = _DebugRecorder(str(f))
    rec.record("POST", "/api/portal/horse/action", {"action": "walk"}, {"ok": True, "result": {"csrfToken": "s"}})
    rec.record("GET", "/api/portal/horse", None, {"ok": True})

    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["method"] == "POST"
    assert first["path"] == "/api/portal/horse/action"
    assert first["request"] == {"action": "walk"}
    assert first["response"]["result"]["csrfToken"] == "***"


def test_debug_recorder_rotates_when_over_max(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 异常路径：超过大小上限先轮转为 .1 再写新记录
    from plugins.skyGame.games import hdsky as hdsky_mod

    monkeypatch.setattr(hdsky_mod, "_DEBUG_MAX_BYTES", 10)
    f = tmp_path / "d.jsonl"
    f.write_text("x" * 50 + "\n", encoding="utf-8")

    _DebugRecorder(str(f)).record("GET", "/api/portal/horse", None, {"ok": True})

    assert (tmp_path / "d.jsonl.1").exists()
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["path"] == "/api/portal/horse"


def test_debug_recorder_swallows_write_errors(tmp_path: Path) -> None:
    # 异常路径：目标是目录无法写入时静默吞掉，绝不抛出影响主流程
    _DebugRecorder(str(tmp_path)).record("GET", "/x", None, {"ok": True})


@pytest.mark.asyncio
async def test_client_traces_request_when_debug_enabled(tmp_path: Path) -> None:
    # 正向：开启调试后，客户端每次请求/响应落盘
    f = tmp_path / "d.jsonl"
    client = _make_client([_FakeResp(200, {"horse": {"balance": 123}})])
    client._debug = _DebugRecorder(str(f))

    result = await client.get("/api/portal/horse")

    assert result == {"horse": {"balance": 123}}
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["method"] == "GET"
    assert rec["response"] == {"horse": {"balance": 123}}


@pytest.mark.asyncio
async def test_client_does_not_trace_when_debug_disabled(tmp_path: Path) -> None:
    # 异常路径：configure 关闭调试 → 不落盘
    f = tmp_path / "d.jsonl"
    client = _make_client([_FakeResp(200, {"ok": True})])
    client.configure("/nonexistent_cookie.txt", "https://example.test", debug_enabled=False, debug_file=str(f))

    assert client._debug is None
    await client.get("/api/portal/horse")
    assert not f.exists()
