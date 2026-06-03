"""QMT 进程管理公共工具。

提供跨模块复用的进程查询和终止功能：
- ``qmt_init_helpers`` 在 init-wizard 恢复时调用
- ``trade_service`` 在运行时重启 QMT 时调用

本模块刻意保持无状态、无外部依赖（仅 loguru + subprocess），
方便测试时 monkeypatch ``subprocess.run``。
"""

from __future__ import annotations

import subprocess

from loguru import logger

# tasklist/taskkill 输出中“进程未找到”的标志（中英文）
PROCESS_NOT_FOUND_MARKERS = (
    "没有找到进程",
    "没有找到",
    "找不到",
    "没有运行的实例",
    "no instances",
    "not found",
)


def list_process_ids(executable_name: str) -> list[int]:
    """通过 tasklist 查询指定可执行文件的进程 ID。

    Args:
        executable_name: 可执行文件名，如 ``XtItClient.exe``。

    Returns:
        匹配到的进程 ID 列表（可能为空）。
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {executable_name}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            check=False,
        )
    except Exception as exc:
        logger.warning(f"查询 {executable_name} 进程失败: {exc}")
        return []

    pids: list[int] = []
    for raw in (result.stdout or "").splitlines():
        parts = [p.strip().strip('"') for p in raw.split(",")]
        if len(parts) < 2:
            continue
        if parts[0].lower() != executable_name.lower():
            continue
        try:
            pids.append(int(parts[1]))
        except ValueError:
            continue
    return pids


def is_process_running(executable_name: str) -> bool:
    """判断指定可执行文件的进程是否在运行。"""
    return bool(list_process_ids(executable_name))


def kill_process(executable_name: str) -> str:
    """强制终止指定可执行文件的所有进程。

    Args:
        executable_name: 可执行文件名，如 ``XtItClient.exe``。

    Returns:
        - ``"terminated"``: 成功终止
        - ``"not-running"``: 本来就没有进程
        - 其他字符串: 失败原因

    Raises:
        RuntimeError: taskkill 执行失败且无法识别返回信息。
    """
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", executable_name],
            capture_output=True,
            text=False,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        logger.warning(f"调用 taskkill 失败: {exc}")
        raise RuntimeError(f"调用 taskkill 失败: {exc}") from exc

    stdout = _decode_subprocess_output(result.stdout)
    stderr = _decode_subprocess_output(result.stderr)
    combined = f"{stdout}\n{stderr}".lower()

    if result.returncode == 0:
        logger.info(f"进程已终止: {executable_name}")
        return "terminated"

    if any(marker in combined for marker in PROCESS_NOT_FOUND_MARKERS):
        logger.info(f"没有检测到运行中的进程: {executable_name}")
        return "not-running"

    error_msg = combined.strip() or f"终止进程失败，退出码: {result.returncode}"
    logger.warning(f"taskkill 返回异常: rc={result.returncode}, output={error_msg}")
    raise RuntimeError(error_msg)


def _decode_subprocess_output(raw: bytes | str) -> str:
    """解码子进程输出，优先尝试 UTF-8，回退到 GBK（Windows 中文环境）。"""
    if isinstance(raw, bytes):
        # 优先 UTF-8，失败则尝试系统默认编码（Windows 中文环境为 GBK）
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore")
    return str(raw)
