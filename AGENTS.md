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
│   ├── skyGame/          # 天空游戏（v1.16.26）：炸金花/养马/Cookie 续期统一入口
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
- **scope 选择**：`user`（用户账号监听群消息）、`bot`（机器人回复命令）、`both`（两者都挂）
- **同步机制**：直接操作远程 `AWdress/AWBotNest-Plugins` 仓库（不是 fork），确保本地 `origin` 指向正确
