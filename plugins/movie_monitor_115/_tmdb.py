# =============================================================================
# movie_monitor_115 私有辅助：TMDB 查询 + Emby 媒体库检查
# =============================================================================

import re
from typing import List, Optional

import aiohttp
from aiohttp import ClientTimeout


class TmdbApi:
    """TMDB 识别匹配（异步）。"""

    def __init__(self, api_key: str, proxy_enable: bool = False, proxy_url: str = ""):
        self.api_key = api_key
        self.language = "zh"
        self.base_url = "https://api.themoviedb.org/3"
        self.proxy_enable = proxy_enable
        self.proxy_url = proxy_url

    def _kwargs(self, params: dict) -> dict:
        kwargs = {"params": params, "ssl": False}
        if self.proxy_enable and self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return kwargs

    async def search_all(self, title: str, year: str = None, log=None) -> List[dict]:
        movie = await self._search(f"{self.base_url}/search/movie", title,
                                   {"year": year}, log)
        tv = await self._search(f"{self.base_url}/search/tv", title,
                                {"first_air_date_year": year}, log)
        for r in movie:
            r["media_type"] = "movie"
        for r in tv:
            r["media_type"] = "tv"
        return movie + tv

    async def _search(self, url: str, title: str, extra: dict, log) -> List[dict]:
        if not title:
            return []
        params = {"api_key": self.api_key, "language": self.language, "query": title}
        params.update({k: v for k, v in extra.items() if v})
        try:
            timeout = ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, **self._kwargs(params)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("results", [])
        except Exception as e:  # noqa: BLE001
            if log:
                log.error("[影巢监控] TMDB 查询失败: %r", e)
            return []

    @staticmethod
    def compare_names(file_name: str, tmdb_names: list) -> bool:
        if not file_name or not tmdb_names:
            return False
        if not isinstance(tmdb_names, list):
            tmdb_names = [tmdb_names]
        file_name = re.sub(r"[\W_]+", " ", file_name).strip().upper()
        for n in tmdb_names:
            if file_name == re.sub(r"[\W_]+", " ", n).strip().upper():
                return True
        return False


async def get_emby_tmdb_ids(emby_server: str, emby_api: str, title: str,
                            media_type: Optional[str], log=None) -> List[str]:
    """查 Emby 媒体库里某标题已有项的 TMDB ID 列表。"""
    if not emby_server or not emby_api:
        return []
    if media_type and media_type.lower() == "movie":
        item_types = "Movie"
    elif media_type and media_type.lower() == "tv":
        item_types = "Series"
    else:
        item_types = None

    url = f"{emby_server}emby/Items"
    params = {
        "IncludeItemTypes": item_types or "",
        "Fields": "ProviderIds,OriginalTitle,ProductionYear,Path",
        "StartIndex": 0, "Recursive": "true", "SearchTerm": title,
        "Limit": 10, "IncludeSearchTypes": "false", "api_key": emby_api,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                items = res.get("Items") if res else None
                if not items:
                    return []
                return [it["ProviderIds"].get("Tmdb") for it in items
                        if "Tmdb" in it.get("ProviderIds", {})]
    except Exception as e:  # noqa: BLE001
        if log:
            log.error("[影巢监控] 连接 Emby 失败: %r", e)
        return []
