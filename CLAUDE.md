# AWBotNest-Plugins 工作流

## 改插件标准流程

1. 先加载 `plugin-guide` skill，确认插件契约和 ctx API
2. 参考同类在用的插件写法，不自己发明
3. 改完代码跑 `ruff check` + `ruff format --check`
4. **同步提升版本号：`__init__.py` 的 `__plugin__["version"]` 和 `manifest.json` 对应条目必须一起改，漏一个算 bug**
5. 更新 changelog
6. **先 commit + push 到远程仓库**
7. 再调用 `deploy-plugin` skill 同步到平台并热重载
8. 验证：`curl` 检查插件版本/日志确认生效（重载约 20 秒后再复查一次版本，确认没被回退）

> **为什么必须先提交推送、再部署**：平台会在你 push 后约 20 秒自动从 git（origin 默认分支）拉代码覆盖插件目录并重载。
> 若先部署、后提交，部署上去的未提交版本会被这次 git 同步**回退成远程旧版本**（表现为 reload 成新版、几十秒后又变回旧版）。
> 因此顺序固定为：改码 → commit + push → deploy → 验证。验证时务必等过这 20 秒再查版本。

## 外部 API 文档维护

- 调研、日志、抓包或运行实测确认/更正第三方或平台 API 的端点、字段、动作、状态或限制时，必须在同一提交更新对应 `docs/` API 文档。
- 文档必须区分“已确认”和“待验证”；代码只能依赖已确认的契约，不能把推测字段或参数写成既定事实。
- 扩展既有 API 对接前，先阅读对应文档；如果文档缺失，先建立最小接口文档并注明证据来源。

## 文档同步（官方更新时及时跟进）

本仓库维护两类同步自上游的文档，**官方更新后要及时同步到本地**，避免本地落后导致写错契约：

- **平台文档**（上游：`https://github.com/AWdress/AWBotNest/tree/main/docs`）：`docs/PLUGIN_GUIDE.md`、`docs/SPEC.md` 直接镜像上游同名文件，`docs/API.md`、`docs/CLAUDE.md` 为上层平台文档。以官方版本为准，本地版本是校验过的快照，**不做本地改动**（否则下次同步会覆盖丢失）。
- **官方 skill 库**（上游：`https://github.com/AWdress/AWBotNest-Plugins/tree/main/skills/software-development`）：`awbotnest-plugin-development/`、`awbotnest-plugin-pitfalls/` 两份 SKILL 已整合进本地 `docs/` 与 `.claude/skills/plugin-guide/`。官方新增契约/坑时，对照补进本地整合 skill。

**同步流程**（官方可见更新后，或每隔一段时间核对）：
1. `git clone --depth 1`（或 `git fetch`）拉上游两份仓库到临时目录。
2. `diff` 对比上游 `docs/` 与本地 `docs/`；逐条看差异，判断是官方重排/补充还是废弃。
3. 平台文档变更：直接覆盖本地同名文件（若本地有超越官方的改动，先在 CLAUDE.md/skill 里迁移记录再覆盖）。
4. skill 变更：把官方新增契约/坑同步进 `.claude/skills/plugin-guide/`（SKILL.md + references/pitfalls.md），保持中文表述与本地风格一致。
5. 新增/变更需在 changelog 或 PROGRESS.md 记录「同步了哪个上游版本」。

> 注意：本地 `docs/juai-api.md`、`docs/skyGame-hdsky-api.md` 是**第三方平台 API 调研产出**，不属于上游 `AWBotNest/docs`，**不要跟上游做覆盖式同步**（只保留在本地 docs/）。
