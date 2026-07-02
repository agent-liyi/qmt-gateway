"""Tests for qmt_gateway.services.port."""
import socket
import threading
import time

import pytest

from qmt_gateway.services.port import find_available_port, is_port_available


def _occupy_port(port: int) -> socket.socket:
    """Bind a socket to a port so find_available_port has to skip it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def test_is_port_available_returns_true_for_unused_port():
    assert is_port_available(18745) is True


def test_find_available_port_returns_default_when_free():
    # Use a high random port to avoid collision with anything.
    port = find_available_port(default=18746, max_tries=5)
    assert port == 18746


def test_find_available_port_skips_busy_ports():
    busy = _occupy_port(18750)
    try:
        port = find_available_port(default=18750, max_tries=5, wait_for_default_sec=0)
        assert port == 18751
    finally:
        busy.close()


def test_find_available_port_waits_for_default_to_become_free():
    """#120 重启优化：托盘重启场景下默认端口被旧进程占用，
    新 gateway 启动后应**先等**默认端口空闲（最多 N 秒），不立刻跳到下一个端口。
    """
    busy = _occupy_port(18760)
    try:
        # Schedule the busy socket to be released after 0.3s.
        def _release():
            time.sleep(0.3)
            busy.close()

        t = threading.Thread(target=_release, daemon=True)
        t.start()

        start = time.monotonic()
        port = find_available_port(default=18760, max_tries=5, wait_for_default_sec=2.0)
        elapsed = time.monotonic() - start

        assert port == 18760
        # 应该在 0.3s 附近空闲（不超过 1s）；如果走了 skip 路径会立刻返回 < 50ms。
        assert 0.2 < elapsed < 1.5, f"elapsed={elapsed:.3f}s 不在预期范围"
    finally:
        # If thread didn't run for some reason, close here.
        try:
            busy.close()
        except OSError:
            pass


def test_find_available_port_times_out_and_falls_back():
    """wait 超时后应该跳到 default+1，而不是无限等待。"""
    busy = _occupy_port(18770)

    try:
        start = time.monotonic()
        port = find_available_port(default=18770, max_tries=5, wait_for_default_sec=0.2)
        elapsed = time.monotonic() - start
        assert port == 18771
        # 0.2s 等不到 default，转 8131。必须远小于 max_tries 累加（如果 skip 全部
        # 端口会立刻返回 < 50ms；这里 18770 等了 0.2s + 18771 立刻 bind = ~0.2-0.3s）。
        assert elapsed < 1.0
    finally:
        busy.close()


def test_find_available_port_raises_when_all_busy():
    sockets = [_occupy_port(18780 + i) for i in range(5)]
    try:
        with pytest.raises(RuntimeError, match="未找到可用端口"):
            find_available_port(default=18780, max_tries=5, wait_for_default_sec=0)
    finally:
        for s in sockets:
            s.close()
