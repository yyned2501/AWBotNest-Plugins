# JUAI（juaiapi.com）签到 API

对象：`https://www.juaiapi.com`（new-api 系 AI 网关，React SPA，`<meta name="generator" content="new-api">`）。
用途：`plugins/juai_checkin.py` 每日签到。

## 鉴权模型（已确认）

- 登录后服务端通过 `Set-Cookie: session=<token>` 维持会话：`Path=/; Max-Age=2592000（30 天）; HttpOnly; Secure; SameSite=None`。
- `/api/user/checkin` 系列接口**同时**要求两样凭证，缺一即 401 语义错误（HTTP 200 + success:false）：
  1. 登录 `session` Cookie；
  2. 请求头 `New-Api-User: <登录响应 data.id>`。
- 只有 Cookie 无 `New-Api-User` 头 → `{"success": false, "message": "Unauthorized, New-Api-User header not provided"}`。
- 两者都无 → `{"success": false, "message": "Unauthorized, not logged in and no access token provided"}`。
- 浏览器登录成功后前端还会把整份 `data` 写入 `localStorage.user`（含 `id`），插件从这里抽 `New-Api-User`。

## 登录（已确认，2026-08-13 起强制 reCAPTCHA）

`POST /api/user/login`，`Content-Type: application/json`。

### reCAPTCHA v3（已确认）

`GET /api/status` 公开字段（2026-08-13 实测）：

- `recaptcha_check=true`
- `recaptcha_version=v3`
- `recaptcha_site_key=6LdqrSYtAAAAAB2y2I7P1sAj6DRd1KIOtyuPWo21`
- `turnstile_check=false`（未启用；`turnstile_site_key` 有值但前端不带）
- `user_agreement_enabled=true`、`privacy_policy_enabled=true`

前端 `LoginForm` + `Recaptcha` 模块已确认：

- token **不在 JSON body**，走查询串：`POST /api/user/login?recaptcha=<token>`（可选 `&turnstile=`）
- 生成：加载 `https://www.recaptcha.net/recaptcha/api.js?render=<siteKey>`，再 `grecaptcha.execute(siteKey, {action: "login"})`
- 无 token 或空字符串 → HTTP 200 + `{"success": false, "message": "reCAPTCHA token 为空"}`
- 服务端要的是浏览器里 Google 打分后的有效 v3 token，**不能靠纯 REST 伪造**

因此插件不直打登录接口，改为平台托管浏览器打开 `/login`，让前端自己 `grecaptcha.execute`，再抽出 `session` Cookie 给后续 REST。

### 请求体（已确认）

```json
{"username": "<注册邮箱>", "password": "<密码>"}
```

`username` 字段填邮箱。前端还会可选附带 `browser_fingerprint`（canvas/webgl/audio，`source:"web-login"`）；服务端是否强制该字段待验证，插件走浏览器登录时由前端自行带上。

### 浏览器登录页（已确认，2026-08-13 本地 CloakBrowser 实测调通）

`/login` 是 SPA 壳（HTML 仅约 1.6KB），控件全靠 JS 渲染。**登录卡片直接渲染在 `/login`**：
页面上同时有一段营销背景文案（`Home / Console / Model Marketplace / Sign in / Sign up`），
那是同页的装饰内容，**不需要点任何 Sign in**——`input[name="username"]`、`input[name="password"]`、
协议 checkbox、`button.login-btn-primary`（Continue）一开始就可见。之前误以为要先点 Sign in 进登录卡。

真正卡点（已确认）：协议 checkbox 是 Semi Design 组件，原生 `input[type="checkbox"]` 上盖了一层
`span.semi-checkbox-inner-display` 拦截指针事件，普通 `click()` / `.check()` 会被挡住超时，
导致 Continue 一直 `disabled`、登录超时。**必须对 input 用 `force=True` 点击**才能触发 React onChange。

实测可用的登录序列：
1. 打开 `/login`，等 networkidle + 约 2.5s 渲染。
2. `input[type="checkbox"]` 用 `click(force=True)` 勾上协议。
3. `input[name="username"]` / `input[name="password"]` 用真实键盘事件逐个输入。
4. 点 `button.login-btn-primary`（Continue）。
5. 成功：跳 `/console`，`localStorage.user = JSON.stringify(data)`，`Set-Cookie: session=<token>`。
   从 `localStorage.user.id` 抽 `New-Api-User`，从 cookie 抽 `session`。

