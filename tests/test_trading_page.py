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
    assert "showTradeToast(message, kind, options)" in html
    assert "window.recordUnreadAlarm(message, 'trade')" in html
    assert "recordUnread: true" in html
    assert "alarm-unread-count" in html
    assert "trade-connection-indicator" in html
    assert "trade-connection-status" in html
    assert "handleTradeConnectionAction" in html
    assert "restart-qmt-modal" in html
    assert "submitRestartQmt" in html
    assert "/api/trade/restart-qmt" in html
    assert "强行终止其进程" in html
    assert "notification-center-modal" in html
    assert "buy-button" in html
    assert "sell-button" in html
    assert "buy-button-asterisk" in html
    assert "sell-button-asterisk" in html
    assert "handleOrderSideClick" in html
    assert "fetch('/api/trade/' + orderSide, {" in html
    assert "fetch('/api/trade/cancel', {" in html
    assert "detailLines.join('\\n') + '\\n\\n确定要撤单吗？'" in html
    assert "}, 7000);" in html


def test_trading_page_removes_confirm_order_button():
    """确认下单按钮已被移除 (issue #34)."""
    html = to_xml(TradingPage())
    assert "确认下单" not in html
    assert "confirm-order-button" not in html


def test_trading_page_renders_warning_toast_kind():
    """ShowTradeToast 支持 warning 类型 (用于切换方向、无可用股份提示)."""
    html = to_xml(TradingPage())
    assert "'warning'" in html
    assert "border-amber-200" in html


def test_trading_page_two_click_flow_submits_on_second_click():
    """首次点击切换方向，再次点击提交委托 (issue #28)."""
    html = to_xml(TradingPage())
    assert "window.handleOrderSideClick = function(side)" in html
    assert "currentSide === side" in html
    assert "window.submitTradeOrder()" in html
    assert "已切换为" in html
    assert "请再次点击" in html
    assert "请再次点击' + sideText + '按钮提交委托" in html


def test_position_double_click_shows_toast_for_no_available_shares():
    """双击持仓无可用股份时弹出 toast (issue #27)."""
    html = to_xml(TradingPage())
    assert "无可用股份" in html
    assert "该持仓无可用股份" in html
    assert "无法填充卖出表单" in html


def test_position_double_click_uses_limit_order_and_real_time_price():
    """双击持仓使用限价单并填入实时价格 (issue #27)."""
    html = to_xml(TradingPage())
    assert "orderTypeInput.value = 'limit'" in html
    assert "window.onOrderTypeChange('limit')" in html


def test_position_double_click_switches_to_sell_with_asterisk():
    """双击持仓后切换到卖出方向并显示星号指示 (issue #27 + #28)."""
    html = to_xml(TradingPage())
    assert "已从持仓填充卖出表单" in html
    assert "请点击卖出按钮提交委托" in html


def test_buy_endpoint_logs_submission(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "login_required", lambda request: {"username": "tester"})
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
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
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
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


def test_restart_qmt_endpoint_logs_submission(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "login_required", lambda request: {"username": "tester"})
    monkeypatch.setattr(trade_api, "require_api_key_or_session", lambda request: {"username": "tester"})
    monkeypatch.setattr(
        trade_api.trade_service,
        "restart_qmt",
        lambda password: {"success": True, "message": "QMT 已重启并重新连接交易接口"},
    )

    response = client.post("/api/trade/restart-qmt", data={"password": "trade-secret"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    info_messages = [message for level, message, _ in fake_logger.records if level == "INFO"]
    assert any("收到 QMT 重启请求" in message for message in info_messages)
    assert any("QMT 重启完成并已发起重连" in message for message in info_messages)


def test_restart_qmt_password_endpoint_consumes_token(monkeypatch):
    monkeypatch.setattr(trade_api, "_require_local_request", lambda request: None)
    monkeypatch.setattr(
        trade_api.trade_service,
        "consume_restart_password_token",
        lambda token: "trade-secret" if token == "token-1" else None,
    )

    response = client.get("/api/trade/restart-qmt/password?token=token-1")

    assert response.status_code == 200
    assert response.json() == {"password": "trade-secret"}


def test_restart_qmt_helper_status_endpoint_logs_warning(monkeypatch):
    fake_logger = FakeLogger()
    recorded = {}
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "_require_local_request", lambda request: None)
    monkeypatch.setattr(
        trade_api.trade_service,
        "record_restart_helper_status",
        lambda token, status: recorded.update({"token": token, "status": status}),
    )

    response = client.post(
        "/api/trade/restart-qmt/helper-status",
        data={"token": "token-1", "status": "自动填入 QMT 密码失败：未找到登录窗口"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert recorded == {
        "token": "token-1",
        "status": "自动填入 QMT 密码失败：未找到登录窗口",
    }
    warning_messages = [message for level, message, _ in fake_logger.records if level == "WARNING"]
    assert any("QMT helper 状态" in message for message in warning_messages)


def test_restart_qmt_helper_status_endpoint_logs_info_for_progress(monkeypatch):
    fake_logger = FakeLogger()
    recorded = {}
    monkeypatch.setattr(trade_api, "logger", fake_logger)
    monkeypatch.setattr(trade_api, "_require_local_request", lambda request: None)
    monkeypatch.setattr(
        trade_api.trade_service,
        "record_restart_helper_status",
        lambda token, status: recorded.update({"token": token, "status": status}),
    )

    response = client.post(
        "/api/trade/restart-qmt/helper-status",
        data={"token": "token-1", "status": "INFO: 已通过布局坐标填入并提交 QMT 登录"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert recorded == {
        "token": "token-1",
        "status": "INFO: 已通过布局坐标填入并提交 QMT 登录",
    }
    info_messages = [message for level, message, _ in fake_logger.records if level == "INFO"]
    assert any("QMT helper 状态" in message for message in info_messages)


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
