"""Trade service regression tests."""

import importlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qmt_gateway.core.enums import OrderSide, OrderStatus
from qmt_gateway.services.trade_service import TradeService


trade_service_module = importlib.import_module("qmt_gateway.services.trade_service")
process_utils_module = importlib.import_module("qmt_gateway.core.process_utils")


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


def test_trade_service_connection_status_tracks_disconnect():
    service = TradeService()

    service._set_connection_state(True, "交易接口已连接：demo")
    connected = service.get_connection_status()

    assert connected["connected"] is False
    assert connected["message"] == "交易接口已连接：demo"

    message = service.mark_disconnected("交易接口连接断开")
    disconnected = service.get_connection_status()

    assert message == "交易接口连接断开"
    assert disconnected["connected"] is False
    assert disconnected["message"] == "交易接口连接断开"


def test_mark_disconnected_schedules_auto_reconnect_when_enabled(monkeypatch):
    service = TradeService()
    service._account_id = "123456"
    service._qmt_path = r"C:\qmt\userdata_mini"
    scheduled = []

    def fake_config_get(key, default=None):
        if key == "auto_start_qmt":
            return True
        return getattr(trade_service_module.config, "_cache", {}).get(key, default)

    monkeypatch.setattr(trade_service_module.config, "get", fake_config_get)
    monkeypatch.setattr(
        service,
        "_schedule_auto_reconnect",
        lambda: scheduled.append(True) or True,
    )

    message = service.mark_disconnected("交易接口连接断开")

    assert message == "交易接口连接断开"
    assert scheduled == [True]


def test_connect_uses_unique_session_id_and_safe_cleanup(monkeypatch):
    service = TradeService()
    session_ids = []

    class FakeStockAccount:
        def __init__(self, account_id, account_type):
            self.account_id = account_id
            self.account_type = account_type

    class FakeTrader:
        def __init__(self, qmt_path, session_id):
            session_ids.append(session_id)

        def register_callback(self, callback):
            return None

        def start(self):
            return None

        def connect(self):
            return -1

        stop = None

    def fake_get_xtquant(name):
        if name == "XtQuantTrader":
            return FakeTrader
        if name == "StockAccount":
            return FakeStockAccount
        return object()

    generated_ids = iter([101, 202])
    monkeypatch.setattr(trade_service_module, "_get_xtquant", fake_get_xtquant)
    monkeypatch.setattr(service, "_prepare_xtquant_env", lambda qmt_path: None)
    monkeypatch.setattr(service, "_build_session_id", lambda: next(generated_ids))

    first = service.connect("8881457417", r"C:\apps\qmt\userdata_mini")
    second = service.connect("8881457417", r"C:\apps\qmt\userdata_mini")

    assert first is False
    assert second is False
    assert session_ids == [101, 202]
    assert service._trader is None


def test_resolve_qmt_client_path_from_userdata_dir(monkeypatch):
    service = TradeService()
    expected = Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe")

    monkeypatch.setattr(service, "_qmt_executable_exists", lambda path: path == expected)

    resolved = service._resolve_qmt_client_path(r"C:\apps\qmt\userdata_mini")

    assert resolved == expected


