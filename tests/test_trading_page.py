"""Trading page regression tests."""

from fastcore.xml import to_xml
from starlette.testclient import TestClient

import qmt_gateway.apis.trade as trade_api
from qmt_gateway.app import app
from qmt_gateway.web.pages.trading import TradingPage


client = TestClient(app)


class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(("INFO", message, args))

    def warning(self, message, *args):
        self.records.append(("WARNING", message, args))


def test_trading_page_renders_order_submission_hooks():
    html = to_xml(TradingPage())

    assert "submitTradeOrder" in html
    assert "buy-button" in html
    assert "sell-button" in html
    assert "order-submit-status" in html
    assert "fetch('/api/trade/' + orderSide, {" in html


def test_buy_endpoint_logs_submission(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "login_required", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api.trade_service,
        "buy",
        lambda symbol, price, shares, qtoid="", strategy_id="": {
            "success": True,
            "qtoid": "qtoid-1",
            "order_id": "order-1",
        },
    )

    response = client.post(
        "/api/trade/buy",
        data={"symbol": "601398.SH", "price": "4.50", "shares": "100"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    info_messages = [message for level, message, _ in fake_logger.records if level == "INFO"]
    assert any("收到买入委托请求" in message for message in info_messages)
    assert any("买入委托已提交" in message for message in info_messages)
