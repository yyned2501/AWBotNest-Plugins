# AWBotNest-Plugins — 项目上下文

此仓库是 AWBotNest 平台的官方插件市场仓库。每个插件遵守单文件/文件夹二形态、三段式契约。

## 目录结构

```
AWBotNest-Plugins/
├── plugins/              # 插件目录（7 个插件，与 manifest.json 一一对应）
│   ├── __init__.py       # 包标记（非插件）
│   ├── battleroyale/     # 大逃杀助手（v1.0.2）：大逃杀跟踪/结算通知/自动下注
│   ├── skyRedPacket/     # 天空红包（v2.5.3）：拼手气红包自动抢
│   ├── learning/         # 智能学习（v3.1.1）：学习聊天偏好，智能参与对话
│   ├── scratch.py        # 天空刮奖（v1.6.2）：刮刮乐自动挂机（单文件插件）
│   ├── skyDropAnswer/    # 天空答题（v2.1.5）：答题 + 定时触发一体化
│   ├── skyGame/          # 天空游戏（v1.27.0）：炸金花/养马/Cookie 续期统一入口
│   ├── juai_checkin.py   # JUAI 自动签到（v1.4.2）（单文件插件）
│   └── _TEMPLATE.py      # 插件开发模板（非插件，不在 manifest 中）
├── manifest.json          # 插件市场清单（登记上述 7 个插件的 id/version/path）
├── icons/                 # 插件图标（SVG，manifest icon 字段引用）
├── tests/                 # pytest 回归测试
├── pyproject.toml         # Python 项目配置（requires-python>=3.12，dev 组 ruff/pytest）
├── uv.lock                # 依赖锁定文件
├── README.md              # 项目说明
├── docs/                  # 从 AWBotNest 同步的平台文档与插件 API 文档
│   ├── PLUGIN_GUIDE.md    # 插件开发指南
│   ├── SPEC.md            # 平台完整规范
│   ├── API.md             # 平台 API 文档
│   ├── CLAUDE.md          # 平台同步的 Claude 指南
│   ├── juai-api.md        # juai 平台 API 文档
│   └── skyGame-hdsky-api.md  # HDSky 门户 API 文档
├── .clinerules            # 编码规则
└── AGENTS.md              # 本文件（代理行为指南）
```

## 关键行为准则

- **不改平台内核（AWBotNest 项目）**——这是插件仓库，不是平台仓库
- **改插件代码 → 必须同步改 `manifest.json` 的 `version`**（否则商店推送失效）
- **新插件先确认不在 manifest 里**，加进去；同时检查是否和已有插件 id 冲突
- **同步机制**：日常发布直接 `git push origin main`——`origin` 是 `github.com/yyned2501/AWBotNest-Plugins`（实例商店拉这个仓库，需在平台「插件仓库」列表里，即 `PLUGIN_REPOS`）；不是 fork 流程。`AWdress/AWBotNest-Plugins` 是平台文档所称的官方仓库（`docs/CLAUDE.md` 的 `repo_sync`），本仓库改动默认不进那里
- **scope 选择**：`user`（用户账号监听群消息）、`bot`（机器人回复命令）、`both`（两者都挂）

## 发布与部署链路

改完代码到实例上生效，按顺序走（开发机通常访问不到实例端口，第 3、4 步要么在能访问实例的机器上 curl，要么在控制台点）：

1. `manifest.json` 的 `version` 与插件 `__plugin__.__version__` **一起升**——平台按 manifest 版本判定更新，不升商店永不推
2. 带 Vue 配置前端的插件先构建：`cd plugins/<id>/frontend && npm run build`，并把 `frontend/dist/` 一起提交（平台加载的是构建产物，入口 `dist/assets/remoteEntry.js`）
3. `git push origin main` → 平台 `repo_sync` 默认**每 20 分钟**轮询商店，给已安装且版本变化的插件下载并热重载（绝不自动启用）
4. 不想等轮询：控制台接口（管理员登录态，**不吃 `X-API-Key`**）`GET /api/plugins/store?refresh=true` 手动刷新，再 `POST /api/plugins/store/download` 下载
5. 校验版本与运行：`curl -H "X-API-Key: <key>" http://<实例>:18001/api/v1/plugins/<id>` 看 `version`；只替换了本地文件没走商店时用 `POST /api/v1/plugins/<id>/reload`
6. 排错看插件日志：`GET /api/v1/logs/plugins/<id>?limit=100`

**开放 API 不下发源码**：`PUT /api/v1/plugins/{id}/source` 自平台 v1.1.2.2 起因远程执行风险返回 403（`docs/API.md`）。`/api/v1` 只有 enable/disable/reload/config/kv/消息/日志/状态；改源码只能走商店（push）或控制台的上传/GitHub 导入。

## 能力唯一化 —— 写新函数前先搜（防重复实现铁律）

同一个能力只允许有一个实现。AI 最容易犯的错不是写错，而是**忘了已经有人写过**：生成是上下文局部最优，写出第二份时没有任何东西会报错。本机项目群实测已出现同一功能 2–4 份不同签名的实现（`login` 两份分别返回 `tuple[bool,str,dict|None]` 与 `tuple[bool,str,str]`；`is_banned` 一份带缓存一份不带），改一处漏一处。

**写任何新函数前，先搜（按能力词搜，不按变量名）：**

```bash
rg -n "(def|async def) .{0,24}(fetch|request|login|parse|merge|send|download|update|notify)" --type py
rg -n "httpx\.|requests\.|aiohttp|sqlite3\.connect|create_engine" --type py   # 是否已有统一封装
rg -n "def <你要写的函数名>" --glob '!tests/**'                                  # 同名函数是否已存在
```

**判定：**

- **命中 → 复用**：需要变体就给原函数加参数 / 加分支，**不要复制改两行另开一份**
- **未命中 → 新建**：建完在本文件「能力表」补一行
- 要改原函数签名 → 先 `rg -n "<函数名>"` 找齐全部调用方，一次改完

**硬性规则：**

- 一个能力 = 一个模块里的一个函数；同名函数全项目只允许一份（测试桩 / 夹具除外，且须带 `_test` / `fake_` 前缀）
- 第三方库只在封装层 import：HTTP / 时间 / 日志 / JSON 一律走封装，禁裸 `httpx.AsyncClient(`、`requests.`、`time.sleep`、`print`
- **一个概念全项目用一个词**：`get` / `fetch` / `load` 只留一个；`user` 不要又写成 `member` / `account`。名字飘了搜索就命中不了，必然重造
- 新增 / 改名 / 删除公共函数，同步更新下表

**收尾自检（提交前）：** 本次新增了几个函数，就逐个问一遍「项目里已有同职责的实现吗」。有 → 合并，不留第二份。

**能力表（本项目唯一入口）**

| 能力 | 唯一入口 | 禁止写法 |
|---|---|---|
| 插件能力（HTTP / 存储 / 消息 / 日志） | `ctx.*`（见上文「ctx 能力速查」） | 插件内直连 httpx / sqlite3 / print |
