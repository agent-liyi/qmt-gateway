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


# 默认 server_time：放在 10:00 连续竞价段，避免被集合竞价 / 订阅快照闸门拦截
_DEFAULT_SERVER_DT = datetime.datetime(2026, 6, 12, 10, 0, 0)
_DEFAULT_SERVER_MS = int(_DEFAULT_SERVER_DT.timestamp() * 1000)


def _make_tick(
    symbol: str = "600000.SH",
    last_price: float = 10.0,
    open_price: float | None = None,
    high_price: float | None = None,
    low_price: float | None = None,
    volume: int = 1000,
    amount: float = 10000.0,
    server_time_ms: int | None = None,
) -> dict:
    """构造一个 xtquant 风格的 tick 字典。

    关键字段：
    - ``time``: server_time（毫秒）；不指定则取 _DEFAULT_SERVER_MS
    - ``code`` / ``lastPrice`` / ``volume`` / ``amount``: 与 xtquant 全推一致
    """
    return {
        "code": symbol,
        "time": server_time_ms if server_time_ms is not None else _DEFAULT_SERVER_MS,
        "lastPrice": last_price,
        "open": last_price if open_price is None else open_price,
        "high": last_price if high_price is None else high_price,
        "low": last_price if low_price is None else low_price,
        "volume": volume,
        "amount": amount,
        "lastClose": last_price,
        "stockStatus": 3,
    }


def _ms(dt: datetime.datetime) -> int:
    """datetime → server_time 毫秒。"""
    return int(dt.timestamp() * 1000)


def test_on_tick_uses_one_now_for_all_bars(monkeypatch):
    """_on_tick 应只取一次 now，避免三个 _update_bar 内部各自 datetime.now()
    产生微小时间差，导致 1m / 30m / 1d 的 timestamp 出现不一致。

    做法：mock _update_bar 记录每次调用收到的 now 参数，断言三次 now 完全一致。
    """
    service = QuoteService()

    seen_nows: list[datetime.datetime] = []
    seen_lock = threading.Lock()

    def spy_update_bar(bar_cache, tick, now, interval):
        with seen_lock:
            seen_nows.append(now)
        return {"time": now.isoformat()}

    monkeypatch.setattr(service, "_is_trade_time", lambda: True)
    monkeypatch.setattr(service, "_update_bar", spy_update_bar)

    # tick 自带 server_time（10:00），不再依赖本地 now
    service._on_tick(_make_tick(server_time_ms=_ms(datetime.datetime(2026, 6, 12, 10, 0, 0))))

    # 三个级别（1m / 30m / 1d）各走一次 _update_bar
    assert len(seen_nows) == 3
    # 关键不变量：三次调用共享同一 now（避免每个级别各自 datetime.now()
    # 产生微小时间差）
    assert seen_nows[0] == seen_nows[1] == seen_nows[2]


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
    assert bar["last_tick_volume"] == 5000
    assert bar["last_tick_amount"] == 50000.0


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
    # bar.time 是区间右端点：09:32:05 的 tick 属于 09:33 bar（详见 issue #80）
    assert bar3["time"] == "2026-06-12T09:33:00"
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


def test_update_bar_1m_bar_time_is_right_edge():
    """1m bar.time 是区间右端点（A 股标准 K 线语义）。

    09:30:00 ~ 09:30:59 的成交属于 09:31 bar；09:31:00 ~ 09:31:59 属于 09:32。
    详见 docs/know-how.md §1.2、issue #80。
    """
    service = QuoteService()
    bar_cache: dict = {}

    # 09:30:30 → 09:31 bar
    now = datetime.datetime(2026, 6, 12, 9, 30, 30)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    assert bar["time"] == "2026-06-12T09:31:00"

    # 09:31:00 整 → 09:32 bar（边界算"下一根"，符合 (ts // 60 + 1) * 60）
    bar_cache.clear()
    now = datetime.datetime(2026, 6, 12, 9, 31, 0)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    assert bar["time"] == "2026-06-12T09:32:00"

    # 09:30:59.999 → 09:31 bar（ts 截断到 09:30:59）
    bar_cache.clear()
    now = datetime.datetime(2026, 6, 12, 9, 30, 59, 999000)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 60)
    assert bar["time"] == "2026-06-12T09:31:00"


