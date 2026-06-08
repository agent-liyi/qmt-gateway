from pathlib import Path
from types import SimpleNamespace

import qmt_gateway.qmt_restart_helper as helper


def _make_clock(step: float = 0.1):
    state = {"value": 0.0}

    def fake_monotonic():
        state["value"] += step
        return state["value"]

    return fake_monotonic


def test_wait_for_login_completion_succeeds_when_login_window_disappears(monkeypatch):
    window = SimpleNamespace(handle=0x1234, element_info=SimpleNamespace(handle=0x1234))
    states = iter([[window], []])

    monkeypatch.setattr(helper, "_get_probable_login_windows", lambda desktop, process_ids: next(states))
    monkeypatch.setattr(helper.time, "monotonic", _make_clock())
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)

    assert helper._wait_for_login_completion(object(), [1001], window, 2.0) is True


def test_submit_login_attempt_checks_independent_trading_before_password(monkeypatch):
    window = object()
    password_edit = object()
    calls = []

    monkeypatch.setattr(helper, "ensure_independent_trading_checked", lambda target: calls.append(("check", target)) or True)
    monkeypatch.setattr(helper, "locate_password_input", lambda target: calls.append(("locate", target)) or password_edit)
    monkeypatch.setattr(helper, "populate_password_input", lambda window, control, password: calls.append(("fill", window, control, password)))
    monkeypatch.setattr(helper, "submit_login_window", lambda target: calls.append(("submit", target)))

    strategy = helper._submit_login_attempt(window, "trade-secret")

    assert strategy == "控件树"
    assert calls == [
        ("check", window),
        ("locate", window),
        ("fill", window, password_edit, "trade-secret"),
        ("submit", window),
    ]


def test_restart_helper_retries_once_when_login_window_stays_visible(monkeypatch):
    window = SimpleNamespace(
        handle=0x1234,
        element_info=SimpleNamespace(handle=0x1234),
    )
    reports = []
    attempts = []
    ready_results = iter([False, True])

    monkeypatch.setattr(helper, "_fetch_password", lambda base_url, token: "trade-secret")
    monkeypatch.setattr(helper.os, "startfile", lambda *args, **kwargs: None)
    monkeypatch.setattr(helper, "_list_process_ids", lambda executable_name: [4321])
    monkeypatch.setattr(helper, "_wait_for_new_process", lambda executable_name, before_pids, timeout_sec: [4321])
    monkeypatch.setattr(helper, "Desktop", lambda backend=None: object())
    monkeypatch.setattr(helper, "_get_probable_login_windows", lambda desktop, process_ids: [window])
    monkeypatch.setattr(helper, "_submit_login_attempt", lambda target_window, password: attempts.append((target_window, password)) or "布局坐标")
    monkeypatch.setattr(helper, "_wait_for_login_completion", lambda desktop, process_ids, submitted_window, timeout_sec: next(ready_results))
    monkeypatch.setattr(helper, "describe_window", lambda target_window: "title=国金证券QMT交易端")
    monkeypatch.setattr(helper, "_report_status", lambda base_url, token, status: reports.append(status))
    monkeypatch.setattr(helper.time, "monotonic", _make_clock())
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)

    helper.restart_qmt_in_interactive_session(
        base_url="http://127.0.0.1:8130",
        token="token-1",
        executable=Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe"),
        launch_timeout=15.0,
        login_timeout=40.0,
    )

    assert len(attempts) == 2
    assert any("准备重试一次" in status for status in reports)
    assert any("登录窗口已消失" in status for status in reports)


def test_restart_helper_fails_after_retry_budget_is_exhausted(monkeypatch):
    window = SimpleNamespace(
        handle=0x1234,
        element_info=SimpleNamespace(handle=0x1234),
    )
    reports = []
    attempts = []

    monkeypatch.setattr(helper, "_fetch_password", lambda base_url, token: "trade-secret")
    monkeypatch.setattr(helper.os, "startfile", lambda *args, **kwargs: None)
    monkeypatch.setattr(helper, "_list_process_ids", lambda executable_name: [4321])
    monkeypatch.setattr(helper, "_wait_for_new_process", lambda executable_name, before_pids, timeout_sec: [4321])
    monkeypatch.setattr(helper, "Desktop", lambda backend=None: object())
    monkeypatch.setattr(helper, "_get_probable_login_windows", lambda desktop, process_ids: [window])
    monkeypatch.setattr(helper, "_submit_login_attempt", lambda target_window, password: attempts.append((target_window, password)) or "布局坐标")
    monkeypatch.setattr(helper, "_wait_for_login_completion", lambda desktop, process_ids, submitted_window, timeout_sec: False)
    monkeypatch.setattr(helper, "describe_window", lambda target_window: "title=国金证券QMT交易端")
    monkeypatch.setattr(helper, "_report_status", lambda base_url, token, status: reports.append(status))
    monkeypatch.setattr(helper.time, "monotonic", _make_clock())
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)

    try:
        helper.restart_qmt_in_interactive_session(
            base_url="http://127.0.0.1:8130",
            token="token-1",
            executable=Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe"),
            launch_timeout=15.0,
            login_timeout=40.0,
        )
    except RuntimeError as exc:
        assert "登录窗口仍然可见" in str(exc)
    else:
        raise AssertionError("expected restart_qmt_in_interactive_session to fail after the retry budget was exhausted")

    assert len(attempts) == 2
    assert any("准备重试一次" in status for status in reports)