def test_restart_and_login_relaunches_client_and_reconnects(monkeypatch):
    service = TradeService()
    service._account_id = "8881457417"
    service._qmt_path = r"C:\apps\qmt\userdata_mini"
    executable = Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe")
    calls = []

    monkeypatch.setattr(service, "_get_current_session_id", lambda: 1)
    monkeypatch.setattr(service, "_resolve_qmt_client_path", lambda qmt_path: executable)
    monkeypatch.setattr(service, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(service, "discard_restart_password_token", lambda token: calls.append(("discard", token)))
    monkeypatch.setattr(service, "_set_connection_state", lambda connected, message: calls.append(("state", connected, message)) or message)
    monkeypatch.setattr(service, "_kill_qmt_process", lambda name: calls.append(("kill", name)) or "terminated")
    monkeypatch.setattr(service, "_launch_qmt_process", lambda path, password_token=None: calls.append(("launch", path, password_token)) or SimpleNamespace(pid=4321))
    monkeypatch.setattr(service, "_fill_qmt_login_password", lambda pid, password: calls.append(("fill", pid, password)))
    monkeypatch.setattr(
        service,
        "connect",
        lambda account_id, qmt_path: calls.append(("connect", account_id, qmt_path)) or True,
    )

    result = service.restart_and_login(
        qmt_path=r"C:\apps\qmt\userdata_mini",
        account_id="8881457417",
        qmt_password="trade-secret",
        kill_first=True,
    )

    assert result == {"success": True, "message": "QMT 已重启并重新连接交易接口"}
    assert calls == [
        "disconnect",
        ("state", False, "交易接口连接断开，正在重启 QMT"),
        ("kill", "XtMiniQmt.exe"),
        ("launch", executable, None),
        ("fill", 4321, "trade-secret"),
        ("connect", "8881457417", r"C:\apps\qmt\userdata_mini"),
        ("discard", None),
    ]


def test_restart_and_login_requires_password():
    service = TradeService()

    result = service.restart_and_login(
        qmt_path=r"C:\broker\userdata_mini",
        account_id="12345678",
        qmt_password="",
    )

    assert result == {"success": False, "error": "请输入交易密码"}


def test_restart_and_login_waits_for_login_window_before_connecting(monkeypatch):
    """填入密码后应等待登录窗口消失，再尝试 connect()。"""
    service = TradeService()
    service._account_id = "8881457417"
    service._qmt_path = r"C:\apps\qmt\userdata_mini"
    executable = Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe")
    calls = []

    monkeypatch.setattr(service, "_get_current_session_id", lambda: 1)
    monkeypatch.setattr(service, "_resolve_qmt_client_path", lambda qmt_path: executable)
    monkeypatch.setattr(service, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(service, "discard_restart_password_token", lambda token: calls.append(("discard", token)))
    monkeypatch.setattr(service, "_set_connection_state", lambda connected, message: calls.append(("state", connected, message)) or message)
    monkeypatch.setattr(service, "_kill_qmt_process", lambda name: "terminated")
    monkeypatch.setattr(service, "_launch_qmt_process", lambda path, password_token=None: SimpleNamespace(pid=4321))
    monkeypatch.setattr(service, "_fill_qmt_login_password", lambda pid, password: calls.append(("fill", pid, password)))
    monkeypatch.setattr(
        service,
        "_wait_for_login_window_to_close",
        lambda pid, timeout_sec: calls.append(("wait", pid, timeout_sec)) or True,
    )
    monkeypatch.setattr(
        service,
        "connect",
        lambda account_id, qmt_path: calls.append(("connect", account_id, qmt_path)) or True,
    )

    result = service.restart_and_login(
        qmt_path=r"C:\apps\qmt\userdata_mini",
        account_id="8881457417",
        qmt_password="trade-secret",
        kill_first=True,
    )

    assert result["success"] is True
    # 关键：fill 之后必须 wait，然后才 connect
    assert ("fill", 4321, "trade-secret") in calls
    fill_index = calls.index(("fill", 4321, "trade-secret"))
    wait_index = calls.index(("wait", 4321, 20.0))
    connect_index = calls.index(("connect", "8881457417", r"C:\apps\qmt\userdata_mini"))
    assert fill_index < wait_index < connect_index


def test_kill_qmt_process_ignores_missing_process_message(monkeypatch):
    service = TradeService()
    missing_message = '错误: 没有找到进程 "XtMiniQmt.exe"。'.encode("gbk")

    monkeypatch.setattr(
        process_utils_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=128, stdout=b"", stderr=missing_message),
    )

    assert service._kill_qmt_process("XtMiniQmt.exe") == "not-running"


def test_kill_qmt_process_raises_for_other_failures(monkeypatch):
    service = TradeService()

    monkeypatch.setattr(
        process_utils_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=5, stdout=b"", stderr=b"Access is denied."),
    )

    with pytest.raises(RuntimeError, match="access is denied"):
        service._kill_qmt_process("XtMiniQmt.exe")


