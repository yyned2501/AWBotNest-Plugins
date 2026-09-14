# -*- coding: utf-8 -*-
# 天空游戏 · 炸金花包入口
#
# 从 zhajinhua.py 模块暴露完整公共 API，保持与旧导入路径的兼容性。
# 所有子模块（zjh_hand / zjh_state / zjh_model / zjh_profile / zjh_notify / zjh_prob / gen_zjh_prob）
# 仍可通过 `games.zhajinhua.<子模块>` 直接导入。

from __future__ import annotations

from .zhajinhua import *  # noqa: F403 — __all__ 在 zhajinhua.py 定义，此处显式重导出
