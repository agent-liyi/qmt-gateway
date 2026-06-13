"""apis/auction.py 单元测试

覆盖：
- is_auction_time / auction_phase 时段判定
- AuctionWebSocket._on_tick 在不同时段下的转发行为
- 与 quote_service 的集成（subscribe_tick）
"""

import asyncio
import datetime

import pytest

from qmt_gateway.apis.auction import (
    AUCTION_END,
    AUCTION_START,
    AuctionWebSocket,
    auction_phase,
    is_auction_time,
)


def _dt(h: int, m: int = 0, s: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 6, 12, h, m, s)


# -----------------------------
# is_auction_time
# -----------------------------

@pytest.mark.parametrize(
    "dt,expected",
    [
        (_dt(9, 14, 59), False),  # 早于 09:15
        (_dt(9, 15, 0),  True),   # 边界：>= 09:15
        (_dt(9, 19, 59), True),   # auction_a
        (_dt(9, 20, 0),  True),   # auction_b
        (_dt(9, 24, 59), True),   # auction_b 末
        (_dt(9, 25, 0),  True),   # 撮合那一帧
        (_dt(9, 25, 9),  True),   # 上交所指数撮合
        (_dt(9, 29, 59), True),   # 静默期
        (_dt(9, 30, 0),  False),  # 边界：>= 09:30 走 /ws/quotes
        (_dt(10, 0, 0),  False),  # 连续竞价
    ],
)
def test_is_auction_time(dt, expected):
    assert is_auction_time(dt) is expected


@pytest.mark.parametrize(
    "dt,expected_phase",
    [
        (_dt(9, 15, 0),  "auction_a"),
        (_dt(9, 19, 59), "auction_a"),
        (_dt(9, 20, 0),  "auction_b"),
        (_dt(9, 24, 59), "auction_b"),
        (_dt(9, 25, 0),  "matching"),
        (_dt(9, 25, 9),  "matching"),
        (_dt(9, 29, 59), "matching"),
    ],
)
def test_auction_phase(dt, expected_phase):
    assert auction_phase(dt) == expected_phase


def test_auction_constants():
    """常量约束：[09:15, 09:30) 与 K 线合成的 09:30 起点严格对接。"""
    assert AUCTION_START == datetime.time(9, 15, 0)
    assert AUCTION_END == datetime.time(9, 30, 0)


# -----------------------------
# AuctionWebSocket._on_tick
# -----------------------------

def _fake_tick(
    last_price: float = 12.34,
    open_: float = 0.0,
    high: float = 0.0,
    low: float = 0.0,
    volume: int = 0,
    amount: float = 0.0,
    stock_status: int = 2,
    last_close: float = 12.0,
) -> dict:
    return {
        "code": "ignored-by-on_tick",  # symbol 由 quote_service 从 data["code"] 取，
                                        # auction._on_tick 接收的是已解析后的 (symbol, st, tick)
        "lastPrice": last_price,
        "open": open_,
        "high": high,
        "low": low,
        "volume": volume,
        "amount": amount,
        "stockStatus": stock_status,
        "lastClose": last_close,
    }


def test_on_tick_drops_when_outside_auction():
    """09:30 起的 tick 不进 auction broadcast 队列。"""
    ws = AuctionWebSocket()
    # 模拟有客户端，但 broadcast 不应被触发
    ws._clients.add(object())
    queued: list[dict] = []
    ws.broadcast = lambda payload: queued.append(payload)

    ws._on_tick("000001.SZ", _dt(10, 0, 0), _fake_tick())

    assert queued == []


def test_on_tick_no_clients_short_circuit():
    """没有客户端时直接 return，不构造 payload（性能优化）。"""
    ws = AuctionWebSocket()
    # _clients 默认为空 set
    queued: list[dict] = []
    ws.broadcast = lambda payload: queued.append(payload)

    ws._on_tick("000001.SZ", _dt(9, 20, 0), _fake_tick())

    assert queued == []


