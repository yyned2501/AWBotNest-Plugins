# AWBotNest-Plugins 工作流

## 改插件标准流程

1. 先加载 `plugin-guide` skill，确认插件契约和 ctx API
2. 参考同类在用的插件写法，不自己发明
3. 改完代码跑 `ruff check` + `ruff format --check`
4. 同步提升 `__init__.py` 和 `manifest.json` 的版本号 + 更新 changelog
5. 调用 `deploy-plugin` skill 同步到平台并热重载
6. commit + push 到远程仓库
7. 验证：`curl` 检查插件版本/日志确认生效