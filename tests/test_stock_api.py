"""Stock API regression tests."""

import datetime
import json
from decimal import Decimal

import qmt_gateway.apis.stock as stock_api
from starlette.testclient import TestClient

import qmt_gateway.apis.trade as trade_api
from qmt_gateway.app import app
from qmt_gateway.db.models import Stock
from qmt_gateway.services.stock_service import stock_service
from qmt_gateway.services.trade_service import trade_service


client = TestClient(app)


def test_resolve_stock_rejects_ambiguous_keyword(monkeypatch):
    monkeypatch.setattr(
        stock_service,
        "search_stocks",
        lambda query: [
            Stock(symbol="600000.SH", name="浦发银行", pinyin="pfyh", last_close=10.0),
            Stock(symbol="000001.SZ", name="平安银行", pinyin="payh", last_close=11.0),
        ],
    )
    monkeypatch.setattr(stock_api, "require_api_key_or_session", lambda request: {"username": "tester"})

    response = client.get("/api/stock/resolve", params={"q": "银行"})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "ambiguous": True, "count": 2}


def test_resolve_stock_keeps_exact_match(monkeypatch):
    monkeypatch.setattr(
        stock_service,
        "search_stocks",
        lambda query: [
            Stock(symbol="600000.SH", name="浦发银行", pinyin="pfyh", last_close=10.0),
            Stock(symbol="000001.SZ", name="平安银行", pinyin="payh", last_close=11.0),
        ],
    )
    monkeypatch.setattr(stock_api, "require_api_key_or_session", lambda request: {"username": "tester"})

    response = client.get("/api/stock/resolve", params={"q": "平安银行"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["symbol"] == "000001.SZ"
    assert response.json()["name"] == "平安银行"


def test_search_stocks_returns_html_fragment_for_multiple_matches(monkeypatch):
    matches = [
        Stock(symbol="600000.SH", name="浦发银行", pinyin="pfyh", last_close=10.0),
        Stock(symbol="000001.SZ", name="平安银行", pinyin="payh", last_close=11.0),
    ]
    monkeypatch.setattr(stock_service, "get_all_stocks", lambda: matches)
    monkeypatch.setattr(stock_service, "search_stocks", lambda query: matches)
    monkeypatch.setattr(stock_api, "require_api_key_or_session", lambda request: {"username": "tester"})

    response = client.get("/api/stocks/search", params={"stock_search": "p"})

    assert response.status_code == 200
    assert "浦发银行" in response.text
    assert "平安银行" in response.text
    assert "selectStock" in response.text


def test_positions_table_returns_html_fragment(monkeypatch):
    monkeypatch.setattr(trade_api, "login_required", lambda request: {"username": "tester"})
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(trade_api, "get_latest_positions_data", lambda: [])

    response = client.get("/api/trade/positions", params={"view": "table"})

    assert response.status_code == 200
    assert "暂无持仓" in response.text


# --- #45: /api/trade/{positions,orders,trades} JSON serialization ---


def test_positions_json_returns_200(monkeypatch):
    """#45: /api/trade/positions JSON 路径必须返回 200 + 合法 JSON，不能 500。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api,
        "get_latest_positions_data",
        lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "shares": 100,
                "avail": 100,
                "price": 10.5,
                "cost": 10.0,
                "profit_ratio": 5.0,
                "float_profit": 50.0,
                "market_value": 1050.0,
                "hold_cost": 1000.0,
                "position_ratio": 0.1,
            }
        ],
    )

    response = client.get("/api/trade/positions")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["symbol"] == "600000.SH"
    assert body[0]["shares"] == 100


def test_positions_json_normalizes_datetime_and_decimal(monkeypatch):
    """#45: positions JSON 路径应能处理 datetime / Decimal / numpy 等非 JSON 类型。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})

    class _NumpyFloat:
        def __init__(self, v):
            self._v = v

        def item(self):
            return self._v

    monkeypatch.setattr(
        trade_api,
        "get_latest_positions_data",
        lambda: [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "shares": 200,
                "avail": 200,
                "price": Decimal("11.20"),
                "cost": _NumpyFloat(10.0),
                "profit_ratio": _NumpyFloat(12.0),
                "float_profit": Decimal("240.00"),
                "market_value": _NumpyFloat(2240.0),
                "hold_cost": 2000.0,
                "position_ratio": 0.2,
            }
        ],
    )

    response = client.get("/api/trade/positions")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["price"] == 11.2
    assert body[0]["cost"] == 10.0
    assert body[0]["profit_ratio"] == 12.0
    # ensure json.dumps does not raise
    json.dumps(body)


def test_orders_json_returns_200_with_datetime_time(monkeypatch):
    """#45: orders JSON 路径必须返回 200 + 合法 JSON，time 字段为 datetime 时不抛错。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api,
        "get_latest_orders_data",
        lambda status="all": [
            {
                "time": datetime.datetime(2026, 6, 5, 10, 30, 0),
                "symbol": "600000.SH",
                "name": "浦发银行",
                "side": "buy",
                "price": 10.5,
                "shares": 100,
                "filled": 0,
                "status": "submitted",
                "qtoid": "abc-123",
                "can_cancel": True,
            }
        ],
    )

    response = client.get("/api/trade/orders")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "600000.SH"
    # time field should be normalized to a string by _json_safe (ISO format)
    assert isinstance(body[0]["time"], str)
    assert "2026-06-05" in body[0]["time"]


def test_orders_json_string_time_preserved(monkeypatch):
    """#45: orders JSON 路径中已为字符串的 time 字段应原样保留。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api,
        "get_latest_orders_data",
        lambda status="all": [
            {
                "time": "09:35:12",
                "symbol": "000001.SZ",
                "name": "平安银行",
                "side": "sell",
                "price": 11.2,
                "shares": 200,
                "filled": 200,
                "status": "filled",
                "qtoid": "def-456",
                "can_cancel": False,
            }
        ],
    )

    response = client.get("/api/trade/orders")

    assert response.status_code == 200
    assert response.json()[0]["time"] == "09:35:12"


