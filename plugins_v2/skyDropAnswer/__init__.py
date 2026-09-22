# =============================================================================
# AWBotNest 插件：天空答题 (skyDropAnswer) v2.1.7
#
# 合并自原 skyDropTrigger + skyDropAnswer：
#   - 答题：监听天空小秘（bot 8907007783）的银元掉落题目，模板/AI 解答并点击按钮领取
#   - 触发：每小时智能触发循环（interval 状态机），发「第{n}题{x}」把掉落刷出来
#   - 协同：答题侧统计掉落写入共享 ctx.kv，触发状态机直接读取，无需跨插件通信
#
# 代码按功能拆分：
#   models.py    常量与纯工具函数（无 ctx 依赖）
#   templates.py 答题模板管理（加载/去重/学习/验证/匹配 + 模板 API）
#   answer.py    答题主逻辑（按钮匹配 + 提交 + 通知）
#   trigger.py   每小时触发状态机 + /info 回复捕获
# =============================================================================

from __future__ import annotations

import shutil
from pathlib import Path

from . import answer as answer_mod
from . import kv_facade
from . import models as models_mod
from . import templates as templates_mod
from . import trigger as trigger_mod

__plugin__ = {
    "name": "天空答题",
    "id": "skyDropAnswer",
    "version": "2.1.11",
    "author": "Yy",
    "description": "天空答题奖励 + 每小时智能触发：模板管理/AI答题/自动触发掉落一体化。",
    "icon": "https://raw.githubusercontent.com/yyned2501/AWBotNest-Plugins/main/icons/skyDropAnswer.svg",
    "tags": ["答题", "AI 答题", "模板管理", "自动触发"],
    "changelog": (
        "v2.1.11 修复：\n"
        "- 收紧掉落归属：只答「回复我自己消息」的掉落，不再抢答别人触发的题。\n"
        "  2.1.10 的兜底把「回复了任意消息」都算命中，于是接管全群掉落，\n"
        "  其中按钮已过期的那些点击大量报 MessageIdInvalidError；\n"
        "  现改为运行期登记「自己发过的群消息 id」做归属比对，比对不中一律不答\n"
        "v2.1.10 修复：\n"
        "- 修复 V2 Telethon 运行时自动答题完全不触发：回复归属判断只认 Pyrogram 的\n"
        "  reply_to_message / outgoing，而 Telethon 消息对象没有这两个属性，导致每条掉落\n"
        "  消息都在过滤处静默返回（表现为插件加载正常、零日志、KV 无计数）；\n"
        "  现兼容 reply_to / reply_to_msg_id 与被回复消息的 out 标记；\n"
        "- 内联按钮读取兼容 Telethon 的 reply_markup.rows[].buttons[].text（此前只认\n"
        "  Pyrogram 的 inline_keyboard，即使答对也找不到按钮而跳过）；\n"
        "- 版本号跳过 2.1.9：该版本为实验性 JEV 仲裁分支，未并入本主线\n"
        "v2.1.8 更新：\n"
        "- 补充插件功能标签，插件市场与「我的插件」卡片可见；插件行为无变化\n"
        "v2.1.7 修复：\n"
        "- 适配 V2 Telethon 消息运行时：不再使用 ctx.filters 与 on_message(group=)（该运行时不提供，\n"
        "  启用时报 'PluginContext' object has no attribute 'filters'），群/私聊/文案/回复归属过滤\n"
        "  改在 handler 内手动完成，兼容单 event 与 (client, message) 两种回调形态；\n"
        "- 按钮点击按签名自适应（Telethon click(i=行,j=列) / Pyrogram click(x=列,y=行)）；\n"
        "- /info 与触发消息发送改走 user → user.raw → bot.raw 兜底链（同 skyGame 掉馅守卫）；\n"
        "v2.1.6 修复：\n"
        "- 适配 V2 异步 KV 存储：启用同步外观层（启动预载 + 内存即时读写 + 异步落库），\n"
        "  修复启用即崩溃（PluginKV 无 keys()）及触发计数/模板命中数持久化静默失效；\n"
        "- 卸载前兜底 flush 脏键，避免热卸载取消最后一次异步写；\n"
        "v2.1.5 更新：\n"
        "- 自动触发新增「启用文案类型」多选：可勾选只用模板/背诗/唱歌中的某几个或某一个\n"
        "- 本轮仍从已勾选且有内容的类型中随机选一种，轮内不切换；全不选则回退模板\n"
        "v2.1.4 更新：\n"
        "- 背诗/唱歌改为按配置行顺序逐行发（不再随机），行号存 kv 循环使用\n"
        "- 同一行按标点符号拆成多条消息依次发，段间 1~3 秒短停顿模拟打字\n"
        "- 发送中途检测到掉落则跳过本行剩余段，下次轮到该类别从下一行继续\n"
        "v2.1.3 更新：\n"
        "- 触发消息新增「背诗」「唱歌」两种文案类型，随机切换避免频繁发「第n题x」被系统检测\n"
        "- 新增配置项：背诗池、唱歌池，用户可自定义多行文案\n"
        "v2.1.2 更新：\n"
        "- 触发改为低频调度：不再用 20 秒 tick 逐次重试同一道题\n"
        "- 同一题在一次整轮任务内连续尝试，短随机间隔；检测到掉落立即停止后续尝试\n"
        "- 整轮结束后按「触发间隔」定时启动下一题，插件卸载时会取消未完成轮次\n"
        "v2.1.1 更新：\n"
        "- 触发拟人化：决定触发后随机延迟 0~「拟人延迟上限」秒再发，避免整点机械刷屏\n"
        "- 修正「已定时下一次触发」日志把秒误显示为分钟的问题\n"
        "v2.1.0 更新：\n"
        "- 自动触发新增「开启时段」：只在设定的小时范围内触发（默认 8-23 点，支持跨午夜）\n"
        "- 掉落后不再随机冷却等待，改用定时任务按固定「触发间隔」触发下一题\n"
        "- 移除冷却上下限配置，新增「触发间隔(分钟)」；跨小时自动清空配额重新 /info 校准\n"
        "- 触发统计改为「累计 / 今日 / 本时段」三段，各含触发次数与掉落次数\n"
        "v2.0.0 重大更新（合并 skyDropTrigger）：\n"
        "- 合并天空掉落触发插件，按功能拆分 models/templates/answer/trigger 四个模块\n"
        "- 新增每小时智能触发循环：/info 校准 + 第{n}题{x} 触发 + 掉落检测 + 随机冷却\n"
        "- 新增「全局设置」分组：目标群组、机器人统一配置；答题奖励更名「自动答题」\n"
        "- 每小时掉落目标改为从 /info 自动读取：私聊 bot 发 /info，解析「当前时段剩余掉落」\n"
        "- 触发消息模板可配置（{n}=题号 {x}=尝试次数），连续 N 次未掉落自动发 /info 检查\n"
        "- 【注意】原 skyDropTrigger 的配置不会自动迁移，需在新分组重新配置\n"
        "v1.10.6 更新内容：\n"
        "- 推送通知时附带题目原文，方便管理员验证答案正确性\n"
        "v1.10.5 更新内容：\n"
        "- 模板命中次数改用 ctx.kv 存储，不再写入 .py 模板文件，重启后保留计数\n"
        "v1.10.4 更新内容：\n"
        "- 修复 _reply_to_own 改用 ctx.filters.create 包装 is_self 判断，恢复 filter 层的正确拦截"
    ),
    "scope": "user",
    "plugin_api_version": 2,
    "render_mode": "vue",
    "default_enabled": False,
    "config_schema": {
        # ── 全局设置 ──
        "target_groups": {
            "type": "text",
            "default": "-1001326208894",
            "label": "目标群组（一行一个ID）",
            "section": "全局设置",
            "help": "触发消息发到这些群，一行一个。/info 校准走私聊 bot，不占用群。",
            "order": 1,
        },
        "bot": {
            "type": "string",
            "default": "",
            "label": "天空小秘机器人",
            "section": "全局设置",
            "help": "@用户名 或 数字ID，逗号分隔可填多个。留空=默认天空小秘。",
            "order": 2,
        },
        # ── 自动答题 ──
        "enable_reward_answer": {
            "type": "boolean",
            "default": False,
            "label": "开启自动答题",
            "section": "自动答题",
            "order": 10,
        },
        "reward_delay_min": {
            "type": "number",
            "default": 2,
            "label": "延迟最小",
            "section": "自动答题",
            "min": 1,
            "max": 30,
            "help": "秒",
            "order": 11,
        },
        "reward_delay_max": {
            "type": "number",
            "default": 5,
            "label": "延迟最大",
            "section": "自动答题",
            "min": 1,
            "max": 60,
            "help": "秒",
            "order": 12,
        },
        "use_ai_fallback": {
            "type": "boolean",
            "default": True,
            "label": "AI智能答题",
            "section": "自动答题",
            "help": "未知题型时使用AI分析并回答",
            "order": 13,
        },
        "enable_template_learning": {
            "type": "boolean",
            "default": True,
            "label": "AI学习模板",
            "section": "自动答题",
            "help": "AI答完题后自动生成模板.py文件，下次同类题直接脚本答",
            "order": 14,
        },
        # ── 自动触发 ──
        "trig_enabled": {
            "type": "boolean",
            "default": False,
            "label": "启用自动触发",
            "section": "自动触发",
            "help": "在开启时段内定时触发；掉落目标自动从 /info 读取",
            "order": 20,
        },
        "trig_start_min": {
            "type": "slider",
            "default": 5,
            "label": "触发窗口起始分",
            "section": "自动触发",
            "min": 0,
            "max": 30,
            "step": 1,
            "help": "每小时第几分开始触发循环",
            "order": 21,
        },
        "trig_max_attempts": {
            "type": "slider",
            "default": 10,
            "label": "单题最大尝试次数",
            "section": "自动触发",
            "min": 1,
            "max": 20,
            "step": 1,
            "help": "同一题触发这么多次仍无掉落就放弃该题",
            "order": 22,
        },
        "trig_info_every": {
            "type": "slider",
            "default": 5,
            "label": "每几次未掉落查/info",
            "section": "自动触发",
            "min": 0,
            "max": 10,
            "step": 1,
            "help": "连续这么多次触发未掉落时发 /info 检查状态，0=不检查",
            "order": 23,
        },
        "trig_interval": {
            "type": "slider",
            "default": 5,
            "label": "触发间隔(分钟)",
            "section": "自动触发",
            "min": 1,
            "max": 60,
            "step": 1,
            "help": "一次触发完成后，定时这么久再触发下一题（替代随机冷却）",
            "order": 24,
        },
        "trig_jitter_max": {
            "type": "slider",
            "default": 30,
            "label": "拟人延迟上限(秒)",
            "section": "自动触发",
            "min": 0,
            "max": 120,
            "step": 5,
            "help": "决定触发后随机延迟 0~此值再发，模拟真人发送时机（0=不延迟）",
            "order": 25,
        },
        "trig_active_start": {
            "type": "slider",
            "default": 8,
            "label": "开启时段·开始(点)",
            "section": "自动触发",
            "min": 0,
            "max": 23,
            "step": 1,
            "help": "每天这个点起才允许触发（24 小时制）",
            "order": 26,
        },
        "trig_active_end": {
            "type": "slider",
            "default": 23,
            "label": "开启时段·结束(点)",
            "section": "自动触发",
            "min": 0,
            "max": 23,
            "step": 1,
            "help": "每天到这个点停止触发（含该点）；开始>结束视为跨午夜，如 22→6",
            "order": 27,
        },
        "trig_info_timeout": {
            "type": "slider",
            "default": 60,
            "label": "/info等待超时(秒)",
            "section": "自动触发",
            "min": 10,
            "max": 300,
            "step": 5,
            "help": "发 /info 后这么久没收到回复就用本地计数继续",
            "order": 28,
        },
        "trig_drop_timeout": {
            "type": "slider",
            "default": 120,
            "label": "等掉落超时(秒)",
            "section": "自动触发",
            "min": 30,
            "max": 600,
            "step": 10,
            "help": "发「第n题x」后这么久没掉落就发下一条（第n题x+1 的间隔）",
            "order": 29,
        },
        "trig_use_info": {
            "type": "boolean",
            "default": True,
            "label": "发送/info校准",
            "section": "自动触发",
            "help": "每小时私聊 bot 发 /info 读取「当前时段剩余掉落」；连续失败时也用它检查",
            "order": 30,
        },
        "trig_kinds": {
            "type": "multiselect",
            "default": ["template", "poem", "song"],
            "label": "启用文案类型",
            "section": "自动触发",
            "options": [
                {"value": "template", "label": "模板（第n题x）"},
                {"value": "poem", "label": "背诗"},
                {"value": "song", "label": "唱歌"},
            ],
            "help": "本轮从勾选且有内容的类型中随机选一种；背诗/唱歌需对应池非空；全不选=只用模板",
            "order": 31,
        },
        "trig_message_template": {
            "type": "string",
            "default": "第{n}题{x}",
            "label": "触发消息模板",
            "section": "自动触发",
            "help": "{n}=本小时题号 {x}=本题尝试次数，如 第{n}题{x}",
            "order": 32,
        },
        "trig_msg_poems": {
            "type": "text",
            "default": (
                "床前明月光，疑是地上霜。\n大漠孤烟直，长河落日圆。\n海内存知己，天涯若比邻。\n明月几时有？把酒问青天。"
            ),
            "label": "背诗池（一行一首）",
            "section": "自动触发",
            "help": "按行顺序逐行发，同行按标点拆多条；留空=不启用背诗",
            "order": 33,
        },
        "trig_msg_songs": {
            "type": "text",
            "default": (
                "我相信我就是我，我相信明天。\n"
                "你是我的小呀小苹果，怎么爱你都不嫌多。\n"
                "没有什么能够阻挡，你对自由的向往。"
            ),
            "label": "唱歌池（一行一句）",
            "section": "自动触发",
            "help": "按行顺序逐行发，同行按标点拆多条；留空=不启用唱歌",
            "order": 34,
        },
        "trig_stats": {
            "type": "info",
            "label": "触发统计",
            "section": "自动触发",
            "order": 36,
        },
    },
}


