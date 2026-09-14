from typing import Any

from .core import setup as _core_setup
from .core import teardown as _core_teardown

__plugin__ = {
    "name": "JUAI 自动签到",
    "id": "juai_checkin",
    "version": "2.0.2",
    "author": "Yy",
    "description": "JUAI 自动签到（多账号）：每天分档重试，今日已成功自动跳过；登录 3 次重试，session 缓存 30 天。",
    "changelog": (
        "v2.0.2 更新：\n"
        "- 提高托管后台任务额度，避免签到收尾时并发保存 session、完成标记和历史记录触发上限\n"
        "v2.0.1 更新：\n"
        "- Docker 中 REST 请求经平台代理超时时，自动改用托管浏览器同源接口完成签到\n"
        "- 补充平台通知链路所需的 beautifulsoup4 依赖\n"
        "v2.0.0 更新：\n"
        "- 迁移到 AWBotNest V2 插件契约\n"
        "- 使用平台异步存储、托管后台任务和原生 cron 调度\n"
        "- 保留原有配置表单、浏览器登录、session 缓存和多账号签到行为"
    ),
    "icon": "https://www.juaiapi.com/favicon.png",
    "scope": "standalone",
    "default_enabled": False,
    "requirements": ["httpx>=0.27", "beautifulsoup4>=4.12"],
    "plugin_api_version": 2,
    "resources": {
        "timeout_seconds": 900,
        "max_concurrency": 2,
        "max_background_tasks": 8,
        "failure_threshold": 3,
        "recovery_seconds": 120,
    },
    "config_schema": {
        "auto_checkin": {
            "type": "boolean",
            "default": True,
            "label": "启用自动签到",
            "section": "功能开关",
            "cols": 4,
            "order": 1,
        },
        "notify": {
            "type": "boolean",
            "default": True,
            "label": "推送签到结果",
            "section": "功能开关",
            "cols": 4,
            "order": 2,
        },
        "accounts": {
            "type": "list",
            "default": [],
            "label": "签到账号",
            "item_label": "账号",
            "help": "逐个添加 juai 账号。首次登录走平台浏览器过 recaptcha，session 缓存约 30 天，之后签到走 REST。",
            "section": "账号",
            "cols": 12,
            "order": 10,
            "fields": {
                "email": {
                    "type": "string",
                    "label": "登录邮箱",
                    "help": "juai 注册邮箱。",
                },
                "password": {
                    "type": "password",
                    "label": "账户密码",
                    "help": "juai 登录密码。",
                },
            },
        },
        "checkin_interval_hours": {
            "type": "slider",
            "default": 6,
            "label": "重试间隔（小时）",
            "min": 1,
            "max": 12,
            "step": 1,
            "help": "每天从 0 点起每 N 小时重试一次；已成功账号自动跳过，全部成功则不再触发。默认 6 小时 → 每天 4 次",
            "section": "定时",
            "cols": 6,
            "order": 20,
        },
        "checkin_minute": {
            "type": "slider",
            "default": 7,
            "label": "触发分钟",
            "min": 0,
            "max": 59,
            "step": 1,
            "help": "每次触发时的分钟偏移（对所有重试档生效）",
            "section": "定时",
            "cols": 6,
            "order": 21,
        },
        "run_now": {
            "type": "action",
            "label": "立即签到",
            "action": "run_now",
            "section": "操作",
            "cols": 6,
            "order": 30,
        },
        "last_result": {
            "type": "info",
            "default": "尚未运行",
            "label": "最近结果",
            "section": "运行状态",
            "cols": 12,
            "order": 40,
        },
        "checkin_history": {
            "type": "info",
            "default": "暂无记录",
            "label": "最近签到记录",
            "section": "运行状态",
            "cols": 12,
            "order": 41,
        },
    },
}


async def setup(ctx: Any) -> None:
    await _core_setup(ctx)


async def teardown(ctx: Any) -> None:
    await _core_teardown(ctx)