def test_fill_qmt_login_password_uses_active_process_ids(monkeypatch):
    service = TradeService()
    seen_process_ids = []
    filled_passwords = []
    submitted = []
    calls = []
    fake_window = object()

    class FakeEdit:
        def set_focus(self):
            return None

        def set_edit_text(self, password):
            calls.append(("fill", password))
            filled_passwords.append(password)

    monkeypatch.setattr(service, "_load_pywinauto", lambda: (object(), lambda backend=None: object()))
    monkeypatch.setattr(service, "_collect_qmt_process_ids", lambda launcher_pid, executable_name: [9876])
    monkeypatch.setattr(
        service,
        "_iter_login_windows",
        lambda desktop, process_ids: seen_process_ids.append(tuple(process_ids)) or [fake_window],
    )
    monkeypatch.setattr(service, "_locate_password_edit", lambda window: calls.append(("locate", window)) or FakeEdit())
    monkeypatch.setattr(service, "_submit_login_window", lambda window: calls.append(("submit", window)) or submitted.append(window))

    service._fill_qmt_login_password(4321, "trade-secret")

    assert seen_process_ids == [(9876,)]
    assert filled_passwords == ["trade-secret"]
    assert submitted == [fake_window]
    assert calls == [
        ("locate", fake_window),
        ("fill", "trade-secret"),
        ("submit", fake_window),
    ]


def test_launch_qmt_process_uses_shell_open_and_detects_new_pid(monkeypatch):
    service = TradeService()
    executable = Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe")
    launch_calls = []
    pid_snapshots = iter([[], [8765]])

    monkeypatch.setattr(service, "_get_current_session_id", lambda: 1)
    monkeypatch.setattr(service, "_list_process_ids", lambda executable_name: next(pid_snapshots))
    monkeypatch.setattr(trade_service_module.os, "startfile", lambda path, cwd=None: launch_calls.append((path, cwd)))
    monkeypatch.setattr(trade_service_module.time, "sleep", lambda seconds: None)

    process = service._launch_qmt_process(executable)

    assert process.pid == 8765
    assert launch_calls == [(str(executable), str(executable.parent))]


def test_get_active_interactive_user_parses_quser_output(monkeypatch):
    service = TradeService()
    quser_output = (
        " 用户名                会话名             ID  状态    空闲时间   登录时间\n"
        " aaron                 rdp-tcp#2           1  运行中          .  2026/5/22 9:25\n"
    ).encode("gbk")

    monkeypatch.setattr(
        trade_service_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=quser_output, stderr=b""),
    )

    assert service._get_active_interactive_user() == ("aaron", 1)


def test_launch_qmt_process_uses_interactive_task_in_session_zero(monkeypatch):
    service = TradeService()
    executable = Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe")
    calls = []

    monkeypatch.setattr(service, "_get_current_session_id", lambda: 0)
    monkeypatch.setattr(service, "_list_process_ids", lambda executable_name: [])
    monkeypatch.setattr(
        service,
        "_launch_qmt_process_in_interactive_session",
        lambda executable_path, before_pids, password_token: calls.append((executable_path, before_pids, password_token)) or SimpleNamespace(pid=9988),
    )

    process = service._launch_qmt_process(executable, password_token="token-1")

    assert process.pid == 9988
    assert calls == [(executable, set(), "token-1")]


def test_restart_password_token_is_consumed_once():
    service = TradeService()

    token = service.issue_restart_password_token("trade-secret")

    assert service.consume_restart_password_token(token) == "trade-secret"
    assert service.consume_restart_password_token(token) is None


