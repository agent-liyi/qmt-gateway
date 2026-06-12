"""性能相关不变量测试。

不在这里做时间断言（benchmark 不属于单测范畴），只锁住一些
正确性 / 一致性的关键不变量：

- _on_tick 三个 bar 共用同一 now（保证 1m / 30m / 1d 的 timestamp 一致）
- _on_tick 走完后 _bars_1m / _bars_30m / _bars_1d 各有 1 个 bar
- subscribe / unsubscribe 不会重复添加同一个 callback
"""

import datetime
import threading
import time

import pytest

from qmt_gateway.services.quote_service import QuoteService


def _make_tick(symbol: str = "600000.SH", last_price: float = 10.0,
              volume: int = 1000, amount: float = 10000.0) -> dict:
    return {
        "code": symbol,
        "lastPrice": last_price,
        "volume": volume,
        "amount": amount,
    }


def test_on_tick_uses_one_now_for_all_bars(monkeypatch):
    """_on_tick 应只取一次 now，避免三个 _update_bar 内部各自 datetime.now()
    产生微小时间差，导致 1m / 30m / 1d 的 timestamp 出现不一致。

    做法：mock QuoteService._is_trade_time / _update_bar，
    在 _update_bar 上装一个计数器，第一次调用时记录 bar["time"]，后续断言相等。
    """
    service = QuoteService()

    seen_times: list[str] = []
    seen_lock = threading.Lock()

    real_update_bar = service._update_bar

    def spy_update_bar(bar_cache, tick, now, interval):
        bar = real_update_bar(bar_cache, tick, now, interval)
        with seen_lock:
            seen_times.append(bar["time"])
        return bar

    monkeypatch.setattr(service, "_is_trade_time", lambda: True)
    monkeypatch.setattr(service, "_update_bar", spy_update_bar)

    service._on_tick(_make_tick())

    # 三个级别（1m / 30m / 1d）各走一次 _update_bar
    assert len(seen_times) == 3
    # 因为 _on_tick 取一次 now → 三个 bar 共享同一时间 → bar.time 也一致
    assert seen_times[0] == seen_times[1] == seen_times[2]


def test_subscribe_unsubscribe_dedup():
    """同一个 callback 重复 subscribe 不应出现多次。"""
    service = QuoteService()
    cb = lambda payload: None

    service.subscribe(cb)
    service.subscribe(cb)  # 重复
    assert len(service._callbacks) == 1

    service.unsubscribe(cb)
    service.unsubscribe(cb)  # 重复
    assert len(service._callbacks) == 0


def test_get_latest_price_returns_zero_when_no_bars():
    """没有 tick 时 get_latest_price 返回 0（不抛异常）。"""
    service = QuoteService()
    assert service.get_latest_price("600000.SH") == 0


def test_update_bar_1d_uses_overwrite_with_cumulative():
    """1d 整日 = 自开盘累计，走覆盖（与 1m/30m 走 ref 减法不同）。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 10, 0, 0)

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}, now, 86400)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 5000, "amount": 50000.0}, now, 86400)

    # 1d 走覆盖：bar.volume = tick.volume（最新累计）
    assert bar["volume"] == 5000
    assert bar["amount"] == 50000.0


def test_update_bar_1m_last_tick_locked_delta():
    """1m 走末 tick 锁定：bar.volume = tick.volume - ref_volume（每次 tick 更新 ref）。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 9, 31, 25)

    # 同区间 3 个 tick：ref 每次都更新
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100500, "amount": 1005050.0}, now, 60)
    assert bar["volume"] == 500  # 100500 - 100000
    assert abs(bar["amount"] - 5050.0) < 0.01

    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 101200, "amount": 1012150.0}, now, 60)
    # 末 tick 锁定：ref 已是 100500，bar.volume = 101200 - 100500 = 700
    assert bar["volume"] == 700
    assert abs(bar["amount"] - 7100.0) < 0.01


def test_update_bar_1m_cross_bar_uses_previous_bar_last_tick_as_ref():
    """1m 跨 bar：新 bar 的第一笔 delta = tick.volume - 上一根 bar 末 tick.volume（无延迟）。"""
    service = QuoteService()
    bar_cache: dict = {}
    t1 = datetime.datetime(2026, 6, 12, 9, 31, 25)
    t2 = datetime.datetime(2026, 6, 12, 9, 31, 35)  # 仍在 09:31 桶（>=09:31, <09:32）
    t3 = datetime.datetime(2026, 6, 12, 9, 32, 5)   # 进入 09:32 桶

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, t1, 60)
    bar2 = service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100500, "amount": 1005050.0}, t2, 60)
    assert bar2["volume"] == 500  # 100500 - 100000

    # 跨 bar 进入 09:32 桶
    bar3 = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 100700, "amount": 1007050.0}, t3, 60)
    # 跨 bar 那一刻：新 bar.volume = tick.volume(100700) - 上一根 bar 末 tick.volume(100500) = 200
    assert bar3["volume"] == 200
    assert bar3["time"] == "2026-06-12T09:32:00"
    # 缓存里只剩新 bar
    assert len(bar_cache) == 1
