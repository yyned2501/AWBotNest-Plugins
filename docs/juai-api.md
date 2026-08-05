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

## 登录（已确认）

`POST /api/user/login`，`Content-Type: application/json`

请求体：`{"username": "<注册邮箱>", "password": "<密码>"}`（username 字段填邮箱）。

成功响应（HTTP 200）：

```json
{
  "success": true,
  "message": "",
  "data": {
    "id": "<22 字符字符串，用作 New-Api-User 头>",
    "username": "...", "display_name": "...",
    "role": ..., "status": ..., "group": ...,
    "public_id": "...", "country": "...", "country_code": "...", "connect_tx": ...
  }
}
```

失败响应：`{"success": false, "message": "<错误文案>"}`（HTTP 仍为 200）。
响应体无 `access_token`（实测为 null），鉴权只走 session Cookie。

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

## 用户信息与剩余额度（已确认）

`GET /api/user/self`，带 session Cookie + `New-Api-User` 头。

返回完整用户对象（40+ 字段），插件只读 `data.quota`（剩余额度，内部单位）与 `data.used_quota`（累计已用）。
实测样例：`quota=9514057`（≈$19.03）、`used_quota=1116266403`（≈$2232.53）、`request_count=6873`。

## 其他

- 站点无 Cloudflare 拦截（直接 nginx 响应）；登录接口未观测到频率限制，多账号串行登录即可。
- 前端入口 `/console/personal` 为 SPA 页面，签到按钮背后的请求即上述接口。
