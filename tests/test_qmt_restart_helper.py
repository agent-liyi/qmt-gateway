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
        executable=Path(r"C:\apps\qmt\bin.x64\XtItClient.exe"),
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
            executable=Path(r"C:\apps\qmt\bin.x64\XtItClient.exe"),
            launch_timeout=15.0,
            login_timeout=40.0,
        )
    except RuntimeError as exc:
        assert "登录窗口仍然可见" in str(exc)
    else:
        raise AssertionError("expected restart_qmt_in_interactive_session to fail after the retry budget was exhausted")

    assert len(attempts) == 2
    assert any("准备重试一次" in status for status in reports)