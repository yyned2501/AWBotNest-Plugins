# =============================================================================
# AWBotNest 插件：趣味答题（quiz_game）
#
# 用你的用户账号在群里跑答题游戏：发「开启答题」出题，群友直接发答案抢答，
# 答对自动用 reply("+魔力") 发奖（由群转账 bot 实际打款），支持连胜加成。
#
# 出题源：AI（OpenAI 兼容接口，本插件自带配置）或天行数据 API。
# 无参与费，奖励即转账指令，不依赖平台转账确认。
# =============================================================================

import asyncio

from ._engine import fetch_from_ai, fetch_from_tianapi

__plugin__ = {
    "name": "趣味答题",
    "id": "quiz_game",
    "version": "1.0.0",
    "author": "AWdress",
    "description": "群内答题游戏：发「开启答题」出题，群友抢答，答对自动发魔力奖励，支持连胜加成。AI或天行出题。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "valid_groups": {
            "type": "text", "default": "", "label": "允许的群组ID",
            "section": "范围", "help": "一行一个群组ID。只有这些群能开启答题（需群内有转账bot发奖）。留空=不限制。",
        },
        # —— 玩法 ——
        "reward": {
            "type": "number", "default": 200, "label": "答对奖励(魔力)",
            "min": 1, "section": "玩法",
        },
        "timeout": {
            "type": "slider", "default": 60, "label": "每题限时(秒)",
            "min": 10, "max": 300, "step": 5, "section": "玩法",
        },
        "rounds": {
            "type": "slider", "default": 5, "label": "题目轮数",
            "min": 1, "max": 30, "step": 1, "section": "玩法",
        },
        # —— 出题源 ——
        "source": {
            "type": "select", "default": "ai", "label": "出题源", "section": "出题源",
            "options": [
                {"value": "ai", "label": "🤖 AI 出题"},
                {"value": "tianapi", "label": "☁️ 天行数据"},
            ],
        },
        "difficulty": {
            "type": "string", "default": "中等稍低", "label": "AI 难度",
            "section": "出题源", "show_if": {"source": "ai"},
        },
        "ai_api_key": {
            "type": "password", "default": "", "label": "AI API Key",
            "section": "出题源", "show_if": {"source": "ai"},
        },
        "ai_base_url": {
            "type": "string", "default": "", "label": "AI 接口地址",
            "section": "出题源", "help": "OpenAI 兼容接口，留空用官方默认。", "show_if": {"source": "ai"},
        },
        "ai_model": {
            "type": "string", "default": "gpt-3.5-turbo", "label": "AI 模型",
            "section": "出题源", "show_if": {"source": "ai"},
        },
        "tianapi_key": {
            "type": "password", "default": "", "label": "天行数据 Key",
            "section": "出题源", "show_if": {"source": "tianapi"},
        },
    },
}

# 进行中的答题：{chat_id: state}（进程内）
_active: dict = {}
_busy_hints: set = set()
_name_cache: dict = {}
_tasks: set = set()


def _track(task):
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _lines(raw) -> list[str]:
    return [x.strip() for x in str(raw or "").splitlines() if x.strip()]


def _valid_group(cfg, chat_id: int) -> bool:
    groups = []
    for line in _lines(cfg.get("valid_groups", "")):
        try:
            groups.append(int(line))
        except ValueError:
            pass
    return True if not groups else chat_id in groups


