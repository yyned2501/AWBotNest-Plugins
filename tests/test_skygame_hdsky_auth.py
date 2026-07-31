# -*- coding: utf-8 -*-
# skyGame · hdsky_auth 单元测试
#
# 覆盖：验证码抽取、收件箱 id 解析、PT cookie 头拼装、快照会话复用判断、
# Netscape cookie 写入/读回、续期器防抖与失败收敛（正向 + 异常路径）。

from __future__ import annotations

import asyncio
import time
from typing import Any

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