def test_helper_info_status_is_not_treated_as_failure():
    service = TradeService()

    token = service.issue_restart_password_token("trade-secret")
    service.record_restart_helper_status(token, "INFO: 已通过布局坐标填入并提交 QMT 登录")

    assert service.get_restart_helper_status(token) is None
    token = service.issue_restart_password_token("trade-secret")

    assert service.consume_restart_password_token(token) == "trade-secret"
    assert service.consume_restart_password_token(token) is None


def test_refresh_positions_snapshot_persists_to_db(monkeypatch):
    """成交回报后应刷新持仓快照到数据库。"""
    service = TradeService()
    service._connected = True
    service._account = object()

    monkeypatch.setattr(
        service,
        "get_positions",
        lambda: [
            {
                "symbol": "601398.SH",
                "name": "工商银行",
                "shares": 0,
                "avail": 0,
                "price": 7.0,
                "cost": 7.3601,
                "profit": 0,
                "market_value": 0,
            }
        ],
    )

    deleted = []
    upserted = []

    monkeypatch.setattr(
        trade_service_module.db,
        "execute_write",
        lambda sql, params=(): deleted.append((sql, params)),
    )

    def fake_upsert(table, record, pk):
        upserted.append((table, record, pk))

    fake_positions = SimpleNamespace(upsert=fake_upsert)
    monkeypatch.setattr(trade_service_module.db, "__getitem__", lambda key: fake_positions)

    service.refresh_positions_snapshot()

    assert any("delete from positions" in sql for sql, _ in deleted)
    assert len(upserted) == 0


def test_persist_callback_trade_refreshes_positions(monkeypatch):
    """成交回调后应触发持仓刷新。"""
    service = TradeService()
    refreshed = []

    monkeypatch.setattr(
        trade_service_module.db,
        "insert_trade",
        lambda trade: None,
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "get_order_by_foid",
        lambda foid: None,
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "update_order",
        lambda qtoid, **kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "refresh_positions_snapshot",
        lambda: refreshed.append(True),
    )

    xt_trade = SimpleNamespace(
        traded_id="t-1",
        order_remark="q-1",
        stock_code="601398.SH",
        order_type=24,
        traded_price=7.29,
        traded_volume=100,
        traded_amount=729.0,
        traded_time=time.time(),
        order_id="o-1",
        order_sysid="c-1",
    )

    service.persist_callback_trade(xt_trade)

    assert refreshed == [True]


@pytest.mark.parametrize(
    ("method_name", "expected_side"),
    [
        ("buy", OrderSide.BUY),
        ("sell", OrderSide.SELL),
    ],
)
def test_order_wrappers_defer_xtconstant_lookup_until_place_order(
    monkeypatch, method_name, expected_side
):
    service = TradeService()
    captured = []

    def fake_place_order(symbol, price, shares, side, qtoid="", strategy_id=""):
        captured.append((symbol, price, shares, side, qtoid, strategy_id))
        return {"success": True}

    monkeypatch.setattr(service, "_place_order", fake_place_order)
    monkeypatch.setattr(
        trade_service_module,
        "_get_xtquant",
        lambda name: (_ for _ in ()).throw(AssertionError("wrapper should not load xtconstant")),
    )

    result = getattr(service, method_name)(
        "601398.SH", 7.29, 100, qtoid="q-1", strategy_id="grid"
    )

    assert result == {"success": True}
    assert captured == [
        ("601398.SH", 7.29, 100, expected_side, "q-1", "grid")
    ]


