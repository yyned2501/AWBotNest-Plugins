# -*- coding: utf-8 -*-
# 天空答题 · 同步 KV 外观层
#
# V2 平台的 ctx.kv 是异步存储（PluginKV：get/set/delete/items 均为协程，且无同步
# keys()），而天空答题各模块（models/templates/answer/trigger）沿用 V1 的同步
# ctx.kv 写法。逐个 await 化会牵动大量纯逻辑与单测。这里在 setup 时一次性把真实
# 异步 ctx.kv 换成同步外观：启动用 await items() 预载到内存，运行期同步
# get/set/delete/keys 命中内存，写入异步落库并在 teardown 兜底 flush。
# 对外保持同步接口，行为与 V1 一致。

from __future__ import annotations

from typing import Any

_FACADE_ATTR = "_skydropanswer_kv_facade"


class SyncKV:
    """同步外观的插件 KV：内存即时可见，落库异步。"""

    def __init__(self, ctx: Any, real: Any) -> None:
        self._ctx = ctx
        self._real = real
        self._cache: dict[str, Any] = {}
        self._dirty: set[str] = set()

    async def preload(self) -> None:
        try:
            data = await self._real.items()
        except Exception as exc:  # 平台未提供 items 或读取失败：退回空缓存，运行期自愈
            self._ctx.log.warning("KV 预载失败，按空缓存启动: %r", exc)
            return
        if isinstance(data, dict):
            self._cache = dict(data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._dirty.add(key)
        self._persist(key, value)

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        self._dirty.add(key)
        self._drop(key)

    def keys(self) -> list[str]:
        return list(self._cache.keys())

    def _persist(self, key: str, value: Any) -> None:
        try:
            self._ctx.create_task(self._real.set(key, value), name=f"skyDropAnswer:kv-set:{key}")
        except Exception as exc:
            self._ctx.log.warning("KV 落库任务创建失败（内存仍生效）: %r", exc)

    def _drop(self, key: str) -> None:
        try:
            self._ctx.create_task(self._real.delete(key), name=f"skyDropAnswer:kv-del:{key}")
        except Exception as exc:
            self._ctx.log.warning("KV 删除任务创建失败（内存仍生效）: %r", exc)

    async def flush(self) -> None:
        """把脏键同步落库（teardown 用，避免热卸载/取消丢掉最后一次写）。"""
        for key in list(self._dirty):
            if key in self._cache:
                try:
                    await self._real.set(key, self._cache[key])
                except Exception as exc:
                    self._ctx.log.warning("KV flush 写失败 %s: %r", key, exc)
            else:
                try:
                    await self._real.delete(key)
                except Exception as exc:
                    self._ctx.log.warning("KV flush 删失败 %s: %r", key, exc)
        self._dirty.clear()


async def install(ctx: Any) -> None:
    """把 ctx.kv 换成同步外观并预载。幂等：重复调用不二次包装。"""
    existing = getattr(ctx, _FACADE_ATTR, None)
    if existing is not None:
        return
    facade = SyncKV(ctx, ctx.kv)
    await facade.preload()
    setattr(ctx, _FACADE_ATTR, facade)
    ctx.kv = facade
    ctx.log.info("天空答题已启用同步 KV 外观层（适配 V2 异步存储）")


async def flush(ctx: Any) -> None:
    facade = getattr(ctx, _FACADE_ATTR, None)
    if facade is not None:
        await facade.flush()
