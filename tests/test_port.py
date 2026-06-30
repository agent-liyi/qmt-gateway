"""端口冲突检测与自动切换测试 (#49)"""

import os
import socket
from unittest.mock import patch

import pytest

from qmt_gateway.services.port import find_available_port, is_port_available


def test_is_port_available_with_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert is_port_available(port, "127.0.0.1")


def test_is_port_available_with_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        assert not is_port_available(port, "127.0.0.1")


def test_find_available_port_returns_default_when_free():
    with patch("qmt_gateway.services.port.is_port_available", return_value=True):
        assert find_available_port(default=8130) == 8130


def test_find_available_port_skips_occupied():
    call_count = 0

    def mock_available(port, host="0.0.0.0"):
        nonlocal call_count
        call_count += 1
        return port != 8130

    with patch("qmt_gateway.services.port.is_port_available", side_effect=mock_available):
        result = find_available_port(default=8130, max_tries=10)
        assert result == 8131
        assert call_count == 2


def test_find_available_port_raises_when_all_occupied():
    with patch("qmt_gateway.services.port.is_port_available", return_value=False):
        with pytest.raises(RuntimeError, match="未找到可用端口"):
            find_available_port(default=8130, max_tries=5)


def test_find_available_port_with_limited_tries():
    def mock_available(port, host="0.0.0.0"):
        return port == 8135

    with patch("qmt_gateway.services.port.is_port_available", side_effect=mock_available):
        result = find_available_port(default=8130, max_tries=10)
        assert result == 8135


def test_find_available_port_logs_all_busy_ports(caplog):
    """日志应列出所有被占用的端口，而不是只写默认端口。"""

    import io

    import loguru

    sink = io.StringIO()
    logger = loguru.logger
    handler_id = logger.add(sink, level="INFO", format="{message}")
    try:
        def mock_available(port, host="0.0.0.0"):
            return port == 8132

        with patch(
            "qmt_gateway.services.port.is_port_available",
            side_effect=mock_available,
        ):
            result = find_available_port(default=8130, max_tries=5)
    finally:
        logger.remove(handler_id)
    assert result == 8132
    output = sink.getvalue()
    assert "8130,8131" in output and "8132" in output, output
