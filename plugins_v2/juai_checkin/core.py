# =============================================================================
# AWBotNest 插件：JUAI 自动签到
#
# 每日自动签到 juai（https://www.juaiapi.com）。登录已强制 reCAPTCHA v3，
# 用平台托管浏览器走一遍登录页让前端自己 grecaptcha.execute，抽出 30 天
# session 写入 ctx.storage；之后签到 / 余额仍走 REST。契约见 docs/juai-api.md。
#   1. 浏览器打开 /login → 勾协议 → 填账密 → 点「继续」过 recaptcha
#   2. 抽出 session Cookie + localStorage.user.id（New-Api-User）
#   3. GET  /api/user/checkin 查签到状态（需 session cookie + New-Api-User 头）
#   4. POST /api/user/checkin 执行签到；「今日已签到」错误视为已完成
#   5. GET  /api/user/self 读剩余额度；GET /api/status 读额度单位换算
#      （quota_per_unit=500000，quota_display_type=USD，即 50 万额度 = $1）
# 支持多账号列表、定时签到、手动触发、结果汇总（含每账号剩余额度）通知。
# =============================================================================

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://www.juaiapi.com"
LOGIN_URL = f"{BASE_URL}/login"
HISTORY_KEY = "checkin_history"
HISTORY_LIMIT = 30
SESSION_KEY = "account_sessions"
# 今日已成功账号集合，结构 {"date": "YYYY-MM-DD", "emails": ["a@x.com", ...]}；跨日自动失效
DONE_TODAY_KEY = "checkin_done_today"
REQUEST_TIMEOUT = 30.0
BROWSER_TIMEOUT = 240
LOGIN_WAIT_SECONDS = 45.0
# 平台浏览器登录偶发超时（页面渲染/recaptcha 时快时慢），失败自动重试
BROWSER_LOGIN_ATTEMPTS = 3
BROWSER_RETRY_INTERVAL = 10.0

_run_lock: asyncio.Lock | None = None
_background_tasks: set[asyncio.Task[dict[str, Any]]] = set()
_storage_tasks: set[asyncio.Task[Any]] = set()
_storage_state: dict[str, Any] = {}


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _masked_email(email: str) -> str:
    local, separator, domain = str(email or "").partition("@")
    if not separator:
        return (local[:2] + "***") if local else "未知账号"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def _configured_accounts(config: dict[str, Any]) -> list[dict[str, str]]:
    """从配置读取账号列表；兼容旧版单账号 email/password 字段。"""
    accounts: list[dict[str, str]] = []
    seen: set[str] = set()
    raw_accounts = config.get("accounts") or []
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip()
            password = str(item.get("password") or "")
            key = email.casefold()
            if email and password and key not in seen:
                seen.add(key)
                accounts.append({"email": email, "password": password})
    legacy_email = str(config.get("email") or "").strip()
    legacy_password = str(config.get("password") or "")
    if legacy_email and legacy_password and legacy_email.casefold() not in seen:
        accounts.append({"email": legacy_email, "password": legacy_password})
    return accounts


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _stored(key: str, default: Any = None) -> Any:
    return _storage_state.get(key, default)


def _persist(ctx: Any, key: str, value: Any) -> None:
    _storage_state[key] = value
    task = ctx.create_task(ctx.storage.set(key, value), name=f"juai-storage:{key}")
    _storage_tasks.add(task)
    task.add_done_callback(_storage_tasks.discard)


def _load_done_emails(ctx: Any, today: str) -> set[str]:
    """读今日已成功邮箱集合；日期不匹配（跨天）自动当作空集。"""
    raw = _stored(DONE_TODAY_KEY, {}) or {}
    if not isinstance(raw, dict) or raw.get("date") != today:
        return set()
    emails = raw.get("emails") or []
    if not isinstance(emails, list):
        return set()
    return {str(e).casefold() for e in emails if isinstance(e, str) and e}


