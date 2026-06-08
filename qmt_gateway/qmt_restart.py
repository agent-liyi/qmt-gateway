"""独立的 QMT 重启 + 登录流程。

设计目标：
- 可独立运行（不依赖 ``TradeService`` 实例），便于调试和测试。
- async 接口，调用方可在事件循环中等待并响应取消。
- 通过 ``asyncio.wait_for`` 形式的总体超时控制；内部将取消请求
  通过 ``threading.Event`` 传递给后台工作线程，使其能优雅退出。
- 不再使用 ``concurrent.futures`` + ``result(timeout=...)`` 这种
  无法中断工作线程的模式。

入口：
    ``await QmtRestartCoordinator().restart_and_login(...)``

辅助：
    :func:`run_sync` 以同步方式运行（用于命令行 / 测试脚本）。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from qmt_gateway.qmt_login_automation import (
    is_probable_login_window,
    iter_login_windows,
    locate_password_input,
    populate_password_input,
    populate_password_via_layout,
    populate_password_via_tab,
    submit_login_via_layout,
    submit_login_window,
)


# --- 常量 ---------------------------------------------------------------

QMT_CLIENT_EXECUTABLE = "XtMiniQmt.exe"
DEFAULT_RESTART_TIMEOUT_SEC = 30.0
DEFAULT_LAUNCH_TIMEOUT_SEC = 5.0
DEFAULT_LOGIN_TIMEOUT_SEC = 20.0
DEFAULT_RETRY_DELAY_SEC = 3.0


# --- 取消令牌 -----------------------------------------------------------


@dataclass
class CancellationToken:
    """协作式取消令牌。后台线程周期性检查 ``cancelled`` 标志。"""

    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError("QMT 重启流程已被取消")


class CancelledError(Exception):
    """操作被外部取消时抛出。"""


# --- 进度回调 -----------------------------------------------------------


@dataclass
class RestartProgress:
    """单步进度信息，传递给 ``on_progress`` 回调。"""

    stage: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[RestartProgress], None]


# --- 核心实现 -----------------------------------------------------------


class QmtRestartCoordinator:
    """协调 QMT 重启 + 登录流程的独立对象。

    使用方式::

        coord = QmtRestartCoordinator(qmt_path=..., account_id=...)
        result = await coord.restart_and_login(password="...", timeout=30)
    """

    def __init__(
        self,
        *,
        qmt_path: str | Path,
        account_id: str,
        executable: str = QMT_CLIENT_EXECUTABLE,
        launch_timeout_sec: float = DEFAULT_LAUNCH_TIMEOUT_SEC,
        login_timeout_sec: float = DEFAULT_LOGIN_TIMEOUT_SEC,
        retry_delay_sec: float = DEFAULT_RETRY_DELAY_SEC,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        self._qmt_path = Path(qmt_path).expanduser()
        self._account_id = str(account_id or "").strip()
        self._executable_name = executable
        self._launch_timeout_sec = float(launch_timeout_sec)
        self._login_timeout_sec = float(login_timeout_sec)
        self._retry_delay_sec = float(retry_delay_sec)
        self._on_progress = on_progress
        self._cancel_token: CancellationToken | None = None

    # --- 公共 API ------------------------------------------------------

    async def restart_and_login(
        self,
        *,
        password: str,
        kill_first: bool = False,
        verify_connection: bool = True,
        timeout: float = DEFAULT_RESTART_TIMEOUT_SEC,
        verify_connection_fn: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """异步执行 QMT 重启 + 登录。整体 ``timeout`` 秒后抛出 ``asyncio.TimeoutError``。"""

        if not password:
            return {"success": False, "error": "请输入交易密码"}
        if not self._account_id:
            return {"success": False, "error": "QMT 账号未配置"}
        if not str(self._qmt_path).strip():
            return {"success": False, "error": "QMT 路径未配置"}

        self._cancel_token = CancellationToken()
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._run_in_background,
                    password,
                    kill_first,
                    verify_connection,
                    verify_connection_fn,
                ),
                timeout=float(timeout),
            )
        except asyncio.TimeoutError:
            self._cancel_token.cancel()
            logger.warning("QMT 重启超时 ({:.0f}s)，已发出取消信号", timeout)
            return {
                "success": False,
                "error": f"QMT 重启超时（{timeout:.0f}秒），请稍后重试",
                "cancelled": True,
            }
        except CancelledError as exc:
            return {"success": False, "error": str(exc), "cancelled": True}

    def cancel(self) -> None:
        """请求取消正在运行的重启流程。"""
        if self._cancel_token is not None:
            self._cancel_token.cancel()

    # --- 后台工作线程 ---------------------------------------------------

    def _run_in_background(
        self,
        password: str,
        kill_first: bool,
        verify_connection: bool,
        verify_connection_fn: Optional[Callable[[], bool]],
    ) -> dict:
        assert self._cancel_token is not None
        token = self._cancel_token

        try:
            executable = self._resolve_qmt_client_path()
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        self._emit("resolving", f"已解析 QMT 客户端: {executable}", {"executable": str(executable)})

        try:
            if kill_first:
                token.raise_if_cancelled()
                self._kill_existing(executable.name)

            token.raise_if_cancelled()
            launch_pid = self._launch_with_timeout(executable)
            if not launch_pid:
                return {"success": False, "error": f"启动 QMT 超时（{self._launch_timeout_sec:.0f}秒）"}

            token.raise_if_cancelled()
            self._emit("launched", f"QMT 已启动: pid={launch_pid}", {"pid": launch_pid})

            token.raise_if_cancelled()
            self._fill_password_with_retries(launch_pid, password, token)

            token.raise_if_cancelled()
            self._wait_for_login_window_to_close(launch_pid, token)

            if not verify_connection:
                self._emit("done", "启动+填密码完成，跳过连接验证", {"verified": False})
                return {"success": True, "message": "QMT 已启动，连接验证交给调用方", "pid": launch_pid}

            if verify_connection_fn is not None:
                token.raise_if_cancelled()
                if verify_connection_fn():
                    return {"success": True, "message": "QMT 已重启并已连接", "pid": launch_pid}
                return {"success": False, "error": "交易接口重连失败"}

            self._emit("done", "QMT 重启+填密码流程完成", {"pid": launch_pid})
            return {"success": True, "message": "QMT 已重启", "pid": launch_pid}
        except CancelledError as exc:
            logger.warning("QMT 重启被取消: {}", exc)
            return {"success": False, "error": str(exc), "cancelled": True}
        except Exception as exc:
            logger.error("QMT 重启失败: {}", exc)
            return {"success": False, "error": str(exc)}

    # --- 子步骤 --------------------------------------------------------

    def _resolve_qmt_client_path(self) -> Path:
        base = self._qmt_path
        if base.name.lower() == "userdata_mini":
            base = base.parent
        executable = base / "bin.x64" / self._executable_name
        if not executable.is_file():
            raise FileNotFoundError(f"未找到 QMT 客户端: {executable}")
        return executable

    def _emit(self, stage: str, message: str, detail: Optional[dict] = None) -> None:
        progress = RestartProgress(stage=stage, message=message, detail=detail or {})
        if self._on_progress is not None:
            try:
                self._on_progress(progress)
            except Exception as exc:  # 回调失败不应阻塞主流程
                logger.warning("on_progress 回调失败: {}", exc)
        logger.info("[qmt-restart] {}: {}", stage, message)

    def _kill_existing(self, executable_name: str) -> None:
        pids = self._list_process_ids(executable_name)
        if not pids:
            self._emit("kill", f"未发现正在运行的 {executable_name}")
            return
        self._emit("kill", f"终止现有 {executable_name}: {pids}")
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID"] + [str(pid) for pid in pids],
            check=False,
            capture_output=True,
        )
        time.sleep(1.0)

    def _launch_with_timeout(self, executable: Path) -> int:
        before_pids = set(self._list_process_ids(executable.name))
        self._emit("launching", f"启动 {executable} ...")
        try:
            os.startfile(str(executable), cwd=str(executable.parent))
        except TypeError:
            os.startfile(str(executable))

        deadline = time.monotonic() + self._launch_timeout_sec
        while time.monotonic() < deadline:
            current = self._list_process_ids(executable.name)
            new = [pid for pid in current if pid not in before_pids]
            if new:
                return new[0]
            time.sleep(0.5)
        return 0

    def _list_process_ids(self, executable_name: str) -> list[int]:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {executable_name}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            check=False,
        )
        from csv import reader as csv_reader
        import io as _io

        pids: list[int] = []
        for row in csv_reader(_io.StringIO(result.stdout)):
            if len(row) < 2:
                continue
            if str(row[0] or "").strip().lower() != executable_name.lower():
                continue
            try:
                pids.append(int(str(row[1]).replace(",", "").strip()))
            except ValueError:
                continue
        return pids

    def _fill_password_with_retries(
        self,
        process_id: int,
        password: str,
        token: CancellationToken,
    ) -> None:
        max_attempts = 2
        deadline = time.monotonic() + self._login_timeout_sec
        attempt = 0
        last_error: Exception | None = None

        while attempt < max_attempts and time.monotonic() < deadline:
            token.raise_if_cancelled()
            attempt += 1
            self._emit(
                "fill_attempt",
                f"第 {attempt}/{max_attempts} 次尝试填入密码",
                {"attempt": attempt},
            )
            try:
                self._fill_qmt_login_password(process_id, password, token, deadline)
                return
            except CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                self._emit("fill_failed", f"第 {attempt} 次填入失败: {exc}")
                if attempt < max_attempts and time.monotonic() < deadline:
                    time.sleep(self._retry_delay_sec)

        raise RuntimeError(
            f"在 {self._login_timeout_sec:.0f} 秒内未完成密码填入: {last_error}"
            if last_error
            else f"在 {self._login_timeout_sec:.0f} 秒内未完成密码填入"
        )

    def _fill_qmt_login_password(
        self,
        process_id: int,
        password: str,
        token: CancellationToken,
        overall_deadline: float,
    ) -> None:
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError("缺少 pywinauto 依赖") from exc

        last_error: Exception | None = None
        for backend in ("uia", "win32"):
            token.raise_if_cancelled()
            try:
                desktop = Desktop(backend=backend)
            except Exception as exc:
                last_error = exc
                continue

            while time.monotonic() < overall_deadline:
                token.raise_if_cancelled()
                process_ids = self._list_process_ids(self._executable_name)
                if not process_ids:
                    last_error = RuntimeError(f"未检测到 {self._executable_name} 运行进程")
                    time.sleep(0.5)
                    continue

                windows = list(iter_login_windows(desktop, process_ids))
                self._emit(
                    "fill_scan",
                    f"backend={backend} 扫描到 {len(windows)} 个窗口",
                    {"backend": backend, "count": len(windows)},
                )
                for window in windows:
                    token.raise_if_cancelled()
                    try:
                        password_edit = locate_password_input(window)
                        populate_password_input(window, password_edit, password)
                        self._emit(
                            "filled",
                            "已通过控件树填入密码并提交",
                            {"backend": backend, "pid": process_id},
                        )
                        submit_login_window(window)
                        return
                    except Exception as exc:
                        try:
                            populate_password_via_tab(window, password)
                            self._emit("filled", "已通过 Tab 导航填入密码", {"backend": backend})
                            submit_login_window(window)
                            return
                        except Exception:
                            if not is_probable_login_window(window):
                                last_error = RuntimeError(
                                    f"候选窗口仍像启动页: {window.window_text() if hasattr(window, 'window_text') else '?'}"
                                )
                                continue
                            try:
                                populate_password_via_layout(window, password)
                                self._emit("filled", "已通过布局坐标填入密码", {"backend": backend})
                                submit_login_via_layout(window)
                                return
                            except Exception as layout_exc:
                                last_error = layout_exc
                time.sleep(0.5)

        raise RuntimeError(f"自动填入 QMT 密码失败: {last_error}")

    def _wait_for_login_window_to_close(self, process_id: int, token: CancellationToken) -> bool:
        try:
            from pywinauto import Desktop
        except ImportError:
            return True

        timeout_sec = 8.0
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            token.raise_if_cancelled()
            for backend in ("uia", "win32"):
                try:
                    desktop = Desktop(backend=backend)
                except Exception:
                    continue
                process_ids = self._list_process_ids(self._executable_name)
                if not process_ids:
                    return True
                windows = list(iter_login_windows(desktop, process_ids))
                if not windows:
                    return True
            time.sleep(0.3)
        return False


# --- 同步入口 ----------------------------------------------------------


def run_sync(
    *,
    qmt_path: str | Path,
    account_id: str,
    password: str,
    kill_first: bool = False,
    verify_connection: bool = True,
    timeout: float = DEFAULT_RESTART_TIMEOUT_SEC,
    executable: str = QMT_CLIENT_EXECUTABLE,
    on_progress: Optional[ProgressCallback] = None,
    verify_connection_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    """以同步方式运行 ``QmtRestartCoordinator.restart_and_login``。"""

    async def _runner() -> dict:
        coord = QmtRestartCoordinator(
            qmt_path=qmt_path,
            account_id=account_id,
            executable=executable,
            on_progress=on_progress,
        )
        return await coord.restart_and_login(
            password=password,
            kill_first=kill_first,
            verify_connection=verify_connection,
            timeout=timeout,
            verify_connection_fn=verify_connection_fn,
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError(
                "事件循环正在运行，请改用 await QmtRestartCoordinator().restart_and_login(...)"
            )
        return loop.run_until_complete(_runner())
    except RuntimeError:
        return asyncio.run(_runner())