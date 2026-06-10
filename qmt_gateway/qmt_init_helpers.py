"""init-wizard 专用的 QMT 路径校验与启动辅助。

设计目的：在用户尚未完成交易密码设置的情况下，也能从 init-wizard
内部完成"验证 QMT 路径是否合法"、"尝试启动 QMT 客户端进程"这两件事。
**不会**自动填密码（init 阶段用户没有输入交易密码）。

本模块刻意保持无状态、可被 import 后即调即用，方便测试时 monkeypatch
``subprocess.run`` / ``os.startfile``。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from loguru import logger

# 从共享模块 re-export，保持向后兼容
from qmt_gateway.core.process_utils import (
    is_process_running as is_qmt_process_running,
    kill_process as _kill_qmt_process,
    list_process_ids,
)

QMT_CLIENT_EXECUTABLE = "XtMiniQmt.exe"
QMT_LAUNCH_PROBE_TIMEOUT_SEC = 20.0
QMT_LAUNCH_POLL_INTERVAL_SEC = 0.5


def kill_qmt_processes(
    executable_name: str = QMT_CLIENT_EXECUTABLE,
) -> bool:
    """强制终止所有 QMT 客户端进程。

    Returns:
        成功终止（包括本来就没有进程）时返回 True；
        taskkill 失败时返回 False。
    """
    try:
        _kill_qmt_process(executable_name)
        return True
    except RuntimeError:
        return False


def resolve_qmt_executable(qmt_path: str | Path | None) -> Path:
    """根据用户填写的 qmt_path 解析出 QMT 客户端可执行文件路径。

    接受以下几种入口（#63）：

    - ``C:\\apps\\qmt\\bin.x64\\XtMiniQmt.exe``（可执行文件本体）
    - ``C:\\apps\\qmt\\bin.x64``（bin.x64 目录）
    - ``C:\\apps\\qmt\\userdata_mini``（以 userdata_mini 结尾）
    - ``C:\\apps\\qmt``（QMT 根目录，要求包含 userdata_mini 或 bin.x64）

    解析后返回 ``base_dir / bin.x64 / XtMiniQmt.exe``。
    """
    text = str(qmt_path or "").strip()
    if not text:
        raise ValueError("QMT 路径未配置")

    configured = Path(text).expanduser()
    if not configured.exists():
        raise FileNotFoundError(f"QMT 路径不存在: {configured}")

    if configured.name.lower() == "xtminiqmt.exe":
        if configured.parent.name.lower() == "bin.x64":
            base_dir = configured.parent.parent
        else:
            raise ValueError(
                f"XtMiniQmt.exe 必须位于 bin.x64 子目录下，期望路径形如 ...\\bin.x64\\XtMiniQmt.exe，得到: {configured}"
            )
    elif configured.name.lower() == "bin.x64":
        base_dir = configured.parent
    elif configured.name.lower() == "userdata_mini":
        base_dir = configured.parent
    elif (configured / "userdata_mini").is_dir():
        base_dir = configured
    elif (configured / "bin.x64" / QMT_CLIENT_EXECUTABLE).is_file():
        base_dir = configured
    else:
        raise ValueError(
            "QMT 路径不正确：应包含 userdata_mini、bin.x64\\XtMiniQmt.exe 或指向 QMT 根目录"
        )

    executable = base_dir / "bin.x64" / QMT_CLIENT_EXECUTABLE
    if not executable.is_file():
        raise FileNotFoundError(f"未找到 QMT 客户端可执行文件: {executable}")
    return executable


def is_qmt_process_running(executable_name: str = QMT_CLIENT_EXECUTABLE) -> bool:
    """判断 QMT 客户端进程当前是否在运行。"""
    return bool(list_process_ids(executable_name))


def launch_qmt_client(
    executable: Path,
    *,
    probe_timeout: float = QMT_LAUNCH_PROBE_TIMEOUT_SEC,
    poll_interval: float = QMT_LAUNCH_POLL_INTERVAL_SEC,
) -> bool:
    """启动 QMT 客户端进程，等待新进程出现后返回。

    Args:
        executable: QMT 客户端可执行文件路径。
        probe_timeout: 等待新进程出现的最长时间（秒）。
        poll_interval: 轮询间隔（秒）。

    Returns:
        出现新进程时返回 True；超时未出现则返回 False（不抛异常）。
    """
    if not executable.is_file():
        logger.error(f"QMT 客户端不存在: {executable}")
        return False

    before_pids = set(list_process_ids(executable.name))
    logger.info(f"尝试启动 QMT 客户端: path={executable}")

    try:
        os.startfile(str(executable), cwd=str(executable.parent))
    except TypeError:
        try:
            os.startfile(str(executable))
        except Exception as exc:
            logger.error(f"启动 QMT 客户端失败: {exc}")
            return False
    except Exception as exc:
        logger.error(f"启动 QMT 客户端失败: {exc}")
        return False

    deadline = time.monotonic() + max(float(probe_timeout), 1.0)
    while time.monotonic() < deadline:
        current_pids = set(list_process_ids(executable.name))
        new_pids = current_pids - before_pids
        if new_pids:
            logger.info(f"QMT 客户端已启动: new_pids={new_pids}")
            return True
        time.sleep(max(float(poll_interval), 0.1))

    logger.warning(f"未在 {probe_timeout:.1f}s 内观测到新 QMT 进程: image={executable.name}")
    return False


def summarize_qmt_launch_failure(error: Optional[str]) -> str:
    """把 launch_qmt_client 的失败原因整理成给用户看的提示。"""
    base = "未能自动启动 QMT 客户端"
    if error:
        return f"{base}：{error}"
    return base
