"""Trading page regression tests."""

import pytest
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

    async def fake_async_restart_and_login(**kwargs):
        return {"success": True, "message": "QMT 已重启并重新连接交易接口"}

    monkeypatch.setattr(
        trade_api.trade_service,
        "async_restart_and_login",
        fake_async_restart_and_login,
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


def test_position_table_exposes_avail_map_for_set_position_ratio():
    """PositionTable 应在脚本中暴露 _positionAvailBySymbol，供 setPositionRatio 卖出时使用 (#40)"""
    from qmt_gateway.web.pages.trading import PositionTable

    positions = [
        {
            "symbol": "601398.SH",
            "name": "工商银行",
            "shares": 200,
            "avail": 200,
            "price": 7.0,
            "cost": 7.36,
            "profit_ratio": 0.5,
            "market_value": 1400,
            "position_ratio": 5.0,
        },
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "shares": 1,
            "avail": 1,
            "price": 1800.0,
            "cost": 1800.0,
            "profit_ratio": 0.0,
            "market_value": 1800,
            "position_ratio": 10.0,
        },
    ]
    html = to_xml(PositionTable(positions))

    assert "_positionAvailBySymbol" in html
    assert "601398.SH" in html
    assert "200" in html
    assert "600519.SH" in html


def test_trading_page_set_position_ratio_uses_avail_for_sell():
    """setPositionRatio 在卖出时应使用持仓可卖数而非可用资金 (#40)"""
    html = to_xml(TradingPage())

    # 卖出分支：查找 _positionAvailBySymbol 并按 ratio 折算可卖手数
    assert "_positionAvailBySymbol" in html
    # 卖出时按 ratio * availShares 计算手数
    assert "availShares * ratio" in html
    # 卖出时无持仓应提示
    assert "当前选中股票无持仓可卖" in html


def test_trading_page_uses_refresh_current_table_after_trade():
    """卖出/撤单成功后应使用 refreshCurrentTable 而非切换 tab (#41)"""
    html = to_xml(TradingPage())

    # 新增的 refreshCurrentTable 函数应存在
    assert "function refreshCurrentTable" in html
    # 旧的 refreshOrdersTable 应不再被调用（避免切换 tab 引发 sendAbort 竞争）
    assert "refreshOrdersTable" not in html
    # 应该用 htmx.trigger 触发当前容器的 every 5s 触发器
    assert "htmx.trigger" in html


# --- #40: setPositionRatio 卖出应使用可卖股数 -----------------------

def _set_position_ratio_py(
    side: str,
    symbol: str,
    ratio: float,
    *,
    avail_shares_by_symbol: dict,
    available_cash: float,
    price: float,
    mode: str = "quantity",
) -> dict:
    """Python 版 setPositionRatio 规范实现，与 JS 保持一致 (#40)。

    返回值字段：
      value: 写入 #order-value 的字符串
      switched_to_quantity: amount 模式时是否切到 quantity 模式
      warning: 是否发出"无持仓可卖"提示
    """
    result = {"value": "", "switched_to_quantity": False, "warning": False}
    if not (ratio > 0):
        return result
    if side == "sell":
        avail_shares = float(avail_shares_by_symbol.get(symbol, 0) or 0)
        if not (avail_shares > 0):
            result["warning"] = True
            return result
        if mode == "amount":
            hands_from_avail = int(avail_shares // 100)
            hands_target = int(hands_from_avail * ratio)
            if hands_target < 1 and hands_from_avail > 0:
                hands_target = 1
            result["value"] = str(hands_target)
            result["switched_to_quantity"] = True
            return result
        hands = int((avail_shares * ratio) // 100)
        if hands < 1 and avail_shares > 0:
            hands = 1
        result["value"] = str(hands)
        return result
    # buy
    if not (available_cash > 0):
        return result
    if mode == "amount":
        result["value"] = f"{(available_cash * ratio) / 10000:.2f}"
        return result
    if not (price > 0):
        return result
    shares = int((available_cash * ratio) // price // 100) * 100
    result["value"] = str(max(shares // 100, 0))
    return result


def test_set_position_ratio_sell_full_position_two_hands():
    """200 股可卖 + 1.0 比率 → 2 手 (#40)"""
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=1.0,
        avail_shares_by_symbol={"601398.SH": 200},
        available_cash=0,
        price=0,
    )
    assert out["value"] == "2"
    assert out["warning"] is False


def test_set_position_ratio_sell_half_position_one_hand():
    """200 股可卖 + 0.5 比率 → 1 手 (#40)"""
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=0.5,
        avail_shares_by_symbol={"601398.SH": 200},
        available_cash=0,
        price=0,
    )
    assert out["value"] == "1"


def test_set_position_ratio_sell_quarter_position_one_hand():
    """200 股可卖 + 0.25 比率 → 0 → 兜底为 1 手 (#40)"""
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=0.25,
        avail_shares_by_symbol={"601398.SH": 200},
        available_cash=0,
        price=0,
    )
    assert out["value"] == "1"


def test_set_position_ratio_sell_small_position_floors_to_one_hand():
    """2 股可卖 + 0.5 比率 → floor(1/100)=0，兜底为 1 手 (#40)

    注：A 股最小卖出 1 手（100 股），故不足 1 手的可卖数会被抬升到 1 手。
    这是已知行为，提交委托时仍需用户确认。
    """
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=0.5,
        avail_shares_by_symbol={"601398.SH": 2},
        available_cash=0,
        price=0,
    )
    assert out["value"] == "1"


def test_set_position_ratio_sell_no_position_warns():
    """未选中持仓时卖出应提示"无持仓可卖"，不写入 input (#40)"""
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=0.5,
        avail_shares_by_symbol={},
        available_cash=100000,
        price=10.0,
    )
    assert out["value"] == ""
    assert out["warning"] is True


