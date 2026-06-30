"""托盘模块单元测试。

聚焦于非 GUI 部分：
- 读 .port / .lock 工具函数
- _kill_gateway 的回退逻辑
- _wait_for_port_free 的边界

pystray 的 win32 消息循环依赖交互式桌面，CI 不能跑；这部分留
手测 / 单独 issue 跟踪。
"""
from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from qmt_gateway.tray import (
    _kill_gateway,
    _read_pid,
    _read_port,
    _wait_for_port_free,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("QMT_GATEWAY_HOME", str(tmp_path))
    return tmp_path


# ---------- _read_port ----------

def test_read_port_returns_8130_when_no_file(home: Path):
    assert _read_port() == 8130


def test_read_port_reads_value(home: Path):
    (home / ".port").write_text("8131\n", encoding="utf-8")
    assert _read_port() == 8131


def test_read_port_handles_invalid_content(home: Path):
    (home / ".port").write_text("not a number\n", encoding="utf-8")
    assert _read_port() == 8130


def test_read_port_handles_trailing_whitespace(home: Path):
    (home / ".port").write_text("  8135  \n", encoding="utf-8")
    # strip() should handle this
    assert _read_port() == 8135


# ---------- _read_pid ----------

def test_read_pid_returns_none_when_no_lock(home: Path):
    assert _read_pid() is None


def test_read_pid_reads_value(home: Path):
    (home / ".lock").write_text("12345\n", encoding="utf-8")
    assert _read_pid() == 12345


def test_read_pid_handles_invalid_content(home: Path):
    (home / ".lock").write_text("garbage\n", encoding="utf-8")
    assert _read_pid() is None


# ---------- _wait_for_port_free ----------

def test_wait_for_port_free_returns_true_for_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # 端口已经被释放
    assert _wait_for_port_free(port, timeout=1.0) is True


def test_wait_for_port_free_returns_false_when_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            assert _wait_for_port_free(port, timeout=0.5) is False
        finally:
            s.close()


# ---------- _kill_gateway ----------

def test_kill_gateway_no_lock_returns_false(home: Path):
    assert _kill_gateway() is False


def test_kill_gateway_calls_taskkill(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        assert _kill_gateway() is True
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "taskkill" in cmd
        assert "/F" in cmd
        assert "/T" in cmd
        assert "99999" in cmd


def test_kill_gateway_handles_nonzero_returncode(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="not found"
        )
        assert _kill_gateway() is False


def test_kill_gateway_handles_timeout(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch(
        "qmt_gateway.tray.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="taskkill", timeout=5),
    ):
        assert _kill_gateway() is False


def test_kill_gateway_handles_missing_taskkill(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch(
        "qmt_gateway.tray.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert _kill_gateway() is False