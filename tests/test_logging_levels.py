"""Regression tests for debug log levels."""

import datetime
import importlib
import logging

import qmt_gateway.apis.trade as trade_api
from qmt_gateway.db.models import Asset, Stock
from qmt_gateway.services.quote_service import QuoteService
from qmt_gateway.services.stock_service import StockService
from qmt_gateway.services.trade_service import TradeCallback, TradeService


quote_service_module = importlib.import_module("qmt_gateway.services.quote_service")
stock_service_module = importlib.import_module("qmt_gateway.services.stock_service")


class FakeLogger:
    def __init__(self):
        self.records = []

    def debug(self, message, *args):
        self.records.append(("DEBUG", message, args))

    def info(self, message, *args):
        self.records.append(("INFO", message, args))

    def warning(self, message, *args):
        self.records.append(("WARNING", message, args))

    def error(self, message, *args):
        self.records.append(("ERROR", message, args))

    def critical(self, message, *args):
        self.records.append(("CRITICAL", message, args))


def _messages(records, level):
    return [message for record_level, message, _ in records if record_level == level]


def test_stock_service_search_uses_debug_level(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(stock_service_module, "logger", fake_logger)

    service = StockService()
    service._stocks = {
        "600000.SH": Stock(symbol="600000.SH", name="浦发银行", pinyin="pfyh", last_close=10.0),
        "000001.SZ": Stock(symbol="000001.SZ", name="平安银行", pinyin="payh", last_close=11.0),
    }

    # 按代码前缀匹配
    results = service.search_stocks("60")
    assert [item.symbol for item in results] == ["600000.SH"]

    results = service.search_stocks("00")
    assert [item.symbol for item in results] == ["000001.SZ"]

    # 按名称子串匹配
    results = service.search_stocks("银行")
    assert len(results) == 2

    # 按拼音子串匹配
    results = service.search_stocks("pa")
    assert [item.symbol for item in results] == ["000001.SZ"]

    # 已加载 stocks 时搜索不应产生日志
    assert not _messages(fake_logger.records, "INFO")
    assert not _messages(fake_logger.records, "WARNING")


def test_trade_asset_debug_logs_use_debug_level(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_api, "logger", fake_logger)

    asset = Asset(
        portfolio_id="default",
        dt=datetime.date.today(),
        principal=20000.0,
        cash=18567.67,
        frozen_cash=0.0,
        market_value=0.0,
        total=18567.67,
    )
    monkeypatch.setattr(trade_api, "_get_latest_asset", lambda portfolio_id: asset)
    monkeypatch.setattr(trade_api, "_snapshot_asset", lambda portfolio_id: None)

    result = trade_api.get_latest_asset_data()

    assert result["total"] == 18567.67
    debug_messages = _messages(fake_logger.records, "DEBUG")
    assert any("debug asset cache read" in message for message in debug_messages)
    assert any("debug asset response" in message for message in debug_messages)
    assert not any("debug asset" in message for message in _messages(fake_logger.records, "INFO"))


def test_quote_service_debug_logs_use_debug_level(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(quote_service_module, "logger", fake_logger)

    service = QuoteService()

    class FakeXtdata:
        def subscribe_whole_quote(self, codes, callback):
            return 2 if codes == service.INDEX_CODES else 1

        def unsubscribe_quote(self, seq):
            return None

    xtdata = FakeXtdata()

    service._subscribe(xtdata)
    service._unsubscribe(xtdata)

    debug_messages = _messages(fake_logger.records, "DEBUG")
    assert any("debug quote subscribe stocks" in message for message in debug_messages)
    assert any("debug quote subscribe indices" in message for message in debug_messages)
    assert any("debug quote unsubscribe" in message for message in debug_messages)
    assert not any("debug quote" in message for message in _messages(fake_logger.records, "INFO"))


def test_trade_disconnect_uses_critical_level(monkeypatch):
    trade_service_module = importlib.import_module("qmt_gateway.services.trade_service")
    fake_logger = FakeLogger()
    monkeypatch.setattr(trade_service_module, "logger", fake_logger)

    service = TradeService()
    service._set_connection_state(True, "交易接口已连接：demo")

    callback = TradeCallback(service)
    callback.on_disconnected()

    critical_messages = _messages(fake_logger.records, "CRITICAL")
    assert any("交易接口连接断开" in message for message in critical_messages)
    assert service.get_connection_status()["connected"] is False
    assert not _messages(fake_logger.records, "WARNING")


def test_uvicorn_access_log_console_warning_and_file_info(tmp_path):
    """Uvicorn access logs should not spam console INFO but remain in access.log."""
    from qmt_gateway.access_log import configure_access_log

    access_logger = logging.getLogger("uvicorn.access")
    original_handlers = list(access_logger.handlers)
    original_level = access_logger.level
    original_propagate = access_logger.propagate
    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    access_logger.handlers = [stream]

    try:
        path = configure_access_log(tmp_path)
        access_logger.info('192.168.0.100:53041 - "GET /api/trade/positions?view=table HTTP/1.1" 200 OK')

        assert stream.level == logging.WARNING
        assert path == tmp_path / "access.log"
        assert "GET /api/trade/positions?view=table" in path.read_text(encoding="utf-8")
    finally:
        for handler in access_logger.handlers:
            if handler not in original_handlers:
                handler.close()
        access_logger.handlers = original_handlers
        access_logger.setLevel(original_level)
        access_logger.propagate = original_propagate
