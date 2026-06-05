"""端口冲突检测与自动切换

启动时检测默认端口是否可用，若被占用则依次尝试 8131-8139。
"""

import socket

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
) -> int:
    """从 default 开始尝试，找到第一个可用端口

    Args:
        default: 默认起始端口
        max_tries: 最大尝试次数
        host: 绑定地址

    Returns:
        可用的端口号

    Raises:
        RuntimeError: 所有端口均不可用

    """
    for offset in range(max_tries):
        port = default + offset
        if is_port_available(port, host):
            if offset > 0:
                logger.info(f"端口 {default} 被占用，自动切换到 {port}")
            return port

    raise RuntimeError(
        f"未找到可用端口 (尝试范围 {default}-{default + max_tries - 1})"
    )
