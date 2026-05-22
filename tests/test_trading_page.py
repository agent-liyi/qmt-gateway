"""Trading page regression tests."""

from fastcore.xml import to_xml
from starlette.testclient import TestClient

import qmt_gateway.apis.trade as trade_api
from qmt_gateway.app import app
from qmt_gateway.db.models import Asset
from qmt_gateway.web.pages.trading import OrdersTable, TradingPage


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
    assert "window.cancelOrder = function(orderId" in html
    assert "trade-toast-container" in html
    assert "showTradeToast(message, kind)" in html
    assert "buy-button" in html
    assert "sell-button" in html
    assert "fetch('/api/trade/' + orderSide, {" in html
    assert "fetch('/api/trade/cancel', {" in html
    assert "detailLines.join('\\n') + '\\n\\n确定要撤单吗？'" in html
    assert "}, 7000);" in html


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


def test_cancel_endpoint_logs_submission(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "login_required", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api.trade_service,
        "cancel_order",
        lambda order_id: {"success": True, "qtoid": order_id},
    )

    response = client.post("/api/trade/cancel", data={"order_id": "order-1"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    info_messages = [message for level, message, _ in fake_logger.records if level == "INFO"]
    assert any("收到撤单请求" in message for message in info_messages)
    assert any("撤单请求已提交" in message for message in info_messages)


def test_orders_table_hides_cancel_action_for_canceling_status():
    html = to_xml(
        OrdersTable(
            [
                {
                    "time": "10:00:00",
                    "symbol": "601398.SH",
                    "name": "工商银行",
                    "side": "buy",
                    "price": 7.0,
                    "shares": 100,
                    "filled": 0,
                    "status": "canceling",
                    "qtoid": "order-1",
                    "can_cancel": False,
                }
            ]
        )
    )

    assert "已报待撤" in html
    assert "cursor-pointer" not in html
    assert "window.cancelOrder('order-1'" not in html


def test_get_latest_asset_data_computes_profit_ratio(monkeypatch):
    asset = Asset(
        portfolio_id="default",
        dt=__import__("datetime").date.today(),
        principal=20000.0,
        cash=19000.0,
        frozen_cash=0.0,
        market_value=0.0,
        total=19000.0,
    )
    monkeypatch.setattr(trade_api, "_get_latest_asset", lambda portfolio_id: asset)
    monkeypatch.setattr(trade_api, "_snapshot_asset", lambda portfolio_id: None)

    result = trade_api.get_latest_asset_data()

    assert result["profit"] == -1000.0
    assert result["profit_ratio"] == -5.0
