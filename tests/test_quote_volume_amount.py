"""Tests for QuoteService._update_bar volume/amount semantics.

xtquant 规范：tick 中的 volume / amount 是当日累计成交（自开盘起累计），
不是本 tick 的 delta。K 线内应当直接覆盖，不再 += 累加。
"""

import datetime

from qmt_gateway.services.quote_service import QuoteService


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 6, 12, 9, 31, 25)


def test_new_bar_uses_first_tick_cumulative_values():
    service = QuoteService()
    bar_cache: dict = {}
    tick = {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}

    bar = service._update_bar(bar_cache, tick, _now(), interval=60)

    assert bar["volume"] == 1000
    assert bar["amount"] == 10000.0
    assert bar["open"] == bar["high"] == bar["low"] == bar["close"] == 10.0


def test_subsequent_ticks_overwrite_not_accumulate():
    service = QuoteService()
    bar_cache: dict = {}
    now = _now()

    # 同 bar 内连续 3 个 tick：累计值单调递增
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}, now, 60)
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 1500, "amount": 15100.0}, now, 60)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 2000, "amount": 20200.0}, now, 60)

    # 关键断言：覆盖式更新，不会被累加成 1000+1500+2000=4500
    assert bar["volume"] == 2000
    assert bar["amount"] == 20200.0
    # high/low/close 仍按价格聚合
    assert bar["high"] == 10.2
    assert bar["low"] == 10.0
    assert bar["close"] == 10.2


def test_zero_or_none_volume_does_not_clobber_existing_value():
    service = QuoteService()
    bar_cache: dict = {}
    now = _now()

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}, now, 60)
    # 模拟某些 tick 缺字段或为 0
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 0, "amount": None}, now, 60)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 1800, "amount": 18100.0}, now, 60)

    # 期间没拿到有效值时，保留之前的累计值
    assert bar["volume"] == 1800
    assert bar["amount"] == 18100.0


def test_new_bar_resets_to_first_tick_values():
    service = QuoteService()
    bar_cache: dict = {}
    t1 = datetime.datetime(2026, 6, 12, 9, 31, 25)
    t2 = datetime.datetime(2026, 6, 12, 9, 32, 5)

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 5000, "amount": 50000.0}, t1, 60)
    # 进入下一分钟：bar 切换，累计值以该分钟的"自开盘累计"重新开始
    bar2 = service._update_bar(bar_cache, {"lastPrice": 10.5, "volume": 5500, "amount": 55500.0}, t2, 60)

    assert bar2["open"] == 10.5
    assert bar2["volume"] == 5500
    assert bar2["amount"] == 55500.0
    # 缓存里只剩新 bar
    assert len(bar_cache) == 1
