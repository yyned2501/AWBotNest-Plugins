# -*- coding: utf-8 -*-
# juai_checkin 单元测试
#
# 覆盖：多账号配置解析（含旧版兼容）、邮箱打码、额度单位换算展示、
# 单账号签到全流程（未签到→成功 / 状态已签到 / POST 返回已签到 / 登录失败 /
# 签到失败 / 站点未启用签到 / 非 JSON 响应 / 余额读取失败降级）、
# _run 多账号汇总（含剩余额度合计）与网络异常收敛（正向 + 异常路径）。
# 签到契约见 docs/juai-api.md。

from __future__ import annotations

from typing import Any

import httpx
import pytest

from plugins.juai_checkin import (
    HISTORY_KEY,
    _bounded_int,
    _checkin_one,
    _configured_accounts,
    _fetch_quota_unit,
    _format_quota,
    _masked_email,
    _run,
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


_LOGIN_OK = {"success": True, "message": "", "data": {"id": "u-123", "username": "tester"}}
_LOGIN_FAIL = {"success": False, "message": "用户名或密码错误"}
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
# 单账号签到流程（正向 + 异常）
# ─────────────────────────────────────────────────────────────


async def test_checkin_one_success() -> None:
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_OK),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is False
    assert "签到成功，获得 $2.37" in result["message"]  # 按平台单位展示，不是原始额度值
    assert "剩余 $19.03" in result["message"]
    assert result["quota"] == 1183945
    assert result["balance"] == 9514057
    # 鉴权契约：登录用 username/password；checkin/self 带 New-Api-User 头
    assert client.calls[0]["json"] == {"username": "a@x.com", "password": "pw"}
    assert client.calls[1]["headers"]["New-Api-User"] == "u-123"
    assert client.calls[3]["headers"]["New-Api-User"] == "u-123"


async def test_checkin_one_already_in_status_skips_post() -> None:
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_ALREADY),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is True
    assert "累计签到 5 次" in result["message"]
    assert "剩余 $19.03" in result["message"]
    # 状态已签到则不再 POST，但仍读余额
    assert [c["method"] for c in client.calls] == ["POST", "GET", "GET"]


async def test_checkin_one_post_returns_already() -> None:
    # 状态接口漏报、POST 才告知已签到 → 仍视为成功（幂等）
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_ALREADY),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["already"] is True


async def test_checkin_one_login_failed() -> None:
    client = _FakeClient([("POST", "/api/user/login", _LOGIN_FAIL)])
    result = await _checkin_one(client, "a@x.com", "bad", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "登录失败" in result["message"]
    assert "用户名或密码错误" in result["message"]
    assert len(client.calls) == 1  # 登录失败不再请求后续接口


async def test_checkin_one_login_success_but_no_id() -> None:
    client = _FakeClient([("POST", "/api/user/login", {"success": True, "data": {}})])
    result = await _checkin_one(client, "a@x.com", "pw")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "用户 ID" in result["message"]


async def test_checkin_one_checkin_failed() -> None:
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_NOT_YET),
            ("POST", "/api/user/checkin", _CHECKIN_FAIL),
            ("GET", "/api/user/self", _SELF_OK),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "签到失败" in result["message"]
    assert "签到间隔过短" in result["message"]
    assert "剩余 $19.03" in result["message"]  # 签到失败也统计余额


async def test_checkin_one_site_disabled() -> None:
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_DISABLED),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "未启用签到" in result["message"]


async def test_checkin_one_balance_fetch_failed_degrades() -> None:
    # 余额接口失败不影响签到结果，只是文案里没有「剩余」
    client = _FakeClient(
        [
            ("POST", "/api/user/login", _LOGIN_OK),
            ("GET", "/api/user/checkin", _STATUS_ALREADY),
            ("GET", "/api/user/self", {"success": False, "message": "Unauthorized"}),
        ]
    )
    result = await _checkin_one(client, "a@x.com", "pw", PER_UNIT, DISPLAY_TYPE)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert "剩余" not in result["message"]
    assert "balance" not in result


async def test_checkin_one_non_json_response() -> None:
    client = _FakeClient([("POST", "/api/user/login", ValueError("not json"))])
    result = await _checkin_one(client, "a@x.com", "pw")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "登录失败" in result["message"]


# ─────────────────────────────────────────────────────────────
# _run 多账号汇总（正向 + 异常收敛）
# ─────────────────────────────────────────────────────────────


class _FakeKv:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.store[key] = value


class _FakeCtx:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.kv = _FakeKv()
        self.updated: dict[str, Any] = {}
        self.notifications: list[tuple[str, str]] = []
        self.logs: list[str] = []

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


def _patch_run_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """替换 _run_lock 与单位查询，避免真实网络请求。"""
    monkeypatch.setattr("plugins.juai_checkin._run_lock", None)

    async def fake_fetch_unit(client: Any) -> tuple[float, str]:
        return PER_UNIT, DISPLAY_TYPE

    monkeypatch.setattr("plugins.juai_checkin._fetch_quota_unit", fake_fetch_unit)


async def test_run_multi_account_summary_with_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _FakeCtx(
        {
            "accounts": [{"email": "a@x.com", "password": "p1"}, {"email": "b@x.com", "password": "p2"}],
            "notify": True,
        }
    )

    async def fake_checkin_one(
        client: Any, email: str, password: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        assert per_unit == PER_UNIT  # 单位信息已透传
        if email == "a@x.com":
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
        client: Any, email: str, password: str, per_unit: float = 0.0, display_type: str = ""
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
        client: Any, email: str, password: str, per_unit: float = 0.0, display_type: str = ""
    ) -> dict[str, Any]:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("plugins.juai_checkin._checkin_one", fake_checkin_one)
    _patch_run_env(monkeypatch)
    result = await _run(ctx, "测试")
    assert result["ok"] is False
    assert "网络请求失败" in result["accounts"][0]["message"]
    assert ctx.notifications == []  # notify=False 不通知