def test_orders_json_status_filter(monkeypatch):
    """#45: orders JSON 路径应支持 status 查询参数。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})

    def fake_get_orders(status="all"):
        rows = [
            {"time": "09:30:00", "symbol": "X", "name": "X", "side": "buy", "price": 1, "shares": 1, "filled": 0, "status": "submitted", "qtoid": "1", "can_cancel": True},
            {"time": "10:00:00", "symbol": "Y", "name": "Y", "side": "sell", "price": 2, "shares": 1, "filled": 1, "status": "filled", "qtoid": "2", "can_cancel": False},
        ]
        if status == "all":
            return rows
        return [r for r in rows if r["status"] == status]

    monkeypatch.setattr(trade_api, "get_latest_orders_data", fake_get_orders)

    response = client.get("/api/trade/orders", params={"status": "filled"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "filled"


def test_trades_json_returns_200(monkeypatch):
    """#45: /api/trade/trades JSON 路径必须返回 200 + 合法 JSON。"""
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_service,
        "get_trades",
        lambda: [
            {
                "tid": "t-1",
                "qtoid": "abc",
                "time": datetime.datetime(2026, 6, 5, 11, 0, 0),
                "symbol": "600000.SH",
                "name": "浦发银行",
                "side": "buy",
                "price": 10.5,
                "shares": 100,
                "amount": 1050.0,
            }
        ],
    )

    response = client.get("/api/trade/trades")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["tid"] == "t-1"
    # time field is normalized to HH:MM:SS by _format_time in the handler
    assert body[0]["time"] == "11:00:00"


def test_json_safe_handles_common_types():
    """#45: _json_safe / _json_safe_rows 单元测试，覆盖各类型分支。"""
    dt = datetime.datetime(2026, 6, 5, 10, 30, 0)
    d = datetime.date(2026, 6, 5)
    dec = Decimal("12.34")

    class _NpFloat:
        def item(self):
            return 3.14

    assert trade_api._json_safe(None) is None
    assert trade_api._json_safe(True) is True
    assert trade_api._json_safe(42) == 42
    assert trade_api._json_safe(3.14) == 3.14
    assert trade_api._json_safe("hi") == "hi"
    assert trade_api._json_safe(dt) == "2026-06-05T10:30:00"
    assert trade_api._json_safe(d) == "2026-06-05"
    assert trade_api._json_safe(dec) == 12.34
    assert trade_api._json_safe(b"abc") == "616263"
    assert trade_api._json_safe(_NpFloat()) == 3.14
    # unknown type -> str fallback
    class _Foo: pass
    assert trade_api._json_safe(_Foo()) == "<class 'tests.test_stock_api.test_json_safe_handles_common_types.<locals>._Foo'>" or isinstance(trade_api._json_safe(_Foo()), str)

    # _json_safe_rows
    rows = trade_api._json_safe_rows([{"a": dt, "b": dec}, {"a": "x", "b": 1}])
    assert rows[0]["a"] == "2026-06-05T10:30:00"
    assert rows[0]["b"] == 12.34
    assert rows[1]["a"] == "x"


def test_get_latest_orders_data_live_path_normalizes_datetime(monkeypatch):
    """#45: get_latest_orders_data 在 trade_service 有订单时也应将 datetime.time 归一为 HH:MM:SS。"""
    monkeypatch.setattr(
        trade_service,
        "get_orders",
        lambda: [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "side": "buy",
                "price": 11.2,
                "shares": 100,
                "filled": 0,
                "status": "submitted",
                "time": datetime.datetime(2026, 6, 5, 9, 35, 12),
                "qtoid": "live-1",
            }
        ],
    )
    monkeypatch.setattr(trade_api, "_get_stock_name_map", lambda symbols: {})

    rows = trade_api.get_latest_orders_data()

    assert len(rows) == 1
    assert rows[0]["time"] == "09:35:12"
