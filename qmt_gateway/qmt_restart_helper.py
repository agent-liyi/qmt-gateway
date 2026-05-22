"""Interactive-session helper for restarting QMT and filling the login password."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from csv import reader as csv_reader
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pywinauto import Desktop
from qmt_gateway.qmt_login_automation import (
    describe_window,
    is_probable_login_window,
    iter_login_windows,
    locate_password_input,
    populate_password_input,
    populate_password_via_layout,
    populate_password_via_tab,
    submit_login_via_layout,
    submit_login_window,
)


def _list_process_ids(executable_name: str) -> list[int]:
    import subprocess

    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {executable_name}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=15,
        check=False,
    )
    process_ids: list[int] = []
    for row in csv_reader(io.StringIO(result.stdout)):
        if len(row) < 2:
            continue
        if str(row[0] or "").strip().lower() != executable_name.lower():
            continue
        try:
            process_ids.append(int(str(row[1]).replace(",", "").strip()))
        except ValueError:
            continue
    return process_ids


def _fetch_password(base_url: str, token: str) -> str:
    query = urlencode({"token": token})
    with urlopen(f"{base_url.rstrip('/')}/api/trade/restart-qmt/password?{query}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    password = str(payload.get("password", "") or "")
    if not password:
        raise RuntimeError("未获取到 QMT 重启密码")
    return password


def _report_status(base_url: str, token: str, status: str) -> None:
    data = urlencode({"token": token, "status": status}).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/api/trade/restart-qmt/helper-status",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10):
            return
    except Exception:
        return


def _wait_for_new_process(executable_name: str, before_pids: set[int], timeout_sec: float) -> list[int]:
    deadline = time.monotonic() + max(float(timeout_sec), 1.0)
    while time.monotonic() < deadline:
        current_pids = _list_process_ids(executable_name)
        if any(pid not in before_pids for pid in current_pids):
            return current_pids
        time.sleep(0.5)
    raise RuntimeError(f"未在预期时间内观测到新的 QMT 进程: image={executable_name}")


def _window_handle(window) -> int | None:
    handle = getattr(window, "handle", None)
    if handle:
        return int(handle)
    element = getattr(window, "element_info", None)
    if element is None:
        return None
    element_handle = getattr(element, "handle", None)
    return int(element_handle) if element_handle else None


def _get_probable_login_windows(desktop, process_ids: list[int] | set[int]):
    return [window for window in iter_login_windows(desktop, process_ids) if is_probable_login_window(window)]


def _submit_login_attempt(window, password: str) -> str:
    try:
        password_edit = locate_password_input(window)
        populate_password_input(password_edit, password)
        submit_login_window(window)
        return "控件树"
    except Exception as exc:
        locate_error = exc

    try:
        populate_password_via_tab(window, password)
        submit_login_window(window)
        return "Tab 导航"
    except Exception as exc:
        tab_error = exc

    if not is_probable_login_window(window):
        raise RuntimeError(f"候选窗口仍像启动页，等待登录页出现: {describe_window(window)}")

    try:
        populate_password_via_layout(window, password)
        submit_login_via_layout(window)
        return "布局坐标"
    except Exception as exc:
        raise RuntimeError(
            f"{locate_error}; fallback={tab_error}; layout={exc}; window={describe_window(window)}"
        ) from exc


def _wait_for_login_completion(desktop, process_ids: list[int] | set[int], submitted_window, timeout_sec: float) -> bool:
    submitted_handle = _window_handle(submitted_window)
    deadline = time.monotonic() + max(float(timeout_sec), 0.5)

    while time.monotonic() < deadline:
        windows = _get_probable_login_windows(desktop, process_ids)
        if not windows:
            return True
        if submitted_handle is not None:
            handles = {_window_handle(window) for window in windows}
            if submitted_handle not in handles:
                return True
        time.sleep(0.5)

    return False


def restart_qmt_in_interactive_session(base_url: str, token: str, executable: Path, launch_timeout: float, login_timeout: float) -> None:
    password = _fetch_password(base_url, token)
    before_pids = set(_list_process_ids(executable.name))

    try:
        os.startfile(str(executable), cwd=str(executable.parent))
    except TypeError:
        os.startfile(str(executable))

    current_pids = _wait_for_new_process(executable.name, before_pids, launch_timeout)

    for backend in ("uia", "win32"):
        desktop = Desktop(backend=backend)
        deadline = time.monotonic() + max(float(login_timeout), 1.0)
        last_error: Exception | None = None
        retries_remaining = 1
        while time.monotonic() < deadline:
            windows = _get_probable_login_windows(desktop, current_pids)
            if not windows:
                current_pids = _list_process_ids(executable.name) or current_pids
                time.sleep(0.5)
                continue

            for window in windows:
                try:
                    strategy = _submit_login_attempt(window, password)
                except Exception as exc:
                    last_error = exc
                    continue

                window_description = describe_window(window)
                ready_timeout = min(8.0, max(deadline - time.monotonic(), 0.5))
                if _wait_for_login_completion(desktop, current_pids, window, ready_timeout):
                    _report_status(base_url, token, f"INFO: 已通过{strategy}填入并提交 QMT 登录，登录窗口已消失: {window_description}")
                    return

                last_error = RuntimeError(f"已通过{strategy}填入并提交 QMT 登录，但登录窗口仍然可见: {window_description}")
                if retries_remaining > 0:
                    retries_remaining -= 1
                    _report_status(base_url, token, f"INFO: 登录窗口在提交后仍然可见，准备重试一次: {window_description}")
                    break

                raise last_error

            current_pids = _list_process_ids(executable.name) or current_pids
            time.sleep(0.5)
        if last_error is not None:
            raise RuntimeError(f"自动填入 QMT 密码失败: {last_error}") from last_error

    raise RuntimeError("自动填入 QMT 密码失败：未找到登录窗口")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QMT restart helper")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--launch-timeout", type=float, default=15.0)
    parser.add_argument("--login-timeout", type=float, default=40.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    executable = Path(args.exe).expanduser()
    try:
        restart_qmt_in_interactive_session(
            base_url=args.base_url,
            token=args.token,
            executable=executable,
            launch_timeout=args.launch_timeout,
            login_timeout=args.login_timeout,
        )
        return 0
    except Exception as exc:
        _report_status(args.base_url, args.token, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())