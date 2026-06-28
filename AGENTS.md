# AWBotNest-Plugins — 项目上下文

此仓库是 AWBotNest 平台的官方插件市场仓库。每个插件遵守单文件/文件夹二形态、三段式契约。

## 目录结构

```
AWBotNest-Plugins/
├── plugins/              # 插件目录（当前为空，等待新插件加入）
├── manifest.json          # 插件市场清单（当前为空）
├── README.md              # 项目说明
├── docs/                  # 从 AWBotNest 同步的平台文档
│   ├── PLUGIN_GUIDE.md    # 插件开发指南
│   └── SPEC.md            # 平台完整规范
├── .clinerules            # 编码规则
└── AGENTS.md              # 本文件（代理行为指南）
```

## 关键行为准则

- **不改平台内核（AWBotNest 项目）**——这是插件仓库，不是平台仓库
- **改插件代码 → 必须同步改 `manifest.json` 的 `version`**（否则商店推送失效）
- **新插件先确认不在 manifest 里**，加进去；同时检查是否和已有插件 id 冲突
- **scope 选择**：`user`（用户账号监听群消息）、`bot`（机器人回复命令）、`both`（两者都挂）
- **同步机制**：直接操作远程 `AWdress/AWBotNest-Plugins` 仓库（不是 fork），确保本地 `origin` 指向正确
