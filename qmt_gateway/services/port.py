"""端口冲突检测与自动切换

启动时检测默认端口是否可用，若被占用则依次尝试 8131-8139。
"""

import socket
import time

from loguru import logger


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """检查端口是否可用（未被监听）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(
    default: int = 8130,
    max_tries: int = 10,
    host: str = "0.0.0.0",
    wait_for_default_sec: float = 0.0,
) -> int:
    """从 default 开始尝试，找到第一个可用端口

    Args:
        default: 默认起始端口
        max_tries: 最大尝试次数
        host: 绑定地址
        wait_for_default_sec: 如果 default 端口被占用，最多等这么久
            （用于重启场景：旧 gateway 刚被 kill，OS 还没释放端口，
            重试几次通常 50-200ms 内就空闲）。等待期间**只**重试 default，
            不会因为等不到 default 就跳到 default+1——这会破坏"浏览器仍在
            8130"的前提，浏览器会看到"拒绝访问"。

    Returns:
        可用的端口号

    Raises:
        RuntimeError: 所有端口均不可用

    """
    deadline = time.monotonic() + max(float(wait_for_default_sec), 0.0)
    while True:
        if is_port_available(default, host):
            return default
        if time.monotonic() < deadline:
            time.sleep(0.05)
            continue
        # default 在 wait_for_default_sec 内仍然被占用，跳出去按 8131-8139 顺序找。
        for offset in range(1, max_tries):
            port = default + offset
            if is_port_available(port, host):
                logger.info(
                    f"端口 {default} 被占用 {wait_for_default_sec:.1f}s 后仍不可用，"
                    f"自动切换到 {port}"
                )
                return port
        raise RuntimeError(
            f"未找到可用端口 (尝试范围 {default}-{default + max_tries - 1})"
        )

