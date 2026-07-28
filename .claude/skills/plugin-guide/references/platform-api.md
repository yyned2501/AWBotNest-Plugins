# AWBotNest 平台开放 API（远程管理/调试插件）

平台提供 `X-API-Key` 鉴权的 REST API，供 AI 工具、脚本远程管理与调试插件。调试已安装插件时优先用它（启用/重载/读配置/读 KV/看日志），免去手动点控制台。

## 认证

请求头携带 API Key（二选一）：`X-API-Key: <key>` 或 `Api-Key: <key>`。

获取：Web 控制台 → 系统设置 →「通知」区 →「API_KEY」→ 点「随机」生成 → 保存。敏感信息，泄露立即重新生成。

## 基础

- 基础路径：`/api/v1`；请求/响应 JSON；UTF-8。
- 错误统一 `{"detail": "..."}`。状态码：400 参数错 / 401 Key 无效或缺失 / 404 资源不存在 / 500 内部错误 / 503 不可用（Key 未配置、插件未加载等）。

## 端点

### 插件管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plugins` | 列出所有插件（id/name/version/scope/enabled/loaded/has_config/webhook） |
| GET | `/plugins/{id}` | 插件详情（含 config_schema/changelog/render_mode） |
| GET | `/plugins/{id}/source` | 读插件源码（path/source/is_package） |
| ~~PUT~~ | ~~`/plugins/{id}/source`~~ | **已禁用**（改源码=远程执行代码，安全原因）。改代码走 Web 编辑器或直接改服务器文件 |
| POST | `/plugins/{id}/enable` | 启用 |
| POST | `/plugins/{id}/disable` | 停用 |
| POST | `/plugins/{id}/reload` | 重载 |

### 插件配置
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plugins/{id}/config` | 读配置 `{plugin_id, config}` |
| PUT | `/plugins/{id}/config` | 改配置，body `{"config": {...}}`，返回 `{ok, message, reloaded}`（更新并重载） |

### 插件 KV 存储
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plugins/{id}/kv` | 列出所有键 `{keys: [...]}` |
| GET | `/plugins/{id}/kv/{key}` | 读键 `{key, value}` |
| PUT | `/plugins/{id}/kv/{key}` | 设值，body `{"value": ...}` |
| DELETE | `/plugins/{id}/kv/{key}` | 删键 |

### 消息 / 会话 / 账号 / 日志 / 状态
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/messages/send` | 发消息，body `{chat_id, text, sender:"bot"\|"user", parse_mode:"HTML"\|"Markdown"}` |
| GET | `/chats/{chat_id}?session=账号名` | 会话信息 `{id, title, type}`（type: private/group/supergroup/channel/bot） |
| GET | `/accounts` | 列账号（type/session/name/connected） |
| GET | `/logs?limit=100` | 平台日志 |
| GET | `/logs/plugins/{id}?limit=100` | 某插件日志 |
| GET | `/status` | 平台状态（version/bot_connected/插件计数等） |

## 示例

```bash
# 列出插件
curl -H "X-API-Key: $KEY" http://localhost:18001/api/v1/plugins

# 重载插件（改完代码后）
curl -X POST -H "X-API-Key: $KEY" http://localhost:18001/api/v1/plugins/skyDropAnswer/reload

# 读插件某 KV 键
curl -H "X-API-Key: $KEY" http://localhost:18001/api/v1/plugins/skyDropAnswer/kv/count

# 发消息
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"chat_id":-1001234567890,"text":"Hello","sender":"bot"}' \
  http://localhost:18001/api/v1/messages/send
```

```python
import requests
API_BASE = "http://localhost:18001/api/v1"
headers = {"X-API-Key": "your_api_key_here", "Content-Type": "application/json"}
plugins = requests.get(f"{API_BASE}/plugins", headers=headers).json()["plugins"]
requests.post(f"{API_BASE}/plugins/my_feature/reload", headers=headers)
```

## 安全

不硬编码 Key（用环境变量）；生产用 HTTPS；不需公网就只监听 localhost；定期轮换。
