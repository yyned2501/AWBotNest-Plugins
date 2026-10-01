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