def test_persist_callback_trade_marks_partial_from_cumulative_fills(monkeypatch):
    service = TradeService()
    stored_trades = []
    updated = {}
    scheduled = []

    monkeypatch.setattr(
        service,
        "_persist_trade_snapshot",
        lambda trade, *, foid, cid: stored_trades.append(SimpleNamespace(shares=trade["shares"])),
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "get_order_by_foid",
        lambda foid: SimpleNamespace(qtoid="q-1", shares=1000),
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "get_trades_by_qtoid",
        lambda qtoid: list(stored_trades),
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "update_order",
        lambda qtoid, **kwargs: updated.update({"qtoid": qtoid, **kwargs}),
    )
    monkeypatch.setattr(service, "_schedule_position_snapshot", lambda: scheduled.append(True))

    xt_trade = SimpleNamespace(
        traded_id="t-1",
        order_remark="q-1",
        stock_code="601398.SH",
        order_type=24,
        traded_price=7.29,
        traded_volume=400,
        traded_amount=2916.0,
        traded_time=time.time(),
        order_id="o-1",
        order_sysid="c-1",
    )

    service.persist_callback_trade(xt_trade)

    assert updated["qtoid"] == "q-1"
    assert updated["filled"] == 400.0
    assert updated["status"] == OrderStatus.PART_SUCC
    assert scheduled == [True]


def test_persist_callback_trade_marks_succeeded_when_cumulative_fills_complete(monkeypatch):
    service = TradeService()
    existing_trades = [SimpleNamespace(shares=400.0)]
    current_trades = []
    updated = {}

    monkeypatch.setattr(
        service,
        "_persist_trade_snapshot",
        lambda trade, *, foid, cid: current_trades.append(SimpleNamespace(shares=trade["shares"])),
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "get_order_by_foid",
        lambda foid: SimpleNamespace(qtoid="q-1", shares=1000),
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "get_trades_by_qtoid",
        lambda qtoid: existing_trades + current_trades,
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "update_order",
        lambda qtoid, **kwargs: updated.update({"qtoid": qtoid, **kwargs}),
    )
    monkeypatch.setattr(service, "_schedule_position_snapshot", lambda: None)

    xt_trade = SimpleNamespace(
        traded_id="t-2",
        order_remark="q-1",
        stock_code="601398.SH",
        order_type=24,
        traded_price=7.30,
        traded_volume=600,
        traded_amount=4380.0,
        traded_time=time.time(),
        order_id="o-1",
        order_sysid="c-2",
    )

    service.persist_callback_trade(xt_trade)

    assert updated["qtoid"] == "q-1"
    assert updated["filled"] == 1000.0
    assert updated["status"] == OrderStatus.SUCCEEDED


def test_try_auto_start_qmt_succeeds_on_first_attempt(monkeypatch):
    service = TradeService()
    service._auto_start_max_retries = 2
    calls = []

    monkeypatch.setattr(service, "_decrypt_qmt_password", lambda: "trade-secret")
    monkeypatch.setattr(
        service,
        "restart_and_login",
        lambda **kwargs: calls.append(kwargs) or {"success": True, "message": "ok"},
    )
    monkeypatch.setattr(trade_service_module.time, "sleep", lambda seconds: None)

    result = service.try_auto_start_qmt(qmt_path=r"C:\qmt", account_id="123456")

    assert result is True
    assert len(calls) == 1
    assert calls[0]["qmt_password"] == "trade-secret"
    assert calls[0]["kill_first"] is False


def test_try_auto_start_qmt_retries_and_succeeds(monkeypatch):
    service = TradeService()
    service._auto_start_max_retries = 2
    attempts = []

    monkeypatch.setattr(service, "_decrypt_qmt_password", lambda: "trade-secret")

    def fake_restart(**kwargs):
        attempts.append(True)
        if len(attempts) < 3:
            return {"success": False, "error": "not ready"}
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(service, "restart_and_login", fake_restart)
    monkeypatch.setattr(trade_service_module.time, "sleep", lambda seconds: None)

    result = service.try_auto_start_qmt(qmt_path=r"C:\qmt", account_id="123456")

    assert result is True
    assert len(attempts) == 3


