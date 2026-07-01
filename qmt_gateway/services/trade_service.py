"""交易服务

基于 qmt_broker.py 封装 xttrader 交易功能。
"""

import concurrent.futures
import datetime
import io
import locale
import os
import subprocess
import sys
import threading
import time
from ctypes import byref, c_uint, windll
from csv import reader as csv_reader
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger

from qmt_gateway.config import config
from qmt_gateway.core import add_xtquant_path
from qmt_gateway.core.enums import BidType, OrderSide, OrderStatus
from qmt_gateway.db.models import Order, Position, Trade
from qmt_gateway.db.sqlite import db
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


# xtquant 模块（延迟导入）
_xtquant_modules: dict[str, Any] = {}
DEFAULT_PORTFOLIO_ID = "default"
QMT_CLIENT_EXECUTABLE = "XtMiniQmt.exe"
QMT_PROCESS_NOT_FOUND_MARKERS = ("not found", "找不到", "没有运行的实例", "没有找到")


def _get_xtquant(name: str):
    """延迟获取 xtquant 模块或类"""
    if name not in _xtquant_modules:
        if name == "xtconstant":
            from xtquant import xtconstant as mod
        elif name == "XtQuantTrader":
            from xtquant.xttrader import XtQuantTrader as mod
        elif name == "XtQuantTraderCallback":
            from xtquant.xttrader import XtQuantTraderCallback as mod
        elif name == "StockAccount":
            from xtquant.xttype import StockAccount as mod
        elif name == "XtAsset":
            from xtquant.xttype import XtAsset as mod
        elif name == "XtPosition":
            from xtquant.xttype import XtPosition as mod
        elif name == "XtOrder":
            from xtquant.xttype import XtOrder as mod
        elif name == "XtTrade":
            from xtquant.xttype import XtTrade as mod
        else:
            raise ImportError(f"Unknown xtquant module: {name}")
        _xtquant_modules[name] = mod
    return _xtquant_modules[name]