def test_set_position_ratio_sell_amount_mode_switches_to_quantity():
    """卖出 + 按金额模式应切到按数量并按可卖手数计算 (#40)"""
    out = _set_position_ratio_py(
        side="sell",
        symbol="601398.SH",
        ratio=0.5,
        avail_shares_by_symbol={"601398.SH": 400},
        available_cash=0,
        price=0,
        mode="amount",
    )
    # 400 股 → 4 手 × 0.5 = 2 手
    assert out["value"] == "2"
    assert out["switched_to_quantity"] is True


def test_set_position_ratio_buy_uses_available_cash():
    """买入按金额模式：1万现金 + 1.0 比率 → 1.00 万元 (#40 回归)"""
    out = _set_position_ratio_py(
        side="buy",
        symbol="601398.SH",
        ratio=1.0,
        avail_shares_by_symbol={},
        available_cash=10000,
        price=10.0,
        mode="amount",
    )
    assert out["value"] == "1.00"


def test_set_position_ratio_buy_quantity_uses_cash_and_price():
    """买入按数量模式：1万现金 / 10元股价 / 1.0 比率 → 10 手 (#40 回归)"""
    out = _set_position_ratio_py(
        side="buy",
        symbol="601398.SH",
        ratio=1.0,
        avail_shares_by_symbol={},
        available_cash=10000,
        price=10.0,
        mode="quantity",
    )
    assert out["value"] == "10"


def test_trading_page_set_position_ratio_branch_on_side():
    """TradingPage 中的 setPositionRatio 必须按 side 分支：sell 用 avail，buy 用 cash (#40)"""
    html = to_xml(TradingPage())

    # 卖出分支
    assert "side === 'sell'" in html
    assert "_positionAvailBySymbol" in html
    assert "availShares * ratio" in html
    # 买入分支
    assert "availableCash" in html
    # 卖出/买入分支独立返回
    assert "当前选中股票无持仓可卖" in html


def test_position_table_avail_map_filters_invalid_symbols():
    """_positionAvailBySymbol 应只暴露有 symbol 的持仓，且 avail 为浮点 (#40)"""
    from qmt_gateway.web.pages.trading import PositionTable

    positions = [
        {"symbol": "601398.SH", "avail": 200},
        {"symbol": "", "avail": 999},  # 无 symbol 应被过滤
        {"symbol": None, "avail": 100},  # None 应被过滤
        {"symbol": "000001.SZ", "avail": "150"},  # 字符串数字也应可解析
    ]
    html = to_xml(PositionTable(positions))

    # JSON 序列化区段
    import re
    import json

    match = re.search(
        r"window\._positionAvailBySymbol\s*=\s*(\{.*?\});",
        html,
        re.DOTALL,
    )
    assert match is not None, "_positionAvailBySymbol 未在 HTML 中暴露"
    parsed = json.loads(match.group(1))
    assert parsed == {
        "601398.SH": 200.0,
        "000001.SZ": 150.0,
    }
    assert "" not in parsed
    assert "None" not in parsed