def test_update_bar_30m_bar_time_aligns_to_right_edge():
    """30m bar.time 也是区间右端点。

    A 股 30m 边界：09:30 ~ 10:00 → 10:00 bar；10:00 ~ 10:30 → 10:30 bar。
    """
    service = QuoteService()
    bar_cache: dict = {}

    # 09:30:30 → 10:00 bar（属于 09:30~10:00 这 30 分钟）
    now = datetime.datetime(2026, 6, 12, 9, 30, 30)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 1800)
    assert bar["time"] == "2026-06-12T10:00:00"

    # 09:59:30 → 10:00 bar
    bar_cache.clear()
    now = datetime.datetime(2026, 6, 12, 9, 59, 30)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 1800)
    assert bar["time"] == "2026-06-12T10:00:00"

    # 10:00:01 → 10:30 bar
    bar_cache.clear()
    now = datetime.datetime(2026, 6, 12, 10, 0, 1)
    bar = service._update_bar(bar_cache, {"lastPrice": 10.0, "volume": 100000, "amount": 1000000.0}, now, 1800)
    assert bar["time"] == "2026-06-12T10:30:00"


def test_on_tick_skips_auction_period(monkeypatch):
    """09:15 ~ 09:29:59 集合竞价期间不合成 K 线、不广播。

    集合竞价期间撮合数据走独立 endpoint /ws/auction（issue #81）；
    /ws/quotes 的第一根 1m bar 必须是 09:31。
    """
    service = QuoteService()

    update_bar_calls: list[int] = []

    def spy_update_bar(bar_cache, tick, now, interval):
        update_bar_calls.append(interval)
        return {}

    monkeypatch.setattr(service, "_is_trade_time", lambda: True)
    monkeypatch.setattr(service, "_update_bar", spy_update_bar)

    # 09:20:30（集合竞价 B 段）的 tick——通过 server_time 控制，无需 mock datetime
    auction_ms = _ms(datetime.datetime(2026, 6, 12, 9, 20, 30))
    service._on_tick(_make_tick(server_time_ms=auction_ms))

    # 集合竞价期间不应进 _update_bar
    assert update_bar_calls == []


def test_on_tick_synthesizes_at_0930(monkeypatch):
    """09:30:00 起开始合成 K 线（第一根 1m bar 落在 09:31）。"""
    service = QuoteService()

    update_bar_calls: list[int] = []

    def spy_update_bar(bar_cache, tick, now, interval):
        update_bar_calls.append(interval)
        return {"time": "2026-06-12T09:31:00"}

    monkeypatch.setattr(service, "_is_trade_time", lambda: True)
    monkeypatch.setattr(service, "_update_bar", spy_update_bar)

    cont_ms = _ms(datetime.datetime(2026, 6, 12, 9, 30, 0, 500_000))
    service._on_tick(_make_tick(server_time_ms=cont_ms))

    # 三个级别（1m / 30m / 1d）都进了 _update_bar
    assert sorted(update_bar_calls) == [60, 1800, 86400]


def test_on_tick_first_bar_inherits_auction_ohlc_and_volume():
    """首根连续竞价 bar 应承接集合竞价价格语义与累计成交量。"""
    service = QuoteService()
    service._is_trade_time = lambda: True

    symbol = "600000.SH"
    tick1_ms = _ms(datetime.datetime(2026, 6, 12, 9, 30, 5))
    tick2_ms = _ms(datetime.datetime(2026, 6, 12, 9, 30, 35))

    service._on_tick(
        _make_tick(
            symbol=symbol,
            last_price=10.02,
            open_price=10.00,
            high_price=10.03,
            low_price=10.00,
            volume=100000,
            amount=1000000.0,
            server_time_ms=tick1_ms,
        )
    )
    service._on_tick(
        _make_tick(
            symbol=symbol,
            last_price=10.01,
            open_price=10.00,
            high_price=10.05,
            low_price=9.98,
            volume=100300,
            amount=1003500.0,
            server_time_ms=tick2_ms,
        )
    )

    bar_1m = next(iter(service._bars_1m[symbol].values()))
    bar_30m = next(iter(service._bars_30m[symbol].values()))
    bar_1d = next(iter(service._bars_1d[symbol].values()))

    for bar in (bar_1m, bar_30m, bar_1d):
        assert bar["open"] == 10.00
        assert bar["high"] == 10.05
        assert bar["low"] == 9.98
        assert bar["close"] == 10.01

    # 首根日内 bar 的累计成交应自然包含集合竞价撮合量。
    assert bar_1m["volume"] == 100300
    assert bar_30m["volume"] == 100300
    assert bar_1d["volume"] == 100300