async def setup(ctx: object) -> None:
    ctx.log.info("天空答题插件已加载 (v%s)", __plugin__["version"])
    # V2 的 ctx.kv 是异步存储；先换成同步外观，令后续同步读写（含 keys()）照常生效
    await kv_facade.install(ctx)

    template_dir = Path(ctx.data_dir) / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    builtin_dir = Path(templates_mod.__file__).parent / "templates"
    for builtin in builtin_dir.glob("builtin_*.py"):
        target = template_dir / builtin.name
        if not target.exists():
            shutil.copy2(builtin, target)
    templates_mod._TEMPLATES_DIR = template_dir
    models_mod._TEMPLATES_DIR = template_dir

    # 加载答题模板（去重 + 从 kv 恢复命中计数）
    templates = templates_mod.load_templates(ctx)

    # 答题 handler（窄匹配：群消息 + 掉落文案 + 仅回复自己消息，含掉落计数；过滤在 handler 内手动做）
    answer_mod.register_answer_handler(ctx, templates)
    # /info 回复捕获 handler：等待 /info 时记录 bot 私聊回复
    trigger_mod.register_info_handler(ctx)
    # 模板管理 API（供 Vue 面板调用）
    templates_mod.register_api(ctx, templates)

    # 启动每小时触发状态机（interval tick，状态全存 kv）
    trigger_mod.start_trigger(ctx)
    trigger_mod.refresh_stats(ctx)

    ctx.log.info("天空答题已就绪")


async def teardown(ctx: object) -> None:
    trigger_mod.stop_trigger(ctx)
    await kv_facade.flush(ctx)  # 卸载前把脏键落库，避免热卸载取消最后一次异步写
    ctx.log.info("天空答题已卸载")