def test_restart_helper_sleeps_before_retry(monkeypatch):
    window = SimpleNamespace(
        handle=0x1234,
        element_info=SimpleNamespace(handle=0x1234),
    )
    reports = []
    sleeps = []
    ready_results = iter([False, True])

    monkeypatch.setattr(helper, "_fetch_password", lambda base_url, token: "trade-secret")
    monkeypatch.setattr(helper.os, "startfile", lambda *args, **kwargs: None)
    monkeypatch.setattr(helper, "_list_process_ids", lambda executable_name: [4321])
    monkeypatch.setattr(helper, "_wait_for_new_process", lambda executable_name, before_pids, timeout_sec: [4321])
    monkeypatch.setattr(helper, "Desktop", lambda backend=None: object())
    monkeypatch.setattr(helper, "_get_probable_login_windows", lambda desktop, process_ids: [window])
    monkeypatch.setattr(helper, "_submit_login_attempt", lambda target_window, password: "布局坐标")
    monkeypatch.setattr(helper, "_wait_for_login_completion", lambda desktop, process_ids, submitted_window, timeout_sec: next(ready_results))
    monkeypatch.setattr(helper, "describe_window", lambda target_window: "title=国金证券QMT交易端")
    monkeypatch.setattr(helper, "_report_status", lambda base_url, token, status: reports.append(status))
    monkeypatch.setattr(helper.time, "monotonic", _make_clock())
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleeps.append(seconds))

    helper.restart_qmt_in_interactive_session(
        base_url="http://127.0.0.1:8130",
        token="token-1",
        executable=Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe"),
        launch_timeout=15.0,
        login_timeout=40.0,
        retry_delay=5.0,
    )

    assert any("等待 5.0 秒" in status and "准备重试一次" in status for status in reports)
    assert 5.0 in sleeps


def test_restart_helper_retries_when_submit_login_attempt_raises(monkeypatch):
    """If the first attempt raises (e.g. user interference blocked input),
    the helper should still wait, retry once, and report the warning clearly.
    """
    window = SimpleNamespace(
        handle=0x1234,
        element_info=SimpleNamespace(handle=0x1234),
    )
    reports = []
    sleeps = []
    attempt_counter = {"n": 0}

    def _flaky(target_window, password):
        attempt_counter["n"] += 1
        if attempt_counter["n"] == 1:
            raise RuntimeError("未找到 QMT 登录密码输入框")
        return "布局坐标"

    monkeypatch.setattr(helper, "_fetch_password", lambda base_url, token: "trade-secret")
    monkeypatch.setattr(helper.os, "startfile", lambda *args, **kwargs: None)
    monkeypatch.setattr(helper, "_list_process_ids", lambda executable_name: [4321])
    monkeypatch.setattr(helper, "_wait_for_new_process", lambda executable_name, before_pids, timeout_sec: [4321])
    monkeypatch.setattr(helper, "Desktop", lambda backend=None: object())
    monkeypatch.setattr(helper, "_get_probable_login_windows", lambda desktop, process_ids: [window])
    monkeypatch.setattr(helper, "_submit_login_attempt", _flaky)
    monkeypatch.setattr(helper, "_wait_for_login_completion", lambda desktop, process_ids, submitted_window, timeout_sec: True)
    monkeypatch.setattr(helper, "describe_window", lambda target_window: "title=国金证券QMT交易端")
    monkeypatch.setattr(helper, "_report_status", lambda base_url, token, status: reports.append(status))
    monkeypatch.setattr(helper.time, "monotonic", _make_clock())
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleeps.append(seconds))

    helper.restart_qmt_in_interactive_session(
        base_url="http://127.0.0.1:8130",
        token="token-1",
        executable=Path(r"C:\apps\qmt\bin.x64\XtMiniQmt.exe"),
        launch_timeout=15.0,
        login_timeout=40.0,
        retry_delay=4.0,
    )

    assert any("第 1/2 次自动登录失败" in status for status in reports)
    assert 4.0 in sleeps
    assert any("等待 4.0 秒" in status for status in reports)
    assert any("登录窗口已消失" in status for status in reports)