def _restart_and_login_sync(
    service: "TradeService",
    qmt_path: str,
    account_id: str,
    qmt_password: str,
    kill_first: bool,
    verify_connection: bool = True,
) -> dict:
    """``TradeService.restart_and_login`` 的同步实现。

    整体 30 秒超时，超时后返回 ``{"success": False, "error": ...}``。
    """
    import concurrent.futures

    timeout_sec = float(service._qmt_restart_timeout_sec)

    def _task() -> dict:
        password_token: str | None = None
        try:
            executable = service._resolve_qmt_client_path(qmt_path)
            logger.info("准备重启 QMT: qmt_path={}, executable={}", qmt_path, executable)
            service.disconnect()
            service._set_connection_state(False, "交易接口连接断开，正在重启 QMT")

            if kill_first:
                kill_result = service._kill_qmt_process(executable.name)
                if kill_result == "terminated":
                    logger.info("已终止现有 QMT 进程: image={}", executable.name)
                else:
                    logger.info("未发现正在运行的 QMT 进程: image={}", executable.name)

            if service._get_current_session_id() == 0:
                password_token = service.issue_restart_password_token(qmt_password)

            process = service._launch_qmt_process(executable, password_token=password_token)
            if password_token is None:
                service._fill_qmt_login_password(process.pid, qmt_password)
                # 等待登录窗口消失，确保 QMT 已处理完密码提交
                service._wait_for_login_window_to_close(
                    process.pid,
                    timeout_sec=float(service._qmt_login_timeout_sec),
                )

            if not verify_connection:
                logger.info("启动+填密码完成，跳过连接验证（verify_connection=False）")
                service._qmt_path = qmt_path
                service._account_id = account_id
                return {"success": True, "message": "QMT 已启动，连接验证交给调用方"}

            # 多次尝试连接，应对 QMT 还在初始化 mini trader 的情况
            if service._connect_with_retry(account_id=account_id, qmt_path=qmt_path):
                return {"success": True, "message": "QMT 已重启并重新连接交易接口"}
            return {"success": False, "error": "交易接口重连失败"}
        except Exception as exc:
            logger.error(f"重启 QMT 失败: {exc}")
            service._set_connection_state(False, f"重启 QMT 失败: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            service.discard_restart_password_token(password_token)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_task)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            logger.warning("重启 QMT 超时 ({}s)，请稍后重试", timeout_sec)
            service._set_connection_state(False, f"重启 QMT 超时 ({timeout_sec}s)")
            return {
                "success": False,
                "error": f"重启 QMT 超时（{timeout_sec:.0f}秒），请检查 QMT 是否已启动后重试",
            }


class TradeCallback:
    """交易回调实现"""

    def __init__(self, service: "TradeService"):
        self._service = service

    def on_disconnected(self):
        """连接断开"""
        message = self._service.mark_disconnected("交易接口连接断开")
        logger.critical(message)

    def on_stock_order(self, order):
        """委托回报推送"""
        logger.info(f"委托回报: {order.stock_code} {order.order_status}")
        self._service.persist_callback_order(order)

    def on_stock_asset(self, asset):
        """资产回报推送"""
        logger.info(f"资产回报: {asset}")

    def on_stock_position(self, position):
        """持仓回报推送"""
        logger.info(f"持仓回报: {position}")

    def on_stock_trade(self, trade):
        """成交回报推送"""
        logger.info(f"成交回报: {trade}")
        self._service.persist_callback_trade(trade)

    def on_order_error(self, order_error):
        """委托失败推送"""
        logger.error(f"委托失败: {order_error}")

    def on_cancel_error(self, cancel_error):
        """撤单失败推送"""
        message = self._service.record_cancel_error(cancel_error)
        logger.error(f"撤单失败: {message}")


class TradeService:
    """交易服务

    封装 xttrader 交易功能，提供买入、卖出、撤单、查询等操作。
    """

    def __init__(self):
        self._trader = None
        self._account = None
        self._connected = False
        self._account_id = None
        self._qmt_path = None
        self._recent_cancel_errors: dict[str, tuple[float, str]] = {}
        self._cancel_error_wait_timeout_sec = 1.2
        self._connection_message = "交易接口未连接"
        self._connection_updated_at = datetime.datetime.now().isoformat(timespec="seconds")
        self._qmt_restart_timeout_sec = 30.0
        self._qmt_login_timeout_sec = 20.0
        self._qmt_launch_probe_timeout_sec = 5.0
        self._qmt_login_retry_delay_sec = 3.0
        self._restart_password_token_ttl_sec = 120.0
        self._restart_password_tokens: dict[str, dict[str, object]] = {}
        self._auto_start_max_retries = 2
        self._auto_reconnect_lock = threading.Lock()
        self._auto_reconnect_running = False
        # 持仓快照线程池：确保同一时间最多一个刷新任务 (#91)
        self._position_snapshot_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="position-snapshot"
        )

    def _set_connection_state(self, connected: bool, message: str) -> str:
        self._connected = connected
        self._connection_message = str(message or ("交易接口已连接" if connected else "交易接口未连接"))
        self._connection_updated_at = datetime.datetime.now().isoformat(timespec="seconds")
        return self._connection_message

    def _build_session_id(self) -> int:
        session_id = int(time.time_ns() % 2147483647)
        return session_id if session_id > 0 else 1

    def _cleanup_trader(self) -> None:
        trader = self._trader
        self._trader = None
        if trader is None:
            return

        stop = getattr(trader, "stop", None)
        if callable(stop):
            stop()

    def mark_disconnected(self, message: str = "交易接口连接断开") -> str:
        state_message = self._set_connection_state(False, message)
        if config.auto_start_qmt:
            self._schedule_auto_reconnect()
        return state_message

    def _schedule_auto_reconnect(self) -> bool:
        account_id = str(self._account_id or config.qmt_account_id or "").strip()
        qmt_path = str(self._qmt_path or config.qmt_path or "").strip()
        if not account_id or not qmt_path:
            logger.warning("auto_start_qmt: QMT 账号或路径未配置，跳过断线自动重启")
            return False
        with self._auto_reconnect_lock:
            if self._auto_reconnect_running:
                logger.info("auto_start_qmt: 断线自动重启任务已在运行，跳过重复调度")
                return False
            self._auto_reconnect_running = True
        thread = threading.Thread(
            target=self._run_auto_reconnect,
            args=(qmt_path, account_id),
            daemon=True,
        )
        thread.start()
        return True

    def _run_auto_reconnect(self, qmt_path: str, account_id: str) -> None:
        try:
            logger.warning("auto_start_qmt: 检测到交易接口断线，开始自动重启 QMT")
            self.try_auto_start_qmt(qmt_path=qmt_path, account_id=account_id)
        finally:
            with self._auto_reconnect_lock:
                self._auto_reconnect_running = False

    def get_connection_status(self) -> dict:
        return {
            "connected": bool(self._connected and self._trader is not None and self._account is not None),
            "message": self._connection_message,
            "updated_at": self._connection_updated_at,
        }

    def _prune_restart_password_tokens(self) -> None:
        now = time.monotonic()
        for token, entry in list(self._restart_password_tokens.items()):
            created_at = float(entry.get("created_at", 0.0) or 0.0)
            if now - created_at > self._restart_password_token_ttl_sec:
                self._restart_password_tokens.pop(token, None)

    def issue_restart_password_token(self, password: str) -> str:
        self._prune_restart_password_tokens()
        token = uuid4().hex
        self._restart_password_tokens[token] = {
            "created_at": time.monotonic(),
            "password": str(password or ""),
            "status": "",
        }
        return token

    def consume_restart_password_token(self, token: str) -> str | None:
        self._prune_restart_password_tokens()
        entry = self._restart_password_tokens.get(str(token or ""))
        if entry is None:
            return None

        password = str(entry.get("password", "") or "")
        entry["password"] = ""
        return password or None

    def record_restart_helper_status(self, token: str, status: str) -> None:
        self._prune_restart_password_tokens()
        entry = self._restart_password_tokens.get(str(token or ""))
        if entry is None:
            return
        entry["status"] = str(status or "")

    def get_restart_helper_status(self, token: str | None) -> str | None:
        if not token:
            return None
        self._prune_restart_password_tokens()
        entry = self._restart_password_tokens.get(str(token or ""))
        if entry is None:
            return None
        status = str(entry.get("status", "") or "").strip()
        if status.startswith("INFO:"):
            return None
        return status or None

    def discard_restart_password_token(self, token: str | None) -> None:
        if token:
            self._restart_password_tokens.pop(str(token), None)

    def _normalize_cancel_error_keys(self, *keys: object) -> list[str]:
        normalized = []
        for key in keys:
            value = str(key or "").strip()
            if value:
                normalized.append(value)
        return list(dict.fromkeys(normalized))

    def _format_cancel_error(self, cancel_error) -> str:
        error_message = str(
            getattr(cancel_error, "error_msg", "")
            or getattr(cancel_error, "error_message", "")
            or getattr(cancel_error, "msg", "")
            or ""
        ).strip()
        error_code = str(
            getattr(cancel_error, "error_id", "")
            or getattr(cancel_error, "error_code", "")
            or ""
        ).strip()

        if error_message and error_code and error_code not in error_message:
            return f"{error_message} (错误码: {error_code})"
        if error_message:
            return error_message
        if error_code:
            return f"撤单失败，错误码: {error_code}"
        return str(cancel_error)

    def record_cancel_error(self, cancel_error) -> str:
        message = self._format_cancel_error(cancel_error)
        keys = self._normalize_cancel_error_keys(
            getattr(cancel_error, "order_id", ""),
            getattr(cancel_error, "order_sysid", ""),
            getattr(cancel_error, "foid", ""),
            getattr(cancel_error, "qtoid", ""),
            getattr(cancel_error, "order_remark", ""),
            "__latest__",
        )
        now = time.monotonic()
        for key in keys:
            self._recent_cancel_errors[key] = (now, message)
        return message

    def _clear_recent_cancel_errors(self, *keys: object) -> None:
        for key in self._normalize_cancel_error_keys(*keys, "__latest__"):
            self._recent_cancel_errors.pop(key, None)

    def _consume_recent_cancel_error(self, *keys: object) -> str | None:
        now = time.monotonic()
        for key in self._normalize_cancel_error_keys(*keys, "__latest__"):
            item = self._recent_cancel_errors.get(key)
            if item is None:
                continue
            ts, message = item
            self._recent_cancel_errors.pop(key, None)
            if now - ts <= 5:
                return message
        return None

    def _wait_for_cancel_error(self, *keys: object) -> str | None:
        immediate = self._consume_recent_cancel_error(*keys)
        if immediate:
            return immediate

        timeout_sec = max(float(self._cancel_error_wait_timeout_sec), 0.0)
        if timeout_sec <= 0:
            return None

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            time.sleep(0.05)
            message = self._consume_recent_cancel_error(*keys)
            if message:
                return message
        return None

    def _prepare_xtquant_env(self, qmt_path: str) -> None:
        """在连接交易接口前准备 xtquant 运行环境。"""
        add_xtquant_path(
            xtquant_path=str(config.xtquant_path) if config.xtquant_path else None,
            qmt_path=qmt_path or (str(config.qmt_path) if config.qmt_path else None),
        )

    def _ensure_connected(self) -> bool:
        """在读取实时交易数据前尝试补连。"""
        if self._connected and self._trader is not None and self._account is not None:
            return True
        account_id = str(self._account_id or config.qmt_account_id or "").strip()
        qmt_path = str(self._qmt_path or config.qmt_path or "").strip()
        if not account_id or not qmt_path:
            return False
        if not config.auto_start_qmt and not self._connected:
            return False
        logger.info("交易接口未连接，尝试自动补连")
        return self.connect(account_id=account_id, qmt_path=qmt_path)

    def connect(self, account_id: str, qmt_path: str) -> bool:
        """连接交易接口

        Args:
            account_id: 资金账号
            qmt_path: QMT 安装路径

        Returns:
            是否连接成功
        """
        try:
            self.disconnect()
            self._account_id = account_id
            self._qmt_path = qmt_path
            self._prepare_xtquant_env(qmt_path)

            # 延迟导入 xtquant
            XtQuantTrader = _get_xtquant("XtQuantTrader")
            StockAccount = _get_xtquant("StockAccount")
            _get_xtquant("xtconstant")

            # 创建账户对象
            self._account = StockAccount(account_id, "stock")

            # 创建交易对象
            session_id = self._build_session_id()
            self._trader = XtQuantTrader(qmt_path, session_id)

            # 注册回调
            callback = TradeCallback(self)
            self._trader.register_callback(callback)

            # 启动交易接口
            self._trader.start()

            # 连接
            connect_result = self._trader.connect()
            if connect_result != 0:
                logger.error(f"连接交易接口失败，错误码: {connect_result}")
                self._cleanup_trader()
                self._set_connection_state(False, f"已和 QMT 断开连接，错误码: {connect_result}")
                return False

            # 订阅账户
            subscribe_result = self._trader.subscribe(self._account)
            if subscribe_result != 0:
                logger.error(f"订阅账户失败，错误码: {subscribe_result}")
                self._cleanup_trader()
                self._set_connection_state(False, f"交易接口订阅失败，错误码: {subscribe_result}")
                return False

            self._set_connection_state(True, f"交易接口已连接：{account_id}")
            logger.info(f"交易接口连接成功，账号: {account_id}")
            return True

        except Exception as e:
            logger.error(f"连接交易接口失败: {e}")
            self._set_connection_state(False, f"已和 QMT 断开连接: {e}")
            return False

    def _qmt_executable_exists(self, path: Path) -> bool:
        return path.is_file()

    def _resolve_qmt_client_path(self, qmt_path: str | Path | None = None) -> Path:
        """把用户在 wizard 中填写的 QMT 路径归一化，并解析出
        bin.x64/XtMiniQmt.exe 的可执行路径。

        支持四种入口粒度（与 init wizard placeholder 一致，与
        qmt_init_helpers.resolve_qmt_executable 行为对齐）：
          - XtMiniQmt.exe 本体（如 ...\\bin.x64\\XtMiniQmt.exe）
          - bin.x64 目录
          - userdata_mini 目录
          - QMT 根目录（含 bin.x64/）
        """
        raw = str(qmt_path or self._qmt_path or config.qmt_path or "").strip()
        if not raw:
            raise ValueError("未配置 QMT 路径")

        configured_path = Path(raw).expanduser()
        base_dir = configured_path

        name_lower = configured_path.name.lower()
        if name_lower == "xtminiqmt.exe":
            # 用户填的是 .exe 本体——必须上跳两层到 QMT 根目录
            if configured_path.parent.name.lower() != "bin.x64":
                raise ValueError(
                    f"XtMiniQmt.exe 必须位于 bin.x64 子目录下，得到: {configured_path}"
                )
            base_dir = configured_path.parent.parent
        elif name_lower in ("userdata_mini", "bin.x64"):
            # 用户填的是子目录——上跳一层到 QMT 根目录
            base_dir = configured_path.parent

        executable = base_dir / "bin.x64" / QMT_CLIENT_EXECUTABLE
        if not self._qmt_executable_exists(executable):
            raise FileNotFoundError(f"未找到 QMT 客户端: {executable}")
        return executable

    def _decode_subprocess_output(self, value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value

        candidate_encodings = []
        locale_encoding = locale.getencoding()
        if locale_encoding:
            candidate_encodings.append(locale_encoding)
        candidate_encodings.extend(["mbcs", "gbk", "utf-8"])

        for encoding in dict.fromkeys(candidate_encodings):
            try:
                return value.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return value.decode("utf-8", errors="ignore")

    def _list_process_ids(self, executable_name: str) -> list[int]:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {executable_name}"],
            capture_output=True,
            text=False,
            timeout=15,
            check=False,
        )
        stdout = self._decode_subprocess_output(result.stdout)
        stderr = self._decode_subprocess_output(result.stderr)
        combined = f"{stdout}\n{stderr}".lower()
        if result.returncode != 0 and not any(marker in combined for marker in QMT_PROCESS_NOT_FOUND_MARKERS):
            raise RuntimeError(combined.strip() or f"查询 QMT 进程失败，退出码: {result.returncode}")

        process_ids: list[int] = []
        for row in csv_reader(io.StringIO(stdout)):
            if len(row) < 2:
                continue
            image_name = str(row[0] or "").strip().lower()
            if image_name != executable_name.lower():
                continue
            try:
                process_ids.append(int(str(row[1]).replace(",", "").strip()))
            except ValueError:
                continue
        return process_ids

    def _get_current_session_id(self) -> int | None:
        session_id = c_uint()
        try:
            success = windll.kernel32.ProcessIdToSessionId(os.getpid(), byref(session_id))
        except Exception:
            return None
        return int(session_id.value) if success else None

    def _get_active_interactive_user(self) -> tuple[str, int] | None:
        result = subprocess.run(
            ["quser"],
            capture_output=True,
            text=False,
            timeout=15,
            check=False,
        )
        output = self._decode_subprocess_output(result.stdout)
        fallback: tuple[str, int] | None = None

        for raw_line in output.splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                line = line[1:].strip()

            tokens = line.split()
            if len(tokens) < 2:
                continue

            username = tokens[0]
            session_id = None
            state = ""
            for idx in range(1, len(tokens)):
                if tokens[idx].isdigit():
                    session_id = int(tokens[idx])
                    state = tokens[idx + 1] if idx + 1 < len(tokens) else ""
                    break

            if session_id is None:
                continue

            candidate = (username, session_id)
            normalized_state = state.lower()
            if "active" in normalized_state or "运行" in state or "活动" in state:
                return candidate
            if fallback is None:
                fallback = candidate

        return fallback

    def _get_helper_python_executable(self) -> Path:
        project_root = Path(__file__).resolve().parents[2]
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
        if venv_python.is_file():
            return venv_python
        return Path(sys.executable)

    def _build_restart_helper_base_url(self) -> str:
        port = int(config.server_port or 8130)
        return f"http://127.0.0.1:{port}"

    def _collect_qmt_process_ids(self, initial_process_id: int | None, executable_name: str) -> list[int]:
        process_ids: list[int] = []
        if initial_process_id and int(initial_process_id) > 0:
            process_ids.append(int(initial_process_id))
        for process_id in self._list_process_ids(executable_name):
            if process_id not in process_ids:
                process_ids.append(process_id)
        return process_ids

    def _kill_qmt_process(self, executable_name: str) -> str:

        result = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", executable_name],
            capture_output=True,
            text=False,
            timeout=15,
            check=False,
        )
        stdout = self._decode_subprocess_output(result.stdout)
        stderr = self._decode_subprocess_output(result.stderr)
        combined = f"{stdout}\n{stderr}".lower()
        if result.returncode == 0:
            return "terminated"
        if any(marker in combined for marker in QMT_PROCESS_NOT_FOUND_MARKERS):
            return "not-running"
        raise RuntimeError(combined.strip() or f"终止 QMT 进程失败，退出码: {result.returncode}")

    def _wait_for_new_process(self, executable_name: str, before_pids: set[int]):
        deadline = time.monotonic() + max(float(self._qmt_launch_probe_timeout_sec), 1.0)
        last_seen_pids: list[int] = []
        while time.monotonic() < deadline:
            current_pids = self._list_process_ids(executable_name)
            last_seen_pids = current_pids
            new_pids = [pid for pid in current_pids if pid not in before_pids]
            if new_pids:
                launch_pid = new_pids[0]
                logger.info("QMT 启动命令已发出: pid={}, active_pids={}", launch_pid, current_pids)
                return type("LaunchedProcess", (), {"pid": launch_pid})()
            time.sleep(0.5)

        logger.warning("未在预期时间内观测到新的 QMT 进程: image={}, active_pids={}", executable_name, last_seen_pids)
        return type("LaunchedProcess", (), {"pid": 0})()

    def _launch_qmt_process_locally(self, executable: Path, before_pids: set[int]):
        logger.info("启动 QMT 客户端: path={}, cwd={}, mode=shell-open", executable, executable.parent)

        try:
            os.startfile(str(executable), cwd=str(executable.parent))
        except TypeError:
            os.startfile(str(executable))

        return self._wait_for_new_process(executable.name, before_pids)

    def _launch_qmt_process_in_interactive_session(self, executable: Path, before_pids: set[int], password_token: str):
        active_user = self._get_active_interactive_user()
        if active_user is None:
            raise RuntimeError("当前网关运行在 Session 0，且未检测到活动桌面会话，无法启动 QMT 图形界面")

        username, session_id = active_user
        logger.info("当前进程位于 Session 0，改用交互会话启动 QMT: user={}, session_id={}", username, session_id)

        task_name = f"QmtGatewayLaunch-{uuid4().hex[:8]}"
        python_executable = self._get_helper_python_executable()
        python_literal = str(python_executable).replace("'", "''")
        username_literal = username.replace("'", "''")
        argument_string = subprocess.list2cmdline(
            [
                "-m",
                "qmt_gateway.qmt_restart_helper",
                "--base-url",
                self._build_restart_helper_base_url(),
                "--token",
                password_token,
                "--exe",
                str(executable),
                "--launch-timeout",
                str(self._qmt_launch_probe_timeout_sec),
                "--login-timeout",
                str(self._qmt_login_timeout_sec),
                "--retry-delay",
                str(self._qmt_login_retry_delay_sec),
            ]
        )
        argument_literal = argument_string.replace("'", "''")
        cwd_literal = str(executable.parent).replace("'", "''")
        command = (
            f"$taskName='{task_name}'; "
            f"$action=New-ScheduledTaskAction -Execute '{python_literal}' -Argument '{argument_literal}' -WorkingDirectory '{cwd_literal}'; "
            f"$principal=New-ScheduledTaskPrincipal -UserId '{username_literal}' -LogonType Interactive; "
            "$task=New-ScheduledTask -Action $action -Principal $principal; "
            "Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null; "
            "Start-ScheduledTask -TaskName $taskName; "
            "Start-Sleep -Seconds 1; "
            "Unregister-ScheduledTask -TaskName $taskName -Confirm:$false"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=False,
            timeout=30,
            check=False,
        )
        stdout = self._decode_subprocess_output(result.stdout)
        stderr = self._decode_subprocess_output(result.stderr)
        if result.returncode != 0:
            combined = (stdout + "\n" + stderr).strip()
            raise RuntimeError(combined or f"通过交互会话启动 QMT 失败，退出码: {result.returncode}")

        logger.info("已通过交互会话触发 QMT 启动: user={}, session_id={}", username, session_id)
        return self._wait_for_new_process(executable.name, before_pids)

    def _launch_qmt_process(self, executable: Path, password_token: str | None = None):
        before_pids = set(self._list_process_ids(executable.name))
        current_session_id = self._get_current_session_id()
        if current_session_id == 0:
            if not password_token:
                raise RuntimeError("缺少 QMT 重启密码令牌，无法在交互会话中自动填入密码")
            return self._launch_qmt_process_in_interactive_session(executable, before_pids, password_token)
        return self._launch_qmt_process_locally(executable, before_pids)

    def _load_pywinauto(self):
        try:
            from pywinauto import Application, Desktop
        except ImportError as exc:
            raise RuntimeError("缺少 pywinauto 依赖，请先安装后再重试") from exc
        return Application, Desktop

    def _iter_login_windows(self, desktop, process_ids: list[int] | set[int]):
        return iter_login_windows(desktop, process_ids)

    def _locate_password_edit(self, window):
        return locate_password_input(window)

    def _submit_login_window(self, window):
        submit_login_window(window)

    def _wait_for_login_window_to_close(self, process_id: int, timeout_sec: float = 8.0) -> bool:
        """等待 QMT 登录窗口自动消失。

        登录窗口消失说明 QMT 已处理完密码提交并进入了交易主界面，
        此时再调用 ``connect()`` 才能成功建立连接。
        """
        try:
            _Application, Desktop = self._load_pywinauto()
        except Exception as exc:
            logger.warning("加载 pywinauto 失败，跳过登录窗口消失检测: {}", exc)
            return True

        deadline = time.monotonic() + max(float(timeout_sec), 0.5)
        initial_pids = set(self._collect_qmt_process_ids(process_id, QMT_CLIENT_EXECUTABLE))
        while time.monotonic() < deadline:
            for backend in ("uia", "win32"):
                try:
                    desktop = Desktop(backend=backend)
                except Exception:
                    continue
                current_pids = set(self._collect_qmt_process_ids(process_id, QMT_CLIENT_EXECUTABLE))
                if not current_pids:
                    return True
                windows = self._iter_login_windows(desktop, current_pids)
                if not list(windows):
                    logger.info("QMT 登录窗口已消失，可以尝试连接")
                    return True
            time.sleep(0.3)
        logger.warning("QMT 登录窗口在 {}s 内未消失", timeout_sec)
        return False

    def _fill_qmt_login_password(self, process_id: int, password: str) -> None:
        _Application, Desktop = self._load_pywinauto()
        last_error: Exception | None = None
        logger.info("开始自动填入 QMT 密码: launcher_pid={}, image={}", process_id, QMT_CLIENT_EXECUTABLE)

        for backend in ("uia", "win32"):
            try:
                desktop = Desktop(backend=backend)
            except Exception as exc:
                last_error = exc
                continue

            deadline = time.monotonic() + self._qmt_login_timeout_sec
            while time.monotonic() < deadline:
                process_ids = self._collect_qmt_process_ids(process_id, QMT_CLIENT_EXECUTABLE)
                if not process_ids:
                    last_error = RuntimeError(f"未检测到 {QMT_CLIENT_EXECUTABLE} 运行进程")
                    time.sleep(0.5)
                    continue
                windows = self._iter_login_windows(desktop, process_ids)
                for window in windows:
                    try:
                        password_edit = self._locate_password_edit(window)
                        populate_password_input(window, password_edit, password)
                        logger.info("已定位 QMT 登录窗口并填入密码: backend={}, process_ids={}", backend, process_ids)
                        self._submit_login_window(window)
                        return
                    except Exception as exc:
                        try:
                            populate_password_via_tab(window, password)
                            logger.info("已通过 Tab 导航填入 QMT 密码: backend={}, process_ids={}", backend, process_ids)
                            self._submit_login_window(window)
                            return
                        except Exception as fallback_exc:
                            if not is_probable_login_window(window):
                                last_error = RuntimeError(f"候选窗口仍像启动页，等待登录页出现: {describe_window(window)}")
                                continue
                            try:
                                populate_password_via_layout(window, password)
                                logger.info("已通过窗口布局坐标填入 QMT 密码: backend={}, process_ids={}", backend, process_ids)
                                submit_login_via_layout(window)
                                return
                            except Exception as layout_exc:
                                last_error = RuntimeError(
                                    f"{exc}; fallback={fallback_exc}; layout={layout_exc}; window={describe_window(window)}"
                                )
                time.sleep(0.5)

        active_process_ids = self._collect_qmt_process_ids(process_id, QMT_CLIENT_EXECUTABLE)
        logger.warning(
            "自动填入 QMT 密码失败，未找到登录窗口: launcher_pid={}, active_pids={}",
            process_id,
            active_process_ids,
        )
        if last_error is not None:
            raise RuntimeError(f"自动填入 QMT 密码失败: {last_error}") from last_error
        raise RuntimeError("自动填入 QMT 密码失败：未找到登录窗口")

    def _connect_with_retry(self, account_id: str, qmt_path: str) -> bool:
        deadline = time.monotonic() + max(float(self._qmt_restart_timeout_sec), 1.0)
        while time.monotonic() < deadline:
            if self.connect(account_id=account_id, qmt_path=qmt_path):
                return True
            time.sleep(2)
        return False

    def _connect_with_helper_status(self, account_id: str, qmt_path: str, password_token: str | None = None) -> dict:
        deadline = time.monotonic() + max(float(self._qmt_restart_timeout_sec), 1.0)
        last_message = self.get_connection_status().get("message", "交易接口重连失败")

        while time.monotonic() < deadline:
            helper_status = self.get_restart_helper_status(password_token)
            if helper_status:
                return {"success": False, "error": helper_status}

            if self.connect(account_id=account_id, qmt_path=qmt_path):
                return {"success": True, "message": "QMT 已重启并重新连接交易接口"}

            last_message = self.get_connection_status().get("message", last_message)
            time.sleep(2)

        helper_status = self.get_restart_helper_status(password_token)
        if helper_status:
            return {"success": False, "error": helper_status}
        return {"success": False, "error": last_message}

    def restart_and_login(
        self,
        *,
        qmt_path: str,
        account_id: str,
        qmt_password: str,
        kill_first: bool = False,
        verify_connection: bool = True,
    ) -> dict:
        """统一的 QMT 重启 + 登录入口（同步版本）。

        流程：kill (如需要) → 启动 QMT → 自动填入登录密码 → 验证连接。
        整体 30 秒超时（由 ``_qmt_restart_timeout_sec`` 控制）。
        异步端点应使用 ``async_restart_and_login`` 以避免阻塞事件循环。

        Args:
            qmt_path: QMT 安装路径
            account_id: 资金账号
            qmt_password: QMT 交易密码
            kill_first: 是否先杀掉已有 QMT 进程
            verify_connection: 是否验证连接。init-wizard 场景设为 False，
                启动+填密码后立即返回，由调用方轮询验证。

        Returns:
            ``{"success": True, "message": ...}`` 或
            ``{"success": False, "error": ...}``
        """
        resolved_password = str(qmt_password or "")
        resolved_path = str(qmt_path or "").strip()
        resolved_account = str(account_id or "").strip()

        if not resolved_password.strip():
            return {"success": False, "error": "请输入交易密码"}
        if not resolved_account or not resolved_path:
            return {"success": False, "error": "QMT 账号或路径未配置"}

        return _restart_and_login_sync(
            self,
            resolved_path,
            resolved_account,
            resolved_password,
            kill_first,
            verify_connection=verify_connection,
        )

    async def async_restart_and_login(
        self,
        *,
        qmt_path: str,
        account_id: str,
        qmt_password: str,
        kill_first: bool = False,
        verify_connection: bool = True,
    ) -> dict:
        """``restart_and_login`` 的异步版本，在线程池中执行同步重置流程。

        异步端点应使用本方法以避免阻塞事件循环。
        """
        import asyncio
        return await asyncio.to_thread(
            self.restart_and_login,
            qmt_path=qmt_path,
            account_id=account_id,
            qmt_password=qmt_password,
            kill_first=kill_first,
            verify_connection=verify_connection,
        )

    def _decrypt_qmt_password(self) -> str | None:
        """尝试解密存储的 QMT 交易密码用于自动启动。

        优先使用 auto-start 专用加密密码（机器密钥加密），
        如果不存在则尝试使用用户密码加密的密码（需要 auto_login 用户）。
        """
        try:
            settings = db.get_settings()
            if settings.qmt_password_auto_start:
                try:
                    from qmt_gateway.core.crypto_utils import decrypt_for_auto_start
                    password = decrypt_for_auto_start(settings.qmt_password_auto_start)
                    if password:
                        logger.info("已使用 auto-start 加密密码解密 QMT 密码")
                        return password
                except Exception as exc:
                    logger.warning("auto-start 密码解密失败: {}", exc)

            if not settings.qmt_password_encrypted or not settings.qmt_password_salt:
                return None

            admin_users = db.conn.execute(
                "SELECT username FROM users WHERE is_admin = 1 AND auto_login = 1"
            ).fetchall()
            if not admin_users:
                logger.info("未找到启用 auto_login 的管理员用户，无法解密 QMT 密码")
                return None

            from qmt_gateway.core.crypto_utils import decrypt_password
            for row in admin_users:
                username = row[0]
                user = db.get_user(username)
                if user is None:
                    continue
                try:
                    password = decrypt_password(
                        settings.qmt_password_encrypted,
                        settings.qmt_password_salt,
                        user.password_hash,
                    )
                    if password:
                        logger.info("已使用 auto_login 用户 {} 的密码解密 QMT 密码", username)
                        return password
                except Exception:
                    continue
            return None
        except Exception as exc:
            logger.warning("自动解密 QMT 密码失败: {}", exc)
            return None

    def try_auto_start_qmt(self, *, qmt_path: str, account_id: str) -> bool:
        """在进程启动时自动启动 QMT 并登录。

        条件：配置了 auto_start_qmt 且存储了加密的 QMT 交易密码。
        最多重试 ``_auto_start_max_retries`` 次，即使全部失败也不阻塞服务启动。

        Returns:
            是否最终连接成功。
        """
        qmt_password = self._decrypt_qmt_password()
        if not qmt_password:
            logger.info("auto_start_qmt: 未找到可解密的 QMT 交易密码，跳过自动启动")
            return False

        max_retries = max(int(self._auto_start_max_retries), 0)
        for attempt in range(1, max_retries + 2):
            try:
                logger.info(
                    "auto_start_qmt: 第 {}/{} 次尝试启动 QMT",
                    attempt,
                    max_retries + 1,
                )
                result = self.restart_and_login(
                    qmt_path=qmt_path,
                    account_id=account_id,
                    qmt_password=qmt_password,
                    kill_first=False,
                    verify_connection=True,
                )
                if result.get("success"):
                    logger.info("auto_start_qmt: 第 {} 次尝试成功", attempt)
                    return True
                logger.warning(
                    "auto_start_qmt: 第 {} 次尝试失败: {}",
                    attempt,
                    result.get("error", "未知错误"),
                )
            except Exception as exc:
                logger.warning("auto_start_qmt: 第 {} 次尝试异常: {}", attempt, exc)

            if attempt <= max_retries:
                time.sleep(3)

        logger.warning(
            "auto_start_qmt: 已尝试 {} 次，均未成功，服务仍将继续运行",
            max_retries + 1,
        )
        self._set_connection_state(False, "自动启动 QMT 失败，请通过 Web 界面手动重启")
        return False

    def disconnect(self):
        """断开交易接口连接"""
        if self._trader is not None:
            try:
                self._cleanup_trader()
                logger.info("交易接口已断开")
            except Exception as e:
                logger.error(f"断开交易接口失败: {e}")
            finally:
                self._account = None
                self._set_connection_state(False, "交易接口已断开")

    def _place_order(
        self,
        symbol: str,
        price: float,
        shares: int,
        side: OrderSide,
        qtoid: str = "",
        strategy_id: str = "",
    ) -> dict:
        """下单公共方法，buy/sell 共用 (#83, #90)

        Args:
            symbol: 股票代码
            price: 委托价格（0 表示市价）
            shares: 委托数量
            side: 买卖方向
            qtoid: 客户端指定的订单 ID，为空时自动生成
            strategy_id: 策略 ID

        Returns:
            委托结果
        """
        if not self._ensure_connected():
            return {"success": False, "error": "交易接口未连接"}

        try:
            xtconstant = _get_xtquant("xtconstant")
            resolved_qtoid = qtoid or str(uuid4())
            order_type = xtconstant.STOCK_BUY if side == OrderSide.BUY else xtconstant.STOCK_SELL

            # 确定价格类型
            if price <= 0:
                # 市价
                market = symbol.split(".")[1].upper() if "." in symbol else "SH"
                if market == "SH":
                    price_type = xtconstant.MARKET_SH_CONVERT_5_CANCEL
                else:
                    price_type = xtconstant.MARKET_SZ_CONVERT_5_CANCEL
                price = 0
            else:
                price_type = xtconstant.FIX_PRICE

            # 下单
            order_id = self._trader.order_stock(
                account=self._account,
                stock_code=symbol,
                order_type=order_type,
                order_volume=shares,
                price_type=price_type,
                price=price,
                strategy_name=strategy_id or "gateway",
                order_remark=resolved_qtoid,
            )

            if order_id == -1:
                return {"success": False, "error": "下单失败"}

            self._persist_submitted_order(
                symbol=symbol,
                side=side,
                price=price,
                shares=shares,
                qtoid=resolved_qtoid,
                foid=str(order_id),
                strategy_id=strategy_id,
            )
            return {"success": True, "qtoid": resolved_qtoid, "order_id": str(order_id)}

        except Exception as e:
            side_name = "buy" if side == OrderSide.BUY else "sell"
            logger.error(f"{side_name}失败: {e}")
            return {"success": False, "error": str(e)}

    def buy(self, symbol: str, price: float, shares: int, qtoid: str = "", strategy_id: str = "") -> dict:
        """买入股票"""
        return self._place_order(symbol, price, shares, OrderSide.BUY, qtoid, strategy_id)

    def sell(self, symbol: str, price: float, shares: int, qtoid: str = "", strategy_id: str = "") -> dict:
        """卖出股票"""
        return self._place_order(symbol, price, shares, OrderSide.SELL, qtoid, strategy_id)

    def cancel_order(self, order_id: str) -> dict:
        """撤单

        Args:
            order_id: 订单 ID

        Returns:
            撤单结果
        """
        if not self._connected:
            return {"success": False, "error": "交易接口未连接"}

        try:
            db_order = db.get_order(order_id) or db.get_order_by_foid(order_id)
            foid = str(db_order.foid if db_order and db_order.foid else order_id)
            qtoid = str(db_order.qtoid if db_order and db_order.qtoid else order_id)
            self._clear_recent_cancel_errors(order_id, foid, qtoid)
            result = self._trader.cancel_order_stock(self._account, int(foid))
            if result == 0:
                cancel_error = self._wait_for_cancel_error(order_id, foid, qtoid)
                if cancel_error:
                    return {"success": False, "error": cancel_error}
                if db_order is not None:
                    db.update_order(db_order.qtoid, status=OrderStatus.CANCELED)
                return {"success": True, "qtoid": db_order.qtoid if db_order else order_id}
            else:
                return {"success": False, "error": f"撤单失败，错误码: {result}"}

        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return {"success": False, "error": str(e)}

    def get_asset(self) -> Optional[dict]:
        """获取账户资产

        Returns:
            账户资产信息字典
        """
        if not self._ensure_connected():
            return None

        try:
            xt_asset = self._trader.query_stock_asset(self._account)
            if xt_asset is None:
                return None

            return {
                "total": xt_asset.total_asset,
                "cash": xt_asset.cash,
                "market_value": xt_asset.market_value,
                "frozen_cash": xt_asset.frozen_cash,
            }

        except Exception as e:
            logger.error(f"获取资产失败: {e}")
            return None

    def get_positions(self) -> list[dict]:
        """获取持仓列表

        Returns:
            持仓列表（字典列表）
        """
        if not self._ensure_connected():
            return []

        try:
            xt_positions = self._trader.query_stock_positions(self._account)
            if xt_positions is None:
                return []

            positions = []
            for p in xt_positions:
                pos = {
                    "symbol": p.stock_code,
                    "name": "",  # 需要通过其他方式获取名称
                    "shares": p.volume,
                    "avail": p.can_use_volume,
                    "price": p.avg_price,
                    "cost": p.avg_price,
                    "profit": p.profit_rate,
                    "market_value": p.market_value,
                }
                positions.append(pos)

            return positions

        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []

    def refresh_positions_snapshot(self) -> None:
        """刷新持仓快照到数据库。

        成交回报（on_stock_trade）后调用，确保持仓表中的可用股数、
        成本、市值等数据与券商保持同步，避免前端显示陈旧数据。
        """
        rows = self.get_positions()
        if rows is None:
            return
        try:
            import datetime
            today = datetime.date.today()
            db.execute_write(
                "delete from positions where portfolio_id = ? and dt = ?",
                (DEFAULT_PORTFOLIO_ID, today),
            )
            for row in rows:
                symbol = str(row.get("symbol", "")).strip()
                if not symbol:
                    continue
                shares = float(row.get("shares", 0) or 0)
                if shares <= 0:
                    continue
                price = float(row.get("cost", row.get("price", 0)) or 0)
                position = Position(
                    portfolio_id=DEFAULT_PORTFOLIO_ID,
                    dt=today,
                    asset=symbol,
                    shares=shares,
                    avail=float(row.get("avail", 0) or 0),
                    price=price,
                    profit=float(row.get("profit", 0) or 0),
                    mv=float(row.get("market_value", 0) or 0),
                )
                db["positions"].upsert(position.to_dict(), pk=Position.__pk__)
        except Exception as exc:
            logger.warning(f"持仓快照刷新失败: {exc}")

    def get_orders(self) -> list[dict]:
        """获取当日委托列表

        Returns:
            委托列表（字典列表）
        """
        # 不要在同步 HTTP 路径里触发 _ensure_connected() —— 那是阻塞路径，
        # 会同步启动 QMT 客户端（10+ 秒），导致 / 和 /trading 页面首次
        # 加载卡住。断线场景由 mark_disconnected → _schedule_auto_reconnect
        # 异步处理；这里只读已连接状态。
        if not self._connected or self._trader is None or self._account is None:
            return []

        try:
            xt_orders = self._trader.query_stock_orders(self._account)
            if xt_orders is None:
                return []

            orders = []
            for o in xt_orders:
                status_code = self._convert_order_status_code(o.order_status)
                qtoid = str(getattr(o, "order_remark", "") or "")
                db_order = db.get_order_by_foid(str(o.order_id))
                if db_order is not None:
                    qtoid = db_order.qtoid
                if not qtoid:
                    qtoid = str(o.order_id)
                order = {
                    "symbol": o.stock_code,
                    "name": "",
                    "side": self._convert_order_side(o.order_type),
                    "price": o.price,
                    "shares": o.order_volume,
                    "filled": o.traded_volume,
                    "status": self._status_code_to_text(status_code),
                    "status_code": status_code,
                    "time": datetime.datetime.fromtimestamp(o.order_time).strftime("%H:%M:%S"),
                    "qtoid": qtoid,
                    "foid": str(o.order_id),
                    "cid": str(getattr(o, "order_sysid", "") or ""),
                }
                orders.append(order)
                self._persist_order_snapshot(order)

            return orders

        except Exception as e:
            logger.error(f"获取委托失败: {e}")
            return []

    def get_trades(self) -> list[dict]:
        """获取当日成交列表

        Returns:
            成交列表（字典列表）
        """
        # 同 get_orders：避免在同步路径里同步 connect()。
        if not self._connected or self._trader is None or self._account is None:
            return []

        try:
            xt_trades = self._trader.query_stock_trades(self._account)
            if xt_trades is None:
                return []

            trades = []
            for t in xt_trades:
                qtoid = str(getattr(t, "order_remark", "") or "")
                db_order = db.get_order_by_foid(str(getattr(t, "order_id", "") or ""))
                if db_order is not None:
                    qtoid = db_order.qtoid
                trade = {
                    "tid": str(getattr(t, "traded_id", "") or ""),
                    "qtoid": qtoid,
                    "symbol": t.stock_code,
                    "name": "",
                    "side": self._convert_order_side(t.order_type),
                    "price": t.traded_price,
                    "shares": t.traded_volume,
                    "amount": t.traded_amount,
                    "time": datetime.datetime.fromtimestamp(t.traded_time).strftime("%H:%M:%S"),
                }
                trades.append(trade)
                self._persist_trade_snapshot(
                    trade,
                    foid=str(getattr(t, "order_id", "") or ""),
                    cid=str(getattr(t, "order_sysid", "") or ""),
                )

            return trades

        except Exception as e:
            logger.error(f"获取成交失败: {e}")
            return []

    def _convert_order_side(self, order_type: Any) -> str:
        try:
            xtconstant = _get_xtquant("xtconstant")
            buy_type = int(getattr(xtconstant, "STOCK_BUY", 23))
        except Exception:
            buy_type = 23
        return "buy" if int(order_type) == buy_type else "sell"

    def _status_code_to_text(self, status_code: int) -> str:
        status_map = {
            48: "unreported",
            49: "pending",
            50: "reported",
            51: "canceling",
            52: "partial_canceling",
            53: "partial_cancelled",
            54: "cancelled",
            55: "partial",
            56: "filled",
            57: "rejected",
        }
        return status_map.get(status_code, "unknown")

    def _convert_order_status(self, xt_status: Any) -> str:
        return self._status_code_to_text(self._convert_order_status_code(xt_status))

    def _convert_order_status_code(self, xt_status: Any) -> int:
        aliases = {
            "unreported": 48,
            "wait_reporting": 49,
            "pending": 49,
            "reported": 50,
            "reported_cancel": 51,
            "canceling": 51,
            "partsucc_cancel": 52,
            "partial_canceling": 52,
            "part_cancel": 53,
            "partial_cancelled": 53,
            "canceled": 54,
            "cancelled": 54,
            "part_succ": 55,
            "partial": 55,
            "succeeded": 56,
            "filled": 56,
            "junk": 57,
            "rejected": 57,
            "unknown": 255,
        }
        text = str(xt_status).strip().lower()
        if text in aliases:
            return aliases[text]
        try:
            code = int(text)
        except (TypeError, ValueError):
            return 255
        if 0 <= code <= 9:
            return 48 + code
        if code in {48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 255}:
            return code
        return 255

    def _persist_order_snapshot(self, order: dict) -> None:
        qtoid = str(order.get("qtoid", "")).strip()
        symbol = str(order.get("symbol", "")).strip()
        if not qtoid or not symbol:
            return
        now = datetime.datetime.now()
        tm = now
        tm_text = str(order.get("time", "")).strip()
        if tm_text:
            try:
                tm = datetime.datetime.fromisoformat(
                    f"{now.date().isoformat()} {tm_text}"
                )
            except ValueError:
                tm = now
        side_text = str(order.get("side", "buy")).strip().lower()
        side = OrderSide.BUY if side_text == "buy" else OrderSide.SELL
        status_code = self._convert_order_status_code(
            order.get("status_code", order.get("status", "unknown"))
        )
        foid = str(order.get("foid", "") or qtoid)
        db["orders"].upsert(
            Order(
                qtoid=qtoid,
                portfolio_id=DEFAULT_PORTFOLIO_ID,
                asset=symbol,
                side=side,
                shares=float(order.get("shares", 0) or 0),
                bid_type=BidType.UNKNOWN,
                tm=tm,
                price=float(order.get("price", 0) or 0),
                filled=float(order.get("filled", 0) or 0),
                foid=foid,
                status=OrderStatus(status_code),
                status_msg="",
                cid=str(order.get("cid", "") or ""),
                strategy=str(order.get("strategy_id", "") or "gateway"),
            ).to_dict(),
            pk=Order.__pk__,
        )

    def _persist_submitted_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        price: float,
        shares: int,
        qtoid: str,
        foid: str,
        strategy_id: str,
    ) -> None:
        """在 gateway 提交成功后立即建立 qtoid 映射。"""
        db["orders"].upsert(
            Order(
                qtoid=qtoid,
                portfolio_id=DEFAULT_PORTFOLIO_ID,
                asset=symbol,
                side=side,
                shares=float(shares),
                bid_type=BidType.UNKNOWN,
                tm=datetime.datetime.now(),
                price=float(price),
                filled=0.0,
                foid=foid,
                status=OrderStatus.REPORTED,
                status_msg="",
                strategy=strategy_id or "gateway",
            ).to_dict(),
            pk=Order.__pk__,
        )

    def _persist_trade_snapshot(self, trade: dict, *, foid: str, cid: str) -> None:
        """落地成交快照并维持 qtoid 关联。"""
        qtoid = str(trade.get("qtoid", "") or "").strip()
        if not qtoid and foid:
            db_order = db.get_order_by_foid(foid)
            if db_order is not None:
                qtoid = db_order.qtoid
        if not qtoid:
            return
        time_text = str(trade.get("time", "") or "").strip()
        now = datetime.datetime.now()
        tm = now
        if time_text:
            try:
                tm = datetime.datetime.fromisoformat(
                    f"{now.date().isoformat()} {time_text}"
                )
            except ValueError:
                tm = now
        side_text = str(trade.get("side", "buy")).strip().lower()
        db.insert_trade(
            Trade(
                tid=str(trade.get("tid", "") or str(uuid4())),
                portfolio_id=DEFAULT_PORTFOLIO_ID,
                qtoid=qtoid,
                foid=foid,
                asset=str(trade.get("symbol", "") or ""),
                shares=float(trade.get("shares", 0) or 0),
                price=float(trade.get("price", 0) or 0),
                amount=float(trade.get("amount", 0) or 0),
                tm=tm,
                side=OrderSide.BUY if side_text == "buy" else OrderSide.SELL,
                cid=cid,
            )
        )

    def persist_callback_trade(self, xt_trade: Any) -> None:
        """处理成交回调并将其映射回 qtoid。

        根据累计成交量与委托量对比判断部分成交 / 全部成交 (#84)。
        """
        try:
            trade = {
                "tid": str(getattr(xt_trade, "traded_id", "") or ""),
                "qtoid": str(getattr(xt_trade, "order_remark", "") or ""),
                "symbol": getattr(xt_trade, "stock_code", ""),
                "side": self._convert_order_side(getattr(xt_trade, "order_type", 23)),
                "price": float(getattr(xt_trade, "traded_price", 0) or 0),
                "shares": float(getattr(xt_trade, "traded_volume", 0) or 0),
                "amount": float(getattr(xt_trade, "traded_amount", 0) or 0),
                "time": datetime.datetime.fromtimestamp(
                    getattr(xt_trade, "traded_time", 0) or 0
                ).strftime("%H:%M:%S"),
            }
            foid = str(getattr(xt_trade, "order_id", "") or "")
            cid = str(getattr(xt_trade, "order_sysid", "") or "")
            self._persist_trade_snapshot(trade, foid=foid, cid=cid)
            db_order = db.get_order_by_foid(foid)
            if db_order is not None:
                order_volume = float(db_order.shares or 0)
                filled_volume = sum(
                    float(getattr(item, "shares", 0) or 0)
                    for item in db.get_trades_by_qtoid(db_order.qtoid)
                )
                if order_volume > 0 and filled_volume < order_volume:
                    new_status = OrderStatus.PART_SUCC
                else:
                    new_status = OrderStatus.SUCCEEDED
                db.update_order(db_order.qtoid, filled=filled_volume, status=new_status)
            self._schedule_position_snapshot()
        except Exception as e:
            logger.error(f"回调成交落库失败: {e}")

    def _schedule_position_snapshot(self) -> None:
        """在后台线程池中刷新持仓快照，避免阻塞 QMT 回调导致死锁 (#41)

        on_stock_trade / on_stock_order 回调运行在 QMT 库的内部线程中。
        refresh_positions_snapshot() 内部需要调用 self._trader.query_stock_positions()，
        这会从 QMT 回调中再次进入 QMT 库，导致死锁或挂起，并最终使整个网关无响应。

        使用 ThreadPoolExecutor(max_workers=1) 确保同一时间最多一个
        持仓刷新任务在运行，避免短时间内大量成交回报创建过多线程 (#91)。
        """
        self._position_snapshot_executor.submit(self._safe_refresh_positions_snapshot)

    def _safe_refresh_positions_snapshot(self) -> None:
        """包装 refresh_positions_snapshot，捕获并记录所有异常，避免后台线程崩溃。"""
        try:
            self.refresh_positions_snapshot()
        except Exception as exc:
            logger.warning(f"后台刷新持仓快照失败: {exc}")

    def persist_callback_order(self, xt_order: Any) -> None:
        try:
            order_time = getattr(xt_order, "order_time", None)
            if order_time:
                time_text = datetime.datetime.fromtimestamp(order_time).strftime(
                    "%H:%M:%S"
                )
            else:
                time_text = datetime.datetime.now().strftime("%H:%M:%S")
            qtoid = str(getattr(xt_order, "order_remark", "") or "")
            db_order = db.get_order_by_foid(str(getattr(xt_order, "order_id", "") or ""))
            if db_order is not None:
                qtoid = db_order.qtoid
            order = {
                "symbol": getattr(xt_order, "stock_code", ""),
                "side": self._convert_order_side(getattr(xt_order, "order_type", 23)),
                "price": float(getattr(xt_order, "price", 0) or 0),
                "shares": float(getattr(xt_order, "order_volume", 0) or 0),
                "filled": float(getattr(xt_order, "traded_volume", 0) or 0),
                "status_code": self._convert_order_status_code(
                    getattr(xt_order, "order_status", 255)
                ),
                "time": time_text,
                "qtoid": qtoid,
                "foid": str(getattr(xt_order, "order_id", "")),
                "cid": str(getattr(xt_order, "order_sysid", "") or ""),
                "strategy_id": str(getattr(xt_order, "strategy_name", "") or "gateway"),
            }
            self._persist_order_snapshot(order)
        except Exception as e:
            logger.error(f"回调委托落库失败: {e}")


# 全局交易服务实例
trade_service = TradeService()
