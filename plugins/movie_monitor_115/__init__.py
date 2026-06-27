# =============================================================================
# AWBotNest 插件：影巢 115 媒体监控（movie_monitor_115）
#
# 监控指定频道里的 115 分享消息，解析标题/年份 → TMDB 识别 → 查 Emby 媒体库，
# 库里没有的就把 115 链接转发给 CMS 入库机器人。也支持 /getmedia 手动查 TMDB。
#
# 用你的用户账号监听。所有参数（TMDB/Emby/代理/监控频道/屏蔽词）在配置里填。
# =============================================================================

import json
import re
import shutil
import tempfile
from pathlib import Path

from ._tmdb import TmdbApi, get_emby_tmdb_ids

__plugin__ = {
    "name": "影巢115媒体监控",
    "id": "movie_monitor_115",
    "version": "1.0.0",
    "author": "AWdress",
    "description": "监控频道里的 115 分享，TMDB 识别后查 Emby 媒体库，缺失的转发给 CMS 入库机器人。",
    "scope": "user",
    "default_enabled": False,
    "config_schema": {
        "shareswitch": {
            "type": "boolean", "default": False, "label": "启用自动监控转发",
            "section": "功能开关", "help": "关闭后只监听不转发（/getmedia 手动查仍可用）。",
        },
        # —— 监控范围 ——
        "monitor_chats": {
            "type": "text", "default": "-1002188663986\n-1002245898899\n-1002343015438",
            "label": "监控频道ID", "section": "监控范围",
            "help": "一行一个频道ID。这些频道里出现 115 链接消息就处理。",
        },
        "pan115_chat_id": {
            "type": "string", "default": "-1002343015438", "label": "Pan115频道ID",
            "section": "监控范围", "help": "该频道用不同的标题/大小解析规则（带【】或冒号 + 大小判断完结）。",
        },
        "blockyword_list": {
            "type": "text", "default": "", "label": "屏蔽关键词",
            "section": "监控范围", "help": "一行一个。标题含这些词则不检索转发。",
        },
        # —— TMDB ——
        "tmdbapi": {
            "type": "password", "default": "", "label": "TMDB API Key", "section": "TMDB",
        },
        "proxy_enable": {
            "type": "boolean", "default": False, "label": "TMDB 走代理", "section": "TMDB",
        },
        "proxy_url": {
            "type": "string", "default": "", "label": "代理地址", "section": "TMDB",
            "help": "如 http://127.0.0.1:7890 或 socks5://...", "show_if": {"proxy_enable": True},
        },
        # —— Emby + CMS ——
        "embyserver": {
            "type": "string", "default": "", "label": "Emby 地址", "section": "Emby/CMS",
            "help": "形如 http://host:8096/ （结尾带斜杠）。",
        },
        "embyapi": {
            "type": "password", "default": "", "label": "Emby API Key", "section": "Emby/CMS",
        },
        "cmsbot": {
            "type": "string", "default": "", "label": "CMS 入库机器人", "section": "Emby/CMS",
            "help": "把缺失媒体的 115 链接发给这个机器人（用户名或ID）。",
        },
    },
}

_LINK_PATTERN = re.compile(r"https://115cdn\.com/s/[^\s]+")


def _lines(raw) -> list[str]:
    return [x.strip() for x in str(raw or "").splitlines() if x.strip()]


def _monitor_ids(cfg) -> list[int]:
    ids = []
    for line in _lines(cfg.get("monitor_chats", "")):
        try:
            ids.append(int(line))
        except ValueError:
            pass
    return ids


def _normalize(raw):
    s = str(raw or "").strip()
    if not s:
        return None
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return None


async def _send_115_links(client, cfg, message, title, year, ctx):
    """提取 115 链接并发给 CMS 机器人。"""
    cmsbot = _normalize(cfg.get("cmsbot"))
    if cmsbot is None:
        ctx.log.warning("[影巢监控] 未配置 CMS 机器人，跳过发送")
        return
    links = _LINK_PATTERN.findall(message.caption or "")
    if not links:
        ctx.log.warning("[影巢监控] 未找到 115 链接")
        return
    for link in links:
        try:
            await client.send_message(cmsbot, link)
            ctx.log.info("[影巢监控] 已发送 [%s %s]: %s", title, year, link)
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[影巢监控] 发送链接失败: %r", e)


