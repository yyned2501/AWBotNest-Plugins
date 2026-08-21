# -*- coding: utf-8 -*-
# 天空游戏 · AI 评价（心路历程）通用模块
#
# 各游戏结算/结果后调用 review()，让平台 AI 在群聊总结本局心路历程：
# 赢了炫耀决策好、输了吐槽没办法/对手运气好（带对手简称）、平局轻松调侃。
# prompt 只喂动作过程与输赢结果，绝不暴露 EV/算法细节（system 中文化禁令）。
#
# 配置（config_schema + 前端 Config.vue「AI 评价」分组）：
#   ai_review_enabled  总开关（默认开）
#   ai_review_games    多选参与评价的游戏（默认含十点半；支持 zjh/horse/tenhalf/lucky）
#   ai_review_groups   发送到指定群 ID（一行一个，空=走 ctx.notify 通知中心原渠道）
#   ai_review_prompt   自定义提示词模板（占位符 {game}/{actions}/{opponent}/{result}/{tone}，
#                      空=内置默认模板）
#
# 容错：平台未接入 AI / 调用失败 / 发送失败都只记日志，绝不阻塞结算主流程。

from __future__ import annotations

import re

_GAME_LABELS = {
    "tenhalf": "十点半",
    "zjh": "炸金花",
    "horse": "养马",
    "lucky": "幸运轮盘",
}

_DEFAULT_TEMPLATE = (
    "本局我先后做了这样的决定：{actions}。对手是「{opponent}」，本局结果：{result}。"
    "{tone}。直接输出要说的话，不要解释。"
)

_SYSTEM = (
    "你是{game}游戏的玩家社交嘴替，用中文群聊口吻说话，1～2 句话、40 字以内，"
    "可以带一两个 emoji。绝对不要暴露任何数据分析或计算过程，也不要说胜率、算法、"
    "机器人这些词，更不要报具体数字，像个普通玩家一样说话。"
)


def _short_name(display_name: str, fallback: str = "对手") -> str:
    """展示名简称（AI 吐槽用）：去空白，多于 2 字符取前 2——
    「麦克格雷涛」→「麦克」、「南凝 徐」→「南凝」、短名原样、空则 fallback。"""
    name = str(display_name or "").replace(" ", "").strip()
    return name[:2] or fallback


def _action_sequence_text(steps: list[list[object]], labels: dict[str, str] | None = None) -> str:
    """决策轨迹转自然动作序列（只要动作与点数，不掺 EV 数值，供 AI prompt）。

    labels 缺省时动作原样输出（炸金花等传描述文本的调用方不走轨迹解析）。"""
    parts = []
    for total, _hand, action, *_rest in steps:
        label = (labels or {}).get(str(action), str(action))
        parts.append(f"{label} {total:g}点")
    return " → ".join(parts) or "观望"


def _tone_text(delta: int, opponent_short: str) -> str:
    """按胜负给语气指令：赢炫决策、输吐槽对手运气好（带简称）、平调侃。"""
    if delta > 0:
        return "本局我赢了，请得意地炫耀一下自己的决策（比如忍住没贪、跑得快），别谦虚"
    if delta < 0:
        return f"本局我输了，请吐槽一下没办法、对手{opponent_short}运气太好，认命但不服气"
    return "本局不亏不赚，轻松调侃一句就好"


def _build_prompt(cfg: dict, game: str, opponent_short: str, delta: int, result_text: str, seq: str) -> tuple[str, str]:
    """构造 (system, prompt)。system 固定安全底线；prompt 用自定义模板（ai_review_prompt，
    占位符 {game}/{actions}/{opponent}/{result}/{tone}）替换，缺省用内置默认模板。"""
    system = _SYSTEM.format(game=_GAME_LABELS.get(game, game))
    mapping = {
        "{game}": _GAME_LABELS.get(game, game),
        "{actions}": seq,
        "{opponent}": opponent_short,
        "{result}": result_text or "无",
        "{tone}": _tone_text(delta, opponent_short),
    }
    template = str(cfg.get("ai_review_prompt", "") or "").strip() or _DEFAULT_TEMPLATE
    prompt = template
    for key, value in mapping.items():
        prompt = prompt.replace(key, value)
    return system, prompt


def _game_enabled(cfg: dict, game: str) -> bool:
    """总开关 + 多选游戏开关；旧 tenhalf_ai_comment 显式关过则十点半不开启（迁移兼容）。"""
    if not bool(cfg.get("ai_review_enabled", True)):
        return False
    if game == "tenhalf" and cfg.get("tenhalf_ai_comment") is False:
        return False
    games = cfg.get("ai_review_games")
    if games is None:
        # 未配置过多选：十点半默认开（与旧 tenhalf_ai_comment 默认一致），其余关
        return game == "tenhalf" and bool(cfg.get("tenhalf_ai_comment", True))
    return game in (games or [])


def _group_ids(cfg: dict) -> list[str]:
    """解析 ai_review_groups：一行一个，兼容逗号分隔，去空白。"""
    raw = str(cfg.get("ai_review_groups", "") or "").strip()
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\n,]", raw) if part.strip()]


async def review(
    ctx: object,
    cfg: dict,
    game: str,
    delta: int,
    result_text: str,
    opponent: str = "",
    actions: object | None = None,
    rid: object = None,
    labels: dict[str, str] | None = None,
) -> None:
    """结算/结果后用平台 AI 生成心路历程并推送：有配置群 ID 就直发群，否则走通知中心。

    各游戏结算点调用（开关由 ai_review_games 控制）；平台无 AI / 关闭 / 失败只记日志。"""
    if game not in _GAME_LABELS or not _game_enabled(cfg, game):
        return
    label = _GAME_LABELS[game]
    ai = getattr(ctx, "ai", None)
    if ai is None or not callable(getattr(ai, "chat", None)):
        ctx.log.debug("%s AI 评价跳过：平台未提供 ctx.ai.chat", label)
        return
    if isinstance(actions, str):
        seq = actions
    elif actions:
        seq = _action_sequence_text(list(actions), labels)
    else:
        seq = "观望"
    try:
        opponent_short = _short_name(opponent, "对手")
        system, prompt = _build_prompt(cfg, game, opponent_short, delta, result_text, seq)
        text = str(await ai.chat(prompt, system=system, temperature=0.9) or "").strip()
        if not text:
            return
        await _push(ctx, cfg, label, text)
        ctx.log.info("%s AI 评价已推送%s", label, " #%s" % rid if rid is not None else "")
    except Exception as e:
        ctx.log.warning("%s AI 评价失败（跳过）: %r", label, e)


async def _push(ctx: object, cfg: dict, label: str, text: str) -> None:
    """发送心路历程：配置了 ai_review_groups 就逐个群直发，否则走 ctx.notify 原渠道。"""
    message = f"🗣 {label}心路历程：{text}"
    groups = _group_ids(cfg)
    if not groups:
        try:
            await ctx.notify(message, category=label)
        except Exception as e:
            ctx.log.warning("AI 评价通知发送失败（渠道暂不可用）: %r", e)
        return
    bot = getattr(ctx, "bot", None)
    if bot is None or not callable(getattr(bot, "send", None)):
        ctx.log.debug("AI 评价跳过群直发：平台未提供 ctx.bot.send")
        return
    for raw in groups:
        try:
            chat_id: object = raw
            if raw.lstrip("-").isdigit():
                chat_id = int(raw)
            await bot.send(chat_id, message)
        except Exception as e:
            ctx.log.warning("AI 评价直发群 %s 失败: %r", raw, e)