def _save_done_emails(ctx: Any, today: str, emails: set[str]) -> None:
    normalized = {e.casefold() for e in emails if e}
    _persist(ctx, DONE_TODAY_KEY, {"date": today, "emails": sorted(normalized)})


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    """响应体解析为 dict；非 JSON 返回空 dict，由调用方按失败处理。"""
    try:
        data = resp.json()
    except (ValueError, httpx.DecodingError):
        return {}
    return data if isinstance(data, dict) else {}


_QUOTA_SYMBOLS = {"USD": "$", "CNY": "¥"}


def _format_quota(quota: int | float, per_unit: float, display_type: str) -> str:
    """内部额度值 → 平台实际单位的展示文本；换算系数未知时退回原始值。"""
    if per_unit > 0:
        symbol = _QUOTA_SYMBOLS.get(display_type, "")
        return f"{symbol}{quota / per_unit:,.2f}"
    return f"{quota:,.0f} 额度"


async def _fetch_quota_unit(client: httpx.AsyncClient) -> tuple[float, str]:
    """读 /api/status 的 quota_per_unit / quota_display_type（公开接口无需鉴权）。

    失败返回 (0, "")，调用方退回原始额度值展示。
    """
    try:
        data = _safe_json(await client.get("/api/status"))
    except httpx.HTTPError:
        return 0.0, ""
    status = data.get("data") or {}
    per_unit = status.get("quota_per_unit")
    display_type = str(status.get("quota_display_type") or "")
    if isinstance(per_unit, (int, float)) and per_unit > 0:
        return float(per_unit), display_type
    return 0.0, ""


async def _fetch_balance(client: httpx.AsyncClient, user_id: str) -> int | float | None:
    """读 /api/user/self 的剩余额度（quota）；失败返回 None，不阻断签到流程。"""
    try:
        data = _safe_json(await client.get("/api/user/self", headers={"New-Api-User": user_id}))
    except httpx.HTTPError:
        return None
    if not data.get("success"):
        return None
    quota = (data.get("data") or {}).get("quota")
    return quota if isinstance(quota, (int, float)) else None


def _page_text(page: Any, timeout_ms: int = 3_000) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=timeout_ms))
    except Exception:  # noqa: BLE001 - 兼容不同浏览器引擎
        try:
            return str(page.content())
        except Exception:  # noqa: BLE001
            return ""


def _current_url(page: Any) -> str:
    value = getattr(page, "url", "")
    return str(value() if callable(value) else value)


def _matching_locators(page: Any, selector: str) -> Iterator[Any]:
    try:
        locator = page.locator(selector)
        count = min(locator.count(), 20)
    except Exception:  # noqa: BLE001 - 页面切换时 locator 可能短暂失效
        return
    for index in range(count):
        try:
            yield locator.nth(index)
        except Exception:  # noqa: BLE001 - 尝试同一选择器的下一个元素
            continue


