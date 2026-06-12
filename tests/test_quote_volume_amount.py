"""Tests for QuoteService._update_bar volume/amount semantics.

xtquant 规范：tick 中的 volume / amount 是**当日累计成交**（自开盘起累计），
不是本 tick 的 delta。不同级别 K 线采用不同语义：

- 1d 整日 = 自开盘起累计 → 直接覆盖
- 日内级别（1m / 30m / 其它）→ 本 bar 成交量 = tick.volume - bar_baseline.volume
"""

import datetime

from qmt_gateway.services.quote_service import QuoteService


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 6, 12, 9, 31, 25)


# ============================================================
# 1d 级别：走"覆盖"语义（1d 整日 = 自开盘累计）
# ============================================================

def test_1d_new_bar_uses_first_tick_cumulative_value():
    """1d 的 volume 等于 tick.volume，因为 1d 整日就是开盘以来累计。"""
    service = QuoteService()
    bar_cache: dict = {}
    tick = {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}

    bar = service._update_bar(bar_cache, tick, _now(), interval=86400)

    assert bar["volume"] == 1000
    assert bar["amount"] == 10000.0
    assert bar["open"] == bar["high"] == bar["low"] == bar["close"] == 10.0


def test_1d_subsequent_ticks_overwrite_to_latest_cumulative():
    """1d 后续 tick 覆盖到最新累计值。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 10, 0, 0)

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 1000, "amount": 10000.0}, now, 86400)
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 5000, "amount": 50500.0}, now, 86400)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 8000, "amount": 81000.0}, now, 86400)

    # 1d 整日累计：直接覆盖，最后一笔 = 8000
    assert bar["volume"] == 8000
    assert bar["amount"] == 81000.0
    assert bar["high"] == 10.2
    assert bar["low"] == 10.0
    assert bar["close"] == 10.2


# ============================================================
# 1m 级别：走"baseline 减法"语义（本 bar 成交量 = tick - baseline）
# ============================================================

def test_1m_new_bar_records_baseline_from_first_tick():
    """1m 新 bar 第一个 tick 把 volume 当作 baseline，bar.volume 从 0 起步。"""
    service = QuoteService()
    bar_cache: dict = {}
    tick = {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}  # 当日已累计 10w 股

    bar = service._update_bar(bar_cache, tick, _now(), interval=60)

    # 第一笔：volume=0（基线已记 100000，等下一笔再算 delta）
    assert bar["baseline_volume"] == 100000
    assert bar["volume"] == 0
    assert bar["baseline_amount"] == 1000000.0
    assert bar["amount"] == 0.0
    assert bar["open"] == bar["high"] == bar["low"] == bar["close"] == 10.0


def test_1m_subsequent_ticks_subtract_baseline():
    """1m 后续 tick: bar.volume = tick.volume - baseline.volume（等于本 bar 内产生的成交量）。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = _now()

    # 09:31:25 第 1 个 tick：当日累计 = 100000
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    # 09:31:35 第 2 个 tick：当日累计 = 100500（这一分钟内增了 500）
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100500, "amount": 1005050.0}, now, 60)
    # 09:31:55 第 3 个 tick：当日累计 = 101200（再增 700）
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 101200, "amount": 1012150.0}, now, 60)

    # 这 1 分钟产生的成交量 = 101200 - 100000 = 1200
    assert bar["volume"] == 1200
    # 这 1 分钟产生的成交额 = 1012150 - 1000000 = 12150
    assert abs(bar["amount"] - 12150.0) < 0.01
    # 价格正常
    assert bar["high"] == 10.2
    assert bar["low"] == 10.0
    assert bar["close"] == 10.2


def test_1m_new_bar_first_tick_missing_volume_recovers_on_second_tick():
    """1m 首 tick 缺 volume：第 1 笔 vol=0；第 2 笔有 vol 时把 baseline 重新建好。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = _now()

    # 第 1 个 tick 没有 volume 字段
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 0, "amount": 0.0}, now, 60)
    # 第 2 个 tick 有 volume
    bar = service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100000, "amount": 1001000.0}, now, 60)

    # 第一个有效 tick 同时被当作 baseline：bar.volume = 0
    assert bar["baseline_volume"] == 100000
    assert bar["volume"] == 0


def test_1m_new_bar_advances_to_next_bar_resets_baseline():
    """1m 跨 bar：旧 bar 缓存清空，新 bar 重新记录 baseline。"""
    service = QuoteService()
    bar_cache: dict = {}
    t1 = datetime.datetime(2026, 6, 12, 9, 31, 25)
    t2 = datetime.datetime(2026, 6, 12, 9, 32, 5)

    # 09:31 bar
    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, t1, 60)
    service._update_bar(bar_cache, {"lastPrice": 10.1, "volume": 100500, "amount": 1005050.0}, t1, 60)
    # 09:32 bar：baseline 重置为 100700
    bar2 = service._update_bar(bar_cache, {"lastPrice": 10.5, "volume": 100700, "amount": 1007050.0}, t2, 60)

    assert bar2["open"] == 10.5
    # 09:32 第一笔 volume 从 0 起步
    assert bar2["volume"] == 0
    assert bar2["baseline_volume"] == 100700
    # 旧 bar 已清掉
    assert len(bar_cache) == 1


# ============================================================
# 30m 级别：与 1m 一致，走 baseline 减法
# ============================================================

def test_30m_uses_baseline_subtraction():
    """30m 与 1m 走同一逻辑：本 bar 成交量 = tick.volume - baseline.volume。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = datetime.datetime(2026, 6, 12, 10, 5, 0)

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 500000, "amount": 5000000.0}, now, 1800)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.2, "volume": 512000, "amount": 5120000.0}, now, 1800)

    # 30 分钟内增 12000
    assert bar["volume"] == 12000
    assert abs(bar["amount"] - 120000.0) < 0.01


# ============================================================
# 通用边界
# ============================================================

def test_volume_never_negative_when_tick_equals_baseline():
    """保护：bar.volume 不应出现负数（即使某次 tick.volume 异常回落）。"""
    service = QuoteService()
    bar_cache: dict = {}
    now = _now()

    service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)

    assert bar["volume"] == 0
    assert bar["amount"] == 0.0