async def _search_and_send(client, cfg, title, year, complete_series, message, ctx):
    if not title:
        return
    tmdb = TmdbApi(cfg.get("tmdbapi", ""), bool(cfg.get("proxy_enable", False)), cfg.get("proxy_url", ""))
    results = await tmdb.search_all(title, year, ctx.log)
    if not results:
        ctx.log.info("[影巢监控] TMDB 无结果 | %s %s", title, year)
        return

    idx = next(
        (i for i, it in enumerate(results)
         if (it.get("title") == title or it.get("name") == title)
         and ((it.get("release_date") or it.get("first_air_date") or "")[:4] == str(year))),
        next((i for i, it in enumerate(results)
              if it.get("title") == title or it.get("name") == title), 0),
    )
    media = results[idx]
    tmdb_id = media.get("id", "")
    media_type = media.get("media_type", "")
    ctx.log.info("[影巢监控] TMDB 匹配 | %s (%s) id=%s type=%s",
                 media.get("title") or media.get("name"), year, tmdb_id, media_type)

    async def check_and_send():
        try:
            ids = await get_emby_tmdb_ids(cfg.get("embyserver", ""), cfg.get("embyapi", ""),
                                          title, media_type, ctx.log)
            if ids and str(tmdb_id) in ids:
                ctx.log.info("[影巢监控] 已在媒体库 | %s id=%s", title, tmdb_id)
            else:
                await _send_115_links(client, cfg, message, title, year, ctx)
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[影巢监控] 检查媒体失败 | %s: %r", title, e)

    if media_type == "movie":
        await check_and_send()
    elif media_type == "tv":
        if complete_series:
            await check_and_send()
        else:
            ctx.log.info("[影巢监控] 剧集未完结 | %s id=%s", title, tmdb_id)


async def setup(ctx):
    @ctx.on_message(ctx.filters.text | ctx.filters.caption, group=7)
    async def monitor_channels(client, message):
        cfg = ctx.config
        if not cfg.get("shareswitch", False):
            return
        monitor_ids = _monitor_ids(cfg)
        if message.chat.id not in monitor_ids:
            return
        caption = message.caption or message.text or ""
        if not _LINK_PATTERN.search(caption):
            return

        pan115_id = _normalize(cfg.get("pan115_chat_id"))
        block_words = _lines(cfg.get("blockyword_list", ""))
        title = year = ""
        complete_series = False

        if message.chat.id == pan115_id:
            if "】" in caption:
                pat = r"[】](.*?)\s*\((\d+)\)"
            else:
                pat = r"[:] (.*?)\s*\((\d+)\)"
            ty = re.search(pat, caption)
            size = re.search(r"大\s*小[：:]\s*([\d.]+)\s*([TGM])", caption)
            if ty:
                title, year = ty.group(1).strip(), ty.group(2).strip()
            if size:
                unit_map = {"M": 1, "G": 1024, "T": 1024 ** 2}
                size_mb = float(size.group(1)) * unit_map[size.group(2)]
                complete_series = size_mb >= 10240 and "第" not in caption
        else:
            m = re.search(r"(.*?)\s*\((\d+)\)", caption)
            if m:
                title, year = m.group(1).strip(), m.group(2).strip()
                complete_series = ("EP" not in caption and "全" in caption) or "完结" in caption

        if title and year:
            if any(w in title for w in block_words):
                ctx.log.info("[影巢监控] %s %s 命中屏蔽词，跳过", title, year)
            else:
                ctx.log.info("[影巢监控] 检索 [%s] %s %s", message.chat.title, title, year)
                await _search_and_send(client, cfg, title, year, complete_series, message, ctx)

    @ctx.on_message(ctx.filters.outgoing & ctx.filters.text, group=-9)
    async def getmedia(client, message):
        text = message.text or ""
        if not re.match(r"^[/\.]getmedia(?:\s|$)", text, re.IGNORECASE):
            return
        cfg = ctx.config
        parts = text.split()
        title = parts[1] if len(parts) >= 2 else ""
        year = parts[2] if len(parts) >= 3 else "0"
        if not title:
            return await message.edit("请提供名称，例如：/getmedia 泰坦尼克号 1997")

        tmdb = TmdbApi(cfg.get("tmdbapi", ""), bool(cfg.get("proxy_enable", False)), cfg.get("proxy_url", ""))
        result = await tmdb.search_all(title, year, ctx.log)

        tmp_dir = Path(tempfile.mkdtemp(prefix="getmedia_"))
        fp = tmp_dir / f"{title}({year}).txt"
        try:
            fp.write_text(json.dumps(result, ensure_ascii=False, indent=4), encoding="utf-8")
            # 发到自己收藏夹
            await client.send_document("me", str(fp))
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            ctx.log.error("[影巢监控] /getmedia 失败: %r", e)
            try:
                await message.edit(f"❌ 查询失败: {e.__class__.__name__}")
            except Exception:
                pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def teardown(ctx):
    pass
