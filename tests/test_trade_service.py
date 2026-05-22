"""Trade service regression tests."""

import importlib
from types import SimpleNamespace

from qmt_gateway.core.enums import OrderStatus
from qmt_gateway.services.trade_service import TradeService


trade_service_module = importlib.import_module("qmt_gateway.services.trade_service")


def test_cancel_order_returns_recent_cancel_error(monkeypatch):
    service = TradeService()
    service._connected = True
    service._account = object()
    service._cancel_error_wait_timeout_sec = 0.2

    fake_order = SimpleNamespace(foid="123456", qtoid="qtoid-1")
    monkeypatch.setattr(trade_service_module.db, "get_order", lambda order_id: fake_order)
    monkeypatch.setattr(trade_service_module.db, "get_order_by_foid", lambda order_id: None)
    monkeypatch.setattr(trade_service_module.db, "update_order", lambda qtoid, **kwargs: None)

    class FakeTrader:
        def cancel_order_stock(self, account, foid):
            service.record_cancel_error(
                SimpleNamespace(order_id=str(foid), error_msg="超过交易时间")
            )
            return 0

    service._trader = FakeTrader()

    result = service.cancel_order("qtoid-1")

    assert result == {"success": False, "error": "超过交易时间"}


def test_cancel_order_updates_status_when_no_callback_error(monkeypatch):
    service = TradeService()
    service._connected = True
    service._account = object()
    service._cancel_error_wait_timeout_sec = 0

    fake_order = SimpleNamespace(foid="123456", qtoid="qtoid-1")
    updated = {}

    monkeypatch.setattr(trade_service_module.db, "get_order", lambda order_id: fake_order)
    monkeypatch.setattr(trade_service_module.db, "get_order_by_foid", lambda order_id: None)
    monkeypatch.setattr(
        trade_service_module.db,
        "update_order",
        lambda qtoid, **kwargs: updated.update({"qtoid": qtoid, **kwargs}),
    )

    class FakeTrader:
        def cancel_order_stock(self, account, foid):
            return 0

    service._trader = FakeTrader()

    result = service.cancel_order("qtoid-1")

    assert result == {"success": True, "qtoid": "qtoid-1"}
    assert updated["qtoid"] == "qtoid-1"
    assert updated["status"] == OrderStatus.CANCELED