登录接口响应体被加密（已确认）：`POST /api/user/login` 返回 `{"data": "<base64 加密串>"}`，
无明文 success/message。浏览器内部自行解密处理，插件不解析该响应，只抽 cookie + localStorage。
**但签到相关接口返回明文**：`GET /api/user/checkin`、`GET /api/user/self` 用 session + `New-Api-User`
请求均返回未加密 JSON（已实测），故签到/余额仍走 REST。

2FA：`data.require_2fa` 为真时出弹窗走 `POST /api/user/login/2fa`。当前配置账号未观察到；插件遇 2FA 文案明确失败，不盲重试。

`GET /api/status` 的 `recaptcha_check` 随站点配置开关：2026-08-13 早间 `true`（纯 REST 报 token 为空），
下午实测 `false`（登录 POST 不带 recaptcha 参数）。无论开关，浏览器登录都由前端自动处理 recaptcha，插件不依赖该开关。

### 成功响应（部分确认）

HTTP 响应体现已加密（见上），但登录成功后前端写入 `localStorage.user` 的是明文用户对象，
插件从这里抽 `id`。结构与早期明文响应一致：

```json
{
  "id": "<24 字符字符串，用作 New-Api-User 头>",
  "username": "...", "display_name": "...",
  "role": "...", "status": "...", "group": "..."
}
```

失败文案（密码错误、2FA 等）由前端解密后以 toast 呈现；无头环境插件改为读页面文本匹配
`用户名或密码错误 / 两步验证` 等关键词判断。鉴权只走 session Cookie，无 `access_token`。

### 待验证

- recaptcha v3 开关翻回 `true` 时，无头浏览器评分是否稳定过关（当前为 `false`，登录不带 token）。

## 查询签到状态（已确认）

`GET /api/user/checkin`，带 session Cookie + `New-Api-User` 头。

```json
{
  "success": true,
  "message": null,
  "data": {
    "enabled": true,
    "max_quota": 5000000,
    "min_quota": 500000,
    "stats": {
      "checked_in_today": true,
      "checkin_count": 3,
      "total_checkins": 4,
      "total_quota": 10467117,
      "records": [{"checkin_date": "2026-08-05", "quota_awarded": 1183945}]
    }
  }
}
```

- `enabled=false` 表示站点临时关闭签到功能。
- `max_quota`/`min_quota` 推断为单次签到可得额度的上下限（随机区间），未直接验证发放逻辑。
- `checkin_count` 与 `total_checkins` 语义差异未确认（前者疑似连续签到天数）。
- 插件用该接口探活缓存 session：`success=true` 视为仍有效，未登录文案视为失效并重走浏览器。

## 执行签到（部分确认）

`POST /api/user/checkin`，带 session Cookie + `New-Api-User` 头，请求体 `{}`。

- 重复签到（已确认）：`{"success": false, "message": "今日已签到"}`，插件按「已完成」幂等处理。
- 首次签到成功（待验证）：预期 `{"success": true, "data": {"quota_awarded": <int>}}`。
  字段名来自初版插件代码，当日签到已由其他途径完成、未能实测完整成功响应体；
  间接证据：状态接口 records 中当日 `quota_awarded` 已入账。插件对该字段做了缺失兜底。

## 额度单位换算（已确认）

`GET /api/status`（公开接口，无需鉴权）：

```json
{"success": true, "data": {"quota_per_unit": 500000, "quota_display_type": "USD"}}
```

- 内部额度值 ÷ `quota_per_unit` = 平台展示金额；本站 50 万额度 = $1（USD）。
- 插件每次运行读一次该接口，金额按 `$X.XX` 展示；接口异常时退回原始额度值。
- 同一接口现也承载 recaptcha / 协议开关（见登录章节）。

## 用户信息与剩余额度（已确认）

`GET /api/user/self`，带 session Cookie + `New-Api-User` 头。

返回完整用户对象（40+ 字段），插件只读 `data.quota`（剩余额度，内部单位）与 `data.used_quota`（累计已用）。
实测样例：`quota=9514057`（≈$19.03）、`used_quota=1116266403`（≈$2232.53）、`request_count=6873`。

## 其他

- 站点无 Cloudflare 拦截（直接 nginx 响应）。登录现强制 recaptcha，不能再靠多账号串行裸登。
- 前端入口 `/console/personal` 为 SPA 页面，签到按钮背后的请求即上述接口。
- `ctx.browser` 无状态：每次 `run` 起独立上下文用完即关。session 必须由插件抽 cookie 存 `ctx.kv`（`account_sessions`），下次 REST 自带。
