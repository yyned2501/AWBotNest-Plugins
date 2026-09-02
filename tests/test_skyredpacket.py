# -*- coding: utf-8 -*-
# 天空红包重试延迟测试：未发言被拒后追加随机大延迟；上限设 0 关闭保持旧行为。
#
# 只覆盖抽出的纯函数（等待时间计算），不触碰真实 Telegram/消息点击。

from __future__ import annotations

import time

from plugins import skyRedPacket


def test_parse_wait_seconds_variants() -> None:
    # 取第一个 N秒："红包前 30 秒" 用于以 msg_ts+30 计算可抢点（与重试主链一致）
    assert skyRedPacket._parse_wait_seconds("红包前 30 秒仅限最近 20 位发言人领取，请在 12 秒后重试") == 30
    assert skyRedPacket._parse_wait_seconds("距红包可抢还有 5 秒") == 5
    assert skyRedPacket._parse_wait_seconds("") is None
    assert skyRedPacket._parse_wait_seconds("没有数字") is None


def test_quiet_extra_disabled_keeps_old_behavior() -> None:
    # 上限 <= 0：关闭大延迟，返回 0（向后兼容旧的“可抢即点”）
    assert skyRedPacket._quiet_extra_delay(0, 0) == 0.0
    assert skyRedPacket._quiet_extra_delay(10, 0) == 0.0


def test_quiet_extra_within_range() -> None:
    for _ in range(100):
        v = skyRedPacket._quiet_extra_delay(10, 40)
        assert 10 <= v <= 40


def test_quiet_extra_normalizes_reversed_bounds() -> None:
    # min/max 写反也能落在正确区间
    for _ in range(100):
        v = skyRedPacket._quiet_extra_delay(40, 10)
        assert 10 <= v <= 40


def test_quiet_extra_negative_min_clamped() -> None:
    for _ in range(50):
        v = skyRedPacket._quiet_extra_delay(-5, 10)
        assert 0 <= v <= 10


def test_retry_wait_without_msg_ts_uses_base_plus_extra() -> None:
    # 拿不到发送时间：从现在起等 wait_seconds，再叠加未发言延迟
    assert skyRedPacket._compute_retry_wait(30, msg_ts=0, retry_offset=1, quiet_extra=5) == 35.0


def test_retry_wait_with_msg_ts_grabs_at_eligibility() -> None:
    now = time.time()
    # 可抢时间已过 20 秒（now-50+30-1）→ 至少等 0.5 秒
    assert skyRedPacket._compute_retry_wait(30, msg_ts=now - 50, retry_offset=1, quiet_extra=0) == 0.5
    # 可抢时间在未来：msg_ts-10+30-offset1 = 距 now 约 19 秒
    w = skyRedPacket._compute_retry_wait(30, msg_ts=now - 10, retry_offset=1, quiet_extra=0)
    assert 18.0 < w <= 19.0
    # 叠加 10 秒未发言延迟 → 约 29 秒
    w2 = skyRedPacket._compute_retry_wait(30, msg_ts=now - 10, retry_offset=1, quiet_extra=10)
    assert 28.0 < w2 <= 29.0
