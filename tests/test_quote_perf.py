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


def test_update_bar_1m_xtquant_standard_kline_semantics():
    """1m 走 xtquant 标准 K 线语义：bar.volume = tick.volume - bar 起点 ref_volume。

    与 docs/know-how.md §1.4 一致：
    - 同 bar 内多 tick：ref_volume 保持为该 bar 起点（=上一根 bar 末 tick.volume，
      首根 bar 为 0）；bar.volume 表达"截至本 tick 为止的累计成交"
    - 跨 bar 那一刻：ref_volume 切换为上一根 bar 末 tick.volume
    """
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 9, 31, 25)

    # tick1：首根 bar，ref=0
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    # tick2：仍 09:31 桶，ref 保持 0；bar.volume = 100300 - 0 = 100300
    bar = service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100300, "amount": 1003000.0}, now, 60)
    assert bar["volume"] == 100300
    assert abs(bar["amount"] - 1003000.0) < 0.01

    # tick3：仍 09:31 桶，ref 仍 0；bar.volume = 100500 - 0 = 100500
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 100500, "amount": 1005050.0}, now, 60)
    assert bar["volume"] == 100500
    assert abs(bar["amount"] - 1005050.0) < 0.01


def test_update_bar_1m_cross_bar_inherits_previous_bar_last_tick():
    """1m 跨 bar：新 bar 的 ref_volume 继承自旧 bar 的最后一个 tick.volume。

    这是与 docs/know-how.md §1.4 "跨 bar 更新 ref_volume <- last_tick.volume" 一致的行为。
    """
    service = QuoteService()
    bar_cache: dict = {}
    t1 = datetime.datetime(2026, 6, 12, 9, 31, 25)
    t2 = datetime.datetime(2026, 6, 12, 9, 32, 5)   # 进入 09:32 桶

    # 09:31 bar 末 tick.volume = 100500
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, t1, 60)
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100500, "amount": 1005050.0}, t1, 60)

    # 跨 bar：09:32 第一个 tick 进来
    bar3 = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 100700, "amount": 1007050.0}, t2, 60)
    # 新 bar 的 ref_volume = 旧 bar 末 tick.volume(100500)
    # bar.volume = 100700 - 100500 = 200
    assert bar3["volume"] == 200
    assert bar3["time"] == "2026-06-12T09:32:00"
    assert len(bar_cache) == 1


def test_update_bar_1m_does_not_use_this_tick_in_subtraction():
    """1m 关键不变量：bar.volume = tick.volume - ref(更新前)，不是 tick.volume - tick.volume。

    即"用 ref 记录本 bar 区间的起点累计值"；本 tick 不参与当次减法。
    """
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 9, 31, 25)

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100300, "amount": 1003000.0}, now, 60)
    # 如果错误地写成 tick - tick，结果是 0；正确值是 100300
    assert bar["volume"] != 0
    assert bar["volume"] == 100300
