"""Trade service regression tests."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

"""Trade service regression tests."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    expected = Path(r"C:\apps\qmt\bin.x64\XtItClient.exe")

    monkeypatch.setattr(service, "_qmt_executable_exists", lambda path: path == expected)

    resolved = service._resolve_qmt_client_path(r"C:\apps\qmt\userdata_mini")

    assert resolved == expected


def test_restart_qmt_relaunches_client_and_reconnects(monkeypatch):
    service = TradeService()
    service._account_id = "8881457417"
    service._qmt_path = r"C:\apps\qmt\userdata_mini"
    executable = Path(r"C:\apps\qmt\bin.x64\XtItClient.exe")
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
        "_connect_with_helper_status",
        lambda account_id, qmt_path, password_token=None: calls.append(("connect", account_id, qmt_path, password_token)) or {"success": True, "message": "QMT 已重启并重新连接交易接口"},
    )

    result = service.restart_qmt("trade-secret")

    assert result == {"success": True, "message": "QMT 已重启并重新连接交易接口"}
    assert calls == [
        "disconnect",
        ("state", False, "交易接口连接断开，正在重启 QMT"),
        ("kill", "XtItClient.exe"),
        ("launch", executable, None),
        ("fill", 4321, "trade-secret"),
        ("connect", "8881457417", r"C:\apps\qmt\userdata_mini", None),
        ("discard", None),
    ]


def test_restart_qmt_requires_password():
    service = TradeService()

    result = service.restart_qmt("")

    assert result == {"success": False, "error": "请输入交易密码"}


def test_kill_qmt_process_ignores_missing_process_message(monkeypatch):
    service = TradeService()
    missing_message = '错误: 没有找到进程 "XtItClient.exe"。'.encode("gbk")

    monkeypatch.setattr(
        trade_service_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=128, stdout=b"", stderr=missing_message),
    )

    assert service._kill_qmt_process("XtItClient.exe") == "not-running"


def test_kill_qmt_process_raises_for_other_failures(monkeypatch):
    service = TradeService()

    monkeypatch.setattr(
        trade_service_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=5, stdout=b"", stderr=b"Access is denied."),
    )

    with pytest.raises(RuntimeError, match="access is denied"):
        service._kill_qmt_process("XtItClient.exe")


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
    monkeypatch.setattr(trade_service_module, "ensure_independent_trading_checked", lambda window: calls.append(("check", window)) or True)
    monkeypatch.setattr(service, "_locate_password_edit", lambda window: calls.append(("locate", window)) or FakeEdit())
    monkeypatch.setattr(service, "_submit_login_window", lambda window: calls.append(("submit", window)) or submitted.append(window))

    service._fill_qmt_login_password(4321, "trade-secret")

    assert seen_process_ids == [(9876,)]
    assert filled_passwords == ["trade-secret"]
    assert submitted == [fake_window]
    assert calls == [
        ("check", fake_window),
        ("locate", fake_window),
        ("fill", "trade-secret"),
        ("submit", fake_window),
    ]


def test_launch_qmt_process_uses_shell_open_and_detects_new_pid(monkeypatch):
    service = TradeService()
    executable = Path(r"C:\apps\qmt\bin.x64\XtItClient.exe")
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
    executable = Path(r"C:\apps\qmt\bin.x64\XtItClient.exe")
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