def _click_first_visible(page: Any, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        for candidate in _matching_locators(page, selector):
            try:
                if not candidate.is_visible(timeout=1_000):
                    continue
                candidate.click()
                return True
            except Exception:  # noqa: BLE001 - 尝试下一个可见元素或选择器
                continue
    return False


def _type_like_user(locator: Any, value: str) -> None:
    """触发真实键盘事件；React 受控表单不吃 Playwright.fill。"""
    locator.click(timeout=5_000)
    locator.press("Control+A")
    locator.type(str(value), delay=20, timeout=10_000)


def _wait_for_any_visible(page: Any, selectors: tuple[str, ...], timeout_ms: int = 20_000) -> Any:
    """等待 SPA 渲染出任一目标控件，返回第一个可见 locator。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for selector in selectors:
            for candidate in _matching_locators(page, selector):
                try:
                    if candidate.is_visible(timeout=500):
                        return candidate
                except Exception:  # noqa: BLE001 - SPA 导航过程中 locator 可能短暂失效
                    continue
        page.wait_for_timeout(500)
    return None


def _session_cookie(page: Any) -> str:
    try:
        context = getattr(page, "context", None)
        cookies = context.cookies() if context is not None else page.context.cookies()
        return "; ".join(
            f"{item['name']}={item['value']}" for item in cookies if item.get("name") and item.get("value")
        )
    except Exception:  # noqa: BLE001 - Cookie 抽取失败由调用方判无效会话
        return ""


def _page_user_id(page: Any) -> str:
    """从 localStorage.user 读登录成功后写入的 data.id。"""
    try:
        raw = page.evaluate("() => window.localStorage.getItem('user') || ''")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(raw, dict):
        return str(raw.get("id") or "")
    if not raw:
        return ""
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError):
        return ""
    if isinstance(data, dict):
        return str(data.get("id") or "")
    return ""


def _accept_agreement(page: Any) -> bool:
    """勾选用户协议 checkbox。返回是否勾上（或本就无需勾选）。

    Semi Design 的 checkbox 有一层 `semi-checkbox-inner-display` span 拦截指针事件，
    普通 click / .check() 会被挡住超时。必须 force click 原生 input 才能触发 React onChange。
    开关开启时前端会拦下未勾选的提交（Continue 保持 disabled）。
    """
    try:
        boxes = page.locator('input[type="checkbox"]')
        if boxes.count() == 0:
            return True  # 站点没放协议框，视为无需勾选
        boxes.first.click(force=True, timeout=5_000)
        page.wait_for_timeout(400)
        return True
    except Exception:  # noqa: BLE001 - 兜底用 JS 直接点
        pass
    try:
        return bool(
            page.evaluate(
                """() => {
                    const box = document.querySelector('input[type="checkbox"]');
                    if (!box) return true;
                    box.click();
                    return true;
                }"""
            )
        )
    except Exception:  # noqa: BLE001 - 站点未展示协议时无需处理
        return True


_USERNAME_SELECTORS = (
    'input[name="username"]',
    "#username",
    'input[placeholder*="用户名"]',
    'input[placeholder*="邮箱"]',
    'input[placeholder*="username" i]',
    'input[placeholder*="email" i]',
    "input.semi-input",
)
_PASSWORD_SELECTORS = (
    'input[name="password"]',
    "#password",
    'input[type="password"]',
)
# 登录卡片里的提交按钮（Semi Design，class 带 login-btn-primary）
_SUBMIT_SELECTORS = (
    "button.login-btn-primary",
    'button[type="submit"]',
)
_TWO_FA_MARKERS = ("两步验证", "require_2fa", "认证器应用")
_PASSWORD_ERROR_MARKERS = ("用户名或密码错误", "密码错误", "账号不存在", "账户不存在")
_RECAPTCHA_ERROR_MARKERS = ("reCAPTCHA token 为空", "reCAPTCHA 校验初始化失败")


def _login_error_from_text(text: str) -> str | None:
    if any(marker in text for marker in _TWO_FA_MARKERS):
        return "账号已开启两步验证，插件暂不支持，请先在网站关闭 2FA"
    if any(marker in text for marker in _PASSWORD_ERROR_MARKERS):
        return "用户名或密码错误"
    if any(marker in text for marker in _RECAPTCHA_ERROR_MARKERS):
        return "reCAPTCHA 校验失败，浏览器未能完成行为验证"
    if "请先阅读并同意" in text or "please read and agree" in text.casefold():
        return "未勾选用户协议，登录被前端拦截"
    return None


def _visible_clickables(page: Any) -> list[str]:
    """收集当前页可见按钮/链接文字，供失败摘要对照。"""
    labels: list[str] = []
    try:
        nodes = page.locator("button, a, [role='button']")
        count = min(nodes.count(), 40)
    except Exception:  # noqa: BLE001
        return labels
    for index in range(count):
        try:
            node = nodes.nth(index)
            if not node.is_visible(timeout=200):
                continue
            text = re.sub(r"\s+", " ", node.inner_text(timeout=800)).strip()
            if text:
                labels.append(text[:40])
        except Exception:  # noqa: BLE001
            continue
    return labels


def _page_debug(page: Any) -> str:
    text = re.sub(r"\s+", " ", _page_text(page, timeout_ms=2_000)).strip()
    click_text = " | ".join(_visible_clickables(page)[:12])
    return f"url={_current_url(page)} clicks=[{click_text}] text={text[:120]!r}"


def _browser_login(page: Any, email: str, password: str) -> dict[str, str]:
    """同步浏览器动作：登录并抽出 session + user_id。

    实测登录卡片直接渲染在 /login（营销文案只是同页背景，无需点 Sign in）。
    关键：Semi Design 协议 checkbox 会拦截普通点击，必须 force click，
    否则 Continue 一直 disabled、登录超时。recaptcha 由前端在提交时自动处理。
    """
    if hasattr(page, "set_default_timeout"):
        page.set_default_timeout(15_000)

    username_input = _wait_for_any_visible(page, _USERNAME_SELECTORS, timeout_ms=20_000)
    if username_input is None:
        raise RuntimeError(f"登录页未找到用户名输入框，页面可能已更新；{_page_debug(page)}")
    password_input = _wait_for_any_visible(page, _PASSWORD_SELECTORS, timeout_ms=10_000)
    if password_input is None:
        raise RuntimeError(f"登录页未找到密码输入框，页面可能已更新；{_page_debug(page)}")

    # 先勾协议再填表；force click 才能穿过 Semi 的 inner-display span
    _accept_agreement(page)
    _type_like_user(username_input, email)
    _type_like_user(password_input, password)

    submitted = _click_first_visible(page, _SUBMIT_SELECTORS)
    if not submitted:
        try:
            password_input.press("Enter")
            submitted = True
        except Exception:  # noqa: BLE001
            submitted = False
    if not submitted:
        raise RuntimeError(f"登录表单无法提交，网站页面可能已更新；{_page_debug(page)}")

    wait_until = time.monotonic() + LOGIN_WAIT_SECONDS
    while time.monotonic() < wait_until:
        error = _login_error_from_text(_page_text(page, timeout_ms=2_000))
        if error:
            raise RuntimeError(error)
        user_id = _page_user_id(page)
        cookie = _session_cookie(page)
        if user_id and cookie and ("session=" in cookie):
            return {"cookie": cookie, "user_id": user_id}
        page.wait_for_timeout(500)

    leftover = _login_error_from_text(_page_text(page, timeout_ms=2_000))
    if leftover:
        raise RuntimeError(leftover)
    raise RuntimeError(f"登录超时，未进入控制台；{_page_debug(page)}")


async def _session_alive(client: httpx.AsyncClient, user_id: str) -> bool:
    """用签到状态接口探活缓存 session；未登录 / 网络失败视为失效。"""
    if not user_id:
        return False
    try:
        data = _safe_json(await client.get("/api/user/checkin", headers={"New-Api-User": user_id}))
    except httpx.HTTPError:
        return False
    return bool(data.get("success"))


def _cached_session(sessions: dict[str, Any], email: str) -> dict[str, str] | None:
    raw = sessions.get(email.casefold())
    if not isinstance(raw, dict):
        return None
    cookie = str(raw.get("cookie") or "")
    user_id = str(raw.get("user_id") or "")
    if cookie and user_id:
        return {"cookie": cookie, "user_id": user_id}
    return None


async def _ensure_session(ctx: Any, email: str, password: str) -> dict[str, str]:
    """复用 kv 里的 session；失效或不存在则浏览器登录并写回。"""
    sessions = _stored(SESSION_KEY, {}) or {}
    if not isinstance(sessions, dict):
        sessions = {}
    cached = _cached_session(sessions, email)
    if cached:
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"Cookie": cached["cookie"]},
        ) as client:
            if await _session_alive(client, cached["user_id"]):
                ctx.log.info("[登录][%s] 复用缓存 session", _masked_email(email))
                return cached
        ctx.log.info("[登录][%s] 缓存 session 已失效，改走浏览器登录", _masked_email(email))

    browser = getattr(ctx, "browser", None)
    if browser is None:
        raise RuntimeError("平台托管浏览器不可用，无法完成 recaptcha 登录")

    masked = _masked_email(email)

    def action(page: Any) -> dict[str, str]:
        try:
            return _browser_login(page, email, password)
        except Exception:
            # 失败时留现场截图 + 可见控件清单，便于对照平台浏览器真实渲染
            try:
                shot_dir = getattr(ctx, "data_dir", None)
                if shot_dir is not None:
                    shot = Path(shot_dir) / f"login_fail_{email.casefold().replace('@', '_at_')}.png"
                    page.screenshot(path=str(shot))
                    ctx.log.warning("[登录][%s] 失败截图已存到插件数据目录：%s", masked, shot.name)
                ctx.log.warning("[登录][%s] 失败时页面：%s", masked, _page_debug(page))
            except Exception:  # noqa: BLE001 - 截图失败不影响抛错
                pass
            raise

    last_err: Exception | None = None
    for attempt in range(1, BROWSER_LOGIN_ATTEMPTS + 1):
        ctx.log.info("[登录][%s] 打开浏览器登录（第 %s/%s 次，过 recaptcha）", masked, attempt, BROWSER_LOGIN_ATTEMPTS)
        try:
            result = await browser.run(LOGIN_URL, action, headless=True, timeout=BROWSER_TIMEOUT)
            cookie = str((result or {}).get("cookie") or "")
            user_id = str((result or {}).get("user_id") or "")
            if cookie and user_id:
                sessions[email.casefold()] = {"cookie": cookie, "user_id": user_id}
                _persist(ctx, SESSION_KEY, sessions)
                ctx.log.info("[登录][%s] 已写入 session 缓存", masked)
                return {"cookie": cookie, "user_id": user_id}
            last_err = RuntimeError("浏览器登录未拿到有效会话")
        except Exception as exc:  # noqa: BLE001 - 单次失败收敛后重试
            last_err = exc
        if attempt < BROWSER_LOGIN_ATTEMPTS:
            ctx.log.warning(
                "[登录][%s] 第 %s 次浏览器登录失败，%s 秒后重试：%s",
                masked,
                attempt,
                int(BROWSER_RETRY_INTERVAL),
                last_err,
            )
            await asyncio.sleep(BROWSER_RETRY_INTERVAL)
    raise RuntimeError(f"浏览器登录重试 {BROWSER_LOGIN_ATTEMPTS} 次仍失败：{last_err}")


def _browser_checkin_action(page: Any, user_id: str) -> dict[str, Any]:
    return page.evaluate(
        """async ({ userId }) => {
            const headers = { 'New-Api-User': userId };
            const request = async (path, options = {}) => {
                const response = await fetch(path, { credentials: 'include', headers, ...options });
                try { return await response.json(); } catch { return {}; }
            };
            const status = await request('/api/user/checkin');
            let checkin = null;
            if (status?.success && status?.data?.enabled !== false && !status?.data?.stats?.checked_in_today) {
                checkin = await request('/api/user/checkin', {
                    method: 'POST',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: '{}',
                });
            }
            const self = await request('/api/user/self');
            const quota = await fetch('/api/status', { credentials: 'include' })
                .then(response => response.json())
                .catch(() => ({}));
            return { status, checkin, self, quota };
        }""",
        {"userId": user_id},
    )


async def _checkin_with_browser(ctx: Any, session: dict[str, str]) -> dict[str, Any]:
    browser = getattr(ctx, "browser", None)
    if browser is None:
        raise RuntimeError("平台托管浏览器不可用，无法执行浏览器签到兜底")

    def action(page: Any) -> dict[str, Any]:
        return _browser_checkin_action(page, session["user_id"])

    payload = await browser.run(
        BASE_URL,
        action,
        cookies=session["cookie"],
        headless=True,
        timeout=BROWSER_TIMEOUT,
    )
    payload = payload if isinstance(payload, dict) else {}
    status_data = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    checkin_data = payload.get("checkin") if isinstance(payload.get("checkin"), dict) else {}
    self_data = payload.get("self") if isinstance(payload.get("self"), dict) else {}
    quota_data = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
    unit_data = quota_data.get("data") if isinstance(quota_data.get("data"), dict) else {}
    per_unit = unit_data.get("quota_per_unit")
    per_unit = float(per_unit) if isinstance(per_unit, (int, float)) and per_unit > 0 else 0.0
    display_type = str(unit_data.get("quota_display_type") or "")

    if status_data.get("success"):
        data = status_data.get("data") if isinstance(status_data.get("data"), dict) else {}
        if not data.get("enabled", True):
            return {"ok": False, "already": False, "message": "站点当前未启用签到功能"}
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        if stats.get("checked_in_today"):
            total = stats.get("total_checkins")
            suffix = f"，累计签到 {total} 次" if isinstance(total, int) else ""
            item: dict[str, Any] = {"ok": True, "already": True, "message": f"今日已签到{suffix}"}
        elif checkin_data.get("success"):
            awarded = (checkin_data.get("data") or {}).get("quota_awarded")
            if isinstance(awarded, (int, float)):
                item = {
                    "ok": True,
                    "already": False,
                    "message": f"签到成功，获得 {_format_quota(awarded, per_unit, display_type)}",
                    "quota": awarded,
                }
            else:
                item = {"ok": True, "already": False, "message": "签到成功"}
        else:
            message = str(checkin_data.get("message") or "签到失败")
            if "已签到" in message:
                item = {"ok": True, "already": True, "message": f"今日已签到（{message}）"}
            else:
                item = {"ok": False, "already": False, "message": f"签到失败：{message}"}
    else:
        message = str(status_data.get("message") or "无法读取签到状态")
        item = {"ok": False, "already": False, "message": f"签到失败：{message}"}

    if self_data.get("success"):
        balance = (self_data.get("data") or {}).get("quota")
        if isinstance(balance, (int, float)):
            item["balance"] = balance
            item["message"] += f" · 剩余 {_format_quota(balance, per_unit, display_type)}"
    return item


async def _checkin_one(
    client: httpx.AsyncClient,
    user_id: str,
    per_unit: float = 0.0,
    display_type: str = "",
) -> dict[str, Any]:
    """单账号签到：查状态 → 未签到才 POST → 读剩余额度。客户端须已带 session Cookie。

    返回 {ok, already, message}，登录成功的账号另附 balance（剩余额度原始值）。
    """
    if not user_id:
        return {"ok": False, "already": False, "message": "登录成功但未返回用户 ID，接口可能已变更"}
    headers = {"New-Api-User": user_id}

    item: dict[str, Any]
    status_resp = await client.get("/api/user/checkin", headers=headers)
    status_data = _safe_json(status_resp)
    already = False
    if status_data.get("success"):
        checkin_data = status_data.get("data") or {}
        if not checkin_data.get("enabled", True):
            return {"ok": False, "already": False, "message": "站点当前未启用签到功能"}
        stats = checkin_data.get("stats") or {}
        if stats.get("checked_in_today"):
            total = stats.get("total_checkins")
            suffix = f"，累计签到 {total} 次" if isinstance(total, int) else ""
            item = {"ok": True, "already": True, "message": f"今日已签到{suffix}"}
            already = True
    if not already:
        checkin_resp = await client.post("/api/user/checkin", headers=headers, json={})
        checkin_data = _safe_json(checkin_resp)
        if checkin_data.get("success"):
            awarded = (checkin_data.get("data") or {}).get("quota_awarded")
            if isinstance(awarded, (int, float)):
                awarded_text = _format_quota(awarded, per_unit, display_type)
                item = {"ok": True, "already": False, "message": f"签到成功，获得 {awarded_text}", "quota": awarded}
            else:
                item = {"ok": True, "already": False, "message": "签到成功"}
        else:
            message = str(checkin_data.get("message") or "签到失败")
            if "已签到" in message:
                item = {"ok": True, "already": True, "message": f"今日已签到（{message}）"}
            else:
                item = {"ok": False, "already": False, "message": f"签到失败：{message}"}

    # 登录成功的账号都统计剩余额度（含签到失败/已签到），追加到结果文案
    balance = await _fetch_balance(client, user_id)
    if isinstance(balance, (int, float)):
        item["balance"] = balance
        item["message"] += f" · 剩余 {_format_quota(balance, per_unit, display_type)}"
    return item


async def _run(
    ctx: Any,
    source: str,
    only_accounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """完整签到流程：逐账号登录（缓存优先）→ REST 签到、记录历史、汇总通知。

    only_accounts=None 时从配置读全量账号（手动签到默认行为）；
    传入列表时仅处理列表内的账号（定时 tick 使用，已过滤掉今日已成功者）。
    任意账号本次成功（含“今日已签到”）都会刷新 kv 里的今日完成标记。
    """
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    if _run_lock.locked():
        return {"ok": False, "message": "已有签到任务正在运行，请稍后再试"}

    async with _run_lock:
        today = _today_key()
        done_emails = _load_done_emails(ctx, today)
        if only_accounts is None:
            accounts = _configured_accounts(dict(ctx.config or {}))
        else:
            accounts = list(only_accounts)
        if not accounts:
            result: dict[str, Any] = {"ok": False, "message": "请先添加至少一个 juai 签到账号"}
        else:
            ctx.log.info("开始%s签到，共 %s 个账号", source, len(accounts))
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT) as client:
                per_unit, display_type = await _fetch_quota_unit(client)
            account_results: list[dict[str, Any]] = []
            for index, account in enumerate(accounts, 1):
                email = account["email"]
                masked = _masked_email(email)
                ctx.log.info("[签到][%s/%s][%s] 开始", index, len(accounts), masked)
                try:
                    session = await _ensure_session(ctx, email, account["password"])
                    try:
                        async with httpx.AsyncClient(
                            base_url=BASE_URL,
                            timeout=REQUEST_TIMEOUT,
                            headers={"Cookie": session["cookie"]},
                        ) as client:
                            item = await _checkin_one(client, session["user_id"], per_unit, display_type)
                    except httpx.HTTPError as exc:
                        ctx.log.warning("[签到][%s] REST 请求失败，改用浏览器同源接口：%r", masked, exc)
                        item = await _checkin_with_browser(ctx, session)
                except Exception as exc:  # noqa: BLE001 - 登录/浏览器失败收敛到单账号结果
                    item = {"ok": False, "already": False, "message": f"登录失败：{exc}"}
                    ctx.log.error("[签到][%s] 登录失败：%r", masked, exc)
                account_results.append(item)
                if item["ok"]:
                    done_emails.add(email.casefold())
                ctx.log.info("[签到][%s] 结果：%s", masked, item["message"])

            _save_done_emails(ctx, today, done_emails)

            success_count = sum(1 for item in account_results if item["ok"])
            failed_count = len(account_results) - success_count
            summary = f"签到完成（{len(account_results)} 个账号）：成功 {success_count}，失败 {failed_count}"
            details = "\n".join(
                f"[{_masked_email(account['email'])}] {item['message']}"
                for account, item in zip(accounts, account_results, strict=True)
            )
            message = f"{summary}\n{details}"
            balances = [item["balance"] for item in account_results if isinstance(item.get("balance"), (int, float))]
            if len(balances) >= 2:
                message += f"\n账号剩余额度合计：{_format_quota(sum(balances), per_unit, display_type)}"
            result = {
                "ok": failed_count == 0,
                "partial": success_count > 0 and failed_count > 0,
                "message": message,
                "accounts": account_results,
            }

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        display = f"{stamp} · {result['message']}"
        record = {"time": stamp, **result}
        history = _stored(HISTORY_KEY, [])
        if not isinstance(history, list):
            history = []
        history = [*history, record][-HISTORY_LIMIT:]
        history_display = "\n\n".join(
            f"{item.get('time', '')} · {item.get('message', '')}" for item in reversed(history[-10:])
        )
        ctx.update_config(
            {
                "last_result": display,
                "checkin_history": history_display or "暂无记录",
            }
        )
        _persist(ctx, HISTORY_KEY, history)
        if ctx.config.get("notify", True):
            try:
                level = "success" if result["ok"] else ("warning" if result.get("partial") else "error")
                await ctx.notify(result["message"], level=level, category="JUAI 签到")
            except Exception as exc:  # noqa: BLE001 - 通知失败不改变签到结果
                ctx.log.warning("签到结果通知失败：%r", exc)
        ctx.log.info("%s", result["message"])
        return result


async def _scheduled_tick(ctx: Any) -> None:
    """定时入口：先过滤掉今日已成功账号，全部完成时直接跳过，不启动登录/接口/通知。"""
    today = _today_key()
    all_accounts = _configured_accounts(dict(ctx.config or {}))
    if not all_accounts:
        ctx.log.info("定时任务已触发：未配置签到账号，跳过")
        return
    done_emails = _load_done_emails(ctx, today)
    pending = [a for a in all_accounts if a["email"].casefold() not in done_emails]
    if not pending:
        ctx.log.info("定时任务已触发：今日 %s 个账号均已签到，本次跳过", len(all_accounts))
        return
    ctx.log.info("定时任务已触发：待签到 %s/%s 个账号", len(pending), len(all_accounts))
    await _run(ctx, "定时", only_accounts=pending)


async def setup(ctx: Any) -> None:
    global _run_lock
    _run_lock = asyncio.Lock()
    _storage_state.clear()
    _storage_state.update(dict(await ctx.storage.items()))

    @ctx.action("run_now")
    async def _run_now() -> dict[str, Any]:
        if not _configured_accounts(dict(ctx.config or {})):
            return {"ok": False, "message": "请先添加至少一个 juai 签到账号"}
        if _run_lock and _run_lock.locked():
            return {"ok": True, "message": "签到任务已在后台运行，请查看运行日志"}
        task = ctx.create_task(_run(ctx, "手动"), name="JUAI 手动签到")
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {"ok": True, "message": "签到已在后台开始，请查看运行日志"}

    if ctx.config.get("auto_checkin", True):
        interval = _bounded_int(ctx.config.get("checkin_interval_hours"), 6, 1, 12)
        minute = _bounded_int(ctx.config.get("checkin_minute"), 7, 0, 59)
        firing_hours = list(range(0, 24, interval))

        def _make_tick() -> Any:
            async def _tick() -> None:
                await _scheduled_tick(ctx)

            return _tick

        for hour in firing_hours:
            ctx.schedule_cron(
                f"JUAI 签到 {hour:02d}:{minute:02d}",
                _make_tick(),
                hour=hour,
                minute=minute,
            )
        hours_text = "/".join(f"{h:02d}" for h in firing_hours)
        ctx.log.info(
            "已注册分档重试签到：每天 %s 的第 %s 分（间隔 %s 小时），已成功账号自动跳过",
            hours_text,
            minute,
            interval,
        )
    else:
        ctx.log.info("自动签到未启用，仅保留手动签到")


async def teardown(ctx: Any) -> None:
    background_tasks = list(_background_tasks)
    for task in background_tasks:
        if not task.done():
            task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    if _storage_tasks:
        await asyncio.gather(*list(_storage_tasks), return_exceptions=True)
    _background_tasks.clear()
    _storage_tasks.clear()
    _storage_state.clear()
    ctx.log.info("JUAI 自动签到插件已停用")
