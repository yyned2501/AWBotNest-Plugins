from __future__ import annotations

import asyncio
from typing import Any

from plugins_v2.juai_checkin import __plugin__, core


class _Storage:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    async def items(self) -> list[tuple[str, Any]]:
        return list(self.values.items())

    async def set(self, key: str, value: Any) -> None:
        self.values[key] = value


class _Log:
    def info(self, *args: Any) -> None:
        pass


class _Ctx:
    def __init__(self, config: dict[str, Any] | None = None, stored: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.storage = _Storage(stored)
        self.log = _Log()
        self.actions: dict[str, Any] = {}
        self.schedules: list[dict[str, Any]] = []
        self.tasks: list[asyncio.Task[Any]] = []

    def action(self, name: str) -> Any:
        def register(callback: Any) -> Any:
            self.actions[name] = callback
            return callback

        return register

    def create_task(self, awaitable: Any, *, name: str, **kwargs: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(awaitable, name=name)
        self.tasks.append(task)
        return task

    def schedule_cron(self, name: str, callback: Any, *, hour: int, minute: int) -> None:
        self.schedules.append({"name": name, "callback": callback, "hour": hour, "minute": minute})


def test_v2_metadata_keeps_schema_configuration() -> None:
    assert __plugin__["version"] == "2.0.2"
    assert __plugin__["plugin_api_version"] == 2
    assert __plugin__["resources"]["max_background_tasks"] == 8
    assert __plugin__["scope"] == "standalone"
    assert "render_mode" not in __plugin__
    assert __plugin__["requirements"] == ["httpx>=0.27", "beautifulsoup4>=4.12"]
    assert __plugin__["config_schema"]["accounts"]["fields"]["password"]["type"] == "password"


async def test_setup_loads_storage_and_registers_native_cron() -> None:
    ctx = _Ctx(
        {"auto_checkin": True, "checkin_interval_hours": 6, "checkin_minute": 7},
        {core.HISTORY_KEY: [{"time": "stored"}]},
    )

    await core.setup(ctx)

    assert core._stored(core.HISTORY_KEY) == [{"time": "stored"}]
    assert "run_now" in ctx.actions
    assert [(item["hour"], item["minute"]) for item in ctx.schedules] == [(0, 7), (6, 7), (12, 7), (18, 7)]
    await core.teardown(ctx)


async def test_persist_uses_managed_storage_task() -> None:
    ctx = _Ctx()
    await core.setup(ctx)

    core._save_done_emails(ctx, "2026-09-14", {"User@Example.com"})
    await asyncio.gather(*ctx.tasks)

    assert ctx.storage.values[core.DONE_TODAY_KEY] == {
        "date": "2026-09-14",
        "emails": ["user@example.com"],
    }
    await core.teardown(ctx)


async def test_browser_checkin_fallback_preserves_result_semantics() -> None:
    class Browser:
        async def run(self, url: str, action: Any, **kwargs: Any) -> dict[str, Any]:
            assert url == core.BASE_URL
            assert kwargs["cookies"] == "session=token"
            return {
                "status": {
                    "success": True,
                    "data": {"enabled": True, "stats": {"checked_in_today": True, "total_checkins": 8}},
                },
                "checkin": None,
                "self": {"success": True, "data": {"quota": 1_000_000}},
                "quota": {"success": True, "data": {"quota_per_unit": 500_000, "quota_display_type": "USD"}},
            }

    ctx = _Ctx()
    ctx.browser = Browser()

    result = await core._checkin_with_browser(ctx, {"cookie": "session=token", "user_id": "42"})

    assert result == {
        "ok": True,
        "already": True,
        "message": "今日已签到，累计签到 8 次 · 剩余 $2.00",
        "balance": 1_000_000,
    }