def test_on_tick_forwards_during_auction_a():
    """09:15-09:19:59 集合竞价 A 段：转发，phase=auction_a，OHLV 全 0。"""
    ws = AuctionWebSocket()
    ws._clients.add(object())  # 触发 broadcast 路径
    captured: list[dict] = []
    ws.broadcast = lambda payload: captured.append(payload)

    st = _dt(9, 17, 30)
    tick = _fake_tick(last_price=12.34, last_close=12.0)
    ws._on_tick("000001.SZ", st, tick)

    assert len(captured) == 1
    p = captured[0]
    assert p["type"] == "auction"
    assert p["symbol"] == "000001.SZ"
    assert p["phase"] == "auction_a"
    assert p["price"] == 12.34
    assert p["open"] == 0.0
    assert p["volume"] == 0
    assert p["stock_status"] == 2
    assert p["last_close"] == 12.0
    assert p["server_time"] == st.isoformat(timespec="milliseconds")


def test_on_tick_forwards_at_matching_frame():
    """09:25 撮合那一帧：phase=matching，open/high/low/volume 同时被填入。"""
    ws = AuctionWebSocket()
    ws._clients.add(object())
    captured: list[dict] = []
    ws.broadcast = lambda payload: captured.append(payload)

    # 撮合那一帧的特征：open=high=low=lastPrice，volume>0
    matching_tick = _fake_tick(
        last_price=11.00,
        open_=11.00,
        high=11.00,
        low=11.00,
        volume=23464,
        amount=258104.0,
        stock_status=2,
    )
    ws._on_tick("000001.SZ", _dt(9, 25, 0), matching_tick)

    assert len(captured) == 1
    p = captured[0]
    assert p["phase"] == "matching"
    assert p["price"] == 11.00
    assert p["open"] == 11.00
    assert p["high"] == 11.00
    assert p["low"] == 11.00
    assert p["volume"] == 23464


def test_on_tick_forwards_during_silent_period():
    """09:25-09:30 静默期：phase=matching，OHLV 锁定，仅 lastPrice 偶动。"""
    ws = AuctionWebSocket()
    ws._clients.add(object())
    captured: list[dict] = []
    ws.broadcast = lambda payload: captured.append(payload)

    silent_tick = _fake_tick(
        last_price=11.02,    # lastPrice 微调
        open_=11.00,         # OHLV 保持撮合那一帧的值
        high=11.00,
        low=11.00,
        volume=23464,
        stock_status=3,      # 已切到"连续竞价就绪"
    )
    ws._on_tick("000001.SZ", _dt(9, 28, 30), silent_tick)

    assert len(captured) == 1
    p = captured[0]
    assert p["phase"] == "matching"
    assert p["price"] == 11.02
    assert p["open"] == 11.00
    assert p["volume"] == 23464
    assert p["stock_status"] == 3


def test_quote_service_dispatches_to_auction(monkeypatch):
    """端到端：quote_service._on_tick 把 09:20 的 tick 路由到 _tick_callbacks。"""
    from qmt_gateway.services.quote_service import QuoteService

    service = QuoteService()
    monkeypatch.setattr(service, "_is_trade_time", lambda: True)

    update_bar_calls: list[int] = []
    monkeypatch.setattr(
        service,
        "_update_bar",
        lambda *a, **kw: update_bar_calls.append(a[3]) or {},
    )

    captured: list[tuple] = []
    service.subscribe_tick(lambda sym, st, tick: captured.append((sym, st, tick)))

    auction_dt = _dt(9, 20, 30)
    auction_ms = int(auction_dt.timestamp() * 1000)
    service._on_tick({
        "code": "000001.SZ",
        "time": auction_ms,
        "lastPrice": 11.05,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "volume": 0,
        "amount": 0.0,
        "stockStatus": 2,
        "lastClose": 11.0,
    })

    # 集合竞价段：tick 回调被触发，但 K 线合成被跳过
    assert update_bar_calls == []
    assert len(captured) == 1
    sym, st, _ = captured[0]
    assert sym == "000001.SZ"
    assert st == auction_dt
