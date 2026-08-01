# AWBotNest-Plugins 工作流

## 改插件标准流程

1. 先加载 `plugin-guide` skill，确认插件契约和 ctx API
2. 参考同类在用的插件写法，不自己发明
3. 改完代码跑 `ruff check` + `ruff format --check`
4. **同步提升版本号：`__init__.py` 的 `__plugin__["version"]` 和 `manifest.json` 对应条目必须一起改，漏一个算 bug**
5. 更新 changelog
6. 调用 `deploy-plugin` skill 同步到平台并热重载
7. commit + push 到远程仓库
8. 验证：`curl` 检查插件版本/日志确认生效

## 外部 API 文档维护

- 调研、日志、抓包或运行实测确认/更正第三方或平台 API 的端点、字段、动作、状态或限制时，必须在同一提交更新对应 `docs/` API 文档。
- 文档必须区分“已确认”和“待验证”；代码只能依赖已确认的契约，不能把推测字段或参数写成既定事实。
- 扩展既有 API 对接前，先阅读对应文档；如果文档缺失，先建立最小接口文档并注明证据来源。