async def _auto_del(message, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def setup(ctx):
    async def _send_temp(client, chat_id, text, delay=30):
        msg = await client.send_message(chat_id, text)
        _track(asyncio.create_task(_auto_del(msg, delay)))
        return msg

    async def _fetch_pool(cfg, rounds):
        source = cfg.get("source", "ai")
        if source == "tianapi":
            pool = []
            for _ in range(rounds):
                q = await fetch_from_tianapi(cfg.get("tianapi_key", ""), ctx.log)
                if q:
                    pool.append(q)
            return pool
        return await fetch_from_ai(
            rounds, cfg.get("difficulty", "中等稍低"),
            cfg.get("ai_api_key", ""), cfg.get("ai_base_url", ""),
            cfg.get("ai_model", "gpt-3.5-turbo"), ctx.log,
        )

    def _schedule_timeout(client, chat_id, timeout):
        async def _runner():
            await asyncio.sleep(timeout)
            if chat_id in _active:
                ans = _active[chat_id]["a"]
                await _send_temp(client, chat_id,
                                 f"⏱️ 时间到！没人答对，正确答案是：{ans}\n🛑 活动已结束")
                await _stop(client, chat_id)
        return _track(asyncio.create_task(_runner()))

    async def _send_next_question(client, chat_id, timeout):
        state = _active[chat_id]
        text = (f"🎯 趣味答题 · 第 {state['round']}/{state['total_rounds']} 轮\n"
                f"❓ {state['q']}\n\n⏱️ 请在 {timeout} 秒内直接发送答案")
        try:
            msg = await client.send_message(chat_id, text)
            state["q_msgs"].append(msg)
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[答题] 发题失败: %r", e)
            return
        state["task"] = _schedule_timeout(client, chat_id, timeout)

    async def _start(client, chat_id, message):
        cfg = ctx.config
        if chat_id in _active:
            if chat_id not in _busy_hints:
                _busy_hints.add(chat_id)
                await _send_temp(client, chat_id, "⚠️ 答题已在进行中，结束请发：结束答题")
            return
        timeout = int(cfg.get("timeout", 60) or 60)
        reward = int(cfg.get("reward", 200) or 200)
        rounds = max(1, min(int(cfg.get("rounds", 5) or 5), 30))

        pool = await _fetch_pool(cfg, rounds)
        _busy_hints.discard(chat_id)
        if len(pool) < rounds:
            await _send_temp(client, chat_id, "❌ 出题失败，题目数量不足，请检查出题源配置或稍后重试。")
            return

        first = pool[0]
        _active[chat_id] = {
            "q": first["q"], "a": first["a"], "aliases": first.get("aliases", []),
            "round": 1, "total_rounds": rounds, "scores": {}, "task": None,
            "answering": False, "question_pool": pool, "next_idx": 1, "q_msgs": [],
            "last_winner_id": 0, "streak_count": 0,
        }
        _name_cache.setdefault(chat_id, {})
        text = (f"🎯 趣味答题 · 第 1/{rounds} 轮\n🎁 答对奖励：{reward} 魔力\n"
                f"❓ {first['q']}\n\n⏱️ 请在 {timeout} 秒内直接发送答案\n（发「结束答题」可手动结束）")
        try:
            msg = await message.edit_text(text)
        except Exception:
            msg = await client.send_message(chat_id, text)
        if msg:
            _active[chat_id]["q_msgs"].append(msg)
        _active[chat_id]["task"] = _schedule_timeout(client, chat_id, timeout)

    async def _stop(client, chat_id):
        if chat_id in _active:
            state = _active[chat_id]
            if state["task"]:
                state["task"].cancel()
            for msg in state.get("q_msgs", []):
                try:
                    await msg.delete()
                except Exception:
                    pass
            scores = state["scores"]
            if scores:
                names = _name_cache.get(chat_id, {})
                board = "\n".join(f"👤 {names.get(uid, str(uid))}: {sc} 分"
                                  for uid, sc in sorted(scores.items(), key=lambda x: x[1], reverse=True))
                text = f"🛑 答题结束\n🏆 排行榜\n{board}"
            else:
                text = "🛑 答题结束，本轮无人得分。"
            await _send_temp(client, chat_id, text)
            _active.pop(chat_id, None)
            _name_cache.pop(chat_id, None)
        _busy_hints.discard(chat_id)

    # ── 控制命令（自己发出）──
    @ctx.on_message(ctx.filters.outgoing & ctx.filters.group & ctx.filters.text, group=-8)
    async def quiz_control(client, message):
        text = (message.text or "").strip()
        if text == "开启答题":
            if not _valid_group(ctx.config, message.chat.id):
                try:
                    await message.edit_text("⚠️ 该群未在允许列表，无法开启答题。")
                except Exception:
                    pass
                return
            try:
                await message.edit_text("🎮 趣味答题启动中，正在生成题目...")
            except Exception:
                pass
            await _start(client, message.chat.id, message)
        elif text == "结束答题":
            await _stop(client, message.chat.id)

    # ── 抢答（群内收到的消息）──
    @ctx.on_message(ctx.filters.group & ctx.filters.text & ctx.filters.incoming, group=15)
    async def quiz_answer(client, message):
        chat_id = message.chat.id
        if chat_id not in _active:
            return
        text = (message.text or "").strip()
        if not text or text.startswith((".", "/")):
            return
        state = _active[chat_id]
        if state.get("answering"):
            return

        ans = str(state["a"]).lower()
        aliases = [str(x).lower() for x in state.get("aliases", [])]
        user_ans = text.lower()
        if not (ans in user_ans or user_ans in aliases):
            return

        state["answering"] = True
        if state["task"]:
            state["task"].cancel()

        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.first_name if message.from_user else str(uid)
        if uid:
            _name_cache.setdefault(chat_id, {})[uid] = uname
        state["scores"][uid] = state["scores"].get(uid, 0) + 1
        score = state["scores"][uid]

        reward = int(ctx.config.get("reward", 200) or 200)
        if uid and state.get("last_winner_id") == uid:
            streak = int(state.get("streak_count", 1)) + 1
        else:
            streak = 1
        state["last_winner_id"] = uid
        state["streak_count"] = streak
        bonus = int(reward * min(max(streak - 1, 0), 5) * 0.2)
        total = reward + bonus

        try:
            await message.reply(f"+{total}")  # 群转账 bot 识别发奖
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[答题] 发奖失败: %r", e)

        streak_text = f"🔥 连胜 {streak}（+{bonus}）\n" if streak > 1 else ""
        result = await message.reply(
            f"🎉 答对了！\n👤 {uname}\n✅ 答案：{ans}\n💰 +{total} 魔力\n{streak_text}📈 累计 {score} 次\n⏳ 准备下一题..."
        )
        _track(asyncio.create_task(_auto_del(result, 30)))

        if state["round"] >= state["total_rounds"]:
            await _stop(client, chat_id)
            return
        state["round"] += 1
        await asyncio.sleep(3)
        pool = state.get("question_pool", [])
        nxt = int(state.get("next_idx", 0))
        if nxt < len(pool):
            qd = pool[nxt]
            state.update({"q": qd["q"], "a": qd["a"], "aliases": qd.get("aliases", []),
                          "next_idx": nxt + 1, "answering": False})
            await _send_next_question(client, chat_id, int(ctx.config.get("timeout", 60) or 60))
        else:
            await _stop(client, chat_id)


async def teardown(ctx):
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
    _active.clear()
    _busy_hints.clear()
    _name_cache.clear()