def test_update_bar_non_first_intraday_bar_uses_last_price_extremes():
    """非首根日内 bar 的 high/low 继续按区间内 lastPrice 估算。"""
    service = QuoteService()
    bar_cache: dict = {}

    # 先走完首根 09:31 bar。
    service._update_bar(
        bar_cache,
        _make_tick(
            last_price=10.02,
            open_price=10.00,
            high_price=10.05,
            low_price=9.98,
            volume=100300,
            amount=1003500.0,
            server_time_ms=_ms(datetime.datetime(2026, 6, 12, 9, 30, 35)),
        ),
        datetime.datetime(2026, 6, 12, 9, 30, 35),
        60,
    )

    # 进入下一根 09:32 bar；tick.high/tick.low 虽然带着当日累计极值，
    # 但这一根应只按该区间内 lastPrice 做 max/min。
    service._update_bar(
        bar_cache,
        _make_tick(
            last_price=10.20,
            open_price=10.00,
            high_price=11.00,
            low_price=9.50,
            volume=100500,
            amount=1005500.0,
            server_time_ms=_ms(datetime.datetime(2026, 6, 12, 9, 31, 5)),
        ),
        datetime.datetime(2026, 6, 12, 9, 31, 5),
        60,
    )
    bar = service._update_bar(
        bar_cache,
        _make_tick(
            last_price=10.10,
            open_price=10.00,
            high_price=11.20,
            low_price=9.40,
            volume=100700,
            amount=1007500.0,
            server_time_ms=_ms(datetime.datetime(2026, 6, 12, 9, 31, 35)),
        ),
        datetime.datetime(2026, 6, 12, 9, 31, 35),
        60,
    )

    assert bar["time"] == "2026-06-12T09:32:00"
    assert bar["open"] == 10.20
    assert bar["high"] == 10.20
    assert bar["low"] == 10.10
    assert bar["close"] == 10.10


def test_on_tick_drops_subscription_snapshot():
    """订阅瞬间 xtquant 推送的 server_time=0 快照 tick 必须被剔除。

    特征：tick.time<=0；payload OHLV=0、lastPrice=lastClose=昨收价。
    见 wiki "xtquant 全推 Tick 行为" §3.1。
    """
    service = QuoteService()

    update_bar_calls: list[int] = []
    tick_callback_calls: list[tuple] = []

    def spy_update_bar(bar_cache, tick, now, interval):
        update_bar_calls.append(interval)
        return {}

    def tick_cb(symbol, server_time, tick):
        tick_callback_calls.append((symbol, server_time, tick))

    service._is_trade_time = lambda: True
    service._update_bar = spy_update_bar
    service.subscribe_tick(tick_cb)

    # time=0 的快照 tick
    service._on_tick(_make_tick(server_time_ms=0))
    # time<0 的异常 tick
    service._on_tick(_make_tick(server_time_ms=-100))

    assert update_bar_calls == []
    assert tick_callback_calls == []


def test_on_tick_fires_tick_callback_during_auction():
    """集合竞价段（09:15~09:29:59）应触发 _tick_callbacks，但不进 _update_bar。"""
    service = QuoteService()

    update_bar_calls: list[int] = []
    tick_calls: list[tuple] = []

    def spy_update_bar(bar_cache, tick, now, interval):
        update_bar_calls.append(interval)
        return {}

    def tick_cb(symbol, server_time, tick):
        tick_calls.append((symbol, server_time, tick))

    service._is_trade_time = lambda: True
    service._update_bar = spy_update_bar
    service.subscribe_tick(tick_cb)

    # 09:20:30 集合竞价 B 段
    t = datetime.datetime(2026, 6, 12, 9, 20, 30)
    service._on_tick(_make_tick(symbol="000001.SZ", server_time_ms=_ms(t)))

    assert update_bar_calls == []
    assert len(tick_calls) == 1
    sym, st, tick = tick_calls[0]
    assert sym == "000001.SZ"
    assert st == t
    assert tick["code"] == "000001.SZ"


def test_on_tick_fires_tick_callback_during_continuous():
    """连续竞价段（>= 09:30）也触发 _tick_callbacks，便于下游做统一加工。"""
    service = QuoteService()

    tick_calls: list[tuple] = []

    def tick_cb(symbol, server_time, tick):
        tick_calls.append((symbol, server_time, tick))

    service._is_trade_time = lambda: True
    service.subscribe_tick(tick_cb)

    t = datetime.datetime(2026, 6, 12, 10, 0, 0)
    service._on_tick(_make_tick(symbol="600519.SH", server_time_ms=_ms(t)))

    # 连续竞价段 → tick 回调被触发，且 K 线也被合成
    assert len(tick_calls) == 1
    assert tick_calls[0][0] == "600519.SH"


def test_subscribe_tick_dedup():
    """同一个 tick 回调重复 subscribe_tick 不应出现多次。"""
    service = QuoteService()
    cb = lambda symbol, st, tick: None

    service.subscribe_tick(cb)
    service.subscribe_tick(cb)
    assert len(service._tick_callbacks) == 1

    service.unsubscribe_tick(cb)
    service.unsubscribe_tick(cb)
    assert len(service._tick_callbacks) == 0

