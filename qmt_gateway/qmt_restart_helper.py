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
        populate_password_input(window, password_edit, password)
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


def _minimize_browser_windows() -> list[tuple[int, bool]]:
    """把当前桌面上所有 chromium / edge / chrome / firefox 顶层窗口最小化，
    返回 ``[(hwnd, was_visible), ...]`` 用于登录完成后 restore。

    实现思路：
    - 枚举所有顶层可见窗口
    - 用进程命令行（通过 WMI）判断该窗口是否属于主流浏览器
    - 是的话 ``ShowWindow(hwnd, SW_MINIMIZE)`` 并记下 was_visible 状态

    为什么不只最小化我们识别的浏览器？init-wizard 在用户默认浏览器里开，
    但用户可能同时打开了别的浏览器窗口；只最小化 wizard 那个窗口的话，
    用户看的其他 tab 仍可能挡住 miniqmt。
    """
    if sys.platform != "win32":
        return []

    import ctypes
    import ctypes.wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    IsWindowVisible = user32.IsWindowVisible

    candidates: list[int] = []
    GetWindowTextW = user32.GetWindowTextW
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId

    def collect(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        pid = ctypes.wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid.value}').Name",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            proc_name = (result.stdout or "").strip().lower()
        except Exception:
            return True
        browser_markers = (
            "msedge.exe",
            "chrome.exe",
            "firefox.exe",
            "browser_broker.exe",
            "brave.exe",
            "opera.exe",
        )
        if proc_name in browser_markers:
            candidates.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(collect), 0)

    minimized: list[tuple[int, bool]] = []
    SW_MINIMIZE = 6
    for hwnd in candidates:
        try:
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            minimized.append((hwnd, True))
            logger.info(
                "helper: 临时最小化浏览器窗口 hwnd=0x{:X}，登录完成后恢复",
                hwnd,
            )
        except Exception:
            pass
    return minimized


def _restore_minimized_windows(windows: list[tuple[int, bool]]) -> None:
    """把 ``_minimize_browser_windows`` 之前最小化的窗口 restore。"""
    if sys.platform != "win32" or not windows:
        return
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    SW_RESTORE = 9
    for hwnd, _was_visible in windows:
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
        except Exception:
            pass


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


def restart_qmt_in_interactive_session(
    base_url: str,
    token: str,
    executable: Path,
    launch_timeout: float,
    login_timeout: float,
    retry_delay: float = 3.0,
) -> None:
    password = _fetch_password(base_url, token)
    before_pids = set(_list_process_ids(executable.name))

    try:
        os.startfile(str(executable), cwd=str(executable.parent))
    except TypeError:
        os.startfile(str(executable))

    current_pids = _wait_for_new_process(executable.name, before_pids, launch_timeout)

    # 临时把浏览器最小化，避免 init-wizard 的浏览器页面挡住 QMT 登录窗口。
    # 登录流程结束后无论成败都会 restore，所以即使中途出错也不影响用户。
    # 修复 #94：方案 4 + 2 组合（HWND_TOPMOST + 临时最小化浏览器）
    minimized_browser = _minimize_browser_windows()

    def _restore_browser():
        _restore_minimized_windows(minimized_browser)

    def _release_topmost(window):
        try:
            from qmt_gateway.qmt_login_automation import _deactivate_topmost
            _deactivate_topmost(window)
        except Exception:
            pass

    try:
        max_attempts = 2
        attempt = 0
        for backend in ("uia", "win32"):
            if attempt >= max_attempts:
                break
            desktop = Desktop(backend=backend)
            deadline = time.monotonic() + max(float(login_timeout), 1.0)
            last_error: Exception | None = None
            while time.monotonic() < deadline and attempt < max_attempts:
                windows = _get_probable_login_windows(desktop, current_pids)
                if not windows:
                    current_pids = _list_process_ids(executable.name) or current_pids
                    time.sleep(0.5)
                    continue

                for window in windows:
                    if attempt >= max_attempts:
                        break
                    attempt += 1
                    try:
                        strategy = _submit_login_attempt(window, password)
                    except Exception as exc:
                        last_error = exc
                        # 当前窗口处理失败，撤掉它的 TOPMOST 再试下一个
                        _release_topmost(window)
                        _report_status(
                            base_url,
                            token,
                            f"WARN: 第 {attempt}/{max_attempts} 次自动登录失败: {exc}; window={describe_window(window)}",
                        )
                        continue

                    window_description = describe_window(window)
                    ready_timeout = min(8.0, max(deadline - time.monotonic(), 0.5))
                    login_ok = _wait_for_login_completion(desktop, current_pids, window, ready_timeout)
                    # 无论登录是否成功，先撤掉 TOPMOST 恢复 Z-order
                    _release_topmost(window)

                    if login_ok:
                        _report_status(base_url, token, f"INFO: 已通过{strategy}填入并提交 QMT 登录，登录窗口已消失: {window_description}")
                        return

                    last_error = RuntimeError(f"已通过{strategy}填入并提交 QMT 登录，但登录窗口仍然可见: {window_description}")
                    _report_status(
                        base_url,
                        token,
                        f"INFO: 登录窗口在提交后仍然可见，准备重试一次（等待 {retry_delay:.1f} 秒以避开干扰）: {window_description}",
                    )
                    break

                if last_error is not None and attempt < max_attempts and time.monotonic() < deadline:
                    _report_status(
                        base_url,
                        token,
                        f"INFO: 等待 {retry_delay:.1f} 秒后进行第 {attempt + 1}/{max_attempts} 次重试",
                    )
                    time.sleep(max(float(retry_delay), 0.0))
            if last_error is not None:
                raise RuntimeError(f"自动填入 QMT 密码失败: {last_error}") from last_error

        raise RuntimeError("自动填入 QMT 密码失败：未找到登录窗口")
    finally:
        _restore_browser()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QMT restart helper")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--launch-timeout", type=float, default=15.0)
    parser.add_argument("--login-timeout", type=float, default=40.0)
    parser.add_argument("--retry-delay", type=float, default=3.0)
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
            retry_delay=args.retry_delay,
        )
        return 0
    except Exception as exc:
        _report_status(args.base_url, args.token, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())