"""Stock API regression tests."""

import qmt_gateway.apis.stock as stock_api
from starlette.testclient import TestClient

import qmt_gateway.apis.trade as trade_api
from qmt_gateway.app import app
from qmt_gateway.db.models import Stock
from qmt_gateway.services.stock_service import stock_service


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