def test_try_auto_start_qmt_retries_max_then_gives_up(monkeypatch):
    service = TradeService()
    service._auto_start_max_retries = 2
    attempts = []

    monkeypatch.setattr(service, "_decrypt_qmt_password", lambda: "trade-secret")
    monkeypatch.setattr(
        service,
        "restart_and_login",
        lambda **kwargs: attempts.append(True) or {"success": False, "error": "fail"},
    )
    monkeypatch.setattr(trade_service_module.time, "sleep", lambda seconds: None)

    result = service.try_auto_start_qmt(qmt_path=r"C:\qmt", account_id="123456")

    assert result is False
    assert len(attempts) == 3


def test_try_auto_start_qmt_skips_when_no_password(monkeypatch):
    service = TradeService()

    monkeypatch.setattr(service, "_decrypt_qmt_password", lambda: None)

    result = service.try_auto_start_qmt(qmt_path=r"C:\qmt", account_id="123456")

    assert result is False


def test_decrypt_qmt_password_uses_auto_start_encrypted(monkeypatch):
    service = TradeService()

    fake_settings = SimpleNamespace(
        qmt_password_auto_start="encrypted-auto-start",
        qmt_password_encrypted="encrypted-user",
        qmt_password_salt="salt",
    )

    monkeypatch.setattr(trade_service_module.db, "get_settings", lambda: fake_settings)

    import qmt_gateway.core.crypto_utils as crypto_module
    decrypted = []
    monkeypatch.setattr(
        crypto_module,
        "decrypt_for_auto_start",
        lambda payload: decrypted.append(payload) or "my-password",
    )

    result = service._decrypt_qmt_password()

    assert result == "my-password"
    assert decrypted == ["encrypted-auto-start"]


def test_persist_callback_trade_does_not_block_on_qmt(monkeypatch):
    """成交回调不应同步调用 QMT，否则会在 QMT 回调线程中死锁 (#41)

    on_stock_trade 回调运行在 QMT 库的内部线程。
    refresh_positions_snapshot() 内部需要调用 self._trader.query_stock_positions()，
    这会从 QMT 回调中再次进入 QMT 库，导致死锁或挂起，并最终使整个网关无响应。
    修复：persistence 完成后，只调度后台线程执行刷新，主流程立即返回。
    """
    import threading
    import time
    from types import SimpleNamespace as NS

    service = TradeService()

    xt_trade = NS(
        traded_id="t-1",
        order_remark="q-1",
        stock_code="601398.SH",
        order_type=24,
        traded_price=7.29,
        traded_volume=100,
        traded_amount=729.0,
        traded_time=time.time(),
        order_id="o-1",
        order_sysid="c-1",
    )

    snapshot_started = threading.Event()
    snapshot_finished = threading.Event()

    def slow_snapshot():
        snapshot_started.set()
        time.sleep(0.5)  # 模拟慢的 QMT 调用
        snapshot_finished.set()

    monkeypatch.setattr(service, "_persist_trade_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(
        trade_service_module.db,
        "get_order_by_foid",
        lambda foid: None,
    )
    monkeypatch.setattr(
        trade_service_module.db,
        "update_order",
        lambda qtoid, **kwargs: None,
    )
    monkeypatch.setattr(service, "refresh_positions_snapshot", slow_snapshot)

    start = time.monotonic()
    service.persist_callback_trade(xt_trade)
    elapsed = time.monotonic() - start

    # 主流程应在 0.1 秒内返回（不等待 QMT 调用）
    assert elapsed < 0.1, f"主流程耗时 {elapsed:.3f}s，应在后台线程中执行"
    # 后台线程已启动但还没完成（因为有 0.5s 延迟）
    assert snapshot_started.is_set()
    assert not snapshot_finished.is_set()

    # 等待后台线程完成
    snapshot_finished.wait(timeout=2.0)
    assert snapshot_finished.is_set()
